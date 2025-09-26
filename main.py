#!/usr/bin/env python3
"""
Main script for Sensex Options Trading System
Orchestrates debug, test, and live modes with secure logging
"""
import argparse
import logging
import logging.handlers
import threading
import asyncio
from datetime import datetime
import pytz

try:
    from utils.secure_config_manager import SecureConfigManager
    from telegram_handler import TelegramBotHandler  # Use our simple telegram handler
    from utils.health_monitor import HealthMonitor
    from utils.data_manager import DataManager
    from integrated_e2e_trading_system import TradingSystem
    from utils.zipper import Zipper
    from utils.notification_service import NotificationService
    from utils.trading_service import TradingService
    from utils.broker_adapter import BrokerAdapter
    from utils.database_layer import DatabaseLayer
    from utils.enums import TradingMode
    from sensex_trading_bot_debug import SensexTradingBot as DebugBot
    from sensex_trading_bot_live import SensexTradingBot as LiveBot
    from notifications import send_telegram_message  # Use our simple notifications
except ImportError as e:
    logging.error(f"Failed to import dependencies: {e}")
    exit(1)

class RedactingFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.sensitive_keys = ['api_key', 'api_secret', 'telegram_token', 'access_token']

    def filter(self, record):
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            for key in self.sensitive_keys:
                if key in record.msg.lower():
                    # Simple redaction - replace sensitive patterns
                    words = record.msg.split()
                    for i, word in enumerate(words):
                        if any(sensitive in word.lower() for sensitive in self.sensitive_keys):
                            if '=' in word:
                                key_part, _ = word.split('=', 1)
                                words[i] = f"{key_part}=[REDACTED]"
                    record.msg = ' '.join(words)
        return True

def setup_logging():
    # Ensure logs directory exists
    import os
    os.makedirs('logs', exist_ok=True)
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler('logs/trading.log', maxBytes=10485760, backupCount=5)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

