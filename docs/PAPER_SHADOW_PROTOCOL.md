# Trader Bot — Paper/Shadow Protocol

This protocol defines the engineering boundary between the validated research foundation and any future broker-connected shadow session.

## Frozen specification

A paper session must start from one immutable `PaperEvaluationSpec`. Its fingerprint is recorded with the evaluation result. The strategy identifier, strategy version, research reference, minimum closed-trade requirement, and maximum session-loss threshold cannot be changed during a session.

Changing the specification creates a new session and a new evaluation fingerprint. It is not a continuation of the previous session.

## Paper execution

Paper orders are hypothetical only. They use the existing decision and safety path and record entry/exit prices, spread, slippage, latency, evidence samples, and P&L. The execution gateway must remain `DISABLED`.

## Evaluation

Only `CLOSED` paper orders are evaluated. Closed orders must have unique IDs and chronological timestamps. The evaluator reports:

- closed-trade count;
- wins and losses;
- total P&L;
- expectancy;
- profit factor when losses exist;
- maximum drawdown;
- frozen specification fingerprint;
- explicit failure reasons.

A session fails when its frozen minimum closed-trade requirement is not met, when the frozen maximum session-loss threshold is breached, or when it has no closed trades.

## Research boundary

The paper/shadow layer does not download research data, recompute empirical research, retune thresholds, or rewrite completed research artifacts. Paper results are evaluated against the frozen specification and cannot be used to silently alter that same session's contract.

## Live boundary

Paper and shadow capability never grants broker-order transmission. Live execution remains impossible until the independent promotion requirements in `docs/FINAL_VALIDATION_GATES.md` are satisfied and explicit human approval is provided.
