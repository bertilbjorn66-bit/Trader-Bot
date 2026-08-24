from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .models import DataRequest, Instrument, MarketBar, Quote


class MarketDataProvider(Protocol):
    """Provider-independent contract used by the rest of the application."""

    def instruments(self) -> Sequence[Instrument]: ...

    def historical_bars(self, request: DataRequest) -> Sequence[MarketBar]: ...

    def current_quotes(self, instruments: Sequence[int]) -> Sequence[Quote]: ...

    def health_check(self) -> bool: ...


class ProviderError(RuntimeError):
    """Base error for provider failures."""


class ProviderUnavailable(ProviderError):
    """The provider could not be reached or is temporarily unavailable."""


class ProviderProtocolError(ProviderError):
    """The provider response was malformed or violated the expected contract."""


class ProviderRateLimited(ProviderError):
    """The provider requested that the client slow down."""
