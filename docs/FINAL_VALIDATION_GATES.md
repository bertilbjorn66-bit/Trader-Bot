# Trader Bot — Final Validation Gates

The bot is not considered production-ready merely because a backtest is profitable. Promotion is monotonic and default-deny.

## Gate 1 — Data integrity

- All nine research pairs must be present.
- BID/ASK timestamps must align.
- Bars must be strictly chronological with no duplicates.
- Crossed executable bars are rejected; prices are never repaired or clipped.
- Provider failures fail closed.

## Gate 2 — Leakage-safe research

- Target decisions use only information available at the target timestamp.
- Historical analogues must have complete outcome windows ending no later than the target timestamp.
- Walk-forward purge must cover the maximum prediction horizon.
- Research artifacts must explicitly identify empirical versus synthetic data.

## Gate 3 — Conditional discovery

The enriched experiment records per-target analogue distance, agreement, regime, session, year, direction, horizon, and executable outcome in pips.

Candidate thresholds are selected only on the chronological discovery segment.

## Gate 4 — Untouched confirmation

The selected candidate thresholds are frozen before the confirmation segment is evaluated. Confirmation performance is never fed back into candidate selection.

A candidate fails this gate if confirmation expectancy is non-positive, profit factor is not above 1, or the minimum confirmation sample is not met.

## Gate 5 — Robustness and cost stress

Confirmation finalists are checked by:

- pair;
- year;
- direction;
- maximum drawdown;
- 0.2, 0.5, and 1.0 pip additional cost stress;
- concentration in a single pair;
- minimum positive-pair breadth.

A candidate is not promoted solely because one pair or one period is strong.

## Gate 6 — Paper trading

No broker order is permitted. The candidate runs through the same decision and risk path using live market observations while recording hypothetical fills, spread, slippage, latency, rejected signals, and P&L.

The paper period must be independently evaluated against the frozen research specification. A candidate cannot be retuned from paper results and still call that period confirmation.

## Gate 7 — Shadow execution

If paper trading passes, the bot may connect to a broker market-data feed while the execution gateway remains disabled. Every intended order is logged and safety-authorized, but no order is transmitted.

## Gate 8 — Live authorization

Live execution remains impossible until all of the following are independently true:

1. empirical confirmation passes;
2. robustness and cost stress pass;
3. paper trading passes;
4. shadow execution passes;
5. credentials are configured outside source control;
6. emergency stop is tested;
7. daily loss limits are tested;
8. stale-data and spread gates are tested;
9. broker-side position/risk limits are verified;
10. a final human approval explicitly enables live execution.

The execution gateway remains disabled by default even after the research gates pass.
