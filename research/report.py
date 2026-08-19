from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Mapping


def build_report(
    *,
    dataset: Mapping[str, object],
    findings: list[Mapping[str, object]],
    warnings: list[str],
    empirical: bool,
) -> dict[str, object]:
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "empirical": empirical,
        "empirical_results_status": "REAL_DATA_REQUIRED" if not empirical else "COMPUTED_FROM_REAL_DATA",
        "dataset": dict(dataset),
        "findings": [dict(x) for x in findings],
        "warnings": list(warnings),
        "research_boundary": "Research output is not live-execution authorization.",
    }


def write_json(report: Mapping[str, object], path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
