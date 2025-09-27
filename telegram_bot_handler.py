#!/usr/bin/env python3
"""
Telegram Bot Command Handler for Trading System
Handles /login, /status, /health, /help, /live, /stop, /debug commands
"""

import json
import time
import threading
import requests
import pytz
import os
import logging
import subprocess
import asyncio
from datetime import datetime, time as dt_time
from utils.secure_config_manager import SecureConfigManager
from utils.holiday_checker import HolidayChecker
from utils.notification_service import NotificationService
from utils.trading_service import TradingService
from utils.data_manager import DataManager
from utils.broker_adapter import BrokerAdapter
from utils.database_layer import DatabaseLayer
from integrated_e2e_trading_system import TradingSystem

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/ubuntu/main_trading/logs/telegram_bot_handler.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class TelegramBotHandler:
    def __init__(self):
        self.config_manager = SecureConfigManager()
        self.config = self.config_manager.get_all()
        self.notification_service = NotificationService({
            "TELEGRAM_TOKEN": self.config.get('telegram_token'),
            "TELEGRAM_CHAT_ID": self.config.get('telegram_chat_id'),
            "ENABLE_NOTIFICATIONS": True
        })
        self.trading_runner = TradingSystem()
        self.trading_service = TradingService(
            data_manager=DataManager(self.config_manager),
            broker_adapter=BrokerAdapter(self.config),
            notification_service=self.notification_service,
            config=self.config,
            database_layer=DatabaseLayer()
        )
        self.telegram_token = self.config.get('telegram_token')
        self.chat_id = self.config.get('telegram_chat_id')
        self.ist_tz = pytz.timezone('Asia/Kolkata')
        self.last_update_id = 0
        self.running = False
        
    def is_trading_day_and_hours(self, allow_pre_market=False):
        """Check if it's a trading day and within trading hours"""
        try:
            market_status = self.trading_runner.is_market_hours()
            holiday_checker = HolidayChecker(self.config.get('trading_holidays', []))
            now = datetime.now(self.ist_tz)
            is_trading_day = not holiday_checker.is_holiday(now.date()) and now.weekday() < 5
            is_trading_hours = market_status or (allow_pre_market and now.time() >= dt_time(9, 0))
            status_message = "Market open" if is_trading_hours else "Market closed"
            return is_trading_day and is_trading_hours, status_message
        except Exception as e:
            logger.error(f"Error checking trading hours: {e}")
            return False, f"Unable to verify trading hours: {e}"

    async def send_message(self, message):
        """Send Telegram message using NotificationService"""
        try:
            return await self.notification_service.send_message(message)
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    def get_system_resources(self):
        """Get system resource information"""
        try:
            import psutil
            return {
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory': psutil.virtual_memory(),
                'disk': psutil.disk_usage('/home/ubuntu/main_trading/data'),
                'uptime': self._get_system_uptime(),
                'available': True
            }
        except ImportError:
            logger.warning("psutil not available")
            return {'available': False}
        except Exception as e:
            logger.error(f"Error getting system resources: {e}")
            return {'available': False, 'error': str(e)}
    
    def _get_system_uptime(self):
        """Get system uptime"""
        try:
            import psutil
            uptime_seconds = time.time() - psutil.boot_time()
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            return f"{days}d {hours}h"
        except:
            return "Unknown"
    
    def check_network_connectivity(self):
        """Check network connectivity to endpoints"""
        connectivity = {}
        try:
            response = requests.get('https://api.kite.trade', timeout=5)
            connectivity['zerodha_api'] = {
                'status': '🟢 Reachable' if response.status_code == 200 else f'⚠️ Status {response.status_code}',
                'reachable': response.status_code == 200
            }
        except Exception:
            connectivity['zerodha_api'] = {
                'status': '🔴 Unreachable',
                'reachable': False
            }
        try:
            response = requests.get(f"https://{self.config.get('server_host')}/health", timeout=5, verify=False)
            connectivity['postback_server'] = {
                'status': '🟢 Online' if response.status_code == 200 else f'⚠️ Status {response.status_code}',
                'reachable': response.status_code == 200,
                'url': f"https://{self.config.get('server_host')}"
            }
        except Exception:
            connectivity['postback_server'] = {
                'status': '🔴 Unreachable',
                'reachable': False,
                'url': None
            }
        return connectivity
    
    def handle_health_command(self):
        """Handle /health command"""
        try:
            ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
            token_file = '/home/ubuntu/main_trading/data/request_token.txt'
            has_token = os.path.exists(token_file)
            token_age = int(time.time() - os.path.getmtime(token_file)) if has_token else 0
            system_resources = self.get_system_resources()
            network_status = self.check_network_connectivity()
            is_trading, market_status = self.is_trading_day_and_hours()
            
            health_message = f"""
🏥 <b>System Health Report</b>
📅 Time: {ist_time}
<b>📊 Postback Server:</b>
Status: {'🟢 Online' if network_status['postback_server']['reachable'] else '🔴 Offline'}
URL: {network_status['postback_server']['url'] or 'Not available'}
Reachable: {'✅ Yes' if network_status['postback_server']['reachable'] else '❌ No'}
<b>📈 Market Status:</b>
Trading Day: {'✅ Yes' if is_trading else '❌ No'}
Trading Hours: {'✅ Active' if self.trading_runner.is_market_hours() else '❌ Closed'}
Status: {market_status}
<b>🔑 Authentication:</b>
Valid Token: {'✅ Yes' if has_token and token_age < self.config.get('auth_timeout_seconds', 300) else '❌ No'}
Token Preview: {'****' if has_token else 'None'}
Token Age: {token_age}s
Needs Refresh: {'⚠️ Yes' if has_token and token_age > 240 else '✅ No'}
<b>🤖 Trading Bot:</b>
Initialized: {'✅ Yes' if self.trading_runner.is_trading else '❌ No'}
Mode: {self.trading_runner.mode}
<b>📡 Telegram Bot:</b>
Running: {'✅ Yes' if self.running else '❌ No'}
"""
            if system_resources.get('available'):
                memory = system_resources['memory']
                disk = system_resources['disk']
                health_message += f"""
<b>💻 System Resources:</b>
CPU: {system_resources['cpu_percent']:.1f}%
Memory: {memory.percent:.1f}% ({memory.used//1024//1024//1024:.1f}GB/{memory.total//1024//1024//1024:.1f}GB)
Disk: {disk.percent:.1f}% ({disk.free//1024//1024//1024:.1f}GB free)
Uptime: {system_resources['uptime']}
"""
            else:
                health_message += """
<b>💻 System Resources:</b>
Monitoring not available (install psutil)
"""
            health_message += f"""
<b>🌐 Network Connectivity:</b>
Zerodha API: {network_status['zerodha_api']['status']}
Postback Server: {network_status['postback_server']['status']}
"""
            critical_issues = []
            warnings = []
            if system_resources.get('available'):
                if system_resources['cpu_percent'] > 80:
                    critical_issues.append("High CPU usage")
                elif system_resources['cpu_percent'] > 60:
                    warnings.append("Elevated CPU usage")
                if system_resources['memory'].percent > 85:
                    critical_issues.append("High memory usage")
                elif system_resources['memory'].percent > 70:
                    warnings.append("Elevated memory usage")
                if system_resources['disk'].percent > 90:
                    critical_issues.append("Low disk space")
                elif system_resources['disk'].percent > 80:
                    warnings.append("Limited disk space")
            if not network_status['postback_server']['reachable']:
                critical_issues.append("Postback server down")
            if not has_token or token_age > self.config.get('auth_timeout_seconds', 300):
                if is_trading:
                    critical_issues.append("No valid authentication token during trading hours")
                else:
                    warnings.append("Authentication token needed for trading")
            health_message += f"""
<b>📊 Overall Status:</b>
"""
            if critical_issues:
                health_message += f"🔴 <b>CRITICAL</b> - {len(critical_issues)} issue(s)\n"
                for issue in critical_issues[:3]:
                    health_message += f"• {issue}\n"
            elif warnings:
                health_message += f"⚠️ <b>WARNING</b> - {len(warnings)} concern(s)\n"
                for warning in warnings[:3]:
                    health_message += f"• {warning}\n"
            else:
                health_message += "✅ <b>HEALTHY</b> - All systems operational\n"
            if critical_issues or warnings:
                health_message += f"""
<b>🔧 Recommended Actions:</b>
"""
                if not network_status['postback_server']['reachable']:
                    health_message += "• Restart postback server\n"
                if not has_token and is_trading:
                    health_message += "• Run /login to authenticate\n"
                if not network_status['zerodha_api']['reachable']:
                    health_message += "• Check internet connectivity\n"
            health_message += f"""
<b>🔄 Available Commands:</b>
/login - Authenticate during trading hours
/status - Quick status check
/health - This comprehensive report
/help - All commands
/live - Start live mode
/stop - Stop all services
/debug - One-time debug authentication
"""
            asyncio.run(self.send_message(health_message))
        except Exception as e:
            asyncio.run(self.send_message(f"""
❌ <b>Health Command Error</b>
📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
❌ Error: {str(e)[:100]}
Try /status for basic system information.
            """))
            logger.error(f"Health command error: {e}")

    def handle_login_command(self):
        """Handle /login command"""
        try:
            ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
            is_trading, trading_status = self.is_trading_day_and_hours(allow_pre_market=True)
            if not is_trading:
                asyncio.run(self.send_message(f"""
❌ <b>Login Not Available</b>
📅 Time: {ist_time}
⏰ Status: {trading_status}
<b>🕘 Trading Hours:</b>
Monday to Friday: 9:00 AM - 3:30 PM IST
<b>🔄 Available Commands:</b>
/status - Check system status
/health - Comprehensive diagnostics
/help - Show all commands
/live - Start live mode
/stop - Stop all services
/debug - One-time debug authentication
                """))
                return
            if not self.trading_runner.broker.kws or not self.trading_runner.broker.is_connected:
                asyncio.run(self.send_message(f"""
❌ <b>Login Failed - Server Not Available</b>
📅 Time: {ist_time}
🔧 Issue: Postback server or WebSocket not responding
<b>📋 Server Commands:</b>
• Start HTTPS: <code>sudo systemctl start postback-server</code>
• Check status: <code>curl -k https://sensexbot.ddns.net/status</code>
<b>🔍 Troubleshooting:</b>
1. SSH to AWS instance
2. Run server command
3. Try /login again
                """))
                return
            asyncio.run(self.send_message(f"""
🔄 <b>Manual Login Initiated</b>
📅 Time: {ist_time}
🤖 Mode: Telegram Bot Command
⏰ Status: {trading_status}
🔐 Generating secure authentication link...
⏳ Please wait 5 seconds...
            """))
            auth_thread = threading.Thread(
                target=self._background_authentication, 
                args=('telegram-manual',), 
                daemon=True
            )
            auth_thread.start()
        except Exception as e:
            asyncio.run(self.send_message(f"""
❌ <b>Login Command Error</b>
📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
❌ Error: {str(e)}
Please try again or use manual script:
<code>sudo systemctl start token-generator</code>
            """))
            logger.error(f"Login command error: {e}")

    def handle_debug_command(self):
        """Handle /debug command"""
        try:
            ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
            if not self.trading_runner.broker.kws or not self.trading_runner.broker.is_connected:
                asyncio.run(self.send_message(f"""
❌ <b>Debug Login Failed - Server Not Available</b>
📅 Time: {ist_time}
🔧 Issue: Postback server or WebSocket not responding
<b>📋 Server Commands:</b>
• Start HTTPS: <code>sudo systemctl start postback-server</code>
• Check status: <code>curl -k https://sensexbot.ddns.net/status</code>
<b>🔍 Troubleshooting:</b>
1. SSH to AWS instance
2. Run server command
3. Try /debug again
                """))
                return
            asyncio.run(self.send_message(f"""
🔄 <b>Debug Authentication Initiated</b>
📅 Time: {ist_time}
🤖 Mode: Debug (One-time authentication)
🔐 Generating secure authentication link...
⏳ Please wait 5 seconds...
            """))
            auth_thread = threading.Thread(
                target=self._background_debug_authentication,
                daemon=True
            )
            auth_thread.start()
        except Exception as e:
            asyncio.run(self.send_message(f"""
❌ <b>Debug Command Error</b>
📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
❌ Error: {str(e)}
Try running manually:
<code>python3 ~/main_trading/token_generator.py --debug</code>
            """))
            logger.error(f"Debug command error: {e}")

    def _background_authentication(self, mode):
        """Run authentication in background thread"""
        try:
            auth_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={self.config.get('api_key')}&redirect_url=https://{self.config.get('server_host')}/postback"
            asyncio.run(self.send_message(f"""
🔐 <b>Authentication URL</b>
📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
Please authenticate: {auth_url}
            """))
        except Exception as e:
            asyncio.run(self.send_message(f"""
❌ <b>Background Authentication Error</b>
📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
❌ Error: {str(e)[:200]}...
<b>🔄 Manual Recovery:</b>
<code>sudo systemctl start token-generator</code>
            """))
            logger.error(f"Background authentication error: {e}")

    def _background_debug_authentication(self):
        """Run debug authentication in background thread"""
        try:
            subprocess.run(["/home/ubuntu/main_trading/venv/bin/python3", "/home/ubuntu/main_trading/token_generator.py", "--debug"], check=True)
            asyncio.run(self.send_message(f"""
🔍 <b>Debug Authentication Started</b>
📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
Running token_generator.py in debug mode...
Check logs: <code>tail -f ~/main_trading/logs/token_generator.log</code>
            """))
        except Exception as e:
            asyncio.run(self.send_message(f"""
❌ <b>Debug Authentication Error</b>
📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
❌ Error: {str(e)[:200]}...
Try running manually:
<code>python3 ~/main_trading/token_generator.py --debug</code>
            """))
            logger.error(f"Debug authentication error: {e}")

    def handle_status_command(self):
        """Handle /status command"""
        try:
            ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
            is_trading, market_status = self.is_trading_day_and_hours()
            token_file = '/home/ubuntu/main_trading/data/request_token.txt'
            has_token = os.path.exists(token_file)
            token_age = int(time.time() - os.path.getmtime(token_file)) if has_token else 0
            
            status_message = f"""
📊 <b>Trading System Status</b>
📅 Time: {ist_time}
⏰ Market: {market_status}
<b>🖥️ Server Status:</b>
HTTPS Server: {'🟢 Online' if self.trading_runner.broker.is_connected else '🔴 Offline'}
Host: {self.config.get('server_host')}
URL: https://{self.config.get('server_host')}
<b>🔑 Authentication:</b>
Token: {'✅ Valid' if has_token else '❌ No Token'}
Preview: {'****' if has_token else 'None'}
Age: {token_age}s
Status: {'⚠️ May need refresh' if has_token and token_age > 240 else '✅ Active'}
<b>📈 Market Info:</b>
Trading Day: {'✅ Yes' if is_trading else '❌ No'}
Trading Hours: {'✅ Active' if self.trading_runner.is_market_hours() else '❌ Closed'}
Current: {'🟢 OPEN' if self.trading_runner.is_market_hours() else '🔴 CLOSED'}
<b>🤖 Trading Bot:</b>
Initialized: {'✅ Yes' if self.trading_runner.is_trading else '❌ No'}
Mode: {self.trading_runner.mode}
<b>⚙️ Configuration:</b>
Data Directory: {self.config.get('output_dir', 'archives')}
Holidays Count: {len(self.config.get('trading_holidays', []))}
<b>🔄 Available Commands:</b>
/login - Authenticate during trading hours
/status - This status check
/health - Comprehensive diagnostics
/help - Show all commands
/live - Start live mode
/stop - Stop all services
/debug - One-time debug authentication
            """
            asyncio.run(self.send_message(status_message))
        except Exception as e:
            asyncio.run(self.send_message(f"""
❌ <b>Status Check Error</b>
📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
❌ Error: {str(e)}
Try /health for comprehensive diagnostics.
            """))
            logger.error(f"Status command error: {e}")

    def handle_help_command(self):
        """Handle /help command"""
        help_message = f"""
🤖 <b>Trading System Bot Commands</b>
📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
<b>🔐 Authentication Commands:</b>
/login - Manual authentication (trading hours)
/debug - One-time debug authentication
/status - Check system status
/health - Comprehensive diagnostics
/help - Show this help
/live - Start live mode
/stop - Stop all services
<b>📈 Market Information:</b>
Trading Hours: Mon-Fri 9:00 AM - 3:30 PM IST
Weekends: Markets closed
Holidays: {len(self.config.get('trading_holidays', []))} configured
<b>🖥️ System Commands:</b>
<code>sudo systemctl start postback-server</code>
<code>sudo systemctl start token-generator</code>
<code>sudo systemctl start telegram-bot</code>
<code>sudo systemctl start trading-system</code>
<b>🔍 System Endpoints:</b>
HTTPS: https://{self.config.get('server_host')}/status
HTTP: http://{self.config.get('server_host')}:8001/status
        """
        asyncio.run(self.send_message(help_message))

    def handle_live_command(self):
        """Handle /live command"""
        try:
            ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
            with open('/home/ubuntu/main_trading/.trading_mode', 'w') as f:
                f.write('LIVE')
            subprocess.run(["sudo", "systemctl", "start", "postback-server"], check=True)
            subprocess.run(["sudo", "systemctl", "start", "token-generator"], check=True)
            subprocess.run(["sudo", "systemctl", "start", "telegram-bot"], check=True)
            subprocess.run(["sudo", "systemctl", "start", "trading-system"], check=True)
            asyncio.run(self.send_message(f"""
✅ <b>Live Mode Started</b>
📅 Time: {ist_time}
🖥️ Services: postback-server, token-generator, telegram-bot, trading-system
Authentication URL will be sent daily at 9:00 AM IST on trading days.
Run /status or /health to monitor.
            """))
            # Start trading loop in background
            trading_thread = threading.Thread(
                target=self.trading_runner.run_trading_loop,
                daemon=True
            )
            trading_thread.start()
        except Exception as e:
            asyncio.run(self.send_message(f"""
❌ <b>Live Command Error</b>
📅 Time: {ist_time}
❌ Error: {str(e)}
Check logs: ~/main_trading/logs
            """))
            logger.error(f"Live command error: {e}")

    def handle_stop_command(self):
        """Handle /stop command"""
        try:
            ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
            self.trading_runner.stop()
            subprocess.run(["sudo", "systemctl", "stop", "postback-server"], check=True)
            subprocess.run(["sudo", "systemctl", "stop", "token-generator"], check=True)
            subprocess.run(["sudo", "systemctl", "stop", "trading-system"], check=True)
            requests.get(f"http://localhost:8001/clear_token", timeout=5)
            asyncio.run(self.send_message(f"""
🛑 <b>Services Stopped</b>
📅 Time: {ist_time}
🖥️ Services: postback-server, token-generator, trading-system
Stopping Telegram bot...
            """))
            subprocess.run(["sudo", "systemctl", "stop", "telegram-bot"], check=True)
        except Exception as e:
            asyncio.run(self.send_message(f"""
❌ <b>Stop Command Error</b>
📅 Time: {ist_time}
❌ Error: {str(e)}
Check logs: ~/main_trading/logs
Manually stop services if needed:
<code>sudo systemctl stop postback-server</code>
<code>sudo systemctl stop token-generator</code>
<code>sudo systemctl stop trading-system</code>
<code>sudo systemctl stop telegram-bot</code>
            """))
            logger.error(f"Stop command error: {e}")

    def get_updates(self):
        """Get updates from Telegram Bot API"""
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/getUpdates"
            params = {
                "offset": self.last_update_id + 1,
                "timeout": 30
            }
            response = requests.get(url, params=params, timeout=35)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Telegram getUpdates error: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error getting Telegram updates: {e}")
            return None

    def process_command(self, message):
        """Process incoming command"""
        try:
            text = message.get('text', '').strip().lower()
            chat_id = str(message['chat']['id'])
            if chat_id != str(self.chat_id):
                logger.warning(f"Unauthorized chat ID: {chat_id}")
                return
            logger.info(f"Processing command: {text}")
            if text == '/login':
                self.handle_login_command()
            elif text == '/status':
                self.handle_status_command()
            elif text == '/health':
                self.handle_health_command()
            elif text == '/help' or text == '/start':
                self.handle_help_command()
            elif text == '/live':
                self.handle_live_command()
            elif text == '/stop':
                self.handle_stop_command()
            elif text == '/debug':
                self.handle_debug_command()
            else:
                asyncio.run(self.send_message(f"""
❓ <b>Unknown Command</b>
You sent: <code>{text[:50]}</code>
<b>Available commands:</b>
/login - Authenticate during trading hours
/status - Check system status
/health - Comprehensive diagnostics
/help - Show all commands
/live - Start live mode
/stop - Stop all services
/debug - One-time debug authentication
                """))
        except Exception as e:
            logger.error(f"Error processing command: {e}")
            asyncio.run(self.send_message(f"Error processing command: {str(e)[:100]}"))

    def start_bot(self):
        """Start the Telegram bot listener"""
        self.running = True
        logger.info("Starting Telegram bot listener...")
        startup_message = f"""
🤖 <b>Trading System Bot Started</b>
📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
🔄 Status: Listening for commands
<b>Available commands:</b>
/login - Manual authentication
/status - System status
/health - Comprehensive diagnostics
/help - Show all commands
/live - Start live mode
/stop - Stop all services
/debug - One-time debug authentication
        """
        asyncio.run(self.send_message(startup_message))
        while self.running:
            try:
                updates = self.get_updates()
                if updates and updates.get('ok'):
                    for update in updates.get('result', []):
                        self.last_update_id = update['update_id']
                        if 'message' in update and 'text' in update['message']:
                            self.process_command(update['message'])
                time.sleep(1)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Bot polling error: {e}")
                time.sleep(5)
        logger.info("Telegram bot stopped")

    def stop_bot(self):
        """Stop the Telegram bot listener"""
        self.running = False
        shutdown_message = f"""
🔴 <b>Trading System Bot Stopped</b>
📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
Bot commands are no longer available.
        """
        asyncio.run(self.send_message(shutdown_message))

def main():
    logger.info("Starting telegram_bot_handler.py")
    try:
        bot = TelegramBotHandler()
        bot.start_bot()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
