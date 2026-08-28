from research.trade_evolution import (
    TradeAction,
    TradeEvolutionPolicy,
    TradeObservation,
    TradePhase,
    evaluate_trade_evolution,
    summarize_trade_trajectories,
)
from trader_bot.asset_universe import AssetClass


def observation(**overrides):
    values = {
        "timestamp": 1,
        "asset_class": AssetClass.FOREX,
        "unrealized_return": 0.10,
        "max_favorable_excursion": 0.12,
        "max_adverse_excursion": 0.03,
        "thesis_strength": 0.80,
        "liquidity_score": 0.90,
        "cost_score": 0.90,
        "context_score": 0.85,
        "invalidation_score": 0.10,
    }
    values.update(overrides)
    return TradeObservation(**values)


def test_strong_trade_remains_open():
    state = evaluate_trade_evolution([observation(), observation(timestamp=2)])
    assert state.action is TradeAction.HOLD
    assert state.phase is TradePhase.EARLY


def test_invalidated_trade_exits():
    state = evaluate_trade_evolution(
        [observation(timestamp=1), observation(timestamp=2, invalidation_score=0.90)]
    )
    assert state.action is TradeAction.EXIT
    assert state.phase is TradePhase.EXIT_READY


def test_deteriorating_profitable_trade_reduces():
    state = evaluate_trade_evolution(
        [
            observation(timestamp=1),
            observation(
                timestamp=2,
                thesis_strength=0.50,
                context_score=0.50,
                liquidity_score=0.40,
                cost_score=0.45,
            ),
        ]
    )
    assert state.action in {TradeAction.REDUCE, TradeAction.FREEZE}
    assert state.phase is TradePhase.DETERIORATING


def test_crypto_receives_domain_specific_penalty():
    state = evaluate_trade_evolution(
        [observation(asset_class=AssetClass.CRYPTO, liquidity_score=0.40, cost_score=0.40)]
    )
    assert state.action is TradeAction.HOLD
    assert state.phase is TradePhase.EARLY


def test_policy_rejects_invalid_threshold_order():
    try:
        TradeEvolutionPolicy(deterioration_threshold=0.8, invalidation_threshold=0.7).validate()
    except ValueError as exc:
        assert "below invalidation" in str(exc)
    else:
        raise AssertionError("invalid policy must be rejected")


def test_trade_cannot_mix_asset_classes():
    try:
        evaluate_trade_evolution(
            [observation(timestamp=1), observation(timestamp=2, asset_class=AssetClass.CRYPTO)]
        )
    except ValueError as exc:
        assert "asset class" in str(exc)
    else:
        raise AssertionError("mixed asset classes must be rejected")


def test_trade_trajectory_must_be_strictly_chronological():
    try:
        summarize_trade_trajectories([[observation(timestamp=2), observation(timestamp=1)]])
    except ValueError as exc:
        assert "strictly increasing" in str(exc)
    else:
        raise AssertionError("non-chronological trajectory must be rejected")


def test_trajectory_memory_is_separated_by_asset_class():
    summaries = summarize_trade_trajectories(
        [
            [observation(timestamp=1), observation(timestamp=2)],
            [observation(timestamp=3, asset_class=AssetClass.CRYPTO), observation(timestamp=4, asset_class=AssetClass.CRYPTO, unrealized_return=0.20)],
        ]
    )
    assert {summary.asset_class for summary in summaries} == {AssetClass.FOREX, AssetClass.CRYPTO}
