#!/usr/bin/env python3
"""
Shared utilities for Sensex Trading Bot
Contains TradingHoursValidator, TelegramNotifier, and TradingStrategy classes
Generated on: 2025-09-07
"""

import pandas as pd
import numpy as np
from datetime import datetime, time
from kiteconnect import KiteConnect
import logging
import requests
import pytz
from typing import Dict, Optional, Tuple, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('sensex_trading_bot.log'),
        logging.StreamHandler()
    ]
)

class TradingHoursValidator:
    """Validates trading hours and market days"""
    def __init__(self, holidays: List[str]):
        self.holidays = [datetime.strptime(date, "%Y-%m-%d").date() for date in holidays]
        self.logger = logging.getLogger(__name__)

    def is_market_open(self) -> Tuple[bool, str]:
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        if now.weekday() > 4:
            return False, f"Market closed - Weekend ({now.strftime('%A')})"
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        if now < market_open:
            time_to_open = market_open - now
            return False, f"Market opens in {time_to_open} at 9:15 AM"
        if now > market_close:
            return False, f"Market closed at 3:30 PM (Current: {now.strftime('%H:%M')})"
        if now.date() in self.holidays:
            return False, f"Market closed - Holiday ({now.strftime('%Y-%m-%d')})"
        return True, f"Market open (Current: {now.strftime('%H:%M')})"

    def get_time_to_market_close(self) -> int:
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        is_open, _ = self.is_market_open()
        if not is_open:
            return -1
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        time_diff = market_close - now
        return int(time_diff.total_seconds() / 60)

class TelegramNotifier:
    """Handles Telegram notifications"""
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.logger = logging.getLogger(__name__)

    def send_message(self, message: str, parse_mode: str = "HTML"):
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {'chat_id': self.chat_id, 'text': message, 'parse_mode': parse_mode}
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                self.logger.info("Telegram message sent successfully")
            else:
                self.logger.error(f"Failed to send Telegram message: {response.text}")
        except Exception as e:
            self.logger.error(f"Error sending Telegram message: {e}")

