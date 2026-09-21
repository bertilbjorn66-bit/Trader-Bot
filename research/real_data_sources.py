from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from trader_bot.asset_universe import AssetClass


class DataResolution(StrEnum):
    TICK = "TICK"
    SECOND = "SECOND"
    MINUTE = "MINUTE"
    HOUR = "HOUR"
    DAILY = "DAILY"


class DataField(StrEnum):
    TIMESTAMP = "timestamp"
    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    BID = "bid"
    ASK = "ask"
    VOLUME = "volume"
    TRADE_COUNT = "trade_count"
    FUNDING = "funding"
    VENUE = "venue"
    EVENT_TIME = "event_time"
    KNOWN_TIME = "known_time"


@dataclass(frozen=True, slots=True)
class RealDataSource:
    """Auditable description of a real market-data source.

    This object describes acquisition requirements; it does not itself download data.
    Research code must reject synthetic or provenance-free records at the boundary.
    """

    source_id: str
    provider: str
    asset_classes: frozenset[AssetClass]
    resolutions: frozenset[DataResolution]
    raw_format: str
    public_or_authenticated: str
    primary_url: str
    notes: str
    required_fields: frozenset[DataField]

    def supports(self, asset_class: AssetClass, resolution: DataResolution) -> bool:
        return asset_class in self.asset_classes and resolution in self.resolutions


def default_real_data_sources() -> tuple[RealDataSource, ...]:
    """Return the approved initial real-data acquisition map.

    Sources are intentionally separated by market microstructure. No source is
    treated as universally authoritative across all asset classes.
    """

    return (
        RealDataSource(
            source_id="DUKASCOPY_HISTORICAL",
            provider="Dukascopy",
            asset_classes=frozenset({AssetClass.FOREX, AssetClass.METAL, AssetClass.COMMODITY}),
            resolutions=frozenset({DataResolution.TICK, DataResolution.MINUTE, DataResolution.HOUR, DataResolution.DAILY}),
            raw_format="broker historical export",
            public_or_authenticated="public historical access",
            primary_url="https://www.dukascopy.com/api/data/get/historical-data-export",
            notes="Preferred source for FX, metals and supported commodity CFDs. Preserve bid/ask and volume where supplied; verify instrument availability before ingestion.",
            required_fields=frozenset({DataField.TIMESTAMP, DataField.OPEN, DataField.HIGH, DataField.LOW, DataField.CLOSE, DataField.BID, DataField.ASK}),
        ),
        RealDataSource(
            source_id="BINANCE_PUBLIC_MARKET_DATA",
            provider="Binance",
            asset_classes=frozenset({AssetClass.CRYPTO}),
            resolutions=frozenset({DataResolution.TICK, DataResolution.SECOND, DataResolution.MINUTE, DataResolution.HOUR, DataResolution.DAILY}),
            raw_format="daily/monthly CSV and public market-data API",
            public_or_authenticated="public market data",
            primary_url="https://data.binance.vision/",
            notes="Use public market data only. Keep venue identity, trade/aggTrade semantics, volume and funding/derivatives fields separate.",
            required_fields=frozenset({DataField.TIMESTAMP, DataField.OPEN, DataField.HIGH, DataField.LOW, DataField.CLOSE, DataField.VOLUME, DataField.TRADE_COUNT}),
        ),
        RealDataSource(
            source_id="STOOQ_MARKET_HISTORY",
            provider="Stooq",
            asset_classes=frozenset({AssetClass.EQUITY, AssetClass.INDEX}),
            resolutions=frozenset({DataResolution.DAILY}),
            raw_format="CSV historical download",
            public_or_authenticated="public access",
            primary_url="https://stooq.com/q/d/l/",
            notes="Use for broad historical daily coverage. Intraday equity/index research requires a provider with explicit intraday licensing and exchange-aware metadata.",
            required_fields=frozenset({DataField.TIMESTAMP, DataField.OPEN, DataField.HIGH, DataField.LOW, DataField.CLOSE, DataField.VOLUME}),
        ),
    )
