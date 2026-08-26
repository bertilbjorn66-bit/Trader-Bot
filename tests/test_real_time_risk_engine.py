from research.real_time_risk_engine import RiskAction, RiskSnapshot, RiskState, should_exit_immediately, evaluate


def snap(**kwargs):
    base = dict(now_ms=10_000, quote_ts_ms=9_900, spread_pips=0.8, spread_z=0.0,
                volatility_z=0.0, expected_edge_pips=1.0, adverse_move_pips=0.0,
                model_confidence=0.80)
    base.update(kwargs)
    return RiskSnapshot(**base)


def test_good_candidate_enters():
    assert evaluate(snap(), RiskState(1000.0, 1000.0)) is RiskAction.ENTER


def test_stale_quote_never_enters():
    assert evaluate(snap(quote_ts_ms=7_000), RiskState(1000.0, 1000.0)) is RiskAction.HALT


def test_bad_feed_exits_existing_position():
    assert evaluate(snap(feed_ok=False, position_exists=True), RiskState(1000.0, 1000.0)) is RiskAction.EXIT


def test_large_adverse_move_exits_immediately():
    state = RiskState(1000.0, 1000.0)
    s = snap(position_exists=True, adverse_move_pips=2.1)
    assert should_exit_immediately(s, state)
    assert evaluate(s, state) is RiskAction.EXIT


def test_negative_edge_exits_immediately():
    state = RiskState(1000.0, 1000.0)
    s = snap(position_exists=True, expected_edge_pips=-0.6)
    assert should_exit_immediately(s, state)
    assert evaluate(s, state) is RiskAction.EXIT


def test_spread_spike_blocks_entry():
    assert evaluate(snap(spread_pips=4.0), RiskState(1000.0, 1000.0)) is RiskAction.HOLD


def test_drawdown_halts_everything():
    state = RiskState(1000.0, 915.0)
    s = snap()
    assert evaluate(s, state) is RiskAction.HALT
    assert should_exit_immediately(snap(position_exists=True), state)


def test_loss_streak_halts():
    state = RiskState(1000.0, 1000.0, consecutive_losses=5)
    assert evaluate(snap(), state) is RiskAction.HALT
