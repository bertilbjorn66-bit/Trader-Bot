from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from trader_bot.asset_universe import AssetClass, InstrumentProfile


class ResearchMode(StrEnum):
    HISTORICAL = "HISTORICAL"
    WALK_FORWARD = "WALK_FORWARD"
    CONFIRMATION = "CONFIRMATION"


@dataclass(frozen=True, slots=True)
class ResearchContract:
    asset_class: AssetClass
    mode: ResearchMode
    empirical_only: bool = True
    allow_future_labels: bool = False
    allow_confirmation_learning: bool = False
    require_transaction_costs: bool = True
    require_liquidity_filter: bool = True
    require_calendar_awareness: bool = False
    require_volume_features: bool = False

    def validate_profile(self, profile: InstrumentProfile) -> None:
        if profile.asset_class is not self.asset_class:
            raise ValueError("research contract asset class does not match instrument profile")
        if not self.empirical_only or self.allow_future_labels or self.allow_confirmation_learning:
            raise ValueError("research contracts must remain empirical and leakage-safe")
        if not self.require_transaction_costs or not self.require_liquidity_filter:
            raise ValueError("transaction-cost modeling and liquidity filtering are mandatory")
        if profile.rules.requires_exchange_calendar and not self.require_calendar_awareness:
            raise ValueError("exchange-traded instruments require calendar-aware research")
        if profile.rules.volume_is_first_class and not self.require_volume_features:
            raise ValueError("volume-sensitive instruments require volume-aware research")


def contract_for(profile: InstrumentProfile) -> ResearchContract:
    return ResearchContract(
        asset_class=profile.asset_class,
        mode=ResearchMode.HISTORICAL,
        require_calendar_awareness=profile.rules.requires_exchange_calendar,
        require_volume_features=profile.rules.volume_is_first_class,
    )
