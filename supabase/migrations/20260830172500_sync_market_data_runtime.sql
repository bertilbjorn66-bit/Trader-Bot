-- Keep the live market-data control plane reproducible.
-- No credentials or raw market observations belong in source control.

do $$
declare
  r record;
begin
  for r in
    select p.oid::regprocedure::text as signature
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'market_series_is_generic_refreshable'
  loop
    execute format(
      'alter function %s set search_path = pg_catalog, public',
      r.signature
    );
  end loop;
end
$$;

-- Remove the temporary wrapper schedule if present, then keep a single
-- scheduled raw-datafeed lane for Dukascopy CFD/metals/commodity/FX series.
select cron.unschedule('dukascopy-datafeed-worker-every-minute');

select cron.schedule(
  'dukascopy-datafeed-worker-every-minute',
  '* * * * *',
  $cron$
  select net.http_post(
    url := (select decrypted_secret from vault.decrypted_secrets where name = 'project_url')
      || '/functions/v1/dukascopy-datafeed-worker',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'x-refresh-token',
      (select decrypted_secret from vault.decrypted_secrets where name = 'market_refresh_token')
    ),
    body := jsonb_build_object('triggered_at', now()),
    timeout_milliseconds := 60000
  );
  $cron$
);
