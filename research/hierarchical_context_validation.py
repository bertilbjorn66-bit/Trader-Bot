from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence

BOOTSTRAP_REPS = 2_000
MIN_DISCOVERY_N = 100
MIN_CONFIRMATION_N = 100
MIN_NO_TRADE_N = 30
STRONG_STABILITY = 2 / 3

SPECS = {
    "pair_horizon_regime_direction": ("pair", "horizon", "regime", "direction"),
    "pair_horizon_regime_session_direction": (
        "pair",
        "horizon",
        "regime",
        "session",
        "direction",
    ),
    "pair_horizon_regime_session": ("pair", "horizon", "regime", "session"),
}


def profit_factor(values: Sequence[float]) -> float | None:
    gross_win = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    if gross_loss == 0:
        return None
    return gross_win / gross_loss


def bootstrap_ci(
    values: Sequence[float], seed: int, reps: int = BOOTSTRAP_REPS
) -> tuple[float, float] | tuple[None, None]:
    if len(values) < MIN_CONFIRMATION_N:
        return (None, None)
    rng = random.Random(seed)
    n = len(values)
    means: list[float] = []
    for _ in range(reps):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    lower_index = max(0, int(0.025 * reps) - 1)
    upper_index = min(reps - 1, int(0.975 * reps))
    return means[lower_index], means[upper_index]


def metrics(
    values: Sequence[float],
    years: Sequence[int],
    *,
    bootstrap: bool,
    seed: int = 0,
) -> dict[str, object]:
    count = len(values)
    expectancy = sum(values) / count if count else None
    profit_factor_value = profit_factor(values)
    by_year: dict[int, list[float]] = defaultdict(list)
    for year, value in zip(years, values):
        by_year[year].append(value)
    positive_years = sum(
        sum(year_values) / len(year_values) > 0
        for year_values in by_year.values()
    )
    observed_years = len(by_year)
    stability = positive_years / observed_years if observed_years else 0.0
    ci = bootstrap_ci(values, seed) if bootstrap else (None, None)

    status = "UNKNOWN"
    if count >= MIN_CONFIRMATION_N:
        if (
            expectancy is not None
            and expectancy > 0
            and profit_factor_value is not None
            and profit_factor_value > 1
            and ci[0] is not None
            and ci[0] > 0
            and stability >= STRONG_STABILITY
        ):
            status = "STRONG_CONTEXT"
        elif expectancy is not None and (
            expectancy > 0
            or (profit_factor_value is not None and profit_factor_value > 1)
        ):
            status = "WATCH_CONTEXT"
        elif expectancy is not None and (
            expectancy <= 0
            or (profit_factor_value is not None and profit_factor_value <= 1)
        ):
            status = "NO_TRADE"
    elif count >= MIN_NO_TRADE_N and expectancy is not None and (
        expectancy <= 0
        or (profit_factor_value is not None and profit_factor_value <= 1)
    ):
        status = "NO_TRADE"

    return {
        "n": count,
        "expectancy_pips": expectancy,
        "profit_factor": profit_factor_value,
        "win_rate": sum(value > 0 for value in values) / count if count else None,
        "positive_years": positive_years,
        "observed_years": observed_years,
        "stability_ratio": stability,
        "bootstrap_expectancy_ci_pips": list(ci),
        "status": status,
    }


