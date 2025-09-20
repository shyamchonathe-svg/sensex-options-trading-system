#!/usr/bin/env python3
"""
Bot Controller - Orchestrates trading bot operations
Manages trading sessions, health monitoring, and notifications
"""

import asyncio
import logging
from typing import Optional
from datetime import datetime
import pytz
from config_manager import SecureConfigManager as ConfigManager
from data_manager import DataManager
from notification_service import NotificationService
from health_monitor import HealthMonitor
from database_layer import DatabaseLayer
from trading_service import TradingService
from enums import TradingMode


class BotController:
    def __init__(self, config_manager: ConfigManager, data_manager: DataManager,
                 trading_service: TradingService, notification_service: NotificationService,
                 health_monitor: HealthMonitor, database_layer: DatabaseLayer,
                 logger: logging.Logger):
        self.config_manager = config_manager
        self.data_manager = data_manager
        self.trading_service = trading_service
        self.notification_service = notification_service
        self.health_monitor = health_monitor
        self.database_layer = database_layer
        self.logger = logger
        self.running = False
        self.config = config_manager.get_config()
        self.logger.info("BotController initialized")

    async def start(self, mode: str, force: bool = False):
        """
        Start the trading bot
        
        Args:
            mode: Trading mode (live, test, bot)
            force: Force start even if market is closed
        """
        try:
            self.running = True
            self.logger.info(f"Starting BotController in {mode} mode (force: {force})")
            
            # Validate market hours unless forced
            if not force and not self._is_market_open():
                self.logger.error("Market is closed, use --force to start anyway")
                await self.notification_service.send_message("❌ Market is closed")
                return
            
            # Start notification service
            await self.notification_service.start_bot()
            
            # Start trading service
            await self.trading_service.start_session(TradingMode(mode))
            
            # Start health monitoring
            asyncio.create_task(self.health_monitor.monitor_system())
            
            self.logger.info("BotController started successfully")
            
        except Exception as e:
            self.logger.error(f"Error starting BotController: {e}")
            await self.notification_service.send_message(f"❌ BotController error: {str(e)[:200]}")
            raise

    async def stop(self):
        """Stop the trading bot"""
        try:
            self.running = False
            await self.trading_service.stop_session()
            await self.notification_service.stop_bot()
            self.logger.info("BotController stopped")
        except Exception as e:
            self.logger.error(f"Error stopping BotController: {e}")
            await self.notification_service.send_message(f"❌ BotController stop error: {str(e)[:200]}")

    def _is_market_open(self) -> bool:
        """
        Check if market is open (9:15 AM to 3:30 PM IST, excluding holidays)
        
        Returns:
            True if market is open
        """
        try:
            now = datetime.now(pytz.timezone('Asia/Kolkata'))
            market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
            market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
            is_weekday = now.weekday() < 5  # Monday to Friday
            is_within_hours = market_open.time() <= now.time() <= market_close.time()
            is_holiday = now.strftime('%Y-%m-%d') in self.config.get('market_holidays', [])
            return is_weekday and is_within_hours and not is_holiday
        except Exception as e:
            self.logger.error(f"Error checking market hours: {e}")
            return False
