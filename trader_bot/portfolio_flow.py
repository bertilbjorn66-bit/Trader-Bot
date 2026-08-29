from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .asset_universe import AssetClass
from .market_flow import FlowAssessment, FlowState


@dataclass(frozen=True, slots=True)
class PortfolioLimits:
    max_open_positions: int = 8
    max_total_risk_fraction: float = 0.02
    max_asset_class_fraction: float = 0.01
    max_single_position_fraction: float = 0.005

    def __post_init__(self) -> None:
        if self.max_open_positions <= 0:
            raise ValueError("max_open_positions must be positive")
        for name, value in (("max_total_risk_fraction", self.max_total_risk_fraction), ("max_asset_class_fraction", self.max_asset_class_fraction), ("max_single_position_fraction", self.max_single_position_fraction)):
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if self.max_single_position_fraction > self.max_asset_class_fraction:
            raise ValueError("single-position risk cannot exceed asset-class risk")
        if self.max_asset_class_fraction > self.max_total_risk_fraction:
            raise ValueError("asset-class risk cannot exceed total risk")


@dataclass(frozen=True, slots=True)
class PositionRisk:
    symbol: str
    asset_class: AssetClass
    risk_fraction: float

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must be non-empty")
        if not isfinite(self.risk_fraction) or self.risk_fraction < 0:
            raise ValueError("risk_fraction must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    open_positions: tuple[PositionRisk, ...] = ()

    def __post_init__(self) -> None:
        symbols = [position.symbol.upper() for position in self.open_positions]
        if len(symbols) != len(set(symbols)):
            raise ValueError("portfolio snapshot cannot contain duplicate symbols")

    @property
    def total_risk(self) -> float:
        return sum(position.risk_fraction for position in self.open_positions)

    def risk_for_asset_class(self, asset_class: AssetClass) -> float:
        return sum(position.risk_fraction for position in self.open_positions if position.asset_class is asset_class)


@dataclass(frozen=True, slots=True)
class AllocationDecision:
    allowed: bool
    risk_fraction: float
    reason: str


def allocate(symbol: str, asset_class: AssetClass, assessment: FlowAssessment, snapshot: PortfolioSnapshot, limits: PortfolioLimits | None = None) -> AllocationDecision:
    active_limits = limits if limits is not None else PortfolioLimits()
    normalized_symbol = symbol.upper()
    class_risk = snapshot.risk_for_asset_class(asset_class)
    if any(position.symbol.upper() == normalized_symbol for position in snapshot.open_positions):
        return AllocationDecision(False, 0.0, "position_already_open")
    if len(snapshot.open_positions) >= active_limits.max_open_positions:
        return AllocationDecision(False, 0.0, "position_count_limit_reached")
    if snapshot.total_risk >= active_limits.max_total_risk_fraction:
        return AllocationDecision(False, 0.0, "portfolio_risk_limit_reached")
    if class_risk >= active_limits.max_asset_class_fraction:
        return AllocationDecision(False, 0.0, "asset_class_risk_limit_reached")
    if assessment.state is not FlowState.READY:
        return AllocationDecision(False, 0.0, f"flow_state_{assessment.state.lower()}")
    available_total = active_limits.max_total_risk_fraction - snapshot.total_risk
    available_class = active_limits.max_asset_class_fraction - class_risk
    granted = min(active_limits.max_single_position_fraction, available_total, available_class, assessment.risk_budget_fraction * active_limits.max_single_position_fraction)
    if granted <= 0:
        return AllocationDecision(False, 0.0, "no_risk_budget_available")
    return AllocationDecision(True, granted, "bounded_portfolio_risk_budget_granted")
