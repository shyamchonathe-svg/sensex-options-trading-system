#!/usr/bin/env python3
"""
Broker Adapter - Infrastructure Layer for Sensex Trading Bot
Wraps Kite Connect API with error handling, retry logic, and caching
"""

from kiteconnect import KiteConnect
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import pandas as pd
import logging
from dataclasses import dataclass
from enum import Enum
import time
import pytz
from pathlib import Path
import json


class OrderStatus(Enum):
    """Order status enumeration"""
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OrderType(Enum):
    """Order type enumeration"""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


@dataclass
class InstrumentInfo:
    """Instrument information"""
    instrument_token: str
    exchange_token: str
    tradingsymbol: str
    name: str
    last_price: float
    expiry: datetime = None
    strike: float = 0.0
    lot_size: int = 1
    tick_size: float = 0.05
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'instrument_token': self.instrument_token,
            'tradingsymbol': self.tradingsymbol,
            'name': self.name,
            'last_price': self.last_price,
            'expiry': self.expiry.isoformat() if self.expiry else None,
            'strike': self.strike,
            'lot_size': self.lot_size,
            'tick_size': self.tick_size
        }


@dataclass
class OrderResult:
    """Order execution result"""
    order_id: str
    status: OrderStatus
    message: str
    data: Dict[str, Any] = None
    
    def is_success(self) -> bool:
        return self.status in [OrderStatus.COMPLETE, OrderStatus.OPEN, OrderStatus.PENDING]


