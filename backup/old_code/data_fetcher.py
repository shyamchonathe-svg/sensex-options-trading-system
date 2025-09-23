"""
Reliable data fetching with retry logic and error handling
"""
import pandas as pd
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from kiteconnect import KiteConnect
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import pytz

from config_loader import ConfigLoader

logger = logging.getLogger(__name__)

class DataFetcher:
    """Fetches market data with robust error handling and retries"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.kite = KiteConnect(api_key=config['ZAPI_KEY'])
        
        # Set timezone for IST
        self.ist = pytz.timezone('Asia/Kolkata')
        
        # Set access token if available (should be generated separately)
        access_token = os.getenv('ACCESS_TOKEN')
        if access_token:
            self.kite.set_access_token(access_token)
            logger.info("Access token set")
        else:
            logger.warning("No access token provided - login required")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def fetch_historical_data(self, instrument_token: int, days_back: int = 5) -> Optional[pd.DataFrame]:
        """Fetch historical OHLC data with retry logic"""
        try:
            # Calculate date range
            end_date = datetime.now(self.ist).date()
            start_date = end_date - timedelta(days=days_back)
            
            start_str = start_date.strftime('%Y-%m-%d')
            end_str = end_date.strftime('%Y-%m-%d')
            
            logger.debug(f"Fetching historical data from {start_str} to {end_str}")
            
            # Fetch data
            raw_data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=start_str,
                to_date=end_str,
                interval=self.config['interval']
            )
            
            if not raw_data:
                logger.warning("No historical data returned")
                return None
            
            # Convert to DataFrame
            df = pd.DataFrame(raw_data)
            if df.empty:
                logger.warning("Empty DataFrame returned")
                return None
            
            # Process data
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
            
            # Remove any rows with NaN values
            df = df.dropna()
            
            # Ensure minimum data points
            if len(df) < self.config['ema_long']:
                logger.warning(f"Insufficient data: {len(df)} bars, need {self.config['ema_long']}")
                return None
            
            logger.info(f"Fetched {len(df)} bars of historical data")
            return df
            
        except Exception as e:
            logger.error(f"Historical data fetch failed after retries: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=5),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def fetch_options_chain(self) -> Optional[Dict[str, Any]]:
        """Fetch current options chain data"""
        try:
            # This is a placeholder - implement based on your options data needs
            # For now, return mock data for compatibility
            logger.debug("Fetching options chain (mock data for now)")
            
            # In production, you'd fetch actual options chain via Kite API
            # For now, return structure compatible with strategy
            mock_chain = {
                'calls': [
                    {'strike': 80000, 'last_price': 150.0, 'impliedVolatility': 25.0},
                    {'strike': 80500, 'last_price': 100.0, 'impliedVolatility': 28.0}
                ],
                'puts': [
                    {'strike': 80000, 'last_price': 120.0, 'impliedVolatility': 26.0},
                    {'strike': 79500, 'last_price': 180.0, 'impliedVolatility': 30.0}
                ]
            }
            
            return mock_chain
            
        except Exception as e:
            logger.error(f"Options chain fetch failed: {e}")
            # Return None to skip trading rather than crash
            return None
    
    def is_market_open(self) -> bool:
        """Check if market is currently open"""
        now = datetime.now(self.ist)
        current_time = now.time()
        current_day = now.weekday()
        
        # Market hours: 9:15 AM to 3:30 PM, Mon-Fri
        market_open = datetime.strptime('09:15', '%H:%M').time()
        market_close = datetime.strptime('15:30', '%H:%M').time()
        
        is_weekday = current_day < 5  # 0-4 = Mon-Fri
        is_market_time = market_open <= current_time <= market_close
        
        return is_weekday and is_market_time
    
    def get_current_spot(self, df: pd.DataFrame) -> Optional[float]:
        """Get current spot price from DataFrame"""
        if df is None or df.empty:
            return None
        
        return float(df['close'].iloc[-1])
