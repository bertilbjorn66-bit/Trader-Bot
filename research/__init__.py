"""Research-only quantitative analysis package.

This package is deliberately separate from the live-trading core. It is safe to run
on synthetic data and remains data-source agnostic; empirical conclusions require
real market data and independent validation.
"""

__all__ = ["pipeline"]
