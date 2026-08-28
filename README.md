# DuraPlex Trader Bot

Private, research-first algorithmic trading system.

## Engineering status

The system is built in audited stages. The architecture separates market-data acquisition, data integrity, asset-aware market context, historical similarity, probability/risk, portfolio control, decision, safety, execution boundaries, validation, and audit layers.

**Current boundary:** the system is research-first and non-live by default. The existing Forex V5 profitability validation remains independently gated while the multi-asset foundation is expanded.

## Asset coverage direction

The universal core is designed to support:

- Forex: the existing nine-pair empirical domain
- Crypto: BTC/USD, ETH/USD, SOL/USD
- Metals: XAU/USD, XAG/USD
- Equities: NVDA, MSFT, AAPL, AMZN, META

New instruments enter as `RESEARCH_ONLY` and must earn validation independently. Registration never enables trading.

## Calm-flow principle

The bot is not designed to trade constantly. Its operating flow is:

`observe -> validate -> understand context -> estimate edge -> test costs -> check risk -> check portfolio -> decide -> audit`

`WAIT` and `BLOCKED` are normal successful outcomes. No component is allowed to manufacture certainty, force a trade, or bypass the decision and safety boundaries.

## Core principles

- No manual market-data downloading for normal operation.
- Provider-independent market-data interface.
- Asset-specific market rules rather than one-size-fits-all assumptions.
- BID/ASK or equivalent executable pricing remains distinct through the pipeline where available.
- Raw market data is temporary unless deliberately retained for reproducibility/audit.
- Analytical storage uses Parquet/DuckDB where persistent research data is required.
- Historical evaluation must be chronological and leakage-resistant.
- Each asset domain must model realistic transaction costs and liquidity.
- No strategy is considered profitable merely because it fits historical data.
- Live execution is disabled until research, validation, risk controls, portfolio safeguards, and operational gates pass.

## Important limitation

This software cannot guarantee profits, eliminate losses, or predict the future. Its purpose is to quantify conditional probabilities and risk and to reject trades when evidence is insufficient.

## Development

Python is the primary research/control language. Providers and venue adapters must remain behind provider-independent interfaces so that crypto exchanges, metals venues and equity data sources can be introduced without rewriting the research or risk layers.
