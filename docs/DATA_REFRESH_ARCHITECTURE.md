# Automatic Real-Market Data Refresh Architecture

## Purpose

Every supported asset class must maintain its own verified market-data state and refresh only the interval that has become available since the last accepted snapshot.

## Domain sources

- Forex: Dukascopy historical quotes.
- Metals: Dukascopy historical quotes where the instrument is available.
- Crypto: Binance public historical market-data archives/APIs.
- Equities: Stooq for the initial end-of-day research layer; a licensed/provider-specific intraday source must be selected before intraday equity decisions are enabled.
- Indices: Stooq for the initial end-of-day research layer; a licensed/provider-specific intraday source must be selected before intraday index decisions are enabled.
- Commodities: a provider-specific source must be selected per instrument before the instrument can become research-eligible.

## Refresh loop

1. Read the last accepted snapshot for the instrument/domain.
2. Determine the latest provider timestamp available.
3. Request only the missing interval.
4. Validate timestamps, ordering, OHLC relationships, required fields, and provider identity.
5. Compute an integrity hash and attach provenance.
6. Persist the verified snapshot outside the public Git repository.
7. Expose the new snapshot to the intelligence layer only after the integrity gate passes.
8. Mark the domain stale/blocked when refresh fails or the source falls outside its maximum staleness window.

## Non-negotiable properties

- Raw market data is never committed to this public repository.
- Refresh credentials, if a provider requires them, are stored only in a protected environment.
- A failed refresh never causes fallback to synthetic data.
- A stale feed never silently becomes eligible for a current decision.
- Refresh is incremental and resumable; it must not repeatedly download full history.
- Each domain has independent freshness and provider state; one provider outage must not congest or halt unrelated domains.
- Research reads immutable snapshots so a refresh cannot mutate the dataset being evaluated mid-run.

## Privacy boundary

This public repository must not contain private research evidence, proprietary model weights, private feature stores, broker credentials, or production execution configuration. Those assets belong in the private runtime/research environment.

## Phase boundary

Automatic live-data refresh is an infrastructure capability first. It does not itself authorize trading. Asset-specific historical learning and profitability validation remain separate gates.
