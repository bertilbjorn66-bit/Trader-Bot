# DuraPlex Trader Bot

Research-first algorithmic trading system.

The source repository is currently public and contains the public-safe engineering shell: contracts, orchestration, tests, documentation, and non-sensitive infrastructure. Private market data, proprietary research evidence, credentials, private feature stores, and production configuration must remain outside this repository.

## Engineering status

The system is built in audited stages. The architecture separates market-data acquisition, data integrity, asset-aware market context, historical similarity, probability/risk, portfolio control, decision, trade evolution, data freshness, safety, execution boundaries, validation, and audit layers.

**Current boundary:** the system is research-first and non-live by default. Profitability validation is a later gated stage and is not used to declare the architecture complete.

## Asset coverage direction

The universal core is designed to support:

- Forex: the existing nine-pair empirical domain
- Crypto: BTC/USD, ETH/USD, SOL/USD
- Metals: XAU/USD, XAG/USD
- Equities: NVDA, MSFT, AAPL, AMZN, META

New instruments enter as `RESEARCH_ONLY` and must earn validation independently. Registration never enables trading.

## Calm-flow principle

The bot is not designed to trade constantly. Its operating flow is:

`refresh -> validate -> understand context -> estimate edge -> test costs -> check liquidity -> check risk -> check portfolio -> evaluate trade evolution -> decide -> audit`

`WAIT` and `BLOCKED` are normal successful outcomes. No component is allowed to manufacture certainty, force a trade, use stale data silently, or bypass the decision and safety boundaries.

## Core principles

- No manual market-data downloading for normal operation.
- Provider-independent market-data interface.
- Asset-specific market rules rather than one-size-fits-all assumptions.
- BID/ASK or equivalent executable pricing remains distinct through the pipeline where available.
- Raw market data is kept outside the public repository and retained only when needed for reproducibility/audit.
- Analytical storage uses Parquet/DuckDB where persistent private research data is required.
- Historical evaluation must be chronological and leakage-resistant.
- Each asset domain must model realistic transaction costs and liquidity.
- Automatic refresh is incremental, bounded, resumable, and independently scoped per asset domain.
- A stale or unverifiable feed blocks downstream empirical use.
- No strategy is considered profitable merely because it fits historical data.
- Live execution is disabled until research, validation, risk controls, portfolio safeguards, and operational gates pass.

## Important limitation

This software cannot guarantee profits, eliminate losses, or predict the future. Its purpose is to quantify conditional probabilities and risk and to reject trades when evidence is insufficient.

## Development

Python is the primary research/control language. Providers and venue adapters remain behind provider-independent interfaces so that crypto exchanges, metals venues and equity data sources can be introduced without rewriting the research or risk layers.
