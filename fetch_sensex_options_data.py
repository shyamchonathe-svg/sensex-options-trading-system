#!/usr/bin/env python3
"""
Fetch Sensex Option 3-Minute Data for ATM ±500 Strikes
Saves data locally for use in debug mode of sensex_trading_bot.py
"""

import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
from kiteconnect import KiteConnect
import logging
import json
import os
import argparse
from typing import Dict, Optional
import pytz
import time as time_module

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('fetch_sensex_option_data.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SensexOptionDataFetcher:
    def __init__(self, config_file: str = "config.json"):
        self.load_config(config_file)
        self.kite = None
        self.ist = pytz.timezone('Asia/Kolkata')
        self.instrument_cache = {}  # Cache for instrument tokens

    def load_config(self, config_file: str):
        """Load configuration from config.json"""
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
            logger.info(f"Created default config file: {config_file}")

    def initialize_kite(self, access_token: str) -> bool:
        """Initialize Kite Connect API"""
        try:
            self.kite = KiteConnect(api_key=self.config['api_key'])
            self.kite.set_access_token(access_token)
            profile = self.kite.profile()
            logger.info(f"Kite Connect initialized for user: {profile['user_name']}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Kite Connect: {e}")
            return False

    def get_instrument_token(self, symbol: str) -> Optional[str]:
        """Fetch instrument token for a given symbol"""
        try:
            if symbol in self.instrument_cache:
                logger.info(f"Using cached token for {symbol}: {self.instrument_cache[symbol]}")
                return self.instrument_cache[symbol]
            
            exchange = "BFO" if symbol.startswith("SENSEX") else "BSE"
            instruments = self.kite.instruments(exchange)
            for inst in instruments:
                if inst['tradingsymbol'] == symbol:
                    self.instrument_cache[symbol] = inst['instrument_token']
                    logger.info(f"Found instrument token for {symbol}: {inst['instrument_token']}")
                    return inst['instrument_token']
            
            logger.error(f"No instrument token found for {symbol}")
            return None
        except Exception as e:
            logger.error(f"Error fetching instrument token for {symbol}: {e}")
            return None

    def get_historical_data(self, instrument_token: str, from_date: str, to_date: str, interval: str = "3minute") -> pd.DataFrame:
        """Fetch historical data with 10 and 20 EMAs"""
        if not instrument_token:
            logger.error("Invalid instrument token provided")
            return pd.DataFrame()
        try:
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval=interval
            )
            if not isinstance(data, list):
                logger.error(f"Invalid historical data response for token {instrument_token}: {data}")
                return pd.DataFrame()
            df = pd.DataFrame(data)
            if not df.empty:
                # Check if 'date' is already timezone-aware
                if pd.to_datetime(df['date']).dt.tz is None:
                    df['timestamp'] = pd.to_datetime(df['date']).dt.tz_localize(self.ist)
                else:
                    df['timestamp'] = pd.to_datetime(df['date']).dt.tz_convert(self.ist)
                df.set_index('timestamp', inplace=True)
                df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
                df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
                logger.info(f"Fetched {len(df)} 3-minute candles for token {instrument_token}")
            else:
                logger.warning(f"No historical data returned for token {instrument_token}")
            return df
        except Exception as e:
            logger.error(f"Error fetching historical data for token {instrument_token}: {e}")
            return pd.DataFrame()

    def load_weekly_options(self, weekly_db_file: str = "sensex_weekly_options.json") -> Dict:
        """Load weekly options database"""
        try:
            if not os.path.exists(weekly_db_file):
                logger.error(f"Weekly options database file not found: {weekly_db_file}")
                return {}
            with open(weekly_db_file, 'r') as f:
                data = json.load(f)
            if not isinstance(data, dict) or 'weekly_expiries' not in data:
                logger.error(f"Invalid format in {weekly_db_file}: 'weekly_expiries' key missing")
                return {}
            logger.info(f"Loaded weekly options database with expiries: {list(data['weekly_expiries'].keys())}")
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding {weekly_db_file}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error loading weekly options database: {e}")
            return {}

    def get_option_symbols(self, strike: int, expiry_date: str, weekly_db: Dict) -> Optional[Dict]:
        """Get CE and PE symbols for a given strike and expiry"""
        if not weekly_db:
            logger.error("Weekly options database is empty")
            return None
        expiry_str = expiry_date
        if expiry_str not in weekly_db.get('weekly_expiries', {}):
            logger.error(f"Expiry {expiry_date} not found in weekly options database")
            return None
        expiry_data = weekly_db['weekly_expiries'][expiry_str]
        strike_str = str(strike)
        if strike_str not in expiry_data.get('strikes', {}):
            logger.error(f"No options found for strike {strike} on expiry {expiry_date}")
            return None
        strike_data = expiry_data['strikes'][strike_str]
        return {
            'ce_symbol': strike_data['ce_symbol'],
            'pe_symbol': strike_data['pe_symbol'],
            'strike': strike,
            'expiry': expiry_str,
            'lot_size': strike_data['lot_size']
        }

    def fetch_option_data(self, date: str, atm_strike: int, expiry_date: str, output_dir: str = "option_data"):
        """Fetch and save 3-minute data for ATM ±500 strikes"""
        try:
            weekly_db = self.load_weekly_options()
            if not weekly_db:
                logger.error("Cannot proceed: Weekly options database is empty or invalid")
                return

            # Create output directory
            os.makedirs(output_dir, exist_ok=True)

            # Get strikes: ATM ±500 in 100-point increments
            strikes = list(range(atm_strike - 500, atm_strike + 600, 100))
            logger.info(f"Fetching data for strikes: {strikes}")
            for strike in strikes:
                symbols = self.get_option_symbols(strike, expiry_date, weekly_db)
                if not symbols:
                    logger.warning(f"Skipping strike {strike}: No symbols found")
                    continue
                ce_token = self.get_instrument_token(symbols['ce_symbol'])
                pe_token = self.get_instrument_token(symbols['pe_symbol'])
                if not ce_token or not pe_token:
                    logger.warning(f"Skipping strike {strike}: CE or PE token not found")
                    continue
                ce_df = self.get_historical_data(ce_token, date, date)
                time_module.sleep(0.5)  # Respect rate limit (3 req/s)
                pe_df = self.get_historical_data(pe_token, date, date)
                time_module.sleep(0.5)  # Respect rate limit
                if not ce_df.empty:
                    ce_df = ce_df.between_time("09:15", "15:30")
                    ce_file = os.path.join(output_dir, f"{symbols['ce_symbol']}_{date}.csv")
                    ce_df.to_csv(ce_file)
                    logger.info(f"Saved CE data for strike {strike} to {ce_file} ({len(ce_df)} candles)")
                else:
                    logger.warning(f"No CE data for strike {strike}")
                if not pe_df.empty:
                    pe_df = pe_df.between_time("09:15", "15:30")
                    pe_file = os.path.join(output_dir, f"{symbols['pe_symbol']}_{date}.csv")
                    pe_df.to_csv(pe_file)
                    logger.info(f"Saved PE data for strike {strike} to {pe_file} ({len(pe_df)} candles)")
                else:
                    logger.warning(f"No PE data for strike {strike}")
        except Exception as e:
            logger.error(f"Error fetching option data: {e}")

def main():
    parser = argparse.ArgumentParser(description='Fetch Sensex Option 3-Minute Data for ATM ±500 Strikes')
    parser.add_argument('--access-token', required=True, help='Kite Connect access token')
    parser.add_argument('--date', required=True, help='Date to fetch data for (YYYY-MM-DD)')
    parser.add_argument('--atm-strike', type=int, help='ATM strike price (optional)')
    parser.add_argument('--expiry-date', required=True, help='Expiry date (YYYY-MM-DD)')
    parser.add_argument('--output-dir', default="option_data", help='Directory to save CSV files (default: option_data)')
    args = parser.parse_args()

    fetcher = SensexOptionDataFetcher()
    if not fetcher.initialize_kite(args.access_token):
        print("Failed to initialize Kite Connect. Exiting.")
        return

    atm_strike = args.atm_strike or 80800  # Default to 80800 if not provided
    fetcher.fetch_option_data(args.date, atm_strike, args.expiry_date, args.output_dir)
    print(f"Data fetching complete. Check {args.output_dir} for CSV files.")

if __name__ == "__main__":
    main()
