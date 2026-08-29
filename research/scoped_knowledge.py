from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trader_bot.asset_universe import AssetClass


@dataclass(frozen=True, slots=True)
class KnowledgeScope:
    """Exact scope a learned fact is allowed to influence."""

    asset_class: AssetClass
    symbol: str
    venue: str | None

    def matches(self, asset_class: AssetClass, symbol: str, venue: str | None) -> bool:
        return (
            self.asset_class is asset_class
            and self.symbol == symbol
            and (self.venue is None or self.venue == venue)
        )


@dataclass(frozen=True, slots=True)
class ScopedKnowledge:
    """Auditable learned knowledge with explicit provenance and expiry/review rules."""

    scope: KnowledgeScope
    claim: str
    evidence_count: int
    confidence: float
    observed_from: datetime
    observed_to: datetime
    learned_at: datetime
    review_after: datetime
    source_fingerprint: str

    def validate(self) -> None:
        if not self.scope.symbol:
            raise ValueError("knowledge scope symbol must be non-empty")
        if self.evidence_count <= 0:
            raise ValueError("evidence_count must be positive")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        timestamps = (self.observed_from, self.observed_to, self.learned_at, self.review_after)
        if any(ts.tzinfo is None for ts in timestamps):
            raise ValueError("knowledge timestamps must be timezone-aware")
        if self.observed_from >= self.observed_to:
            raise ValueError("observed_from must precede observed_to")
        if self.learned_at < self.observed_to:
            raise ValueError("learned_at cannot precede the end of the observed period")
        if self.review_after <= self.learned_at:
            raise ValueError("review_after must be after learned_at")
        if not self.source_fingerprint:
            raise ValueError("source_fingerprint must be non-empty")

    def is_current(self, now: datetime) -> bool:
        self.validate()
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return now < self.review_after

    def applies_to(self, asset_class: AssetClass, symbol: str, venue: str | None) -> bool:
        self.validate()
        return self.scope.matches(asset_class, symbol, venue) and symbol == self.scope.symbol


@dataclass(frozen=True, slots=True)
class RelationshipEvidence:
    """Evidence required before one market can influence another market's native reasoning."""

    source_scope: KnowledgeScope
    target_scope: KnowledgeScope
    relationship_id: str
    lag_periods: int
    regime_conditioned: bool
    sample_size: int
    stability_score: float
    approved: bool

    def validate(self) -> None:
        if not self.relationship_id:
            raise ValueError("relationship_id must be non-empty")
        if self.lag_periods < 0:
            raise ValueError("lag_periods cannot be negative")
        if self.sample_size <= 0:
            raise ValueError("sample_size must be positive")
        if not 0.0 <= self.stability_score <= 1.0:
            raise ValueError("stability_score must be in [0, 1]")
        if self.source_scope == self.target_scope:
            raise ValueError("relationship evidence must span distinct scopes")

    def can_influence(self, source: KnowledgeScope, target: KnowledgeScope) -> bool:
        self.validate()
        return self.approved and self.source_scope == source and self.target_scope == target
