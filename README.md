# DuraPlex Trader Bot

Private, research-first algorithmic trading system.

## Engineering status

The repository is being built in audited stages. The system is intentionally separated into market-data acquisition, data integrity, market context, historical similarity, probability/risk, decision, safety, execution, and validation layers.

**Current boundary:** engineering infrastructure is built before large-scale historical data analysis. No live trading is enabled by default.

## Core principles

- No manual market-data downloading for normal operation.
- Provider-independent market-data interface.
- Dukascopy is the initial historical/current market-data provider.
- BID and ASK remain distinct through the pipeline.
- Raw market data is temporary unless deliberately retained for reproducibility/audit.
- Compact analytical storage uses Parquet/DuckDB where persistent research data is required.
- Historical evaluation must be walk-forward and leakage-resistant.
- No strategy is considered profitable merely because it fits historical data.
- Live execution is disabled until research, validation, risk controls, and operational safeguards pass their gates.

## Important limitation

This software cannot guarantee profits, eliminate losses, or predict the future. Its purpose is to quantify conditional probabilities and risk and to reject trades when evidence is insufficient.

## Development

Python is the primary research/control language. A small Node.js provider adapter may be used where the maintained Dukascopy tooling is the most reliable integration path. The rest of the system must not depend directly on provider-specific APIs.
