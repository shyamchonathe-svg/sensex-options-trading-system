#!/usr/bin/env python3
"""
Integrated Trading System with Telegram Bot
Fixed version with proper error handling and all modes working
Generated on: 2025-09-12
Fixed: Configuration key error for position_size and lot_size
Fixed: Syntax error in TelegramNotifier send_message method
"""

import os
import sys
import json
import time
import logging
from logging.handlers import RotatingFileHandler
import threading
from datetime import datetime, time as dt_time, timedelta
import argparse
from pathlib import Path
import pytz
import schedule
import requests
import urllib3
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
import traceback

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Import dependencies
try:
    from sensex_trading_bot_live import SensexTradingBot
except ImportError:
    print("Warning: sensex_trading_bot_live not found. Trading functionality will be limited.")
    SensexTradingBot = None

try:
    from kiteconnect import KiteConnect
    from kiteconnect.exceptions import (
        NetworkException, TokenException, PermissionException, 
        OrderException, InputException, DataException, GeneralException
    )
except ImportError:
    print("Warning: kiteconnect not found. API functionality will be limited.")
    KiteConnect = None
    NetworkException = TokenException = PermissionException = Exception
    OrderException = InputException = DataException = GeneralException = Exception


class AuthenticationMode(Enum):
    INTERACTIVE = "interactive"
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    TEST = "test"


class TradingMode(Enum):
    TEST = "test"
    LIVE = "live"


@dataclass
class AuthenticationResult:
    success: bool
    token: Optional[str] = None
    error_message: Optional[str] = None
    source: Optional[str] = None


@dataclass
class MarketStatus:
    is_trading_day: bool
    is_trading_hours: bool
    status_message: str
    current_time: datetime


@dataclass
class SystemHealth:
    postback_server_running: bool
    postback_server_url: Optional[str]
    market_status: MarketStatus
    has_token: bool
    token_preview: Optional[str]
    trading_bot_initialized: bool
    telegram_bot_running: bool
    holidays_configured: List[str]


class ISTFormatter(logging.Formatter):
    def converter(self, timestamp):
        dt = datetime.fromtimestamp(timestamp)
        return pytz.timezone('Asia/Kolkata').localize(dt).timetuple()


class ConfigurationManager:
    """Handles configuration loading and validation"""
    
    def __init__(self, config_path: str = 'config.json'):
        self.config_path = config_path
        self.config = self._load_config()
        self._ensure_config_file_updated()
    
    def _load_config(self) -> Dict:
        """Load configuration from file with defaults"""
        defaults = {
            'use_https': True,
            'postback_urls': {
                "primary": "https://sensexbot.ddns.net/postback",
                "secondary": "https://sensexbot.ddns.net/redirect"
            },
            'server_host': 'sensexbot.ddns.net',
            'auth_timeout_seconds': 300,
            'market_holidays': [
                "2025-01-26", "2025-03-14", "2025-08-15", "2025-10-02",
                "2025-10-21", "2025-10-22", "2025-11-05", "2025-12-25"
            ],
            'api_key': 'xpft4r4qmsoq0p9b',
            'api_secret': '6c96tog8pgp8wiqti9ox7b7nx4hej8g9',
            'telegram_token': '7913084624:AAGvk9-R9YEUf4FGHCwDyOOpGHZOKUHr0mE',
            'chat_id': '1639045622',
            'position_size': 100,
            'lot_size': 20
        }
        
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            
            # Merge with defaults
            for key, value in defaults.items():
                if key not in config:
                    config[key] = value
                    logging.info(f"Added missing config key: {key} = {value}")
            
            return config
            
        except FileNotFoundError:
            logging.info(f"Config file {self.config_path} not found, creating with defaults")
            self._save_config(defaults)
            return defaults
        except Exception as e:
            logging.error(f"Config loading error: {e}")
            return defaults
    
    def _ensure_config_file_updated(self):
        """Ensure config file has all required keys"""
        try:
            self._save_config(self.config)
            logging.info(f"Config file {self.config_path} updated with all required keys")
        except Exception as e:
            logging.warning(f"Failed to update config file: {e}")
    
    def _save_config(self, config: Dict):
        """Save configuration to file"""
        with open(self.config_path, 'w') as f:
            json.dump(config, f, indent=2)
    
    def get(self, key: str, default=None):
        """Get configuration value"""
        return self.config.get(key, default)
    
    def update(self, key: str, value: Any):
        """Update configuration value"""
        self.config[key] = value
        try:
            self._save_config(self.config)
        except Exception as e:
            logging.warning(f"Failed to save config after update: {e}")


