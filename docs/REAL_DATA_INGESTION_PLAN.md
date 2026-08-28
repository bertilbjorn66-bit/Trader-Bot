# Real Data Ingestion Plan

## Objective

Feed each market layer with real historical market data from an appropriate source without mixing market microstructures, inventing missing values, or allowing synthetic records into empirical research.

## Source map

| Domain | Primary source | Initial use | Important native context |
|---|---|---|---|
| Forex | Dukascopy Historical Data | tick/minute/hour/daily | bid/ask, spread, session, volume when supplied |
| Metals | Dukascopy historical instruments where available | minute/hour/daily | session, bid/ask, volatility, USD/rates/event context |
| Commodities | Dukascopy-supported instruments where available | minute/hour/daily | session, volume, event/calendar context |
| Crypto | Binance public market data | trade/aggTrade/kline history | 24/7 state, volume, funding/derivatives data when separately sourced, venue identity |
| Equities | Stooq for broad daily history | daily research baseline | exchange calendar, gaps, splits/adjustments as provided by source |
| Indices | Stooq for broad daily history | daily research baseline | exchange calendar, gaps, volume where supplied |

The source map is an acquisition design, not a claim that every source provides every required field for every instrument. A domain remains blocked until its source data satisfy the domain research contract.

## Later ingestion sequence

1. Discover the exact supported instrument identifier at the source.
2. Retrieve the smallest complete raw interval needed for the research stage.
3. Preserve source-native records unchanged in immutable storage.
4. Record source, instrument, resolution, interval, retrieval time, row count and SHA-256 digest.
5. Validate timestamps, ordering, duplicates, missing intervals, numeric ranges and required fields.
6. Validate market-specific requirements such as bid/ask, volume, venue or exchange-calendar metadata.
7. Mark the snapshot `VERIFIED_REAL` only after all checks pass.
8. Generate research features from the verified snapshot without changing the raw record.
9. Keep discovery/training and confirmation data physically and logically separated.
10. Never use a synthetic fallback for an empirical result.

## No-disturbance policy

Large historical retrieval must be chunked and resumable. Failed or rate-limited retrievals pause and resume from the last verified chunk rather than restarting the entire dataset. The raw source is never modified.

Research jobs should work from immutable local/cache snapshots after acquisition so repeated analyses do not repeatedly hit the source.

## Data depth

Each domain should eventually receive enough history to study multiple regimes rather than merely one recent period. Resolution should be chosen according to the intended holding horizon and microstructure requirements. High-frequency research requires trade/quote-level data; daily equity research can begin with daily OHLCV and later add intraday data from a properly licensed provider.

## Evidence boundary

`VERIFIED_REAL` is the only provenance state permitted into empirical research. `SYNTHETIC` is for tests only. `UNVERIFIED` data remains blocked.
