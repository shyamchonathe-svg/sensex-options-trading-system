#!/usr/bin/env python3
"""
Sensex BigBar Trading Bot - FIXED for BFO Exchange
Complete implementation with proper BFO exchange support
"""

import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
from kiteconnect import KiteConnect
import logging
import requests
import json
import schedule
import time as time_module
import pytz
from typing import Dict, Optional, Tuple, List
import sys
import argparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('sensex_bigbar_bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

class TradingHoursValidator:
    """Validates trading hours and market days"""
    
    @staticmethod
    def is_market_open() -> Tuple[bool, str]:
        """Check if market is currently open for trading"""
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        
        # Check if it's a weekday (Monday=0, Sunday=6)
        if now.weekday() > 4:  # Saturday=5, Sunday=6
            return False, f"Market closed - Weekend ({now.strftime('%A')})"
        
        # Market hours: 9:15 AM to 3:30 PM IST
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        
        if now < market_open:
            time_to_open = market_open - now
            return False, f"Market opens in {time_to_open} at 9:15 AM"
        
        if now > market_close:
            return False, f"Market closed at 3:30 PM (Current: {now.strftime('%H:%M')})"
        
        # Check for major holidays
        if TradingHoursValidator.is_market_holiday(now):
            return False, f"Market closed - Holiday ({now.strftime('%Y-%m-%d')})"
        
        return True, f"Market open (Current: {now.strftime('%H:%M')})"
    
    @staticmethod
    def is_market_holiday(date: datetime) -> bool:
        """Check if given date is a market holiday"""
        # Basic holiday list - expand as needed
        holidays_2024 = [
            (1, 26), (3, 8), (3, 29), (4, 11), (4, 17), (5, 1),
            (8, 15), (10, 2), (10, 24), (11, 1), (11, 12), (12, 25)
        ]
        
        holidays_2025 = [
            (1, 26), (2, 26), (4, 18), (4, 6), (4, 14), (5, 1),
            (8, 15), (10, 2), (10, 22), (11, 1), (12, 25)
        ]
        
        current_year_holidays = holidays_2024 if date.year == 2024 else holidays_2025
        date_tuple = (date.month, date.day)
        
        return date_tuple in current_year_holidays
    
    @staticmethod
    def get_time_to_market_close() -> int:
        """Get minutes remaining until market close"""
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        
        is_open, _ = TradingHoursValidator.is_market_open()
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
        """Send message to Telegram"""
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode
            }
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                self.logger.info("Telegram message sent successfully")
            else:
                self.logger.error(f"Failed to send Telegram message: {response.text}")
        except Exception as e:
            self.logger.error(f"Error sending Telegram message: {e}")

