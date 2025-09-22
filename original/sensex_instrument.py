#!/usr/bin/env python3
"""
Sensex Instrument Data Fetcher - SECURE VERSION
Fetches and caches instrument data and historical OHLC data for Sensex and options
Generated on: 2025-09-06 10:30:00
SECURITY: No hardcoded credentials
"""

import pandas as pd
import os
import logging
from kiteconnect import KiteConnect
import argparse
import pytz
from datetime import datetime
from config_manager import SecureConfigManager as ConfigManager


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('fetch_sensex_instruments.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class SensexInstrument:
    def __init__(self, access_token: str, cache_dir: str = "instrument_cache"):
        # Load secure configuration
        config_manager = ConfigManager()
        config = config_manager.get_config()
        
        # Initialize KiteConnect with secure credentials
        self.kite = KiteConnect(api_key=config['api_key'])
        self.kite.set_access_token(access_token)
        
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        logger.info("KiteConnect initialized with secure configuration")

    def load_cached_instruments(self, exchange: str) -> pd.DataFrame:
        """Load cached instruments from CSV"""
        cache_file = os.path.join(self.cache_dir, f"instruments_{exchange.lower()}.csv")
        if os.path.exists(cache_file):
            try:
                df = pd.read_csv(cache_file)
                logger.info(f"Loaded {len(df)} instruments from {cache_file}")
                return df
            except Exception as e:
                logger.error(f"Error loading cached instruments: {e}")
                return pd.DataFrame()
        return pd.DataFrame()

    def save_instruments_cache(self, instruments: list, exchange: str):
        """Save instruments to cache file"""
        cache_file = os.path.join(self.cache_dir, f"instruments_{exchange.lower()}.csv")
        try:
            df = pd.DataFrame(instruments)
            df.to_csv(cache_file, index=False)
            logger.info(f"Cached {len(instruments)} instruments to {cache_file}")
        except Exception as e:
            logger.error(f"Error saving instruments cache: {e}")

    def get_instrument_token(self, exchange: str, symbol: str) -> str:
        """Get instrument token with caching"""
        # Try cache first
        cached_instruments = self.load_cached_instruments(exchange)
        if not cached_instruments.empty:
            instrument = cached_instruments[cached_instruments['tradingsymbol'] == symbol]
            if not instrument.empty:
                token = str(instrument.iloc[0]['instrument_token'])
                logger.info(f"Using cached token for {symbol}: {token}")
                return token
        
        # Fetch from API if not cached
        try:
            logger.info(f"Fetching instruments for {exchange}...")
            instruments = self.kite.instruments(exchange)
            self.save_instruments_cache(instruments, exchange)
            
            for inst in instruments:
                if inst['tradingsymbol'] == symbol:
                    token = str(inst['instrument_token'])
                    logger.info(f"Found instrument token for {symbol}: {token}")
                    print(f"Instrument token for {symbol}: {token}")  # Keep console output
                    return token
                    
        except Exception as e:
            logger.error(f"Error fetching instruments for {exchange}: {e}", exc_info=True)
        
        logger.error(f"No instrument token found for {symbol}")
        return ""

    def fetch_historical_data(self, instrument_token: str, symbol: str, 
                            from_date: str, to_date: str, output_dir: str):
        """Fetch and save historical data with EMAs"""
        try:
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval="3minute"
            )
            
            if not data:
                logger.error(f"No historical data returned for {symbol}")
                return
            
            df = pd.DataFrame(data)
            if df.empty:
                logger.error(f"Empty historical data for {symbol}")
                return
            
            # Handle timezone-aware timestamps
            if hasattr(df['date'].iloc[0], 'tzinfo') and df['date'].iloc[0].tzinfo is None:
                df['timestamp'] = pd.to_datetime(df['date']).dt.tz_localize('Asia/Kolkata')
            else:
                df['timestamp'] = pd.to_datetime(df['date']).dt.tz_convert('Asia/Kolkata')
            
            df = df.drop(columns=['date'])
            df.set_index('timestamp', inplace=True)
            
            # Calculate EMAs
            df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
            df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
            
            # Create output directory
            os.makedirs(output_dir, exist_ok=True)
            output_file = os.path.join(output_dir, f"{symbol.replace(':', '_')}_{to_date}.csv")
            df.to_csv(output_file)
            
            logger.info(f"Saved {len(df)} candles to {output_file}")
            print(f"Saved historical data to {output_file}: {len(df)} candles")
            
        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}", exc_info=True)


def main():
    """Main function with secure configuration"""
    parser = argparse.ArgumentParser(description='Sensex Instrument Data Fetcher')
    parser.add_argument('--access-token', required=True, help='Kite Connect access token')
    parser.add_argument('--exchange', required=True, help='Exchange (e.g., BSE, BFO)')
    parser.add_argument('--symbol', required=True, help='Trading symbol (e.g., BSE:SENSEX, SENSEX2591180500CE)')
    parser.add_argument('--fetch-data', action='store_true', help='Fetch historical data')
    parser.add_argument('--from-date', help='From date (YYYY-MM-DD)')
    parser.add_argument('--to-date', help='To date (YYYY-MM-DD)')
    parser.add_argument('--output-dir', default="option_data", help='Output directory for historical data')
    args = parser.parse_args()

    try:
        # Initialize with secure config
        instrument = SensexInstrument(args.access_token)
        
        # Get token
        token = instrument.get_instrument_token(args.exchange, args.symbol)
        if not token:
            logger.error(f"Could not find instrument token for {args.symbol}")
            return

        print(f"🎯 Instrument Token: {token}")

        # Fetch historical data if requested
        if args.fetch_data:
            if not args.from_date or not args.to_date:
                logger.error("Both --from-date and --to-date are required for fetching historical data")
                return
            instrument.fetch_historical_data(token, args.symbol, args.from_date, args.to_date, args.output_dir)
            print(f"📊 Historical data saved to {args.output_dir}")

    except Exception as e:
        logger.error(f"System error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
