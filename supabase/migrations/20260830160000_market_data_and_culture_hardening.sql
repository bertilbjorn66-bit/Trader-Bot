-- Reconciles the latest live Trader Bot Supabase control-plane hardening.
-- Secrets and raw market data are intentionally excluded.

ALTER TABLE public.market_series_health
  DROP CONSTRAINT IF EXISTS market_series_health_quality_state_check;

ALTER TABLE public.market_series_health
  ADD CONSTRAINT market_series_health_quality_state_check
  CHECK (quality_state = ANY (ARRAY[
    'UNASSESSED','PASS','FAIL','INSUFFICIENT_DATA','INCOMPLETE_HISTORY','BLOCKED'
  ]::text[]));

CREATE TABLE IF NOT EXISTS public.market_culture_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  instrument_id uuid NOT NULL REFERENCES public.market_instruments(id) ON DELETE CASCADE,
  culture_version integer NOT NULL CHECK (culture_version > 0),
  source_scope_fingerprint text NOT NULL,
  observed_from timestamptz NOT NULL,
  observed_to timestamptz NOT NULL,
  evidence_count bigint NOT NULL CHECK (evidence_count >= 0),
  context_dimensions jsonb NOT NULL DEFAULT '{}'::jsonb,
  operating_profile jsonb NOT NULL DEFAULT '{}'::jsonb,
  evolution_profile jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (instrument_id, culture_version)
);

CREATE INDEX IF NOT EXISTS market_culture_history_instrument_time_idx
  ON public.market_culture_history (instrument_id, created_at DESC);

ALTER TABLE public.market_culture_history ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.market_culture_history FROM anon, authenticated;

DROP POLICY IF EXISTS market_culture_history_service_only ON public.market_culture_history;
CREATE POLICY market_culture_history_service_only
  ON public.market_culture_history
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

