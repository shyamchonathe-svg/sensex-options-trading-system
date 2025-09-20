#!/usr/bin/env python3
"""
Sensex Trading Bot - Live/Test Mode
EMA-based strategy with ATM ±500 strikes, runs steps 1-3 in a 3-minute cycle
Generated on: 2025-09-07
"""

import pandas as pd
from datetime import datetime, time, timedelta
from kiteconnect import KiteConnect
import logging
import json
import schedule
import time as time_module
import pytz
from typing import Dict, Optional
import sys
import argparse
import os
from optimized_sensex_option_chain import OptimizedSensexOptionChain
from utils import TradingHoursValidator, TelegramNotifier, TradingStrategy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('sensex_trading_bot_live.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

class SensexTradingBot:
    """Main trading bot class for live/test mode"""
    def __init__(self, config_file: str = "config.json", expiry_date: str = None):
        self.logger = logging.getLogger(__name__)
        self.load_config(config_file)
        self.kite = None
        self.telegram = TelegramNotifier(self.config['telegram_token'], self.config['chat_id'])
        self.option_chain = None
        self.trading_hours = None
        self.strategy = None
        self.is_running = False
        self.expiry_date = expiry_date
        self.entry_sensex_price = None

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

    def initialize_kite(self, access_token: str):
        try:
            self.kite = KiteConnect(api_key=self.config['api_key'])
            self.kite.set_access_token(access_token)
            profile = self.kite.profile()
            self.logger.info(f"Kite Connect initialized for user: {profile['user_name']}")
            self.option_chain = OptimizedSensexOptionChain(self.kite, expiry_date=self.expiry_date)
            self.trading_hours = TradingHoursValidator(self.config.get('market_holidays', []))
            self.strategy = TradingStrategy(self.kite)
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize Kite Connect: {e}", exc_info=True)
            return False

    def get_previous_trading_day(self, target_date: str) -> str:
        try:
            target = datetime.strptime(target_date, "%Y-%m-%d").date()
            holidays = [datetime.strptime(h, "%Y-%m-%d").date() for h in self.config['market_holidays']]
            prev_day = target - timedelta(days=1)
            while prev_day.weekday() >= 5 or prev_day in holidays:
                prev_day -= timedelta(days=1)
            prev_day_str = prev_day.strftime("%Y-%m-%d")
            self.logger.info(f"Previous trading day for {target_date}: {prev_day_str}")
            return prev_day_str
        except Exception as e:
            self.logger.error(f"Error finding previous trading day: {e}", exc_info=True)
            return None

    def construct_option_symbol(self, expiry_date: str, strike: int, option_type: str) -> str:
        try:
            expiry = datetime.strptime(expiry_date, "%Y-%m-%d")
            expiry_str = f"{expiry.strftime('%y')}{expiry.month}{expiry.day:02d}"
            symbol = f"SENSEX{expiry_str}{strike}{option_type}"
            self.logger.info(f"Constructed option symbol: {symbol} for expiry {expiry_date}, strike {strike}, type {option_type}")
            return symbol
        except Exception as e:
            self.logger.error(f"Error constructing option symbol: {e}")
            return None

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

    def save_historical_data(self, df: pd.DataFrame, filename: str):
        try:
            if df.empty:
                self.logger.warning(f"No data to save for {filename}")
                return
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            df.to_csv(filename, index=True, index_label='timestamp')
            self.logger.info(f"Saved historical data to {filename}: {len(df)} rows")
        except Exception as e:
            self.logger.error(f"Error saving historical data to {filename}: {e}", exc_info=True)

    def initialize_market_data(self, data_dir: str = "option_data"):
        try:
            is_open, reason = self.trading_hours.is_market_open()
            if not is_open:
                self.logger.warning(f"Cannot initialize market data: {reason}")
                return False
            today = datetime.now().strftime("%Y-%m-%d")
            prev_day = self.get_previous_trading_day(today)
            if not prev_day:
                self.logger.error("Failed to determine previous trading day")
                return False

            # Fetch Sensex data
            sensex_token = self.get_instrument_token("BSE:SENSEX")
            if not sensex_token:
                self.logger.error("Failed to fetch Sensex instrument token")
                return False
            sensex_df_today = self.kite.historical_data(
                instrument_token=sensex_token,
                from_date=today,
                to_date=today,
                interval="3minute"
            )
            sensex_df_prev = self.kite.historical_data(
                instrument_token=sensex_token,
                from_date=prev_day,
                to_date=prev_day,
                interval="3minute"
            )
            sensex_df_today = pd.DataFrame(sensex_df_today)
            sensex_df_prev = pd.DataFrame(sensex_df_prev)
            for df in [sensex_df_today, sensex_df_prev]:
                if not df.empty:
                    df['timestamp'] = pd.to_datetime(df['date']).dt.tz_localize('Asia/Kolkata')
                    df.drop(columns=['date'], inplace=True)
            self.save_historical_data(sensex_df_today, os.path.join(data_dir, f"SENSEX_{today}.csv"))
            self.save_historical_data(sensex_df_prev, os.path.join(data_dir, f"SENSEX_{prev_day}.csv"))

            # Fetch option data for ATM ±500 strikes
            sensex_price = self.option_chain.get_sensex_spot_price()
            if not sensex_price:
                self.logger.error("Failed to fetch Sensex spot price")
                return False
            atm_strike = int(sensex_price // 100) * 100
            strikes = list(range(atm_strike - 500, atm_strike + 600, 100))
            for strike in strikes:
                symbols = self.option_chain.get_weekly_expiry_symbols(strike)
                if not symbols or 'error' in symbols:
                    self.logger.warning(f"No weekly options found for strike {strike}")
                    continue
                for opt_type, sym_key in [('CE', 'ce_symbol'), ('PE', 'pe_symbol')]:
                    symbol = symbols[sym_key]
                    token = self.get_instrument_token(symbol)
                    if not token:
                        self.logger.warning(f"Failed to fetch token for {symbol}")
                        continue
                    for date in [today, prev_day]:
                        opt_df = self.kite.historical_data(
                            instrument_token=token,
                            from_date=date,
                            to_date=date,
                            interval="3minute"
                        )
                        opt_df = pd.DataFrame(opt_df)
                        if not opt_df.empty:
                            opt_df['timestamp'] = pd.to_datetime(opt_df['date']).dt.tz_localize('Asia/Kolkata')
                            opt_df.drop(columns=['date'], inplace=True)
                            filename = os.path.join(data_dir, f"{symbol}_{date}.csv")
                            self.save_historical_data(opt_df, filename)
            self.logger.info("Market data initialization completed")
            message = (
                f"📂 <b>Market Data Initialized</b>\n\n"
                f"📅 <b>Date:</b> {today}\n"
                f"📈 <b>Sensex Data:</b> Saved for {today} and {prev_day}\n"
                f"🎯 <b>Option Strikes:</b> {', '.join(map(str, strikes))}\n"
                f"⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"
            )
            self.telegram.send_message(message)
            return True
        except Exception as e:
            self.logger.error(f"Error initializing market data: {e}", exc_info=True)
            self.telegram.send_message(f"❌ <b>Market Data Init Error:</b> {str(e)}")
            return False

    def load_sensex_data_with_previous_day(self, target_date: str, data_dir: str) -> pd.DataFrame:
        try:
            sensex_file = os.path.join(data_dir, f"SENSEX_{target_date}.csv")
            self.logger.info(f"Loading Sensex data from: {sensex_file}")
            if not os.path.exists(sensex_file):
                self.logger.error(f"Sensex data file not found: {sensex_file}")
                return pd.DataFrame()
            sensex_df = pd.read_csv(sensex_file, parse_dates=['timestamp'], usecols=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            sensex_df['timestamp'] = pd.to_datetime(sensex_df['timestamp'], errors='coerce')
            sensex_df['timestamp'] = sensex_df['timestamp'].apply(
                lambda x: x.replace(tzinfo=pytz.timezone('Asia/Kolkata')) if x.tzinfo is None else x.tz_convert('Asia/Kolkata')
            )
            if sensex_df['timestamp'].isna().any():
                self.logger.error(f"Invalid timestamps in {sensex_file}")
                return pd.DataFrame()
            expected_rows = (6 * 60 + 15) // 3
            if len(sensex_df) < expected_rows - 10 or len(sensex_df) > expected_rows + 10:
                self.logger.warning(f"Unexpected row count in {sensex_file}: {len(sensex_df)} rows, expected ~{expected_rows}")
            else:
                self.logger.info(f"Confirmed {len(sensex_df)} rows in {sensex_file}, expected ~{expected_rows} (3-minute data)")
            prev_day = self.get_previous_trading_day(target_date)
            if prev_day:
                prev_file = os.path.join(data_dir, f"SENSEX_{prev_day}.csv")
                self.logger.info(f"Loading previous trading day data from: {prev_file}")
                if os.path.exists(prev_file):
                    prev_df = pd.read_csv(prev_file, parse_dates=['timestamp'], usecols=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    prev_df['timestamp'] = pd.to_datetime(prev_df['timestamp'], errors='coerce')
                    prev_df['timestamp'] = prev_df['timestamp'].apply(
                        lambda x: x.replace(tzinfo=pytz.timezone('Asia/Kolkata')) if x.tzinfo is None else x.tz_convert('Asia/Kolkata')
                    )
                    if prev_df['timestamp'].isna().any():
                        self.logger.error(f"Invalid timestamps in {prev_file}")
                        return pd.DataFrame()
                    sensex_df = pd.concat([prev_df, sensex_df], ignore_index=True)
                    sensex_df = sensex_df.drop_duplicates(subset='timestamp', keep='last')
                    sensex_df['timestamp'] = pd.to_datetime(sensex_df['timestamp'], errors='coerce').dt.tz_convert('Asia/Kolkata')
            sensex_df.set_index('timestamp', inplace=True)
            sensex_df = sensex_df.sort_index()
            sensex_df['ema10'] = sensex_df['close'].ewm(span=10, adjust=False).mean()
            sensex_df['ema20'] = sensex_df['close'].ewm(span=20, adjust=False).mean()
            self.logger.info(f"Loaded Sensex data: {len(sensex_df)} rows, from {sensex_df.index[0]} to {sensex_df.index[-1]}")
            return sensex_df
        except Exception as e:
            self.logger.error(f"Error loading Sensex data: {e}", exc_info=True)
            return pd.DataFrame()

    def load_option_data_with_previous_day(self, option_symbol: str, target_date: str, data_dir: str) -> pd.DataFrame:
        try:
            option_file = os.path.join(data_dir, f"{option_symbol}_{target_date}.csv")
            self.logger.info(f"Loading option data from: {option_file}")
            if not os.path.exists(option_file):
                self.logger.error(f"Option data file not found: {option_file}")
                return pd.DataFrame()
            option_df = pd.read_csv(option_file, parse_dates=['timestamp'], usecols=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            option_df['timestamp'] = pd.to_datetime(option_df['timestamp'], errors='coerce')
            option_df['timestamp'] = option_df['timestamp'].apply(
                lambda x: x.replace(tzinfo=pytz.timezone('Asia/Kolkata')) if x.tzinfo is None else x.tz_convert('Asia/Kolkata')
            )
            if option_df['timestamp'].isna().any():
                self.logger.error(f"Invalid timestamps in {option_file}")
                return pd.DataFrame()
            expected_rows = (6 * 60 + 15) // 3
            if len(option_df) < expected_rows - 10 or len(option_df) > expected_rows + 10:
                self.logger.warning(f"Unexpected row count in {option_file}: {len(option_df)} rows, expected ~{expected_rows}")
            prev_day = self.get_previous_trading_day(target_date)
            if prev_day:
                prev_file = os.path.join(data_dir, f"{option_symbol}_{prev_day}.csv")
                self.logger.info(f"Loading previous trading day option data from: {prev_file}")
                if os.path.exists(prev_file):
                    prev_df = pd.read_csv(prev_file, parse_dates=['timestamp'], usecols=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    prev_df['timestamp'] = pd.to_datetime(prev_df['timestamp'], errors='coerce')
                    prev_df['timestamp'] = prev_df['timestamp'].apply(
                        lambda x: x.replace(tzinfo=pytz.timezone('Asia/Kolkata')) if x.tzinfo is None else x.tz_convert('Asia/Kolkata')
                    )
                    if prev_df['timestamp'].isna().any():
                        self.logger.error(f"Invalid timestamps in {prev_file}")
                        return pd.DataFrame()
                    option_df = pd.concat([prev_df, option_df], ignore_index=True)
                    option_df = option_df.drop_duplicates(subset='timestamp', keep='last')
                    option_df['timestamp'] = pd.to_datetime(option_df['timestamp'], errors='coerce').dt.tz_convert('Asia/Kolkata')
            option_df.set_index('timestamp', inplace=True)
            option_df = option_df.sort_index()
            option_df['ema10'] = option_df['close'].ewm(span=10, adjust=False).mean()
            option_df['ema20'] = option_df['close'].ewm(span=20, adjust=False).mean()
            self.logger.info(f"Loaded option data: {len(option_df)} rows, from {option_df.index[0]} to {option_df.index[-1]}")
            return option_df
        except Exception as e:
            self.logger.error(f"Error loading option data: {e}", exc_info=True)
            return pd.DataFrame()

    def append_latest_data(self, symbol: str, token: str, date: str, data_dir: str):
        try:
            now = datetime.now(pytz.timezone('Asia/Kolkata'))
            last_3min = now - timedelta(minutes=3)
            data = self.kite.historical_data(
                instrument_token=token,
                from_date=date,
                to_date=date,
                interval="3minute"
            )
            if not data:
                self.logger.warning(f"No new data for {symbol}")
                return
            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['date']).dt.tz_localize('Asia/Kolkata')
            df.drop(columns=['date'], inplace=True)
            filename = os.path.join(data_dir, f"{symbol}_{date}.csv")
            if os.path.exists(filename):
                existing_df = pd.read_csv(filename, parse_dates=['timestamp'])
                existing_df['timestamp'] = pd.to_datetime(existing_df['timestamp']).dt.tz_localize('Asia/Kolkata')
                df = pd.concat([existing_df, df], ignore_index=True)
                df = df.drop_duplicates(subset='timestamp', keep='last')
            self.save_historical_data(df, filename)
        except Exception as e:
            self.logger.error(f"Error appending data for {symbol}: {e}", exc_info=True)

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

    def check_option_entry_conditions(self, ce_df: pd.DataFrame, pe_df: pd.DataFrame, target_date: str) -> Dict:
        """Check option-based entry conditions from debug script"""
        analysis = {
            'target_date': target_date,
            'target_time': datetime.now().strftime('%H:%M'),
            'ce_signal': False,
            'pe_signal': False,
            'ce_condition_details': {},
            'pe_condition_details': {}
        }

        for opt_type, df in [('CE', ce_df), ('PE', pe_df)]:
            if df.empty:
                continue
            df = df.drop(columns=['ema10', 'ema20'], errors='ignore')
            df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
            df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
            latest_data = df.iloc[-1]
            ema10 = df['ema10'].iloc[-1]
            ema20 = df['ema20'].iloc[-1]
            condition_details = {}
            is_green_candle = latest_data['close'] > latest_data['open']
            condition_details['Green Candle'] = {
                'pass': is_green_candle,
                'value': f"close:{latest_data['close']:.2f}, open:{latest_data['open']:.2f}"
            }
            ema10_gt_ema20 = ema10 > ema20
            condition_details['EMA10 > EMA20'] = {
                'pass': ema10_gt_ema20,
                'value': f"ema10:{ema10:.2f}, ema20:{ema20:.2f}"
            }
            ema_diff = abs(ema10 - ema20)
            ema_diff_lt_15 = ema_diff < 15
            condition_details['|EMA10 - EMA20| < 15'] = {
                'pass': ema_diff_lt_15,
                'value': f"|ema10-ema20|:{ema_diff:.2f}"
            }
            open_ema10_diff = abs(latest_data['open'] - ema10)
            low_ema10_diff = abs(latest_data['low'] - ema10)
            min_diff = min(open_ema10_diff, low_ema10_diff)
            min_diff_lt_21 = min_diff < 21
            condition_details['min(|open - EMA10|, |low - EMA10|) < 21'] = {
                'pass': min_diff_lt_21,
                'value': f"min(|open-ema10|:{open_ema10_diff:.2f}, |low-ema10|:{low_ema10_diff:.2f}):{min_diff:.2f}"
            }
            if opt_type == 'CE':
                analysis['ce_signal'] = all(condition['pass'] for condition in condition_details.values())
                analysis['ce_condition_details'] = condition_details
                analysis['ce_entry_price'] = latest_data['close'] if analysis['ce_signal'] else 0.0
                analysis['ce_sl_price'] = ema10 if analysis['ce_signal'] else 0.0
            else:
                analysis['pe_signal'] = all(condition['pass'] for condition in condition_details.values())
                analysis['pe_condition_details'] = condition_details
                analysis['pe_entry_price'] = latest_data['close'] if analysis['pe_signal'] else 0.0
                analysis['pe_sl_price'] = ema10 if analysis['pe_signal'] else 0.0
        return analysis

    def send_sensex_debug_message(self, analysis: Dict, option_symbol: str = None, option_price: float = None, exit_info: Dict = None, trade_type: str = 'long'):
        try:
            signal_type = 'CE' if trade_type == 'long' else 'PE'
            message = f"🔍 <b>Sensex Analysis ({signal_type})</b>\n\n"
            message += f"🎯 <b>Date:</b> {analysis.get('timestamp', 'N/A')}\n"
            message += f"🏷️ <b>Option Symbol:</b> <code>{option_symbol or 'N/A'}</code>\n"
            signal_key = 'ce_signal' if trade_type == 'long' else 'pe_signal'
            basis_key = 'ce_basis' if trade_type == 'long' else 'pe_basis'
            if analysis.get(signal_key):
                message += f"✅ <b>{signal_type} Signal Detected</b>\n"
                message += f"   Entry Time: {analysis.get('timestamp').split(' ')[1]}\n"
                message += f"   Basis: {analysis.get(basis_key, 'N/A')}\n"
                entry_price_str = f'₹{option_price:.2f}' if option_price is not None else 'N/A'
                message += f"   Option Price @ Entry: {entry_price_str}\n"
                if exit_info:
                    message += f"\n   🚪 <b>Exit Details</b>\n"
                    message += f"      Exit Time: {exit_info.get('timestamp', 'N/A').split(' ')[1]}\n"
                    exit_option_price = exit_info.get('exit_price')
                    exit_price_str = f'₹{exit_option_price:.2f}' if exit_option_price is not None else 'N/A'
                    message += f"      Option Price @ Exit: {exit_price_str}\n"
                    option_points = exit_info.get('pnl')
                    option_points_str = f'{option_points:.2f}' if option_points is not None else 'N/A'
                    message += f"      Option Points Captured: {option_points_str}\n"
                    message += f"      Exit Reason: {exit_info.get('reason', 'N/A')}\n"
            else:
                message += f"❌ <b>No {signal_type} Signal</b>\n"
                message += f"   Option: <code>{option_symbol or 'N/A'}</code>\n"
                if analysis.get('debug') and 'ce' in analysis['debug'] and 'sensex' in analysis['debug']['ce']:
                    message += "\n   📊 <b>Condition Details:</b>\n"
                    for key, value in analysis['debug']['ce' if trade_type == 'long' else 'pe']['sensex'].items():
                        message += f"      {value}\n"
            message += f"\n⏰ <b>Analysis Time:</b> {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S')}"
            self.telegram.send_message(message)
        except Exception as e:
            self.logger.error(f"Error sending Sensex debug message: {e}", exc_info=True)

    def send_option_debug_message(self, analysis: Dict, option_symbol: str, entry_price: float = None, exit_info: Dict = None, option_type: str = 'CE'):
        try:
            signal_type = option_type.upper()
            message = f"🔍 <b>Option Analysis ({signal_type})</b>\n\n"
            message += f"🎯 <b>Date:</b> {analysis.get('target_date', 'N/A')} {analysis.get('target_time', 'N/A')}\n"
            message += f"🏷️ <b>Option Symbol:</b> <code>{option_symbol}</code>\n"
            signal_key = f"{signal_type.lower()}_signal"
            if analysis.get(signal_key):
                message += f"✅ <b>{signal_type} Signal Detected</b>\n"
                message += f"   Entry Time: {analysis.get('target_time')}\n"
                entry_price_str = f'₹{entry_price:.2f}' if entry_price is not None else 'N/A'
                message += f"   Option Price @ Entry: {entry_price_str}\n"
                if exit_info:
                    message += f"\n🚪 <b>Exit Details</b>\n"
                    message += f"   Exit Time: {exit_info.get('timestamp', 'N/A').split(' ')[1]}\n"
                    exit_option_price = exit_info.get('exit_price')
                    exit_price_str = f'₹{exit_option_price:.2f}' if exit_option_price is not None else 'N/A'
                    message += f"   Option Price @ Exit: {exit_price_str}\n"
                    option_points = exit_info.get('pnl')
                    option_points_str = f'{option_points:.2f}' if option_points is not None else 'N/A'
                    message += f"   Option Points Captured: {option_points_str}\n"
                    message += f"   Exit Reason: {exit_info.get('reason', 'N/A')}\n"
            else:
                message += f"❌ <b>No {signal_type} Signal</b>\n"
                message += f"   Option: <code>{option_symbol}</code>\n"
                if analysis.get(f'{signal_type.lower()}_condition_details'):
                    message += "\n📊 <b>Condition Details:</b>\n"
                    for cond, details in analysis[f'{signal_type.lower()}_condition_details'].items():
                        status = "✅ Pass" if details['pass'] else "❌ Fail"
                        telegram_cond = cond.replace('=', '&lt;=').replace('<', '&lt;').replace('>', '&gt;')
                        telegram_value = details['value'].replace('=', ':').replace('<', '&lt;').replace('>', '&gt;')
                        message += f"   {telegram_cond}: {status} ({telegram_value})\n"
            message += f"\n⏰ <b>Analysis Time:</b> {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S')}"
            self.telegram.send_message(message)
        except Exception as e:
            self.logger.error(f"Error sending option debug message: {e}", exc_info=True)

    def step3_run_strategy_analysis(self, data: Dict, mode: str = 'test', data_dir: str = "option_data"):
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            sensex_token = self.get_instrument_token("BSE:SENSEX")
            if not sensex_token:
                self.telegram.send_message("❌ <b>Failed to fetch Sensex instrument token</b>")
                return
            self.append_latest_data("SENSEX", sensex_token, today, data_dir)
            sensex_df = self.load_sensex_data_with_previous_day(today, data_dir)
            if sensex_df.empty:
                self.telegram.send_message("❌ <b>Failed to load Sensex historical data</b>")
                return
            message = f"📊 <b>Step 3: 3-Minute Data for Strikes</b>\n\n"
            for symbols in data['symbols']:
                strike = symbols['strike']
                ce_symbol = symbols['ce_symbol']
                pe_symbol = symbols['pe_symbol']
                ce_token = self.get_instrument_token(ce_symbol)
                pe_token = self.get_instrument_token(pe_symbol)
                if not ce_token or not pe_token:
                    message += f"❌ <b>Failed to fetch tokens for strike {strike}</b>\n"
                    continue
                self.append_latest_data(ce_symbol, ce_token, today, data_dir)
                self.append_latest_data(pe_symbol, pe_token, today, data_dir)
                ce_df = self.load_option_data_with_previous_day(ce_symbol, today, data_dir)
                pe_df = self.load_option_data_with_previous_day(pe_symbol, today, data_dir)
                if ce_df.empty or pe_df.empty:
                    message += f"❌ <b>Failed to load historical data for strike {strike}</b>\n"
                    continue
                ce_latest = ce_df.iloc[-1] if not ce_df.empty else None
                pe_latest = pe_df.iloc[-1] if not pe_df.empty else None
                message += (
                    f"🎯 <b>Strike: {strike}</b>\n"
                    f"📈 <b>CE Data:</b>\n"
                    f"   Symbol: <code>{ce_symbol}</code>\n"
                    f"   Time: {ce_latest.name.strftime('%H:%M:%S') if ce_latest is not None else 'N/A'}\n"
                    f"   Open: ₹{ce_latest['open']:.2f}\n"
                    f"   High: ₹{ce_latest['high']:.2f}\n"
                    f"   Low: ₹{ce_latest['low']:.2f}\n"
                    f"   Close: ₹{ce_latest['close']:.2f}\n"
                    f"   EMA10: ₹{ce_latest['ema10']:.2f}\n"
                    f"   EMA20: ₹{ce_latest['ema20']:.2f}\n"
                    f"📉 <b>PE Data:</b>\n"
                    f"   Symbol: <code>{pe_symbol}</code>\n"
                    f"   Time: {pe_latest.name.strftime('%H:%M:%S') if pe_latest is not None else 'N/A'}\n"
                    f"   Open: ₹{pe_latest['open']:.2f}\n"
                    f"   High: ₹{pe_latest['high']:.2f}\n"
                    f"   Low: ₹{pe_latest['low']:.2f}\n"
                    f"   Close: ₹{pe_latest['close']:.2f}\n"
                    f"   EMA10: ₹{pe_latest['ema10']:.2f}\n"
                    f"   EMA20: ₹{pe_latest['ema20']:.2f}\n\n"
                )
                if strike == data['symbols'][len(data['symbols'])//2]['strike']:  # ATM strike
                    sensex_price = self.option_chain.get_sensex_spot_price()
                    # Sensex-based conditions
                    sensex_analysis = self.strategy.check_entry_conditions(ce_df, pe_df, sensex_df, debug=True)
                    # Option-based conditions
                    option_analysis = self.check_option_entry_conditions(ce_df, pe_df, today)
                    # Combine signals
                    ce_signal = sensex_analysis['ce_signal'] or option_analysis['ce_signal']
                    ce_basis = 'Sensex' if sensex_analysis['ce_signal'] else 'Option' if option_analysis['ce_signal'] else None
                    pe_signal = option_analysis['pe_signal']  # No sensex PE conditions in TradingStrategy, only option-based
                    pe_basis = 'Option' if option_analysis['pe_signal'] else None
                    self.send_sensex_debug_message(sensex_analysis, ce_symbol, ce_latest['close'] if ce_signal else None, None, trade_type='long')
                    self.send_sensex_debug_message(sensex_analysis, pe_symbol, pe_latest['close'] if pe_signal else None, None, trade_type='short')
                    self.send_option_debug_message(option_analysis, ce_symbol, ce_latest['close'] if option_analysis['ce_signal'] else None, None, 'CE')
                    self.send_option_debug_message(option_analysis, pe_symbol, pe_latest['close'] if option_analysis['pe_signal'] else None, 'PE')
                    if ce_signal and not pe_signal and not self.strategy.current_position:
                        self.strategy.current_position = 'CE'
                        self.strategy.entry_strike = strike
                        self.strategy.entry_price = ce_latest['close']
                        self.strategy.entry_type = 'CE'
                        self.strategy.entry_time = datetime.now(pytz.timezone('Asia/Kolkata'))
                        self.strategy.candle_count = 0
                        self.strategy.instrument_token = ce_token
                        self.strategy.entry_basis = ce_basis
                        self.strategy.sl_price = sensex_analysis['ce_sl_price'] if ce_basis == 'Sensex' else option_analysis['ce_sl_price']
                        self.entry_sensex_price = sensex_price
                        if mode == 'live':
                            self.kite.place_order(
                                variety="regular",
                                exchange="BFO",
                                tradingsymbol=ce_symbol,
                                transaction_type="BUY",
                                quantity=self.config['position_size'],
                                product="MIS",
                                order_type="MARKET"
                            )
                            self.logger.info(f"Placed CE order: {ce_symbol} at ₹{ce_latest['close']:.2f}, Basis: {ce_basis}")
                    elif pe_signal and not ce_signal and not self.strategy.current_position:
                        self.strategy.current_position = 'PE'
                        self.strategy.entry_strike = strike
                        self.strategy.entry_price = pe_latest['close']
                        self.strategy.entry_type = 'PE'
                        self.strategy.entry_time = datetime.now(pytz.timezone('Asia/Kolkata'))
                        self.strategy.candle_count = 0
                        self.strategy.instrument_token = pe_token
                        self.strategy.entry_basis = pe_basis
                        self.strategy.sl_price = option_analysis['pe_sl_price']
                        self.entry_sensex_price = sensex_price
                        if mode == 'live':
                            self.kite.place_order(
                                variety="regular",
                                exchange="BFO",
                                tradingsymbol=pe_symbol,
                                transaction_type="BUY",
                                quantity=self.config['position_size'],
                                product="MIS",
                                order_type="MARKET"
                            )
                            self.logger.info(f"Placed PE order: {pe_symbol} at ₹{pe_latest['close']:.2f}, Basis: {pe_basis}")
                    if self.strategy.current_position:
                        self.strategy.candle_count += 1
                        exit_analysis = self.strategy.check_exit_conditions(
                            ce_df if self.strategy.current_position == 'CE' else pe_df,
                            pe_df if self.strategy.current_position == 'PE' else ce_df,
                            sensex_df,
                            debug=True,
                            debug_option_only=(self.strategy.entry_basis == 'Option')
                        )
                        if exit_analysis and exit_analysis['exit']:
                            exit_symbol = ce_symbol if self.strategy.current_position == 'CE' else pe_symbol
                            if mode == 'live':
                                self.kite.place_order(
                                    variety="regular",
                                    exchange="BFO",
                                    tradingsymbol=exit_symbol,
                                    transaction_type="SELL",
                                    quantity=self.config['position_size'],
                                    product="MIS",
                                    order_type="MARKET"
                                )
                                self.logger.info(f"Placed exit order: {exit_symbol} at ₹{exit_analysis['exit_price']:.2f}, Reason: {exit_analysis['reason']}")
                            self.send_sensex_debug_message(
                                sensex_analysis,
                                exit_symbol,
                                self.strategy.entry_price,
                                exit_analysis,
                                trade_type='long' if self.strategy.current_position == 'CE' else 'short'
                            )
                            self.send_option_debug_message(
                                option_analysis,
                                exit_symbol,
                                self.strategy.entry_price,
                                exit_analysis,
                                self.strategy.current_position
                            )
                            self.strategy.current_position = None
                            self.strategy.entry_strike = None
                            self.strategy.entry_price = 0.0
                            self.strategy.entry_type = ""
                            self.strategy.entry_time = None
                            self.strategy.candle_count = 0
                            self.strategy.instrument_token = None
                            self.strategy.entry_basis = None
                            self.strategy.sl_price = 0.0
                            self.entry_sensex_price = None
            message += f"⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"
            self.telegram.send_message(message)
        except Exception as e:
            self.logger.error(f"Error in step 3: {e}", exc_info=True)
            self.telegram.send_message(f"❌ <b>Trading Cycle Error:</b> {str(e)}")

    def run_3min_cycle(self, mode: str = 'test', data_dir: str = "option_data"):
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
            self.step3_run_strategy_analysis(option_data, mode, data_dir)
        except Exception as e:
            self.logger.error(f"Error in 3-minute cycle: {e}", exc_info=True)
            self.telegram.send_message(f"❌ <b>Trading Cycle Error:</b> {str(e)}")

    def start_trading(self, mode: str = 'test', data_dir: str = "option_data"):
        if not self.kite:
            self.logger.error("Kite Connect not initialized")
            return
        is_open, reason = self.trading_hours.is_market_open()
        if not is_open:
            self.logger.warning(f"Cannot start trading: {reason}")
            message = f"⏰ <b>Trading Not Started</b>\n\n{reason}\n\nBot will start when market opens."
            self.telegram.send_message(message)
            while not self.trading_hours.is_market_open()[0]:
                now = datetime.now(pytz.timezone('Asia/Kolkata')).time()
                if now >= time(9, 15) and now <= time(9, 20):
                    self.initialize_market_data(data_dir)
                time_module.sleep(60)
        self.is_running = True
        message = (
            f"🚀 <b>Sensex Trading Bot Started</b>\n\n"
            f"📊 <b>Configuration:</b>\n"
            f"   Mode: {mode}\n"
            f"   Position Size: {self.config['position_size']} quantity\n"
            f"   Lot Size: {self.config['lot_size']}\n"
            f"   Exchange: BFO (Sensex Options)\n"
            f"   Expiry: {self.expiry_date}\n"
            f"   Analysis Frequency: Every 3 minutes\n\n"
            f"⏰ <b>Trading Hours:</b> 9:15 AM - 3:30 PM\n"
            f"🎯 <b>Strategy:</b> EMA-based Sensex and Option Logic\n\n"
            f"📱 <b>Status:</b> Monitoring market conditions...\n"
            f"🕒 <b>Market Status:</b> {self.trading_hours.is_market_open()[1]}"
        )
        self.telegram.send_message(message)
        self.initialize_market_data(data_dir)
        schedule.every(3).minutes.do(self.run_3min_cycle, mode=mode, data_dir=data_dir)
        self.run_3min_cycle(mode=mode, data_dir=data_dir)
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
    parser = argparse.ArgumentParser(description='Sensex Trading Bot - Live/Test Mode')
    parser.add_argument('--mode', choices=['test', 'live'], default='test',
                        help='Bot mode: test (simulate trades), live (execute trades)')
    parser.add_argument('--access-token', required=True, help='Kite Connect access token')
    parser.add_argument('--expiry-date', help='Weekly expiry date (YYYY-MM-DD)')
    parser.add_argument('--data-dir', default="option_data", help='Directory for pre-fetched data (default: option_data)')
    args = parser.parse_args()
    bot = SensexTradingBot(expiry_date=args.expiry_date or '2025-09-11')
    if not bot.initialize_kite(args.access_token):
        print("Failed to initialize Kite Connect. Exiting.")
        return
    try:
        if args.mode == 'test':
            print("Running test mode - Steps 1, 2, 3...")
            bot.run_3min_cycle(mode='test', data_dir=args.data_dir)
        elif args.mode == 'live':
            print("Starting live trading mode...")
            bot.start_trading(mode='live', data_dir=args.data_dir)
    except KeyboardInterrupt:
        print("\nBot stopped by user")
        bot.stop_trading()
    except Exception as e:
        print(f"Bot error: {e}")
        bot.stop_trading()

if __name__ == "__main__":
    main()
