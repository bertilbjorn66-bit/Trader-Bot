from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trader_bot.paper_campaign import (
    PaperCampaignSpec,
    PaperCampaignState,
    PaperPerformanceGate,
)
from trader_bot.paper_eval import PaperEvaluationResult, PaperEvaluationSpec


START = datetime(2026, 8, 1, tzinfo=timezone.utc)
END = START + timedelta(days=7)


def evaluation_spec() -> PaperEvaluationSpec:
    return PaperEvaluationSpec(
        strategy_id="frozen-candidate",
        strategy_version="1",
        research_reference="verified-paper-reference",
        maximum_session_loss=Decimal("-100"),
        minimum_closed_trades=100,
    )


def campaign_spec() -> PaperCampaignSpec:
    return PaperCampaignSpec(
        campaign_id="paper-2026-08-01",
        strategy_fingerprint="strategy-snapshot-sha256",
        evaluation_spec=evaluation_spec(),
        start_at=START,
        end_at=END,
        minimum_accepted_observations=1000,
    )


def evaluation(*, passed: bool = True, expectancy: str = "0.10", profit_factor: str | None = "1.50") -> PaperEvaluationResult:
    return PaperEvaluationResult(
        spec_fingerprint=evaluation_spec().fingerprint(),
        closed_trades=100,
        winning_trades=60,
        losing_trades=40,
        total_pnl=Decimal("10"),
        expectancy=Decimal(expectancy),
        profit_factor=Decimal(profit_factor) if profit_factor is not None else None,
        max_drawdown=Decimal("20"),
        passed=passed,
        failure_reasons=() if passed else ("maximum_session_loss_breached",),
    )


def test_campaign_pass_requires_complete_window_and_positive_performance() -> None:
    result = PaperPerformanceGate(campaign_spec()).evaluate(
        accepted_observations=1000,
        rejected_observations=50,
        evaluation=evaluation(),
        finalized_at=END,
    )
    assert result.state is PaperCampaignState.COMPLETE
    assert result.failure_reasons == ()


def test_early_finalization_is_incomplete_not_a_paper_pass() -> None:
    result = PaperPerformanceGate(campaign_spec()).evaluate(
        accepted_observations=1000,
        rejected_observations=50,
        evaluation=evaluation(),
        finalized_at=END - timedelta(hours=1),
    )
    assert result.state is PaperCampaignState.INCOMPLETE
    assert "campaign_window_not_complete" in result.failure_reasons


def test_insufficient_observations_are_incomplete() -> None:
    result = PaperPerformanceGate(campaign_spec()).evaluate(
        accepted_observations=999,
        rejected_observations=50,
        evaluation=evaluation(),
        finalized_at=END,
    )
    assert result.state is PaperCampaignState.INCOMPLETE
    assert "minimum_accepted_observations_not_met" in result.failure_reasons


def test_negative_expectancy_fails_even_with_enough_observations() -> None:
    result = PaperPerformanceGate(campaign_spec()).evaluate(
        accepted_observations=1000,
        rejected_observations=50,
        evaluation=evaluation(expectancy="-0.01"),
        finalized_at=END,
    )
    assert result.state is PaperCampaignState.FAILED
    assert "paper_expectancy_not_positive" in result.failure_reasons


def test_profit_factor_at_threshold_fails() -> None:
    result = PaperPerformanceGate(campaign_spec()).evaluate(
        accepted_observations=1000,
        rejected_observations=50,
        evaluation=evaluation(profit_factor="1.00"),
        finalized_at=END,
    )
    assert result.state is PaperCampaignState.FAILED
    assert "paper_profit_factor_not_above_threshold" in result.failure_reasons


def test_missing_evaluation_never_passes() -> None:
    result = PaperPerformanceGate(campaign_spec()).evaluate(
        accepted_observations=1000,
        rejected_observations=50,
        evaluation=None,
        finalized_at=END,
    )
    assert result.state is PaperCampaignState.INCOMPLETE
    assert "paper_evaluation_missing" in result.failure_reasons


def test_evaluation_spec_fingerprint_mismatch_fails() -> None:
    wrong = PaperEvaluationResult(
        spec_fingerprint="wrong-fingerprint",
        closed_trades=100,
        winning_trades=60,
        losing_trades=40,
        total_pnl=Decimal("10"),
        expectancy=Decimal("0.10"),
        profit_factor=Decimal("1.50"),
        max_drawdown=Decimal("20"),
        passed=True,
        failure_reasons=(),
    )
    result = PaperPerformanceGate(campaign_spec()).evaluate(
        accepted_observations=1000,
        rejected_observations=50,
        evaluation=wrong,
        finalized_at=END,
    )
    assert result.state is PaperCampaignState.FAILED
    assert "evaluation_specification_mismatch" in result.failure_reasons


def test_campaign_spec_cannot_be_made_with_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        PaperCampaignSpec(
            campaign_id="bad",
            strategy_fingerprint="strategy",
            evaluation_spec=evaluation_spec(),
            start_at=datetime(2026, 8, 1),
            end_at=datetime(2026, 8, 2),
            minimum_accepted_observations=100,
        )
