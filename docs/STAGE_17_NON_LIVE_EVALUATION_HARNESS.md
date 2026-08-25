# Stage 17 — Non-Live Evaluation Harness

This stage creates the final non-live profitability assessment framework without requiring a broker account or live orders.

## What it evaluates

- chronological walk-forward structure;
- transaction-cost-adjusted expectancy;
- base versus stressed execution costs;
- ordinary bootstrap uncertainty;
- block-bootstrap uncertainty to preserve local dependence;
- maximum drawdown;
- Monte Carlo probability of ruin;
- fold-by-fold positivity;
- an explicit PASS / FAIL / INCOMPLETE verdict.

## Interpretation

A PASS is a result under predefined statistical assumptions, not a guarantee of future profit. A FAIL or INCOMPLETE result blocks promotion. The harness never enables broker transmission.

The intended next step is to connect this harness to a frozen strategy/evidence snapshot and run it on properly time-separated out-of-sample records. No manual trading is required for that evaluation.
