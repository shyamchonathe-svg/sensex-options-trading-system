#!/usr/bin/env python3
"""
Data models for trading bot
Contains Position, TradingSession, and PositionStatus for shared use
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from signal_detection_system import OptionType, SignalSource


class PositionStatus(Enum):
    """Position status"""
    OPEN = "open"
    CLOSED = "closed"
    PENDING = "pending"


@dataclass
class Position:
    """Trading position model"""
    symbol: str
    option_type: OptionType
    strike: int
    entry_price: float
    entry_time: datetime
    entry_basis: SignalSource
    stop_loss: float
    quantity: int
    status: PositionStatus = PositionStatus.OPEN
    exit_price: float = 0.0
    exit_time: datetime = None
    exit_reason: str = ""
    candle_count: int = 0
    pnl: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def update_candle_count(self):
        """Increment candle count"""
        self.candle_count += 1
    
    def close_position(self, exit_price: float, exit_reason: str):
        """Close the position"""
        self.exit_price = exit_price
        self.exit_time = datetime.now()
        self.exit_reason = exit_reason
        self.pnl = (exit_price - self.entry_price) * self.quantity
        self.status = PositionStatus.CLOSED


@dataclass
class TradingSession:
    """Trading session information"""
    date: str
    start_time: datetime
    sensex_entry_price: float = 0.0
    total_signals: int = 0
    positions_opened: int = 0
    positions_closed: int = 0
    total_pnl: float = 0.0
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
