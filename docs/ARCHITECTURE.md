# Architecture

## Boundary

The system is divided into independently testable layers:

1. **Market Data Layer** — provider-independent interface; Dukascopy is the first adapter.
2. **Data Integrity Layer** — schema, chronology, BID/ASK alignment, duplicate and malformed-record checks.
3. **Market Context Layer** — transforms only information known at decision time into a state representation.
4. **Historical Similarity Layer** — finds comparable prior states without using future observations.
5. **Probability & Risk Layer** — summarizes conditional outcomes and applies minimum-evidence/risk gates.
6. **Decision Layer** — emits BUY/SELL/WAIT/NO_TRADE; never places an order.
7. **Safety Layer** — default-deny authorization for any future execution integration.
8. **Execution Layer** — intentionally absent until research and validation gates are passed.
9. **Validation Layer** — walk-forward, out-of-sample and leakage checks.
10. **Audit Layer** — reproducible logs, decision metadata, candidate identity and evidence provenance.

## Data flow

`Provider -> Integrity -> Context -> Similarity -> Probability/Risk -> Decision -> Safety -> (future Execution)`

## Controlled-operation contract

The model must move through the system in a fixed order:

`observe -> validate -> classify context -> estimate conditional edge -> apply cost filter -> apply risk controls -> decide -> audit`

A strategy component cannot bypass the decision factory or safety boundary. `NO_TRADE` is a valid first-class decision and is preferred whenever evidence, cost, spread, context or expert agreement is insufficient.

During empirical confirmation, the candidate is frozen. Confirmation outcomes must never update the candidate, its learned evidence tables, or analogue labels used by later confirmation decisions. Only information available by the decision timestamp may influence a confirmation decision.

## V5 profitability proof contract

V5 is not considered profitable merely because a backtest has positive returns. The locked candidate is identified by a deterministic candidate fingerprint and must be evaluated on a chronological discovery/confirmation split.

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

## Storage policy

Raw data is not required to be permanently archived for normal operation. Small reproducible research slices may be cached. Analytical storage uses DuckDB/Parquet because they support efficient columnar filtering and projection.

## Provider policy

The rest of the application must depend on `MarketDataProvider`, not on Dukascopy-specific request formats. This permits a second provider to be added without rewriting the research or risk layers.

## Live trading gate

No live order path is considered available until all of these are independently demonstrated:

- validated provider data
- stable clock/timestamp handling
- spread/staleness checks
- deterministic risk limits
- duplicate-order prevention
- broker acknowledgement handling
- emergency stop
- daily loss/exposure controls
- complete audit trail
- walk-forward validation
- out-of-sample performance evaluation
- operational recovery testing
- completed V5 non-live profitability verdict
- separate paper/shadow evidence after the historical verdict
