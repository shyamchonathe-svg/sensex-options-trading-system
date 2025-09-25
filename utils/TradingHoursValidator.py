#!/usr/bin/env python3
"""
Trading Hours Validator - Checks if current time is within market hours
"""
import logging
from datetime import time, datetime
import pytz

logger = logging.getLogger(__name__)

class TradingHoursValidator:
    def __init__(self, market_holidays=None):
        self.ist = pytz.timezone('Asia/Kolkata')
        self.market_open = time(9, 15)
        self.market_close = time(15, 30)
        self.market_holidays = market_holidays or []

    def is_trading_day(self):
        today = datetime.now(self.ist).date()
        return today.weekday() < 5 and today not in self.market_holidays

    def is_trading_hours(self):
        now = datetime.now(self.ist).time()
        return self.is_trading_day() and self.market_open <= now <= self.market_close
