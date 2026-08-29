-- Trader Bot market-data runtime controls.
-- Assumes the existing market control-plane tables from
-- create_market_control_plane_v2 already exist.
-- Secrets are provisioned separately in Supabase Vault and never stored here.

alter table public.market_instruments
  add column if not exists access_route text not null default 'UNVERIFIED',
  add column if not exists datafeed_symbol text,
  add column if not exists price_scale integer;

alter table public.market_series_health
  add column if not exists backfill_cursor_at timestamptz,
  add column if not exists backfill_target_at timestamptz,
  add column if not exists earliest_data_at timestamptz,
  add column if not exists quality_state text not null default 'UNASSESSED',
  add column if not exists quality_checked_at timestamptz,
  add column if not exists quality_reason text,
  add column if not exists research_eligible boolean not null default false,
  add column if not exists max_gap_seconds bigint,
  add column if not exists duplicate_timestamp_count bigint not null default 0;

alter table public.market_refresh_policies
  add column if not exists minimum_research_rows integer not null default 1000;

alter table public.market_refresh_runs
  add column if not exists instrument_id uuid references public.market_instruments(id) on delete cascade;

create table if not exists bot.market_series_bars (
  id bigint generated always as identity primary key,
  series_id uuid not null references public.market_series(id) on delete cascade,
  instrument_id uuid not null references public.market_instruments(id) on delete cascade,
  timeframe text not null,
  offer_side text not null,
  opened_at timestamptz not null,
  open numeric not null,
  high numeric not null,
  low numeric not null,
  close numeric not null,
  volume numeric,
  trade_count bigint,
  source text not null,
  source_hash text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint market_series_bars_ohlc_valid
    check (high >= greatest(open, close, low) and low <= least(open, close, high)),
  constraint market_series_bars_unique
    unique (series_id, opened_at)
);

create index if not exists market_series_bars_lookup_idx
  on bot.market_series_bars (instrument_id, timeframe, offer_side, opened_at desc);

alter table bot.market_series_bars enable row level security;
revoke all on table bot.market_series_bars from anon, authenticated;

update public.market_refresh_runs r
set instrument_id = s.instrument_id
from public.market_series s
where r.instrument_id is null and r.series_id = s.id;

create or replace function public.set_market_refresh_run_instrument()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  if new.instrument_id is null then
    select instrument_id into new.instrument_id
    from public.market_series
    where id = new.series_id;
  end if;
  if new.instrument_id is null then
    raise exception 'market_refresh_run_series_not_mapped';
  end if;
  return new;
end;
$$;

revoke all on function public.set_market_refresh_run_instrument() from public, anon, authenticated;
grant execute on function public.set_market_refresh_run_instrument() to service_role;

drop trigger if exists trg_market_refresh_run_instrument on public.market_refresh_runs;
create trigger trg_market_refresh_run_instrument
before insert on public.market_refresh_runs
for each row execute function public.set_market_refresh_run_instrument();

create unique index if not exists market_refresh_runs_one_running_per_series_idx
  on public.market_refresh_runs(series_id)
  where status = 'RUNNING';

create unique index if not exists market_refresh_runs_one_running_per_instrument_idx
  on public.market_refresh_runs(instrument_id)
  where status = 'RUNNING';

create index if not exists market_refresh_runs_instrument_started_idx
  on public.market_refresh_runs(instrument_id, started_at desc);

create or replace function public.upsert_market_series_bars(p_rows jsonb)
returns jsonb
language sql
security definer
set search_path = pg_catalog, public, bot
as $$
with rows as (
  select
    (r->>'series_id')::uuid series_id,
    (r->>'instrument_id')::uuid instrument_id,
    r->>'timeframe' timeframe,
    r->>'offer_side' offer_side,
    (r->>'opened_at')::timestamptz opened_at,
    (r->>'open')::numeric open,
    (r->>'high')::numeric high,
    (r->>'low')::numeric low,
    (r->>'close')::numeric close,
    nullif(r->>'volume','')::numeric volume,
    nullif(r->>'trade_count','')::bigint trade_count,
    coalesce(r->>'source','unknown') source,
    nullif(r->>'source_hash','') source_hash,
    coalesce(r->'metadata','{}'::jsonb) metadata
  from jsonb_array_elements(p_rows) r
), inserted as (
  insert into bot.market_series_bars (
    series_id, instrument_id, timeframe, offer_side, opened_at,
    open, high, low, close, volume, trade_count,
    source, source_hash, metadata
  )
  select
    series_id, instrument_id, timeframe, offer_side, opened_at,
    open, high, low, close, volume, trade_count,
    source, source_hash, metadata
  from rows
  on conflict (series_id, opened_at) do nothing
  returning 1
)
select jsonb_build_object('inserted', count(*)::int)
from inserted;
$$;

revoke all on function public.upsert_market_series_bars(jsonb) from public, anon, authenticated;
grant execute on function public.upsert_market_series_bars(jsonb) to service_role;

create or replace function public.validate_market_refresh_token(p_token text)
returns boolean
language sql
security definer
set search_path = pg_catalog, public, vault
as $$
select exists (
  select 1
  from vault.decrypted_secrets
  where name = 'market_refresh_token'
    and decrypted_secret = p_token
);
$$;

revoke all on function public.validate_market_refresh_token(text) from public, anon, authenticated;
grant execute on function public.validate_market_refresh_token(text) to service_role;

create or replace function public.reap_stale_market_refresh_runs(p_max_age_seconds integer default 180)
returns integer
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_count integer;
begin
  update public.market_refresh_runs
  set status = 'FAILED',
      finished_at = now(),
      failure_reason = 'stale_run_reaped'
  where status = 'RUNNING'
    and started_at < now() - make_interval(secs => p_max_age_seconds);
  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

