# Quantitative Research Layer Engineering Audit

Status: research infrastructure only; no empirical market conclusions.

## Verified design boundaries

- Real trading execution is not implemented or enabled by this research layer.
- Synthetic data is test-only and explicitly labeled non-empirical.
- BID/ASK are preserved separately for executable entry/exit evaluation.
- Future observations are excluded from historical-state similarity.
- Walk-forward helpers preserve chronological ordering.
- Target/stop evaluation returns an indeterminate result when a bar touches both levels and intrabar ordering is unavailable.
- Research output is explicitly marked `REAL_DATA_REQUIRED` until real market data is supplied and validated.

## Statistical caveats that remain intentional

- Neighbor outcomes may be dependent when historical setups overlap; real-data research must use a purge/embargo policy appropriate to the outcome horizon before reporting inferential confidence.
- Confidence intervals on overlapping observations must not be interpreted as independent-sample guarantees.
- Feature selection, thresholds, model selection and strategy promotion must occur inside training/walk-forward folds.
- Multiple-testing corrections are required when many candidate hypotheses are searched.
- Synthetic results are not evidence of a trading edge.

## Required real-data gates

1. Provider data-quality audit.
2. BID/ASK timestamp alignment.
3. UTC/session correctness.
4. Leakage and future-information audit.
5. Purged/embargoed walk-forward validation for overlapping labels.
6. Untouched out-of-sample evaluation.
7. Transaction-cost and spread sensitivity.
8. Multiple-testing/data-mining controls.
9. Parameter-perturbation robustness.
10. Probability calibration and minimum-sample analysis.
11. Risk/drawdown/tail-loss analysis.
12. Independent review before any production strategy promotion.
