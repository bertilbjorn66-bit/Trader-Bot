# Trader Bot — Empirical Deployment Gate Audit

Date: 2026-08-22

Source: preserved `VERIFIED-EMPIRICAL-RESEARCH-REPORT-FINAL` from workflow run `32481090602`.

## Result

**DEPLOYMENT BLOCKED.**

The preserved empirical report contains all nine required FX pairs and 36 sequential out-of-sample pair/horizon evaluations (9 pairs × 4 horizons). Across all 36 evaluations:

- sequential out-of-sample expectancy is negative;
- profit factor is below 1;
- 71,392 sequential targets are represented in total.

The strongest observed expectancy is still negative (EUR/USD, horizon 1): approximately -0.00003655 price units, with profit factor 0.7807.

The highest observed profit factor is still below 1 (USD/JPY, horizon 2): 0.8872, with negative expectancy.

## Interpretation

This is a valid **safety stop**, not evidence of a profitable trading edge. Live trading must remain disabled. The newer enriched conditional Survival Gate has not been falsely marked successful; its GitHub-hosted execution remains blocked before substantive runner steps.

The existing zero-touch retry workflow remains in the repository so the enriched experiment can run automatically when hosted Actions becomes available again.
