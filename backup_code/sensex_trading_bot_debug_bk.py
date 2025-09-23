#!/usr/bin/env python3
"""
Sensex Trading Bot - Debug Mode
Analyzes historical Sensex/option data for entry and exit conditions at a specific timestamp
Generated on: 2025-09-07
"""

import pandas as pd
from datetime import datetime, timedelta
from kiteconnect import KiteConnect
import logging
import json
import pytz
from typing import Dict, Optional
import sys
import argparse
import os
import glob
from optimized_sensex_option_chain import OptimizedSensexOptionChain
from utils import TradingHoursValidator, TelegramNotifier, TradingStrategy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('sensex_trading_bot_debug.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

class SensexTradingBot:
    """Main trading bot class for debug mode"""
    def __init__(self, config_file: str = "config.json"):
        self.logger = logging.getLogger(__name__)
        self.load_config(config_file)
        self.kite = None
        self.telegram = TelegramNotifier(self.config['telegram_token'], self.config['chat_id'])
        self.option_chain = None
        self.strategy = None

    def load_config(self, config_file: str):
        try:
            with open(config_file, 'r') as f:
                self.config = json.load(f)
        except FileNotFoundError:
            self.config = {
                "api_key": "xpft4r4qmsoq0p9b",
                "api_secret": "6c96tog8pgp8wiqti9ox7b7nx4hej8g9",
                "telegram_token": "8427480734:AAFjkFwNbM9iUo0wa1Biwg8UHmJCvLs5vho",
                "chat_id": "1639045622",
                "position_size": 100,
                "lot_size": 20,
                "market_holidays": [
                    "2025-10-02", "2025-10-21", "2025-10-22", "2025-11-05", "2025-12-25"
                ]
            }
            with open(config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            self.logger.info(f"Created default config file: {config_file}")

    def get_previous_trading_day(self, target_date: str) -> str:
        """Finds the previous trading day, skipping weekends and holidays"""
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

    def initialize_kite(self, access_token: str, expiry_date: str = None):
        try:
            self.kite = KiteConnect(api_key=self.config['api_key'])
            self.kite.set_access_token(access_token)
            profile = self.kite.profile()
            self.logger.info(f"Kite Connect initialized for user: {profile['user_name']}")
            self.option_chain = OptimizedSensexOptionChain(self.kite, expiry_date=expiry_date)
            self.strategy = TradingStrategy(self.kite)
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize Kite Connect: {e}", exc_info=True)
            return False

    def get_option_price_at_timestamp(self, symbol: str, target_date: str, target_time: str, data_dir: str = "option_data") -> Optional[float]:
        try:
            if not symbol:
                self.logger.warning("No valid option symbol provided for price fetch")
                return None
            option_file = os.path.join(data_dir, f"{symbol}_{target_date}.csv")
            if not os.path.exists(option_file):
                self.logger.warning(f"Option data file not found: {option_file}")
                return None
            option_df = pd.read_csv(option_file, parse_dates=['timestamp'])
            option_df['timestamp'] = pd.to_datetime(option_df['timestamp'], errors='coerce')
            option_df['timestamp'] = option_df['timestamp'].apply(
                lambda x: x.replace(tzinfo=pytz.timezone('Asia/Kolkata')) if x.tzinfo is None else x.tz_convert('Asia/Kolkata')
            )
            if option_df['timestamp'].isna().any():
                self.logger.error(f"Invalid timestamps in {option_file}")
                return None
            option_df.set_index('timestamp', inplace=True)
            target_datetime = datetime.strptime(f"{target_date} {target_time}", "%Y-%m-%d %H:%M")
            target_datetime = pytz.timezone('Asia/Kolkata').localize(target_datetime)
            closest_idx = option_df.index.get_indexer([target_datetime], method='nearest')[0]
            if closest_idx == -1:
                self.logger.error(f"No data found for {target_time} on {target_date} in {option_file}")
                return None
            return option_df.iloc[closest_idx]['close']
        except Exception as e:
            self.logger.error(f"Error fetching option price for {symbol}: {e}", exc_info=True)
            return None

    def construct_option_symbol(self, expiry_date: str, strike: int, option_type: str) -> str:
        """Constructs a fallback option symbol in case get_symbol_for_strike fails"""
        try:
            expiry = datetime.strptime(expiry_date, "%Y-%m-%d")
            expiry_str = f"{expiry.strftime('%y')}{expiry.month}{expiry.day:02d}"  # Produces '25911'
            symbol = f"SENSEX{expiry_str}{strike}{option_type}"
            self.logger.info(f"Constructed option symbol: {symbol} for expiry {expiry_date}, strike {strike}, type {option_type}")
            return symbol
        except Exception as e:
            self.logger.error(f"Error constructing option symbol: {e}")
            return None

    def load_sensex_data_with_previous_day(self, target_date: str, data_dir: str) -> pd.DataFrame:
        """Loads 3-minute Sensex data for target date and previous trading day"""
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
            
            expected_rows = (6 * 60 + 15) // 3  # ~125 rows
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
                    
                    if len(prev_df) < expected_rows - 10 or len(prev_df) > expected_rows + 10:
                        self.logger.warning(f"Unexpected row count in {prev_file}: {len(prev_df)} rows, expected ~{expected_rows}")
                    else:
                        self.logger.info(f"Confirmed {len(prev_df)} rows in {prev_file}, expected ~{expected_rows} (3-minute data)")

                    sensex_df = pd.concat([prev_df, sensex_df], ignore_index=True)
                    sensex_df = sensex_df.drop_duplicates(subset='timestamp', keep='last')
                    sensex_df['timestamp'] = pd.to_datetime(sensex_df['timestamp'], errors='coerce').dt.tz_convert('Asia/Kolkata')
                    self.logger.info(f"Combined data: {len(prev_df)} rows from {prev_day}, {len(sensex_df)-len(prev_df)} rows from {target_date}")
                else:
                    self.logger.warning(f"Previous day data not found: {prev_file}. Using only {target_date} data")
            else:
                self.logger.warning(f"Could not determine previous trading day for {target_date}")
            
            sensex_df.set_index('timestamp', inplace=True)
            sensex_df = sensex_df.sort_index()
            self.logger.info(f"Loaded Sensex data: {len(sensex_df)} rows, from {sensex_df.index[0]} to {sensex_df.index[-1]}")
            return sensex_df
        except Exception as e:
            self.logger.error(f"Error loading Sensex data: {e}", exc_info=True)
            return pd.DataFrame()

    def load_option_data_with_previous_day(self, option_symbol: str, target_date: str, data_dir: str) -> pd.DataFrame:
        """Loads 3-minute option data for target date and previous trading day"""
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
            
            expected_rows = (6 * 60 + 15) // 3  # ~125 rows
            if len(option_df) < expected_rows - 10 or len(option_df) > expected_rows + 10:
                self.logger.warning(f"Unexpected row count in {option_file}: {len(option_df)} rows, expected ~{expected_rows}")
            else:
                self.logger.info(f"Confirmed {len(option_df)} rows in {option_file}, expected ~{expected_rows} (3-minute data)")

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
                    
                    if len(prev_df) < expected_rows - 10 or len(prev_df) > expected_rows + 10:
                        self.logger.warning(f"Unexpected row count in {prev_file}: {len(prev_df)} rows, expected ~{expected_rows}")
                    else:
                        self.logger.info(f"Confirmed {len(prev_df)} rows in {prev_file}, expected ~{expected_rows} (3-minute data)")

                    option_df = pd.concat([prev_df, option_df], ignore_index=True)
                    option_df = option_df.drop_duplicates(subset='timestamp', keep='last')
                    option_df['timestamp'] = pd.to_datetime(option_df['timestamp'], errors='coerce').dt.tz_convert('Asia/Kolkata')
                    self.logger.info(f"Combined option data: {len(prev_df)} rows from {prev_day}, {len(option_df)-len(prev_df)} rows from {target_date}")
                else:
                    self.logger.warning(f"Previous day option data not found: {prev_file}. Using only {target_date} data")
            else:
                self.logger.warning(f"Could not determine previous trading day for {target_date}")
            
            option_df.set_index('timestamp', inplace=True)
            option_df = option_df.sort_index()
            self.logger.info(f"Loaded option data: {len(option_df)} rows, from {option_df.index[0]} to {option_df.index[-1]}")
            return option_df
        except Exception as e:
            self.logger.error(f"Error loading option data: {e}", exc_info=True)
            return pd.DataFrame()

    def send_sensex_debug_message(self, analysis: Dict, option_symbol: str = None, option_price: float = None, exit_info: Dict = None, trade_type: str = 'long'):
        """Sends a Telegram message for Sensex debug mode with CE or PE signal details"""
        try:
            signal_type = 'CE' if trade_type == 'long' else 'PE'
            signal_key = 'ce_signal' if trade_type == 'long' else 'pe_signal'
            condition_details_key = 'ce_condition_details' if trade_type == 'long' else 'pe_condition_details'
            
            message = f"🔍 <b>Sensex Debug Analysis ({signal_type})</b>\n\n"
            message += f"🎯 <b>Date:</b> {analysis.get('target_date', 'N/A')} {analysis.get('target_time', 'N/A')}\n"
            message += f"📈 <b>Sensex Spot Price:</b> ₹{analysis.get('spot_price', 'N/A'):,.2f}\n"
            message += f"🏷️ <b>Option Symbol:</b> <code>{option_symbol or 'N/A'}</code>\n"
            
            if analysis.get(signal_key):
                message += f"✅ <b>{signal_type} Signal Detected</b>\n"
                message += f"   Entry Time: {analysis.get('target_time')}\n"
                entry_price_str = f'₹{option_price:.2f}' if option_price is not None else 'N/A'
                message += f"   Option Price @ Entry: {entry_price_str}\n"
                sensex_close = analysis.get('sensex_close', 'N/A')
                sensex_entry_str = f'₹{sensex_close:,.2f}' if sensex_close != 'N/A' else 'N/A'
                message += f"   Sensex @ Entry: {sensex_entry_str}\n"
                if exit_info:
                    message += f"\n   🚪 <b>Exit Details</b>\n"
                    message += f"      Exit Time: {exit_info.get('exit_time', 'N/A')}\n"
                    sensex_exit = exit_info.get('sensex_close', 'N/A')
                    sensex_exit_str = f'₹{sensex_exit:,.2f}' if sensex_exit != 'N/A' else 'N/A'
                    message += f"      Sensex @ Exit: {sensex_exit_str}\n"
                    exit_option_price = exit_info.get('option_price')
                    exit_price_str = f'₹{exit_option_price:.2f}' if exit_option_price is not None else 'N/A'
                    message += f"      Option Price @ Exit: {exit_price_str}\n"
                    sensex_points = exit_info.get('sensex_points')
                    sensex_points_str = f'{sensex_points:.2f}' if sensex_points is not None else 'N/A'
                    message += f"      Sensex Points Captured: {sensex_points_str}\n"
                    option_points = exit_info.get('option_points')
                    option_points_str = f'{option_points:.2f}' if option_points is not None else 'N/A'
                    message += f"      Option Points Captured: {option_points_str}\n"
                    message += f"      Exit Reason: {exit_info.get('reason', 'N/A')}\n"
            else:
                message += f"❌ <b>No {signal_type} Signal</b>\n"
                message += f"   Option: <code>{option_symbol or 'N/A'}</code>\n"
                if analysis.get(condition_details_key):
                    message += "\n   📊 <b>Condition Details:</b>\n"
                    for cond, details in analysis[condition_details_key].items():
                        status = "✅ Pass" if details['pass'] else "❌ Fail"
                        telegram_cond = cond.replace('=', '&lt;=').replace('<', '&lt;').replace('>', '&gt;')
                        telegram_value = details['value'].replace('=', ':').replace('<', '&lt;').replace('>', '&gt;')
                        message += f"      {telegram_cond}: {status} ({telegram_value})\n"
            
            message += f"\n⏰ <b>Analysis Time:</b> {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S')}"
            self.telegram.send_message(message)
        except Exception as e:
            self.logger.error(f"Error sending Sensex debug message: {e}", exc_info=True)

    def send_option_debug_message(self, analysis: Dict, option_symbol: str, entry_price: float = None, exit_info: Dict = None, option_type: str = 'PE'):
        """Sends a Telegram message for option debug mode with CE or PE signal details"""
        try:
            signal_type = 'CE' if option_type == 'CE' else 'PE'
            message = f"🔍 <b>Option Debug Analysis ({signal_type})</b>\n\n"
            message += f"🎯 <b>Date:</b> {analysis.get('target_date', 'N/A')} {analysis.get('target_time', 'N/A')}\n"
            message += f"📈 <b>Sensex Spot Price:</b> ₹{analysis.get('spot_price', 'N/A'):,.2f}\n"
            message += f"🏷️ <b>Option Symbol:</b> <code>{option_symbol}</code>\n"
            
            signal_key = f"{signal_type.lower()}_signal"
            if analysis.get(signal_key):
                message += f"✅ <b>{signal_type} Signal Detected</b>\n"
                message += f"   Entry Time: {analysis.get('target_time')}\n"
                entry_price_str = f'₹{entry_price:.2f}' if entry_price is not None else 'N/A'
                message += f"   Option Price @ Entry: {entry_price_str}\n"
                
                if exit_info:
                    message += f"\n🚪 <b>Exit Details</b>\n"
                    message += f"   Exit Time: {exit_info.get('exit_time', 'N/A')}\n"
                    exit_option_price = exit_info.get('option_price')
                    exit_price_str = f'₹{exit_option_price:.2f}' if exit_option_price is not None else 'N/A'
                    message += f"   Option Price @ Exit: {exit_price_str}\n"
                    option_points = exit_info.get('option_points')
                    option_points_str = f'{option_points:.2f}' if option_points is not None else 'N/A'
                    message += f"   Option Points Captured: {option_points_str}\n"
                    message += f"   Exit Reason: {exit_info.get('reason', 'N/A')}\n"
            else:
                message += f"❌ <b>No {signal_type} Signal</b>\n"
                message += f"   Option: <code>{option_symbol}</code>\n"
                if analysis.get('condition_details'):
                    message += "\n📊 <b>Condition Details:</b>\n"
                    for cond, details in analysis['condition_details'].items():
                        status = "✅ Pass" if details['pass'] else "❌ Fail"
                        telegram_cond = cond.replace('=', '&lt;=').replace('<', '&lt;').replace('>', '&gt;')
                        telegram_value = details['value'].replace('=', ':').replace('<', '&lt;').replace('>', '&gt;')
                        message += f"   {telegram_cond}: {status} ({telegram_value})\n"
            
            message += f"\n⏰ <b>Analysis Time:</b> {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S')}"
            self.telegram.send_message(message)
        except Exception as e:
            self.logger.error(f"Error sending option debug message: {e}", exc_info=True)

    def debug_specific_conditions(self, strike: int, option_type: str, expiry_date: str, target_date: str, target_time: str, data_dir: str = "option_data", debug_data: str = "both", trade_type: str = 'long'):
        try:
            self.logger.info(f"Debug mode: Strike={strike}, Type={option_type}, Expiry={expiry_date}, Date={target_date}, Time={target_time}, DebugData={debug_data}, TradeType={trade_type}")
            
            analysis = {
                'target_date': target_date,
                'target_time': target_time,
                'spot_price': None,
                'sensex_close': None,
                'ce_signal': False,
                'pe_signal': False,
                'ce_condition_details': {},
                'pe_condition_details': {}
            }
            
            # Get Sensex spot price
            spot_price = self.option_chain.get_sensex_spot_price(historical_date=target_date)
            analysis['spot_price'] = spot_price
            self.logger.info(f"Sensex spot price for {target_date}: {spot_price}")
            
            if debug_data == "sensex":
                # Sensex debug mode (ATM CE or PE analysis based on trade_type)
                atm_strike = round(spot_price / 100) * 100 if spot_price else None
                option_symbol = None
                signal_type = 'CE' if trade_type == 'long' else 'PE'
                signal_key = 'ce_signal' if trade_type == 'long' else 'pe_signal'
                
                if atm_strike and expiry_date:
                    option_symbol = self.option_chain.get_symbol_for_strike(expiry_date, atm_strike, signal_type)
                    if not option_symbol:
                        option_symbol = self.construct_option_symbol(expiry_date, atm_strike, signal_type)
                        self.logger.warning(f"Fallback to constructed {signal_type} symbol: {option_symbol}")
                    self.logger.info(f"ATM {signal_type} option symbol: {option_symbol}")
                
                sensex_df = self.load_sensex_data_with_previous_day(target_date, data_dir)
                if sensex_df.empty:
                    message = f"❌ <b>No Sensex data available for {target_date}</b>\n"
                    message += f"📈 Sensex Spot Price: ₹{spot_price:,.2f}\n"
                    message += f"🏷️ Option: <code>{option_symbol or 'N/A'}</code>"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                
                sensex_df = sensex_df.drop(columns=['ema10', 'ema20'], errors='ignore')
                sensex_df['ema10'] = sensex_df['close'].ewm(span=10, adjust=False).mean()
                sensex_df['ema20'] = sensex_df['close'].ewm(span=20, adjust=False).mean()
                self.logger.info(f"EMA10 at {sensex_df.index[0]}: {sensex_df['ema10'].iloc[0]:.2f}, EMA20: {sensex_df['ema20'].iloc[0]:.2f}")
                self.logger.info(f"EMA10 at {sensex_df.index[-1]}: {sensex_df['ema10'].iloc[-1]:.2f}, EMA20: {sensex_df['ema20'].iloc[-1]:.2f}")
                
                target_datetime = datetime.strptime(f"{target_date} {target_time}", "%Y-%m-%d %H:%M")
                target_datetime = pytz.timezone('Asia/Kolkata').localize(target_datetime)
                self.logger.info(f"Target datetime: {target_datetime}")
                
                target_date_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
                sensex_df_target_day = sensex_df[sensex_df.index.date == target_date_dt]
                self.logger.info(f"Target day data: {len(sensex_df_target_day)} rows")
                
                if sensex_df_target_day.empty:
                    message = f"❌ <b>No Sensex data found for {target_date}</b>\n"
                    message += f"📈 Sensex Spot Price: ₹{spot_price:,.2f}\n"
                    message += f"🏷️ Option: <code>{option_symbol or 'N/A'}</code>"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                
                closest_idx = sensex_df_target_day.index.get_indexer([target_datetime], method='nearest')[0]
                closest_timestamp = sensex_df_target_day.index[closest_idx]
                time_diff = abs((closest_timestamp - target_datetime).total_seconds())
                self.logger.info(f"Closest entry timestamp: {closest_timestamp}, time_diff: {time_diff} seconds")
                if time_diff > 3 * 60:
                    message = f"❌ <b>No Sensex data found within 3 minutes of {target_time} on {target_date}</b>\n"
                    message += f"📈 Sensex Spot Price: ₹{spot_price:,.2f}\n"
                    message += f"🏷️ Option: <code>{option_symbol or 'N/A'}</code>"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                
                full_idx = sensex_df.index.get_indexer([closest_timestamp])[0]
                self.logger.info(f"Closest index: {full_idx}, Timestamp: {closest_timestamp}")
                sensex_df = sensex_df.iloc[:full_idx+1]
                self.logger.info(f"Sliced sensex_df for entry: {len(sensex_df)} rows up to {sensex_df.index[-1]}")
                analysis['sensex_close'] = sensex_df.iloc[-1]['close']
                
                latest_data = sensex_df.iloc[-1]
                
                # Evaluate conditions based on trade_type
                condition_details = {}
                if trade_type == 'long':
                    # CE Signal (Long)
                    is_green_candle = latest_data['close'] > latest_data['open']
                    condition_details['Green Candle'] = {
                        'pass': is_green_candle,
                        'value': f"close:{latest_data['close']:.2f}, open:{latest_data['open']:.2f}"
                    }
                    self.logger.info(f"CE Condition Green Candle: {'Pass' if is_green_candle else 'Fail'}, {condition_details['Green Candle']['value']}")
                    
                    ema10_gt_ema20 = latest_data['ema10'] > latest_data['ema20']
                    condition_details['EMA10 > EMA20'] = {
                        'pass': ema10_gt_ema20,
                        'value': f"ema10:{latest_data['ema10']:.2f}, ema20:{latest_data['ema20']:.2f}"
                    }
                    self.logger.info(f"CE Condition EMA10 > EMA20: {'Pass' if ema10_gt_ema20 else 'Fail'}, {condition_details['EMA10 > EMA20']['value']}")
                    
                    ema_diff = abs(latest_data['ema10'] - latest_data['ema20'])
                    ema_diff_le_51 = ema_diff <= 51
                    condition_details['|EMA10 - EMA20| <= 51'] = {
                        'pass': ema_diff_le_51,
                        'value': f"|ema10-ema20|:{ema_diff:.2f}"
                    }
                    self.logger.info(f"CE Condition |EMA10 - EMA20| <= 51: {'Pass' if ema_diff_le_51 else 'Fail'}, {condition_details['|EMA10 - EMA20| <= 51']['value']}")
                    
                    open_ema10_diff = abs(latest_data['open'] - latest_data['ema10'])
                    low_ema10_diff = abs(latest_data['low'] - latest_data['ema10'])
                    min_diff = min(open_ema10_diff, low_ema10_diff)
                    min_diff_lt_21 = min_diff < 21
                    condition_details['min(|open - EMA10|, |low - EMA10|) < 21'] = {
                        'pass': min_diff_lt_21,
                        'value': f"min(|open-ema10|:{open_ema10_diff:.2f}, |low-ema10|:{low_ema10_diff:.2f}):{min_diff:.2f}"
                    }
                    self.logger.info(f"CE Condition min(|open - EMA10|, |low - EMA10|) < 21: {'Pass' if min_diff_lt_21 else 'Fail'}, {condition_details['min(|open - EMA10|, |low - EMA10|) < 21']['value']}")
                    
                    analysis['ce_condition_details'] = condition_details
                    analysis['ce_signal'] = all(condition['pass'] for condition in condition_details.values())
                
                else:  # trade_type == 'short'
                    # PE Signal (Short)
                    is_red_candle = latest_data['close'] < latest_data['open']
                    condition_details['Red Candle'] = {
                        'pass': is_red_candle,
                        'value': f"close:{latest_data['close']:.2f}, open:{latest_data['open']:.2f}"
                    }
                    self.logger.info(f"PE Condition Red Candle: {'Pass' if is_red_candle else 'Fail'}, {condition_details['Red Candle']['value']}")
                    
                    ema10_lt_ema20 = latest_data['ema10'] < latest_data['ema20']
                    condition_details['EMA10 < EMA20'] = {
                        'pass': ema10_lt_ema20,
                        'value': f"ema10:{latest_data['ema10']:.2f}, ema20:{latest_data['ema20']:.2f}"
                    }
                    self.logger.info(f"PE Condition EMA10 < EMA20: {'Pass' if ema10_lt_ema20 else 'Fail'}, {condition_details['EMA10 < EMA20']['value']}")
                    
                    ema_diff = abs(latest_data['ema10'] - latest_data['ema20'])
                    ema_diff_le_51 = ema_diff <= 51
                    condition_details['|EMA10 - EMA20| <= 51'] = {
                        'pass': ema_diff_le_51,
                        'value': f"|ema10-ema20|:{ema_diff:.2f}"
                    }
                    self.logger.info(f"PE Condition |EMA10 - EMA20| <= 51: {'Pass' if ema_diff_le_51 else 'Fail'}, {condition_details['|EMA10 - EMA20| <= 51']['value']}")
                    
                    open_ema10_diff = abs(latest_data['open'] - latest_data['ema10'])
                    high_ema10_diff = abs(latest_data['high'] - latest_data['ema10'])
                    min_diff = min(open_ema10_diff, high_ema10_diff)
                    min_diff_lt_21 = min_diff < 21
                    condition_details['min(|open - EMA10|, |high - EMA10|) < 21'] = {
                        'pass': min_diff_lt_21,
                        'value': f"min(|open-ema10|:{open_ema10_diff:.2f}, |high-ema10|:{high_ema10_diff:.2f}):{min_diff:.2f}"
                    }
                    self.logger.info(f"PE Condition min(|open - EMA10|, |high - EMA10|) < 21: {'Pass' if min_diff_lt_21 else 'Fail'}, {condition_details['min(|open - EMA10|, |high - EMA10|) < 21']['value']}")
                    
                    analysis['pe_condition_details'] = condition_details
                    analysis['pe_signal'] = all(condition['pass'] for condition in condition_details.values())
                
                option_price = None
                exit_info = None
                
                if analysis[signal_key] and option_symbol:
                    option_price = self.get_option_price_at_timestamp(option_symbol, target_date, target_time, data_dir)
                    self.logger.info(f"{signal_type} option price for {option_symbol} at {target_date} {target_time}: {option_price if option_price is not None else 'N/A'}")
                
                # Exit Logic
                if analysis[signal_key]:
                    entry_timestamp = closest_timestamp
                    entry_sensex_close = analysis['sensex_close']
                    max_candles = 20 if trade_type == 'long' else 10
                    max_time = entry_timestamp + timedelta(minutes=60 if trade_type == 'long' else 30)
                    
                    subsequent_candles = sensex_df_target_day[sensex_df_target_day.index > entry_timestamp]
                    candle_count = 0
                    
                    for idx, row in subsequent_candles.iterrows():
                        candle_count += 1
                        current_time = idx.strftime("%H:%M")
                        
                        temp_df = sensex_df[sensex_df.index <= idx]
                        temp_df['ema10'] = temp_df['close'].ewm(span=10, adjust=False).mean()
                        temp_df['ema20'] = temp_df['close'].ewm(span=20, adjust=False).mean()
                        current_ema10 = temp_df['ema10'].iloc[-1]
                        current_ema20 = temp_df['ema20'].iloc[-1]
                        
                        if trade_type == 'long':
                            is_red_candle = row['close'] < row['open']
                            close_below_ema20 = row['close'] < current_ema20
                            close_ema20_diff = abs(row['close'] - current_ema20)
                            ema10_lt_ema20 = current_ema10 < current_ema20
                            
                            if is_red_candle and close_below_ema20:
                                exit_reason = "Red candle and close < EMA20"
                                exit_time = current_time
                                exit_sensex_close = row['close']
                                exit_option_price = self.get_option_price_at_timestamp(option_symbol, target_date, exit_time, data_dir)
                                exit_info = {
                                    'exit_time': exit_time,
                                    'sensex_close': exit_sensex_close,
                                    'option_price': exit_option_price,
                                    'sensex_points': exit_sensex_close - entry_sensex_close,
                                    'option_points': exit_option_price - option_price if exit_option_price is not None and option_price is not None else None,
                                    'reason': exit_reason
                                }
                                self.logger.info(f"CE Exit triggered at {exit_time}: {exit_reason}")
                                break
                            
                            if close_ema20_diff > 150:
                                exit_reason = "|close - EMA20| > 150"
                                exit_time = current_time
                                exit_sensex_close = row['close']
                                exit_option_price = self.get_option_price_at_timestamp(option_symbol, target_date, exit_time, data_dir)
                                exit_info = {
                                    'exit_time': exit_time,
                                    'sensex_close': exit_sensex_close,
                                    'option_price': exit_option_price,
                                    'sensex_points': exit_sensex_close - entry_sensex_close,
                                    'option_points': exit_option_price - option_price if exit_option_price is not None and option_price is not None else None,
                                    'reason': exit_reason
                                }
                                self.logger.info(f"CE Exit triggered at {exit_time}: {exit_reason}")
                                break
                            
                            if row['close'] <= current_ema20:
                                exit_reason = "Stop Loss: close <= EMA20"
                                exit_time = current_time
                                exit_sensex_close = row['close']
                                exit_option_price = self.get_option_price_at_timestamp(option_symbol, target_date, exit_time, data_dir)
                                exit_info = {
                                    'exit_time': exit_time,
                                    'sensex_close': exit_sensex_close,
                                    'option_price': exit_option_price,
                                    'sensex_points': exit_sensex_close - entry_sensex_close,
                                    'option_points': exit_option_price - option_price if exit_option_price is not None and option_price is not None else None,
                                    'reason': exit_reason
                                }
                                self.logger.info(f"CE Exit triggered at {exit_time}: {exit_reason}")
                                break
                            
                            if ema10_lt_ema20:
                                exit_reason = "EMA10 < EMA20 crossover"
                                exit_time = current_time
                                exit_sensex_close = row['close']
                                exit_option_price = self.get_option_price_at_timestamp(option_symbol, target_date, exit_time, data_dir)
                                exit_info = {
                                    'exit_time': exit_time,
                                    'sensex_close': exit_sensex_close,
                                    'option_price': exit_option_price,
                                    'sensex_points': exit_sensex_close - entry_sensex_close,
                                    'option_points': exit_option_price - option_price if exit_option_price is not None and option_price is not None else None,
                                    'reason': exit_reason
                                }
                                self.logger.info(f"CE Exit triggered at {exit_time}: {exit_reason}")
                                break
                            
                            if candle_count >= max_candles or idx >= max_time:
                                exit_reason = f"Max {max_candles} candles ({60 if trade_type == 'long' else 30} minutes)"
                                exit_time = current_time
                                exit_sensex_close = row['close']
                                exit_option_price = self.get_option_price_at_timestamp(option_symbol, target_date, exit_time, data_dir)
                                exit_info = {
                                    'exit_time': exit_time,
                                    'sensex_close': exit_sensex_close,
                                    'option_price': exit_option_price,
                                    'sensex_points': exit_sensex_close - entry_sensex_close,
                                    'option_points': exit_option_price - option_price if exit_option_price is not None and option_price is not None else None,
                                    'reason': exit_reason
                                }
                                self.logger.info(f"CE Exit triggered at {exit_time}: {exit_reason}")
                                break
                        
                        else:  # trade_type == 'short'
                            is_green_candle = row['close'] > row['open']
                            close_above_ema20 = row['close'] > current_ema20
                            close_ema20_diff = abs(row['close'] - current_ema20)
                            ema10_gt_ema20 = current_ema10 > current_ema20
                            
                            if is_green_candle and close_above_ema20:
                                exit_reason = "Green candle and close > EMA20"
                                exit_time = current_time
                                exit_sensex_close = row['close']
                                exit_option_price = self.get_option_price_at_timestamp(option_symbol, target_date, exit_time, data_dir)
                                exit_info = {
                                    'exit_time': exit_time,
                                    'sensex_close': exit_sensex_close,
                                    'option_price': exit_option_price,
                                    'sensex_points': exit_sensex_close - entry_sensex_close,
                                    'option_points': exit_option_price - option_price if exit_option_price is not None and option_price is not None else None,
                                    'reason': exit_reason
                                }
                                self.logger.info(f"PE Exit triggered at {exit_time}: {exit_reason}")
                                break
                            
                            if close_ema20_diff > 150:
                                exit_reason = "|close - EMA20| > 150"
                                exit_time = current_time
                                exit_sensex_close = row['close']
                                exit_option_price = self.get_option_price_at_timestamp(option_symbol, target_date, exit_time, data_dir)
                                exit_info = {
                                    'exit_time': exit_time,
                                    'sensex_close': exit_sensex_close,
                                    'option_price': exit_option_price,
                                    'sensex_points': exit_sensex_close - entry_sensex_close,
                                    'option_points': exit_option_price - option_price if exit_option_price is not None and option_price is not None else None,
                                    'reason': exit_reason
                                }
                                self.logger.info(f"PE Exit triggered at {exit_time}: {exit_reason}")
                                break
                            
                            if row['close'] >= current_ema20:
                                exit_reason = "Stop Loss: close >= EMA20"
                                exit_time = current_time
                                exit_sensex_close = row['close']
                                exit_option_price = self.get_option_price_at_timestamp(option_symbol, target_date, exit_time, data_dir)
                                exit_info = {
                                    'exit_time': exit_time,
                                    'sensex_close': exit_sensex_close,
                                    'option_price': exit_option_price,
                                    'sensex_points': exit_sensex_close - entry_sensex_close,
                                    'option_points': exit_option_price - option_price if exit_option_price is not None and option_price is not None else None,
                                    'reason': exit_reason
                                }
                                self.logger.info(f"PE Exit triggered at {exit_time}: {exit_reason}")
                                break
                            
                            if ema10_gt_ema20:
                                exit_reason = "EMA10 > EMA20 crossover"
                                exit_time = current_time
                                exit_sensex_close = row['close']
                                exit_option_price = self.get_option_price_at_timestamp(option_symbol, target_date, exit_time, data_dir)
                                exit_info = {
                                    'exit_time': exit_time,
                                    'sensex_close': exit_sensex_close,
                                    'option_price': exit_option_price,
                                    'sensex_points': exit_sensex_close - entry_sensex_close,
                                    'option_points': exit_option_price - option_price if exit_option_price is not None and option_price is not None else None,
                                    'reason': exit_reason
                                }
                                self.logger.info(f"PE Exit triggered at {exit_time}: {exit_reason}")
                                break
                            
                            if candle_count >= max_candles or idx >= max_time:
                                exit_reason = f"Max {max_candles} candles ({60 if trade_type == 'long' else 30} minutes)"
                                exit_time = current_time
                                exit_sensex_close = row['close']
                                exit_option_price = self.get_option_price_at_timestamp(option_symbol, target_date, exit_time, data_dir)
                                exit_info = {
                                    'exit_time': exit_time,
                                    'sensex_close': exit_sensex_close,
                                    'option_price': exit_option_price,
                                    'sensex_points': exit_sensex_close - entry_sensex_close,
                                    'option_points': exit_option_price - option_price if exit_option_price is not None and option_price is not None else None,
                                    'reason': exit_reason
                                }
                                self.logger.info(f"PE Exit triggered at {exit_time}: {exit_reason}")
                                break
                
                self.send_sensex_debug_message(analysis, option_symbol, option_price, exit_info, trade_type)
            
            elif debug_data == "option":
                # Option debug mode (specific strike and type)
                option_symbol = None
                if strike and option_type and expiry_date:
                    option_symbol = self.option_chain.get_symbol_for_strike(expiry_date, strike, option_type)
                    if not option_symbol:
                        option_symbol = self.construct_option_symbol(expiry_date, strike, option_type)
                        self.logger.warning(f"Fallback to constructed symbol: {option_symbol}")
                    self.logger.info(f"Option symbol for strike {strike} ({option_type}): {option_symbol}")
                    analysis['symbol'] = option_symbol
                
                if not option_symbol:
                    message = f"❌ <b>No valid option symbol for strike {strike} ({option_type}) on {target_date}</b>\n"
                    message += f"📈 Sensex Spot Price: ₹{spot_price:,.2f}\n"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                
                option_df = self.load_option_data_with_previous_day(option_symbol, target_date, data_dir)
                if option_df.empty:
                    pattern = os.path.join(data_dir, f"SENSEX*_{strike}{option_type}_{target_date}.csv")
                    available_files = glob.glob(pattern)
                    if available_files:
                        message = f"❌ <b>Option data file not found for {option_symbol} on {target_date}</b>\n"
                        message += f"📈 Sensex Spot Price: ₹{spot_price:,.2f}\n"
                        message += f"🏷️ Option: <code>{option_symbol}</code>\n"
                        message += f"ℹ️ Available files for strike {strike} ({option_type}) on {target_date}: {', '.join([os.path.basename(f) for f in available_files])}"
                    else:
                        message = f"❌ <b>Option data file not found for {option_symbol} on {target_date}</b>\n"
                        message += f"📈 Sensex Spot Price: ₹{spot_price:,.2f}\n"
                        message += f"🏷️ Option: <code>{option_symbol}</code>"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                
                option_df = option_df.drop(columns=['ema10', 'ema20'], errors='ignore')
                option_df['ema10'] = option_df['close'].ewm(span=10, adjust=False).mean()
                option_df['ema20'] = option_df['close'].ewm(span=20, adjust=False).mean()
                self.logger.info(f"Option EMA10 at {option_df.index[0]}: {option_df['ema10'].iloc[0]:.2f}, EMA20: {option_df['ema20'].iloc[0]:.2f}")
                self.logger.info(f"Option EMA10 at {option_df.index[-1]}: {option_df['ema10'].iloc[-1]:.2f}, EMA20: {option_df['ema20'].iloc[-1]:.2f}")
                
                target_datetime = datetime.strptime(f"{target_date} {target_time}", "%Y-%m-%d %H:%M")
                target_datetime = pytz.timezone('Asia/Kolkata').localize(target_datetime)
                option_df_target_day = option_df[option_df.index.date == target_datetime.date()]
                
                if option_df_target_day.empty:
                    message = f"❌ <b>No option data found for {option_symbol} on {target_date}</b>\n"
                    message += f"📈 Sensex Spot Price: ₹{spot_price:,.2f}\n"
                    message += f"🏷️ Option: <code>{option_symbol}</code>"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                
                closest_idx = option_df_target_day.index.get_indexer([target_datetime], method='nearest')[0]
                closest_timestamp = option_df_target_day.index[closest_idx]
                time_diff = abs((closest_timestamp - target_datetime).total_seconds())
                self.logger.info(f"Closest option timestamp: {closest_timestamp}, time_diff: {time_diff} seconds")
                if time_diff > 3 * 60:
                    message = f"❌ <b>No option data found within 3 minutes of {target_time} on {target_date}</b>\n"
                    message += f"📈 Sensex Spot Price: ₹{spot_price:,.2f}\n"
                    message += f"🏷️ Option: <code>{option_symbol}</code>\n"
                    message += f"ℹ️ Closest timestamp: {closest_timestamp}"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                
                option_df = option_df[option_df.index <= closest_timestamp]
                latest_data = option_df.loc[option_df.index == closest_timestamp]
                if latest_data.empty:
                    message = f"❌ <b>No data found for {option_symbol} at {target_date} {target_time}</b>\n"
                    message += f"📈 Sensex Spot Price: ₹{spot_price:,.2f}\n"
                    message += f"🏷️ Option: <code>{option_symbol}</code>"
                    self.logger.error(message)
                    self.telegram.send_message(message)
                    return
                
                latest_data = latest_data.iloc[0]
                ema10 = option_df.loc[option_df.index == closest_timestamp, 'ema10'].iloc[0]
                ema20 = option_df.loc[option_df.index == closest_timestamp, 'ema20'].iloc[0]
                
                condition_details = {}
                is_green_candle = latest_data['close'] > latest_data['open']
                condition_details['Green Candle'] = {
                    'pass': is_green_candle,
                    'value': f"close:{latest_data['close']:.2f}, open:{latest_data['open']:.2f}"
                }
                self.logger.info(f"Condition Green Candle: {'Pass' if is_green_candle else 'Fail'}, {condition_details['Green Candle']['value']}")
                
                ema10_gt_ema20 = ema10 > ema20
                condition_details['EMA10 > EMA20'] = {
                    'pass': ema10_gt_ema20,
                    'value': f"ema10:{ema10:.2f}, ema20:{ema20:.2f}"
                }
                self.logger.info(f"Condition EMA10 > EMA20: {'Pass' if ema10_gt_ema20 else 'Fail'}, {condition_details['EMA10 > EMA20']['value']}")
                
                ema_diff = abs(ema10 - ema20)
                ema_diff_lt_15 = ema_diff < 15
                condition_details['|EMA10 - EMA20| < 15'] = {
                    'pass': ema_diff_lt_15,
                    'value': f"|ema10-ema20|:{ema_diff:.2f}"
                }
                self.logger.info(f"Condition |EMA10 - EMA20| < 15: {'Pass' if ema_diff_lt_15 else 'Fail'}, {condition_details['|EMA10 - EMA20| < 15']['value']}")
                
                open_ema10_diff = abs(latest_data['open'] - ema10)
                low_ema10_diff = abs(latest_data['low'] - ema10)
                min_diff = min(open_ema10_diff, low_ema10_diff)
                min_diff_lt_21 = min_diff < 21
                condition_details['min(|open - EMA10|, |low - EMA10|) < 21'] = {
                    'pass': min_diff_lt_21,
                    'value': f"min(|open-ema10|:{open_ema10_diff:.2f}, |low-ema10|:{low_ema10_diff:.2f}):{min_diff:.2f}"
                }
                self.logger.info(f"Condition min(|open - EMA10|, |low - EMA10|) < 21: {'Pass' if min_diff_lt_21 else 'Fail'}, {condition_details['min(|open - EMA10|, |low - EMA10|) < 21']['value']}")
                
                analysis['condition_details'] = condition_details
                signal_type = 'ce_signal' if option_type == 'CE' else 'pe_signal'
                analysis[signal_type] = all(condition['pass'] for condition in condition_details.values())
                
                exit_info = None
                if analysis[signal_type]:
                    entry_timestamp = closest_timestamp
                    entry_option_price = latest_data['close']
                    max_candles = 10
                    max_time = entry_timestamp + timedelta(minutes=30)
                    
                    subsequent_candles = option_df_target_day[option_df_target_day.index > entry_timestamp]
                    candle_count = 0
                    
                    for idx, row in subsequent_candles.iterrows():
                        candle_count += 1
                        current_time = idx.strftime("%H:%M")
                        
                        temp_df = option_df[option_df.index <= idx]
                        temp_df['ema10'] = temp_df['close'].ewm(span=10, adjust=False).mean()
                        temp_df['ema20'] = temp_df['close'].ewm(span=20, adjust=False).mean()
                        current_ema10 = temp_df['ema10'].iloc[-1]
                        current_ema20 = temp_df['ema20'].iloc[-1]
                        
                        is_red_candle = row['close'] < row['open']
                        close_below_ema10 = row['close'] < current_ema10
                        close_ema20_diff = abs(row['close'] - current_ema20)
                        
                        if is_red_candle and close_below_ema10:
                            exit_reason = "Red candle and close < EMA10"
                            exit_time = current_time
                            exit_option_price = row['close']
                            exit_info = {
                                'exit_time': exit_time,
                                'option_price': exit_option_price,
                                'option_points': exit_option_price - entry_option_price,
                                'reason': exit_reason
                            }
                            self.logger.info(f"Exit triggered at {exit_time}: {exit_reason}")
                            break
                        
                        if close_ema20_diff > 150:
                            exit_reason = "|close - EMA20| > 150"
                            exit_time = current_time
                            exit_option_price = row['close']
                            exit_info = {
                                'exit_time': exit_time,
                                'option_price': exit_option_price,
                                'option_points': exit_option_price - entry_option_price,
                                'reason': exit_reason
                            }
                            self.logger.info(f"Exit triggered at {exit_time}: {exit_reason}")
                            break
                        
                        if candle_count >= max_candles or idx >= max_time:
                            exit_reason = "Max 10 candles (30 minutes)"
                            exit_time = current_time
                            exit_option_price = row['close']
                            exit_info = {
                                'exit_time': exit_time,
                                'option_price': exit_option_price,
                                'option_points': exit_option_price - entry_option_price,
                                'reason': exit_reason
                            }
                            self.logger.info(f"Exit triggered at {exit_time}: {exit_reason}")
                            break
                
                self.send_option_debug_message(analysis, option_symbol, entry_option_price if analysis.get(signal_type) else None, exit_info, option_type)
            
            elif debug_data == "both":
                self.logger.info("Debug mode 'both' not fully implemented; running Sensex and Option modes")
                self.debug_specific_conditions(strike, option_type, expiry_date, target_date, target_time, data_dir, debug_data="sensex", trade_type=trade_type)
                self.debug_specific_conditions(strike, option_type, expiry_date, target_date, target_time, data_dir, debug_data="option", trade_type=trade_type)
        
        except Exception as e:
            self.logger.error(f"Error in debug mode: {e}", exc_info=True)
            self.telegram.send_message(f"❌ <b>Debug Error:</b> {str(e)}")

def main():
    parser = argparse.ArgumentParser(description='Sensex Trading Bot - Debug Mode')
    parser.add_argument('--access-token', required=True, help='Kite Connect access token')
    parser.add_argument('--strike', type=int, help='Strike price for debug mode')
    parser.add_argument('--option-type', choices=['CE', 'PE'], help='Option type for debug mode')
    parser.add_argument('--expiry-date', help='Expiry date for debug mode (YYYY-MM-DD)')
    parser.add_argument('--date', help='Date for debug mode (YYYY-MM-DD)')
    parser.add_argument('--time', help='Time for debug mode (HH:MM, 24hr format)')
    parser.add_argument('--data-dir', default="option_data", help='Directory for pre-fetched data (default: option_data)')
    parser.add_argument('--debug-data', choices=['sensex', 'option', 'both'], default='both',
                        help='Data to debug: sensex, option, or both')
    parser.add_argument('--trade-type', choices=['long', 'short'], default='long',
                        help='Trade type for sensex mode: long (CE) or short (PE)')
    args = parser.parse_args()
    bot = SensexTradingBot()
    if not bot.initialize_kite(args.access_token, expiry_date=args.expiry_date or '2025-09-11'):
        print("Failed to initialize Kite Connect. Exiting.")
        return
    try:
        if args.debug_data == 'sensex' and not all([args.date, args.time]):
            print("Debug mode 'sensex' requires: --date, --time")
            return
        elif args.debug_data == 'option' and not all([args.strike, args.option_type, args.expiry_date, args.date, args.time]):
            print("Debug mode 'option' requires: --strike, --option-type, --expiry-date, --date, --time")
            return
        print(f"Running debug mode for {args.debug_data} on {args.date} at {args.time}, TradeType={args.trade_type}")
        bot.debug_specific_conditions(
            args.strike,
            args.option_type,
            args.expiry_date or '2025-09-11',
            args.date,
            args.time,
            args.data_dir,
            args.debug_data,
            args.trade_type
        )
    except Exception as e:
        print(f"Bot error: {e}")
        bot.telegram.send_message(f"❌ <b>Bot Error:</b> {str(e)}")

if __name__ == "__main__":
    main()
