"""Compatibility exports for research execution-cost assumptions.

Use :mod:`research.execution` as the canonical implementation. BID/ASK execution
already incorporates spread, so additional costs are limited to slippage and
commission and spread is an eligibility constraint.
"""

from .execution import ExecutionAssumptions, net_move, validate_spread

__all__ = ["ExecutionAssumptions", "net_move", "validate_spread"]
