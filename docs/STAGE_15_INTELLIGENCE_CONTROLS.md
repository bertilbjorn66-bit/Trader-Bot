# Stage 15 — Intelligence Controls Layer

This stage implements the remaining reliability controls identified in the market-intelligence roadmap.

## Controls

- **Execution-cost realism:** spread, slippage, latency and financing are explicit; gross expectancy can never be treated as net expectancy.
- **Cross-pair intelligence:** return correlation is explicit and bounded; relationship calculations require aligned observations.
- **Macro/event regimes:** event windows carry an information-known timestamp and reject look-ahead.
- **Probability calibration:** Brier score and expected calibration error are first-class metrics.
- **Drift detection:** mean, volatility and missingness shifts can force a degraded state.
- **Walk-forward governance:** training windows must end strictly before validation windows.
- **Expert routing:** specialist opinions are aggregated only when sufficiently confident; disagreement forces abstention.

## Safety rule

These controls are analytical and decision-governance primitives. They do not enable broker transmission, create credentials, or authorize live execution. They are intended to become prerequisites for future paper/shadow promotion once a legitimate strategy certificate exists.

## Important limitation

A control being implemented and passing unit tests does **not** prove a trading strategy is profitable. Profitability still requires an independent, out-of-sample evaluation using genuine future information timing and realistic transaction costs.
