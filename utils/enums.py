"""
Enums for the trading system
Defines TradingMode and AuthenticationMode to avoid circular imports
"""

from enum import Enum


class TradingMode(Enum):
    TEST = "test"
    LIVE = "live"


class AuthenticationMode(Enum):
    INTERACTIVE = "interactive"
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    TEST = "test"