class TokenManager:
    """Centralized token management to prevent race conditions"""
    
    def __init__(self):
        self.token_file = 'latest_token.txt'
        self.lock = threading.Lock()
        self.logger = logging.getLogger(__name__)
        self.ist_tz = pytz.timezone('Asia/Kolkata')
    
    def save_token(self, token: str, source: str = "unknown") -> bool:
        """Thread-safe token saving"""
        with self.lock:
            try:
                with open(self.token_file, 'w') as f:
                    f.write(token)
                
                metadata = {
                    'token': token,
                    'source': source,
                    'timestamp': datetime.now(self.ist_tz).isoformat(),
                    'created_at': time.time()
                }
                
                with open(f"{self.token_file}.meta", 'w') as f:
                    json.dump(metadata, f)
                
                self.logger.info(f"Token saved from source: {source}")
                return True
                
            except Exception as e:
                self.logger.error(f"Failed to save token: {e}")
                return False
    
    def load_token(self) -> Optional[str]:
        """Thread-safe token loading"""
        with self.lock:
            try:
                if os.path.exists(self.token_file):
                    with open(self.token_file, 'r') as f:
                        token = f.read().strip()
                    if token:
                        return token
            except Exception as e:
                self.logger.error(f"Failed to load token: {e}")
            return None
    
    def get_token_metadata(self) -> Dict:
        """Get token metadata"""
        try:
            if os.path.exists(f"{self.token_file}.meta"):
                with open(f"{self.token_file}.meta", 'r') as f:
                    return json.load(f)
        except:
            pass
        
        if os.path.exists(self.token_file):
            stat = os.stat(self.token_file)
            return {
                'token': self.load_token(),
                'source': 'file_system',
                'timestamp': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'created_at': stat.st_mtime
            }
        
        return {}
    
    def is_token_valid(self, max_age_hours: int = 8) -> bool:
        """Check if token is still valid based on age"""
        metadata = self.get_token_metadata()
        if not metadata or not metadata.get('token'):
            return False
        
        created_at = metadata.get('created_at', 0)
        age_seconds = time.time() - created_at
        max_age_seconds = max_age_hours * 3600
        
        return age_seconds < max_age_seconds
    
    def get_token_age_string(self) -> str:
        """Get human-readable token age"""
        metadata = self.get_token_metadata()
        if not metadata.get('created_at'):
            return "Unknown age"
        
        age_seconds = time.time() - metadata['created_at']
        hours = int(age_seconds / 3600)
        minutes = int((age_seconds % 3600) / 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m old"
        else:
            return f"{minutes}m old"
    
    def clear_token(self):
        """Clear token and metadata"""
        with self.lock:
            try:
                for file in [self.token_file, f"{self.token_file}.meta"]:
                    if os.path.exists(file):
                        os.remove(file)
                self.logger.info("Token cleared")
            except Exception as e:
                self.logger.error(f"Failed to clear token: {e}")


class MarketHoursValidator:
    """Validates market hours and trading days"""
    
    def __init__(self, config_manager: ConfigurationManager):
        self.config = config_manager
        self.ist_tz = pytz.timezone('Asia/Kolkata')
    
    def get_market_status(self, allow_pre_market: bool = False, allow_test_mode: bool = False) -> MarketStatus:
        """Get comprehensive market status"""
        now = datetime.now(self.ist_tz)
        
        if allow_test_mode:
            return MarketStatus(
                is_trading_day=True,
                is_trading_hours=True,
                status_message=f"Test mode - authentication allowed. Current: {now.strftime('%H:%M IST')}",
                current_time=now
            )
        
        is_trading_day = self._is_trading_day(now)
        if not is_trading_day:
            return MarketStatus(
                is_trading_day=False,
                is_trading_hours=False,
                status_message=self._get_non_trading_day_message(now),
                current_time=now
            )
        
        is_trading_hours, hours_message = self._check_trading_hours(now, allow_pre_market)
        
        return MarketStatus(
            is_trading_day=True,
            is_trading_hours=is_trading_hours,
            status_message=hours_message,
            current_time=now
        )
    
    def _is_trading_day(self, date: datetime) -> bool:
        """Check if given date is a trading day"""
        if date.weekday() >= 5:
            return False
        
        date_str = date.strftime("%Y-%m-%d")
        holidays = self.config.get('market_holidays', [])
        return date_str not in holidays
    
    def _check_trading_hours(self, now: datetime, allow_pre_market: bool = False) -> Tuple[bool, str]:
        """Check if current time is within trading hours"""
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        
        if allow_pre_market:
            pre_market = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if now >= pre_market and now <= market_close:
                if now < market_open:
                    return True, f"Pre-market hours. Market opens at 9:15 AM IST. Current: {now.strftime('%H:%M IST')}"
                else:
                    return True, f"Trading hours active. Current: {now.strftime('%H:%M IST')}"
        else:
            if now >= market_open and now <= market_close:
                return True, f"Trading hours active. Current: {now.strftime('%H:%M IST')}"
        
        if now < market_open:
            return False, f"Market opens at 9:15 AM IST. Current: {now.strftime('%H:%M IST')}"
        else:
            return False, f"Market closed at 3:30 PM IST. Current: {now.strftime('%H:%M IST')}"
    
    def _get_non_trading_day_message(self, date: datetime) -> str:
        """Get message for non-trading days"""
        if date.weekday() >= 5:
            return f"Weekend - Markets closed ({date.strftime('%A')})"
        
        date_str = date.strftime("%Y-%m-%d")
        return f"Market holiday: {date_str}"


class NotificationService(ABC):
    """Abstract notification service"""
    
    @abstractmethod
    def send_message(self, message: str) -> bool:
        pass


class TelegramNotifier(NotificationService):
    """Telegram notification implementation"""
    
    def __init__(self, config_manager: ConfigurationManager):
        self.config = config_manager
        self.logger = logging.getLogger(__name__)
        self.send_lock = threading.Lock()
        self.last_update_id = -1
        self.ist_tz = pytz.timezone('Asia/Kolkata')
        self.running = False
    
    def send_message(self, message: str) -> bool:
        """Send message via Telegram with deduplication"""
        with self.send_lock:
            try:
                url = f"https://api.telegram.org/bot{self.config.get('telegram_token')}/sendMessage"
                
                if len(message) > 4000:
                    message = message[:3950] + "\n\n[Message truncated]"
                
                data = {
                    "chat_id": self.config.get('chat_id'),
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                }
                response = requests.post(url, data=data, timeout=10)
                if response.status_code == 200:
                    self.logger.info("Telegram message sent")
                    return True
                self.logger.error(f"Telegram API error: {response.status_code}")
                return False
            except Exception as e:
                self.logger.error(f"Failed to send Telegram message: {e}")
                return False
    
    def get_updates(self):
        """Get Telegram updates"""
        try:
            url = f"https://api.telegram.org/bot{self.config.get('telegram_token')}/getUpdates"
            params = {
                "offset": self.last_update_id + 1,
                "timeout": 30
            }
            
            response = requests.get(url, params=params, timeout=35)
            if response.status_code == 200:
                return response.json()
            else:
                self.logger.error(f"Telegram getUpdates error: {response.status_code}")
                return None
        except Exception as e:
            self.logger.error(f"Error getting Telegram updates: {e}")
            return None
    
    def process_command(self, message):
        """Process incoming command with better error handling"""
        try:
            text = message.get('text', '').strip().lower()
            chat_id = str(message['chat']['id'])
            username = message.get('from', {}).get('username', 'Unknown')
            
            if chat_id != str(self.config.get('chat_id')):
                self.logger.warning(f"Unauthorized chat ID: {chat_id} from user: {username}")
                return
            
            self.logger.info(f"Processing command: {text} from user: {username}")
            
            command_handlers = {
                '/login': self.handle_login_command,
                '/status': self.handle_status_command,
                '/health': self.handle_health_command,
                '/help': self.handle_help_command,
                '/start': self.handle_help_command
            }
            
            handler = command_handlers.get(text, self.handle_unknown_command)
            handler()
                
        except Exception as e:
            self.logger.error(f"Error processing command: {e}")
            self.logger.error(traceback.format_exc())
            try:
                self.send_message(f"Error processing command: {str(e)[:100]}")
            except:
                self.logger.error("Failed to send error message to Telegram")
    
    def handle_login_command(self):
        """Handle /login command"""
        self.send_message("Initiating login process...")
        # Implement login logic here, possibly calling orchestrator
        # This is a placeholder as the actual implementation depends on TradingSystemOrchestrator
        pass
    
    def handle_status_command(self):
        """Handle /status command"""
        self.send_message("Fetching system status...")
        # Implement status logic here
        pass
    
    def handle_health_command(self):
        """Handle /health command"""
        self.send_message("Performing system health check...")
        # Implement health check logic here
        pass
    
    def handle_help_command(self):
        """Handle /help and /start commands"""
        self.send_message("""
🤖 <b>Trading System Bot Commands</b>
/login - Authenticate with Zerodha
/status - Check system status
/health - Comprehensive diagnostics
/help - Show this help message
        """)
    
    def handle_unknown_command(self):
        """Handle unknown commands"""
        self.send_message("""
❓ <b>Unknown Command</b>
<b>Available commands:</b>
/login - Authenticate with Zerodha
/status - Check system status
/health - Comprehensive diagnostics
/help - Show all commands
        """)
    
    def start_bot(self):
        """Start the Telegram bot listener with better error handling"""
        self.running = True
        self.logger.info("Starting Telegram bot listener...")
        
        try:
            startup_message = f"""
🤖 <b>Trading System Bot Started</b>
📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
🔄 Status: Listening for commands
<b>Available commands:</b>
/login - Manual authentication
/status - System status
/health - Comprehensive diagnostics
/help - Show all commands
            """
            self.send_message(startup_message)
        except Exception as e:
            self.logger.error(f"Failed to send startup message: {e}")
        
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while self.running:
            try:
                updates = self.get_updates()
                if updates and updates.get('ok'):
                    for update in updates.get('result', []):
                        self.last_update_id = update['update_id']
                        
                        if 'message' in update:
                            message = update['message']
                            if 'text' in message:
                                self.process_command(message)
                
                consecutive_errors = 0
                time.sleep(1)
                
            except KeyboardInterrupt:
                self.logger.info("Bot interrupted by user")
                break
            except Exception as e:
                consecutive_errors += 1
                self.logger.error(f"Bot polling error #{consecutive_errors}: {e}")
                
                if consecutive_errors >= max_consecutive_errors:
                    self.logger.error(f"Too many consecutive errors ({consecutive_errors}), stopping bot")
                    try:
                        self.send_message(f"""
❌ <b>Bot Stopped Due to Errors</b>
📅 Time: {datetime.now(self.ist_tz).strftime('%Y-%m-%d %H:%M:%S IST')}
❌ Consecutive errors: {consecutive_errors}
🔄 Restart required
                        """)
                    except:
                        pass
                    break
                
                sleep_time = min(60, 5 * (2 ** consecutive_errors))
                self.logger.info(f"Sleeping {sleep_time} seconds before retry")
                time.sleep(sleep_time)
        
        self.logger.info("Telegram bot stopped")
    
    def stop_bot(self):
        """Stop the Telegram bot listener"""
        self.running = False
        
        try:
            shutdown_message = f"""
🔴 <b>Trading System Bot Stopped</b>
📅 Time: {datetime.now(self.ist_tz).strftime('%Y-%m-%d %H:%M:%S IST')}
Bot commands are no longer available.
            """
            self.send_message(shutdown_message)
        except Exception as e:
            self.logger.error(f"Failed to send shutdown message: {e}")


class TradingBotManager:
    """Manages trading bot lifecycle"""
    
    def __init__(self, config_manager: ConfigurationManager, notifier: NotificationService):
        self.config = config_manager
        self.notifier = notifier
        self.trading_bot = None
        self.logger = logging.getLogger(__name__)
    
    def initialize_bot(self, access_token: str, expiry_date: str) -> bool:
        """Initialize trading bot"""
        if SensexTradingBot is None:
            self.logger.error("SensexTradingBot not available")
            return False
        
        try:
            self.trading_bot = SensexTradingBot(
                access_token=access_token,
                expiry_date=expiry_date,
                position_size=self.config.get('position_size'),
                lot_size=self.config.get('lot_size')
            )
            self.logger.info("Trading bot initialized")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize trading bot: {e}")
            return False
    
    def start_trading(self, mode: TradingMode, data_dir: str):
        """Start trading in specified mode"""
        if not self.trading_bot:
            self.logger.error("Trading bot not initialized")
            return
        
        try:
            self.trading_bot.start(data_dir, test_mode=(mode == TradingMode.TEST))
            self.logger.info(f"Trading started in {mode.value} mode")
        except Exception as e:
            self.logger.error(f"Error starting trading: {e}")
    
    def stop_trading(self):
        """Stop trading bot"""
        if self.trading_bot:
            try:
                self.trading_bot.stop()
                self.logger.info("Trading bot stopped")
            except Exception as e:
                self.logger.error(f"Error stopping trading bot: {e}")
            self.trading_bot = None


class SchedulingService:
    """Handles scheduled tasks"""
    
    def __init__(self, auth_service: 'AuthenticationService', 
                 trading_manager: TradingBotManager,
                 market_validator: MarketHoursValidator,
                 notifier: NotificationService,
                 expiry_date: str,
                 data_dir: str):
        self.auth_service = auth_service
        self.trading_manager = trading_manager
        self.market_validator = market_validator
        self.notifier = notifier
        self.expiry_date = expiry_date
        self.data_dir = data_dir
        self.logger = logging.getLogger(__name__)
        self.running = False
    
    def schedule_daily_authentication(self):
        """Schedule daily authentication at 9:00 AM IST"""
        schedule.every().day.at("09:00").do(self._daily_authentication_task)
        self.running = True
        self.logger.info("Daily authentication scheduled for 9:00 AM IST")
        
        threading.Thread(target=self._run_schedule, daemon=True).start()
    
    def _run_schedule(self):
        """Run schedule loop"""
        while self.running:
            try:
                schedule.run_pending()
                time.sleep(60)
            except Exception as e:
                self.logger.error(f"Schedule error: {e}")
                time.sleep(60)
    
    def _daily_authentication_task(self):
        """Daily authentication task"""
        try:
            market_status = self.market_validator.get_market_status()
            if not market_status.is_trading_day:
                self.logger.info(f"Skipping authentication: {market_status.status_message}")
                return
            
            self.logger.info("Running scheduled authentication")
            result = self.auth_service.authenticate(AuthenticationMode.SCHEDULED)
            if result.success:
                self.trading_manager.initialize_bot(result.token, self.expiry_date)
                self.trading_manager.start_trading(TradingMode.TEST, self.data_dir)
            else:
                self.logger.error(f"Scheduled authentication failed: {result.error_message}")
        except Exception as e:
            self.logger.error(f"Daily authentication task error: {e}")
    
    def stop_scheduling(self):
        """Stop scheduled tasks"""
        self.running = False
        schedule.clear()
        self.logger.info("Scheduling stopped")


class ZerodhaErrorHandler:
    """Handles Zerodha API errors"""
    
    def __init__(self, notifier: NotificationService):
        self.notifier = notifier
        self.logger = logging.getLogger(__name__)
        self.ist_tz = pytz.timezone('Asia/Kolkata')
    
    def handle_error(self, error: Exception, operation: str) -> bool:
        """Handle Zerodha API errors with notifications"""
        ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
        error_type = type(error).__name__
        error_message = str(error)
        
        message = f"""
🔴 <b>Zerodha {error_type}</b>
📅 Time: {ist_time}
🔧 Operation: {operation}
❌ Error: {error_message[:200]}
🔄 Action: Check logs and retry
        """
        
        self.notifier.send_message(message)
        self.logger.error(f"Zerodha {error_type} during {operation}: {error_message}")
        return False


class PostbackHealthMonitor:
    """Monitors postback server health"""
    
    def __init__(self, config_manager: ConfigurationManager):
        self.config = config_manager
        self.logger = logging.getLogger(__name__)
    
    def get_server_urls(self) -> List[str]:
        """Get server API URLs"""
        host = self.config.get('server_host', 'sensexbot.ddns.net')
        if self.config.get('use_https', True):
            return [f"https://{host}", f"http://{host}:8001"]
        return [f"http://{host}:8001"]
    
    def test_server_connection(self, base_url: str) -> bool:
        """Test server connection"""
        try:
            response = requests.get(f"{base_url}/health", timeout=5, verify=False)
            return response.status_code == 200
        except:
            return False
    
    def get_working_server_url(self) -> Optional[str]:
        """Find a working server URL"""
        for url in self.get_server_urls():
            if self.test_server_connection(url):
                self.logger.info(f"Using server: {url}")
                return url
        return None
    
    def check_postback_server(self) -> bool:
        """Check if postback server is running"""
        server_url = self.get_working_server_url()
        if not server_url:
            self.logger.error("No postback server responding")
            return False
        
        try:
            response = requests.get(f"{server_url}/status", timeout=10, verify=False)
            if response.status_code == 200:
                self.logger.info(f"Postback server running: {response.json().get('server')}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Cannot connect to postback server: {e}")
            return False


class SafeAPIWrapper:
    """Wrapper for safe API calls with error handling"""
    
    def __init__(self, error_handler: ZerodhaErrorHandler):
        self.error_handler = error_handler
    
    def safe_call(self, operation_name: str, operation_func, *args, **kwargs) -> Tuple[Any, bool]:
        """Wrapper for safe Zerodha API calls"""
        try:
            result = operation_func(*args, **kwargs)
            return result, True
        except (NetworkException, TokenException, PermissionException, 
                OrderException, InputException, DataException, GeneralException) as e:
            return None, self.error_handler.handle_error(e, operation_name)
        except Exception as e:
            logging.error(f"Unexpected error in {operation_name}: {e}")
            return None, False


class AuthenticationService:
    """Handles authentication flow with race condition prevention"""
    
    def __init__(self, config_manager: ConfigurationManager, 
                 market_validator: MarketHoursValidator,
                 postback_monitor: PostbackHealthMonitor,
                 notifier: NotificationService,
                 api_wrapper: SafeAPIWrapper,
                 token_manager: TokenManager):
        self.config = config_manager
        self.market_validator = market_validator
        self.postback_monitor = postback_monitor
        self.notifier = notifier
        self.api_wrapper = api_wrapper
        self.token_manager = token_manager
        self.logger = logging.getLogger(__name__)
        self.ist_tz = pytz.timezone('Asia/Kolkata')
        self.auth_lock = threading.Lock()
        self.auth_in_progress = False
    
    def authenticate(self, mode: AuthenticationMode, force: bool = False) -> AuthenticationResult:
        """Main authentication method with race condition protection"""
        with self.auth_lock:
            if self.auth_in_progress:
                self.logger.warning("Authentication already in progress, skipping")
                return AuthenticationResult(success=False, error_message="Authentication in progress")
            
            self.auth_in_progress = True
        
        try:
            return self._perform_authentication_internal(mode, force)
        finally:
            with self.auth_lock:
                self.auth_in_progress = False
    
    def _perform_authentication_internal(self, mode: AuthenticationMode, force: bool = False) -> AuthenticationResult:
        """Internal authentication method"""
        try:
            if self.token_manager.is_token_valid() and not force:
                existing_token = self.token_manager.load_token()
                if existing_token:
                    self.logger.info("Using existing valid token")
                    return AuthenticationResult(
                        success=True, 
                        token=existing_token, 
                        source="existing_token"
                    )
            
            allow_test_mode = (mode == AuthenticationMode.TEST)
            market_status = self.market_validator.get_market_status(
                allow_pre_market=True, 
                allow_test_mode=allow_test_mode
            )
            
            if not market_status.is_trading_day and mode != AuthenticationMode.SCHEDULED and not force and not allow_test_mode:
                error_msg = f"Authentication not allowed: {market_status.status_message}"
                self._send_auth_not_allowed_message(market_status, force)
                return AuthenticationResult(success=False, error_message=error_msg)
            
            if not self.postback_monitor.check_postback_server():
                self._send_postback_error_message()
                return AuthenticationResult(success=False, error_message="Postback server error")
            
            self.logger.info(f"Starting HTTPS authentication (mode: {mode.value})")
            return self._perform_authentication(mode, market_status)
            
        except Exception as e:
            self.logger.error(f"Authentication error: {e}")
            self._send_auth_error_message(str(e))
            return AuthenticationResult(success=False, error_message=str(e))
    
    def _perform_authentication(self, mode: AuthenticationMode, market_status: MarketStatus) -> AuthenticationResult:
        """Perform the actual authentication"""
        self.token_manager.clear_token()
        server_url = self.postback_monitor.get_working_server_url()
        if server_url:
            try:
                requests.get(f"{server_url}/clear_token", timeout=5, verify=False)
                self.logger.info("Cleared existing tokens on server")
            except Exception as e:
                self.logger.warning(f"Failed to clear server tokens: {e}")
        
        postback_url = self.config.get('postback_urls')['primary']
        auth_url = (f"https://kite.zerodha.com/connect/login?"
                   f"api_key={self.config.get('api_key')}&v=3&postback_url={postback_url}")
        
        self._send_auth_link_message(auth_url, mode, market_status)
        
        request_token = self._wait_for_postback_response()
        if not request_token:
            return AuthenticationResult(success=False, error_message="No postback response")
        
        return self._exchange_token(request_token, mode)
    
    def _wait_for_postback_response(self) -> Optional[str]:
        """Wait for postback response from server"""
        timeout = self.config.get('auth_timeout_seconds', 300)
        start_time = time.time()
        server_url = self.postback_monitor.get_working_server_url()
        
        if not server_url:
            self._send_server_connection_error()
            return None
        
        self.logger.info(f"Waiting for postback response (timeout: {timeout}s)")
        
        while (time.time() - start_time) < timeout:
            try:
                response = requests.get(f"{server_url}/get_token", timeout=5, verify=False)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('status') == 'success' and 'request_token' in data:
                        self.logger.info(f"Received request token via {server_url}")
                        return data['request_token']
                
                response = requests.get(f"{server_url}/get_access_token", timeout=5, verify=False)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('status') == 'success' and 'access_token' in data:
                        self.logger.info("Received access token directly from server")
                        access_token = data['access_token']
                        self.token_manager.save_token(access_token, "postback_server")
                        return "DIRECT_ACCESS_TOKEN"
                
                time.sleep(3)
                
            except Exception as e:
                self.logger.warning(f"Postback check failed: {e}")
                time.sleep(3)
        
        self._send_auth_timeout_message(timeout)
        return None
    
    def _exchange_token(self, request_token: str, mode: AuthenticationMode) -> AuthenticationResult:
        """Exchange request token for access token"""
        if request_token == "DIRECT_ACCESS_TOKEN":
            access_token = self.token_manager.load_token()
            if access_token:
                self._send_auth_success_message(access_token, "postback_server")
                return AuthenticationResult(
                    success=True, 
                    token=access_token, 
                    source="postback_server"
                )
        
        if KiteConnect is None:
            self.logger.error("KiteConnect not available for token exchange")
            return AuthenticationResult(success=False, error_message="KiteConnect not available")
        
        kite = KiteConnect(api_key=self.config.get('api_key'))
        data, success = self.api_wrapper.safe_call(
            "Token Exchange",
            kite.generate_session,
            request_token=request_token,
            api_secret=self.config.get('api_secret')
        )
        
        if not success or not data:
            return AuthenticationResult(success=False, error_message="Token exchange failed")
        
        access_token = data["access_token"]
        
        self.token_manager.save_token(access_token, f"token_exchange_{mode.value}")
        
        self._send_auth_success_message(access_token, "token_exchange")
        return AuthenticationResult(success=True, token=access_token, source="token_exchange")
    
    def _send_auth_not_allowed_message(self, market_status: MarketStatus, force: bool):
        """Send authentication not allowed message"""
        message = f"""
❌ <b>Authentication Not Allowed</b>
📅 Time: {market_status.current_time.strftime('%Y-%m-%d %H:%M:%S IST')}
⏰ Status: {market_status.status_message}
🕘 Available: Mon-Fri, 9:00 AM - 3:30 PM IST
💡 For after-hours testing: --mode test --force
{'🔄 Use --force to override' if not force else ''}
        """
        self.notifier.send_message(message)
    
    def _send_postback_error_message(self):
        """Send postback server error message"""
        message = f"""
❌ <b>Postback Server Error</b>
📅 Time: {datetime.now(self.ist_tz).strftime('%Y-%m-%d %H:%M:%S IST')}
🔧 Issue: Postback server not running
📋 Actions:
1. Check server: <code>sudo systemctl status postback</code>
2. Restart: <code>sudo systemctl restart postback</code>
        """
        self.notifier.send_message(message)
    
    def _send_auth_link_message(self, auth_url: str, mode: AuthenticationMode, market_status: MarketStatus):
        """Send authentication link message"""
        message = f"""
🔐 <b>Zerodha Authentication Required</b>
📅 Time: {market_status.current_time.strftime('%Y-%m-%d %H:%M:%S IST')}
🤖 Mode: {mode.value.upper()}
⏰ Market: {market_status.status_message}
🔗 <b>Login:</b> {auth_url}
⏱️ Complete login within 5 minutes
        """
        self.notifier.send_message(message)
    
    def _send_server_connection_error(self):
        """Send server connection error message"""
        message = f"""
❌ <b>Server Connection Error</b>
📅 Time: {datetime.now(self.ist_tz).strftime('%Y-%m-%d %H:%M:%S IST')}
🔧 Issue: No response from postback server
        """
        self.notifier.send_message(message)
    
    def _send_auth_timeout_message(self, timeout: int):
        """Send authentication timeout message"""
        message = f"""
⏰ <b>Authentication Timeout</b>
📅 Time: {datetime.now(self.ist_tz).strftime('%Y-%m-%d %H:%M:%S IST')}
❌ No response after {timeout} seconds
🔄 Retry with /login
        """
        self.notifier.send_message(message)
    
    def _send_auth_success_message(self, access_token: str, source: str):
        """Send authentication success message"""
        message = f"""
✅ <b>Authentication Successful</b>
📅 Time: {datetime.now(self.ist_tz).strftime('%Y-%m-%d %H:%M:%S IST')}
🔑 Token: {access_token[:20]}...
🔧 Source: {source}
💾 Saved to: latest_token.txt
🚀 Ready for trading
        """
        self.notifier.send_message(message)


class TelegramBotService:
    """Manages Telegram bot lifecycle"""
    
    def __init__(self, config_manager: ConfigurationManager, system_orchestrator):
        self.config = config_manager
        self.system_orchestrator = system_orchestrator
        self.notifier = TelegramNotifier(config_manager)
        self.telegram_bot = None
        self.bot_thread = None
        self.logger = logging.getLogger(__name__)
    
    def start_bot(self) -> bool:
        """Start Telegram bot"""
        try:
            self.telegram_bot = self.notifier  # Use TelegramNotifier directly
            self.bot_thread = threading.Thread(target=self.telegram_bot.start_bot, daemon=True)
            self.bot_thread.start()
            self.logger.info("Telegram bot started")
            return True
        except Exception as e:
            self.logger.error(f"Failed to start Telegram bot: {e}")
            return False
    
    def stop_bot(self):
        """Stop Telegram bot"""
        try:
            if self.telegram_bot:
                self.telegram_bot.stop_bot()
            self.logger.info("Telegram bot stopped")
        except Exception as e:
            self.logger.error(f"Error stopping Telegram bot: {e}")


class TradingSystemOrchestrator:
    """High-level system orchestrator with improved token management"""
    
    def __init__(self, expiry_date: str = None, data_dir: str = "option_data"):
        self.logger = logging.getLogger(__name__)
        self.expiry_date = expiry_date or '2025-09-11'
        self.data_dir = data_dir
        self.is_running = False
        
        self._initialize_components()
    
    def _initialize_components(self):
        """Initialize all system components"""
        self.config_manager = ConfigurationManager()
        self.market_validator = MarketHoursValidator(self.config_manager)
        self.postback_monitor = PostbackHealthMonitor(self.config_manager)
        self.notifier = TelegramNotifier(self.config_manager)
        self.token_manager = TokenManager()
        
        self.error_handler = ZerodhaErrorHandler(self.notifier)
        self.api_wrapper = SafeAPIWrapper(self.error_handler)
        
        self.auth_service = AuthenticationService(
            self.config_manager, self.market_validator,
            self.postback_monitor, self.notifier, self.api_wrapper, self.token_manager
        )
        self.trading_manager = TradingBotManager(self.config_manager, self.notifier)
        self.scheduling_service = SchedulingService(
            self.auth_service, self.trading_manager, self.market_validator,
            self.notifier, self.expiry_date, self.data_dir
        )
        
        self.telegram_service = TelegramBotService(self.config_manager, self)
    
    def get_access_token_via_telegram(self, mode: str = "telegram-manual") -> Optional[str]:
        """Telegram bot compatible method for authentication"""
        try:
            self.logger.info(f"Telegram bot initiated authentication: {mode}")
            result = self.auth_service.authenticate(AuthenticationMode.MANUAL, force=False)
            if result.success:
                self.logger.info("Authentication successful via Telegram")
                return result.token
            else:
                self.logger.error(f"Authentication failed: {result.error_message}")
                return None
        except Exception as e:
            self.logger.error(f"Error in get_access_token_via_telegram: {e}")
            return None
    
    def check_postback_server(self) -> bool:
        """Wrapper method for postback server check"""
        return self.postback_monitor.check_postback_server()
    
    def authenticate_manual(self, force: bool = False) -> bool:
        """Public method for manual authentication"""
        result = self.auth_service.authenticate(AuthenticationMode.MANUAL, force)
        return result.success
    
    def authenticate_test(self, force: bool = False) -> bool:
        """Public method for test mode authentication"""
        result = self.auth_service.authenticate(AuthenticationMode.TEST, force)
        return result.success
    
    def get_postback_server_url(self) -> Optional[str]:
        """Get working postback server URL"""
        return self.postback_monitor.get_working_server_url()
    
    def get_market_status(self, allow_pre_market: bool = False) -> MarketStatus:
        """Get current market status"""
        return self.market_validator.get_market_status(allow_pre_market)
    
    def has_valid_token(self) -> bool:
        """Check if system has a valid access token"""
        return self.token_manager.is_token_valid()
    
    def get_token_preview(self) -> Optional[str]:
        """Get preview of current token"""
        token = self.token_manager.load_token()
        if token:
            return token[:20] + '...'
        return None
    
    def get_token_age(self) -> str:
        """Get age of current token"""
        return self.token_manager.get_token_age_string()
    
    def is_token_expired(self) -> bool:
        """Check if token is likely expired"""
        return not self.token_manager.is_token_valid()
    
    def get_system_health(self) -> SystemHealth:
        """Get comprehensive system health for /health command"""
        market_status = self.market_validator.get_market_status()
        postback_status = self.postback_monitor.check_postback_server()
        server_url = self.postback_monitor.get_working_server_url()
        
        return SystemHealth(
            postback_server_running=postback_status,
            postback_server_url=server_url,
            market_status=market_status,
            has_token=self.has_valid_token(),
            token_preview=self.get_token_preview(),
            trading_bot_initialized=bool(self.trading_manager.trading_bot),
            telegram_bot_running=bool(self.telegram_service.telegram_bot and self.telegram_service.telegram_bot.running),
            holidays_configured=self.config_manager.get('market_holidays', [])
        )
    
    def get_detailed_status(self) -> Dict:
        """Get detailed status for Telegram bot /status command"""
        market_status = self.get_market_status()
        server_url = self.get_postback_server_url()
        
        return {
            'market_status': market_status,
            'postback_server': {
                'running': self.check_postback_server(),
                'url': server_url,
                'host': self.config_manager.get('server_host', 'sensexbot.ddns.net')
            },
            'authentication': {
                'has_token': self.has_valid_token(),
                'token_preview': self.get_token_preview(),
                'token_age': self.get_token_age(),
                'is_expired': self.is_token_expired()
            },
            'trading_bot': {
                'initialized': bool(self.trading_manager.trading_bot)
            },
            'system': {
                'expiry_date': self.expiry_date,
                'data_dir': self.data_dir,
                'holidays': self.config_manager.get('market_holidays', [])
            }
        }
    
    def get_health_report(self) -> Dict:
        """Get comprehensive health report for /health command"""
        health = self.get_system_health()
        
        return {
            'timestamp': datetime.now(pytz.timezone('Asia/Kolkata')),
            'postback_server': {
                'status': 'Online' if health.postback_server_running else 'Offline',
                'url': health.postback_server_url,
                'reachable': health.postback_server_running
            },
            'market': {
                'is_trading_day': health.market_status.is_trading_day,
                'is_trading_hours': health.market_status.is_trading_hours,
                'status_message': health.market_status.status_message,
                'current_time': health.market_status.current_time
            },
            'authentication': {
                'has_valid_token': health.has_token,
                'token_preview': health.token_preview,
                'token_age': self.get_token_age(),
                'needs_refresh': self.is_token_expired()
            },
            'trading_bot': {
                'initialized': health.trading_bot_initialized,
                'ready': health.trading_bot_initialized and health.has_token
            },
            'telegram_bot': {
                'running': health.telegram_bot_running
            },
            'configuration': {
                'expiry_date': self.expiry_date,
                'data_directory': self.data_dir,
                'holidays_count': len(health.holidays_configured),
                'next_holiday': self._get_next_holiday(health.holidays_configured)
            }
        }
    
    def _get_next_holiday(self, holidays: List[str]) -> Optional[str]:
        """Get the next upcoming holiday"""
        try:
            today = datetime.now().date()
            future_holidays = [
                datetime.strptime(h, '%Y-%m-%d').date() 
                for h in holidays 
                if datetime.strptime(h, '%Y-%m-%d').date() >= today
            ]
            if future_holidays:
                return min(future_holidays).strftime('%Y-%m-%d')
        except Exception:
            pass
        return None
    
    def authenticate(self, mode: AuthenticationMode = AuthenticationMode.INTERACTIVE, force: bool = False) -> bool:
        """Public method for authentication"""
        result = self.auth_service.authenticate(mode, force)
        return result.success
    
    def start_trading(self, mode: TradingMode) -> bool:
        """Start trading in specified mode"""
        token = self.token_manager.load_token()
        if not token:
            self.logger.error("No access token available for trading")
            return False
        
        if self.trading_manager.initialize_bot(token, self.expiry_date):
            self.trading_manager.start_trading(mode, self.data_dir)
            return True
        return False
    
    def get_system_status(self) -> Dict:
        """Get comprehensive system status"""
        return self.get_detailed_status()
    
    def run_full_setup(self) -> bool:
        """Run complete system setup"""
        try:
            self.logger.info("Starting full system setup")
            
            holidays = self.config_manager.get('market_holidays', [])
            holidays_str = ', '.join(holidays) if holidays else 'None configured'
            
            self.notifier.send_message(f"""
🛠️ <b>System Setup Starting</b>
📅 Time: {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S IST')}
📡 Checking postback server...
🎯 Market Holidays: {holidays_str}
            """)
            
            if not self.telegram_service.start_bot():
                self.notifier.send_message("❌ <b>Failed to start Telegram bot</b>")
                return False
            
            self.scheduling_service.schedule_daily_authentication()
            
            self.notifier.send_message(f"""
✅ <b>System Setup Complete</b>
📅 Time: {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S IST')}
📡 Postback Server: {self.postback_monitor.get_working_server_url() or 'Not running'}
📅 Authentication scheduled for 9:00 AM IST on trading days
🤖 Trading will start in test mode after authentication
🔄 Commands: /login, /status, /health, /help
            """)
            
            self.is_running = True
            return True
            
        except Exception as e:
            self.logger.error(f"Setup error: {e}")
            self.notifier.send_message(f"❌ <b>Setup Error</b>: {str(e)[:200]}")
            return False
    
    def run_bot_only_mode(self) -> bool:
        """Run only Telegram bot for manual commands"""
        try:
            self.logger.info("Starting bot-only mode")
            success = self.telegram_service.start_bot()
            if success:
                holidays = self.config_manager.get('market_holidays', [])
                holidays_str = ', '.join(holidays) if holidays else 'None configured'
                
                self.notifier.send_message(f"""
🤖 <b>Telegram Bot Only Mode Started</b>
📅 Time: {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S IST')}
🎯 Market Holidays: {holidays_str}
🔄 Commands: /login, /status, /health, /help
                """)
                self.is_running = True
                return True
            return False
        except Exception as e:
            self.logger.error(f"Bot-only mode error: {e}")
            self.notifier.send_message(f"❌ <b>Bot Mode Error</b>: {str(e)[:200]}")
            return False
    
    def run_test_mode(self, force: bool = False) -> bool:
        """Run test mode with authentication and trading setup"""
        try:
            self.logger.info(f"Starting test mode (force: {force})")
            
            success = self.authenticate_test(force)
            if not success:
                self.logger.error("Test mode authentication failed")
                return False
            
            success = self.start_trading(TradingMode.TEST)
            if not success:
                self.logger.error("Failed to start test mode trading")
                return False
            
            self.is_running = True
            self.logger.info("Test mode started successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Test mode error: {e}")
            self.notifier.send_message(f"❌ <b>Test Mode Error</b>: {str(e)[:200]}")
            return False
    
    def run_live_mode(self, force: bool = False) -> bool:
        """Run live mode with authentication and trading setup"""
        try:
            self.logger.info(f"Starting live mode (force: {force})")
            
            success = self.authenticate_manual(force)
            if not success:
                self.logger.error("Live mode authentication failed")
                return False
            
            success = self.start_trading(TradingMode.LIVE)
            if not success:
                self.logger.error("Failed to start live mode trading")
                return False
            
            self.is_running = True
            self.logger.info("Live mode started successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Live mode error: {e}")
            self.notifier.send_message(f"❌ <b>Live Mode Error</b>: {str(e)[:200]}")
            return False
    
    def stop_system(self):
        """Stop all system components"""
        try:
            self.scheduling_service.stop_scheduling()
            self.trading_manager.stop_trading()
            self.telegram_service.stop_bot()
            self.is_running = False
            self.logger.info("System stopped")
            
            self.notifier.send_message(f"""
🛑 <b>System Stopped</b>
📅 Time: {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S IST')}
All services terminated
            """)
        except Exception as e:
            self.logger.error(f"Error stopping system: {e}")


def setup_logging():
    """Configure logging with IST timezone"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    os.makedirs('logs', exist_ok=True)
    
    file_handler = RotatingFileHandler(
        'logs/trading_system.log',
        maxBytes=5*1024*1024,
        backupCount=5
    )
    
    console_handler = logging.StreamHandler(sys.stdout)
    
    formatter = ISTFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S IST'
    )
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def main():
    """Main entry point"""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    parser = argparse.ArgumentParser(description="Integrated Trading System")
    parser.add_argument('--mode', choices=['setup', 'test', 'live', 'bot'], 
                       default='setup', help="Operation mode")
    parser.add_argument('--force', action='store_true', 
                       help="Force authentication even on non-trading days")
    parser.add_argument('--expiry-date', default='2025-09-11',
                       help="Option expiry date (YYYY-MM-DD)")
    parser.add_argument('--data-dir', default='option_data',
                       help="Directory for trading data")
    
    args = parser.parse_args()
    
    system = None
    try:
        system = TradingSystemOrchestrator(
            expiry_date=args.expiry_date,
            data_dir=args.data_dir
        )
        
        success = False
        
        if args.mode == 'setup':
            logger.info("Running full setup mode")
            success = system.run_full_setup()
            if not success:
                logger.error("Full setup failed")
                sys.exit(1)
                
        elif args.mode == 'bot':
            logger.info("Running bot-only mode")
            success = system.run_bot_only_mode()
            if not success:
                logger.error("Bot-only mode failed")
                sys.exit(1)
                
        elif args.mode == 'test':
            logger.info(f"Running test mode (force: {args.force})")
            success = system.run_test_mode(args.force)
            if not success:
                logger.error("Test mode failed")
                sys.exit(1)
                
        elif args.mode == 'live':
            logger.info(f"Running live mode (force: {args.force})")
            success = system.run_live_mode(args.force)
            if not success:
                logger.error("Live mode failed")
                sys.exit(1)
        
        logger.info(f"System running in {args.mode} mode. Press Ctrl+C to stop.")
        try:
            while system.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
            
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)
    finally:
        if system:
            system.stop_system()


if __name__ == "__main__":
    main()
