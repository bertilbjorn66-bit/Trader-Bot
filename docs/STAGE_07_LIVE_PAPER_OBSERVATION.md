# Stage 07 — Live-Observation Paper Runner

This stage connects the completed paper session/evidence boundary to the repository's existing `MarketDataProvider.current_quotes()` interface.

The runner is deliberately provider-agnostic and non-transmitting:

- it uses current quotes only;
- it does not call `historical_bars()`;
- provider health must pass before an observation is accepted;
- quote freshness, future timestamp skew, and maximum spread are enforced;
- rejected observations are journaled with a tamper-evident SHA-256 chain;
- accepted observations are passed into the frozen decision factory;
- BUY/SELL decisions become hypothetical paper orders only;
- `ExecutionGateway` remains `DISABLED` and no broker adapter is introduced;
- the frozen `PaperEvaluationSpec` remains the contract for the full session.

This implementation makes the repository ready to conduct a genuine paper observation period when an appropriate current-quote provider is configured. Passing this engineering gate does **not** constitute a paper-performance pass; actual observations and the independent paper-performance gate are still required before shadow execution.
