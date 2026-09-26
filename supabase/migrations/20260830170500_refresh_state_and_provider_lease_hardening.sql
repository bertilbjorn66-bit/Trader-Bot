-- Records the production refresh state-machine and provider-lease hardening.
-- No secrets, tokens, provider credentials, or raw market data are included.

CREATE TABLE IF NOT EXISTS public.market_worker_leases (
  worker_key text PRIMARY KEY,
  owner_id uuid NOT NULL,
  acquired_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL
);

ALTER TABLE public.market_worker_leases ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.market_worker_leases FROM anon, authenticated;
DROP POLICY IF EXISTS market_worker_leases_service_only ON public.market_worker_leases;
CREATE POLICY market_worker_leases_service_only
  ON public.market_worker_leases
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

CREATE OR REPLACE FUNCTION public.acquire_market_worker_lease(
  p_worker_key text,
  p_owner_id uuid,
  p_ttl_seconds integer DEFAULT 1800
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  acquired boolean := false;
BEGIN
  INSERT INTO public.market_worker_leases(worker_key, owner_id, acquired_at, expires_at)
  VALUES (
    p_worker_key,
    p_owner_id,
    now(),
    now() + make_interval(secs => greatest(30, least(p_ttl_seconds, 3600)))
  )
  ON CONFLICT (worker_key) DO UPDATE
    SET owner_id = excluded.owner_id,
        acquired_at = excluded.acquired_at,
        expires_at = excluded.expires_at
  WHERE public.market_worker_leases.expires_at < now()
  RETURNING true INTO acquired;
  RETURN coalesce(acquired, false);
END;
$$;

REVOKE ALL ON FUNCTION public.acquire_market_worker_lease(text, uuid, integer)
  FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.acquire_market_worker_lease(text, uuid, integer)
  TO service_role;

CREATE OR REPLACE FUNCTION public.release_market_worker_lease(
  p_worker_key text,
  p_owner_id uuid
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  removed integer;
BEGIN
  DELETE FROM public.market_worker_leases
   WHERE worker_key = p_worker_key
     AND owner_id = p_owner_id;
  GET DIAGNOSTICS removed = ROW_COUNT;
  RETURN removed = 1;
END;
$$;

REVOKE ALL ON FUNCTION public.release_market_worker_lease(text, uuid)
  FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.release_market_worker_lease(text, uuid)
  TO service_role;

CREATE OR REPLACE FUNCTION public.claim_market_refresh_run(
  p_series_id uuid,
  p_instrument_id uuid,
  p_started_at timestamptz,
  p_requested_from timestamptz,
  p_requested_to timestamptz
) RETURNS TABLE(run_id uuid, claimed boolean, reason text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_id uuid := gen_random_uuid();
  v_worker_key text;
  v_ttl integer;
  v_claimed boolean;
  v_provider text;
  v_generation text;
  v_timeframe text;
BEGIN
  SELECT p.provider_key, s.generation_mode, s.timeframe
    INTO v_provider, v_generation, v_timeframe
    FROM public.market_series s
    JOIN public.market_instruments i ON i.id = s.instrument_id
    JOIN public.market_providers p ON p.id = i.provider_id
   WHERE s.id = p_series_id
     AND i.id = p_instrument_id;

  IF v_generation = 'DIRECT' AND v_timeframe = '1m'
     AND v_provider IN ('DUKASCOPY', 'BINANCE') THEN
    v_worker_key := CASE WHEN v_provider = 'DUKASCOPY'
                         THEN 'DUKASCOPY_BASE'
                         ELSE 'BINANCE_BASE' END;
    v_ttl := CASE WHEN v_provider = 'DUKASCOPY' THEN 3600 ELSE 1200 END;

    SELECT public.acquire_market_worker_lease(v_worker_key, v_id, v_ttl)
      INTO v_claimed;
    IF NOT coalesce(v_claimed, false) THEN
      RETURN QUERY SELECT null::uuid, false, 'provider_lane_busy';
      RETURN;
    END IF;
  END IF;

  IF EXISTS (
    SELECT 1 FROM public.market_refresh_runs
     WHERE series_id = p_series_id AND status = 'RUNNING'
  ) THEN
    IF v_worker_key IS NOT NULL THEN
      PERFORM public.release_market_worker_lease(v_worker_key, v_id);
    END IF;
    RETURN QUERY SELECT null::uuid, false, 'series_busy';
    RETURN;
  END IF;

  IF EXISTS (
    SELECT 1 FROM public.market_refresh_runs
     WHERE instrument_id = p_instrument_id AND status = 'RUNNING'
  ) THEN
    IF v_worker_key IS NOT NULL THEN
      PERFORM public.release_market_worker_lease(v_worker_key, v_id);
    END IF;
    RETURN QUERY SELECT null::uuid, false, 'instrument_busy';
    RETURN;
  END IF;

  INSERT INTO public.market_refresh_runs(
    id, series_id, instrument_id, started_at, status,
    requested_from, requested_to, received_rows, stored_rows
  )
  VALUES (
    v_id, p_series_id, p_instrument_id, p_started_at, 'RUNNING',
    p_requested_from, p_requested_to, 0, 0
  );

  RETURN QUERY SELECT v_id, true, 'claimed';
EXCEPTION
  WHEN unique_violation THEN
    IF v_worker_key IS NOT NULL THEN
      PERFORM public.release_market_worker_lease(v_worker_key, v_id);
    END IF;
    RETURN QUERY SELECT null::uuid, false, 'concurrent_claim';
END;
$$;

REVOKE ALL ON FUNCTION public.claim_market_refresh_run(uuid, uuid, timestamptz, timestamptz, timestamptz)
  FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_market_refresh_run(uuid, uuid, timestamptz, timestamptz, timestamptz)
  TO service_role;

CREATE OR REPLACE FUNCTION public.release_market_refresh_worker_lease()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_provider text;
  v_worker_key text;
BEGIN
  IF old.status = 'RUNNING' AND new.status <> 'RUNNING' THEN
    SELECT p.provider_key INTO v_provider
      FROM public.market_series s
      JOIN public.market_instruments i ON i.id = s.instrument_id
      JOIN public.market_providers p ON p.id = i.provider_id
     WHERE s.id = new.series_id
       AND s.generation_mode = 'DIRECT'
       AND s.timeframe = '1m';

    IF v_provider = 'DUKASCOPY' THEN
      v_worker_key := 'DUKASCOPY_BASE';
    ELSIF v_provider = 'BINANCE' THEN
      v_worker_key := 'BINANCE_BASE';
    ELSE
      v_worker_key := null;
    END IF;

    IF v_worker_key IS NOT NULL THEN
      PERFORM public.release_market_worker_lease(v_worker_key, new.id);
    END IF;
  END IF;
  RETURN new;
END;
$$;

REVOKE ALL ON FUNCTION public.release_market_refresh_worker_lease()
  FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.release_market_refresh_worker_lease()
  TO service_role;

DROP TRIGGER IF EXISTS trg_release_market_refresh_worker_lease
  ON public.market_refresh_runs;
CREATE TRIGGER trg_release_market_refresh_worker_lease
AFTER UPDATE OF status ON public.market_refresh_runs
FOR EACH ROW
EXECUTE FUNCTION public.release_market_refresh_worker_lease();

CREATE OR REPLACE FUNCTION public.normalize_market_refresh_status()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  IF new.status = 'SUCCESS' THEN
    new.status := 'SUCCEEDED';
  END IF;
  RETURN new;
END;
$$;

REVOKE ALL ON FUNCTION public.normalize_market_refresh_status()
  FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.normalize_market_refresh_status()
  TO service_role;

DROP TRIGGER IF EXISTS a_normalize_market_refresh_status
  ON public.market_refresh_runs;
CREATE TRIGGER a_normalize_market_refresh_status
BEFORE INSERT OR UPDATE OF status ON public.market_refresh_runs
FOR EACH ROW
EXECUTE FUNCTION public.normalize_market_refresh_status();

CREATE OR REPLACE FUNCTION public.enforce_market_refresh_terminal_state()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  IF old.status <> 'RUNNING' AND new.status <> old.status THEN
    new.status := old.status;
    new.finished_at := old.finished_at;
    new.failure_reason := old.failure_reason;
  END IF;
  RETURN new;
END;
$$;

REVOKE ALL ON FUNCTION public.enforce_market_refresh_terminal_state()
  FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.enforce_market_refresh_terminal_state()
  TO service_role;

DROP TRIGGER IF EXISTS trg_market_refresh_terminal_state
  ON public.market_refresh_runs;
CREATE TRIGGER trg_market_refresh_terminal_state
BEFORE UPDATE ON public.market_refresh_runs
FOR EACH ROW
EXECUTE FUNCTION public.enforce_market_refresh_terminal_state();
