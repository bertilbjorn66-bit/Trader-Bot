# Multi-Asset Architecture

## Objective

The Trader Bot is designed as a calm, controlled flow rather than a system that is pressured to trade.

The universal path is:

`observe -> validate -> understand context -> estimate edge -> test costs -> check risk -> check portfolio -> decide -> audit`

Every stage may return `WAIT` or `BLOCKED`. Nothing in the architecture creates a trade quota, countdown, forced retry, or requirement to remain invested.

## Asset domains

### Forex

The existing nine-pair empirical domain remains the first validated research domain:

- EUR/USD
- GBP/USD
- USD/JPY
- AUD/USD
- USD/CAD
- USD/CHF
- NZD/USD
- EUR/JPY
- GBP/JPY

The current V5 profitability validation remains separate and frozen while multi-asset foundations are introduced.

### Crypto

Initial research universe:

- BTC/USD
- ETH/USD
- SOL/USD

Crypto research must model continuous 24/7 availability, venue liquidity, volume, funding/carry where applicable, spread, slippage and exchange-specific market structure. No crypto instrument is currently considered validated merely because it is registered in the universe.

### Metals

Initial research universe:

- XAU/USD
- XAG/USD

Metals require their own volatility, liquidity, session and macro-context treatment. They are not treated as Forex pairs simply because they are quoted in USD.

### Equities

Initial research universe:

- NVDA
- MSFT
- AAPL
- AMZN
- META

Equity research must be calendar-aware and volume-aware and must explicitly handle market sessions, overnight gaps and event-sensitive conditions. A stock is not placed into a validated trading state by registration alone.

## Separation of concerns

The universal layers should remain reusable:

- data contracts
- data integrity
- context representation
- similarity and probability tooling
- risk controls
- decision factory
- safety
- audit
- portfolio allocation

Asset-specific layers supply the rules that differ by market class:

- venue and provider semantics
- trading calendar/session model
- price and contract units
- transaction-cost model
- liquidity requirements
- volume interpretation
- funding/carry treatment
- event sensitivity
- market-specific research features

The universal core must never silently substitute Forex assumptions for another asset class.

## Research isolation

Each asset class gets its own empirical research contract and evidence identity.

A successful crypto result does not automatically validate gold, equities or Forex. A successful gold result does not automatically validate a stock. Promotion is domain-specific first, portfolio-aware second.

Each research engine must remain:

- empirical-only
- chronological
- leakage-resistant
- transaction-cost-aware
- liquidity-aware
- frozen during confirmation
- non-live until independently promoted

## Portfolio flow

Once multiple domains become individually research-eligible, the portfolio layer controls combined exposure.

It enforces:

- maximum open positions
- total portfolio risk ceiling
- asset-class risk ceiling
- single-position ceiling
- duplicate-position prevention

The portfolio allocator can reject an otherwise attractive instrument because the portfolio is already carrying too much risk in the same asset class. This is intentional: the best isolated trade is not necessarily the best portfolio action.

## Calm-flow principle

The system should behave like a river:

1. Information enters at its natural rate.
2. Invalid, stale or ambiguous information is filtered without forcing downstream activity.
3. Context is formed before opportunity is evaluated.
4. Opportunities compete for limited risk capacity.
5. Absence of a clear edge produces no action.
6. A blocked provider, uncertain context or full risk budget stops flow locally rather than destabilizing the whole system.
7. Every decision is auditable and traceable to the evidence that allowed it.

No component should manufacture certainty merely to keep the pipeline busy.

## Promotion boundary

The asset universe is broader than the validated universe.

`REGISTERED -> RESEARCH_ONLY -> EMPIRICALLY_VALIDATED -> PAPER_ELIGIBLE -> PROMOTION_ELIGIBLE`

A symbol must move through these states deliberately. Adding an instrument to the registry never authorizes live execution.

Live execution remains globally disabled until the existing safety, research, operational and promotion gates independently pass.