class BrokerAdapter:
    """
    Broker adapter that wraps Kite Connect API with enhanced functionality
    """
    
    def __init__(self, api_key: str, api_secret: str, config: Dict[str, Any] = None):
        """
        Initialize broker adapter
        
        Args:
            api_key: Kite Connect API key
            api_secret: Kite Connect API secret
            config: Broker configuration
        """
        self.logger = logging.getLogger(__name__)
        self.api_key = api_key
        self.api_secret = api_secret
        self.config = config or {}
        
        # Initialize Kite Connect
        self.kite = KiteConnect(api_key=api_key)
        self.access_token = None
        self.user_profile = None
        
        # Configuration
        self.timeout = self.config.get('api_timeout', 30)
        self.max_retries = self.config.get('max_retries', 3)
        self.retry_delay = self.config.get('retry_delay', 1)
        self.sandbox_mode = self.config.get('sandbox_mode', False)
        
        # Caching
        self.instruments_cache = {}
        self.instruments_cache_expiry = None
        self.quotes_cache = {}
        self.quotes_cache_expiry = {}
        self.cache_duration_minutes = self.config.get('cache_duration_minutes', 5)
        
        # Rate limiting
        self.last_api_call = {}
        self.min_api_interval = self.config.get('min_api_interval_ms', 100) / 1000.0
        
        self.logger.info(f"BrokerAdapter initialized with API key: ...{api_key[-8:]}")
    
    def set_access_token(self, access_token: str) -> bool:
        """
        Set access token and validate connection
        
        Args:
            access_token: Kite Connect access token
            
        Returns:
            True if token set successfully
        """
        try:
            self.access_token = access_token
            self.kite.set_access_token(access_token)
            
            # Validate by fetching profile
            self.user_profile = self._execute_api_call('profile')
            if self.user_profile:
                self.logger.info(f"Access token validated for user: {self.user_profile.get('user_name', 'Unknown')}")
                return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to set access token: {e}")
            return False
    
    def _execute_api_call(self, method: str, *args, **kwargs) -> Any:
        """
        Execute Kite API call with retry logic and rate limiting
        
        Args:
            method: Kite method name
            *args, **kwargs: Method arguments
            
        Returns:
            API response or None if failed
        """
        if not self.access_token:
            raise Exception("Access token not set")
        
        # Rate limiting
        now = time.time()
        last_call = self.last_api_call.get(method, 0)
        if now - last_call < self.min_api_interval:
            sleep_time = self.min_api_interval - (now - last_call)
            time.sleep(sleep_time)
        
        # Execute with retries
        for attempt in range(self.max_retries):
            try:
                # Get the method from kite object
                kite_method = getattr(self.kite, method)
                result = kite_method(*args, **kwargs)
                
                self.last_api_call[method] = time.time()
                self.logger.debug(f"API call successful: {method}")
                return result
                
            except Exception as e:
                self.logger.warning(f"API call failed (attempt {attempt + 1}/{self.max_retries}): {method} - {e}")
                
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2 ** attempt)  # Exponential backoff
                    time.sleep(delay)
                else:
                    self.logger.error(f"API call failed after {self.max_retries} attempts: {method}")
                    raise e
        
        return None
    
    def get_instruments(self, exchange: str = "BFO", force_refresh: bool = False) -> List[InstrumentInfo]:
        """
        Get instruments list with caching
        
        Args:
            exchange: Exchange code (BFO, NSE, BSE)
            force_refresh: Force refresh cache
            
        Returns:
            List of instrument information
        """
        cache_key = f"instruments_{exchange}"
        now = datetime.now()
        
        # Check cache
        if not force_refresh and cache_key in self.instruments_cache:
            if self.instruments_cache_expiry and now < self.instruments_cache_expiry:
                self.logger.debug(f"Using cached instruments for {exchange}")
                return self.instruments_cache[cache_key]
        
        try:
            # Fetch from API
            raw_instruments = self._execute_api_call('instruments', exchange)
            
            instruments = []
            for inst in raw_instruments:
                # Convert to InstrumentInfo
                expiry = None
                if inst.get('expiry'):
                    try:
                        expiry = datetime.strptime(inst['expiry'], '%Y-%m-%d')
                    except (ValueError, TypeError):
                        pass
                
                instrument = InstrumentInfo(
                    instrument_token=str(inst['instrument_token']),
                    exchange_token=str(inst['exchange_token']),
                    tradingsymbol=inst['tradingsymbol'],
                    name=inst['name'],
                    last_price=float(inst.get('last_price', 0)),
                    expiry=expiry,
                    strike=float(inst.get('strike', 0)),
                    lot_size=int(inst.get('lot_size', 1)),
                    tick_size=float(inst.get('tick_size', 0.05))
                )
                instruments.append(instrument)
            
            # Update cache
            self.instruments_cache[cache_key] = instruments
            self.instruments_cache_expiry = now + timedelta(hours=1)  # Cache for 1 hour
            
            self.logger.info(f"Loaded {len(instruments)} instruments for {exchange}")
            return instruments
            
        except Exception as e:
            self.logger.error(f"Failed to get instruments for {exchange}: {e}")
            # Return cached data if available
            return self.instruments_cache.get(cache_key, [])
    
    def find_instrument(self, symbol: str, exchange: str = "BFO") -> Optional[InstrumentInfo]:
        """
        Find instrument by trading symbol
        
        Args:
            symbol: Trading symbol to search for
            exchange: Exchange to search in
            
        Returns:
            InstrumentInfo or None if not found
        """
        try:
            instruments = self.get_instruments(exchange)
            
            for inst in instruments:
                if inst.tradingsymbol == symbol:
                    return inst
                    
            self.logger.warning(f"Instrument not found: {symbol} in {exchange}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error finding instrument {symbol}: {e}")
            return None
    
    def get_quote(self, instrument_token: str, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """
        Get live quote for instrument
        
        Args:
            instrument_token: Instrument token
            use_cache: Whether to use cached data
            
        Returns:
            Quote data or None
        """
        now = datetime.now()
        
        # Check cache
        if use_cache and instrument_token in self.quotes_cache:
            cache_entry = self.quotes_cache[instrument_token]
            cache_time = self.quotes_cache_expiry.get(instrument_token, datetime.min)
            
            if now < cache_time:
                self.logger.debug(f"Using cached quote for {instrument_token}")
                return cache_entry
        
        try:
            # Fetch from API
            quotes = self._execute_api_call('quote', [instrument_token])
            
            if quotes and instrument_token in quotes:
                quote_data = quotes[instrument_token]
                
                # Update cache
                self.quotes_cache[instrument_token] = quote_data
                self.quotes_cache_expiry[instrument_token] = now + timedelta(minutes=self.cache_duration_minutes)
                
                return quote_data
            
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to get quote for {instrument_token}: {e}")
            return None
    
    def get_historical_data(self, instrument_token: str, from_date: str, to_date: str, 
                          interval: str = "3minute") -> Optional[pd.DataFrame]:
        """
        Get historical OHLCV data
        
        Args:
            instrument_token: Instrument token
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            interval: Data interval
            
        Returns:
            DataFrame with OHLCV data or None
        """
        try:
            # Convert dates
            from_dt = datetime.strptime(from_date, '%Y-%m-%d')
            to_dt = datetime.strptime(to_date, '%Y-%m-%d')
            
            # Fetch data
            data = self._execute_api_call(
                'historical_data',
                instrument_token=int(instrument_token),
                from_date=from_dt,
                to_date=to_dt,
                interval=interval
            )
            
            if not data:
                return None
            
            # Convert to DataFrame
            df = pd.DataFrame(data)
            if not df.empty:
                df['timestamp'] = pd.to_datetime(df['date']).dt.tz_localize(pytz.timezone('Asia/Kolkata'))
                df.drop(columns=['date'], inplace=True, errors='ignore')
                df.set_index('timestamp', inplace=True)
                
                self.logger.debug(f"Retrieved {len(df)} historical records for {instrument_token}")
            
            return df
            
        except Exception as e:
            self.logger.error(f"Failed to get historical data for {instrument_token}: {e}")
            return None
    
    def place_order(self, symbol: str, transaction_type: str, quantity: int,
                   product: str = "MIS", order_type: str = "MARKET", 
                   price: float = None, trigger_price: float = None,
                   validity: str = "DAY", disclosed_quantity: int = 0) -> OrderResult:
        """
        Place order
        
        Args:
            symbol: Trading symbol
            transaction_type: BUY or SELL
            quantity: Order quantity
            product: Product type (MIS, CNC, NRML)
            order_type: Order type (MARKET, LIMIT, etc.)
            price: Limit price (for limit orders)
            trigger_price: Trigger price (for SL orders)
            validity: Order validity
            disclosed_quantity: Disclosed quantity
            
        Returns:
            OrderResult with execution details
        """
        if self.sandbox_mode:
            # Return mock order result for testing
            return OrderResult(
                order_id=f"TEST_{int(time.time())}",
                status=OrderStatus.COMPLETE,
                message="Test order executed successfully",
                data={
                    'symbol': symbol,
                    'transaction_type': transaction_type,
                    'quantity': quantity,
                    'product': product,
                    'order_type': order_type
                }
            )
        
        try:
            order_params = {
                'tradingsymbol': symbol,
                'exchange': 'BFO',  # Assuming BFO for options
                'transaction_type': transaction_type,
                'quantity': quantity,
                'product': product,
                'order_type': order_type,
                'validity': validity
            }
            
            if price is not None:
                order_params['price'] = price
            if trigger_price is not None:
                order_params['trigger_price'] = trigger_price
            if disclosed_quantity > 0:
                order_params['disclosed_quantity'] = disclosed_quantity
            
            # Place order
            result = self._execute_api_call('place_order', **order_params)
            
            if result:
                return OrderResult(
                    order_id=result['order_id'],
                    status=OrderStatus.PENDING,
                    message="Order placed successfully",
                    data=order_params
                )
            else:
                return OrderResult(
                    order_id="",
                    status=OrderStatus.REJECTED,
                    message="Failed to place order"
                )
                
        except Exception as e:
            self.logger.error(f"Failed to place order: {e}")
            return OrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                message=f"Order placement failed: {e}"
            )
    
    def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Get order status
        
        Args:
            order_id: Order ID
            
        Returns:
            Order status data
        """
        try:
            orders = self._execute_api_call('orders')
            
            if orders:
                for order in orders:
                    if order.get('order_id') == order_id:
                        return order
            
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to get order status for {order_id}: {e}")
            return None
    
    def get_positions(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get current positions
        
        Returns:
            Dictionary with day and net positions
        """
        try:
            if self.sandbox_mode:
                return {'day': [], 'net': []}
            
            positions = self._execute_api_call('positions')
            return positions or {'day': [], 'net': []}
            
        except Exception as e:
            self.logger.error(f"Failed to get positions: {e}")
            return {'day': [], 'net': []}
    
    def get_margins(self) -> Dict[str, Any]:
        """
        Get account margins
        
        Returns:
            Margin data
        """
        try:
            if self.sandbox_mode:
                return {
                    'equity': {'available': {'cash': 100000}},
                    'commodity': {'available': {'cash': 0}}
                }
            
            margins = self._execute_api_call('margins')
            return margins or {}
            
        except Exception as e:
            self.logger.error(f"Failed to get margins: {e}")
            return {}
    
    def get_sensex_spot_price(self) -> Optional[float]:
        """
        Get current Sensex spot price
        
        Returns:
            Sensex price or None
        """
        try:
            # Find Sensex instrument
            sensex_inst = self.find_instrument("SENSEX", "BSE")
            if not sensex_inst:
                return None
            
            # Get quote
            quote = self.get_quote(sensex_inst.instrument_token)
            if quote:
                return float(quote.get('last_price', 0))
            
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to get Sensex price: {e}")
            return None
    
    def get_weekly_expiry_date(self, base_date: str = None) -> Optional[str]:
        """
        Get next weekly expiry date for options
        
        Args:
            base_date: Base date (YYYY-MM-DD), uses today if None
            
        Returns:
            Weekly expiry date or None
        """
        try:
            if base_date:
                target_date = datetime.strptime(base_date, '%Y-%m-%d')
            else:
                target_date = datetime.now(pytz.timezone('Asia/Kolkata'))
            
            # Find next Thursday (weekly expiry)
            days_until_thursday = (3 - target_date.weekday()) % 7
            if days_until_thursday == 0 and target_date.time() > time(15, 30):
                # If today is Thursday and market closed, get next Thursday
                days_until_thursday = 7
            
            expiry_date = target_date + timedelta(days=days_until_thursday)
            return expiry_date.strftime('%Y-%m-%d')
            
        except Exception as e:
            self.logger.error(f"Failed to get weekly expiry date: {e}")
            return None
    
    def construct_option_symbol(self, strike: int, option_type: str, expiry_date: str = None) -> Optional[str]:
        """
        Construct option trading symbol
        
        Args:
            strike: Strike price
            option_type: CE or PE
            expiry_date: Expiry date (YYYY-MM-DD), uses weekly if None
            
        Returns:
            Option symbol or None
        """
        try:
            if not expiry_date:
                expiry_date = self.get_weekly_expiry_date()
                if not expiry_date:
                    return None
            
            # Parse expiry date
            expiry_dt = datetime.strptime(expiry_date, '%Y-%m-%d')
            
            # Format: SENSEX{YY}{M}{DD}{STRIKE}{CE/PE}
            expiry_str = f"{expiry_dt.strftime('%y')}{expiry_dt.month}{expiry_dt.day:02d}"
            symbol = f"SENSEX{expiry_str}{strike}{option_type}"
            
            self.logger.debug(f"Constructed option symbol: {symbol}")
            return symbol
            
        except Exception as e:
            self.logger.error(f"Failed to construct option symbol: {e}")
            return None
    
    def get_option_chain(self, base_strike: int, strike_range: int = 500) -> Dict[int, Dict[str, Any]]:
        """
        Get option chain data for strike range
        
        Args:
            base_strike: Base strike price (typically ATM)
            strike_range: Range around base strike
            
        Returns:
            Dictionary with option chain data
        """
        try:
            option_chain = {}
            expiry_date = self.get_weekly_expiry_date()
            
            if not expiry_date:
                self.logger.error("Could not determine expiry date")
                return {}
            
            # Generate strike prices
            strikes = list(range(base_strike - strike_range, base_strike + strike_range + 100, 100))
            
            for strike in strikes:
                try:
                    # Construct symbols
                    ce_symbol = self.construct_option_symbol(strike, "CE", expiry_date)
                    pe_symbol = self.construct_option_symbol(strike, "PE", expiry_date)
                    
                    if not ce_symbol or not pe_symbol:
                        continue
                    
                    # Find instruments
                    ce_inst = self.find_instrument(ce_symbol, "BFO")
                    pe_inst = self.find_instrument(pe_symbol, "BFO")
                    
                    if not ce_inst or not pe_inst:
                        self.logger.debug(f"Option instruments not found for strike {strike}")
                        continue
                    
                    # Get quotes
                    ce_quote = self.get_quote(ce_inst.instrument_token)
                    pe_quote = self.get_quote(pe_inst.instrument_token)
                    
                    option_chain[strike] = {
                        'strike': strike,
                        'expiry': expiry_date,
                        'ce': {
                            'symbol': ce_symbol,
                            'instrument_token': ce_inst.instrument_token,
                            'last_price': ce_quote.get('last_price', 0) if ce_quote else 0,
                            'volume': ce_quote.get('volume', 0) if ce_quote else 0,
                            'oi': ce_quote.get('oi', 0) if ce_quote else 0,
                            'lot_size': ce_inst.lot_size
                        },
                        'pe': {
                            'symbol': pe_symbol,
                            'instrument_token': pe_inst.instrument_token,
                            'last_price': pe_quote.get('last_price', 0) if pe_quote else 0,
                            'volume': pe_quote.get('volume', 0) if pe_quote else 0,
                            'oi': pe_quote.get('oi', 0) if pe_quote else 0,
                            'lot_size': pe_inst.lot_size
                        }
                    }
                    
                except Exception as e:
                    self.logger.warning(f"Failed to process strike {strike}: {e}")
                    continue
            
            self.logger.info(f"Retrieved option chain for {len(option_chain)} strikes")
            return option_chain
            
        except Exception as e:
            self.logger.error(f"Failed to get option chain: {e}")
            return {}
    
    def save_instruments_cache(self, file_path: str = "instruments_cache.json") -> bool:
        """
        Save instruments cache to file
        
        Args:
            file_path: Cache file path
            
        Returns:
            True if saved successfully
        """
        try:
            cache_data = {
                'cache_expiry': self.instruments_cache_expiry.isoformat() if self.instruments_cache_expiry else None,
                'instruments': {}
            }
            
            for cache_key, instruments in self.instruments_cache.items():
                cache_data['instruments'][cache_key] = [inst.to_dict() for inst in instruments]
            
            with open(file_path, 'w') as f:
                json.dump(cache_data, f, indent=2, default=str)
            
            self.logger.info(f"Instruments cache saved to {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to save instruments cache: {e}")
            return False
    
    def load_instruments_cache(self, file_path: str = "instruments_cache.json") -> bool:
        """
        Load instruments cache from file
        
        Args:
            file_path: Cache file path
            
        Returns:
            True if loaded successfully
        """
        try:
            cache_file = Path(file_path)
            if not cache_file.exists():
                return False
            
            with open(file_path, 'r') as f:
                cache_data = json.load(f)
            
            # Check if cache is still valid
            if cache_data.get('cache_expiry'):
                expiry = datetime.fromisoformat(cache_data['cache_expiry'])
                if datetime.now() > expiry:
                    self.logger.info("Cached instruments expired")
                    return False
            
            # Load instruments
            self.instruments_cache = {}
            for cache_key, inst_list in cache_data.get('instruments', {}).items():
                instruments = []
                for inst_data in inst_list:
                    # Reconstruct InstrumentInfo objects
                    expiry = None
                    if inst_data.get('expiry'):
                        expiry = datetime.fromisoformat(inst_data['expiry'])
                    
                    instrument = InstrumentInfo(
                        instrument_token=inst_data['instrument_token'],
                        exchange_token=inst_data.get('exchange_token', ''),
                        tradingsymbol=inst_data['tradingsymbol'],
                        name=inst_data['name'],
                        last_price=inst_data['last_price'],
                        expiry=expiry,
                        strike=inst_data.get('strike', 0),
                        lot_size=inst_data.get('lot_size', 1),
                        tick_size=inst_data.get('tick_size', 0.05)
                    )
                    instruments.append(instrument)
                
                self.instruments_cache[cache_key] = instruments
            
            if cache_data.get('cache_expiry'):
                self.instruments_cache_expiry = datetime.fromisoformat(cache_data['cache_expiry'])
            
            self.logger.info(f"Instruments cache loaded from {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to load instruments cache: {e}")
            return False
    
    def validate_connection(self) -> Dict[str, Any]:
        """
        Validate broker connection and return status
        
        Returns:
            Connection validation results
        """
        result = {
            'connected': False,
            'user_profile': None,
            'margins_available': False,
            'instruments_loaded': False,
            'api_responsive': False,
            'errors': []
        }
        
        try:
            # Check if access token is set
            if not self.access_token:
                result['errors'].append("Access token not set")
                return result
            
            # Test API responsiveness
            try:
                profile = self._execute_api_call('profile')
                if profile:
                    result['api_responsive'] = True
                    result['user_profile'] = profile
                    result['connected'] = True
                else:
                    result['errors'].append("Failed to fetch user profile")
            except Exception as e:
                result['errors'].append(f"API call failed: {e}")
            
            # Test margins
            try:
                margins = self.get_margins()
                if margins:
                    result['margins_available'] = True
            except Exception as e:
                result['errors'].append(f"Failed to fetch margins: {e}")
            
            # Test instruments
            try:
                instruments = self.get_instruments("BFO")
                if instruments:
                    result['instruments_loaded'] = True
                    result['instrument_count'] = len(instruments)
            except Exception as e:
                result['errors'].append(f"Failed to fetch instruments: {e}")
            
        except Exception as e:
            result['errors'].append(f"Connection validation error: {e}")
        
        return result
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """Get connection statistics"""
        return {
            'api_key_length': len(self.api_key) if self.api_key else 0,
            'access_token_set': bool(self.access_token),
            'sandbox_mode': self.sandbox_mode,
            'max_retries': self.max_retries,
            'timeout': self.timeout,
            'cache_stats': {
                'instruments_cached': len(self.instruments_cache),
                'quotes_cached': len(self.quotes_cache),
                'cache_expiry': self.instruments_cache_expiry.isoformat() if self.instruments_cache_expiry else None
            },
            'rate_limiting': {
                'min_interval_ms': self.min_api_interval * 1000,
                'last_calls': {k: v for k, v in list(self.last_api_call.items())[-5:]}  # Last 5 calls
            }
        }
    
    def cleanup_cache(self) -> None:
        """Clean up expired cache entries"""
        now = datetime.now()
        
        # Clean up quotes cache
        expired_quotes = []
        for token, expiry_time in self.quotes_cache_expiry.items():
            if now > expiry_time:
                expired_quotes.append(token)
        
        for token in expired_quotes:
            self.quotes_cache.pop(token, None)
            self.quotes_cache_expiry.pop(token, None)
        
        # Clean up instruments cache if expired
        if self.instruments_cache_expiry and now > self.instruments_cache_expiry:
            self.instruments_cache.clear()
            self.instruments_cache_expiry = None
        
        if expired_quotes or not self.instruments_cache:
            self.logger.debug(f"Cache cleanup: removed {len(expired_quotes)} expired quotes, instruments cache {'cleared' if not self.instruments_cache else 'retained'}")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources"""
        self.cleanup_cache()
