# Historical Data Analysis Handoff

This is the deliberate handoff point for large-scale data research.

## What is already engineered

- provider-independent market-data contract
- automatic Dukascopy retrieval
- automatic instrument discovery
- BID/ASK separation
- bounded historical requests with chunking and deduplication
- integrity validation
- local 5m/15m/4h aggregation
- compact DuckDB research storage
- market-context representation
- historical similarity interface with timestamp leakage guard
- probability/risk gate primitives
- walk-forward split validation
- default-deny execution boundary
- CI and deterministic unit tests

## What Claude should analyze

1. 2020-present historical behavior across selected FX instruments.
2. Multi-timeframe market regimes.
3. Conditional outcomes for candidate states/setups.
4. MFE/MAE and time-to-outcome distributions.
5. Spread and execution-cost sensitivity.
6. Session/day-of-week effects.
7. Cross-pair/correlation context.
8. Failure regimes and instability periods.
9. Walk-forward and out-of-sample robustness.
10. Probability calibration and minimum sample requirements.

## Required response format

For every proposed feature or strategy rule, provide:

- exact definition
- information available at decision time
- historical sample count
- training period
- validation period
- untouched test period
- expected outcome distribution
- adverse/favorable excursion
- transaction-cost assumptions
- failure conditions
- sensitivity to parameter changes
- evidence that the result is not a data-mining artifact

## Reproduction rule

Claude's conclusions are research hypotheses. They must be reproduced against the repository's data pipeline and independently validated before entering the production decision engine.

## No-go conditions

Do not promote a rule because of a single backtest, a high in-sample accuracy number, a small sample, or an apparent pattern without out-of-sample confirmation. Do not optimize for a target such as 90-99% accuracy merely to reach a headline number.
