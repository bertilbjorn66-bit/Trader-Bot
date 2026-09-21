# Intelligence Maximum-Potential Contract

## Purpose

This document defines how the Trader Bot becomes deeper without becoming more chaotic. The goal is not maximum trade frequency. The goal is maximum useful information per unit of risk and computation.

## Universal intelligence

Every asset domain uses the same reasoning faculties:

- structure
- trend and regime
- momentum
- volatility
- liquidity and execution cost
- historical similarity
- expert-family agreement
- conditional outcome distributions
- risk
- abstention

The faculties are universal. Their meanings, inputs, costs, calendars and market mechanics are domain-specific.

## Historical behavioral memory

Each instrument maintains chronological behavioral memory. Comparable historical observations are selected only from timestamps strictly before the decision timestamp. Context summaries retain expectancy, win rate, profit factor, dispersion and positive-observation counts.

This memory is descriptive evidence, not an automatic strategy promotion mechanism.

## Context transition intelligence

The broader research layer may analyze state transitions, cross-market relationships, calibration, drift and walk-forward behavior. A transition is not treated as a signal unless its future-outcome evidence has been independently established.

## Cross-asset comparison

Opportunities are compared only after each domain supplies an asset-native expected return, uncertainty, liquidity quality, cost burden, risk budget and correlation exposure. Ranking is portfolio-aware and cannot override the domain research contract.

## Anti-overfitting controls

Research must record the number of variants/trials considered and measure the distance between the selected result and the broader trial distribution. Parameter perturbations are treated as robustness evidence rather than opportunities to retune the confirmation set.

The lightweight selection-risk statistic in the research package is a screening control, not a formal probability-of-backtest-overfitting estimator. A future formal PBO/CSCV implementation must remain separately identified.

## Model health

The model has four health states:

`HEALTHY -> CAUTIOUS -> DEFENSIVE -> OBSERVATION_ONLY`

Health deterioration is driven by changes in expectancy, volatility and error behavior. Health state can reduce or stop downstream activity; it cannot force a recovery trade or automatically retune a validated candidate.

## Verification discipline

Every new intelligence component must have:

1. deterministic inputs and outputs
2. chronological safety
3. explicit failure behavior
4. unit/regression tests
5. empirical data provenance before financial interpretation
6. separation from live execution

## Promotion boundary

The new intelligence modules do not make an instrument tradable. They remain subordinate to the existing research, risk, portfolio, safety and promotion gates.

The execution boundary remains disabled until independent research and safety authorization are completed.
