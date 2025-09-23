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
    from telegram.telegram_bot import TelegramBot
    from telegram.telegram_bot_handler import TelegramBotHandler
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
                record.msg = record.msg.replace(getattr(record, key, ''), '[REDACTED]')
        return True

def setup_logging():
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
        config = config_manager.get_config()
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        exit(1)
    
    telegram_bot = TelegramBot(config['telegram_token'], config['telegram_chat_id'])
    notification_service = NotificationService(config)
    data_manager = DataManager(config_manager)
    broker_adapter = BrokerAdapter(config)
    database_layer = DatabaseLayer()
    trading_service = TradingService(data_manager, broker_adapter, notification_service, config, database_layer)
    trading_system = TradingSystem()
    zipper = Zipper()

    with open('/home/ubuntu/main_trading/.trading_mode', 'w') as f:
        f.write(args.mode.upper())

    mode = TradingMode(args.mode.upper())
    await trading_service.start_session(mode)

    try:
        if args.mode == 'debug':
            if not args.csv_path and not all([args.date, args.time, args.access_token]):
                logger.error("Debug mode requires --csv-path or --date, --time, --access-token")
                await notification_service.send_system_alert({
                    'type': 'ERROR', 'component': 'Main', 'message': 'Debug mode requires --csv-path or --date, --time, --access-token', 'mode': args.mode
                })
                return
            if args.csv_path:
                results = trading_system.run_debug_mode(args.csv_path)
                logger.info(f"Debug results: {results}")
                await notification_service.send_daily_summary({
                    'mode': args.mode,
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'daily_pnl': results['total_pnl'],
                    'total_trades': results['trade_count'],
                    'winning_trades': int(results['trade_count'] * results['win_rate'] / 100),
                    'win_rate': results['win_rate'],
                    'avg_pnl': results['total_pnl'] / max(results['trade_count'], 1),
                    'sl_hits': 0,
                    'max_loss': False,
                    'trading_allowed': True,
                    'risk_level': 'LOW'
                })
            else:
                debug_bot = DebugBot(config_file='config.json')
                if not debug_bot.initialize_kite(args.access_token, args.expiry_date):
                    logger.error("Failed to initialize Kite Connect for debug mode")
                    await notification_service.send_system_alert({
                        'type': 'ERROR', 'component': 'KiteConnect', 'message': 'Failed to initialize Kite Connect', 'mode': args.mode
                    })
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
            await zipper.unzip_data(args.date or datetime.now().strftime('%Y-%m-%d'))
            await zipper.check_disk_space()

        elif args.mode == 'test':
            bot_handler = TelegramBotHandler(config, trading_system)
            threading.Thread(target=bot_handler.start_bot, daemon=True).start()
            health_monitor = HealthMonitor(config_manager, data_manager, logger, telegram_bot)
            threading.Thread(target=lambda: asyncio.run(health_monitor.monitor_system()), daemon=True).start()
            from data.data_collector import DataCollector
            collector = DataCollector()
            await collector.start()

        elif args.mode == 'live':
            if not args.access_token:
                logger.error("Live mode requires --access-token")
                await notification_service.send_system_alert({
                    'type': 'ERROR', 'component': 'Main', 'message': 'Live mode requires --access-token', 'mode': args.mode
                })
                return
            live_bot = LiveBot(config_file='config.json', expiry_date=args.expiry_date or '2025-09-11')
            if not live_bot.initialize_kite(args.access_token):
                logger.error("Failed to initialize Kite Connect for live mode")
                await notification_service.send_system_alert({
                    'type': 'ERROR', 'component': 'KiteConnect', 'message': 'Failed to initialize Kite Connect', 'mode': args.mode
                })
                return
            logger.info("Starting live trading mode")
            live_bot.start_trading(mode='live', data_dir=args.data_dir)
            threading.Thread(target=trading_system.run_trading_loop, daemon=True).start()
            await zipper.check_disk_space()

    finally:
        await trading_service.stop_session()

if __name__ == "__main__":
    asyncio.run(main())
