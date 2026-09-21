# Complete Trader Bot Build Plan

## Build order

Profitability testing is intentionally postponed until every non-validation layer is implemented, internally tested, integrated, and audited.

### Layer stack

1. Data acquisition and provider contracts
2. Data integrity and timestamp discipline
3. Instrument and asset contracts
4. Asset-specific context interpretation
5. Regime classification and transition detection
6. Behavioral historical memory
7. Similarity / analogue retrieval
8. Expert reasoning ensemble
9. Probability estimation
10. Probability calibration
11. Execution-cost modeling
12. Liquidity and market-impact assessment
13. Risk controls
14. Portfolio exposure and concentration control
15. Cross-asset opportunity comparison
16. Model health and drift monitoring
17. Decision factory
18. Decision audit and immutable reason records
19. Paper/shadow operational boundary
20. Safety and non-live execution boundary
21. Validation harness and evidence infrastructure
22. Profitability validation — deferred until the above are complete

## Completion rule

A layer is complete only when:

- it has one clear owner;
- its inputs and outputs are explicit;
- invalid or incomplete inputs fail closed;
- its behavior is covered by automated tests;
- it does not silently fall back to another asset class or another stage;
- it can be audited from its emitted decision artifact;
- it does not introduce forced retries, quotas, timers, or activity pressure.

## Asset intelligence rule

Every asset class inherits the same reasoning faculties:

- trend
- momentum
- breakout
- mean reversion
- pullback
- volatility
- reversal
- historical analogue

The interpretation of those faculties is asset-specific. Historical evidence for one asset class cannot validate another.

## Profitability firewall

Before the final validation phase:

- no profitability optimization;
- no holdout tuning;
- no parameter selection using confirmation data;
- no promotion based on simulated or synthetic profitability;
- no live execution.

The final validation phase will separately evaluate each asset domain and then the combined portfolio/system behavior using frozen candidates and untouched evidence.

## Calm-flow rule

The bot may always return WAIT or BLOCKED. A later stage may not manufacture evidence to keep the pipeline moving. Local failure remains local and auditable.
