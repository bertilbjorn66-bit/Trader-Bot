from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum


class StrategyBindingState(StrEnum):
    BLOCKED = "BLOCKED"
    VERIFIED = "VERIFIED"


@dataclass(frozen=True)
class FrozenRuntimeContract:
    """Fingerprint of the exact runtime/research inputs allowed into paper trading."""

    snapshot_id: str
    strategy_id: str
    strategy_version: str
    research_artifact_name: str
    research_artifact_digest: str
    research_source_commit: str
    decision_source_sha: str
    risk_source_sha: str
    evaluation_source_sha: str
    observation_source_sha: str
    context_source_sha: str
    decision_factory_id: str = ""
    decision_factory_source_sha: str = ""

    def __post_init__(self) -> None:
        text_fields = {
            "snapshot_id": self.snapshot_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "research_artifact_name": self.research_artifact_name,
            "research_artifact_digest": self.research_artifact_digest,
            "research_source_commit": self.research_source_commit,
            "decision_source_sha": self.decision_source_sha,
            "risk_source_sha": self.risk_source_sha,
            "evaluation_source_sha": self.evaluation_source_sha,
            "observation_source_sha": self.observation_source_sha,
            "context_source_sha": self.context_source_sha,
        }
        for field, value in text_fields.items():
            if not value.strip():
                raise ValueError(f"{field} must be non-empty")
        if len(self.research_artifact_digest.removeprefix("sha256:")) != 64:
            raise ValueError("research_artifact_digest must be a SHA-256 digest")
        for field in (
            "research_source_commit",
            "decision_source_sha",
            "risk_source_sha",
            "evaluation_source_sha",
            "observation_source_sha",
            "context_source_sha",
        ):
            if len(getattr(self, field)) != 40:
                raise ValueError(f"{field} must be a 40-character Git SHA")

    @property
    def factory_bound(self) -> bool:
        return bool(self.decision_factory_id.strip() and self.decision_factory_source_sha.strip())

    def fingerprint(self) -> str:
        payload = {
            "context_source_sha": self.context_source_sha,
            "decision_factory_id": self.decision_factory_id,
            "decision_factory_source_sha": self.decision_factory_source_sha,
            "decision_source_sha": self.decision_source_sha,
            "evaluation_source_sha": self.evaluation_source_sha,
            "observation_source_sha": self.observation_source_sha,
            "research_artifact_digest": self.research_artifact_digest,
            "research_artifact_name": self.research_artifact_name,
            "research_source_commit": self.research_source_commit,
            "risk_source_sha": self.risk_source_sha,
            "snapshot_id": self.snapshot_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class StrategyBindingResult:
    state: StrategyBindingState
    snapshot_fingerprint: str
    failure_reasons: tuple[str, ...]


class StrategyBindingGate:
    """Fail-closed gate preventing paper trading with an unbound decision factory."""

    def __init__(self, contract: FrozenRuntimeContract) -> None:
        self.contract = contract
        self._fingerprint = contract.fingerprint()

    def evaluate(self) -> StrategyBindingResult:
        if self.contract.fingerprint() != self._fingerprint:
            raise RuntimeError("frozen runtime contract changed after binding gate creation")
        failures: list[str] = []
        if not self.contract.factory_bound:
            failures.append("decision_factory_not_bound")
        if failures:
            return StrategyBindingResult(
                StrategyBindingState.BLOCKED,
                self._fingerprint,
                tuple(failures),
            )
        return StrategyBindingResult(
            StrategyBindingState.VERIFIED,
            self._fingerprint,
            (),
        )
