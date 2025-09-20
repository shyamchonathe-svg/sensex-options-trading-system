#!/usr/bin/env python3
"""
Optimized Sensex Option Chain
Handles option chain data fetching and symbol generation for Sensex options, and Sensex spot price retrieval
Generated on: 2025-09-06
"""

from kiteconnect import KiteConnect
import logging
import pandas as pd
from datetime import datetime, timedelta
import pytz
from typing import Dict, Optional, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('sensex_option_chain.log'),
        logging.StreamHandler()
    ]
)

class OptimizedSensexOptionChain:
    """Handles Sensex option chain data and symbol generation, and Sensex spot price retrieval"""
    def __init__(self, kite: KiteConnect, expiry_date: str = None):
        self.kite = kite
        self.logger = logging.getLogger(__name__)
        self.expiry_date = expiry_date if expiry_date else self.get_nearest_expiry()
        self.instruments_cache = None
        self.logger.info(f"Initialized OptimizedSensexOptionChain with expiry_date: {self.expiry_date}")

    def get_nearest_expiry(self) -> str:
        """Returns the nearest weekly expiry date (Thursday) in YYYY-MM-DD format"""
        try:
            ist = pytz.timezone('Asia/Kolkata')
            today = datetime.now(ist).date()
            days_to_thursday = (3 - today.weekday() + 7) % 7
            if days_to_thursday == 0:
                days_to_thursday = 7
            next_thursday = today + timedelta(days=days_to_thursday)
            expiry_str = next_thursday.strftime("%Y-%m-%d")
            self.logger.info(f"Calculated nearest expiry: {expiry_str}")
            return expiry_str
        except Exception as e:
            self.logger.error(f"Error calculating nearest expiry: {e}", exc_info=True)
            default_expiry = datetime.now(ist).strftime("%Y-%m-%d")
            self.logger.warning(f"Returning default expiry: {default_expiry}")
            return default_expiry

    def get_sensex_spot_price(self, historical_date: str = None) -> Optional[float]:
        """Fetches the current or historical Sensex spot price"""
        try:
            sensex_symbol = "BSE:SENSEX"
            sensex_token = self.get_instrument_token(sensex_symbol)
            if not sensex_token:
                self.logger.error("Failed to fetch Sensex instrument token")
                return None
            if historical_date:
                try:
                    from_date = historical_date
                    to_date = historical_date
                    data = self.kite.historical_data(
                        instrument_token=sensex_token,
                        from_date=from_date,
                        to_date=to_date,
                        interval="day"
                    )
                    if data and len(data) > 0:
                        price = data[-1]['close']
                        self.logger.info(f"Fetched historical Sensex price for {historical_date}: {price}")
                        return price
                    self.logger.error(f"No historical data for Sensex on {historical_date}")
                    return None
                except Exception as e:
                    self.logger.error(f"Error fetching historical Sensex price for {historical_date}: {e}", exc_info=True)
                    return None
            else:
                quote = self.kite.quote([sensex_symbol])
                if quote and sensex_symbol in quote:
                    price = quote[sensex_symbol]['last_price']
                    self.logger.info(f"Fetched current Sensex price: {price}")
                    return price
                self.logger.error(f"No quote data for {sensex_symbol}")
                return None
        except Exception as e:
            self.logger.error(f"Error fetching Sensex spot price: {e}", exc_info=True)
            return None

    def get_instrument_token(self, symbol: str) -> Optional[str]:
        """Fetches instrument token for a given symbol"""
        try:
            if not self.instruments_cache:
                self.instruments_cache = []
                # Load BSE instruments for Sensex
                try:
                    self.instruments_cache.extend(self.kite.instruments("BSE"))
                    self.logger.info("Loaded BSE instruments")
                except Exception as e:
                    self.logger.error(f"Error fetching BSE instruments: {e}", exc_info=True)
                # Load BFO instruments for options
                try:
                    self.instruments_cache.extend(self.kite.instruments("BFO"))
                    self.logger.info("Loaded BFO instruments")
                except Exception as e:
                    self.logger.error(f"Error fetching BFO instruments: {e}", exc_info=True)
            symbol_clean = symbol.replace("BSE:", "").replace("BFO:", "")
            for inst in self.instruments_cache:
                if inst['tradingsymbol'] == symbol_clean:
                    self.logger.info(f"Found instrument token for {symbol}: {inst['instrument_token']}")
                    return inst['instrument_token']
            self.logger.error(f"No instrument found for symbol: {symbol}")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching instrument token for {symbol}: {e}", exc_info=True)
            return None

    def get_weekly_expiry_symbols(self, strike: int) -> Dict:
        """Fetches CE and PE symbols for a given strike and weekly expiry"""
        try:
            expiry_date = datetime.strptime(self.expiry_date, "%Y-%m-%d").date()
            expiry_str = expiry_date.strftime("%y%m%d")
            ce_symbol = f"SENSEX{expiry_str}{strike}CE"
            pe_symbol = f"SENSEX{expiry_str}{strike}PE"
            ce_token = self.get_instrument_token(f"BFO:{ce_symbol}")
            pe_token = self.get_instrument_token(f"BFO:{pe_symbol}")
            if not ce_token or not pe_token:
                self.logger.error(f"No instruments found for strike {strike} and expiry {self.expiry_date}")
                return {'error': f'No instruments found for strike {strike}'}
            result = {
                'ce_symbol': ce_symbol,
                'pe_symbol': pe_symbol,
                'strike': strike,
                'expiry': self.expiry_date,
                'lot_size': self.instruments_cache[0].get('lot_size', 20)
            }
            self.logger.info(f"Generated symbols for strike {strike}: CE={ce_symbol}, PE={pe_symbol}")
            return result
        except Exception as e:
            self.logger.error(f"Error fetching symbols for strike {strike}: {e}", exc_info=True)
            return {'error': str(e)}

    def get_symbol_for_strike(self, expiry_date: str, strike: int, option_type: str) -> Optional[str]:
        """Generates the trading symbol for a specific strike and option type"""
        try:
            expiry = datetime.strptime(expiry_date, "%Y-%m-%d").date()
            expiry_str = expiry.strftime("%y%m%d")
            symbol = f"SENSEX{expiry_str}{strike}{option_type}"
            token = self.get_instrument_token(f"BFO:{symbol}")
            if not token:
                self.logger.error(f"No instrument found for symbol: {symbol}")
                return None
            self.logger.info(f"Generated symbol: {symbol} for strike {strike}, type {option_type}, expiry {expiry_date}")
            return symbol
        except Exception as e:
            self.logger.error(f"Error generating symbol for strike {strike} {option_type}: {e}", exc_info=True)
            return None

    def get_option_prices(self, symbols: Dict) -> Dict:
        """Fetches current prices for CE and PE symbols"""
        try:
            tokens = [
                f"BFO:{symbols['ce_symbol']}",
                f"BFO:{symbols['pe_symbol']}"
            ]
            quotes = self.kite.quote(tokens)
            ce_price = quotes.get(f"BFO:{symbols['ce_symbol']}")['last_price'] if quotes.get(f"BFO:{symbols['ce_symbol']}") else None
            pe_price = quotes.get(f"BFO:{symbols['pe_symbol']}")['last_price'] if quotes.get(f"BFO:{symbols['pe_symbol']}") else None
            if ce_price is None or pe_price is None:
                self.logger.error(f"Failed to fetch prices for {symbols['ce_symbol']} or {symbols['pe_symbol']}")
                return {'error': f'Failed to fetch option prices for {symbols["ce_symbol"]} or {symbols["pe_symbol"]}'}
            result = {
                'ce_price': ce_price,
                'pe_price': pe_price,
                'strike': symbols['strike'],
                'expiry': symbols['expiry']
            }
            self.logger.info(f"Fetched option prices: CE={ce_price}, PE={pe_price} for strike {symbols['strike']}")
            return result
        except Exception as e:
            self.logger.error(f"Error fetching option prices: {e}", exc_info=True)
            return {'error': str(e)}
