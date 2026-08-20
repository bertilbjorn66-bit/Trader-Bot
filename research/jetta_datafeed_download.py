from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return dt.astimezone(timezone.utc)


def parse_timestamp(value: str) -> int:
    value = value.strip()
    try:
        numeric = float(value)
    except ValueError as exc:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("timestamp must include a timezone") from exc
        return int(dt.timestamp() * 1000)
    # Dukascopy CSVs use millisecond timestamps; accept second timestamps defensively.
    return int(numeric if abs(numeric) >= 100_000_000_000 else numeric * 1000)


def run_download(
    symbol: str,
    start: datetime,
    end: datetime | None,
    side: str,
    output: Path,
) -> None:
    slug = symbol.replace("/", "").replace("_", "").replace("-", "").lower()
    command = [
        "dukascopy-go",
        "download",
        "--engine",
        "jetta",
        "--symbol",
        slug,
        "--timeframe",
        "m5",
        "--side",
        side,
        "--from",
        start.isoformat(),
        "--output",
        str(output),
        "--resume",
    ]
    if end is not None:
        command.extend(["--to", end.isoformat()])
    subprocess.run(command, check=True)


def read_bars(path: Path) -> Iterable[tuple[int, float, float, float, float, float]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = {name.strip().lower(): name for name in (reader.fieldnames or [])}
        required = {"timestamp", "open", "high", "low", "close"}
        if not required.issubset(headers):
            raise RuntimeError(f"Unexpected Dukascopy-go CSV schema in {path}: {reader.fieldnames}")
        volume_key = headers.get("volume")
        for row in reader:
            yield (
                parse_timestamp(row[headers["timestamp"]]),
                float(row[headers["open"]]),
                float(row[headers["high"]]),
                float(row[headers["low"]]),
                float(row[headers["close"]]),
                float(row[volume_key] or 0.0) if volume_key else 0.0,
            )


def aggregate_10m(
    bars: Iterable[tuple[int, float, float, float, float, float]]
) -> list[tuple[int, float, float, float, float, float]]:
    result: list[tuple[int, float, float, float, float, float]] = []
    bucket: list[tuple[int, float, float, float, float, float]] = []
    current_bucket: int | None = None

    for bar in bars:
        ts = bar[0]
        bucket_start = (ts // 600_000) * 600_000
        if current_bucket is None:
            current_bucket = bucket_start
        if bucket_start != current_bucket:
            if len(bucket) == 2 and bucket[0][0] + 300_000 == bucket[1][0]:
                result.append(
                    (
                        current_bucket,
                        bucket[0][1],
                        max(bucket[0][2], bucket[1][2]),
                        min(bucket[0][3], bucket[1][3]),
                        bucket[1][4],
                        bucket[0][5] + bucket[1][5],
                    )
                )
            bucket = []
            current_bucket = bucket_start
        bucket.append(bar)

    if current_bucket is not None and len(bucket) == 2 and bucket[0][0] + 300_000 == bucket[1][0]:
        result.append(
            (
                current_bucket,
                bucket[0][1],
                max(bucket[0][2], bucket[1][2]),
                min(bucket[0][3], bucket[1][3]),
                bucket[1][4],
                bucket[0][5] + bucket[1][5],
            )
        )
    return result


def merge_sides(
    bid: list[tuple[int, float, float, float, float, float]],
    ask: list[tuple[int, float, float, float, float, float]],
    output: Path,
) -> None:
    bid_by_ts = {row[0]: row for row in bid}
    ask_by_ts = {row[0]: row for row in ask}
    common = sorted(set(bid_by_ts) & set(ask_by_ts))
    if not common:
        raise RuntimeError("No timestamp overlap between BID and ASK data")
    with output.open("w", encoding="utf-8") as handle:
        for ts in common:
            b = bid_by_ts[ts]
            a = ask_by_ts[ts]
            handle.write(
                json.dumps(
                    {
                        "timestamp": ts,
                        "bid_open": b[1],
                        "bid_high": b[2],
                        "bid_low": b[3],
                        "bid_close": b[4],
                        "ask_open": a[1],
                        "ask_high": a[2],
                        "ask_low": a[3],
                        "ask_close": a[4],
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Dukascopy 5m BID/ASK through JETTA and resample to 10m."
    )
    parser.add_argument("--pair", required=True)
    parser.add_argument("--start", default="2020-01-01T00:00:00+00:00")
    parser.add_argument("--end", default="")
    parser.add_argument("--out-dir", default=".data/empirical_feed")
    args = parser.parse_args()

    start = parse_dt(args.start)
    end = parse_dt(args.end) if args.end else None
    slug = args.pair.replace("/", "").replace("_", "").replace("-", "").lower()
    out_dir = Path(args.out_dir)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    bid_csv = raw_dir / f"{slug}_bid_m5.csv"
    ask_csv = raw_dir / f"{slug}_ask_m5.csv"
    final_jsonl = out_dir / f"{slug}.jsonl"

    run_download(args.pair, start, end, "bid", bid_csv)
    run_download(args.pair, start, end, "ask", ask_csv)

    bid_10m = aggregate_10m(read_bars(bid_csv))
    ask_10m = aggregate_10m(read_bars(ask_csv))
    merge_sides(bid_10m, ask_10m, final_jsonl)


if __name__ == "__main__":
    main()
