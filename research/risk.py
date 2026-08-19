from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecutionAssumptions:
    slippage: float = 0.0
    commission: float = 0.0
    max_spread: float | None = None

    def __post_init__(self) -> None:
        if self.slippage < 0 or self.commission < 0:
            raise ValueError("cost assumptions cannot be negative")
        if self.max_spread is not None and self.max_spread < 0:
            raise ValueError("max_spread cannot be negative")


def net_move(raw_move: float, spread: float, assumptions: ExecutionAssumptions) -> float:
    if spread < 0:
        raise ValueError("spread cannot be negative")
    if assumptions.max_spread is not None and spread > assumptions.max_spread:
        raise ValueError("spread exceeds execution limit")
    return raw_move - assumptions.slippage - assumptions.commission
