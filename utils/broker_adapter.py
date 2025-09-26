#!/usr/bin/env python3
"""
Broker Adapter - Interface to KiteConnect API for trading
Handles order placement and market data
"""

import logging
from typing import Dict, Any, Optional
from kiteconnect import KiteConnect
from utils.secure_config_manager import SecureConfigManager as ConfigManager


class BrokerAdapter:
    """KiteConnect API wrapper for trading operations"""
    
    def __init__(self, config_manager: ConfigManager, logger: logging.Logger, notification_service):
        """
        Initialize Broker Adapter
        
        Args:
            config_manager: Configuration manager instance
            logger: Logger instance
            notification_service: Notification service for alerts
        """
        self.logger = logger
        self.config = config_manager.get_all()
        self.notification_service = notification_service
        self.kite = KiteConnect(
            api_key=self.config.get('api_key'),
            access_token=self.config.get('access_token')
        )
        self.logger.info("BrokerAdapter initialized")

    def place_order(self, instrument: str, quantity: int, price: float,
                    order_type: str = "MARKET", transaction_type: str = "BUY") -> Optional[Dict[str, Any]]:
        """
        Place an order via KiteConnect
        
        Args:
            instrument: Trading instrument
            quantity: Order quantity
            price: Order price
            order_type: MARKET or LIMIT
            transaction_type: BUY or SELL
            
        Returns:
            Order details or None if failed
        """
        try:
            order_params = {
                "tradingsymbol": instrument,
                "exchange": "BSE",
                "quantity": quantity,
                "order_type": order_type,
                "transaction_type": transaction_type,
                "product": "MIS",
                "variety": "regular"
            }
            if order_type == "LIMIT":
                order_params["price"] = price

            order_id = self.kite.place_order(**order_params)
            order_details = {"order_id": order_id, "instrument": instrument, "quantity": quantity}
            
            self.logger.info(f"Order placed: {transaction_type} {quantity} {instrument} @ {price}")
            if self.notification_service:
                asyncio.run(self.notification_service.send_message(
                    f"📝 Order placed: {transaction_type} {quantity} {instrument} @ {price}"
                ))
            return order_details
            
        except Exception as e:
            self.logger.error(f"Error placing order for {instrument}: {e}")
            if self.notification_service:
                asyncio.run(self.notification_service.send_message(
                    f"❌ Order failed for {instrument}: {str(e)[:200]}"
                ))
            return None

    def get_current_price(self, instrument: str) -> Optional[float]:
        """
        Get current market price for an instrument
        
        Args:
            instrument: Trading instrument
            
        Returns:
            Current price or None if failed
        """
        try:
            quote = self.kite.quote(instrument)
            price = quote[instrument]["last_price"]
            return price
        except Exception as e:
            self.logger.error(f"Error fetching price for {instrument}: {e}")
            return None