CREATE OR REPLACE FUNCTION public.audit_market_series(
  p_series_id uuid,
  p_timeframe text,
  p_asset_class text,
  p_min_rows bigint DEFAULT 100
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, bot
AS $$
DECLARE
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
  v_cursor timestamptz;
  v_target timestamptz;
BEGIN
  v_step := CASE p_timeframe
    WHEN '1s' THEN 1 WHEN '1m' THEN 60 WHEN '5m' THEN 300
    WHEN '15m' THEN 900 WHEN '1h' THEN 3600 WHEN '4h' THEN 14400
    WHEN '1d' THEN 86400 ELSE 0 END;
  IF v_step = 0 THEN
    RAISE EXCEPTION 'unsupported_timeframe:%', p_timeframe;
  END IF;

  v_min_rows := COALESCE(
    (SELECT minimum_research_rows
       FROM public.market_refresh_policies
      WHERE series_id = p_series_id),
    p_min_rows
  );

  SELECT backfill_cursor_at, backfill_target_at
    INTO v_cursor, v_target
    FROM public.market_series_health
   WHERE series_id = p_series_id;

  v_max_allowed := CASE upper(p_asset_class)
    WHEN 'CRYPTO' THEN v_step * 2
    WHEN 'FOREX' THEN greatest(v_step * 3, 259200)
    WHEN 'METAL' THEN greatest(v_step * 3, 259200)
    WHEN 'COMMODITY' THEN greatest(v_step * 3, 259200)
    WHEN 'EQUITY' THEN greatest(v_step * 3, 604800)
    WHEN 'INDEX' THEN greatest(v_step * 3, 604800)
    ELSE v_step * 2 END;

  WITH ordered AS (
    SELECT opened_at, open, high, low, close,
           lag(opened_at) OVER (ORDER BY opened_at) AS prev_at
      FROM bot.market_series_bars
     WHERE series_id = p_series_id
     ORDER BY opened_at DESC
     LIMIT 5000
  ), ordered2 AS (
    SELECT * FROM ordered ORDER BY opened_at
  ), stats AS (
    SELECT count(*) AS rows,
           count(*) FILTER (
             WHERE high < greatest(open, close, low)
                OR low > least(open, close, high)
           ) AS bad_ohlc,
           0::bigint AS duplicate_count,
           coalesce(max(extract(epoch FROM (opened_at - prev_at))), 0)::bigint AS max_gap,
           min(opened_at) AS first_at,
           max(opened_at) AS last_at
      FROM ordered2
  )
  SELECT rows, bad_ohlc, duplicate_count, max_gap, first_at, last_at
    INTO v_rows, v_bad_ohlc, v_duplicate, v_max_gap, v_first, v_last
    FROM stats;

  IF v_cursor IS NOT NULL THEN
    v_quality := 'INCOMPLETE_HISTORY';
    v_reason := 'backfill_in_progress';
    v_eligible := false;
  ELSIF v_rows = 0 THEN
    v_quality := 'INSUFFICIENT_DATA';
    v_reason := 'no_rows';
    v_eligible := false;
  ELSIF v_rows < v_min_rows THEN
    v_quality := 'INSUFFICIENT_DATA';
    v_reason := 'minimum_research_rows_not_met';
    v_eligible := false;
  ELSIF v_bad_ohlc > 0 THEN
    v_quality := 'FAIL';
    v_reason := 'invalid_ohlc';
    v_eligible := false;
  ELSIF v_max_gap > v_max_allowed THEN
    v_quality := 'FAIL';
    v_reason := 'unexpected_gap';
    v_eligible := false;
  ELSE
    v_quality := 'PASS';
    v_reason := 'quality_and_maturity_pass';
    v_eligible := true;
  END IF;

  UPDATE public.market_series_health
     SET quality_state = v_quality,
         quality_checked_at = now(),
         quality_reason = v_reason,
         research_eligible = v_eligible,
         max_gap_seconds = v_max_gap,
         duplicate_timestamp_count = v_duplicate,
         state = CASE WHEN v_eligible THEN 'FRESH' ELSE 'BLOCKED' END,
         updated_at = now()
   WHERE series_id = p_series_id;

  RETURN jsonb_build_object(
    'series_id', p_series_id,
    'rows', v_rows,
    'minimum_research_rows', v_min_rows,
    'bad_ohlc', v_bad_ohlc,
    'max_gap_seconds', v_max_gap,
    'quality_state', v_quality,
    'research_eligible', v_eligible,
    'backfill_in_progress', v_cursor IS NOT NULL,
    'backfill_target_at', v_target,
    'reason', v_reason
  );
END;
$$;

REVOKE ALL ON FUNCTION public.audit_market_series(uuid, text, text, bigint)
  FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.audit_market_series(uuid, text, text, bigint)
  TO service_role;

CREATE OR REPLACE FUNCTION public.reap_stale_market_refresh_runs(
  p_max_age_seconds integer DEFAULT 1800
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_count integer;
BEGIN
  UPDATE public.market_refresh_runs r
     SET status = 'FAILED',
         finished_at = now(),
         failure_reason = 'stale_run_reaped'
    FROM public.market_series s
    JOIN public.market_instruments i ON i.id = s.instrument_id
    JOIN public.market_providers p ON p.id = i.provider_id
   WHERE r.series_id = s.id
     AND r.status = 'RUNNING'
     AND r.started_at < now() - make_interval(
       secs => CASE
         WHEN p.provider_key = 'BINANCE' THEN 600
         WHEN p.provider_key = 'DUKASCOPY' THEN 1800
         ELSE 900 END
     );
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION public.reap_stale_market_refresh_runs(integer)
  FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reap_stale_market_refresh_runs(integer)
  TO service_role;

CREATE OR REPLACE FUNCTION public.refresh_market_culture(
  p_limit integer DEFAULT 3
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, bot
AS $$
DECLARE
  r record;
  v_limit integer := greatest(1, least(coalesce(p_limit, 3), 10));
  v_processed integer := 0;
  v_version integer;
  v_first timestamptz;
  v_last timestamptz;
  v_rows bigint;
  v_mean_ret numeric;
  v_vol numeric;
  v_down numeric;
  v_mean_range numeric;
  v_trend_persistence numeric;
  v_reversal_rate numeric;
  v_breakout_rate numeric;
  v_support numeric;
  v_resistance numeric;
  v_hour jsonb;
  v_dow jsonb;
  v_fp text;
BEGIN
  FOR r IN
    SELECT i.id AS instrument_id, i.venue, i.canonical_symbol, i.asset_class
      FROM public.market_instruments i
     WHERE i.enabled
       AND EXISTS (
         SELECT 1
           FROM public.market_series s
           JOIN public.market_series_health h ON h.series_id = s.id
          WHERE s.instrument_id = i.id
            AND s.enabled
            AND s.generation_mode = 'DIRECT'
            AND s.timeframe = '1m'
            AND h.research_eligible
            AND h.backfill_cursor_at IS NULL
            AND h.quality_state = 'PASS'
       )
     ORDER BY i.updated_at
     LIMIT v_limit
  LOOP
    SELECT min(b.opened_at), max(b.opened_at), count(*)
      INTO v_first, v_last, v_rows
      FROM bot.market_series_bars b
      JOIN public.market_series s ON s.id = b.series_id
      JOIN public.market_series_health h ON h.series_id = s.id
     WHERE s.instrument_id = r.instrument_id
       AND s.generation_mode = 'DIRECT'
       AND s.enabled
       AND s.timeframe = '1m'
       AND h.research_eligible
       AND h.backfill_cursor_at IS NULL;

    IF v_rows < 10000 THEN CONTINUE; END IF;

    WITH x AS (
      SELECT b.opened_at, b.high, b.low, b.close,
             lag(b.close) OVER (ORDER BY b.opened_at) AS prev_close
        FROM bot.market_series_bars b
        JOIN public.market_series s ON s.id = b.series_id
        JOIN public.market_series_health h ON h.series_id = s.id
       WHERE s.instrument_id = r.instrument_id
         AND s.generation_mode = 'DIRECT'
         AND s.enabled AND s.timeframe = '1m'
         AND h.research_eligible AND h.backfill_cursor_at IS NULL
    ), y AS (
      SELECT *, CASE WHEN prev_close IS NULL OR prev_close = 0 THEN NULL
                     ELSE (close - prev_close) / prev_close END AS ret
        FROM x
    ), z AS (
      SELECT *, lag(ret) OVER (ORDER BY opened_at) AS prev_ret
        FROM y
    )
    SELECT avg(ret), stddev_samp(ret), stddev_samp(ret) FILTER (WHERE ret < 0),
           avg(high - low),
           avg(CASE WHEN ret <> 0 AND prev_ret <> 0 AND sign(ret) = sign(prev_ret) THEN 1 ELSE 0 END),
           avg(CASE WHEN ret <> 0 AND prev_ret <> 0 AND sign(ret) <> sign(prev_ret) THEN 1 ELSE 0 END)
      INTO v_mean_ret, v_vol, v_down, v_mean_range, v_trend_persistence, v_reversal_rate
      FROM z
     WHERE ret IS NOT NULL;

    WITH x AS (
      SELECT b.opened_at, b.close,
             max(b.close) OVER (ORDER BY b.opened_at ROWS BETWEEN 21 PRECEDING AND 1 PRECEDING) AS prior_high
        FROM bot.market_series_bars b
        JOIN public.market_series s ON s.id = b.series_id
        JOIN public.market_series_health h ON h.series_id = s.id
       WHERE s.instrument_id = r.instrument_id
         AND s.generation_mode = 'DIRECT' AND s.enabled AND s.timeframe = '1m'
         AND h.research_eligible AND h.backfill_cursor_at IS NULL
    )
    SELECT avg(CASE WHEN close > prior_high THEN 1 ELSE 0 END),
           percentile_cont(0.1) WITHIN GROUP (ORDER BY close),
           percentile_cont(0.9) WITHIN GROUP (ORDER BY close)
      INTO v_breakout_rate, v_support, v_resistance
      FROM x WHERE prior_high IS NOT NULL;

    WITH q AS (
      SELECT b.opened_at, b.high, b.low, b.close,
             CASE WHEN lag(b.close) OVER (ORDER BY b.opened_at) = 0 THEN NULL
                  ELSE (b.close - lag(b.close) OVER (ORDER BY b.opened_at)) /
                       lag(b.close) OVER (ORDER BY b.opened_at) END AS ret
        FROM bot.market_series_bars b
        JOIN public.market_series s ON s.id = b.series_id
        JOIN public.market_series_health h ON h.series_id = s.id
       WHERE s.instrument_id = r.instrument_id AND s.generation_mode = 'DIRECT'
         AND s.enabled AND s.timeframe = '1m' AND h.research_eligible
         AND h.backfill_cursor_at IS NULL AND b.opened_at >= v_last - interval '365 days'
    )
    SELECT coalesce(jsonb_object_agg(k, metrics), '{}'::jsonb)
      INTO v_dow
      FROM (
        SELECT extract(isodow FROM opened_at)::int k,
               jsonb_build_object('count', count(*), 'mean_abs_return', avg(abs(ret)), 'mean_range', avg(high-low)) metrics
          FROM q WHERE ret IS NOT NULL
         GROUP BY extract(isodow FROM opened_at)
      ) d;

    SELECT md5(coalesce(string_agg(DISTINCT h.source_hash, '|' ORDER BY h.source_hash), '') || ':' || r.instrument_id::text)
      INTO v_fp
      FROM public.market_series s
      JOIN public.market_series_health h ON h.series_id = s.id
     WHERE s.instrument_id = r.instrument_id AND s.generation_mode = 'DIRECT'
       AND s.enabled AND s.timeframe = '1m' AND h.research_eligible
       AND h.backfill_cursor_at IS NULL;

    SELECT coalesce(max(culture_version), 0) + 1
      INTO v_version
      FROM public.market_knowledge_scopes WHERE instrument_id = r.instrument_id;

    INSERT INTO public.market_culture_history (
      instrument_id, culture_version, source_scope_fingerprint, observed_from, observed_to,
      evidence_count, context_dimensions, operating_profile, evolution_profile
    ) VALUES (
      r.instrument_id, v_version, v_fp, v_first, v_last, v_rows,
      jsonb_build_object(
        'asset_class', r.asset_class,
        'timeframe', '1m',
        'data_source_scope', 'DIRECT_ONLY',
        'cross_market_relations', 'SEPARATE_LAYER',
        'news_context', 'NOT_PRESENT_IN_BASE_DATA',
        'spread_context', 'DATA_DEPENDENT'
      ),
      jsonb_build_object(
        'mean_return', v_mean_ret,
        'realized_volatility', v_vol,
        'downside_volatility', v_down,
        'mean_range', v_mean_range,
        'trend_persistence', v_trend_persistence,
        'reversal_rate', v_reversal_rate,
        'breakout_rate', v_breakout_rate,
        'support_quantile', v_support,
        'resistance_quantile', v_resistance,
        'day_of_week_profile', v_dow
      ),
      jsonb_build_object(
        'trade_outcome_memory', 'PENDING_ACTUAL_DECISION_OUTCOMES',
        'mfe_mae_memory', 'PENDING_ACTUAL_DECISION_OUTCOMES',
        'holding_behavior', 'PENDING_ACTUAL_DECISION_OUTCOMES',
        'adaptation', 'VERSIONED_REBUILD_ONLY'
      )
    );

    UPDATE public.market_knowledge_scopes k
       SET culture_version = v_version,
           evidence_count = v_rows,
           confidence = least(1, greatest(0, ln(greatest(v_rows, 1)) / 12)),
           observation_started_at = v_first,
           observation_ended_at = v_last,
           source_fingerprint = v_fp,
           review_after = now() + interval '30 days',
           status = 'VALIDATED',
           context_dimensions = (SELECT context_dimensions FROM public.market_culture_history WHERE instrument_id = r.instrument_id AND culture_version = v_version),
           operating_profile = (SELECT operating_profile FROM public.market_culture_history WHERE instrument_id = r.instrument_id AND culture_version = v_version),
           evolution_profile = (SELECT evolution_profile FROM public.market_culture_history WHERE instrument_id = r.instrument_id AND culture_version = v_version),
           evidence_state = 'EMPIRICAL_PRICE_CONTEXT_ONLY',
           data_freshness_state = 'FRESH',
           source_scope_fingerprint = v_fp,
           updated_at = now()
     WHERE k.instrument_id = r.instrument_id;

    v_processed := v_processed + 1;
  END LOOP;

  RETURN jsonb_build_object('processed', v_processed, 'updated', v_processed);
END;
$$;

REVOKE ALL ON FUNCTION public.refresh_market_culture(integer)
  FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.refresh_market_culture(integer)
  TO service_role;

-- Low-pressure scheduler; the learner is a no-op while no series is eligible.
SELECT cron.schedule('refresh-market-culture-every-15m', '*/15 * * * *', 'select public.refresh_market_culture(3);')
WHERE NOT EXISTS (
  SELECT 1 FROM cron.job WHERE jobname = 'refresh-market-culture-every-15m'
);
