from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from .data_provider import MarketDataProvider
from .ingestion_store import IngestionStore
from .models import DataRequest, MarketBar, OfferSide, Timeframe


@dataclass(frozen=True, slots=True)
class IngestionResult:
    provider: str
    asset_class: str
    instrument: int
    timeframe: Timeframe
    offer_side: OfferSide
    requested_start: datetime
    requested_end: datetime
    received: int
    stored: int
    latest_timestamp: datetime | None
    source_hash: str | None


class IngestionContractError(RuntimeError):
    """Raised when a provider response violates the normalized data contract."""


def canonical_bar_hash(bars: Sequence[MarketBar]) -> str:
    payload = "\n".join(
        "|".join(
            (
                bar.timestamp.isoformat(),
                str(bar.instrument),
                bar.timeframe.value,
                bar.offer_side.value,
                str(bar.open),
                str(bar.high),
                str(bar.low),
                str(bar.close),
                "" if bar.volume is None else str(bar.volume),
                "" if bar.trade_count is None else str(bar.trade_count),
            )
        )
        for bar in sorted(bars, key=lambda item: item.timestamp)
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_provider_bars(
    bars: Sequence[MarketBar],
    *,
    request: DataRequest,
) -> list[MarketBar]:
    if not bars:
        return []
    ordered = sorted(bars, key=lambda bar: bar.timestamp)
    previous: datetime | None = None
    seen: set[datetime] = set()
    for bar in ordered:
        if bar.instrument != request.instrument:
            raise IngestionContractError("provider returned an unexpected instrument")
        if bar.timeframe is not request.timeframe:
            raise IngestionContractError("provider returned an unexpected timeframe")
        if bar.offer_side is not request.offer_side:
            raise IngestionContractError("provider returned an unexpected offer side")
        if bar.timestamp.tzinfo is None:
            raise IngestionContractError("provider returned a naive timestamp")
        if not request.start <= bar.timestamp < request.end:
            raise IngestionContractError("provider returned a bar outside the requested interval")
        if bar.timestamp in seen:
            raise IngestionContractError("provider returned duplicate timestamps")
        if previous is not None and bar.timestamp <= previous:
            raise IngestionContractError("provider returned non-increasing timestamps")
        seen.add(bar.timestamp)
        previous = bar.timestamp
    return ordered


def ingest_series(
    provider: MarketDataProvider,
    store: IngestionStore,
    *,
    provider_name: str,
    asset_class: str,
    instrument: int,
    timeframe: Timeframe,
    offer_side: OfferSide,
    start: datetime,
    end: datetime,
    observed_at: datetime | None = None,
) -> IngestionResult:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    if start >= end:
        raise ValueError("start must be before end")
    request = DataRequest(
        instrument=instrument,
        timeframe=timeframe,
        start=start,
        end=end,
        offer_side=offer_side,
    )
    bars = validate_provider_bars(provider.historical_bars(request), request=request)
    digest = canonical_bar_hash(bars) if bars else None
    stored = store.append_verified(list(bars), provider=provider_name, asset_class=asset_class)
    if bars:
        observed = observed_at or datetime.now(timezone.utc)
        latest = bars[-1].timestamp
        store.save_checkpoint(
            provider=provider_name,
            asset_class=asset_class,
            instrument=instrument,
            timeframe=timeframe.value,
            offer_side=offer_side.value,
            as_of=latest,
            observed_at=observed,
            source_hash=digest or "",
        )
    else:
        latest = None
    return IngestionResult(
        provider=provider_name,
        asset_class=asset_class,
        instrument=instrument,
        timeframe=timeframe,
        offer_side=offer_side,
        requested_start=start,
        requested_end=end,
        received=len(bars),
        stored=stored,
        latest_timestamp=latest,
        source_hash=digest,
    )


def next_incremental_start(
    store: IngestionStore,
    *,
    provider: str,
    asset_class: str,
    instrument: int,
    timeframe: Timeframe,
    offer_side: OfferSide,
    initial_start: datetime,
) -> datetime:
    checkpoint = store.checkpoint(
        provider=provider,
        asset_class=asset_class,
        instrument=instrument,
        timeframe=timeframe.value,
        offer_side=offer_side.value,
    )
    if checkpoint is None:
        return initial_start
    value = checkpoint["as_of"]
    if not isinstance(value, datetime):
        raise IngestionContractError("stored checkpoint timestamp is invalid")
    return value
