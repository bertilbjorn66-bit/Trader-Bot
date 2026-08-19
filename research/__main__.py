from __future__ import annotations

import json

from .pipeline import research_snapshot
from .report import build_report
from .synthetic import generate_bars


def main() -> None:
    bars = generate_bars(260)
    snapshot = research_snapshot(bars, target_index=210, horizon=5, k=25)
    report = build_report(
        dataset={
            "source": "SYNTHETIC_TEST_ONLY",
            "bars": len(bars),
            "empirical_results": False,
        },
        findings=[snapshot],
        warnings=["SYNTHETIC TEST — NOT REAL MARKET RESULTS"],
        empirical=False,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
