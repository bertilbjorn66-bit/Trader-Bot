"""External market-data provider adapters."""

from .binance import BinanceProvider
from .dukascopy import DukascopyProvider
from .stooq import StooqProvider

__all__ = ["BinanceProvider", "DukascopyProvider", "StooqProvider"]
