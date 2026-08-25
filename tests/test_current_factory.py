from trader_bot.current_factory import current_factory
from trader_bot.decision import Action
from trader_bot.decision_factory import FactoryState


def test_current_factory_is_safely_blocked() -> None:
    factory = current_factory()
    decision = factory.decide(1)
    assert factory.state is FactoryState.BLOCKED
    assert decision.action is Action.NO_TRADE
    assert decision.evidence_samples == 0
