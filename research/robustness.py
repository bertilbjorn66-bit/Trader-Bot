from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence


def perturbation_grid(base: float, relative_changes: Iterable[float] = (-0.10, -0.05, 0.0, 0.05, 0.10)) -> list[float]:
    if base <= 0:
        raise ValueError("base must be positive")
    return [base * (1.0 + delta) for delta in relative_changes]


def stability_score(values: Sequence[float]) -> float | None:
    if not values:
        return None
    positives = sum(v > 0 for v in values) / len(values)
    magnitude = sum(abs(v) for v in values) / len(values)
    if magnitude == 0:
        return 0.0
    return positives


def evaluate_sensitivity(parameters: Sequence[float], evaluate: Callable[[float], float]) -> list[dict[str, float]]:
    return [{"parameter": p, "metric": evaluate(p)} for p in parameters]
