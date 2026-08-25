from research.hierarchical_context_validation import bootstrap_ci, metrics


def test_bootstrap_is_not_a_permutation() -> None:
    values = tuple(float(index) for index in range(100))
    lower, upper = bootstrap_ci(values, seed=123)
    assert lower is not None
    assert upper is not None
    assert lower < upper


def test_strong_context_requires_positive_bootstrap_bound() -> None:
    values = tuple([1.0] * 60 + [-0.5] * 40)
    years = tuple([2020] * 34 + [2021] * 33 + [2022] * 33)
    result = metrics(values, years, bootstrap=True, seed=99)
    assert result["n"] == 100
    assert result["expectancy_pips"] > 0
    assert result["profit_factor"] > 1
    lower = result["bootstrap_expectancy_ci_pips"][0]
    assert lower is not None
    assert result["status"] in {"STRONG_CONTEXT", "WATCH_CONTEXT"}


def test_weak_confirmation_cannot_be_strong() -> None:
    values = tuple([0.2] * 50 + [-0.2] * 50)
    years = tuple([2020] * 34 + [2021] * 33 + [2022] * 33)
    result = metrics(values, years, bootstrap=True, seed=7)
    assert result["status"] != "STRONG_CONTEXT"
