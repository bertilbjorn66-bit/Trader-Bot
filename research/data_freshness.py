from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from trader_bot.asset_universe import AssetClass
from trader_bot.models import Timeframe


class FreshnessState(StrEnum):
    CURRENT = "CURRENT"
    DUE = "DUE"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DataFeedContract:
    asset_class: AssetClass
    provider: str
    required_timeframes: tuple[Timeframe, ...]
    required_fields: tuple[str, ...]
    refresh_interval: timedelta
    maximum_staleness: timedelta

    def validate(self) -> None:
        if not self.provider.strip() or self.provider == "provider_pending":
            raise ValueError("a concrete data provider is required")
        if not self.required_timeframes:
            raise ValueError("at least one timeframe is required")
        if not self.required_fields:
            raise ValueError("at least one required field is required")
        if self.refresh_interval <= timedelta(0):
            raise ValueError("refresh_interval must be positive")
        if self.maximum_staleness < self.refresh_interval:
            raise ValueError("maximum_staleness must be >= refresh_interval")


@dataclass(frozen=True, slots=True)
class FeedSnapshot:
    asset_class: AssetClass
    instrument: str
    provider: str
    as_of: datetime
    observed_at: datetime
    fields: tuple[str, ...]
    source_hash: str
    real_data: bool = True

    def validate(self, contract: DataFeedContract) -> None:
        contract.validate()
        if self.asset_class is not contract.asset_class:
            raise ValueError("snapshot asset class does not match feed contract")
        if self.provider != contract.provider:
            raise ValueError("snapshot provider does not match feed contract")
        if not self.instrument.strip():
            raise ValueError("instrument must not be empty")
        if self.as_of.tzinfo is None or self.observed_at.tzinfo is None:
            raise ValueError("snapshot timestamps must be timezone-aware")
        if not self.source_hash.strip():
            raise ValueError("source_hash must not be empty")
        if not self.real_data:
            raise ValueError("empirical feeds must contain real data")
        missing = set(contract.required_fields) - set(self.fields)
        if missing:
            raise ValueError(f"snapshot missing required fields: {sorted(missing)}")
        if self.observed_at < self.as_of:
            raise ValueError("observed_at cannot precede as_of")


def assess_freshness(
    snapshot: FeedSnapshot | None,
    contract: DataFeedContract,
    *,
    now: datetime | None = None,
) -> FreshnessState:
    contract.validate()
    if snapshot is None:
        return FreshnessState.UNKNOWN
    snapshot.validate(contract)
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    age = current_time - snapshot.as_of
    if age < timedelta(0):
        return FreshnessState.UNKNOWN
    if age >= contract.maximum_staleness:
        return FreshnessState.STALE
    if age >= contract.refresh_interval:
        return FreshnessState.DUE
    return FreshnessState.CURRENT


def refresh_window(
    snapshot: FeedSnapshot | None,
    contract: DataFeedContract,
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime] | None:
    """Return only the missing interval; never force a full-history refresh."""

    contract.validate()
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    state = assess_freshness(snapshot, contract, now=current_time)
    if state in {FreshnessState.UNKNOWN, FreshnessState.CURRENT}:
        return None
    start = snapshot.as_of
    if start >= current_time:
        return None
    return start, current_time


def default_feed_contracts() -> dict[AssetClass, DataFeedContract]:
    return {
        AssetClass.FOREX: DataFeedContract(
            AssetClass.FOREX,
            "dukascopy",
            (Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES, Timeframe.ONE_HOUR, Timeframe.ONE_DAY),
            ("timestamp", "open", "high", "low", "close", "volume"),
            timedelta(hours=1),
            timedelta(hours=6),
        ),
        AssetClass.CRYPTO: DataFeedContract(
            AssetClass.CRYPTO,
            "binance_public",
            (Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES, Timeframe.ONE_HOUR, Timeframe.ONE_DAY),
            ("timestamp", "open", "high", "low", "close", "volume"),
            timedelta(minutes=15),
            timedelta(hours=2),
        ),
        AssetClass.METAL: DataFeedContract(
            AssetClass.METAL,
            "dukascopy",
            (Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES, Timeframe.ONE_HOUR, Timeframe.ONE_DAY),
            ("timestamp", "open", "high", "low", "close", "volume"),
            timedelta(hours=1),
            timedelta(hours=6),
        ),
        AssetClass.COMMODITY: DataFeedContract(
            AssetClass.COMMODITY,
            "stooq_initial",
            (Timeframe.ONE_DAY,),
            ("timestamp", "open", "high", "low", "close", "volume"),
            timedelta(days=1),
            timedelta(days=3),
        ),
        AssetClass.EQUITY: DataFeedContract(
            AssetClass.EQUITY,
            "stooq_initial",
            (Timeframe.ONE_DAY,),
            ("timestamp", "open", "high", "low", "close", "volume"),
            timedelta(days=1),
            timedelta(days=3),
        ),
        AssetClass.INDEX: DataFeedContract(
            AssetClass.INDEX,
            "stooq_initial",
            (Timeframe.ONE_DAY,),
            ("timestamp", "open", "high", "low", "close", "volume"),
            timedelta(days=1),
            timedelta(days=3),
        ),
    }
