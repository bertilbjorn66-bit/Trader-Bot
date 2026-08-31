-- Deterministic provider-replay coverage controls.
-- Raw bars remain disabled. This migration only stores compact replay windows,
-- claims, and evidence-derived coverage state.

create table if not exists public.market_replay_windows (
  id uuid primary key default gen_random_uuid(),
  series_id uuid not null references public.market_series(id) on delete cascade,
  requested_from timestamptz not null,
  requested_to timestamptz not null,
  status text not null default 'READY' check (status in ('READY','IN_FLIGHT','COMPLETE','ERROR')),
  attempts integer not null default 0 check (attempts >= 0),
  request_id bigint,
  last_error text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  check (requested_to > requested_from),
  unique (series_id, requested_from, requested_to)
);

create index if not exists market_replay_windows_claim_idx
  on public.market_replay_windows(status, requested_from, created_at);

create table if not exists public.market_replay_coverage (
  series_id uuid primary key references public.market_series(id) on delete cascade,
  required_from timestamptz,
  required_to timestamptz,
  covered_from timestamptz,
  covered_to timestamptz,
  covered_seconds bigint not null default 0,
  required_seconds bigint not null default 0,
  uncovered_seconds bigint not null default 0,
  complete boolean not null default false,
  complete_windows bigint not null default 0,
  updated_at timestamptz not null default now()
);

alter table public.market_replay_windows enable row level security;
alter table public.market_replay_coverage enable row level security;
revoke all on public.market_replay_windows from anon, authenticated;
revoke all on public.market_replay_coverage from anon, authenticated;
grant all on public.market_replay_windows to service_role;
grant all on public.market_replay_coverage to service_role;

create or replace function public.seed_replay_windows(p_limit integer default 66)
returns bigint
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  r record;
  v_from timestamptz;
  v_to timestamptz;
  v_target timestamptz;
  v_chunk interval;
  v_count bigint := 0;
begin
  if p_limit is null or p_limit < 1 then
    raise exception 'invalid_limit';
  end if;
  for r in
    select s.id, s.timeframe, p.provider_key, h.backfill_cursor_at,
           h.backfill_target_at
    from public.market_series s
    join public.market_series_health h on h.series_id = s.id
    join public.market_instruments i on i.id = s.instrument_id
    join public.market_providers p on p.id = i.provider_id
    where s.enabled = true
      and s.generation_mode = 'DIRECT'
      and p.provider_key in ('BINANCE','DUKASCOPY')
      and coalesce(h.research_eligible,false) = false
    order by h.backfill_cursor_at nulls first, s.id
  loop
    v_from := coalesce(r.backfill_cursor_at,
      case when r.provider_key = 'DUKASCOPY' then '2020-01-01T00:00:00Z'::timestamptz
           when r.timeframe = '1m' then '2026-03-01T00:00:00Z'::timestamptz
           when r.timeframe = '1s' then '2026-08-22T00:00:00Z'::timestamptz
           else '2026-03-01T00:00:00Z'::timestamptz end);
    v_target := coalesce(r.backfill_target_at, now());
    v_chunk := case
      when r.provider_key = 'DUKASCOPY' then interval '31 days'
      when r.timeframe = '1m' then interval '3 days'
      when r.timeframe = '1s' then interval '30 minutes'
      else interval '1 day'
    end;
    if v_from < v_target then
      v_to := least(v_from + v_chunk, v_target);
      insert into public.market_replay_windows(series_id, requested_from, requested_to)
      values (r.id, v_from, v_to)
      on conflict (series_id, requested_from, requested_to) do nothing;
      if found then
        v_count := v_count + 1;
      end if;
    end if;
    if v_count >= p_limit then
      exit;
    end if;
  end loop;
  return v_count;
end;
$$;

revoke all on function public.seed_replay_windows(integer) from public, anon, authenticated;
grant execute on function public.seed_replay_windows(integer) to service_role;

create or replace function public.replay_coverage_status(
  p_series_id uuid,
  p_required_from timestamptz,
  p_required_to timestamptz
)
returns jsonb
language sql
security definer
set search_path = pg_catalog, public
as $$
with eligible as (
  select greatest(e.requested_from, p_required_from) as a,
         least(e.requested_to, p_required_to) as b
  from public.market_replay_evidence e
  where e.series_id = p_series_id
    and e.continuity_state = 'COMPLETE'
    and e.requested_to > e.requested_from
    and e.received_rows > 0
    and length(e.source_hash) = 64
    and length(e.evidence_hash) = 64
), bounded as (
  select a,b from eligible where b > a
), ordered as (
  select a,b,
         max(b) over(order by a,b rows between unbounded preceding and 1 preceding) as prior_end
  from bounded
), grouped as (
  select a,b,
         sum(case when prior_end is null or a > prior_end then 1 else 0 end)
         over(order by a,b rows unbounded preceding) as grp
  from ordered
), merged as (
  select min(a) as a, max(b) as b
  from grouped
  group by grp
), stats as (
  select coalesce(sum(extract(epoch from (b-a)))::bigint,0) as covered_seconds,
         count(*)::bigint as complete_windows,
         min(a) as covered_from,
         max(b) as covered_to
  from merged
)
select jsonb_build_object(
  'series_id', p_series_id,
  'required_from', p_required_from,
  'required_to', p_required_to,
  'required_seconds', greatest(0,extract(epoch from (p_required_to-p_required_from))::bigint),
  'covered_seconds', s.covered_seconds,
  'uncovered_seconds', greatest(0,extract(epoch from (p_required_to-p_required_from))::bigint-s.covered_seconds),
  'covered_from', s.covered_from,
  'covered_to', s.covered_to,
  'complete_windows', s.complete_windows,
  'complete', s.covered_seconds >= greatest(0,extract(epoch from (p_required_to-p_required_from))::bigint)
)
from stats s;
$$;

revoke all on function public.replay_coverage_status(uuid,timestamptz,timestamptz) from public, anon, authenticated;
grant execute on function public.replay_coverage_status(uuid,timestamptz,timestamptz) to service_role;

create or replace function public.refresh_replay_coverage(
  p_series_id uuid,
  p_required_from timestamptz,
  p_required_to timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v jsonb;
begin
  v := public.replay_coverage_status(p_series_id,p_required_from,p_required_to);
  insert into public.market_replay_coverage(
    series_id, required_from, required_to, covered_from, covered_to,
    covered_seconds, required_seconds, uncovered_seconds, complete,
    complete_windows, updated_at
  )
  values (
    p_series_id, p_required_from, p_required_to,
    nullif(v->>'covered_from','')::timestamptz,
    nullif(v->>'covered_to','')::timestamptz,
    (v->>'covered_seconds')::bigint,
    (v->>'required_seconds')::bigint,
    (v->>'uncovered_seconds')::bigint,
    (v->>'complete')::boolean,
    (v->>'complete_windows')::bigint,
    now()
  )
  on conflict(series_id) do update set
    required_from=excluded.required_from,
    required_to=excluded.required_to,
    covered_from=excluded.covered_from,
    covered_to=excluded.covered_to,
    covered_seconds=excluded.covered_seconds,
    required_seconds=excluded.required_seconds,
    uncovered_seconds=excluded.uncovered_seconds,
    complete=excluded.complete,
    complete_windows=excluded.complete_windows,
    updated_at=excluded.updated_at;
  return v;
end;
$$;

revoke all on function public.refresh_replay_coverage(uuid,timestamptz,timestamptz) from public, anon, authenticated;
grant execute on function public.refresh_replay_coverage(uuid,timestamptz,timestamptz) to service_role;
