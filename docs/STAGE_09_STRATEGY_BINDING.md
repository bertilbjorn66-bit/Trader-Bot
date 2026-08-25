# Stage 09 — Frozen Strategy Binding Gate

Stage 08 established the distinction between engineering readiness and a genuine paper-performance result. Stage 09 closes the next ambiguity: the live paper observer requires a concrete `Quote -> Decision` factory, but the repository currently contains only the generic evidence/risk decision kernel.

## What is frozen

The runtime contract records exact Git source fingerprints for:

- `trader_bot/decision.py`;
- `trader_bot/risk.py`;
- `trader_bot/paper_eval.py`;
- `trader_bot/paper_observation.py`;
- `trader_bot/context.py`.

It also binds the verified empirical research artifact `VERIFIED-EMPIRICAL-RESEARCH-REPORT-FINAL` by its immutable GitHub Actions artifact digest and source commit.

The contract itself is SHA-256 fingerprinted. Any change to the strategy identity/version, research artifact, or runtime source fingerprints produces a different snapshot.

## Current state

The binding is intentionally **BLOCKED** until a concrete production `Quote -> Decision` factory is bound with its own immutable identifier and source SHA.

This is not a failed strategy result. It is a fail-closed engineering condition. The system must not invent a direction, fabricate a research-to-live mapping, or silently substitute a new rule in order to start paper trading.

## Promotion rule

`StrategyBindingState.VERIFIED` is the only state permitted to start a real paper campaign. `BLOCKED` must prevent campaign start.

A paper-performance result can therefore never be attributed to an untracked or ad-hoc decision factory.

## Safety

This stage changes no broker behavior. `ExecutionGateway` remains disabled. The existing live-observation runner remains current-quote-only and non-transmitting.
