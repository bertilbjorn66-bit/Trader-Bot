from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import Sequence


@dataclass(frozen=True)
class OutcomeSummary:
    samples: int
    win_probability: float
    loss_probability: float
    expected_return: float
    average_win: float
    average_loss: float
    max_adverse: float
    max_favorable: float


@dataclass(frozen=True)
class RiskLimits:
    minimum_samples: int = 200
    minimum_win_probability: float = 0.55
    minimum_expected_return: float = 0.0
    maximum_adverse: float = 1.0


def summarize(returns: Sequence[float], adverse: Sequence[float], favorable: Sequence[float]) -> OutcomeSummary | None:
    if not returns:
        return None
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]
    return OutcomeSummary(
        samples=len(returns),
        win_probability=len(wins) / len(returns),
        loss_probability=len(losses) / len(returns),
        expected_return=fmean(returns),
        average_win=fmean(wins) if wins else 0.0,
        average_loss=fmean(losses) if losses else 0.0,
        max_adverse=max(adverse) if adverse else 0.0,
        max_favorable=max(favorable) if favorable else 0.0,
    )


def passes(summary: OutcomeSummary | None, limits: RiskLimits) -> bool:
    if summary is None or summary.samples < limits.minimum_samples:
        return False
    return (
        summary.win_probability >= limits.minimum_win_probability
        and summary.expected_return >= limits.minimum_expected_return
        and summary.max_adverse <= limits.maximum_adverse
    )
