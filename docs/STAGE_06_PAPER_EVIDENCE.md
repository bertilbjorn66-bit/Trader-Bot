# Stage 06 — Paper Evidence Integrity

This stage supplies the evidence boundary required for a future real paper run.

## Scope

The evidence layer records hypothetical paper-session events without connecting to a broker, transmitting orders, downloading market data, or recomputing empirical research.

## Integrity controls

Every record is bound to the paper session ID and frozen evaluation-specification fingerprint. Records are sequence-numbered, timestamp-ordered, and chained with SHA-256 hashes from a fixed genesis value. The journal can be verified before a result is accepted, and finalization is terminal.

`EvidenceBackedPaperSession` composes the existing `PaperSession` with the evidence journal so signal, order, close, rejection, and finalization events cannot be silently omitted by the calling code.

## Evidence contents

The journal retains the event kind, session ID, specification fingerprint, order identifiers, instrument/action, quantity, relevant price, spread, slippage, latency, P&L where applicable, and the original event reason.

The serialized evidence bundle is canonical JSON with sorted keys and explicit decimal string representation. The resulting bytes are deterministic for an unchanged journal.

## Promotion boundary

A passing evidence-integrity check does not mean the trading strategy passed paper trading. A real paper period still must use actual market observations, remain on the frozen research specification, satisfy the independent paper-performance gate, and remain completely non-transmitting.