class SensexOptionChain:
    """Handles Sensex option chain operations - FIXED for BFO exchange"""
    def __init__(self, kite: KiteConnect):
        self.kite = kite
        self.logger = logging.getLogger(__name__)
        self.option_chain_cache = {}
        self.cache_timestamp = None
        self.cache_duration = 180  # 3 minutes
        
    def get_sensex_spot_price(self) -> float:
        """Get current Sensex spot price"""
        try:
            quote = self.kite.quote(["BSE:SENSEX"])
            return quote["BSE:SENSEX"]["last_price"]
        except Exception as e:
            self.logger.error(f"Error fetching Sensex price: {e}")
            return None
    
    def get_vix_price(self) -> float:
        """Get current VIX price"""
        try:
            quote = self.kite.quote(["NSE:INDIAVIX"])
            return quote["NSE:INDIAVIX"]["last_price"]
        except Exception as e:
            self.logger.error(f"Error fetching VIX price: {e}")
            return None
    
    def calculate_target_strike(self, sensex_price: float) -> int:
        """Calculate target strike based on session and price"""
        current_time = datetime.now().time()
        
        if current_time < time(12, 0):  # Morning session
            target_strike = int(sensex_price // 100) * 100
            session = "Morning"
        else:  # Afternoon session
            target_strike = int((sensex_price - 175) // 100) * 100
            session = "Afternoon"
            
        self.logger.info(f"Sensex: {sensex_price}, Session: {session}, Target Strike: {target_strike}")
        return target_strike
    
    def get_option_chain(self) -> Dict:
        """Fetch Sensex option chain with caching - FIXED for BFO exchange"""
        current_time = datetime.now()
        
        # Check cache validity
        if (self.option_chain_cache and self.cache_timestamp and 
            (current_time - self.cache_timestamp).seconds < self.cache_duration):
            return self.option_chain_cache
        
        try:
            # CRITICAL FIX: Use BFO exchange instead of NSE
            instruments = self.kite.instruments("BFO")
            
            # Filter Sensex options - FIXED naming pattern
            sensex_options = [
                inst for inst in instruments 
                if (inst['name'] == 'SENSEX' and 
                    inst['instrument_type'] in ['CE', 'PE'] and
                    inst['expiry'])
            ]
            
            self.logger.info(f"Found {len(sensex_options)} Sensex options on BFO")
            
            # Group by expiry and strike
            option_chain = {}
            for option in sensex_options:
                expiry = option['expiry']
                strike = int(option['strike'])
                option_type = option['instrument_type']
                
                if expiry not in option_chain:
                    option_chain[expiry] = {}
                if strike not in option_chain[expiry]:
                    option_chain[expiry][strike] = {}
                    
                option_chain[expiry][strike][option_type] = {
                    'symbol': option['tradingsymbol'],
                    'instrument_token': option['instrument_token'],
                    'lot_size': option['lot_size'],
                    'exchange': 'BFO'  # Ensure BFO exchange
                }
            
            self.option_chain_cache = option_chain
            self.cache_timestamp = current_time
            
            self.logger.info(f"Option chain refreshed. Found {len(sensex_options)} Sensex options")
            return option_chain
            
        except Exception as e:
            self.logger.error(f"Error fetching option chain: {e}")
            return {}
    
    def get_weekly_expiry_symbols(self, target_strike: int) -> Dict:
        """Get weekly expiry symbols for target strike"""
        option_chain = self.get_option_chain()
        
        # Find next Tuesday (weekly expiry)
        today = datetime.now()
        days_ahead = 1 - today.weekday()  # 1 = Tuesday
        if days_ahead <= 0:
            days_ahead += 7
        next_tuesday = today + timedelta(days=days_ahead)
        
        # If today is Tuesday after 3:30 PM, get next week
        if today.weekday() == 1 and today.time() > time(15, 30):
            next_tuesday += timedelta(days=7)
        
        target_expiry = next_tuesday.strftime("%Y-%m-%d")
        
        # Find matching expiry and strike
        for expiry, strikes in option_chain.items():
            if expiry == target_expiry and target_strike in strikes:
                symbols = strikes[target_strike]
                return {
                    'expiry': expiry,
                    'strike': target_strike,
                    'ce_symbol': symbols.get('CE', {}).get('symbol'),
                    'pe_symbol': symbols.get('PE', {}).get('symbol'),
                    'ce_token': symbols.get('CE', {}).get('instrument_token'),
                    'pe_token': symbols.get('PE', {}).get('instrument_token'),
                    'lot_size': symbols.get('CE', {}).get('lot_size', 10),  # FIXED: Default lot size for BFO
                    'exchange': 'BFO'
                }
        
        return {}
    
    def get_option_prices(self, symbols: Dict) -> Dict:
        """Get current option prices - FIXED for BFO exchange"""
        try:
            if not symbols or not symbols.get('ce_symbol') or not symbols.get('pe_symbol'):
                return {}
            
            # CRITICAL FIX: Use BFO: prefix instead of NSE:
            ce_symbol = f"BFO:{symbols['ce_symbol']}"
            pe_symbol = f"BFO:{symbols['pe_symbol']}"
            
            quotes = self.kite.quote([ce_symbol, pe_symbol])
            
            return {
                'ce_price': quotes[ce_symbol]['last_price'],
                'pe_price': quotes[pe_symbol]['last_price'],
                'ce_symbol': symbols['ce_symbol'],
                'pe_symbol': symbols['pe_symbol'],
                'strike': symbols['strike'],
                'expiry': symbols['expiry'],
                'exchange': 'BFO'
            }
            
        except Exception as e:
            self.logger.error(f"Error fetching option prices: {e}")
            return {}

class VIXThresholdManager:
    """Manages VIX-based dynamic thresholds"""
    
    @staticmethod
    def get_vix_thresholds(vix_price: float) -> Dict:
        """Get VIX-based thresholds"""
        if vix_price <= 12:
            return {
                'candle_size_threshold': 40,
                'max_candle_size': 80,
                'candle_count_limit': 0,
                'ema40_distance_threshold': 150.0
            }
        elif vix_price <= 13:
            return {
                'candle_size_threshold': 45,
                'max_candle_size': 90,
                'candle_count_limit': 5,
                'ema40_distance_threshold': 150.0
            }
        elif vix_price <= 14:
            return {
                'candle_size_threshold': 50,
                'max_candle_size': 100,
                'candle_count_limit': 5,
                'ema40_distance_threshold': 150.0
            }
        elif vix_price <= 15:
            return {
                'candle_size_threshold': 55,
                'max_candle_size': 110,
                'candle_count_limit': 5,
                'ema40_distance_threshold': 200.0
            }
        elif vix_price <= 16:
            return {
                'candle_size_threshold': 60,
                'max_candle_size': 120,
                'candle_count_limit': 5,
                'ema40_distance_threshold': 200.0
            }
        elif vix_price <= 17:
            return {
                'candle_size_threshold': 65,
                'max_candle_size': 130,
                'candle_count_limit': 3,
                'ema40_distance_threshold': 200.0
            }
        elif vix_price <= 18:
            return {
                'candle_size_threshold': 70,
                'max_candle_size': 140,
                'candle_count_limit': 3,
                'ema40_distance_threshold': 200.0
            }
        elif vix_price <= 19:
            return {
                'candle_size_threshold': 75,
                'max_candle_size': 150,
                'candle_count_limit': 3,
                'ema40_distance_threshold': 200.0
            }
        else:  # VIX >= 19
            return {
                'candle_size_threshold': 85,
                'max_candle_size': 170,
                'candle_count_limit': 3,
                'ema40_distance_threshold': 200.0
            }

class BigBarStrategy:
    """Implements BigBar trading strategy"""
    
    def __init__(self, kite: KiteConnect):
        self.kite = kite
        self.logger = logging.getLogger(__name__)
        
        # Trading state
        self.current_position = None
        self.entry_strike = None
        self.entry_price = 0.0
        self.entry_type = ""
        self.entry_bar = 0
        self.sl_price = 0.0
        self.candle_count = 0
        self.trading_paused = False
        self.vix_918_change = 0.0
        
        # Store 9:18 AM VIX for pause logic
        self.vix_918 = 0.0
    
    def get_historical_data(self, instrument_token: str, from_date: str, to_date: str, interval: str = "3minute") -> pd.DataFrame:
        """Get historical OHLCV data"""
        try:
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval=interval
            )
            
            df = pd.DataFrame(data)
            if not df.empty:
                df['timestamp'] = pd.to_datetime(df['date'])
                df.set_index('timestamp', inplace=True)
                
                # Calculate EMAs
                df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
                df['ema40'] = df['close'].ewm(span=40, adjust=False).mean()
                
            return df
            
        except Exception as e:
            self.logger.error(f"Error fetching historical data: {e}")
            return pd.DataFrame()
    
    def check_vix_pause_condition(self, vix_price: float) -> bool:
        """Check if trading should be paused due to VIX conditions"""
        current_time = datetime.now().time()
        
        # Store VIX at 9:18 AM
        if current_time >= time(9, 18) and current_time <= time(9, 19) and self.vix_918 == 0.0:
            try:
                vix_quote = self.kite.quote(["NSE:INDIAVIX"])
                vix_open = vix_quote["NSE:INDIAVIX"]["ohlc"]["open"]
                self.vix_918 = vix_price
                self.vix_918_change = abs((vix_price - vix_open) / vix_open * 100)
                
                if self.vix_918_change > 10:
                    self.trading_paused = True
                    self.logger.warning(f"Trading paused: VIX change {self.vix_918_change:.2f}% > 10%")
                    return True
            except Exception as e:
                self.logger.error(f"Error checking VIX pause condition: {e}")
        
        return self.trading_paused
    
    def validate_previous_candles(self, df: pd.DataFrame, current_idx: int, threshold: float) -> bool:
        """Validate previous 3 candles for large red candles"""
        try:
            for i in range(1, 4):  # Check last 3 candles
                if current_idx - i < 0:
                    continue
                    
                prev_candle = df.iloc[current_idx - i]
                candle_size = prev_candle['close'] - prev_candle['open']
                
                # Check for large red candle
                if (prev_candle['close'] < prev_candle['open'] and 
                    abs(candle_size) > 1.5 * threshold):
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating previous candles: {e}")
            return False
    
    def check_bigbar_entry_conditions(self, df: pd.DataFrame, vix_thresholds: Dict, debug: bool = False) -> Dict:
        """Check BigBar entry conditions for latest candle"""
        if df.empty or len(df) < 40:  # Need at least 40 candles for EMA40
            return {'signal': False, 'debug': 'Insufficient data'}
        
        current = df.iloc[-1]  # Latest candle
        current_idx = len(df) - 1
        
        debug_info = {
            'timestamp': current.name.strftime('%Y-%m-%d %H:%M:%S'),
            'open': current['open'],
            'close': current['close'],
            'ema20': current['ema20'],
            'ema40': current['ema40']
        }
        
        # Extract thresholds
        candle_size_threshold = vix_thresholds['candle_size_threshold']
        max_candle_size = vix_thresholds['max_candle_size']
        
        # Condition 1: Green candle
        is_green = current['close'] > current['open']
        candle_size = current['close'] - current['open']
        debug_info['condition_1_green'] = f"{'✅ PASS' if is_green else '❌ FAIL'} - Close: {current['close']:.2f} > Open: {current['open']:.2f}"
        
        # Condition 2: Candle size within range
        size_ok = candle_size_threshold <= candle_size <= max_candle_size
        debug_info['condition_2_size'] = f"{'✅ PASS' if size_ok else '❌ FAIL'} - Size: {candle_size:.2f} (Required: {candle_size_threshold}-{max_candle_size})"
        
        # Condition 3: EMA alignment
        ema_diff = abs(current['ema20'] - current['ema40'])
        ema_condition1 = current['ema20'] > current['ema40'] and ema_diff < 50
        ema_condition2 = current['ema40'] > current['ema20'] and ema_diff < 10
        ema_aligned = ema_condition1 or ema_condition2
        debug_info['condition_3_ema'] = f"{'✅ PASS' if ema_aligned else '❌ FAIL'} - EMA20: {current['ema20']:.2f}, EMA40: {current['ema40']:.2f}, Diff: {ema_diff:.2f}"
        
        # Condition 4: Open-EMA20 distance
        open_ema_diff = abs(current['open'] - current['ema20'])
        open_ema_condition1 = open_ema_diff < 50
        open_ema_condition2 = (current['open'] > current['ema20'] or 
                              (current['ema20'] > current['open'] and abs(current['ema20'] - current['open']) < 10))
        open_ema_ok = open_ema_condition1 and open_ema_condition2
        debug_info['condition_4_open_ema'] = f"{'✅ PASS' if open_ema_ok else '❌ FAIL'} - Distance: {open_ema_diff:.2f}"
        
        # Condition 5: Not paused
        not_paused = not self.trading_paused
        debug_info['condition_5_not_paused'] = f"{'✅ PASS' if not_paused else '❌ FAIL'} - VIX Change: {self.vix_918_change:.2f}%"
        
        # Condition 6: No existing position
        no_position = self.current_position is None
        debug_info['condition_6_no_position'] = f"{'✅ PASS' if no_position else '❌ FAIL'}"
        
        # Condition 7: Previous candles valid
        prev_valid = self.validate_previous_candles(df, current_idx, candle_size_threshold)
        debug_info['condition_7_prev_valid'] = f"{'✅ PASS' if prev_valid else '❌ FAIL'}"
        
        # Final result
        all_conditions = (is_green and size_ok and ema_aligned and 
                         open_ema_ok and not_paused and no_position and prev_valid)
        
        result = {
            'signal': all_conditions,
            'entry_price': current['close'],
            'sl_price': current['low'],
            'debug': debug_info if debug else None
        }
        
        return result
    
    def check_exit_conditions(self, df: pd.DataFrame, vix_thresholds: Dict, debug: bool = False) -> Dict:
        """Check exit conditions for current position"""
        if not self.current_position or df.empty:
            return {'exit': False, 'reason': 'No position', 'debug': None}
        
        current = df.iloc[-1]
        debug_info = {
            'timestamp': current.name.strftime('%Y-%m-%d %H:%M:%S'),
            'current_price': current['close'],
            'entry_price': self.entry_price,
            'sl_price': self.sl_price,
            'candle_count': self.candle_count
        }
        
        # Exit condition 1: Stop loss hit
        sl_hit = current['close'] < self.sl_price
        debug_info['exit_1_sl'] = f"{'🔴 YES' if sl_hit else '✅ NO'} - Price: {current['close']:.2f} < SL: {self.sl_price:.2f}"
        
        # Exit condition 2: Large candle
        candle_size = abs(current['close'] - current['open'])
        large_candle = candle_size > vix_thresholds['candle_size_threshold']
        debug_info['exit_2_large_candle'] = f"{'🔴 YES' if large_candle else '✅ NO'} - Size: {candle_size:.2f} > Threshold: {vix_thresholds['candle_size_threshold']}"
        
        # Exit condition 3: EMA40 distance
        ema40_distance = abs(current['close'] - current['ema40'])
        ema40_breach = ema40_distance > vix_thresholds['ema40_distance_threshold']
        debug_info['exit_3_ema40'] = f"{'🔴 YES' if ema40_breach else '✅ NO'} - Distance: {ema40_distance:.2f} > Threshold: {vix_thresholds['ema40_distance_threshold']}"
        
        # Exit condition 4: EMA divergence
        ema_divergence = (current['ema20'] > current['ema40'] and 
                         abs(current['ema20'] - current['ema40']) >= 100)
        debug_info['exit_4_ema_div'] = f"{'🔴 YES' if ema_divergence else '✅ NO'}"
        
        # Exit condition 5: Candle limit
        candle_limit_hit = (vix_thresholds['candle_count_limit'] > 0 and 
                           self.candle_count >= vix_thresholds['candle_count_limit'])
        debug_info['exit_5_candle_limit'] = f"{'🔴 YES' if candle_limit_hit else '✅ NO'} - Count: {self.candle_count}/{vix_thresholds['candle_count_limit']}"
        
        # Exit condition 6: Time limit (20 bars = 60 minutes)
        time_limit_hit = self.candle_count >= 20
        debug_info['exit_6_time_limit'] = f"{'🔴 YES' if time_limit_hit else '✅ NO'} - Count: {self.candle_count}/20"
        
        # Determine exit reason
        exit_needed = False
        exit_reason = ""
        
        if sl_hit:
            exit_needed = True
            exit_reason = "SL Hit"
        elif large_candle:
            exit_needed = True
            exit_reason = "Large Candle"
        elif ema40_breach:
            exit_needed = True
            exit_reason = "EMA40 Distance"
        elif ema_divergence:
            exit_needed = True
            exit_reason = "EMA Divergence"
        elif candle_limit_hit:
            exit_needed = True
            exit_reason = "Candle Limit"
        elif time_limit_hit:
            exit_needed = True
            exit_reason = "Time Limit"
        
        return {
            'exit': exit_needed,
            'reason': exit_reason,
            'exit_price': current['close'],
            'pnl': current['close'] - self.entry_price if exit_needed else 0,
            'debug': debug_info if debug else None
        }

class SensexBigBarBot:
    """Main trading bot class"""
    
    def __init__(self, config_file: str = "config.json"):
        self.logger = logging.getLogger(__name__)
        self.load_config(config_file)
        
        # Initialize components
        self.kite = None  # Will be initialized with access token
        self.telegram = TelegramNotifier(self.config['telegram_token'], self.config['chat_id'])
        self.option_chain = None
        self.strategy = None
        
        # Bot state
        self.is_running = False
        
    def load_config(self, config_file: str):
        """Load configuration from JSON file"""
        try:
            with open(config_file, 'r') as f:
                self.config = json.load(f)
        except FileNotFoundError:
            # Create default config
            self.config = {
                "api_key": null,
                "api_secret": null,
                "telegram_token": "7913084624:AAGvk9-R9YEUf4FGHCwDyOOpGHZOKUHr0mE",
                "chat_id": "7374806646",
                "position_size": 100,
                "lot_size": 10  # Updated for BFO Sensex options
            }
            with open(config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            self.logger.info(f"Created default config file: {config_file}")
    
    def initialize_kite(self, access_token: str):
        """Initialize Kite Connect with access token"""
        try:
            self.kite = KiteConnect(api_key=self.config['api_key'])
            self.kite.set_access_token(access_token)
            
            # Test connection
            profile = self.kite.profile()
            self.logger.info(f"Kite Connect initialized for user: {profile['user_name']}")
            
            # Initialize other components
            self.option_chain = SensexOptionChain(self.kite)
            self.strategy = BigBarStrategy(self.kite)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Kite Connect: {e}")
            return False
    
    def step1_detect_strike_price(self):
        """Step 1: Detect correct strike price"""
        try:
            # Check market hours first
            is_open, reason = TradingHoursValidator.is_market_open()
            if not is_open:
                self.logger.warning(f"Market not open: {reason}")
                return None
            
            sensex_price = self.option_chain.get_sensex_spot_price()
            if sensex_price is None:
                return None
            
            target_strike = self.option_chain.calculate_target_strike(sensex_price)
            
            message = (
                f"🎯 <b>Step 1: Strike Price Detection</b>\n\n"
                f"📊 <b>Sensex Spot:</b> {sensex_price:,.2f}\n"
                f"🎯 <b>Target Strike:</b> {target_strike}\n"
                f"⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}\n"
                f"📅 <b>Session:</b> {'Morning' if datetime.now().time() < time(12, 0) else 'Afternoon'}\n"
                f"🕒 <b>Market Status:</b> {reason}"
            )
            
            self.telegram.send_message(message)
            return target_strike
            
        except Exception as e:
            self.logger.error(f"Error in step 1: {e}")
            return None
    
    def step2_get_weekly_symbols_and_prices(self, target_strike: int):
        """Step 2: Get weekly symbols and their prices"""
        try:
            symbols = self.option_chain.get_weekly_expiry_symbols(target_strike)
            if not symbols:
                message = "❌ <b>No weekly options found for target strike</b>"
                self.telegram.send_message(message)
                return None
            
            prices = self.option_chain.get_option_prices(symbols)
            if not prices:
                message = "❌ <b>Failed to fetch option prices</b>"
                self.telegram.send_message(message)
                return None
            
            message = (
                f"📋 <b>Step 2: Weekly Options Data</b>\n\n"
                f"🎯 <b>Strike:</b> {target_strike}\n"
                f"📅 <b>Expiry:</b> {symbols['expiry']}\n"
                f"🏦 <b>Exchange:</b> BFO (FIXED!)\n"
                f"📊 <b>Lot Size:</b> {symbols['lot_size']}\n\n"
                f"📈 <b>Call Option (CE):</b>\n"
                f"   Symbol: <code>{symbols['ce_symbol']}</code>\n"
                f"   Price: ₹{prices['ce_price']:,.2f}\n\n"
                f"📉 <b>Put Option (PE):</b>\n"
                f"   Symbol: <code>{symbols['pe_symbol']}</code>\n"
                f"   Price: ₹{prices['pe_price']:,.2f}\n\n"
                f"⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"
            )
            
            self.telegram.send_message(message)
            return {'symbols': symbols, 'prices': prices}
            
        except Exception as e:
            self.logger.error(f"Error in step 2: {e}")
            return None
    
    def step3_run_strategy_analysis(self, symbols: Dict):
        """Step 3: Run BigBar strategy analysis"""
        try:
            vix_price = self.option_chain.get_vix_price()
            if vix_price is None:
                message = "❌ <b>Failed to fetch VIX price</b>"
                self.telegram.send_message(message)
                return
            
            # Check VIX pause condition
            self.strategy.check_vix_pause_condition(vix_price)
            
            # Get VIX thresholds
            vix_thresholds = VIXThresholdManager.get_vix_thresholds(vix_price)
            
            # Get historical data for both CE and PE
            today = datetime.now().strftime("%Y-%m-%d")
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            
            ce_df = self.strategy.get_historical_data(symbols['ce_token'], yesterday, today)
            pe_df = self.strategy.get_historical_data(symbols['pe_token'], yesterday, today)
            
            if ce_df.empty or pe_df.empty:
                message = "❌ <b>Failed to fetch historical data</b>"
                self.telegram.send_message(message)
                return
            
            # Analyze both options
            ce_analysis = self.strategy.check_bigbar_entry_conditions(ce_df, vix_thresholds, debug=True)
            pe_analysis = self.strategy.check_bigbar_entry_conditions(pe_df, vix_thresholds, debug=True)
            
            # Check for position exit if exists
            exit_analysis = None
            if self.strategy.current_position:
                if self.strategy.current_position == 'CE':
                    exit_analysis = self.strategy.check_exit_conditions(ce_df, vix_thresholds, debug=True)
                else:
                    exit_analysis = self.strategy.check_exit_conditions(pe_df, vix_thresholds, debug=True)
            
            # Send comprehensive analysis
            self.send_strategy_analysis(vix_price, vix_thresholds, ce_analysis, pe_analysis, exit_analysis)
            
        except Exception as e:
            self.logger.error(f"Error in step 3: {e}")
    
    def send_strategy_analysis(self, vix_price: float, vix_thresholds: Dict, 
                              ce_analysis: Dict, pe_analysis: Dict, exit_analysis: Dict = None):
        """Send detailed strategy analysis to Telegram"""
        try:
            # Header
            message = (
                f"🔍 <b>Step 3: BigBar Strategy Analysis</b>\n\n"
                f"📊 <b>VIX Analysis:</b>\n"
                f"   Current VIX: {vix_price:.2f}\n"
                f"   Candle Threshold: {vix_thresholds['candle_size_threshold']}\n"
                f"   Max Candle Size: {vix_thresholds['max_candle_size']}\n"
                f"   Candle Limit: {vix_thresholds['candle_count_limit']}\n"
                f"   EMA40 Distance: {vix_thresholds['ema40_distance_threshold']}\n\n"
            )
            
            # CE Analysis
            ce_signal = "🟢 ENTRY SIGNAL" if ce_analysis['signal'] else "🔴 NO SIGNAL"
            message += f"📈 <b>CE Analysis:</b> {ce_signal}\n"
            if ce_analysis.get('debug'):
                debug = ce_analysis['debug']
                message += f"   Time: {debug['timestamp']}\n"
                message += f"   {debug['condition_1_green']}\n"
                message += f"   {debug['condition_2_size']}\n"
                message += f"   {debug['condition_3_ema']}\n"
                message += f"   {debug['condition_4_open_ema']}\n"
                message += f"   {debug['condition_5_not_paused']}\n"
                message += f"   {debug['condition_6_no_position']}\n"
                message += f"   {debug['condition_7_prev_valid']}\n\n"
            
            # PE Analysis
            pe_signal = "🟢 ENTRY SIGNAL" if pe_analysis['signal'] else "🔴 NO SIGNAL"
            message += f"📉 <b>PE Analysis:</b> {pe_signal}\n"
            if pe_analysis.get('debug'):
                debug = pe_analysis['debug']
                message += f"   Time: {debug['timestamp']}\n"
                message += f"   {debug['condition_1_green']}\n"
                message += f"   {debug['condition_2_size']}\n"
                message += f"   {debug['condition_3_ema']}\n"
                message += f"   {debug['condition_4_open_ema']}\n"
                message += f"   {debug['condition_5_not_paused']}\n"
                message += f"   {debug['condition_6_no_position']}\n"
                message += f"   {debug['condition_7_prev_valid']}\n\n"
            
            # Position Management
            if ce_analysis['signal'] and pe_analysis['signal']:
                message += "⚠️ <b>DUAL SIGNAL DETECTED - NO TRADING</b>\n\n"
            elif ce_analysis['signal']:
                message += f"✅ <b>CE ENTRY TRIGGERED</b>\n"
                message += f"   Entry Price: ₹{ce_analysis['entry_price']:.2f}\n"
                message += f"   Stop Loss: ₹{ce_analysis['sl_price']:.2f}\n\n"
            elif pe_analysis['signal']:
                message += f"✅ <b>PE ENTRY TRIGGERED</b>\n"
                message += f"   Entry Price: ₹{pe_analysis['entry_price']:.2f}\n"
                message += f"   Stop Loss: ₹{pe_analysis['sl_price']:.2f}\n\n"
            else:
                message += "⏳ <b>NO ENTRY SIGNALS - WAITING</b>\n\n"
            
            # Exit Analysis (if position exists)
            if exit_analysis:
                exit_status = "🔴 EXIT SIGNAL" if exit_analysis['exit'] else "✅ HOLD POSITION"
                message += f"🚪 <b>Exit Analysis:</b> {exit_status}\n"
                if exit_analysis.get('debug'):
                    debug = exit_analysis['debug']
                    message += f"   Current Price: ₹{debug['current_price']:.2f}\n"
                    message += f"   Entry Price: ₹{debug['entry_price']:.2f}\n"
                    message += f"   {debug['exit_1_sl']}\n"
                    message += f"   {debug['exit_2_large_candle']}\n"
                    message += f"   {debug['exit_3_ema40']}\n"
                    message += f"   {debug['exit_4_ema_div']}\n"
                    message += f"   {debug['exit_5_candle_limit']}\n"
                    message += f"   {debug['exit_6_time_limit']}\n\n"
                
                if exit_analysis['exit']:
                    pnl = exit_analysis['pnl']
                    pnl_emoji = "💚" if pnl > 0 else "❤️"
                    message += f"   {pnl_emoji} P&L: ₹{pnl:.2f}\n"
                    message += f"   Reason: {exit_analysis['reason']}\n\n"
            
            message += f"⏰ <b>Analysis Time:</b> {datetime.now().strftime('%H:%M:%S')}"
            
            # Split message if too long
            if len(message) > 4000:
                messages = [message[i:i+4000] for i in range(0, len(message), 4000)]
                for msg in messages:
                    self.telegram.send_message(msg)
            else:
                self.telegram.send_message(message)
                
        except Exception as e:
            self.logger.error(f"Error sending strategy analysis: {e}")
    
    def debug_specific_conditions(self, strike: int, option_type: str, 
                                 target_date: str, target_time: str):
        """Debug specific conditions for given parameters"""
        try:
            self.logger.info(f"Debug mode: Strike={strike}, Type={option_type}, Date={target_date}, Time={target_time}")
            
            # Get symbols for the strike
            symbols = self.option_chain.get_weekly_expiry_symbols(strike)
            if not symbols:
                message = f"❌ <b>No options found for strike {strike}</b>"
                self.telegram.send_message(message)
                return
            
            # Get historical data
            token = symbols['ce_token'] if option_type == 'CE' else symbols['pe_token']
            symbol = symbols['ce_symbol'] if option_type == 'CE' else symbols['pe_symbol']
            
            df = self.strategy.get_historical_data(token, target_date, target_date)
            if df.empty:
                message = f"❌ <b>No data found for {symbol} on {target_date}</b>"
                self.telegram.send_message(message)
                return
            
            # Find specific time
            target_datetime = pd.to_datetime(f"{target_date} {target_time}")
            closest_idx = df.index.get_indexer([target_datetime], method='nearest')[0]
            
            if closest_idx == -1:
                message = f"❌ <b>No data found for time {target_time}</b>"
                self.telegram.send_message(message)
                return
            
            # Get VIX thresholds (use current VIX if available)
            vix_price = self.option_chain.get_vix_price() or 15.0  # Default to 15 if unavailable
            vix_thresholds = VIXThresholdManager.get_vix_thresholds(vix_price)
            
            # Analyze conditions for that specific time
            df_subset = df.iloc[:closest_idx+1]  # Include data up to target time
            analysis = self.strategy.check_bigbar_entry_conditions(df_subset, vix_thresholds, debug=True)
            
            # Send debug analysis
            message = (
                f"🐛 <b>Debug Analysis</b>\n\n"
                f"🎯 <b>Parameters:</b>\n"
                f"   Strike: {strike}\n"
                f"   Option: {option_type}\n"
                f"   Symbol: <code>{symbol}</code>\n"
                f"   Exchange: BFO (FIXED!)\n"
                f"   Date: {target_date}\n"
                f"   Time: {target_time}\n\n"
                f"📊 <b>VIX Thresholds:</b>\n"
                f"   VIX: {vix_price:.2f}\n"
                f"   Min Candle: {vix_thresholds['candle_size_threshold']}\n"
                f"   Max Candle: {vix_thresholds['max_candle_size']}\n\n"
            )
            
            if analysis.get('debug'):
                debug = analysis['debug']
                result = "🟢 MATCH" if analysis['signal'] else "🔴 NO MATCH"
                message += f"🔍 <b>Condition Analysis:</b> {result}\n\n"
                message += f"   📊 Data: O={debug['open']:.2f}, C={debug['close']:.2f}\n"
                message += f"   📈 EMAs: 20={debug['ema20']:.2f}, 40={debug['ema40']:.2f}\n\n"
                message += f"   1️⃣ {debug['condition_1_green']}\n"
                message += f"   2️⃣ {debug['condition_2_size']}\n"
                message += f"   3️⃣ {debug['condition_3_ema']}\n"
                message += f"   4️⃣ {debug['condition_4_open_ema']}\n"
                message += f"   5️⃣ {debug['condition_5_not_paused']}\n"
                message += f"   6️⃣ {debug['condition_6_no_position']}\n"
                message += f"   7️⃣ {debug['condition_7_prev_valid']}\n"
            
            self.telegram.send_message(message)
            
        except Exception as e:
            self.logger.error(f"Error in debug mode: {e}")
            message = f"❌ <b>Debug Error:</b> {str(e)}"
            self.telegram.send_message(message)
    
    def run_3min_cycle(self):
        """Run the 3-minute trading cycle"""
        try:
            self.logger.info("Starting 3-minute trading cycle")
            
            # Check if market is open
            is_open, reason = TradingHoursValidator.is_market_open()
            if not is_open:
                self.logger.info(f"Skipping cycle: {reason}")
                return
            
            # Step 1: Detect strike price
            target_strike = self.step1_detect_strike_price()
            if target_strike is None:
                return
            
            # Step 2: Get symbols and prices
            option_data = self.step2_get_weekly_symbols_and_prices(target_strike)
            if option_data is None:
                return
            
            # Step 3: Run strategy analysis
            self.step3_run_strategy_analysis(option_data['symbols'])
            
        except Exception as e:
            self.logger.error(f"Error in 3-minute cycle: {e}")
            message = f"❌ <b>Trading Cycle Error:</b> {str(e)}"
            self.telegram.send_message(message)
    
    def start_trading(self):
        """Start automated trading"""
        if not self.kite:
            self.logger.error("Kite Connect not initialized")
            return
        
        # Check if market is open
        is_open, reason = TradingHoursValidator.is_market_open()
        if not is_open:
            self.logger.warning(f"Cannot start trading: {reason}")
            message = f"⏰ <b>Trading Not Started</b>\n\n{reason}\n\nBot will start when market opens."
            self.telegram.send_message(message)
            
            # Wait for market to open
            while not TradingHoursValidator.is_market_open()[0]:
                time_module.sleep(300)  # Check every 5 minutes
        
        self.is_running = True
        
        # Send startup message
        message = (
            f"🚀 <b>Sensex BigBar Bot Started (BFO Fixed!)</b>\n\n"
            f"📊 <b>Configuration:</b>\n"
            f"   Position Size: {self.config['position_size']} quantity\n"
            f"   Lot Size: {self.config['lot_size']}\n"
            f"   Exchange: BFO (Sensex Options)\n"
            f"   Analysis Frequency: Every 3 minutes\n\n"
            f"⏰ <b>Trading Hours:</b> 9:15 AM - 3:30 PM\n"
            f"🎯 <b>Strategy:</b> BigBar Entry Logic Only\n\n"
            f"📱 <b>Status:</b> Monitoring market conditions...\n"
            f"🕒 <b>Market Status:</b> {TradingHoursValidator.is_market_open()[1]}"
        )
        self.telegram.send_message(message)
        
        # Schedule 3-minute cycles
        schedule.every(3).minutes.do(self.run_3min_cycle)
        
        # Run initial cycle
        self.run_3min_cycle()
        
        # Main loop
        while self.is_running:
            # Check if market is still open
            is_open, reason = TradingHoursValidator.is_market_open()
            if not is_open:
                self.logger.info(f"Market closed: {reason}")
                self.stop_trading()
                break
            
            schedule.run_pending()
            time_module.sleep(10)  # Check every 10 seconds
    
    def stop_trading(self):
        """Stop automated trading"""
        self.is_running = False
        schedule.clear()
        
        message = (
            f"🛑 <b>Sensex BigBar Bot Stopped</b>\n\n"
            f"⏰ <b>Stop Time:</b> {datetime.now().strftime('%H:%M:%S')}\n"
            f"📊 <b>Session Summary:</b> Trading session ended\n"
            f"🕒 <b>Market Status:</b> {TradingHoursValidator.is_market_open()[1]}"
        )
        self.telegram.send_message(message)

def main():
    """Main function to run the bot"""
    parser = argparse.ArgumentParser(description='Sensex BigBar Trading Bot - BFO Exchange Fixed')
    parser.add_argument('--mode', choices=['test', 'debug', 'live'], default='test',
                       help='Bot mode: test (steps 1-3), debug (specific analysis), live (automated trading)')
    parser.add_argument('--access-token', required=True, help='Kite Connect access token')
    parser.add_argument('--strike', type=int, help='Strike price for debug mode')
    parser.add_argument('--option-type', choices=['CE', 'PE'], help='Option type for debug mode')
    parser.add_argument('--date', help='Date for debug mode (YYYY-MM-DD)')
    parser.add_argument('--time', help='Time for debug mode (HH:MM)')
    
    args = parser.parse_args()
    
    # Initialize bot
    bot = SensexBigBarBot()
    
    # Initialize Kite Connect
    if not bot.initialize_kite(args.access_token):
        print("Failed to initialize Kite Connect. Exiting.")
        return
    
    try:
        if args.mode == 'test':
            print("Running test mode - Steps 1, 2, 3...")
            bot.run_3min_cycle()
            
        elif args.mode == 'debug':
            if not all([args.strike, args.option_type, args.date, args.time]):
                print("Debug mode requires: --strike, --option-type, --date, --time")
                return
            
            print(f"Running debug mode for {args.option_type} {args.strike} on {args.date} at {args.time}")
            bot.debug_specific_conditions(args.strike, args.option_type, args.date, args.time)
            
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
