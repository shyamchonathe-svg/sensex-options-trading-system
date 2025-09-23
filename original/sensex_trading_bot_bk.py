#!/usr/bin/env python3
"""
Sensex Trading Bot - Custom EMA-Based Strategy with ATM ±500 Strikes Support
Uses config.json for holidays, Thursday expiries via OptimizedSensexOptionChain
Reads local CSV data for debug mode (option and Sensex data)
Generated on: 2025-09-06 10:52:00
"""

import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta, date
from kiteconnect import KiteConnect
import logging
import requests
import json
import schedule
import time as time_module
import pytz
from typing import Dict, Optional, Tuple
import sys
import argparse
import os
from optimized_sensex_option_chain import OptimizedSensexOptionChain

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('sensex_trading_bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

class TradingHoursValidator:
    """Validates trading hours and market days"""
    def __init__(self, holidays: list):
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
            'debug': debug_info if debug else None
        }

        if debug_option_only:
            if (ce_df.empty and pe_df.empty) or (len(ce_df) < 20 and len(pe_df) < 20):
                result['debug'] = 'Insufficient option data' if debug else None
                return result
        elif sensex_df is not None and not sensex_df.empty and len(sensex_df) >= 20:
            if (ce_df.empty or len(ce_df) < 20) and (pe_df.empty or len(pe_df) < 20):
                result['debug'] = 'Insufficient option data for Sensex-based entry' if debug else None
                return result
        else:
            result['debug'] = 'Insufficient Sensex data' if debug else None
            return result

        ce_current = ce_df.iloc[-1] if not ce_df.empty else None
        pe_current = pe_df.iloc[-1] if not pe_df.empty else None
        sensex_current = sensex_df.iloc[-1] if sensex_df is not None and not sensex_df.empty else None

        if not debug_option_only and sensex_current is not None:
            ce_sensex_conditions = [
                sensex_current['close'] > sensex_current['open'],
                sensex_current['ema10'] > sensex_current['ema20'],
                abs(sensex_current['close'] - sensex_current['ema10']) <= 1,
                abs(sensex_current['ema10'] - sensex_current['ema20']) <= 21,
                min(abs(sensex_current['open'] - sensex_current['ema10']),
                    abs(sensex_current['low'] - sensex_current['ema10'])) < 21
            ]
            debug_info['ce']['sensex'] = {
                'green': f"{'✅' if ce_sensex_conditions[0] else '❌'} Green: Close {sensex_current['close']:.2f} greater than Open {sensex_current['open']:.2f}",
                'ema': f"{'✅' if ce_sensex_conditions[1] else '❌'} EMA10 {sensex_current['ema10']:.2f} greater than EMA20 {sensex_current['ema20']:.2f}",
                'close_ema10': f"{'✅' if ce_sensex_conditions[2] else '❌'} Close-EMA10 {abs(sensex_current['close'] - sensex_current['ema10']):.2f} less than or equals 1",
                'ema_diff': f"{'✅' if ce_sensex_conditions[3] else '❌'} EMA10-EMA20 {abs(sensex_current['ema10'] - sensex_current['ema20']):.2f} less than or equals 21",
                'open_low_ema10': f"{'✅' if ce_sensex_conditions[4] else '❌'} Min(Open/Low-EMA10) {min(abs(sensex_current['open'] - sensex_current['ema10']), abs(sensex_current['low'] - sensex_current['ema10'])):.2f} less than 21"
            }
            result['ce_signal'] = all(ce_sensex_conditions)
            result['ce_basis'] = 'Sensex' if result['ce_signal'] else None
            result['ce_entry_price'] = ce_current['close'] if ce_current is not None and result['ce_signal'] else 0.0
            result['ce_sl_price'] = sensex_current['ema20'] if result['ce_signal'] else 0.0

        if ce_current is not None and len(ce_df) >= 20:
            ce_option_conditions = [
                ce_current['close'] > ce_current['open'],
                ce_current['ema10'] > ce_current['ema20'],
                min(ce_current['open'], ce_current['high'], ce_current['low'], ce_current['close']) > ce_current['ema10'] - 1,
                abs(ce_current['ema10'] - ce_current['ema20']) <= 11,
                min(abs(ce_current['open'] - ce_current['ema10']),
                    abs(ce_current['low'] - ce_current['ema10'])) < 11
            ]
            debug_info['ce']['option'] = {
                'green': f"{'✅' if ce_option_conditions[0] else '❌'} Green: Close {ce_current['close']:.2f} greater than Open {ce_current['open']:.2f}",
                'ema': f"{'✅' if ce_option_conditions[1] else '❌'} EMA10 {ce_current['ema10']:.2f} greater than EMA20 {ce_current['ema20']:.2f}",
                'ohlc_ema10': f"{'✅' if ce_option_conditions[2] else '❌'} Min(OHLC) {min(ce_current['open'], ce_current['high'], ce_current['low'], ce_current['close']):.2f} greater than EMA10-1 {ce_current['ema10']-1:.2f}",
                'ema_diff': f"{'✅' if ce_option_conditions[3] else '❌'} EMA10-EMA20 {abs(ce_current['ema10'] - ce_current['ema20']):.2f} less than or equals 11",
                'open_low_ema10': f"{'✅' if ce_option_conditions[4] else '❌'} Min(Open/Low-EMA10) {min(abs(ce_current['open'] - ce_current['ema10']), abs(ce_current['low'] - ce_current['ema10'])):.2f} less than 11"
            }
            if not result['ce_signal']:
                result['ce_signal'] = all(ce_option_conditions)
                result['ce_basis'] = 'Option' if result['ce_signal'] else None
                result['ce_entry_price'] = ce_current['close'] if result['ce_signal'] else 0.0
                result['ce_sl_price'] = ce_current['ema20'] if result['ce_signal'] else 0.0

        if not debug_option_only and sensex_current is not None:
            pe_sensex_conditions = [
                sensex_current['close'] < sensex_current['open'],
                sensex_current['ema10'] < sensex_current['ema20'],
                abs(sensex_current['close'] - sensex_current['ema10']) <= 1,
                abs(sensex_current['ema10'] - sensex_current['ema20']) <= 21,
                min(abs(sensex_current['open'] - sensex_current['ema10']),
                    abs(sensex_current['high'] - sensex_current['ema10'])) < 21
            ]
            debug_info['pe']['sensex'] = {
                'red': f"{'✅' if pe_sensex_conditions[0] else '❌'} Red: Close {sensex_current['close']:.2f} less than Open {sensex_current['open']:.2f}",
                'ema': f"{'✅' if pe_sensex_conditions[1] else '❌'} EMA10 {sensex_current['ema10']:.2f} less than EMA20 {sensex_current['ema20']:.2f}",
                'close_ema10': f"{'✅' if pe_sensex_conditions[2] else '❌'} Close-EMA10 {abs(sensex_current['close'] - sensex_current['ema10']):.2f} less than or equals 1",
                'ema_diff': f"{'✅' if pe_sensex_conditions[3] else '❌'} EMA10-EMA20 {abs(sensex_current['ema10'] - sensex_current['ema20']):.2f} less than or equals 21",
                'open_high_ema10': f"{'✅' if pe_sensex_conditions[4] else '❌'} Min(Open/High-EMA10) {min(abs(sensex_current['open'] - sensex_current['ema10']), abs(sensex_current['high'] - sensex_current['ema10'])):.2f} less than 21"
            }
            result['pe_signal'] = all(pe_sensex_conditions)
            result['pe_basis'] = 'Sensex' if result['pe_signal'] else None
            result['pe_entry_price'] = pe_current['close'] if pe_current is not None and result['pe_signal'] else 0.0
            result['pe_sl_price'] = sensex_current['ema20'] if result['pe_signal'] else 0.0

        if pe_current is not None and len(pe_df) >= 20:
            pe_option_conditions = [
                pe_current['close'] > pe_current['open'],
                pe_current['ema10'] > pe_current['ema20'],
                min(pe_current['open'], pe_current['high'], pe_current['low'], pe_current['close']) > pe_current['ema10'] - 1,
                abs(pe_current['ema10'] - pe_current['ema20']) <= 11,
                min(abs(pe_current['open'] - pe_current['ema10']),
                    abs(pe_current['high'] - pe_current['ema10'])) < 11
            ]
            debug_info['pe']['option'] = {
                'green': f"{'✅' if pe_option_conditions[0] else '❌'} Green: Close {pe_current['close']:.2f} greater than Open {pe_current['open']:.2f}",
                'ema': f"{'✅' if pe_option_conditions[1] else '❌'} EMA10 {pe_current['ema10']:.2f} greater than EMA20 {pe_current['ema20']:.2f}",
                'ohlc_ema10': f"{'✅' if pe_option_conditions[2] else '❌'} Min(OHLC) {min(pe_current['open'], pe_current['high'], pe_current['low'], pe_current['close']):.2f} greater than EMA10-1 {pe_current['ema10']-1:.2f}",
                'ema_diff': f"{'✅' if pe_option_conditions[3] else '❌'} EMA10-EMA20 {abs(pe_current['ema10'] - pe_current['ema20']):.2f} less than or equals 11",
                'open_high_ema10': f"{'✅' if pe_option_conditions[4] else '❌'} Min(Open/High-EMA10) {min(abs(pe_current['open'] - pe_current['ema10']), abs(pe_current['high'] - pe_current['ema10'])):.2f} less than 11"
            }
            if not result['pe_signal']:
                result['pe_signal'] = all(pe_option_conditions)
                result['pe_basis'] = 'Option' if result['pe_signal'] else None
                result['pe_entry_price'] = pe_current['close'] if result['pe_signal'] else 0.0
                result['pe_sl_price'] = pe_current['ema20'] if result['pe_signal'] else 0.0

        if debug:
            result['debug'] = debug_info
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
                    (abs(current['close'] - current['ema20']) > 155, 'Close-EMA20 > 150'),
                    (current['close'] < current['open'] and current['close'] < current['ema10'], 'Red below 10 EMA'),
                    (self.candle_count >= 10, 'Max 10 candles (30 min)')
                ]
            else:
                conditions = [
                    (current['close'] < current['open'] and current['close'] < sensex_current['ema20'], 'Red below 20 EMA'),
                    (abs(current['close'] - sensex_current['ema20']) > 155, 'Close-EMA20 > 150'),
                    (current['ema10'] < current['ema20'], '10 EMA < 20 EMA'),
                    (self.candle_count >= 20, 'Max 20 candles (1 hr)')
                ]
        else:  # PE
            if debug_option_only or sensex_current is None or self.entry_basis == 'Option':
                conditions = [
                    (current['close'] < current['open'] and current['close'] < current['ema10'], 'Red below 10 EMA'),
                    (abs(current['close'] - current['ema20']) > 155, 'Close-EMA20 > 150'),
                    (self.candle_count >= 10, 'Max 10 candles (30 min)')
                ]
            else:
                conditions = [
                    (current['close'] > current['open'] and current['close'] > sensex_current['ema20'], 'Green above 20 EMA'),
                    (abs(current['close'] - sensex_current['ema20']) > 155, 'Close-EMA20 > 150'),
                    (current['ema10'] > current['ema20'], '10 EMA > 20 EMA'),
                    (self.candle_count >= 10, 'Max 10 candles (30 min)')
                ]

        exit_needed = False
        exit_reason = ""
        for condition, reason in conditions:
            debug_info[reason] = f"{'🔴' if condition else '✅'} {reason}: {condition}"
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