revoke all on function public.reap_stale_market_refresh_runs(integer) from public, anon, authenticated;
grant execute on function public.reap_stale_market_refresh_runs(integer) to service_role;

create or replace function public.audit_market_series(
  p_series_id uuid,
  p_timeframe text,
  p_asset_class text,
  p_min_rows bigint default 100
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public, bot
as $$
declare
  v_step bigint;
  v_max_allowed bigint;
  v_rows bigint;
  v_bad_ohlc bigint;
  v_duplicate bigint;
  v_max_gap bigint;
  v_first timestamptz;
  v_last timestamptz;
  v_quality text;
  v_reason text;
  v_eligible boolean;
  v_min_rows bigint;
begin
  v_step := case p_timeframe
    when '1s' then 1
    when '1m' then 60
    when '5m' then 300
    when '15m' then 900
    when '1h' then 3600
    when '4h' then 14400
    when '1d' then 86400
    else 0 end;
  if v_step = 0 then raise exception 'unsupported_timeframe:%', p_timeframe; end if;
  v_min_rows := coalesce(
    (select minimum_research_rows from public.market_refresh_policies where series_id = p_series_id),
    p_min_rows
  );
  v_max_allowed := case upper(p_asset_class)
    when 'CRYPTO' then v_step * 2
    when 'FOREX' then greatest(v_step * 3, 259200)
    when 'METAL' then greatest(v_step * 3, 259200)
    when 'COMMODITY' then greatest(v_step * 3, 259200)
    when 'EQUITY' then greatest(v_step * 3, 604800)
    when 'INDEX' then greatest(v_step * 3, 604800)
    else v_step * 2 end;
  with ordered as (
    select opened_at, open, high, low, close,
           lag(opened_at) over(order by opened_at) prev_at
    from bot.market_series_bars
    where series_id = p_series_id
    order by opened_at desc
    limit 5000
  ), stats as (
    select count(*) rows,
           count(*) filter(where high < greatest(open, close, low)
                             or low > least(open, close, high)) bad_ohlc,
           0::bigint duplicate_count,
           coalesce(max(extract(epoch from(opened_at - prev_at))),0)::bigint max_gap,
           min(opened_at) first_at,
           max(opened_at) last_at
    from ordered
  )
  select rows, bad_ohlc, duplicate_count, max_gap, first_at, last_at
  into v_rows, v_bad_ohlc, v_duplicate, v_max_gap, v_first, v_last
  from stats;
  if v_rows = 0 then
    v_quality := 'INSUFFICIENT_DATA'; v_reason := 'no_rows'; v_eligible := false;
  elsif v_rows < v_min_rows then
    v_quality := 'INSUFFICIENT_DATA'; v_reason := 'minimum_research_rows_not_met'; v_eligible := false;
  elsif v_bad_ohlc > 0 then
    v_quality := 'FAIL'; v_reason := 'invalid_ohlc'; v_eligible := false;
  elsif v_max_gap > v_max_allowed then
    v_quality := 'FAIL'; v_reason := 'unexpected_gap'; v_eligible := false;
  else
    v_quality := 'PASS'; v_reason := 'quality_and_maturity_pass'; v_eligible := true;
  end if;
  update public.market_series_health
  set quality_state = v_quality,
      quality_checked_at = now(),
      quality_reason = v_reason,
      research_eligible = v_eligible,
      max_gap_seconds = v_max_gap,
      duplicate_timestamp_count = v_duplicate,
      updated_at = now()
  where series_id = p_series_id;
  return jsonb_build_object(
    'series_id', p_series_id,
    'rows', v_rows,
    'minimum_research_rows', v_min_rows,
    'bad_ohlc', v_bad_ohlc,
    'max_gap_seconds', v_max_gap,
    'quality_state', v_quality,
    'research_eligible', v_eligible,
    'first_data_at', v_first,
    'last_data_at', v_last,
    'reason', v_reason
  );
end;
$$;

revoke all on function public.audit_market_series(uuid, text, text, bigint) from public, anon, authenticated;
grant execute on function public.audit_market_series(uuid, text, text, bigint) to service_role;

create or replace function public.audit_market_series_batch(p_limit integer default 25)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public, bot
as $$
declare
  r record;
  v_results jsonb := '[]'::jsonb;
  v_limit integer := greatest(1, least(coalesce(p_limit, 25), 100));
begin
  for r in
    select s.id, i.asset_class, s.timeframe
    from public.market_series s
    join public.market_instruments i on i.id = s.instrument_id
    join public.market_series_health h on h.series_id = s.id
    where h.row_count > 0
    order by h.quality_checked_at nulls first, h.quality_checked_at asc
    limit v_limit
  loop
    v_results := v_results || jsonb_build_array(
      public.audit_market_series(r.id, r.timeframe, r.asset_class, 100)
    );
  end loop;
  return jsonb_build_object('audited', jsonb_array_length(v_results), 'results', v_results);
end;
$$;

revoke all on function public.audit_market_series_batch(integer) from public, anon, authenticated;
grant execute on function public.audit_market_series_batch(integer) to service_role;

update public.market_refresh_policies rp
set minimum_research_rows = case s.timeframe
  when '1s' then 10000
  when '1m' then 5000
  when '5m' then 1000
  when '15m' then 1000
  when '1h' then 500
  when '4h' then 500
  when '1d' then 200
  else 1000 end,
    updated_at = now()
from public.market_series s
where s.id = rp.series_id;
