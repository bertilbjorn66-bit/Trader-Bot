import pytest

from trader_bot.decision import Action
from trader_bot.execution import ExecutionDisabled, ExecutionGateway, OrderIntent


def test_execution_gateway_is_hard_disabled():
    gateway = ExecutionGateway()
    with pytest.raises(ExecutionDisabled):
        gateway.submit(OrderIntent(1, Action.BUY, 1.0, 0.001, 0.002))
