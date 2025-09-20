#!/usr/bin/env python3
"""
Integrated End-to-End Trading System
Orchestrates trading bot components with async notifications
"""

import argparse
import asyncio
import logging
import sys
import signal
import os
from datetime import datetime
import pytz

from config_manager import SecureConfigManager as ConfigManager
from data_manager import DataManager
from broker_adapter import BrokerAdapter
from notification_service import NotificationService
from health_monitor import HealthMonitor
from database_layer import DatabaseLayer
from bot_controller import BotController
from trading_service import TradingService
from enums import TradingMode


async def main():
    """Main function to run the trading bot"""
    # Initialize logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s IST - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/trading_system.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting trading bot initialization")

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Sensex Trading Bot")
    parser.add_argument("--mode", choices=["live", "test", "bot"], default="test",
                        help="Trading mode: live, test, or bot")
    parser.add_argument("--force", action="store_true",
                        help="Force start even if market is closed")
    parser.add_argument("--data-dir", default="option_data",
                        help="Directory for market data")
    parser.add_argument("--expiry-date", default=None,
                        help="Expiry date for options (YYYY-MM-DD)")
    args = parser.parse_args()

    # Initialize config manager
    config_manager = ConfigManager()
    config = config_manager.get_config()
    
    # Update config with command-line arguments
    config['mode'] = args.mode
    config['data_dir'] = args.data_dir
    if args.expiry_date:
        config['expiry_date'] = args.expiry_date

    # Initialize notification service
    notification_service = NotificationService(
        telegram_token=config['telegram_token'],
        chat_id=config['chat_id'],
        logger=logger
    )
    try:
        # Initialize core components
        data_manager = DataManager(config_manager)
        database_layer = DatabaseLayer(db_path="trades.db")
        broker = BrokerAdapter(config_manager, logger, notification_service)
        health_monitor = HealthMonitor(config_manager, data_manager, logger, notification_service)
        trading_service = TradingService(
            data_manager=data_manager,
            broker_adapter=broker,
            notification_service=notification_service,
            config=config,
            database_layer=database_layer
        )
        
        # Initialize bot controller
        bot_controller = BotController(
            config_manager=config_manager,
            data_manager=data_manager,
            trading_service=trading_service,
            notification_service=notification_service,
            health_monitor=health_monitor,
            database_layer=database_layer,
            logger=logger
        )
        
        # Start trading bot
        logger.info(f"Starting trading bot in {args.mode} mode (force: {args.force})")
        await notification_service.send_message(
            f"🚀 BotController started: {args.mode.capitalize()} mode, 3min data"
        )
        
        # Run bot controller
        await bot_controller.start(args.mode, args.force)
        
        logger.info(f"Trading bot initialized with BotController for {config['instruments']}")
        
        # Keep the bot running until interrupted
        logger.info("System running in %s mode. Press Ctrl+C to stop.", args.mode)
        try:
            while True:
                await asyncio.sleep(60)  # Keep main loop alive
        except asyncio.CancelledError:
            logger.info("Received shutdown signal")
            await bot_controller.stop()
            await notification_service.send_message("🛑 BotController stopped")
        
    except Exception as e:
        logger.error(f"System error: {e}", exc_info=True)
        try:
            await notification_service.send_message(f"❌ System error: {str(e)[:200]}")
        except Exception as notify_error:
            logger.error(f"Failed to send error notification: {notify_error}")
        raise

def signal_handler(sig, frame):
    """Handle SIGINT (Ctrl+C) and SIGTERM"""
    logger = logging.getLogger(__name__)
    logger.info("Shutdown signal received")
    raise asyncio.CancelledError

if __name__ == "__main__":
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Set timezone to IST
    os.environ['TZ'] = 'Asia/Kolkata'
    try:
        import time
        time.tzset()
    except AttributeError:
        pass  # tzset not available on all platforms
    
    # Run the main async function
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        logging.getLogger(__name__).info("Main program terminated")
