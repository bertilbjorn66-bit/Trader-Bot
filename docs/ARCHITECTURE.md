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
10. **Audit Layer** — reproducible logs and decision metadata.

## Data flow

`Provider -> Integrity -> Context -> Similarity -> Probability/Risk -> Decision -> Safety -> (future Execution)`

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
