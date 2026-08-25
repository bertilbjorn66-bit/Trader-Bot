# Stage 10 — Promotion-aware decision factory

The decision factory is now a concrete adapter around the repository's existing `decide()` kernel.

It is deliberately two-state:

- `BLOCKED`: emits `NO_TRADE` and records the reason.
- `ELIGIBLE`: may emit `BUY`/`SELL` only when the frozen runtime contract is bound and an immutable promotion certificate proves every pre-paper gate passed.

The factory never invents a direction from raw price movement and never manufactures evidence. Its per-instrument inputs are frozen `OutcomeSummary` and `RiskLimits` values.

The current authoritative enriched robustness artifact reported 10 finalists but 0 promotion-eligible candidates. Therefore `current_factory()` is intentionally `BLOCKED` and cannot produce a trade.

This is an engineering-complete factory boundary. A future strategy becomes eligible only by supplying a new immutable promotion certificate and a new frozen runtime contract that match the verified research artifact/source commit and bind the factory itself.
