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
except Exception as e:
    print(f"Error: {e}")
