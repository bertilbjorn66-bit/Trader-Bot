from __future__ import annotations

from research.anti_overfit import perturbation_audit, stability_ratio, summarize_trials
from research.behavioral_memory import (
    BehavioralObservation,
    chronological_memory,
    conditional_memory,
    summarize_context,
)
from research.model_health import HealthState, assess_model_health
from research.opportunity_ranking import Opportunity, rank_opportunities


def test_behavioral_memory_is_strictly_chronological() -> None:
    observations = (
        BehavioralObservation(3, "BTC/USD", "trend", {"momentum": 1.0}, 2.0),
        BehavioralObservation(1, "BTC/USD", "trend", {"momentum": 0.9}, 1.0),
        BehavioralObservation(4, "BTC/USD", "trend", {"momentum": 1.1}, 3.0),
    )
    history = chronological_memory(observations, cutoff_timestamp=4)
    assert [item.timestamp for item in history] == [1, 3]


def test_conditional_memory_never_reads_future_observations() -> None:
    observations = (
        BehavioralObservation(1, "XAU/USD", "range", {"volatility": 0.5, "momentum": 0.1}, 1.0),
        BehavioralObservation(9, "XAU/USD", "range", {"volatility": 0.5, "momentum": 0.1}, 9.0),
    )
    matches = conditional_memory(
        observations,
        instrument="XAU/USD",
        cutoff_timestamp=9,
        context={"volatility": 0.5, "momentum": 0.1},
        tolerances={"volatility": 0.01, "momentum": 0.01},
    )
    assert [item.timestamp for item in matches] == [1]


def test_context_summary_exposes_distribution_not_only_direction() -> None:
    observations = tuple(
        BehavioralObservation(index, "ETH/USD", "breakout", {}, 1.0 if index % 2 == 0 else -0.5)
        for index in range(20)
    )
    summary = summarize_context(observations, instrument="ETH/USD", regime="breakout")
    assert summary.observations == 20
    assert summary.profit_factor is not None
    assert summary.outcome_std > 0


def test_anti_overfit_reports_selection_pressure() -> None:
    summary = summarize_trials([0.1, 0.2, 0.15, 1.2, 0.05])
    assert summary.trial_count == 5
    assert summary.best_oos_score == 1.2
    assert summary.selection_risk > 0


def test_perturbation_audit_rejects_destroyed_edge() -> None:
    result = perturbation_audit(1.0, [0.9, 0.8, 0.7], maximum_degradation_fraction=0.20)
    assert result.robust is False
    assert result.worst_score == 0.7


def test_stability_ratio_is_explicit() -> None:
    assert stability_ratio([1.0, -1.0, 2.0, 3.0]) == 0.75


def test_opportunity_ranking_prefers_lower_uncertainty_and_concentration() -> None:
    ranked = rank_opportunities([
        Opportunity("BTC/USD", "CRYPTO", 1.0, 0.10, 0.01, 0.95, 0.05, 0.05),
        Opportunity("XAU/USD", "METAL", 1.0, 0.40, 0.01, 0.95, 0.05, 0.60),
    ])
    assert ranked[0].opportunity.symbol == "BTC/USD"
    assert ranked[0].rank == 1


def test_model_health_enters_observation_only_after_material_deterioration() -> None:
    assessment = assess_model_health(
        recent_outcomes=[-1.0, -1.0, -0.5, -0.5],
        reference_outcomes=[1.0, 1.0, 1.0, 1.0],
    )
    assert assessment.state is HealthState.OBSERVATION_ONLY
    assert assessment.reasons
