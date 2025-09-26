import sys
print(sys.path)
try:
    from utils.secure_config_manager import SecureConfigManager
    print("Imported SecureConfigManager")
    from telegram_handler import TelegramBotHandler
    print("Imported TelegramBotHandler")
    from utils.health_monitor import HealthMonitor
    print("Imported HealthMonitor")
    from utils.data_manager import DataManager
    print("Imported DataManager")
    config_manager = SecureConfigManager()
    print("Initialized SecureConfigManager")
    data_manager = DataManager(config_manager)
    print("Initialized DataManager")
    from integrated_e2e_trading_system import TradingSystem
    print("Imported TradingSystem")
    from utils.zipper import Zipper
    print("Imported Zipper")
    from utils.notification_service import NotificationService
    print("Imported NotificationService")
    from utils.broker_adapter import BrokerAdapter
    print("Imported BrokerAdapter")
    from utils.trading_service import TradingService
    print("Imported TradingService")
    from utils.database_layer import DatabaseLayer
    print("Imported DatabaseLayer")
    from utils.enums import TradingMode
    print("Imported TradingMode")
    from sensex_trading_bot_debug import SensexTradingBot as DebugBot
    print("Imported DebugBot")
    from sensex_trading_bot_live import SensexTradingBot as LiveBot
    print("Imported LiveBot")
    from notifications import send_telegram_message
    print("Imported send_telegram_message")
    print("All imports successful")
except Exception as e:
    print(f"Error: {e}")
