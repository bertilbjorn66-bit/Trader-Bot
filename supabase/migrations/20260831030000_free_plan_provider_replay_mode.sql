-- Free-plan market-data operating mode.
-- Raw market bars are not a durable warehouse. Historical research must use a
-- provider-replay path and keep only compact control/evidence state in Postgres.
--
-- This migration intentionally does NOT enable RLS on legacy bot tables because
-- those tables need explicit application policies before RLS can be enabled.

insert into public.market_storage_policy(key, enabled, updated_at)
values ('persist_raw_market_bars', false, now())
on conflict (key) do update
set enabled = excluded.enabled,
    updated_at = now();

-- Never allow derived or blocked-source series to remain enabled when their
-- required raw base is deliberately absent.
update public.market_series
set enabled = false,
    updated_at = now()
where generation_mode in ('DERIVED', 'BLOCKED_SOURCE_PENDING');

update public.market_series_health h
set state = 'BLOCKED',
    quality_pass = false,
    research_eligible = false,
    quality_state = 'BLOCKED',
    quality_reason = 'provider_replay_required_raw_storage_disabled',
    reason = 'provider_replay_required_raw_storage_disabled',
    updated_at = now()
where not exists (
  select 1
  from public.market_series s
  where s.id = h.series_id
    and s.enabled = true
    and s.generation_mode = 'DIRECT'
);

create or replace function public.guard_market_series_bars_storage()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
  if not coalesce((select enabled
                   from public.market_storage_policy
                   where key = 'persist_raw_market_bars'), false) then
    return null;
  end if;

  if pg_database_size(current_database()) > 450 * 1024 * 1024 then
    return null;
  end if;

  return new;
end;
$$;

-- Recreate the trigger idempotently so the fail-closed guard is always present.
drop trigger if exists trg_market_series_bars_storage_guard on bot.market_series_bars;
create trigger trg_market_series_bars_storage_guard
before insert on bot.market_series_bars
for each row
execute function public.guard_market_series_bars_storage();

-- Preserve the explicit no-raw-storage policy even after a database reset.
revoke all on function public.guard_market_series_bars_storage() from public, anon, authenticated;

-- Historical control-plane schedulers that depend on the removed raw-bar
-- warehouse must not restart automatically. Re-enable them only after the
-- provider-replay research path is production-ready.
do $$
begin
  if to_regprocedure('cron.unschedule(bigint)') is not null then
    begin perform cron.unschedule(5); exception when others then null; end;
    begin perform cron.unschedule(18); exception when others then null; end;
    begin perform cron.unschedule(23); exception when others then null; end;
    begin perform cron.unschedule(29); exception when others then null; end;
  end if;
end
$$;
