from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True, slots=True)
class Opportunity:
    symbol: str
    asset_class: str
    expected_return: float
    uncertainty: float
    risk_fraction: float
    liquidity_score: float
    cost_fraction: float
    correlation_exposure: float


@dataclass(frozen=True, slots=True)
class RankedOpportunity:
    opportunity: Opportunity
    score: float
    rank: int
    reasons: tuple[str, ...]


def rank_opportunities(opportunities: list[Opportunity]) -> tuple[RankedOpportunity, ...]:
    if not opportunities:
        return ()
    for opportunity in opportunities:
        if opportunity.expected_return < 0:
            raise ValueError("expected_return cannot be negative")
        for name, value in (
            ("uncertainty", opportunity.uncertainty),
            ("risk_fraction", opportunity.risk_fraction),
            ("liquidity_score", opportunity.liquidity_score),
            ("cost_fraction", opportunity.cost_fraction),
            ("correlation_exposure", opportunity.correlation_exposure),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")

    scored: list[tuple[float, Opportunity, tuple[str, ...]]] = []
    for opportunity in opportunities:
        uncertainty_penalty = 1.0 - opportunity.uncertainty
        liquidity_factor = opportunity.liquidity_score
        cost_factor = 1.0 - opportunity.cost_fraction
        concentration_factor = 1.0 - opportunity.correlation_exposure
        risk_efficiency = opportunity.expected_return / sqrt(max(opportunity.risk_fraction, 1e-12))
        score = max(0.0, risk_efficiency) * uncertainty_penalty * liquidity_factor * cost_factor * concentration_factor
        reasons = (
            f"risk_efficiency={risk_efficiency:.6f}",
            f"uncertainty_factor={uncertainty_penalty:.6f}",
            f"liquidity_factor={liquidity_factor:.6f}",
            f"cost_factor={cost_factor:.6f}",
            f"concentration_factor={concentration_factor:.6f}",
        )
        scored.append((score, opportunity, reasons))

    scored.sort(key=lambda item: (-item[0], item[1].asset_class, item[1].symbol))
    return tuple(
        RankedOpportunity(opportunity, score, index + 1, reasons)
        for index, (score, opportunity, reasons) in enumerate(scored)
    )
