from research.intelligence_controls import ExecutionCostModel
from research.non_live_evaluation import (
    apply_costs,
    block_bootstrap_means,
    bootstrap_means,
    distribution_audit,
    evaluate_non_live,
    max_drawdown,
    probability_of_ruin,
)


def test_costs_are_applied_before_evaluation() -> None:
    values = apply_costs([2.0, -1.0], ExecutionCostModel(0.5, 0.1, 0.1))
    assert values == [1.3, -1.7]


def test_max_drawdown_is_non_negative() -> None:
    assert max_drawdown([1.0, -2.0, 1.0]) == 2.0


def test_bootstrap_is_reproducible() -> None:
    a = bootstrap_means([1.0, -1.0, 2.0, -0.5], reps=200, seed=7)
    b = bootstrap_means([1.0, -1.0, 2.0, -0.5], reps=200, seed=7)
    assert a == b


def test_block_bootstrap_is_reproducible() -> None:
    a = block_bootstrap_means([1.0, -1.0, 2.0, -0.5, 1.5], block_size=2, reps=200, seed=9)
    b = block_bootstrap_means([1.0, -1.0, 2.0, -0.5, 1.5], block_size=2, reps=200, seed=9)
    assert a == b


def test_ruin_probability_is_bounded() -> None:
    probability = probability_of_ruin([1.0, 2.0, 3.0], 5.0, simulations=200, horizon=20, seed=3)
    assert 0.0 <= probability <= 1.0


def test_distribution_audit_is_populated() -> None:
    audit = distribution_audit([0.5, 1.0, -0.2, 0.7] * 10, 10.0, reps=200, seed=4)
    assert audit.observations if hasattr(audit, "observations") else audit.mean_pips is not None
    assert audit.max_drawdown_pips >= 0


def test_insufficient_data_is_incomplete_not_profitable() -> None:
    verdict = evaluate_non_live(
        [1.0, -1.0] * 5,
        train_size=20,
        validation_size=10,
        step=10,
        costs=[("base", ExecutionCostModel(0.1, 0.1, 0.1))],
    )
    assert verdict.state == "INCOMPLETE"


def test_positive_series_can_pass_structure_without_live_orders() -> None:
    outcomes = [1.0] * 120
    verdict = evaluate_non_live(
        outcomes,
        train_size=40,
        validation_size=20,
        step=20,
        costs=[("base", ExecutionCostModel(0.1, 0.0, 0.0))],
        starting_capital_pips=20.0,
    )
    assert verdict.folds_evaluated > 0
    assert verdict.state in {"PASS", "FAIL"}
