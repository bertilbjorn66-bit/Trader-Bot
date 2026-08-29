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


def _add_profiles(
    profiles: dict[str, InstrumentProfile],
    symbols: tuple[str, ...],
    *,
    asset_class: AssetClass,
    venue: str,
    quote_currency: str,
    price_increment: float,
    research_status: ResearchStatus,
    cost: CostProfile,
    rules: MarketRules,
) -> None:
    for symbol in symbols:
        profiles[symbol] = InstrumentProfile(
            symbol=symbol,
            asset_class=asset_class,
            venue=venue,
            quote_currency=quote_currency,
            price_increment=price_increment,
            contract_multiplier=1.0,
            research_status=research_status,
            cost=cost,
            rules=rules,
        )


def default_asset_registry() -> AssetRegistry:
    """Return the initial multi-asset universe with validation-safe defaults.

    The registry is deliberately broad: each asset class has representative
    instruments, while only the existing Forex domain is empirically validated.
    New domains remain research-only until their own evidence gates pass.
    """

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
    metal_rules = MarketRules(
        session=TradingSession.WEEKDAY_CONTINUOUS,
        supports_shorting=True,
        has_funding_or_carry=True,
        event_gap_sensitive=True,
        volume_is_first_class=False,
        requires_exchange_calendar=False,
    )
    commodity_rules = MarketRules(
        session=TradingSession.WEEKDAY_CONTINUOUS,
        supports_shorting=True,
        has_funding_or_carry=True,
        event_gap_sensitive=True,
        volume_is_first_class=True,
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
    index_rules = MarketRules(
        session=TradingSession.EXCHANGE_HOURS,
        supports_shorting=True,
        has_funding_or_carry=False,
        event_gap_sensitive=True,
        volume_is_first_class=True,
        requires_exchange_calendar=True,
    )

    profiles: dict[str, InstrumentProfile] = {}

    _add_profiles(
        profiles,
        ("EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "USD/CHF", "NZD/USD", "EUR/JPY", "GBP/JPY"),
        asset_class=AssetClass.FOREX,
        venue="Dukascopy",
        quote_currency="USD",
        price_increment=0.0001,
        research_status=ResearchStatus.EXISTING_VALIDATED_DOMAIN,
        cost=forex_cost,
        rules=fx_rules,
    )
    for symbol in ("USD/JPY", "EUR/JPY", "GBP/JPY"):
        profiles[symbol] = InstrumentProfile(
            symbol=symbol,
            asset_class=AssetClass.FOREX,
            venue="Dukascopy",
            quote_currency="JPY",
            price_increment=0.01,
            contract_multiplier=1.0,
            research_status=ResearchStatus.EXISTING_VALIDATED_DOMAIN,
            cost=forex_cost,
            rules=fx_rules,
        )

    _add_profiles(
        profiles,
        ("BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD", "ADA/USD", "DOGE/USD", "AVAX/USD", "LINK/USD"),
        asset_class=AssetClass.CRYPTO,
        venue="Binance",
        quote_currency="USD",
        price_increment=0.01,
        research_status=ResearchStatus.RESEARCH_ONLY,
        cost=CostProfile(typical_spread=None, stress_spread=None),
        rules=crypto_rules,
    )

    _add_profiles(
        profiles,
        ("XAU/USD", "XAG/USD", "XPT/USD", "XPD/USD"),
        asset_class=AssetClass.METAL,
        venue="Dukascopy",
        quote_currency="USD",
        price_increment=0.01,
        research_status=ResearchStatus.RESEARCH_ONLY,
        cost=CostProfile(typical_spread=None, stress_spread=None),
        rules=metal_rules,
    )

    commodity_increments = {
        "BRENT.CMD/USD": 0.01,
        "LIGHT.CMD/USD": 0.01,
        "GAS.CMD/USD": 0.001,
        "COPPER.CMD/USD": 0.001,
        "DIESEL.CMD/USD": 0.01,
        "COFFEE.CMD/USX": 0.01,
        "COCOA.CMD/USD": 0.01,
        "SUGAR.CMD/USD": 0.01,
        "COTTON.CMD/USX": 0.01,
        "OJUICE.CMD/USX": 0.01,
        "SOYBEAN.CMD/USX": 0.01,
    }
    for symbol, increment in commodity_increments.items():
        profiles[symbol] = InstrumentProfile(
            symbol=symbol,
            asset_class=AssetClass.COMMODITY,
            venue="Dukascopy",
            quote_currency="USD" if symbol.endswith("/USD") else "USX",
            price_increment=increment,
            contract_multiplier=1.0,
            research_status=ResearchStatus.RESEARCH_ONLY,
            cost=CostProfile(typical_spread=None, stress_spread=None),
            rules=commodity_rules,
        )

    _add_profiles(
        profiles,
        ("NVDA", "MSFT", "AAPL", "AMZN", "META", "GOOGL", "GOOG", "AVGO", "AMD", "TSLA", "ORCL", "CRM", "ADBE", "INTC", "QCOM"),
        asset_class=AssetClass.EQUITY,
        venue="EXCHANGE_PENDING",
        quote_currency="USD",
        price_increment=0.01,
        research_status=ResearchStatus.RESEARCH_ONLY,
        cost=CostProfile(typical_spread=None, stress_spread=None),
        rules=equity_rules,
    )

    _add_profiles(
        profiles,
        ("SPX", "NDX", "DJI", "FTSE", "DAX", "NIKKEI"),
        asset_class=AssetClass.INDEX,
        venue="INDEX_PENDING",
        quote_currency="USD",
        price_increment=0.01,
        research_status=ResearchStatus.RESEARCH_ONLY,
        cost=CostProfile(typical_spread=None, stress_spread=None),
        rules=index_rules,
    )

    return AssetRegistry(profiles)
