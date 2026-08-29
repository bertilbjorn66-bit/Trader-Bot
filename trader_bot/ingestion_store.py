from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from .models import MarketBar


class IngestionStore:
    """Private, idempotent storage for verified provider data and checkpoints."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = duckdb.connect(str(path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_bars (
                provider VARCHAR NOT NULL,
                asset_class VARCHAR NOT NULL,
                instrument INTEGER NOT NULL,
                timeframe VARCHAR NOT NULL,
                offer_side VARCHAR NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL,
                open DECIMAL(38,18) NOT NULL,
                high DECIMAL(38,18) NOT NULL,
                low DECIMAL(38,18) NOT NULL,
                close DECIMAL(38,18) NOT NULL,
                volume DECIMAL(38,18),
                trade_count BIGINT,
                PRIMARY KEY (provider, asset_class, instrument, timeframe, offer_side, timestamp)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingestion_checkpoints (
                provider VARCHAR NOT NULL,
                asset_class VARCHAR NOT NULL,
                instrument INTEGER NOT NULL,
                timeframe VARCHAR NOT NULL,
                offer_side VARCHAR NOT NULL,
                as_of TIMESTAMPTZ NOT NULL,
                observed_at TIMESTAMPTZ NOT NULL,
                source_hash VARCHAR NOT NULL,
                PRIMARY KEY (provider, asset_class, instrument, timeframe, offer_side)
            )
            """
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "IngestionStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def append_verified(self, bars: list[MarketBar], *, provider: str, asset_class: str) -> int:
        if not bars:
            return 0
        if not provider.strip() or not asset_class.strip():
            raise ValueError("provider and asset_class must not be empty")
        rows = [
            (
                provider,
                asset_class,
                bar.instrument,
                bar.timeframe.value,
                bar.offer_side.value,
                bar.timestamp,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.trade_count,
            )
            for bar in bars
        ]
        self._conn.executemany(
            """
            INSERT INTO market_bars
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )
        return len(rows)

    def checkpoint(self, *, provider: str, asset_class: str, instrument: int, timeframe: str, offer_side: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT provider, asset_class, instrument, timeframe, offer_side, as_of, observed_at, source_hash
            FROM ingestion_checkpoints
            WHERE provider = ? AND asset_class = ? AND instrument = ? AND timeframe = ? AND offer_side = ?
            """,
            [provider, asset_class, instrument, timeframe, offer_side],
        ).fetchone()
        if row is None:
            return None
        keys = ("provider", "asset_class", "instrument", "timeframe", "offer_side", "as_of", "observed_at", "source_hash")
        return dict(zip(keys, row, strict=True))

    def save_checkpoint(
        self,
        *,
        provider: str,
        asset_class: str,
        instrument: int,
        timeframe: str,
        offer_side: str,
        as_of: datetime,
        observed_at: datetime,
        source_hash: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO ingestion_checkpoints
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (provider, asset_class, instrument, timeframe, offer_side)
            DO UPDATE SET
                as_of = excluded.as_of,
                observed_at = excluded.observed_at,
                source_hash = excluded.source_hash
            """,
            [provider, asset_class, instrument, timeframe, offer_side, as_of, observed_at, source_hash],
        )

    def count_series(self, *, provider: str, asset_class: str, instrument: int, timeframe: str, offer_side: str) -> int:
        row = self._conn.execute(
            """
            SELECT COUNT(*)
            FROM market_bars
            WHERE provider = ? AND asset_class = ? AND instrument = ? AND timeframe = ? AND offer_side = ?
            """,
            [provider, asset_class, instrument, timeframe, offer_side],
        ).fetchone()
        return 0 if row is None else int(row[0])
