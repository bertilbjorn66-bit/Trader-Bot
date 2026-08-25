# Stage 19 — Intelligence Governance

This stage closes two remaining intelligence-quality gaps without introducing a new execution path.

## Event provenance

Each event carries `release_at`, `known_at`, and a revision number. The validator rejects look-ahead and invalid revisions. This provides the data contract required for future macro/news regime ingestion without allowing future information into historical analysis.

## Probability calibration

A deterministic logistic calibrator can be fit on a training split and evaluated on a separate validation split. The validation object explicitly records that no information leakage is allowed.

Calibration metrics remain diagnostic until they are validated under a larger, strictly chronological experiment. They do not authorize trading.
