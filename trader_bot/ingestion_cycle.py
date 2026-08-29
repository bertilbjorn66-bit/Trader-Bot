from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .data_provider import MarketDataProvider
from .ingestion import IngestionContractError, ingest_series, next_incremental_start
from .ingestion_store import IngestionStore
from .models import OfferSide, Timeframe


@dataclass(frozen=True, slots=True)
class SeriesPlan:
    asset_class: str
    instrument: int
    timeframe: Timeframe
    offer_side: OfferSide
    initial_start: datetime


@dataclass(frozen=True, slots=True)
class SeriesOutcome:
    plan: SeriesPlan
    status: str
    requested_start: datetime | None
    requested_end: datetime | None
    received: int = 0
    stored: int = 0
    latest_timestamp: datetime | None = None
    reason: str | None = None


def run_cycle(
    provider: MarketDataProvider,
    store: IngestionStore,
    *,
    provider_name: str,
    plans: tuple[SeriesPlan, ...],
    now: datetime,
) -> tuple[SeriesOutcome, ...]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    outcomes: list[SeriesOutcome] = []
    for plan in plans:
        start = next_incremental_start(
            store,
            provider=provider_name,
            asset_class=plan.asset_class,
            instrument=plan.instrument,
            timeframe=plan.timeframe,
            offer_side=plan.offer_side,
            initial_start=plan.initial_start,
        )
        if start.tzinfo is None:
            raise IngestionContractError("initial/checkpoint start must be timezone-aware")
        if start >= now:
            outcomes.append(
                SeriesOutcome(
                    plan=plan,
                    status="CURRENT",
                    requested_start=start,
                    requested_end=now,
                )
            )
            continue
        try:
            result = ingest_series(
                provider,
                store,
                provider_name=provider_name,
                asset_class=plan.asset_class,
                instrument=plan.instrument,
                timeframe=plan.timeframe,
                offer_side=plan.offer_side,
                start=start,
                end=now,
                observed_at=now,
            )
        except Exception as exc:
            outcomes.append(
                SeriesOutcome(
                    plan=plan,
                    status="FAILED",
                    requested_start=start,
                    requested_end=now,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        outcomes.append(
            SeriesOutcome(
                plan=plan,
                status="UPDATED" if result.received else "NO_DATA",
                requested_start=start,
                requested_end=now,
                received=result.received,
                stored=result.stored,
                latest_timestamp=result.latest_timestamp,
            )
        )
    return tuple(outcomes)
