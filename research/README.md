# Quantitative Research Pipeline

This directory contains research-only infrastructure. It is intentionally separate from the audited trading core and does not authorize or submit live orders.

## Evidence boundary

Synthetic data is used only for deterministic pipeline testing. It has **no financial meaning**. Any empirical performance claim requires real market data and must be labeled `COMPUTED_FROM_REAL_DATA` only after the data source, timestamp handling, BID/ASK execution model, walk-forward design, leakage checks, and out-of-sample test are verified.

## Core flow

`real/synthetic bars -> state features -> historical similarity -> outcomes/MFE/MAE -> probability -> expectancy/risk -> validation/report`

## Required gates before live use

1. Real data quality audit passes.
2. Feature definitions are timestamp-safe.
3. Research parameters are selected without test-period information.
4. Walk-forward and strict out-of-sample tests pass.
5. Transaction costs and realistic BID/ASK execution are included.
6. Robustness and data-mining controls pass.
7. Engineering safety gates independently authorize any later execution path.

## Important limitation

This package deliberately does not contain empirical results because the current environment does not have a connected historical Dukascopy dataset. Synthetic test output must never be interpreted as trading performance.