async def main():
    parser = argparse.ArgumentParser(description='Sensex Options Trading System')
    parser.add_argument('--mode', choices=['debug', 'test', 'live'], default='test', help='Operation mode')
    parser.add_argument('--date', help='Date for debug mode (YYYY-MM-DD)')
    parser.add_argument('--time', help='Time for debug mode (HH:MM)')
    parser.add_argument('--strike', type=int, help='Strike price for debug mode')
    parser.add_argument('--option-type', choices=['CE', 'PE'], help='Option type for debug mode')
    parser.add_argument('--expiry-date', help='Expiry date for debug mode (YYYY-MM-DD)')
    parser.add_argument('--trade-type', choices=['long', 'short'], default='long', help='Trade type for debug mode')
    parser.add_argument('--access-token', help='Kite Connect access token')
    parser.add_argument('--data-dir', default='option_data', help='Data directory')
    parser.add_argument('--csv-path', help='CSV path for debug mode backtest')
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger(__name__)
    
    try:
        config_manager = SecureConfigManager()
        config = config_manager.get_all()  # Use get_all() method as shown in your SecureConfigManager
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        exit(1)
    
    # Initialize services - wrap in try-catch to handle missing components gracefully
    try:
        notification_service = NotificationService(config)
    except Exception as e:
        logger.warning(f"Could not initialize notification service: {e}")
        notification_service = None
    
    try:
        data_manager = DataManager(config_manager)
    except Exception as e:
        logger.warning(f"Could not initialize data manager: {e}")
        data_manager = None
    
    try:
        broker_adapter = BrokerAdapter(config)
    except Exception as e:
        logger.warning(f"Could not initialize broker adapter: {e}")
        broker_adapter = None
    
    try:
        database_layer = DatabaseLayer()
    except Exception as e:
        logger.warning(f"Could not initialize database layer: {e}")
        database_layer = None
    
    try:
        trading_service = TradingService(data_manager, broker_adapter, notification_service, config, database_layer)
    except Exception as e:
        logger.warning(f"Could not initialize trading service: {e}")
        trading_service = None
    
    try:
        trading_system = TradingSystem()
    except Exception as e:
        logger.warning(f"Could not initialize trading system: {e}")
        trading_system = None
    
    try:
        zipper = Zipper(config_manager.get_all(), telegram_bot)
    except Exception as e:
        logger.warning(f"Could not initialize zipper: {e}")
        zipper = None

    # Create trading mode file
    import os
    os.makedirs(os.path.dirname('/home/ubuntu/main_trading/.trading_mode'), exist_ok=True)
    with open('/home/ubuntu/main_trading/.trading_mode', 'w') as f:
        f.write(args.mode.upper())

    try:
        mode = TradingMode(args.mode.upper())
        if trading_service:
            await trading_service.start_session(mode)
    except Exception as e:
        logger.warning(f"Could not start trading service session: {e}")

    try:
        if args.mode == 'debug':
            logger.info("Starting debug mode")
            if not args.csv_path and not all([args.date, args.time, args.access_token]):
                logger.error("Debug mode requires --csv-path or --date, --time, --access-token")
                if notification_service:
                    await notification_service.send_system_alert({
                        'type': 'ERROR', 'component': 'Main', 
                        'message': 'Debug mode requires --csv-path or --date, --time, --access-token', 
                        'mode': args.mode
                    })
                return
            
            if args.csv_path and trading_system:
                results = trading_system.run_debug_mode(args.csv_path)
                logger.info(f"Debug results: {results}")
                if notification_service:
                    await notification_service.send_daily_summary({
                        'mode': args.mode,
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'daily_pnl': results.get('total_pnl', 0),
                        'total_trades': results.get('trade_count', 0),
                        'winning_trades': int(results.get('trade_count', 0) * results.get('win_rate', 0) / 100),
                        'win_rate': results.get('win_rate', 0),
                        'avg_pnl': results.get('total_pnl', 0) / max(results.get('trade_count', 1), 1),
                        'sl_hits': 0,
                        'max_loss': False,
                        'trading_allowed': True,
                        'risk_level': 'LOW'
                    })
            else:
                debug_bot = DebugBot(config_file='config.json')
                if not debug_bot.initialize_kite(args.access_token, args.expiry_date):
                    logger.error("Failed to initialize Kite Connect for debug mode")
                    return
                
                logger.info(f"Running debug mode for {args.date} at {args.time}")
                debug_bot.debug_specific_conditions(
                    strike=args.strike,
                    option_type=args.option_type,
                    expiry_date=args.expiry_date or '2025-09-11',
                    target_date=args.date,
                    target_time=args.time,
                    data_dir=args.data_dir,
                    debug_data='both',
                    trade_type=args.trade_type
                )
            
            if zipper:
                await zipper.unzip_data(args.date or datetime.now().strftime('%Y-%m-%d'))
                await zipper.check_disk_space()

        elif args.mode == 'test':
            logger.info("Starting test mode")
            
            # Send test message
            send_telegram_message(f"""
🧪 <b>Test Mode Started</b>

📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🔧 Mode: Testing system components
🤖 Status: Running diagnostics

System is now in test mode. Monitoring all components.
            """)
            
            # Start telegram bot handler
            if trading_system:
                bot_handler = TelegramBotHandler(config, trading_system)
                threading.Thread(target=bot_handler.start_bot, daemon=True).start()
            
            # Start health monitor if available
            try:
                if data_manager:
                    health_monitor = HealthMonitor(config_manager, data_manager, logger)
                    threading.Thread(target=lambda: asyncio.run(health_monitor.monitor_system()), daemon=True).start()
            except Exception as e:
                logger.warning(f"Could not start health monitor: {e}")
            
            # Start data collector if available
            try:
                from data.data_collector import DataCollector
                collector = DataCollector()
                await collector.start()
            except Exception as e:
                logger.warning(f"Could not start data collector: {e}")
                # Keep the program running for telegram bot
                logger.info("Test mode running with basic functionality...")
                while True:
                    await asyncio.sleep(60)  # Keep alive

        elif args.mode == 'live':
            logger.info("Starting live mode")
            if not args.access_token:
                logger.error("Live mode requires --access-token")
                if notification_service:
                    await notification_service.send_system_alert({
                        'type': 'ERROR', 'component': 'Main', 
                        'message': 'Live mode requires --access-token', 
                        'mode': args.mode
                    })
                return
            
            live_bot = LiveBot(config_file='config.json', expiry_date=args.expiry_date or '2025-09-11')
            if not live_bot.initialize_kite(args.access_token):
                logger.error("Failed to initialize Kite Connect for live mode")
                return
            
            logger.info("Starting live trading mode")
            live_bot.start_trading(mode='live', data_dir=args.data_dir)
            if trading_system:
                threading.Thread(target=trading_system.run_trading_loop, daemon=True).start()
            
            if zipper:
                await zipper.check_disk_space()

    except Exception as e:
        logger.error(f"Error in main execution: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        if trading_service:
            try:
                await trading_service.stop_session()
            except Exception as e:
                logger.warning(f"Error stopping trading service: {e}")

if __name__ == "__main__":
    asyncio.run(main())
