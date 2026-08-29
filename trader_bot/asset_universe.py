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
    typical_spread: float | None
    stress_spread: float | None
    slippage_rate: float = 0.0
    commission_rate: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (("typical_spread", self.typical_spread), ("stress_spread", self.stress_spread), ("slippage_rate", self.slippage_rate), ("commission_rate", self.commission_rate)):
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
        if not self.symbol.strip() or self.symbol != self.symbol.upper():
            raise ValueError("symbol must be non-empty and normalized uppercase")
        if not self.venue.strip() or not self.quote_currency.strip():
            raise ValueError("venue and quote_currency must be non-empty")
        if self.price_increment <= 0 or self.contract_multiplier <= 0:
            raise ValueError("price_increment and contract_multiplier must be positive")

    @property
    def is_research_ready(self) -> bool:
        return self.research_status is ResearchStatus.EXISTING_VALIDATED_DOMAIN


class AssetRegistry:
    def __init__(self, profiles: Mapping[str, InstrumentProfile]) -> None:
        normalized: dict[str, InstrumentProfile] = {}
        for key, profile in profiles.items():
            if key != profile.symbol or key.upper() != key:
                raise ValueError("registry keys must match normalized profile symbols")
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


def _add_profiles(profiles: dict[str, InstrumentProfile], symbols: tuple[str, ...], *, asset_class: AssetClass, venue: str, quote_currency: str, price_increment: float, research_status: ResearchStatus, cost: CostProfile, rules: MarketRules) -> None:
    for symbol in symbols:
        profiles[symbol] = InstrumentProfile(symbol, asset_class, venue, quote_currency, price_increment, 1.0, research_status, cost, rules)


def default_asset_registry() -> AssetRegistry:
    forex_cost = CostProfile(None, None)
    fx_rules = MarketRules(TradingSession.WEEKDAY_CONTINUOUS, True, True, True, False, False)
    crypto_rules = MarketRules(TradingSession.TWENTY_FOUR_SEVEN, True, True, False, True, False)
    metal_rules = MarketRules(TradingSession.WEEKDAY_CONTINUOUS, True, True, True, False, False)
    commodity_rules = MarketRules(TradingSession.WEEKDAY_CONTINUOUS, True, True, True, True, False)
    equity_rules = MarketRules(TradingSession.EXCHANGE_HOURS, True, False, True, True, True)
    index_rules = MarketRules(TradingSession.EXCHANGE_HOURS, True, False, True, True, True)
    profiles: dict[str, InstrumentProfile] = {}
    _add_profiles(profiles, ("EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CAD","USD/CHF","NZD/USD","EUR/JPY","GBP/JPY"), asset_class=AssetClass.FOREX, venue="Dukascopy", quote_currency="USD", price_increment=0.0001, research_status=ResearchStatus.EXISTING_VALIDATED_DOMAIN, cost=forex_cost, rules=fx_rules)
    for symbol in ("USD/JPY", "EUR/JPY", "GBP/JPY"):
        profiles[symbol] = InstrumentProfile(symbol, AssetClass.FOREX, "Dukascopy", "JPY", 0.01, 1.0, ResearchStatus.EXISTING_VALIDATED_DOMAIN, forex_cost, fx_rules)
    _add_profiles(profiles, ("BTC/USD","ETH/USD","SOL/USD","BNB/USD","XRP/USD","ADA/USD","DOGE/USD","AVAX/USD","LINK/USD"), asset_class=AssetClass.CRYPTO, venue="Binance", quote_currency="USD", price_increment=0.01, research_status=ResearchStatus.RESEARCH_ONLY, cost=CostProfile(None,None), rules=crypto_rules)
    _add_profiles(profiles, ("XAU/USD","XAG/USD","XPT/USD","XPD/USD"), asset_class=AssetClass.METAL, venue="Dukascopy", quote_currency="USD", price_increment=0.01, research_status=ResearchStatus.RESEARCH_ONLY, cost=CostProfile(None,None), rules=metal_rules)
    for symbol in ("BRENT.CMD/USD","LIGHT.CMD/USD","GAS.CMD/USD","COPPER.CMD/USD","DIESEL.CMD/USD","COFFEE.CMD/USX","COCOA.CMD/USD","SUGAR.CMD/USD","COTTON.CMD/USX","OJUICE.CMD/USX","SOYBEAN.CMD/USX"):
        profiles[symbol] = InstrumentProfile(symbol, AssetClass.COMMODITY, "Dukascopy", "USD" if symbol.endswith("/USD") else "USX", 0.01, 1.0, ResearchStatus.RESEARCH_ONLY, CostProfile(None,None), commodity_rules)
    _add_profiles(profiles, ("NVDA","MSFT","AAPL","AMZN","META","GOOGL","GOOG","AVGO","AMD","TSLA","ORCL","CRM","ADBE","INTC","QCOM"), asset_class=AssetClass.EQUITY, venue="EXCHANGE_PENDING", quote_currency="USD", price_increment=0.01, research_status=ResearchStatus.RESEARCH_ONLY, cost=CostProfile(None,None), rules=equity_rules)
    _add_profiles(profiles, ("SPX","NDX","DJI","FTSE","DAX","NIKKEI"), asset_class=AssetClass.INDEX, venue="INDEX_PENDING", quote_currency="USD", price_increment=0.01, research_status=ResearchStatus.RESEARCH_ONLY, cost=CostProfile(None,None), rules=index_rules)
    return AssetRegistry(profiles)