def build_groups(records: Iterable[dict]) -> dict[tuple[str, tuple[object, ...], str], tuple[tuple[float, ...], tuple[int, ...]]]:
    buckets: dict[tuple[str, tuple[object, ...], str], list[tuple[float, int]]] = defaultdict(list)
    for record in records:
        for spec, keys in SPECS.items():
            key = tuple(record[key_name] for key_name in keys)
            buckets[(spec, key, record["split"])].append(
                (float(record["outcome_pips"]), int(record["year"]))
            )
    return {
        bucket_key: (
            tuple(value for value, _ in values),
            tuple(year for _, year in values),
        )
        for bucket_key, values in buckets.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source_path = Path(args.input)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    records = source["target_records"]
    source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    groups = build_groups(records)

    discovery_candidates: list[dict[str, object]] = []
    for (spec, key, split), (values, years) in groups.items():
        if split != "discovery" or len(values) < MIN_DISCOVERY_N:
            continue
        discovery = metrics(values, years, bootstrap=False)
        if (
            discovery["expectancy_pips"] is not None
            and discovery["expectancy_pips"] > 0
            and discovery["profit_factor"] is not None
            and discovery["profit_factor"] > 1
        ):
            discovery_candidates.append(
                {"spec": spec, "key": list(key), "discovery": discovery}
            )

    discovery_candidates.sort(
        key=lambda candidate: (
            float(candidate["discovery"]["expectancy_pips"]),
            float(candidate["discovery"]["profit_factor"]),
            int(candidate["discovery"]["n"]),
        ),
        reverse=True,
    )

    selected: list[dict[str, object]] = []
    per_spec: dict[str, int] = defaultdict(int)
    for candidate in discovery_candidates:
        spec = str(candidate["spec"])
        if per_spec[spec] >= 20:
            continue
        selected.append(candidate)
        per_spec[spec] += 1

    confirmation_results: list[dict[str, object]] = []
    for candidate in selected:
        spec = str(candidate["spec"])
        key = tuple(candidate["key"])
        group = groups.get((spec, key, "confirmation"))
        if group is None:
            continue
        values, years = group
        if len(values) < MIN_CONFIRMATION_N:
            continue
        seed_material = f"{spec}|{key}|confirmation".encode("utf-8")
        seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
        confirmation = metrics(values, years, bootstrap=True, seed=seed)
        confirmation_results.append(
            {
                "spec": spec,
                "key": list(key),
                "split": "confirmation",
                "discovery_metrics": candidate["discovery"],
                "confirmation_metrics": confirmation,
            }
        )

    strong = [
        result
        for result in confirmation_results
        if result["confirmation_metrics"]["status"] == "STRONG_CONTEXT"
    ]
    watch = [
        result
        for result in confirmation_results
        if result["confirmation_metrics"]["status"] == "WATCH_CONTEXT"
    ]
    no_trade = [
        result
        for result in confirmation_results
        if result["confirmation_metrics"]["status"] == "NO_TRADE"
    ]

    result = {
        "status": "HIERARCHICAL_CONTEXT_VALIDATION_COMPLETED",
        "source": "VERIFIED-FINAL-HOLDOUT-RESEARCH",
        "record_count": len(records),
        "input_sha256": source_digest,
        "methodology": {
            "purpose": "test broader context abstractions without tuning on confirmation data",
            "hierarchies": {name: list(keys) for name, keys in SPECS.items()},
            "discovery_min_samples": MIN_DISCOVERY_N,
            "confirmation_min_samples": MIN_CONFIRMATION_N,
            "fixed_top_k_per_hierarchy": 20,
            "bootstrap_reps": BOOTSTRAP_REPS,
            "strong_rule": "confirmation n>=100, expectancy>0, PF>1, lower bootstrap bound>0, positive expectancy in >=67% of observed years",
            "no_trade_rule": "confirmation n>=30, non-positive expectancy or PF<=1",
            "selection_split": "discovery_only",
            "live_authorization": "never granted by this analysis",
            "input_mutation": "none",
        },
        "summary": {
            "discovery_candidates": len(discovery_candidates),
            "selected_candidates": len(selected),
            "confirmation_evaluated": len(confirmation_results),
            "strong_contexts": len(strong),
            "watch_contexts": len(watch),
            "no_trade_contexts": len(no_trade),
        },
        "strong_contexts": strong,
        "watch_contexts": watch,
        "no_trade_contexts": no_trade,
    }
    Path(args.output).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("HIERARCHICAL_CONTEXT_VALIDATION_COMPLETED=true")
    print("DISCOVERY_CANDIDATES=", len(discovery_candidates))
    print("CONFIRMATION_EVALUATED=", len(confirmation_results))
    print("STRONG_CONTEXTS=", len(strong))
    print("WATCH_CONTEXTS=", len(watch))
    print("NO_TRADE_CONTEXTS=", len(no_trade))
    print("INPUT_SHA256=", source_digest)


if __name__ == "__main__":
    main()