class SensexTradingBot:
    """Main trading bot class"""
    def __init__(self, config_file: str = "config.json"):
        self.logger = logging.getLogger(__name__)
        self.load_config(config_file)
        self.kite = None
        self.telegram = TelegramNotifier(self.config['telegram_token'], self.config['chat_id'])
        self.option_chain = None
        self.strategy = None
        self.is_running = False

    def load_config(self, config_file: str):
        try:
            with open(config_file, 'r') as f:
                self.config = json.load(f)
        except FileNotFoundError:
            self.config = {
                "api_key": null,
                "api_secret": null,
                "telegram_token": null,
                "chat_id": null,
                "position_size": 100,
                "lot_size": 20,
                "market_holidays": [
                    "2025-10-02", "2025-10-21", "2025-10-22", "2025-11-05", "2025-12-25"
                ]
            }
            with open(config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            self.logger.info(f"Created default config file: {config_file}")

    def initialize_kite(self, access_token: str, expiry_date: str = None):
        try:
            self.kite = KiteConnect(api_key=self.config['api_key'])
            self.kite.set_access_token(access_token)
            profile = self.kite.profile()
            self.logger.info(f"Kite Connect initialized for user: {profile['user_name']}")
            self.option_chain = OptimizedSensexOptionChain(self.kite, expiry_date=expiry_date)
            self.strategy = TradingStrategy(self.kite)
            self.trading_hours = TradingHoursValidator(self.config.get('market_holidays', []))
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize Kite Connect: {e}", exc_info=True)
            return False

    def step1_detect_strike_price(self):
        try:
            is_open, reason = self.trading_hours.is_market_open()
            if not is_open:
                self.logger.warning(f"Market not open: {reason}")
                return None
            sensex_price = self.option_chain.get_sensex_spot_price()
            if sensex_price is None:
                return None
            current_time = datetime.now().time()
            if current_time < time(12, 0):
                target_strike = int(sensex_price // 100) * 100
                session = "Morning"
            else:
                target_strike = int((sensex_price - 175) // 100) * 100
                session = "Afternoon"
            self.logger.info(f"Sensex: {sensex_price}, Session: {session}, Target Strike: {target_strike}")
            message = (
                f"🎯 <b>Step 1: Strike Price Detection</b>\n\n"
                f"📊 <b>Sensex Spot:</b> {sensex_price:,.2f}\n"
                f"🎯 <b>Target Strike:</b> {target_strike}\n"
                f"⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}\n"
                f"📅 <b>Session:</b> {session}\n"
                f"🕒 <b>Market Status:</b> {reason}"
            )
            self.telegram.send_message(message)
            return target_strike
        except Exception as e:
            self.logger.error(f"Error in step 1: {e}", exc_info=True)
            return None

    def step2_get_weekly_symbols_and_prices(self, target_strike: int):
        try:
            strikes = list(range(target_strike - 500, target_strike + 600, 100))
            all_symbols = []
            all_prices = {}
            message = f"📋 <b>Step 2: Weekly Options Data</b>\n\n"
            for strike in strikes:
                symbols = self.option_chain.get_weekly_expiry_symbols(strike)
                if not symbols or 'error' in symbols:
                    message += f"❌ <b>No weekly options found for strike {strike}</b>\n"
                    continue
                prices = self.option_chain.get_option_prices(symbols)
                if 'error' in prices:
                    message += f"❌ <b>Failed to fetch option prices for strike {strike}: {prices['error']}</b>\n"
                    continue
                all_symbols.append(symbols)
                all_prices[strike] = prices
                message += (
                    f"🎯 <b>Strike:</b> {strike}\n"
                    f"📅 <b>Expiry:</b> {symbols['expiry']}\n"
                    f"🏦 <b>Exchange:</b> BFO\n"
                    f"📊 <b>Lot Size:</b> {symbols['lot_size']}\n"
                    f"📈 <b>Call Option (CE):</b>\n"
                    f"   Symbol: <code>{symbols['ce_symbol']}</code>\n"
                    f"   Price: ₹{prices['ce_price']:,.2f}\n"
                    f"📉 <b>Put Option (PE):</b>\n"
                    f"   Symbol: <code>{symbols['pe_symbol']}</code>\n"
                    f"   Price: ₹{prices['pe_price']:,.2f}\n\n"
                )
            if not all_symbols:
                self.telegram.send_message(message + "❌ <b>No valid options data found</b>")
                return None
            message += f"⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"
            self.telegram.send_message(message)
            return {'symbols': all_symbols, 'prices': all_prices}
        except Exception as e:
            self.logger.error(f"Error in step 2: {e}", exc_info=True)
            return None

    def step3_run_strategy_analysis(self, data: Dict):
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            sensex_token = self.get_instrument_token("BSE:SENSEX")
            if not sensex_token:
                message = "❌ <b>Failed to fetch Sensex instrument token</b>"
                self.telegram.send_message(message)
                return
            sensex_df = self.strategy.get_historical_data(sensex_token, yesterday, today)
            if sensex_df.empty:
                message = "❌ <b>Failed to fetch Sensex historical data</b>"
                self.telegram.send_message(message)
                return
            message = f"📊 <b>Step 3: 3-Minute Data for Strikes</b>\n\n"
            for symbols in data['symbols']:
                strike = symbols['strike']
                ce_token = self.get_instrument_token(symbols['ce_symbol'])
                pe_token = self.get_instrument_token(symbols['pe_symbol'])
                if not ce_token or not pe_token:
                    message += f"❌ <b>Failed to fetch tokens for strike {strike}</b>\n"
                    continue
                ce_df = self.strategy.get_historical_data(ce_token, yesterday, today)
                pe_df = self.strategy.get_historical_data(pe_token, yesterday, today)
                if ce_df.empty or pe_df.empty:
                    message += f"❌ <b>Failed to fetch historical data for strike {strike}</b>\n"
                    continue
                ce_latest = ce_df.iloc[-1] if not ce_df.empty else None
                pe_latest = pe_df.iloc[-1] if not pe_df.empty else None
                message += (
                    f"🎯 <b>Strike: {strike}</b>\n"
                    f"📈 <b>CE Data:</b>\n"
                    f"   Symbol: <code>{symbols['ce_symbol']}</code>\n"
                    f"   Time: {ce_latest.name.strftime('%H:%M:%S') if ce_latest is not None else 'N/A'}\n"
                    f"   Open: ₹{ce_latest['open']:.2f}\n"
                    f"   High: ₹{ce_latest['high']:.2f}\n"
                    f"   Low: ₹{ce_latest['low']:.2f}\n"
                    f"   Close: ₹{ce_latest['close']:.2f}\n"
                    f"   EMA10: ₹{ce_latest['ema10']:.2f}\n"
                    f"   EMA20: ₹{ce_latest['ema20']:.2f}\n"
                    f"📉 <b>PE Data:</b>\n"
                    f"   Symbol: <code>{symbols['pe_symbol']}</code>\n"
                    f"   Time: {pe_latest.name.strftime('%H:%M:%S') if pe_latest is not None else 'N/A'}\n"
                    f"   Open: ₹{pe_latest['open']:.2f}\n"
                    f"   High: ₹{pe_latest['high']:.2f}\n"
                    f"   Low: ₹{pe_latest['low']:.2f}\n"
                    f"   Close: ₹{pe_latest['close']:.2f}\n"
                    f"   EMA10: ₹{pe_latest['ema10']:.2f}\n"
                    f"   EMA20: ₹{pe_latest['ema20']:.2f}\n\n"
                )
                if strike == data['symbols'][len(data['symbols'])//2]['strike']:
                    analysis = self.strategy.check_entry_conditions(ce_df, pe_df, sensex_df, debug=True)
                    exit_analysis = None
                    if self.strategy.current_position:
                        exit_analysis = self.strategy.check_exit_conditions(ce_df, pe_df, sensex_df, debug=True)
                    if analysis['ce_signal'] and not analysis['pe_signal'] and not self.strategy.current_position:
                        self.strategy.current_position = 'CE'
                        self.strategy.entry_strike = symbols['strike']
                        self.strategy.entry_price = analysis['ce_entry_price']
                        self.strategy.sl_price = analysis['ce_sl_price']
                        self.strategy.entry_type = 'CE'
                        self.strategy.entry_basis = analysis['ce_basis']
                        self.strategy.candle_count = 0
                        self.strategy.instrument_token = ce_token
                        self.strategy.entry_time = datetime.now(pytz.timezone('Asia/Kolkata'))
                    elif analysis['pe_signal'] and not analysis['ce_signal'] and not self.strategy.current_position:
                        self.strategy.current_position = 'PE'
                        self.strategy.entry_strike = symbols['strike']
                        self.strategy.entry_price = analysis['pe_entry_price']
                        self.strategy.sl_price = analysis['pe_sl_price']
                        self.strategy.entry_type = 'PE'
                        self.strategy.entry_basis = analysis['pe_basis']
                        self.strategy.candle_count = 0
                        self.strategy.instrument_token = pe_token
                        self.strategy.entry_time = datetime.now(pytz.timezone('Asia/Kolkata'))
                    if self.strategy.current_position:
                        self.strategy.candle_count += 1
                    if exit_analysis and exit_analysis['exit']:
                        self.strategy.current_position = None
                        self.strategy.entry_strike = None
                        self.strategy.entry_price = 0.0
                        self.strategy.sl_price = 0.0
                        self.strategy.entry_type = ""
                        self.strategy.entry_basis = None
                        self.strategy.candle_count = 0
                        self.strategy.instrument_token = None
                        self.strategy.entry_time = None
                    self.send_strategy_analysis(analysis, exit_analysis)
            message += f"⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"
            self.telegram.send_message(message)
        except Exception as e:
            self.logger.error(f"Error in step 3: {e}", exc_info=True)
            message = f"❌ <b>Trading Cycle Error:</b> {str(e)}"
            self.telegram.send_message(message)

    def get_instrument_token(self, symbol: str) -> Optional[str]:
        try:
            exchange = "BFO" if symbol.startswith("SENSEX") else "BSE"
            instruments = self.kite.instruments(exchange)
            for inst in instruments:
                if inst['tradingsymbol'] == symbol.replace("BSE:", ""):
                    return inst['instrument_token']
            return None
        except Exception as e:
            self.logger.error(f"Error fetching instrument token for {symbol}: {e}", exc_info=True)
            return None

    def get_option_price_at_timestamp(self, symbol: str, target_date: str, target_time: str, data_dir: str = "option_data") -> Optional[float]:
        """Fetch option price from CSV at the specified timestamp."""
        try:
            option_file = os.path.join(data_dir, f"{symbol}_{target_date}.csv")
            if not os.path.exists(option_file):
                self.logger.error(f"Option data file not found: {option_file}")
                return None
            option_df = pd.read_csv(option_file, parse_dates=['timestamp'])
            option_df['timestamp'] = pd.to_datetime(option_df['timestamp'], errors='coerce').dt.tz_convert('Asia/Kolkata')
            if option_df['timestamp'].isna().any():
                self.logger.error(f"Invalid timestamps in {option_file}")
                return None
            option_df.set_index('timestamp', inplace=True)
            target_datetime = pd.to_datetime(f"{target_date} {target_time}", errors='coerce').tz_localize('Asia/Kolkata')
            if pd.isna(target_datetime):
                self.logger.error(f"Invalid datetime format: {target_date} {target_time}")
                return None
            closest_idx = option_df.index.get_indexer([target_datetime], method='nearest')[0]
            if closest_idx == -1:
                self.logger.error(f"No data found for {target_time} on {target_date} in {option_file}")
                return None
            return option_df.iloc[closest_idx]['close']
        except Exception as e:
            self.logger.error(f"Error fetching option price for {symbol}: {e}", exc_info=True)
            return None

    def load_weekly_options(self, weekly_db_file: str = "sensex_weekly_options.json") -> Dict:
        try:
            with open(weekly_db_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            self.logger.error(f"Weekly options database not found: {weekly_db_file}")
            return {}

    def send_strategy_analysis(self, analysis: Dict, exit_analysis: Dict = None):
        try:
            message = f"🔍 <b>Step 3: Strategy Analysis</b>\n\n"
            ce_signal = "🟢 ENTRY SIGNAL" if analysis['ce_signal'] else "🔴 NO SIGNAL"
            message += f"📈 <b>CE Analysis:</b> {ce_signal}"
            if analysis['ce_signal']:
                message += f" ({analysis['ce_basis']}-based)\n"
            else:
                message += "\n"
            if analysis.get('debug'):
                debug = analysis['debug']
                message += f"   Time: {debug['timestamp']}\n"
                message += f"   <b>Sensex-based:</b>\n"
                for key, value in debug['ce']['sensex'].items():
                    value = value.replace('=', ' equals ').replace('<', ' less than ').replace('>', ' greater than ').replace('|', '')
                    value = value.replace('less than equals', 'less than or equals')
                    value = value.replace('-->', '')
                    message += f"     {value}\n"
                message += f"   <b>Option-based:</b>\n"
                for key, value in debug['ce']['option'].items():
                    value = value.replace('=', ' equals ').replace('<', ' less than ').replace('>', ' greater than ').replace('|', '')
                    value = value.replace('less than equals', 'less than or equals')
                    value = value.replace('-->', '')
                    message += f"     {value}\n"
            pe_signal = "🟢 ENTRY SIGNAL" if analysis['pe_signal'] else "🔴 NO SIGNAL"
            message += f"\n📉 <b>PE Analysis:</b> {pe_signal}"
            if analysis['pe_signal']:
                message += f" ({analysis['pe_basis']}-based)\n"
            else:
                message += "\n"
            if analysis.get('debug'):
                debug = analysis['debug']
                message += f"   <b>Sensex-based:</b>\n"
                for key, value in debug['pe']['sensex'].items():
                    value = value.replace('=', ' equals ').replace('<', ' less than ').replace('>', ' greater than ').replace('|', '')
                    value = value.replace('less than equals', 'less than or equals')
                    value = value.replace('-->', '')
                    message += f"     {value}\n"
                message += f"   <b>Option-based:</b>\n"
                for key, value in debug['pe']['option'].items():
                    value = value.replace('=', ' equals ').replace('<', ' less than ').replace('>', ' greater than ').replace('|', '')
                    value = value.replace('less than equals', 'less than or equals')
                    value = value.replace('-->', '')
                    message += f"     {value}\n"
            if analysis['ce_signal'] and analysis['pe_signal']:
                message += "\n⚠️ <b>DUAL SIGNAL DETECTED - NO TRADING</b>\n"
            elif analysis['ce_signal']:
                message += f"\n✅ <b>CE ENTRY TRIGGERED</b> ({analysis['ce_basis']}-based)\n"
                message += f"   Entry Price: ₹{analysis['ce_entry_price']:.2f}\n"
                message += f"   Stop Loss: ₹{analysis['ce_sl_price']:.2f}\n"
                message += f"   Time: {datetime.now().strftime('%H:%M:%S')}\n"
            elif analysis['pe_signal']:
                message += f"\n✅ <b>PE ENTRY TRIGGERED</b> ({analysis['pe_basis']}-based)\n"
                message += f"   Entry Price: ₹{analysis['pe_entry_price']:.2f}\n"
                message += f"   Stop Loss: ₹{analysis['pe_sl_price']:.2f}\n"
                message += f"   Time: {datetime.now().strftime('%H:%M:%S')}\n"
            else:
                message += "\n⏳ <b>NO ENTRY SIGNALS - WAITING</b>\n"
            if exit_analysis:
                exit_status = "🔴 EXIT SIGNAL" if exit_analysis['exit'] else "✅ HOLD POSITION"
                message += f"\n🚪 <b>Exit Analysis:</b> {exit_status}\n"
                if exit_analysis.get('debug'):
                    debug = exit_analysis['debug']
                    message += f"   Current Price: ₹{debug['current_price']:.2f}\n"
                    message += f"   Entry Price: ₹{debug['entry_price']:.2f}\n"
                    message += f"   Stop Loss: ₹{debug['sl_price']:.2f}\n"
                    message += f"   Candle Count: {debug['candle_count']}\n"
                    for key, value in debug.items():
                        if key not in ['timestamp', 'current_price', 'entry_price', 'sl_price', 'candle_count']:
                            value = value.replace('=', ' equals ').replace('<', ' less than ').replace('>', ' greater than ').replace('|', '')
                            value = value.replace('less than equals', 'less than or equals')
                            value = value.replace('-->', '')
                            message += f"   {value}\n"
                    if exit_analysis['exit']:
                        message += f"   Reason: {exit_analysis['reason']}\n"
                        message += f"   P&L: ₹{exit_analysis['pnl']:.2f}\n"
            message += f"\n⏰ <b>Analysis Time:</b> {datetime.now().strftime('%H:%M:%S')}"
            if len(message) > 4000:
                messages = [message[i:i+4000] for i in range(0, len(message), 4000)]
                for msg in messages:
                    self.telegram.send_message(msg)
            else:
                self.telegram.send_message(message)
        except Exception as e:
            self.logger.error(f"Error sending strategy analysis: {e}", exc_info=True)

    def debug_specific_conditions(self, strike: int, option_type: str, expiry_date: str, target_date: str, target_time: str, data_dir: str = "option_data", debug_data: str = "both"):
        try:
            self.logger.info(f"Debug mode: Strike={strike}, Type={option_type}, Expiry={expiry_date}, Date={target_date}, Time={target_time}, DebugData={debug_data}")
            
            # Validate inputs for option mode
            if debug_data == "option" and (not strike or not option_type or not expiry_date):
                message = "❌ <b>Debug mode 'option' requires --strike, --option-type, and --expiry-date</b>"
                self.logger.error(message)
                self.telegram.send_message(message)
                return

            # Get option symbol
            symbol = self.option_chain.get_symbol_for_strike(expiry_date, strike, option_type) if debug_data in ["option", "both"] else None
            self.logger.info(f"Retrieved symbol: {symbol if symbol else 'N/A (Sensex mode)'}")
            
            if debug_data in ["option", "both"] and not symbol:
                message = f"❌ <b>No options found for strike {strike} {option_type} and expiry {expiry_date}</b>"
                self.logger.error(message)
                self.telegram.send_message(message)
                return
            
            # Get Sensex spot price for the target date
            spot_price = self.option_chain.get_sensex_spot_price(historical_date=target_date)
            self.logger.info(f"Sensex spot price for {target_date}: {spot_price}")
            if spot_price is None:
                self.logger.warning(f"Failed to fetch Sensex spot price for {target_date}, relying on CSV data")
            
            # Load data based on debug_data
            option_df = pd.DataFrame()
            sensex_df = pd.DataFrame()
            
            if debug_data in ["sensex", "both"]:
                sensex_file = os.path.join(data_dir, f"SENSEX_{target_date}.csv")
                self.logger.info(f"Loading Sensex data from: {sensex_file}")
                if not os.path.exists(sensex_file):
                    message = f"❌ <b>Sensex data file not found: {sensex_file}</b>"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                sensex_df = pd.read_csv(sensex_file, parse_dates=['timestamp'])
                sensex_df['timestamp'] = pd.to_datetime(sensex_df['timestamp'], errors='coerce').dt.tz_convert('Asia/Kolkata')
                if sensex_df['timestamp'].isna().any():
                    message = f"❌ <b>Invalid timestamps found in {sensex_file}</b>"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                sensex_df.set_index('timestamp', inplace=True)
                sensex_df = sensex_df.drop(columns=['ema10', 'ema20'], errors='ignore')
                sensex_df['ema10'] = sensex_df['close'].ewm(span=10, adjust=False).mean()
                sensex_df['ema20'] = sensex_df['close'].ewm(span=20, adjust=False).mean()
            
            if debug_data in ["option", "both"]:
                option_file = os.path.join(data_dir, f"{symbol}_{target_date}.csv")
                self.logger.info(f"Loading option data from: {option_file}")
                if not os.path.exists(option_file):
                    message = f"❌ <b>Data file not found for {symbol} on {target_date}</b>"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                option_df = pd.read_csv(option_file, parse_dates=['timestamp'])
                option_df['timestamp'] = pd.to_datetime(option_df['timestamp'], errors='coerce').dt.tz_convert('Asia/Kolkata')
                if option_df['timestamp'].isna().any():
                    message = f"❌ <b>Invalid timestamps found in {option_file}</b>"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                option_df.set_index('timestamp', inplace=True)
                option_df = option_df.drop(columns=['ema10', 'ema20'], errors='ignore')
                option_df['ema10'] = option_df['close'].ewm(span=10, adjust=False).mean()
                option_df['ema20'] = option_df['close'].ewm(span=20, adjust=False).mean()
            
            # Construct target datetime
            try:
                target_datetime = pd.to_datetime(f"{target_date} {target_time}", errors='coerce').tz_localize('Asia/Kolkata')
                if pd.isna(target_datetime):
                    raise ValueError("Invalid datetime format")
                self.logger.info(f"Target datetime: {target_datetime}")
            except Exception as e:
                message = f"❌ <b>Failed to parse target datetime {target_date} {target_time}: {e}</b>"
                self.logger.error(message, exc_info=True)
                self.telegram.send_message(message)
                return
            
            # Find closest timestamp
            if debug_data in ["option", "both"] and not option_df.empty:
                if option_df.index.dtype != 'datetime64[ns, Asia/Kolkata]':
                    message = f"❌ <b>Invalid index dtype in option data: {option_df.index.dtype}</b>"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                closest_idx = option_df.index.get_indexer([target_datetime], method='nearest')[0]
                if closest_idx == -1:
                    message = f"❌ <b>No option data found for time {target_time} on {target_date}</b>"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                option_df = option_df.iloc[:closest_idx+1]
            elif debug_data == "option":
                message = f"❌ <b>No option data available for {symbol} on {target_date}</b>"
                self.logger.error(message)
                self.telegram.send_message(message)
                return
            
            if debug_data in ["sensex", "both"] and not sensex_df.empty:
                if sensex_df.index.dtype != 'datetime64[ns, Asia/Kolkata]':
                    message = f"❌ <b>Invalid index dtype in Sensex data: {sensex_df.index.dtype}</b>"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                closest_idx = sensex_df.index.get_indexer([target_datetime], method='nearest')[0]
                if closest_idx == -1:
                    message = f"❌ <b>No Sensex data found for time {target_time} on {target_date}</b>"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                sensex_df = sensex_df.iloc[:closest_idx+1]
            elif debug_data == "sensex":
                message = f"❌ <b>No Sensex data available for {target_date}</b>"
                self.logger.error(message)
                self.telegram.send_message(message)
                return
            
            # Prepare DataFrames for analysis
            ce_df = option_df if option_type == 'CE' and debug_data in ["option", "both"] else pd.DataFrame()
            pe_df = option_df if option_type == 'PE' and debug_data in ["option", "both"] else pd.DataFrame()
            sensex_df = sensex_df if debug_data in ["sensex", "both"] else pd.DataFrame()
            
            # For Sensex-based entry, fetch option price for entry_price
            ce_entry_price = 0.0
            pe_entry_price = 0.0
            if debug_data in ["sensex", "both"] and symbol and sensex_df is not None and not sensex_df.empty:
                if option_type == 'CE':
                    ce_entry_price = self.get_option_price_at_timestamp(symbol, target_date, target_time, data_dir) or 0.0
                elif option_type == 'PE':
                    pe_entry_price = self.get_option_price_at_timestamp(symbol, target_date, target_time, data_dir) or 0.0
            
            # Run entry conditions analysis
            analysis = self.strategy.check_entry_conditions(
                ce_df,
                pe_df,
                sensex_df,
                debug=True,
                debug_option_only=debug_data == "option"
            )
            if debug_data == "sensex":
                analysis['ce_entry_price'] = ce_entry_price if option_type == 'CE' else 0.0
                analysis['pe_entry_price'] = pe_entry_price if option_type == 'PE' else 0.0
            entry_signal = analysis['ce_signal'] if option_type == 'CE' else analysis['pe_signal']
            entry_basis = analysis['ce_basis'] if option_type == 'CE' else analysis['pe_basis']
            entry_price = analysis['ce_entry_price'] if option_type == 'CE' else analysis['pe_entry_price']
            sl_price = analysis['ce_sl_price'] if option_type == 'CE' else analysis['pe_sl_price']
            
            # Prepare Telegram message
            message = (
                f"🐛 <b>Debug Analysis</b>\n\n"
                f"🎯 <b>Parameters:</b>\n"
                f"   Strike: {strike}\n"
                f"   Option: {option_type}\n"
                f"   Symbol: <code>{symbol if symbol else 'N/A'}</code>\n"
                f"   Expiry: {expiry_date}\n"
                f"   Exchange: BFO\n"
                f"   Date: {target_date}\n"
                f"   Time: {target_time}\n"
            )
            if spot_price:
                message += f"   Sensex Spot: ₹{spot_price:,.2f}\n"
            if debug_data in ["sensex", "both"] and not sensex_df.empty:
                message += f"   Sensex Close: ₹{sensex_df.iloc[-1]['close']:.2f}\n"
            message += f"\n🔍 <b>Condition Analysis ({debug_data.capitalize()}):</b> {'🟢 MATCH' if entry_signal else '🔴 NO MATCH'}\n"
            
            if entry_signal:
                message += (
                    f"   Basis: {entry_basis}\n"
                    f"   Entry Price: ₹{entry_price:.2f}\n"
                    f"   Stop Loss: ₹{sl_price:.2f}\n"
                )
            
            if analysis.get('debug'):
                debug = analysis['debug']
                if debug_data in ["sensex", "both"] and not sensex_df.empty:
                    message += f"\n   <b>{option_type} Sensex-based:</b>\n"
                    for key, value in debug[option_type.lower()]['sensex'].items():
                        value = value.replace('=', ' equals ').replace('<', ' less than ').replace('>', ' greater than ').replace('|', '')
                        value = value.replace('less than equals', 'less than or equals')
                        value = value.replace('-->', '')
                        message += f"     {value}\n"
                if debug_data in ["option", "both"] and not option_df.empty:
                    message += f"   <b>{option_type} Option-based:</b>\n"
                    for key, value in debug[option_type.lower()]['option'].items():
                        value = value.replace('=', ' equals ').replace('<', ' less than ').replace('>', ' greater than ').replace('|', '')
                        value = value.replace('less than equals', 'less than or equals')
                        value = value.replace('-->', '')
                        message += f"     {value}\n"
            
            # Check exit conditions (only for option or both modes, as exit requires option data)
            if entry_signal and debug_data in ["option", "both"] and not option_df.empty:
                exit_found = False
                exit_time = None
                exit_price = 0.0
                exit_reason = ""
                self.strategy.current_position = option_type
                self.strategy.entry_price = entry_price
                self.strategy.sl_price = sl_price
                self.strategy.entry_basis = entry_basis
                self.strategy.candle_count = 0
                self.strategy.instrument_token = self.get_instrument_token(symbol)
                
                for i in range(closest_idx, len(option_df)):
                    self.strategy.candle_count += 1
                    ce_df = option_df.iloc[:i+1] if option_type == 'CE' else pd.DataFrame()
                    pe_df = option_df.iloc[:i+1] if option_type == 'PE' else pd.DataFrame()
                    sensex_df_subset = sensex_df.iloc[:i+1] if debug_data == "both" and not sensex_df.empty else pd.DataFrame()
                    exit_analysis = self.strategy.check_exit_conditions(
                        ce_df,
                        pe_df,
                        sensex_df_subset,
                        debug=True,
                        debug_option_only=debug_data == "option" or sensex_df.empty
                    )
                    if exit_analysis['exit']:
                        exit_found = True
                        exit_time = option_df.index[i].strftime('%Y-%m-%d %H:%M:%S')
                        exit_price = exit_analysis['exit_price']
                        exit_reason = exit_analysis['reason']
                        message += (
                            f"\n🚪 <b>Exit Analysis:</b>\n"
                            f"   Exit Time: {exit_time}\n"
                            f"   Exit Price: ₹{exit_price:.2f}\n"
                            f"   P&L: ₹{exit_analysis['pnl']:.2f}\n"
                            f"   Reason: {exit_reason}\n"
                        )
                        if exit_analysis.get('debug'):
                            debug = exit_analysis['debug']
                            for key, value in debug.items():
                                if key not in ['timestamp', 'current_price', 'entry_price', 'sl_price', 'candle_count']:
                                    value = value.replace('=', ' equals ').replace('<', ' less than ').replace('>', ' greater than ').replace('|', '')
                                    value = value.replace('less than equals', 'less than or equals')
                                    value = value.replace('-->', '')
                                    message += f"     {value}\n"
                        break
                self.strategy.current_position = None
                self.strategy.entry_price = 0.0
                self.strategy.sl_price = 0.0
                self.strategy.entry_basis = None
                self.strategy.candle_count = 0
                self.strategy.instrument_token = None
                if not exit_found:
                    message += f"\n🚪 <b>Exit Analysis:</b> No exit signal found in data\n"
            
            self.logger.info(f"Telegram message content:\n{message}")
            self.telegram.send_message(message)
        
        except Exception as e:
            self.logger.error(f"Error in debug mode: {e}", exc_info=True)
            self.telegram.send_message(f"❌ <b>Debug Error:</b> {str(e)}")

    def run_3min_cycle(self):
        try:
            self.logger.info("Starting 3-minute trading cycle")
            is_open, reason = self.trading_hours.is_market_open()
            if not is_open:
                self.logger.info(f"Skipping cycle: {reason}")
                return
            target_strike = self.step1_detect_strike_price()
            if target_strike is None:
                return
            option_data = self.step2_get_weekly_symbols_and_prices(target_strike)
            if option_data is None:
                return
            self.step3_run_strategy_analysis(option_data)
        except Exception as e:
            self.logger.error(f"Error in 3-minute cycle: {e}", exc_info=True)
            message = f"❌ <b>Trading Cycle Error:</b> {str(e)}"
            self.telegram.send_message(message)

    def start_trading(self):
        if not self.kite:
            self.logger.error("Kite Connect not initialized")
            return
        is_open, reason = self.trading_hours.is_market_open()
        if not is_open:
            self.logger.warning(f"Cannot start trading: {reason}")
            message = f"⏰ <b>Trading Not Started</b>\n\n{reason}\n\nBot will start when market opens."
            self.telegram.send_message(message)
            while not self.trading_hours.is_market_open()[0]:
                time_module.sleep(300)
        self.is_running = True
        message = (
            f"🚀 <b>Sensex Trading Bot Started</b>\n\n"
            f"📊 <b>Configuration:</b>\n"
            f"   Position Size: {self.config['position_size']} quantity\n"
            f"   Lot Size: {self.config['lot_size']}\n"
            f"   Exchange: BFO (Sensex Options)\n"
            f"   Analysis Frequency: Every 3 minutes\n\n"
            f"⏰ <b>Trading Hours:</b> 9:15 AM - 3:30 PM\n"
            f"🎯 <b>Strategy:</b> EMA-based Sensex/Option Logic\n\n"
            f"📱 <b>Status:</b> Monitoring market conditions...\n"
            f"🕒 <b>Market Status:</b> {self.trading_hours.is_market_open()[1]}"
        )
        self.telegram.send_message(message)
        schedule.every(3).minutes.do(self.run_3min_cycle)
        self.run_3min_cycle()
        while self.is_running:
            is_open, reason = self.trading_hours.is_market_open()
            if not is_open:
                self.logger.info(f"Market closed: {reason}")
                self.stop_trading()
                break
            schedule.run_pending()
            time_module.sleep(10)

    def stop_trading(self):
        self.is_running = False
        schedule.clear()
        message = (
            f"🛑 <b>Sensex Trading Bot Stopped</b>\n\n"
            f"⏰ <b>Stop Time:</b> {datetime.now().strftime('%H:%M:%S')}\n"
            f"📊 <b>Session Summary:</b> Trading session ended\n"
            f"🕒 <b>Market Status:</b> {self.trading_hours.is_market_open()[1]}"
        )
        self.telegram.send_message(message)

def main():
    parser = argparse.ArgumentParser(description='Sensex Trading Bot - EMA-based Strategy')
    parser.add_argument('--mode', choices=['test', 'debug', 'live'], default='test',
                        help='Bot mode: test (steps 1-3), debug (specific analysis), live (automated trading)')
    parser.add_argument('--access-token', required=True, help='Kite Connect access token')
    parser.add_argument('--strike', type=int, help='Strike price for debug mode')
    parser.add_argument('--option-type', choices=['CE', 'PE'], help='Option type for debug mode')
    parser.add_argument('--expiry-date', help='Expiry date for debug mode (YYYY-MM-DD, nearest/next)')
    parser.add_argument('--date', help='Date for debug mode (YYYY-MM-DD)')
    parser.add_argument('--time', help='Time for debug mode (HH:MM, 24hr format)')
    parser.add_argument('--data-dir', default="option_data", help='Directory for pre-fetched data (default: option_data)')
    parser.add_argument('--debug-data', choices=['sensex', 'option', 'both'], default='both',
                        help='Data to debug: sensex, option, or both')
    args = parser.parse_args()
    bot = SensexTradingBot()
    if not bot.initialize_kite(args.access_token, expiry_date=args.expiry_date if args.mode == 'debug' else None):
        print("Failed to initialize Kite Connect. Exiting.")
        return
    try:
        if args.mode == 'test':
            print("Running test mode - Steps 1, 2, 3...")
            bot.run_3min_cycle()
        elif args.mode == 'debug':
            if not all([args.strike, args.option_type, args.expiry_date, args.date, args.time]):
                print("Debug mode requires: --strike, --option-type, --expiry-date, --date, --time")
                return
            print(f"Running debug mode for {args.option_type} {args.strike} on {args.date} at {args.time} for expiry {args.expiry_date} with data {args.debug_data}")
            bot.debug_specific_conditions(args.strike, args.option_type, args.expiry_date, args.date, args.time, args.data_dir, args.debug_data)
        elif args.mode == 'live':
            print("Starting live trading mode...")
            bot.start_trading()
    except KeyboardInterrupt:
        print("\nBot stopped by user")
        bot.stop_trading()
    except Exception as e:
        print(f"Bot error: {e}")
        bot.stop_trading()

if __name__ == "__main__":
    main()
