from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .decision import Action


class ExecutionStatus(StrEnum):
    DISABLED = "DISABLED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class ExecutionDisabled(RuntimeError):
    """Raised whenever an order path is requested before the live gate is opened."""


@dataclass(frozen=True)
class OrderIntent:
    instrument: int
    action: Action
    quantity: float
    stop_distance: float
    target_distance: float


class ExecutionGateway:
    """Deliberately non-operational execution boundary.

    A future broker adapter must be added behind this boundary and must still pass
    the independent safety authorization gate before any order is transmitted.
    """

    status = ExecutionStatus.DISABLED

    def submit(self, intent: OrderIntent) -> None:
        raise ExecutionDisabled("Live execution is disabled until research and safety gates are passed")
