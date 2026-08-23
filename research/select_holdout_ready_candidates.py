from __future__ import annotations

import argparse
import json
from pathlib import Path

MIN_HOLDOUT_SAMPLES = 100


def matches(record: dict[str, object], candidate: dict[str, object], split: str) -> bool:
    return (
        record["split"] == split
        and record["horizon"] == candidate["horizon"]
        and record["regime"] == candidate["regime"]
        and record["session"] == candidate["session"]
        and (candidate["pairset"] == "all" or str(record["pair"]).endswith("/JPY"))
        and (
            candidate["distance_max"] is None
            or float(record["median_distance"]) <= float(candidate["distance_max"])
        )
        and float(record["agreement"]) >= float(candidate["agreement_min"])
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze discovery-only candidates that have at least 100 structurally available holdout observations."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    records = data["target_records"]
    candidates = data["discovery_candidates"]

    eligible: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []

    for candidate in candidates:
        # This count uses only structural target metadata. No holdout outcome,
        # expectancy, win/loss, or profit-factor value is used for selection.
        holdout_n = sum(1 for record in records if matches(record, candidate, "confirmation"))
        candidate_copy = dict(candidate)
        candidate_copy["holdout_structural_n"] = holdout_n
        if holdout_n >= MIN_HOLDOUT_SAMPLES:
            eligible.append(candidate_copy)
        else:
            rejected.append(candidate_copy)

    eligible.sort(
        key=lambda candidate: (
            float(candidate["discovery"]["expectancy_pips"]),
            float(candidate["discovery"]["profit_factor"] or float("-inf")),
        ),
        reverse=True,
    )
    finalists = eligible[:10]

    data["confirmation_finalists"] = finalists
    data["holdout_selection"] = {
        "status": "DISCOVERY_ONLY_HOLDOUT_CAPACITY_FILTER_COMPLETED",
        "minimum_holdout_samples": MIN_HOLDOUT_SAMPLES,
        "candidate_pool_size": len(candidates),
        "structurally_eligible_candidates": len(eligible),
        "rejected_for_holdout_capacity": len(rejected),
        "finalists_selected": len(finalists),
        "selection_rule": "holdout structural count only; holdout outcomes are not used during finalist selection",
        "rejected_examples": rejected[:20],
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