class TradingStrategy:
    """Implements EMA-based trading strategy for Sensex and options"""
    def __init__(self, kite: KiteConnect = None):
        self.kite = kite
        self.logger = logging.getLogger(__name__)
        self.current_position = None
        self.entry_strike = None
        self.entry_price = 0.0
        self.entry_type = ""
        self.sl_price = 0.0
        self.candle_count = 0
        self.instrument_token = None
        self.entry_time = None
        self.entry_basis = None  # 'Sensex' or 'Option'

    def get_historical_data(self, instrument_token: str, from_date: str, to_date: str, interval: str = "3minute") -> pd.DataFrame:
        if not self.kite:
            self.logger.error("Kite Connect not initialized for historical data fetch")
            return pd.DataFrame()
        try:
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval=interval
            )
            df = pd.DataFrame(data)
            if not df.empty:
                df['timestamp'] = pd.to_datetime(df['date']).dt.tz_localize(pytz.timezone('Asia/Kolkata'))
                df.set_index('timestamp', inplace=True)
                df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
                df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
            return df
        except Exception as e:
            self.logger.error(f"Error fetching historical data: {e}")
            return pd.DataFrame()

    def _sanitize_debug_string(self, debug_str: str) -> str:
        """Sanitize debug string for Telegram HTML compatibility"""
        return (debug_str.replace('=', ':')
                .replace('<', ' less than ')
                .replace('>', ' greater than ')
                .replace('|', '')
                .replace('less than equals', 'less than or equals'))

    def check_entry_conditions(self, ce_df: pd.DataFrame, pe_df: pd.DataFrame, sensex_df: pd.DataFrame = None, debug: bool = False, debug_option_only: bool = False) -> Dict:
        debug_info = {
            'timestamp': (ce_df.iloc[-1].name.strftime('%Y-%m-%d %H:%M:%S') if not ce_df.empty else
                          pe_df.iloc[-1].name.strftime('%Y-%m-%d %H:%M:%S') if not pe_df.empty else
                          sensex_df.iloc[-1].name.strftime('%Y-%m-%d %H:%M:%S') if sensex_df is not None and not sensex_df.empty else
                          'N/A'),
            'ce': {'sensex': {}, 'option': {}},
            'pe': {'sensex': {}, 'option': {}}
        }

        result = {
            'ce_signal': False,
            'ce_basis': None,
            'ce_entry_price': 0.0,
            'ce_sl_price': 0.0,
            'pe_signal': False,
            'pe_basis': None,
            'pe_entry_price': 0.0,
            'pe_sl_price': 0.0,
            'condition_details': {},
            'debug': debug_info if debug else None
        }

        if debug_option_only:
            if (ce_df.empty and pe_df.empty) or (len(ce_df) < 20 and len(pe_df) < 20):
                result['debug'] = 'Insufficient option data' if debug else None
                self.logger.info("check_entry_conditions: Insufficient option data")
                return result
        elif sensex_df is not None and not sensex_df.empty and len(sensex_df) >= 20:
            if (ce_df.empty or len(ce_df) < 20) and (pe_df.empty or len(pe_df) < 20):
                result['debug'] = 'Insufficient option data for Sensex-based entry' if debug else None
                self.logger.info("check_entry_conditions: Insufficient option data for Sensex-based entry")
                return result
        else:
            result['debug'] = 'Insufficient Sensex data' if debug else None
            self.logger.info(f"check_entry_conditions: Insufficient Sensex data, len(sensex_df)={len(sensex_df) if sensex_df is not None else 0}")
            return result

        sensex_current = sensex_df.iloc[-1] if sensex_df is not None and not sensex_df.empty else None

        if not debug_option_only and sensex_current is not None:
            ce_sensex_conditions = [
                sensex_current['close'] > sensex_current['open'],
                sensex_current['ema10'] > sensex_current['ema20'],
                abs(sensex_current['ema10'] - sensex_current['ema20']) <= 51,
                min(abs(sensex_current['open'] - sensex_current['ema10']),
                    abs(sensex_current['low'] - sensex_current['ema10'])) < 21
            ]
            self.logger.info(f"CE Sensex Conditions: Green={ce_sensex_conditions[0]}, EMA10>EMA20={ce_sensex_conditions[1]}, |EMA10-EMA20|<=51={ce_sensex_conditions[2]}, Min(Open/Low-EMA10)<21={ce_sensex_conditions[3]}")
            self.logger.info(f"CE Sensex Values: close={sensex_current['close']:.2f}, open={sensex_current['open']:.2f}, ema10={sensex_current['ema10']:.2f}, ema20={sensex_current['ema20']:.2f}, |open-ema10|={abs(sensex_current['open'] - sensex_current['ema10']):.2f}, |low-ema10|={abs(sensex_current['low'] - sensex_current['ema10']):.2f}")
            debug_info['ce']['sensex'] = {
                'green': self._sanitize_debug_string(f"{'✅' if ce_sensex_conditions[0] else '❌'} Green: Close {sensex_current['close']:.2f} greater than Open {sensex_current['open']:.2f}"),
                'ema': self._sanitize_debug_string(f"{'✅' if ce_sensex_conditions[1] else '❌'} EMA10 {sensex_current['ema10']:.2f} greater than EMA20 {sensex_current['ema20']:.2f}"),
                'ema_diff': self._sanitize_debug_string(f"{'✅' if ce_sensex_conditions[2] else '❌'} EMA10-EMA20 {abs(sensex_current['ema10'] - sensex_current['ema20']):.2f} less than or equals 51"),
                'open_low_ema10': self._sanitize_debug_string(f"{'✅' if ce_sensex_conditions[3] else '❌'} Min(Open/Low-EMA10) {min(abs(sensex_current['open'] - sensex_current['ema10']), abs(sensex_current['low'] - sensex_current['ema10'])):.2f} less than 21")
            }
            result['condition_details'] = {
                'Green Candle': {
                    'pass': ce_sensex_conditions[0],
                    'value': f"close:{sensex_current['close']:.2f}, open:{sensex_current['open']:.2f}"
                },
                'EMA10 > EMA20': {
                    'pass': ce_sensex_conditions[1],
                    'value': f"ema10:{sensex_current['ema10']:.2f}, ema20:{sensex_current['ema20']:.2f}"
                },
                '|EMA10 - EMA20| <= 51': {
                    'pass': ce_sensex_conditions[2],
                    'value': f"|ema10-ema20|:{abs(sensex_current['ema10'] - sensex_current['ema20']):.2f}"
                },
                'min(|open - EMA10|, |low - EMA10|) < 21': {
                    'pass': ce_sensex_conditions[3],
                    'value': f"min(|open-ema10|:{abs(sensex_current['open'] - sensex_current['ema10']):.2f}, |low-ema10|:{abs(sensex_current['low'] - sensex_current['ema10']):.2f}):{min(abs(sensex_current['open'] - sensex_current['ema10']), abs(sensex_current['low'] - sensex_current['ema10'])):.2f}"
                }
            }
            result['ce_signal'] = all(ce_sensex_conditions)
            result['ce_basis'] = 'Sensex' if result['ce_signal'] else None
            result['ce_entry_price'] = sensex_current['close'] if result['ce_signal'] else 0.0
            result['ce_sl_price'] = sensex_current['ema20'] if result['ce_signal'] else 0.0

        self.logger.info(f"check_entry_conditions result: ce_signal={result['ce_signal']}, ce_basis={result['ce_basis']}, pe_signal={result['pe_signal']}, pe_basis={result['pe_basis']}")
        return result

    def check_exit_conditions(self, ce_df: pd.DataFrame, pe_df: pd.DataFrame, sensex_df: pd.DataFrame = None, debug: bool = False, debug_option_only: bool = False) -> Dict:
        if not self.current_position or (ce_df.empty and pe_df.empty):
            return {'exit': False, 'reason': 'No position', 'exit_price': 0.0, 'pnl': 0.0, 'debug': None}

        current = ce_df.iloc[-1] if self.current_position == 'CE' and not ce_df.empty else pe_df.iloc[-1] if not pe_df.empty else None
        sensex_current = sensex_df.iloc[-1] if sensex_df is not None and not sensex_df.empty else None

        if current is None:
            return {'exit': False, 'reason': 'No valid data', 'exit_price': 0.0, 'pnl': 0.0, 'debug': None}

        debug_info = {
            'timestamp': current.name.strftime('%Y-%m-%d %H:%M:%S'),
            'current_price': current['close'],
            'entry_price': self.entry_price,
            'sl_price': self.sl_price,
            'candle_count': self.candle_count
        }

        if self.current_position == 'CE':
            if debug_option_only or sensex_current is None or self.entry_basis == 'Option':
                conditions = [
                    (abs(current['close'] - current['ema20']) > 150, 'Close-EMA20 > 150'),
                    (current['close'] < current['open'] and current['close'] < current['ema10'], 'Red below 10 EMA'),
                    (self.candle_count >= 10, 'Max 10 candles (30 min)')
                ]
            else:
                conditions = [
                    (current['close'] < current['open'] and current['close'] < sensex_current['ema20'], 'Red below 20 EMA'),
                    (abs(current['close'] - sensex_current['ema20']) > 150, 'Close-EMA20 > 150'),
                    (current['ema10'] < current['ema20'], '10 EMA < 20 EMA'),
                    (self.candle_count >= 20, 'Max 20 candles (1 hr)')
                ]
        else:  # PE
            if debug_option_only or sensex_current is None or self.entry_basis == 'Option':
                conditions = [
                    (current['close'] < current['open'] and current['close'] < current['ema10'], 'Red below 10 EMA'),
                    (abs(current['close'] - current['ema20']) > 150, 'Close-EMA20 > 150'),
                    (self.candle_count >= 10, 'Max 10 candles (30 min)')
                ]
            else:
                conditions = [
                    (current['close'] > current['open'] and current['close'] > sensex_current['ema20'], 'Green above 20 EMA'),
                    (abs(current['close'] - sensex_current['ema20']) > 150, 'Close-EMA20 > 150'),
                    (current['ema10'] > current['ema20'], '10 EMA > 20 EMA'),
                    (self.candle_count >= 10, 'Max 10 candles (30 min)')
                ]

        exit_needed = False
        exit_reason = ""
        for condition, reason in conditions:
            debug_info[reason] = self._sanitize_debug_string(f"{'🔴' if condition else '✅'} {reason}: {condition}")
            if condition:
                exit_needed = True
                exit_reason = reason
                break

        return {
            'exit': exit_needed,
            'reason': exit_reason,
            'exit_price': current['close'] if exit_needed else 0.0,
            'pnl': (current['close'] - self.entry_price) if exit_needed else 0.0,
            'debug': debug_info if debug else None
        }
