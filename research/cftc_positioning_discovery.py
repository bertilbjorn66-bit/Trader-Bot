from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

import numpy as np

from research.datafeed_empirical import PAIR_TO_SYMBOL, _execution_valid_rows, load_feed_bars
from research.non_live_evaluation import profit_factor
from research.statistics import hac_mean_pvalue

PAIR_CURRENCY = {
    "EUR/USD": ("EUR", "USD"), "GBP/USD": ("GBP", "USD"), "USD/JPY": ("USD", "JPY"),
    "AUD/USD": ("AUD", "USD"), "USD/CAD": ("USD", "CAD"), "USD/CHF": ("USD", "CHF"),
    "NZD/USD": ("NZD", "USD"), "EUR/JPY": ("EUR", "JPY"), "GBP/JPY": ("GBP", "JPY"),
}
PAIR_PIP = {
    "EUR/USD": 0.0001, "GBP/USD": 0.0001, "USD/JPY": 0.01, "AUD/USD": 0.0001,
    "USD/CAD": 0.0001, "USD/CHF": 0.0001, "NZD/USD": 0.0001, "EUR/JPY": 0.01, "GBP/JPY": 0.01,
}
CURRENCIES = ("EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "USD")
CFTC_MARKET_NAMES = {
    "EURO FX - CHICAGO MERCANTILE EXCHANGE": "EUR",
    "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE": "GBP",
    "BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE": "GBP",
    "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE": "JPY",
    "AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE": "AUD",
    "CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE": "CAD",
    "SWISS FRANC - CHICAGO MERCANTILE EXCHANGE": "CHF",
    "NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE": "NZD",
    "U.S. DOLLAR INDEX - ICE FUTURES U.S.": "USD",
    "US DOLLAR INDEX - ICE FUTURES U.S.": "USD",
}
FEATURE_TYPES = ("level_z", "change_z")
FEATURE_WINDOWS = (4, 8, 13, 26)
THRESHOLDS = (0.5, 1.0, 1.5)
ORIENTATIONS = ("momentum", "reversion")
HORIZONS = (1, 3, 5)
FAMILY_SIZE = 2 * 4 * 3 * 2 * 3
MIN_DISCOVERY_SAMPLES = 150
MIN_PAIR_SAMPLES = 20
MIN_POSITIVE_PAIRS = 3
MAX_PAIR_CONCENTRATION = 0.80
MIN_DISCOVERY_PF = 1.10
ALPHA = 0.05
BOOTSTRAP_REPS = 2000
BLOCK_SIZE = 4
STRESS_COSTS_PIPS = (0.5, 1.0, 1.5)
DISCOVERY_FRACTION = 0.60
CFTC_START_YEAR, CFTC_END_YEAR = 2006, 2026
CONTRACT_VERSION = "v1-cftc-legacy-positioning-weekly-release-gated-daily-fx-family"
CFTC_SOURCE_BASE = "https://www.cftc.gov/files/dea/history/deacot{year}.zip"

@dataclass(frozen=True)
class PositionObservation:
    currency: str
    report_date: date
    normalized_net: float

@dataclass(frozen=True)
class DailyBar:
    day: date
    timestamp_ms: int
    bid_open: float
    ask_open: float
    bid_close: float
    ask_close: float
    bar_count: int

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _header(value: str) -> str:
    return " ".join(value.replace("\ufeff", "").strip().lower().split())

def _number(value: str) -> float:
    raw = value.strip().replace(",", "")
    if raw in {"", "-", "--", "N/A", "NA"}:
        raise ValueError
    return float(raw)


def _parse_report_date(value: str) -> date:
    raw = value.strip()
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        return date.fromisoformat(raw)
    if len(raw) == 6 and raw.isdigit():
        year = 2000 + int(raw[:2])
        return date(year, int(raw[2:4]), int(raw[4:6]))
    raise ValueError(f"unsupported CFTC report date format: {raw!r}")


def _float_value(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else float(str(value))

def _market_currency(market: str) -> str | None:
    text = " ".join(
        market.upper().replace("\u2013", "-").replace("\u2014", "-").split()
    )
    return CFTC_MARKET_NAMES.get(text)

def _find_header(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    aliases = {
        "market": {_header("Market and Exchange Names")},
        "date": {_header("As of Date in Form YYYY-MM-DD"), _header("As of Date in Form YYYYMMDD")},
        "oi": {_header("Open Interest (All)")},
        "long": {_header("Noncommercial Positions-Long (All)")},
        "short": {_header("Noncommercial Positions-Short (All)")},
    }
    for row_index, row in enumerate(rows):
        lookup = {_header(v): i for i, v in enumerate(row)}
        if all(aliases[k] & lookup.keys() for k in aliases):
            return row_index, {k: lookup[next(iter(aliases[k] & lookup.keys()))] for k in aliases}
    raise ValueError("Legacy COT header row not found")

def _read_archive(path: Path) -> list[PositionObservation]:
    with zipfile.ZipFile(path) as archive:
        members = [m for m in archive.namelist() if not m.endswith("/") and Path(m).suffix.lower() in {".txt", ".csv"}]
        if not members:
            raise ValueError(f"no text/csv member in {path.name}")
        raw = archive.read(max(members, key=lambda m: archive.getinfo(m).file_size))
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig", errors="replace"))))
    header_index, columns = _find_header(rows)
    seen: dict[tuple[str, date], PositionObservation] = {}
    for row in rows[header_index + 1:]:
        if len(row) <= max(columns.values()):
            continue
        currency = _market_currency(row[columns["market"]])
        if currency is None:
            continue
        try:
            report_date = _parse_report_date(row[columns["date"]])
            oi = _number(row[columns["oi"]])
            long_position = _number(row[columns["long"]])
            short_position = _number(row[columns["short"]])
        except ValueError:
            continue
        if oi <= 0:
            continue
        normalized_net = (long_position - short_position) / oi
        if not math.isfinite(normalized_net):
            continue
        observation = PositionObservation(currency, report_date, float(normalized_net))
        key = (currency, report_date)
        previous = seen.get(key)
        if previous is not None and not math.isclose(previous.normalized_net, observation.normalized_net, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(f"ambiguous {currency} row for {report_date} in {path.name}")
        seen[key] = observation
    result = list(seen.values())
    if not result:
        raise ValueError(f"no required FX COT rows parsed from {path.name}")
    return result

def load_positions(cftc_dir: Path) -> tuple[dict[str, list[PositionObservation]], dict[str, dict[str, object]]]:
    archives = sorted(cftc_dir.glob("deacot*.zip"))
    expected = set(range(CFTC_START_YEAR, CFTC_END_YEAR + 1))
    actual = {int(p.stem[6:]) for p in archives if p.stem[6:].isdigit()}
    missing = sorted(expected - actual)
    if missing:
        raise ValueError(f"missing CFTC annual archives: {missing}")
    records: dict[str, list[PositionObservation]] = {currency: [] for currency in CURRENCIES}
    manifest: dict[str, dict[str, object]] = {}
    for path in archives:
        year_text = path.stem[6:]
        if not year_text.isdigit():
            continue
        year = int(year_text)
        if not CFTC_START_YEAR <= year <= CFTC_END_YEAR:
            continue
        parsed = _read_archive(path)
        manifest[path.name] = {
            "sha256": _sha256(path), "bytes": path.stat().st_size,
            "source_url": CFTC_SOURCE_BASE.format(year=year),
            "parsed_observation_count": len(parsed),
        }
        for item in parsed:
            records[item.currency].append(item)
    for currency in records:
        records[currency].sort(key=lambda item: item.report_date)
        if len(records[currency]) < 500:
            raise ValueError(f"insufficient CFTC observations for {currency}: {len(records[currency])}")
    return records, manifest

def _rolling_z(values: Sequence[float], window: int) -> list[float]:
    result = [math.nan] * len(values)
    for i in range(window, len(values)):
        history = np.asarray(values[i-window:i], dtype=np.float64)
        std = float(np.std(history, ddof=1))
        if not math.isfinite(std) or std <= 0:
            continue
        result[i] = (float(values[i]) - float(np.mean(history))) / std
    return result

def _change(values: Sequence[float]) -> list[float]:
    return [math.nan] + [float(values[i] - values[i-1]) for i in range(1, len(values))]

def build_feature_panel(records: Mapping[str, Sequence[PositionObservation]]) -> dict[date, dict[str, float]]:
    panel: dict[date, dict[str, float]] = {}
    for currency in CURRENCIES:
        series = list(records[currency])
        raw = [x.normalized_net for x in series]
        change = _change(raw)
        for feature_type in FEATURE_TYPES:
            source = raw if feature_type == "level_z" else change
            for window in FEATURE_WINDOWS:
                for item, score in zip(series, _rolling_z(source, window), strict=True):
                    if math.isfinite(score):
                        panel.setdefault(item.report_date, {})[f"{currency}:{feature_type}:{window}"] = float(score)
    return panel

def _next_monday(report_date: date) -> date:
    days = (7 - report_date.weekday()) % 7
    if days == 0:
        days = 7
    return report_date + timedelta(days=days)

def _build_daily_bars(input_dir: Path) -> tuple[dict[str, list[DailyBar]], dict[str, dict[str, object]]]:
    daily: dict[str, list[DailyBar]] = {}
    quality: dict[str, dict[str, object]] = {}
    for pair, symbol in PAIR_TO_SYMBOL.items():
        rows, pair_quality = _execution_valid_rows(load_feed_bars(input_dir / f"{symbol}.jsonl"), pair)
        grouped: dict[date, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            timestamp_ms = int(_float_value(row["timestamp"]))
            grouped[datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date()].append(row)
        complete: list[DailyBar] = []
        for day, day_rows in sorted(grouped.items()):
            day_rows.sort(key=lambda row: int(_float_value(row["timestamp"])))
            stamps = [int(_float_value(row["timestamp"])) for row in day_rows]
            if len(day_rows) < 100 or any(b - a != 600_000 for a, b in zip(stamps, stamps[1:])):
                continue
            first, last = day_rows[0], day_rows[-1]
            complete.append(DailyBar(
                day=day, timestamp_ms=stamps[0], bid_open=_float_value(first["bid_open"]), ask_open=_float_value(first["ask_open"]),
                bid_close=_float_value(last["bid_close"]), ask_close=_float_value(last["ask_close"]), bar_count=len(day_rows),
            ))
        if len(complete) < 1000:
            raise ValueError(f"insufficient complete daily bars for {pair}: {len(complete)}")
        daily[pair] = complete
        quality[pair] = {**pair_quality, "complete_daily_bar_count": len(complete)}
    return daily, quality

def _index_daily(daily: Mapping[str, Sequence[DailyBar]]) -> dict[str, dict[date, int]]:
    return {pair: {bar.day: i for i, bar in enumerate(bars)} for pair, bars in daily.items()}

def _bootstrap_lower(values: Sequence[float], seed: int) -> float:
    if len(values) < 2:
        return math.nan
    rng = np.random.default_rng(seed)
    array = np.asarray(values, dtype=np.float64)
    means = np.mean(rng.choice(array, size=(BOOTSTRAP_REPS, len(array)), replace=True), axis=1)
    return float(np.quantile(means, 0.025))

def _block_lower(timestamp_means: Mapping[date, float], seed: int) -> float:
    ordered = sorted(timestamp_means)
    if len(ordered) < 2:
        return math.nan
    blocks = [ordered[i:i+BLOCK_SIZE] for i in range(0, len(ordered), BLOCK_SIZE)]
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(BOOTSTRAP_REPS):
        selected: list[date] = []
        while len(selected) < len(ordered):
            selected.extend(blocks[int(rng.integers(0, len(blocks)))])
        means.append(mean(timestamp_means[d] for d in selected[:len(ordered)]))
    return float(np.quantile(np.asarray(means, dtype=np.float64), 0.025))

def _safe_hac(values: Sequence[float]) -> float:
    return 1.0 if len(values) < 2 else hac_mean_pvalue(list(values), max_lag=min(5, len(values)-1))

def family_hypotheses() -> list[dict[str, object]]:
    return [
        {"feature_type": feature_type, "feature_window": window, "threshold": threshold, "orientation": orientation, "horizon": horizon}
        for feature_type in FEATURE_TYPES for window in FEATURE_WINDOWS
        for threshold in THRESHOLDS for orientation in ORIENTATIONS for horizon in HORIZONS
    ]

def _evaluate(
    values: Sequence[float],
    by_pair: Mapping[str, Sequence[float]],
    by_timestamp: Mapping[date, Sequence[float]],
    with_bootstrap: bool,
) -> dict[str, Any]:
    if not values:
        return {
            "n": 0, "unique_timestamps": 0, "expectancy_pips": None, "profit_factor": None,
            "hac_one_sided_pvalue": 1.0, "ordinary_bootstrap_lower": math.nan, "blocked_bootstrap_lower": math.nan,
            "positive_pair_count": 0, "largest_pair_observation_share": 1.0,
            "stress": {}, "passes_pre_holm": False,
        }
    timestamp_means = {d: mean(v) for d, v in by_timestamp.items()}
    expectancy = mean(values)
    pf = profit_factor(list(values))
    positive_pairs = sum(
        1 for v in by_pair.values()
        if len(v) >= MIN_PAIR_SAMPLES and mean(v) > 0
        and (pair_pf := profit_factor(list(v))) is not None and float(pair_pf) > 1.0
    )
    concentration = max((len(v) / len(values) for v in by_pair.values()), default=1.0)
    result: dict[str, Any] = {
        "n": len(values), "unique_timestamps": len(timestamp_means), "expectancy_pips": expectancy, "profit_factor": pf,
        "hac_one_sided_pvalue": _safe_hac(list(timestamp_means.values())),
        "ordinary_bootstrap_lower": math.nan, "blocked_bootstrap_lower": math.nan,
        "positive_pair_count": positive_pairs, "largest_pair_observation_share": concentration,
        "stress": {str(c): {"expectancy_pips": mean(x-c for x in values), "profit_factor": profit_factor([x-c for x in values])} for c in STRESS_COSTS_PIPS},
        "passes_pre_holm": (
            len(values) >= MIN_DISCOVERY_SAMPLES and len(timestamp_means) >= 100 and expectancy > 0
            and pf is not None and float(pf) >= MIN_DISCOVERY_PF
            and positive_pairs >= MIN_POSITIVE_PAIRS and concentration <= MAX_PAIR_CONCENTRATION
        ),
    }
    if with_bootstrap:
        result["ordinary_bootstrap_lower"] = _bootstrap_lower(list(timestamp_means.values()), 20260930)
        result["blocked_bootstrap_lower"] = _block_lower(timestamp_means, 20260931)
        result["passes_pre_holm"] = bool(result["passes_pre_holm"]) and float(result["ordinary_bootstrap_lower"]) > 0 and float(result["blocked_bootstrap_lower"]) > 0
    return result

def _outcomes(
    candidate: Mapping[str, Any],
    panel: Mapping[date, Mapping[str, float]],
    daily: Mapping[str, Sequence[DailyBar]],
    indices: Mapping[str, Mapping[date, int]],
    signal_days: Sequence[date],
    split_cutoff: date | None,
    holdout: bool,
) -> tuple[list[float], dict[str, list[float]], dict[date, list[float]]]:
    values: list[float] = []
    by_pair: dict[str, list[float]] = defaultdict(list)
    by_timestamp: dict[date, list[float]] = defaultdict(list)
    if split_cutoff is None:
        return values, by_pair, by_timestamp
    ft = str(candidate["feature_type"])
    window = int(candidate["feature_window"])
    threshold = float(candidate["threshold"])
    orientation = str(candidate["orientation"])
    horizon = int(candidate["horizon"])
    for entry_day in signal_days:
        in_holdout = entry_day >= split_cutoff
        if in_holdout != holdout:
            continue
        report_day = entry_day - timedelta(days=(entry_day.weekday() - 0) % 7 + 6)
        # Report dates are Tuesdays; map the Monday signal back to the immediately preceding Tuesday.
        desired_report = entry_day - timedelta(days=6)
        if desired_report not in panel:
            # Handle holidays where the signal day was delayed from the desired Monday.
            report_candidates = [d for d in panel if d <= entry_day and d.weekday() == 1]
            if not report_candidates:
                continue
            report_day = max(report_candidates)
        else:
            report_day = desired_report
        feature_values = panel.get(report_day, {})
        for pair, (base, quote) in PAIR_CURRENCY.items():
            a = feature_values.get(f"{base}:{ft}:{window}")
            b = feature_values.get(f"{quote}:{ft}:{window}")
            if a is None or b is None:
                continue
            score = float(a) - float(b)
            if not math.isfinite(score) or abs(score) < threshold:
                continue
            index = indices[pair].get(entry_day)
            if index is None or index + horizon - 1 >= len(daily[pair]):
                continue
            entry = daily[pair][index]
            target = daily[pair][index + horizon - 1]
            direction = 1 if score > 0 else -1
            if orientation == "reversion":
                direction *= -1
            movement = (
                (target.bid_close - entry.ask_open) / PAIR_PIP[pair]
                if direction > 0 else
                (entry.bid_open - target.ask_close) / PAIR_PIP[pair]
            )
            value = float(movement)
            values.append(value)
            by_pair[pair].append(value)
            by_timestamp[entry_day].append(value)
    return values, by_pair, by_timestamp

def _holman(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(results, key=lambda item: float(item["discovery"]["hac_one_sided_pvalue"]))
    previous = 0.0
    total = len(ordered)
    for i, item in enumerate(ordered):
        adjusted = min(1.0, max(previous, (total-i) * float(item["discovery"]["hac_one_sided_pvalue"])))
        item["discovery"]["holm_adjusted_pvalue"] = adjusted
        item["discovery"]["passes_familywise"] = bool(item["discovery"]["passes_pre_holm"]) and adjusted <= ALPHA
        previous = adjusted
    return ordered

def run_discovery(cftc_dir: Path, feed_dir: Path) -> dict[str, Any]:
    positions, cftc_manifest = load_positions(cftc_dir)
    panel = build_feature_panel(positions)
    daily, feed_quality = _build_daily_bars(feed_dir)
    indices = _index_daily(daily)
    report_dates = sorted(
        set().union(*(set(x.report_date for x in positions[c]) for c in CURRENCIES))
    )
    common_daily = sorted(set.intersection(*(set(x.day for x in daily[p]) for p in daily)))
    signal_days = []
    for report_day in report_dates:
        desired = _next_monday(report_day)
        candidate_days = [d for d in common_daily if d >= desired]
        if candidate_days:
            signal_days.append(candidate_days[0])
    signal_days = sorted(set(d for d in signal_days if d in common_daily))
    if len(signal_days) < 300:
        raise ValueError(f"too few release-gated signal days: {len(signal_days)}")
    split_cutoff = signal_days[int(len(signal_days) * DISCOVERY_FRACTION)]
    results: list[dict[str, Any]] = []
    for hypothesis in family_hypotheses():
        vals, by_pair, by_ts = _outcomes(hypothesis, panel, daily, indices, signal_days, split_cutoff, False)
        results.append({**hypothesis, "candidate": dict(hypothesis), "discovery": _evaluate(vals, by_pair, by_ts, False)})
    for item in results:
        if item["discovery"]["passes_pre_holm"]:
            vals, by_pair, by_ts = _outcomes(item["candidate"], panel, daily, indices, signal_days, split_cutoff, False)
            item["discovery"] = _evaluate(vals, by_pair, by_ts, True)
    results = _holman(results)
    survivors = [x for x in results if x["discovery"].get("passes_familywise")]
    survivors.sort(key=lambda x: (float(x["discovery"]["holm_adjusted_pvalue"]), -float(x["discovery"]["ordinary_bootstrap_lower"]), -float(x["discovery"]["expectancy_pips"])))
    confirmation: dict[str, Any] | None = None
    if survivors:
        frozen = survivors[0]
        vals, by_pair, by_ts = _outcomes(frozen["candidate"], panel, daily, indices, signal_days, split_cutoff, True)
        conf = _evaluate(vals, by_pair, by_ts, True)
        confirmation = {"rank": 1, "candidate": frozen["candidate"], "discovery": frozen["discovery"], "confirmation": conf}
    if confirmation is not None:
        confirmation_result = confirmation["confirmation"]
        confirmation_result["passes_final_confirmation"] = bool(
            confirmation_result["passes_pre_holm"]
            and float(confirmation_result["hac_one_sided_pvalue"]) <= ALPHA
        )
        confirmation["state"] = (
            "PASS" if confirmation_result["passes_final_confirmation"] else "FAIL"
        )
    return {
        "status": "CFTC_POSITIONING_DISCOVERY_COMPLETED",
        "contract_version": CONTRACT_VERSION,
        "family_size": FAMILY_SIZE,
        "candidate_count": len(survivors),
        "top_candidates": survivors[:10],
        "confirmation": confirmation,
        "signal_week_count": len(signal_days),
        "global_split_cutoff": split_cutoff.isoformat(),
        "release_date_contract": {
            "report_date_scope": "union_of_currency_reports",
            "signal_rule": "first complete common FX day on or after the following Monday UTC",
            "pair_feature_rule": "pairs without both released currency features are skipped for that signal day",
        },
        "cftc_years": [CFTC_START_YEAR, CFTC_END_YEAR],
        "cftc_manifest": cftc_manifest,
        "feed_quality": feed_quality,
        "selection_policy": {
            "whole_family_holm": True, "holm_scope": FAMILY_SIZE, "confirmation_used_for_selection": False,
            "release_gate": "Tuesday COT observation is first eligible for trading use on the following Monday UTC",
            "daily_sampling": "one common nine-pair entry day per weekly COT report",
            "feature_family": "rolling z-score of normalized noncommercial net positioning level or weekly change, with 4/8/13/26-report lookbacks",
            "direction": "base minus quote positioning score; momentum follows score and reversion reverses it",
            "execution": "entry at first complete UTC-day BID/ASK open and exit at horizon-day BID/ASK close",
            "stress_costs_pips": list(STRESS_COSTS_PIPS),
            "pair_gate": ">=3 positive pairs with >=20 observations each; <=80% observation concentration",
        },
        "promotion_authorized": False,
        "live_execution_authorized": False,
    }

def main() -> None:
    parser = argparse.ArgumentParser(description="Non-live CFTC positioning discovery for FX.")
    parser.add_argument("--cftc-dir", required=True)
    parser.add_argument("--feed-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run_discovery(Path(args.cftc_dir), Path(args.feed_dir))
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"STATUS={report['status']}")
    print(f"FAMILY_SIZE={report['family_size']}")
    print(f"CANDIDATE_COUNT={report['candidate_count']}")
    print(f"SIGNAL_WEEK_COUNT={report['signal_week_count']}")
    if report["confirmation"] is None:
        print("CONFIRMATION_STATE=NO_DISCOVERY_CANDIDATE")
    else:
        c = report["confirmation"]["confirmation"]
        print(f"CONFIRMATION_N={c['n']}")
        print(f"CONFIRMATION_EXPECTANCY_PIPS={c['expectancy_pips']}")
        print(f"CONFIRMATION_PROFIT_FACTOR={c['profit_factor']}")
        print(f"CONFIRMATION_PRE_HOLM={c['passes_pre_holm']}")
    print("PROMOTION_AUTHORIZED=false")
    print("LIVE_EXECUTION_AUTHORIZED=false")

if __name__ == "__main__":
    main()
