from __future__ import annotations

from pathlib import Path
from typing import Sequence

import duckdb

from .models import MarketBar


class ResearchStore:
    """Small analytical store for reproducible derived/raw research slices.

    The store is not a substitute for the provider. It is an optional audit/cache
    layer. Large raw archives remain opt-in and are never required for normal startup.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = duckdb.connect(str(path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_bars (
                timestamp TIMESTAMPTZ NOT NULL,
                instrument INTEGER NOT NULL,
                timeframe VARCHAR NOT NULL,
                offer_side VARCHAR NOT NULL,
                open DECIMAL(38,18) NOT NULL,
                high DECIMAL(38,18) NOT NULL,
                low DECIMAL(38,18) NOT NULL,
                close DECIMAL(38,18) NOT NULL,
                volume DECIMAL(38,18)
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_market_bars_lookup ON market_bars(instrument, timeframe, offer_side, timestamp)"
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ResearchStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def append_bars(self, bars: Sequence[MarketBar]) -> int:
        if not bars:
            return 0
        rows = [
            (
                b.timestamp,
                b.instrument,
                b.timeframe.value,
                b.offer_side.value,
                b.open,
                b.high,
                b.low,
                b.close,
                b.volume,
            )
            for b in bars
        ]
        self._conn.executemany(
            """
            INSERT INTO market_bars
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        return len(rows)

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM market_bars").fetchone()[0])
