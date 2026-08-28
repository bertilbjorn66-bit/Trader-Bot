from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class AssetClass(StrEnum):
    FOREX = "FOREX"
    CRYPTO = "CRYPTO"
    METAL = "METAL"
    COMMODITY = "COMMODITY"
    EQUITY = "EQUITY"
    INDEX = "INDEX"


class TradingSession(StrEnum):
    TWENTY_FOUR_SEVEN = "24_7"
    WEEKDAY_CONTINUOUS = "WEEKDAY_CONTINUOUS"
    EXCHANGE_HOURS = "EXCHANGE_HOURS"
    EXCHANGE_EXTENDED = "EXCHANGE_EXTENDED"


class ResearchStatus(StrEnum):
    EXISTING_VALIDATED_DOMAIN = "EXISTING_VALIDATED_DOMAIN"
    RESEARCH_PLANNED = "RESEARCH_PLANNED"
    RESEARCH_ONLY = "RESEARCH_ONLY"


@dataclass(frozen=True, slots=True)
class CostProfile:
    """Execution-cost assumptions expressed in instrument-native units."""

    typical_spread: float | None
    stress_spread: float | None
    slippage_rate: float = 0.0
    commission_rate: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (
            ("typical_spread", self.typical_spread),
            ("stress_spread", self.stress_spread),
            ("slippage_rate", self.slippage_rate),
            ("commission_rate", self.commission_rate),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True, slots=True)
class MarketRules:
    session: TradingSession
    supports_shorting: bool
    has_funding_or_carry: bool
    event_gap_sensitive: bool
    volume_is_first_class: bool
    requires_exchange_calendar: bool


@dataclass(frozen=True, slots=True)
class InstrumentProfile:
    """Immutable instrument contract consumed by universal market services."""

    symbol: str
    asset_class: AssetClass
    venue: str
    quote_currency: str
    price_increment: float
    contract_multiplier: float
    research_status: ResearchStatus
    cost: CostProfile
    rules: MarketRules

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must be non-empty")
        if self.symbol != self.symbol.upper():
            raise ValueError("symbol must be normalized uppercase")
        if not self.venue.strip():
            raise ValueError("venue must be non-empty")
        if not self.quote_currency.strip():
            raise ValueError("quote_currency must be non-empty")
        if self.price_increment <= 0:
            raise ValueError("price_increment must be positive")
        if self.contract_multiplier <= 0:
            raise ValueError("contract_multiplier must be positive")

    @property
    def is_research_ready(self) -> bool:
        return self.research_status is ResearchStatus.EXISTING_VALIDATED_DOMAIN


class AssetRegistry:
    """Read-only instrument registry shared by data, research and risk layers."""

    def __init__(self, profiles: Mapping[str, InstrumentProfile]) -> None:
        normalized = {}
        for key, profile in profiles.items():
            if key != profile.symbol:
                raise ValueError("registry key must match profile.symbol")
            if key.upper() != key:
                raise ValueError("instrument symbols must be uppercase")
            normalized[key] = profile
        self._profiles = MappingProxyType(dict(normalized))

    def get(self, symbol: str) -> InstrumentProfile | None:
        return self._profiles.get(symbol.upper())

    def require(self, symbol: str) -> InstrumentProfile:
        profile = self.get(symbol)
        if profile is None:
            raise KeyError(f"Unknown instrument: {symbol}")
        return profile

    def by_asset_class(self, asset_class: AssetClass) -> tuple[InstrumentProfile, ...]:
        return tuple(profile for profile in self._profiles.values() if profile.asset_class is asset_class)

    def symbols(self) -> tuple[str, ...]:
        return tuple(self._profiles)


def default_asset_registry() -> AssetRegistry:
    """Return the initial multi-asset universe with validation-safe defaults."""

    forex_cost = CostProfile(typical_spread=None, stress_spread=None)
    fx_rules = MarketRules(
        session=TradingSession.WEEKDAY_CONTINUOUS,
        supports_shorting=True,
        has_funding_or_carry=True,
        event_gap_sensitive=True,
        volume_is_first_class=False,
        requires_exchange_calendar=False,
    )

    crypto_rules = MarketRules(
        session=TradingSession.TWENTY_FOUR_SEVEN,
        supports_shorting=True,
        has_funding_or_carry=True,
        event_gap_sensitive=False,
        volume_is_first_class=True,
        requires_exchange_calendar=False,
    )
    crypto_cost = CostProfile(typical_spread=None, stress_spread=None)

    metal_rules = MarketRules(
        session=TradingSession.WEEKDAY_CONTINUOUS,
        supports_shorting=True,
        has_funding_or_carry=True,
        event_gap_sensitive=True,
        volume_is_first_class=False,
        requires_exchange_calendar=False,
    )

    equity_rules = MarketRules(
        session=TradingSession.EXCHANGE_HOURS,
        supports_shorting=True,
        has_funding_or_carry=False,
        event_gap_sensitive=True,
        volume_is_first_class=True,
        requires_exchange_calendar=True,
    )
    equity_cost = CostProfile(typical_spread=None, stress_spread=None)

    profiles: dict[str, InstrumentProfile] = {}
    for symbol, quote_currency, increment in (
        ("EUR/USD", "USD", 0.0001),
        ("GBP/USD", "USD", 0.0001),
        ("USD/JPY", "JPY", 0.01),
        ("AUD/USD", "USD", 0.0001),
        ("USD/CAD", "CAD", 0.0001),
        ("USD/CHF", "CHF", 0.0001),
        ("NZD/USD", "USD", 0.0001),
        ("EUR/JPY", "JPY", 0.01),
        ("GBP/JPY", "JPY", 0.01),
    ):
        profiles[symbol] = InstrumentProfile(
            symbol=symbol,
            asset_class=AssetClass.FOREX,
            venue="Dukascopy",
            quote_currency=quote_currency,
            price_increment=increment,
            contract_multiplier=1.0,
            research_status=ResearchStatus.EXISTING_VALIDATED_DOMAIN,
            cost=forex_cost,
            rules=fx_rules,
        )

    for symbol in ("BTC/USD", "ETH/USD", "SOL/USD"):
        profiles[symbol] = InstrumentProfile(
            symbol=symbol,
            asset_class=AssetClass.CRYPTO,
            venue="MULTI_VENUE_PENDING",
            quote_currency="USD",
            price_increment=0.01,
            contract_multiplier=1.0,
            research_status=ResearchStatus.RESEARCH_ONLY,
            cost=crypto_cost,
            rules=crypto_rules,
        )

    for symbol, increment in (("XAU/USD", 0.01), ("XAG/USD", 0.001)):
        profiles[symbol] = InstrumentProfile(
            symbol=symbol,
            asset_class=AssetClass.METAL,
            venue="MULTI_VENUE_PENDING",
            quote_currency="USD",
            price_increment=increment,
            contract_multiplier=1.0,
            research_status=ResearchStatus.RESEARCH_ONLY,
            cost=CostProfile(typical_spread=None, stress_spread=None),
            rules=metal_rules,
        )

    for symbol in ("NVDA", "MSFT", "AAPL", "AMZN", "META"):
        profiles[symbol] = InstrumentProfile(
            symbol=symbol,
            asset_class=AssetClass.EQUITY,
            venue="EXCHANGE_PENDING",
            quote_currency="USD",
            price_increment=0.01,
            contract_multiplier=1.0,
            research_status=ResearchStatus.RESEARCH_ONLY,
            cost=equity_cost,
            rules=equity_rules,
        )

    return AssetRegistry(profiles)
