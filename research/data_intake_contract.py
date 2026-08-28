from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Mapping

from trader_bot.asset_universe import AssetClass


class ProvenanceStatus(StrEnum):
    VERIFIED_REAL = "VERIFIED_REAL"
    UNVERIFIED = "UNVERIFIED"
    SYNTHETIC = "SYNTHETIC"


@dataclass(frozen=True, slots=True)
class DataSnapshot:
    """Metadata for one immutable raw-data snapshot before feature generation."""

    snapshot_id: str
    source_id: str
    asset_class: AssetClass
    symbol: str
    resolution: str
    start_timestamp: int
    end_timestamp: int
    row_count: int
    content_sha256: str
    provenance: ProvenanceStatus
    fields: frozenset[str]

    def validate(self) -> None:
        if not self.snapshot_id.strip() or not self.source_id.strip():
            raise ValueError("snapshot and source identifiers must be non-empty")
        if not self.symbol.strip():
            raise ValueError("symbol must be non-empty")
        if self.start_timestamp > self.end_timestamp:
            raise ValueError("data interval must be chronological")
        if self.row_count <= 0:
            raise ValueError("row_count must be positive")
        if len(self.content_sha256) != 64:
            raise ValueError("content_sha256 must be a SHA-256 hex digest")
        try:
            int(self.content_sha256, 16)
        except ValueError as exc:
            raise ValueError("content_sha256 must be hexadecimal") from exc
        if self.provenance is not ProvenanceStatus.VERIFIED_REAL:
            raise ValueError("only VERIFIED_REAL snapshots may enter empirical research")


def snapshot_digest(rows: Mapping[str, object]) -> str:
    """Create a stable digest for deterministic metadata used in tests/manifests."""

    encoded = repr(sorted(rows.items())).encode("utf-8")
    return sha256(encoded).hexdigest()
