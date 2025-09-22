#!/usr/bin/env python3
"""
Data Manager - Handles market data for trading bot
Supports multiple instruments and WebSocket/CSV data sources
"""

import pandas as pd
import os
from typing import Dict, Optional
from datetime import datetime, timedelta
import logging
from kiteconnect import KiteTicker
from config_manager import SecureConfigManager as ConfigManager
import pytz


class DataManager:
    def __init__(self, config_manager: ConfigManager):
        self.logger = logging.getLogger(__name__)
        self.config_manager = config_manager
        self.config = config_manager.get_config()
        self.data_dir = self.config.get('data_dir', 'option_data')
        os.makedirs(self.data_dir, exist_ok=True)
        self.instruments = self.config.get('instruments', ['SENSEX'])
        self.latest_data: Dict[str, pd.DataFrame] = {}
        self.kite_ticker = None
        self.logger.info("DataManager initialized")

    def is_data_fresh(self, threshold_seconds: int = 300) -> bool:
        """
        Check if market data is fresh within the given threshold
        
        Args:
            threshold_seconds: Maximum age of data in seconds
            
        Returns:
            True if data is fresh for all instruments
        """
        try:
            current_time = datetime.now(pytz.timezone('Asia/Kolkata'))
            for instrument in self.instruments:
                data = self.latest_data.get(instrument)
                if data is None or data.empty:
                    self.logger.warning(f"No data for {instrument}")
                    return False
                last_timestamp = pd.to_datetime(data.index[-1])
                if (current_time - last_timestamp).total_seconds() > threshold_seconds:
                    self.logger.warning(f"Stale data for {instrument}: {last_timestamp}")
                    return False
            return True
        except Exception as e:
            self.logger.error(f"Error checking data freshness: {e}")
            return False

    def initialize_websocket(self):
        """Initialize KiteTicker WebSocket"""
        try:
            self.kite_ticker = KiteTicker(
                api_key=self.config.get('api_key'),
                access_token=self.config.get('access_token')
            )
            self.logger.info("WebSocket initialized")
        except Exception as e:
            self.logger.error(f"Error initializing WebSocket: {e}")
