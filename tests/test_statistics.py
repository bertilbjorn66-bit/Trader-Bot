from __future__ import annotations

from research.statistics import HAC_DEFAULT_LAG, hac_mean_pvalue


def test_shared_hac_rejects_clear_positive_series() -> None:
    assert hac_mean_pvalue([1.0] * 500) == 0.0
    assert hac_mean_pvalue([-1.0] * 500) == 1.0


def test_shared_hac_default_lag_is_predeclared() -> None:
    assert HAC_DEFAULT_LAG == 5
