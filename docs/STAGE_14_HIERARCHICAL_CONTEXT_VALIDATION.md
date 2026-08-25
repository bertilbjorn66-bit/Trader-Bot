# Stage 14 — Hierarchical Context Validation

This stage tests broader market contexts after Stage 13 found no confirmation-level `STRONG_CONTEXT` cells.

## Safety model

- Uses only `VERIFIED-FINAL-HOLDOUT-RESEARCH` from the existing run.
- Does not redownload market data.
- Discovery data selects candidates; confirmation data only evaluates frozen candidates.
- Uses three predefined context hierarchies rather than arbitrary post-hoc combinations.
- Carries at most 20 discovery candidates per hierarchy into confirmation.
- Requires at least 100 confirmation observations for promotion-level scoring.
- Requires positive expectancy, PF > 1, a positive lower bootstrap bound, and positive expectancy in at least 67% of observed years for `STRONG_CONTEXT`.
- Explicitly records live authorization as disabled.
- Hashes the input before and after analysis to prove immutability.

## Bootstrap hardening

The bootstrap implementation uses independent reproducible resampling with a seeded PRNG. It does **not** use permutation resampling; therefore bootstrap confidence intervals can vary across replicates and are meaningful for the intended uncertainty check.

## Interpretation

A broader context that survives confirmation is still not a trading strategy. It remains a research context until it independently passes subsequent robustness, paper-trading, execution-cost and survival gates.
