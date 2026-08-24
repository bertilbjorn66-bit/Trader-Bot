# Stage 06 — Paper Evidence Integrity

The evidence layer is the audit boundary for a future real paper period. It records hypothetical session events without broker connection, broker transmission, market-data download, or empirical research recomputation.

Each evidence record is bound to the session ID and frozen evaluation-specification fingerprint, ordered by sequence and timestamp, and chained with SHA-256 hashes from a fixed genesis value. The journal can be verified before acceptance, serializes deterministically, and becomes terminal at finalization.

`EvidenceBackedPaperSession` composes the existing `PaperSession` with the journal so signal, order, close/rejection, and finalization events are captured automatically.

A passing integrity check is not a strategy-performance pass. The eventual real paper period must still use actual observations, remain on the frozen research specification, satisfy the independent paper-performance gate, and keep broker transmission disabled.
