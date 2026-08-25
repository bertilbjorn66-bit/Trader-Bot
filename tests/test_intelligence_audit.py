from research.intelligence_audit import (
    calibration_bins,
    cost_stress_curve,
    lagged_correlations,
    regime_transition_stats,
    summarize_audit,
    walk_forward_audit,
)
from research.intelligence_controls import ExecutionCostModel


def test_cost_stress_curve_marks_edges_after_costs() -> None:
    points = cost_stress_curve(
        2.0,
        {
            "base": ExecutionCostModel(0.5, 0.1, 0.1),
            "stress": ExecutionCostModel(1.5, 0.5, 0.5),
        },
    )
    assert points[0].profitable
    assert not points[1].profitable


def test_lagged_correlations_include_negative_and_positive_lags() -> None:
    points = lagged_correlations([1, 2, 3, 4, 5], [0, 1, 2, 3, 4], max_lag=2)
    assert {p.lag for p in points} == {-2, -1, 0, 1, 2}


def test_transition_stats_are_probabilistic_and_outcome_aware() -> None:
    stats = regime_transition_stats(["R", "T", "T", "R"], [0.0, 1.0, 2.0, -1.0])
    assert sum(stat.probability for stat in stats if stat.from_state == "T") == 1.0
    assert any(stat.to_state == "T" and stat.mean_outcome > 0 for stat in stats)


def test_calibration_bins_preserve_empirical_rates() -> None:
    bins = calibration_bins([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1], bins=2)
    assert len(bins) == 2
    assert bins[0].empirical_rate == 0.0
    assert bins[1].empirical_rate == 1.0


def test_walk_forward_audit_is_leakage_free() -> None:
    audit = walk_forward_audit(200, 80, 40, 40)
    assert audit.fold_count == 3
    assert audit.leakage_free


def test_summary_marks_non_live_audit_readiness() -> None:
    costs = cost_stress_curve(2.0, {"base": ExecutionCostModel(0.5, 0.1, 0.1)})
    lags = lagged_correlations([1, 2, 3, 4], [1, 2, 3, 4], max_lag=1)
    transitions = regime_transition_stats(["A", "B", "A"], [1.0, 2.0, 3.0])
    cal = calibration_bins([0.2, 0.8], [0, 1], bins=2)
    wf = walk_forward_audit(50, 20, 10, 10)
    summary = summarize_audit(costs, lags, transitions, cal, wf)
    assert summary.ready_for_non_live_profitability_audit
