# Stage 11 — Operational safety readiness

This stage makes the production operational controls executable and testable without enabling live orders.

## Controls

- Emergency stop is fail-closed and clears any human approval when triggered.
- Daily loss is tracked in the paper/shadow runtime and automatically triggers the emergency stop at the configured limit.
- Quote freshness and maximum spread are evaluated before paper/shadow operation.
- Human approval is a separate live-authorization latch and does not block safe paper operation.
- Credentials are required through runtime environment injection and forbidden from hard-coded source literals.
- The Stage 11 specification is fingerprinted and runtime mutation is rejected.
- Live authorization remains impossible because `live_orders_allowed` is hard-coded false in this stage.

Passing this engineering stage means the operational controls are present and tested. It does not mean a strategy has passed paper or shadow performance.
