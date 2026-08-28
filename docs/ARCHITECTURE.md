# Architecture

## Boundary

The system is divided into independently testable layers:

1. **Market Data Layer** — provider-independent interfaces and asset-aware instrument contracts.
2. **Data Integrity Layer** — schema, chronology, quote/bar alignment, duplicate and malformed-record checks.
3. **Market Context Layer** — transforms only information known at decision time into an asset-aware state representation.
4. **Historical Similarity Layer** — finds comparable prior states without using future observations.
5. **Probability & Risk Layer** — summarizes conditional outcomes and applies minimum-evidence/risk gates.
6. **Decision Layer** — emits BUY/SELL/WAIT/NO_TRADE; never places an order.
7. **Portfolio Layer** — limits combined exposure across instruments and asset classes.
8. **Safety Layer** — default-deny authorization for any future execution integration.
9. **Execution Layer** — intentionally absent until research and validation gates are passed.
10. **Validation Layer** — walk-forward, out-of-sample, robustness and leakage checks.
11. **Audit Layer** — reproducible logs, decision metadata, candidate identity and evidence provenance.

## Universal data flow

`Provider -> Integrity -> Context -> Similarity -> Probability/Risk -> Cost -> Portfolio -> Decision -> Safety -> (future Execution) -> Audit`

## Controlled-operation contract

The model moves through the system in a fixed, pressure-free order:

`observe -> validate -> understand context -> estimate edge -> test costs -> check risk -> check portfolio -> decide -> audit`

No stage is allowed to create work merely to keep the pipeline busy. A quiet or ambiguous market naturally becomes `WAIT`; an unhealthy input or invalid state becomes `BLOCKED`.

A strategy component cannot bypass the decision factory, portfolio layer or safety boundary. There is no trade quota, countdown, forced retry loop or requirement to remain invested.

## Multi-asset separation

The core is asset-aware but not asset-assuming. Each instrument carries an immutable `InstrumentProfile` describing its asset class, venue semantics, price increment, contract multiplier, session model, cost model and market rules.

Initial domains are:

- **Forex:** the existing nine-pair V5 research domain.
- **Crypto:** BTC/USD, ETH/USD, SOL/USD.
- **Metals:** XAU/USD, XAG/USD.
- **Equities:** NVDA, MSFT, AAPL, AMZN, META.

Registration does not imply validation, paper eligibility or live authorization.

Asset-specific research contracts determine what each domain must understand. For example, exchange-traded equities require calendar and volume awareness; crypto research must account for continuous trading and venue/liquidity effects; metals require their own session, volatility and macro-context treatment.

Forex assumptions must never be silently applied to crypto, metals or equities.

## Research promotion states

`REGISTERED -> RESEARCH_ONLY -> EMPIRICALLY_VALIDATED -> PAPER_ELIGIBLE -> PROMOTION_ELIGIBLE`

Every asset class and instrument is promoted independently through evidence. A positive result in one domain cannot automatically validate another domain.

## V5 profitability proof contract

V5 is not considered profitable merely because a backtest has positive returns. The locked Forex candidate is identified by a deterministic candidate fingerprint and must be evaluated on a chronological discovery/confirmation split.

A consolidated non-live profitability verdict requires:

- all four V5 robustness reports to complete successfully
- identical candidate fingerprint across all four reports
- empirical data only; synthetic data explicitly false
- chronological confirmation sample of at least 500 observations
- positive confirmation expectancy after modeled execution costs
- confirmation profit factor greater than 1
- positive expectancy and profit factor greater than 1 under the 1.5-pip severe-cost stress
- at least three observed confirmation years
- positive expectancy in at least 67% of observed confirmation years
- at least two baseline currency pairs with positive confirmation expectancy and profit factor greater than 1
- leakage controls and frozen-holdout controls all true
- live execution authorization false

The verdict is evidence of historical robustness under the locked validation contract, not a guarantee of future profits.

## Asset-specific research contract

Every new domain must satisfy:

- empirical-only data
- chronological evaluation
- no future labels
- no confirmation learning
- transaction-cost modeling
- liquidity filtering
- domain-appropriate session/calendar treatment
- domain-appropriate volume treatment where applicable
- immutable candidate identity before confirmation
- non-live enforcement

## Portfolio control

The portfolio allocator is downstream of market evidence. It may reject a statistically attractive opportunity because portfolio or asset-class risk is already full.

The portfolio layer enforces a maximum number of open positions, total risk ceiling, asset-class risk ceiling, single-position ceiling and duplicate-position prevention.

This is intentional. The system optimizes for controlled risk flow rather than maximum trading frequency.

## Storage policy

Raw data is not required to be permanently archived for normal operation. Small reproducible research slices may be cached. Analytical storage uses DuckDB/Parquet where persistent research data is required.

## Provider policy

The application depends on provider-independent interfaces rather than provider-specific request formats. This permits multiple providers or venues to be introduced without rewriting the research, context or risk layers.

## Live trading gate

No live order path is considered available until all of these are independently demonstrated:

- validated provider data
- stable clock/timestamp handling
- spread/staleness checks
- deterministic risk limits
- portfolio exposure controls
- duplicate-order prevention
- broker acknowledgement handling
- emergency stop
- daily loss/exposure controls
- complete audit trail
- walk-forward validation
- out-of-sample performance evaluation
- operational recovery testing
- completed domain-specific non-live profitability verdict
- separate paper/shadow evidence after the historical verdict
