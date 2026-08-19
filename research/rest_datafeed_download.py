from __future__ import annotations

import argparse
import json
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


def normalize(symbol: str) -> str:
    return symbol.replace("/", "").replace("_", "").replace("-", "").upper()


def request_json(client: httpx.Client, params: dict[str, Any]) -> Any:
    request_params = dict(params)
    path = request_params.pop("path")
    last: Exception | None = None
    for attempt in range(1, 9):
        try:
            response = client.get(API_URL, params={"path": path, **request_params})
            if response.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"provider HTTP {response.status_code}")
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            last = exc
            if attempt == 8:
                break
            time.sleep(min(60.0, 2.0 ** (attempt - 1)))
    raise RuntimeError(f"Dukascopy REST request failed after retries: {last}") from last


def load_instruments(client: httpx.Client) -> dict[str, int]:
    payload = request_json(client, {"path": "api/instrumentList", "fields": "id,name,nameLong"})
    if not isinstance(payload, list):
        raise RuntimeError("instrumentList did not return an array")
    result: dict[str, int] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            instrument_id = int(row["id"])
        except (KeyError, TypeError, ValueError):
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


def fetch_window(client: httpx.Client, instrument_id: int, start: datetime, end: datetime, side: str) -> list[dict[str, object]]:
    payload = request_json(
        client,
        {
            "path": "api/historicalPrices",
            "instrument": instrument_id,
            "timeFrame": "10m",
            "count": BARS_PER_REQUEST,
            "start": int(start.timestamp() * 1000),
            "end": int(end.timestamp() * 1000),
            "offerSide": side,
            "dayStartTime": "UTC",
        },
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
    rows.sort(key=lambda row: int(row["timestamp"]))
    return rows


def merge_sides(bid: list[dict[str, object]], ask: list[dict[str, object]]) -> list[dict[str, object]]:
    bid_by_ts = {int(row["timestamp"]): row for row in bid}
    ask_by_ts = {int(row["timestamp"]): row for row in ask}
    bars: list[dict[str, object]] = []
    for timestamp in sorted(set(bid_by_ts) & set(ask_by_ts)):
        b = bid_by_ts[timestamp]
        a = ask_by_ts[timestamp]
        bars.append(
            {
                "timestamp": timestamp,
                "bid_open": b["open"], "bid_high": b["high"], "bid_low": b["low"], "bid_close": b["close"],
                "ask_open": a["open"], "ask_high": a["high"], "ask_low": a["low"], "ask_close": a["close"],
            }
        )
    return bars


def main() -> None:
    parser = argparse.ArgumentParser(description="Download empirical 10m BID/ASK data through Dukascopy official REST API.")
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
    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
    with httpx.Client(timeout=httpx.Timeout(45.0, connect=20.0), limits=limits) as client:
        instruments = load_instruments(client)
        for pair in pairs:
            instrument_id = instruments.get(normalize(pair))
            if instrument_id is None:
                raise SystemExit(f"Dukascopy instrument not found in official instrumentList: {pair}")
            path = output_dir / f"{normalize(pair).lower()}.jsonl"
            path.unlink(missing_ok=True)
            cursor = start
            with path.open("w", encoding="utf-8") as handle:
                while cursor < end:
                    chunk_end = min(end, cursor + timedelta(days=CHUNK_DAYS))
                    bid = fetch_window(client, instrument_id, cursor, chunk_end, "B")
                    ask = fetch_window(client, instrument_id, cursor, chunk_end, "A")
                    bars = merge_sides(bid, ask)
                    handle.write(json.dumps({"chunk_start": cursor.isoformat(), "bars": bars}) + "\n")
                    cursor = chunk_end


if __name__ == "__main__":
    main()
