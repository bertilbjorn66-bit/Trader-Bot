from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .risk import OutcomeSummary, RiskLimits, passes


class Action(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"
    NO_TRADE = "NO_TRADE"


@dataclass(frozen=True)
class Decision:
    action: Action
    confidence: float
    reason: str
    evidence_samples: int


def decide(summary: OutcomeSummary | None, direction: Action, limits: RiskLimits) -> Decision:
    if direction not in (Action.BUY, Action.SELL):
        raise ValueError("direction must be BUY or SELL")
    if summary is None:
        return Decision(Action.NO_TRADE, 0.0, "No validated historical evidence is available.", 0)
    if not passes(summary, limits):
        return Decision(
            Action.WAIT,
            summary.win_probability,
            "Evidence does not satisfy the configured probability/expected-return/risk gates.",
            summary.samples,
        )
    return Decision(
        direction,
        summary.win_probability,
        "Evidence passed all configured research risk gates. This is not a profit guarantee.",
        summary.samples,
    )
