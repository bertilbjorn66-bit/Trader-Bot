# Stage 13 — Deep Context Intelligence Atlas

## Purpose

Build a descriptive market-knowledge artifact from the already verified final holdout target records. This stage does **not** replace, mutate, or re-run the completed empirical, holdout, or Survival V2 gates.

## What the atlas learns

For every supported pair it maps conditional behavior across:

- pair and forecast horizon;
- market regime;
- trading session;
- weekday and UTC hour block;
- analogue-agreement strength;
- similarity distance;
- long/short direction.

Each context cell records sample size, expectancy, profit factor, win rate, median outcome, maximum drawdown, year-by-year stability, bootstrap expectancy interval, and a conservative state:

- `STRONG_CONTEXT` — robust enough to study further;
- `WATCH_CONTEXT` — positive but not sufficiently robust;
- `NO_TRADE` — evidence is materially unfavorable;
- `UNKNOWN` — insufficient observations.

## Important boundary

The atlas is a **descriptive intelligence layer**, not a promotion engine. No candidate is selected from it, no runtime factory is altered, and no live authorization is possible from this artifact.

## Source discipline

The workflow restores `VERIFIED-FINAL-HOLDOUT-RESEARCH` from the previously completed run. The holdout file is treated as immutable input. This stage performs a new contextual analysis over those records; it does not redownload market data and does not overwrite the original research result.

## Future extensions

The next intelligence layers should add cross-pair lead/lag relationships, macro/news-event regimes, liquidity proxies, structural support/resistance state, volatility-shock transitions, and online regime-change detection. These must remain causally ordered and independently validated before they can influence the decision factory.
