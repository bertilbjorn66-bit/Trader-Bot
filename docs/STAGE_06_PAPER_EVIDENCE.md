# Stage 06 — Paper Evidence Integrity

This stage provides an append-only, tamper-evident evidence journal for future paper sessions.

It does not connect to a broker, transmit orders, download market data, or recompute research. A production paper run must supply real observations through the existing paper decision path and retain the frozen evaluation specification fingerprint captured at session start.

Evidence is ordered, timestamp-validated, bound to the session and frozen specification fingerprint, and hash-chained from a deterministic genesis value. Finalization is terminal: after the finalization record, additional evidence is rejected.
