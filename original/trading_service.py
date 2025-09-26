#!/usr/bin/env python3
"""
Trading Service - Manages trading sessions and position execution
Phase 2: Supports test mode, SEBI compliance, and notifications
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import pytz
from config_manager import SecureConfigManager as ConfigManager
from utils.data_manager import DataManager
from broker_adapter import BrokerAdapter
from notification_service import NotificationService
from database_layer import DatabaseLayer
from enums import TradingMode


class TradingService:
    def __init__(self, data_manager: DataManager, broker_adapter: BrokerAdapter,
                 notification_service: NotificationService, config: Dict[str, Any],
                 database_layer: DatabaseLayer):
        self.data_manager = data_manager
        self.broker_adapter = broker_adapter
        self.notification_service = notification_service
        self.config = config
        self.database_layer = database_layer
        self.logger = logging.getLogger(__name__)
        self.current_session = None
        self.mode = TradingMode(config.get('mode', 'test'))
        self.logger.info(f"TradingService initialized in {self.mode.value} mode")

    async def start_session(self, mode: TradingMode):
        """Start a new trading session."""
        try:
            self.mode = mode
            session_date = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d')
            self.current_session = {
                'date': session_date,
                'start_time': datetime.now(pytz.timezone('Asia/Kolkata')),
                'sensex_entry_price': 0.0,  # Placeholder; update with actual data
                'positions_opened': 0,
                'positions_closed': 0,
                'total_pnl': 0.0,
                'total_signals': 0
            }
            self.database_layer.save_session(self.current_session)
            await self.notification_service.send_session_start(self.current_session, self.mode)
            self.logger.info(f"Trading session started for {session_date}")
        except Exception as e:
            self.logger.error(f"Error starting trading session: {e}")
            await self.notification_service.send_message(f"❌ Trading session error: {str(e)[:200]}")
            raise

    async def stop_session(self):
        """Stop the current trading session."""
        try:
            if self.current_session:
                self.current_session['end_time'] = datetime.now(pytz.timezone('Asia/Kolkata'))
                duration = self.current_session['end_time'] - self.current_session['start_time']
                summary = {
                    'date': self.current_session['date'],
                    'duration': duration,
                    'total_signals': self.current_session['total_signals'],
                    'positions_opened': self.current_session['positions_opened'],
                    'positions_closed': self.current_session['positions_closed'],
                    'total_pnl': self.current_session['total_pnl'],
                    'success_rate': (self.current_session['positions_closed'] / max(self.current_session['positions_opened'], 1)) * 100
                }
                self.database_layer.update_session(self.current_session)
                await self.notification_service.send_session_end(self.current_session, summary)
                self.logger.info(f"Trading session ended: {summary}")
                self.current_session = None
        except Exception as e:
            self.logger.error(f"Error stopping trading session: {e}")
            await self.notification_service.send_message(f"❌ Trading session stop error: {str(e)[:200]}")

    async def execute_trade(self, signal: Dict[str, Any]):
        """Execute a trade based on a signal (placeholder)."""
        try:
            if self.mode == TradingMode.TEST:
                self.logger.info(f"Test mode: Simulating trade for signal {signal}")
                position = {
                    'symbol': signal.get('instrument', 'SENSEX'),
                    'strike': signal.get('strike', 0),
                    'entry_price': signal.get('price', 0.0),
                    'quantity': self.config.get('lot_size', 20),
                    'entry_time': datetime.now(pytz.timezone('Asia/Kolkata')),
                    'metadata': {'test_mode': True}
                }
                self.database_layer.save_position(position)
                self.current_session['positions_opened'] += 1
                await self.notification_service.send_position_opened(position, self.mode)
        except Exception as e:
            self.logger.error(f"Error executing trade: {e}")
            await self.notification_service.send_message(f"❌ Trade execution error: {str(e)[:200]}")
