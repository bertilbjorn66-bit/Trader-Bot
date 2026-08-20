from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

API_URL = "https://freeserv.dukascopy.com/2.0/"
PAIRS = (
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "USD/CHF",
    "NZD/USD", "EUR/JPY", "GBP/JPY",
)
BARS_PER_REQUEST = 5000
CHUNK_DAYS = 30
MIN_REQUEST_INTERVAL_SECONDS = 0.75
MAX_RETRY_SLEEP_SECONDS = 300.0


def normalize(symbol: str) -> str:
    return symbol.replace("/", "").replace("_", "").replace("-", "").upper()


def _int_value(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"Feed field {field!r} must be an integer-compatible value")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Feed field {field!r} must be an integer-compatible value") from exc


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class _RequestPacer:
    def __init__(self, minimum_interval: float = MIN_REQUEST_INTERVAL_SECONDS) -> None:
        self.minimum_interval = minimum_interval
        self._last_request: float | None = None

    def wait(self) -> None:
        now = time.monotonic()
        if self._last_request is not None:
            remaining = self.minimum_interval - (now - self._last_request)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request = time.monotonic()


def request_json(
    client: httpx.Client,
    params: dict[str, Any],
    pacer: _RequestPacer | None = None,
) -> Any:
    request_params = dict(params)
    path = request_params.pop("path")
    active_pacer = pacer or _RequestPacer()
    last: Exception | None = None
    for attempt in range(1, 9):
        try:
            active_pacer.wait()
            response = client.get(API_URL, params={"path": path, **request_params})
            if response.status_code in (429, 500, 502, 503, 504):
                retry_after = _retry_after_seconds(response)
                if retry_after is None:
                    retry_after = min(
                        MAX_RETRY_SLEEP_SECONDS,
                        30.0 * (2 ** (attempt - 1)),
                    )
                time.sleep(min(MAX_RETRY_SLEEP_SECONDS, retry_after) + random.uniform(0.0, 3.0))
                raise RuntimeError(f"provider HTTP {response.status_code}")
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            last = exc
            if attempt == 8:
                break
    raise RuntimeError(f"Dukascopy REST request failed after retries: {last}") from last


def load_instruments(client: httpx.Client) -> dict[str, int]:
    """Retained for diagnostics/tests; the empirical path avoids this rate-limited call."""
    payload = request_json(client, {"path": "api/instrumentList", "fields": "id,name,nameLong"})
    if not isinstance(payload, list):
        raise RuntimeError("instrumentList did not return an array")
    result: dict[str, int] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            instrument_id = _int_value(row.get("id"), "id")
        except ValueError:
            continue
        for key in ("name", "nameLong"):
            value = row.get(key)
            if isinstance(value, str) and value:
                result[normalize(value)] = instrument_id
    return result


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return dt.astimezone(timezone.utc)


def fetch_window(
    client: httpx.Client,
    instrument: int | str,
    start: datetime,
    end: datetime,
    side: str,
    pacer: _RequestPacer | None = None,
) -> list[dict[str, object]]:
    payload = request_json(
        client,
        {
            "path": "api/historicalPrices",
            "instrument": instrument,
            "timeFrame": "10m",
            "count": BARS_PER_REQUEST,
            "start": int(start.timestamp() * 1000),
            "end": int(end.timestamp() * 1000),
            "offerSide": side,
            "dayStartTime": "UTC",
        },
        pacer=pacer,
    )
    if not isinstance(payload, list):
        raise RuntimeError("historicalPrices did not return an array")
    rows: list[dict[str, object]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        required = ("timestamp", "open", "high", "low", "close")
        if not all(key in row for key in required):
            continue
        rows.append({key: row[key] for key in required})
    rows.sort(key=lambda row: _int_value(row["timestamp"], "timestamp"))
    return rows


def merge_sides(
    bid: list[dict[str, object]],
    ask: list[dict[str, object]],
) -> list[dict[str, object]]:
    bid_by_ts = {_int_value(row["timestamp"], "timestamp"): row for row in bid}
    ask_by_ts = {_int_value(row["timestamp"], "timestamp"): row for row in ask}
    bars: list[dict[str, object]] = []
    for timestamp in sorted(set(bid_by_ts) & set(ask_by_ts)):
        b = bid_by_ts[timestamp]
        a = ask_by_ts[timestamp]
        bars.append(
            {
                "timestamp": timestamp,
                "bid_open": b["open"],
                "bid_high": b["high"],
                "bid_low": b["low"],
                "bid_close": b["close"],
                "ask_open": a["open"],
                "ask_high": a["high"],
                "ask_low": a["low"],
                "ask_close": a["close"],
            }
        )
    return bars


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download empirical 10m BID/ASK data through Dukascopy official REST API."
    )
    parser.add_argument("--start", default="2020-01-01T00:00:00+00:00")
    parser.add_argument("--end", default=datetime.now(timezone.utc).isoformat())
    parser.add_argument("--pairs", default=",".join(PAIRS))
    parser.add_argument("--out-dir", default=".data/empirical_feed")
    args = parser.parse_args()

    start = parse_dt(args.start)
    end = parse_dt(args.end)
    if start >= end:
        raise SystemExit("start must be before end")
    pairs = tuple(item.strip() for item in args.pairs.split(",") if item.strip())
    allowed = {item.upper() for item in PAIRS}
    unknown = [pair for pair in pairs if pair.upper() not in allowed]
    if unknown:
        raise SystemExit(f"Unsupported empirical pair(s): {', '.join(unknown)}")

    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    limits = httpx.Limits(max_connections=2, max_keepalive_connections=1)
    pacer = _RequestPacer()

    with httpx.Client(timeout=httpx.Timeout(45.0, connect=20.0), limits=limits) as client:
        for pair in pairs:
            path = output_dir / f"{normalize(pair).lower()}.jsonl"
            path.unlink(missing_ok=True)
            cursor = start
            with path.open("w", encoding="utf-8") as handle:
                while cursor < end:
                    chunk_end = min(end, cursor + timedelta(days=CHUNK_DAYS))
                    bid = fetch_window(client, pair, cursor, chunk_end, "B", pacer=pacer)
                    ask = fetch_window(client, pair, cursor, chunk_end, "A", pacer=pacer)
                    bars = merge_sides(bid, ask)
                    if not bars:
                        raise RuntimeError(
                            f"No overlapping BID/ASK candles returned for {pair} "
                            f"{cursor.isoformat()} to {chunk_end.isoformat()}"
                        )
                    handle.write(
                        json.dumps({"chunk_start": cursor.isoformat(), "bars": bars}) + "\n"
                    )
                    cursor = chunk_end


if __name__ == "__main__":
    main()
