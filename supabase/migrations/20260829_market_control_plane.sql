-- Mirrors the Trader Bot control-plane migrations applied to the dedicated
-- Supabase project. Raw market observations remain outside this relational plane.

create extension if not exists pgcrypto;

create table if not exists public.market_providers (
  id uuid primary key default gen_random_uuid(),
  provider_key text not null unique,
  display_name text not null,
  status text not null default 'ACTIVE' check (status in ('ACTIVE','DEGRADED','BLOCKED','RETIRED')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.market_instruments (
  id uuid primary key default gen_random_uuid(),
  instrument_code integer unique,
  canonical_symbol text not null unique,
  display_name text not null,
  asset_class text not null check (asset_class in ('FOREX','CRYPTO','METAL','COMMODITY','EQUITY','INDEX')),
  venue text,
  provider_id uuid references public.market_providers(id),
  provider_symbol text,
  timezone text not null default 'UTC',
  culture_version integer not null default 1 check (culture_version > 0),
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(provider_id, provider_symbol)
);

create table if not exists public.market_series (
  id uuid primary key default gen_random_uuid(),
  instrument_id uuid not null references public.market_instruments(id) on delete cascade,
  timeframe text not null,
  offer_side text not null check (offer_side in ('BID','ASK','MID','TRADE')),
  native_interval text,
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(instrument_id, timeframe, offer_side)
);

create table if not exists public.market_refresh_policies (
  series_id uuid primary key references public.market_series(id) on delete cascade,
  refresh_seconds integer not null check (refresh_seconds > 0),
  freshness_warn_seconds integer not null check (freshness_warn_seconds > 0),
  freshness_block_seconds integer not null check (freshness_block_seconds >= freshness_warn_seconds),
  max_backfill_seconds integer not null check (max_backfill_seconds > 0),
  max_batch_rows integer not null check (max_batch_rows > 0),
  updated_at timestamptz not null default now()
);

create table if not exists public.market_series_health (
  series_id uuid primary key references public.market_series(id) on delete cascade,
  state text not null default 'BLOCKED' check (state in ('FRESH','WATCH','STALE','BLOCKED')),
  latest_observed_at timestamptz,
  latest_data_at timestamptz,
  row_count bigint not null default 0 check (row_count >= 0),
  quality_pass boolean not null default false,
  contiguous boolean not null default false,
  source_hash text,
  provider_status text,
  reason text,
  checked_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.market_refresh_runs (
  id uuid primary key default gen_random_uuid(),
  series_id uuid not null references public.market_series(id) on delete cascade,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'RUNNING' check (status in ('RUNNING','SUCCEEDED','FAILED','PARTIAL','BLOCKED')),
  requested_from timestamptz,
  requested_to timestamptz,
  received_rows integer not null default 0 check (received_rows >= 0),
  stored_rows integer not null default 0 check (stored_rows >= 0),
  failure_reason text
);

create table if not exists public.market_knowledge_scopes (
  id uuid primary key default gen_random_uuid(),
  instrument_id uuid not null references public.market_instruments(id) on delete cascade,
  venue text,
  culture_version integer not null check (culture_version > 0),
  evidence_count bigint not null default 0 check (evidence_count >= 0),
  confidence numeric(8,6) check (confidence is null or (confidence >= 0 and confidence <= 1)),
  observation_started_at timestamptz,
  observation_ended_at timestamptz,
  source_fingerprint text,
  review_after timestamptz,
  status text not null default 'BUILDING' check (status in ('BUILDING','VALIDATED','WATCH','EXPIRED','BLOCKED')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.market_relationship_evidence (
  id uuid primary key default gen_random_uuid(),
  source_instrument_id uuid not null references public.market_instruments(id) on delete cascade,
  target_instrument_id uuid not null references public.market_instruments(id) on delete cascade,
  lag_seconds integer not null,
  regime_scope text,
  sample_size bigint not null default 0 check (sample_size >= 0),
  out_of_sample boolean not null default false,
  cost_aware boolean not null default false,
  stability_score numeric(8,6) check (stability_score is null or (stability_score >= 0 and stability_score <= 1)),
  status text not null default 'REJECTED' check (status in ('PROPOSED','WATCH','APPROVED','REJECTED','EXPIRED')),
  reviewed_at timestamptz,
  unique(source_instrument_id, target_instrument_id, lag_seconds, regime_scope)
);

create index if not exists market_instruments_asset_class_idx on public.market_instruments(asset_class);
create index if not exists market_series_instrument_idx on public.market_series(instrument_id);
create index if not exists market_refresh_runs_series_started_idx on public.market_refresh_runs(series_id, started_at desc);
create index if not exists market_knowledge_scopes_instrument_idx on public.market_knowledge_scopes(instrument_id);
create index if not exists market_relationship_evidence_source_target_idx on public.market_relationship_evidence(source_instrument_id, target_instrument_id);

alter table public.market_providers enable row level security;
alter table public.market_instruments enable row level security;
alter table public.market_series enable row level security;
alter table public.market_refresh_policies enable row level security;
alter table public.market_series_health enable row level security;
alter table public.market_refresh_runs enable row level security;
alter table public.market_knowledge_scopes enable row level security;
alter table public.market_relationship_evidence enable row level security;

create or replace function public.set_updated_at() returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

 drop trigger if exists market_providers_set_updated_at on public.market_providers;
create trigger market_providers_set_updated_at before update on public.market_providers for each row execute function public.set_updated_at();
drop trigger if exists market_instruments_set_updated_at on public.market_instruments;
create trigger market_instruments_set_updated_at before update on public.market_instruments for each row execute function public.set_updated_at();
drop trigger if exists market_series_set_updated_at on public.market_series;
create trigger market_series_set_updated_at before update on public.market_series for each row execute function public.set_updated_at();
drop trigger if exists market_refresh_policies_set_updated_at on public.market_refresh_policies;
create trigger market_refresh_policies_set_updated_at before update on public.market_refresh_policies for each row execute function public.set_updated_at();
drop trigger if exists market_series_health_set_updated_at on public.market_series_health;
create trigger market_series_health_set_updated_at before update on public.market_series_health for each row execute function public.set_updated_at();
drop trigger if exists market_knowledge_scopes_set_updated_at on public.market_knowledge_scopes;
create trigger market_knowledge_scopes_set_updated_at before update on public.market_knowledge_scopes for each row execute function public.set_updated_at();
