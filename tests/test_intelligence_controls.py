from research.intelligence_controls import (
    EventRegime,
    ExecutionCostModel,
    ExpertVote,
    calibration_report,
    drift_report,
    make_walk_forward_folds,
    pearson_correlation,
    route_experts,
)


def test_execution_costs_reduce_gross_edge() -> None:
    model = ExecutionCostModel(0.8, 0.2, 0.1, 0.0)
    assert model.total_cost_pips() == 1.1
    assert model.net_expectancy(2.0) == 0.9


def test_pair_correlation_is_bounded() -> None:
    corr = pearson_correlation([1, 2, 3], [2, 4, 6])
    assert 0.999 < corr <= 1.0


def test_event_regime_rejects_lookahead() -> None:
    regime = EventRegime("n1", "CPI", 100, 110, 110, 120)
    try:
        regime.validate_no_lookahead()
    except ValueError:
        pass
    else:
        raise AssertionError("look-ahead event regime accepted")


def test_event_regime_is_time_bounded() -> None:
    regime = EventRegime("n1", "CPI", 100, 90, 100, 120)
    regime.validate_no_lookahead()
    assert regime.contains(110)
    assert not regime.contains(121)


def test_calibration_report_is_deterministic() -> None:
    report = calibration_report([0.2, 0.8, 0.7, 0.1], [0, 1, 1, 0], bins=4)
    assert report.observations == 4
    assert report.brier_score >= 0
    assert report.expected_calibration_error >= 0


def test_drift_detects_mean_shift() -> None:
    report = drift_report([0.0, 0.0, 0.1], [1.0, 1.0, 1.1], mean_threshold=0.5)
    assert report.drift


def test_walk_forward_folds_never_leak_future_data() -> None:
    folds = make_walk_forward_folds(100, 40, 20, 20)
    assert folds
    for fold in folds:
        fold.validate()
        assert fold.train_end < fold.validation_start


def test_expert_router_abstains_on_disagreement() -> None:
    route = route_experts(
        [ExpertVote("a", "BUY", 0.8), ExpertVote("b", "SELL", 0.8)],
        min_confidence=0.6,
        max_disagreement=0.2,
    )
    assert route.action == "ABSTAIN"


def test_expert_router_routes_consensus() -> None:
    route = route_experts(
        [ExpertVote("a", "BUY", 0.8), ExpertVote("b", "BUY", 0.7), ExpertVote("c", "SELL", 0.1)],
        min_confidence=0.6,
        max_disagreement=0.25,
    )
    assert route.action == "ROUTE"
    assert route.direction == "BUY"


def test_control_state_requires_every_layer() -> None:
    from research.intelligence_controls import IntelligenceControlState

    state = IntelligenceControlState(True, True, True, True, True, True, False)
    assert not state.ready()
    assert IntelligenceControlState(True, True, True, True, True, True, True).ready()
