#!/usr/bin/env python3
"""
Telegram Bot Command Handler for Trading System
Handles /login, /status, /health, /help commands
Updated to use orchestrator's health monitoring capabilities
"""

import json
import time
import threading
import requests
import pytz
import os
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

class TelegramBotHandler:
    def __init__(self, config, trading_runner):
        self.config = config
        self.trading_runner = trading_runner
        self.telegram_token = config.get('telegram_token')
        self.chat_id = config.get('chat_id')
        self.ist_tz = pytz.timezone('Asia/Kolkata')
        self.last_update_id = 0
        self.running = False
        
    def is_trading_day_and_hours(self):
        """Check if it's a trading day and within trading hours using orchestrator"""
        try:
            # Use orchestrator's market validation instead of custom logic
            market_status = self.trading_runner.get_market_status(allow_pre_market=False)
            
            if not market_status.is_trading_day:
                return False, market_status.status_message
            
            if not market_status.is_trading_hours:
                return False, market_status.status_message
            
            return True, market_status.status_message
            
        except Exception as e:
            logger.error(f"Error checking trading hours: {e}")
            return False, f"Unable to verify trading hours: {e}"
    
    def send_telegram_message(self, message):
        """Send message via Telegram bot"""
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                logger.info("Telegram message sent successfully")
                return True
            else:
                logger.error(f"Telegram API error: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    def get_system_resources(self):
        """Get system resource information safely"""
        try:
            import psutil
            return {
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory': psutil.virtual_memory(),
                'disk': psutil.disk_usage('/'),
                'uptime': self._get_system_uptime(),
                'available': True
            }
        except ImportError:
            logger.warning("psutil not available for system resource monitoring")
            return {'available': False}
        except Exception as e:
            logger.error(f"Error getting system resources: {e}")
            return {'available': False, 'error': str(e)}
    
    def _get_system_uptime(self):
        """Get system uptime safely"""
        try:
            import psutil
            uptime_seconds = time.time() - psutil.boot_time()
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            return f"{days}d {hours}h"
        except:
            return "Unknown"
    
    def check_network_connectivity(self):
        """Check network connectivity to important endpoints"""
        connectivity = {}
        
        # Check Zerodha API
        try:
            response = requests.get('https://api.zerodha.com', timeout=5)
            connectivity['zerodha_api'] = {
                'status': '🟢 Reachable' if response.status_code == 200 else f'⚠️ Status {response.status_code}',
                'reachable': response.status_code == 200
            }
        except Exception:
            connectivity['zerodha_api'] = {
                'status': '🔴 Unreachable',
                'reachable': False
            }
        
        # Check if we can reach our own postback server
        try:
            server_url = self.trading_runner.get_postback_server_url()
            if server_url:
                response = requests.get(f"{server_url}/health", timeout=5, verify=False)
                connectivity['postback_server'] = {
                    'status': '🟢 Online' if response.status_code == 200 else f'⚠️ Status {response.status_code}',
                    'reachable': response.status_code == 200,
                    'url': server_url
                }
            else:
                connectivity['postback_server'] = {
                    'status': '🔴 Not Found',
                    'reachable': False,
                    'url': None
                }
        except Exception:
            connectivity['postback_server'] = {
                'status': '🔴 Unreachable',
                'reachable': False,
                'url': None
            }
        
        return connectivity
    
    def handle_health_command(self):
        """Handle /health command using orchestrator's comprehensive health check"""
        try:
            ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
            
            # Use orchestrator's health report
            health_report = self.trading_runner.get_health_report()
            
            # Get additional system information
            system_resources = self.get_system_resources()
            network_status = self.check_network_connectivity()
            
            # Format the comprehensive health message
            health_message = f"""
🏥 <b>System Health Report</b>

📅 Time: {ist_time}

<b>📊 Postback Server:</b>
Status: {'🟢 Online' if health_report['postback_server']['status'] == 'Online' else '🔴 Offline'}
URL: {health_report['postback_server']['url'] or 'Not available'}
Reachable: {'✅ Yes' if health_report['postback_server']['reachable'] else '❌ No'}

<b>📈 Market Status:</b>
Trading Day: {'✅ Yes' if health_report['market']['is_trading_day'] else '❌ No'}
Trading Hours: {'✅ Active' if health_report['market']['is_trading_hours'] else '❌ Closed'}
Status: {health_report['market']['status_message']}

<b>🔑 Authentication:</b>
Valid Token: {'✅ Yes' if health_report['authentication']['has_valid_token'] else '❌ No'}
Token Preview: {health_report['authentication']['token_preview'] or 'None'}
Token Age: {self.trading_runner.get_token_age()}
Needs Refresh: {'⚠️ Yes' if health_report['authentication']['needs_refresh'] else '✅ No'}

<b>🤖 Trading Bot:</b>
Initialized: {'✅ Yes' if health_report['trading_bot']['initialized'] else '❌ No'}
Ready: {'🟢 Ready' if health_report['trading_bot']['ready'] else '🔴 Not Ready'}

<b>📡 Telegram Bot:</b>
Running: {'✅ Yes' if health_report['telegram_bot']['running'] else '❌ No'}

<b>⚙️ Configuration:</b>
Expiry Date: {health_report['configuration']['expiry_date']}
Data Directory: {health_report['configuration']['data_directory']}
Holidays Configured: {health_report['configuration']['holidays_count']}
Next Holiday: {health_report['configuration']['next_holiday'] or 'None upcoming'}
"""
            
            # Add system resources if available
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
            
            # Add network connectivity
            health_message += f"""
<b>🌐 Network Connectivity:</b>
Zerodha API: {network_status['zerodha_api']['status']}
Postback Server: {network_status['postback_server']['status']}
"""
            
            # Health assessment with issue detection
            critical_issues = []
            warnings = []
            
            # Check system resources
            if system_resources.get('available'):
                cpu = system_resources['cpu_percent']
                memory = system_resources['memory']
                disk = system_resources['disk']
                
                if cpu > 80:
                    critical_issues.append("High CPU usage")
                elif cpu > 60:
                    warnings.append("Elevated CPU usage")
                
                if memory.percent > 85:
                    critical_issues.append("High memory usage")
                elif memory.percent > 70:
                    warnings.append("Elevated memory usage")
                
                if disk.percent > 90:
                    critical_issues.append("Low disk space")
                elif disk.percent > 80:
                    warnings.append("Limited disk space")
            
            # Check server status
            if not health_report['postback_server']['reachable']:
                critical_issues.append("Postback server down")
            
            # Check authentication
            if not health_report['authentication']['has_valid_token']:
                if health_report['market']['is_trading_hours']:
                    critical_issues.append("No valid authentication token during trading hours")
                else:
                    warnings.append("Authentication token needed for trading")
            elif health_report['authentication']['needs_refresh']:
                warnings.append("Authentication token may need refresh")
            
            # Check network
            if not network_status['zerodha_api']['reachable']:
                warnings.append("Zerodha API connectivity issues")
            
            # Overall health status
            health_message += f"""
<b>📊 Overall Status:</b>
"""
            
            if critical_issues:
                health_message += f"🔴 <b>CRITICAL</b> - {len(critical_issues)} issue(s)\n"
                for issue in critical_issues[:3]:  # Limit to 3 most important
                    health_message += f"• {issue}\n"
            elif warnings:
                health_message += f"⚠️ <b>WARNING</b> - {len(warnings)} concern(s)\n"
                for warning in warnings[:3]:  # Limit to 3 most important
                    health_message += f"• {warning}\n"
            else:
                health_message += "✅ <b>HEALTHY</b> - All systems operational\n"
            
            # Add action recommendations
            if critical_issues or warnings:
                health_message += f"""
<b>🔧 Recommended Actions:</b>
"""
                if not health_report['postback_server']['reachable']:
                    health_message += "• Restart postback server\n"
                if not health_report['authentication']['has_valid_token'] and health_report['market']['is_trading_hours']:
                    health_message += "• Run /login to authenticate\n"
                if not network_status['zerodha_api']['reachable']:
                    health_message += "• Check internet connectivity\n"
            
            health_message += f"""
<b>🔄 Available Commands:</b>
/status - Quick status check
/login - Authentication (market hours only)
/health - This comprehensive report
/help - All commands
"""
            
            self.send_telegram_message(health_message)
            
        except Exception as e:
            error_message = f"""
❌ <b>Health Command Error</b>

📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
❌ Error: {str(e)[:100]}

Try /status for basic system information.
            """
            self.send_telegram_message(error_message)
            logger.error(f"Health command error: {e}")
    
    def handle_login_command(self):
        """Handle /login command"""
        try:
            ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
            
            # Check if it's trading hours using orchestrator
            is_trading, trading_status = self.is_trading_day_and_hours()
            
            if not is_trading:
                response_message = f"""
❌ <b>Login Not Available</b>

📅 Time: {ist_time}
⏰ Status: {trading_status}

<b>🕘 Trading Hours:</b>
Monday to Friday: 9:15 AM - 3:30 PM IST

<b>🔄 Available Commands:</b>
/status - Check system status
/health - Comprehensive diagnostics
/help - Show all commands
                """
                self.send_telegram_message(response_message)
                return
            
            # Check if postback server is running using orchestrator
            if not self.trading_runner.check_postback_server():
                error_message = f"""
❌ <b>Login Failed - Server Not Available</b>

📅 Time: {ist_time}
🔧 Issue: HTTPS Postback server not responding

<b>📋 Server Commands:</b>
• Start HTTPS: <code>sudo python3 postback_server.py</code>
• Start HTTP: <code>python3 postback_server.py --http-only</code>
• Check status: <code>curl -k https://sensexbot.ddns.net/status</code>

<b>🔍 Troubleshooting:</b>
1. SSH to AWS instance
2. Run server command
3. Try /login again
                """
                self.send_telegram_message(error_message)
                return
            
            # Initiate authentication
            self.send_telegram_message(f"""
🔄 <b>Manual Login Initiated</b>

📅 Time: {ist_time}
🤖 Mode: Telegram Bot Command
⏰ Status: {trading_status}

🔐 Generating secure authentication link...
⏳ Please wait 5 seconds...
            """)
            
            # Start authentication in background
            auth_thread = threading.Thread(
                target=self._background_authentication, 
                args=('telegram-manual',), 
                daemon=True
            )
            auth_thread.start()
            
        except Exception as e:
            error_message = f"""
❌ <b>Login Command Error</b>

📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
❌ Error: {str(e)}

Please try again or use manual script:
<code>python3 integrated_e2e_trading_system.py --mode test</code>
            """
            self.send_telegram_message(error_message)
            logger.error(f"Login command error: {e}")
    
    def _background_authentication(self, mode):
        """Run authentication in background thread"""
        try:
            access_token = self.trading_runner.get_access_token_via_telegram(mode)
            if access_token:
                success_message = f"""
✅ <b>Telegram Login Successful!</b>

📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
🔑 Token: {access_token[:20]}...
🤖 Via: Telegram Bot Command
💾 Saved: latest_token.txt

🚀 <b>System Ready for Trading!</b>

<b>🔄 Next Steps:</b>
• Token valid until market close
• Start trading: <code>python3 integrated_e2e_trading_system.py --mode live</code>
• Check status anytime: /status or /health
                """
                self.send_telegram_message(success_message)
            else:
                failure_message = f"""
❌ <b>Telegram Login Failed</b>

📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
⚠️ Authentication did not complete

<b>🔍 Possible Issues:</b>
• Zerodha login timeout (5 min limit)
• Network connectivity problems  
• Server connectivity issues
• Invalid Zerodha credentials

<b>🔄 Retry Options:</b>
• Try /login again
• Manual: <code>python3 integrated_e2e_trading_system.py --mode test</code>
• Check server: <code>curl -k https://sensexbot.ddns.net/status</code>
• Run diagnostics: /health
                """
                self.send_telegram_message(failure_message)
                
        except Exception as e:
            error_message = f"""
❌ <b>Background Authentication Error</b>

📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
❌ Error: {str(e)[:200]}...

<b>🔧 Technical Details:</b>
This might be a Zerodha API issue or server problem.

<b>🔄 Manual Recovery:</b>
<code>python3 integrated_e2e_trading_system.py --mode test</code>
            """
            self.send_telegram_message(error_message)
            logger.error(f"Background authentication error: {e}")
    
    def handle_status_command(self):
        """Handle /status command using orchestrator's status methods"""
        try:
            ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
            
            # Use orchestrator's detailed status
            status_data = self.trading_runner.get_detailed_status()
            
            # Format status message
            market_status = status_data['market_status']
            postback = status_data['postback_server']
            auth = status_data['authentication']
            trading_bot = status_data['trading_bot']
            system = status_data['system']
            
            status_message = f"""
📊 <b>Trading System Status</b>

📅 Time: {ist_time}
⏰ Market: {market_status.status_message}

<b>🖥️ Server Status:</b>
HTTPS Server: {'🟢 Online' if postback['running'] else '🔴 Offline'}
Host: {postback['host']}
URL: {postback['url'] or 'Not available'}

<b>🔑 Authentication:</b>
Token: {'✅ Valid' if auth['has_token'] else '❌ No Token'}
Preview: {auth['token_preview'] or 'None'}
Age: {auth['token_age']}
Status: {'⚠️ May need refresh' if auth['is_expired'] else '✅ Active'}

<b>📈 Market Info:</b>
Trading Day: {'✅ Yes' if market_status.is_trading_day else '❌ No'}
Trading Hours: {'✅ Active' if market_status.is_trading_hours else '❌ Closed'}
Current: {'🟢 OPEN' if market_status.is_trading_hours else '🔴 CLOSED'}

<b>🤖 Trading Bot:</b>
Initialized: {'✅ Yes' if trading_bot['initialized'] else '❌ No'}

<b>⚙️ Configuration:</b>
Expiry Date: {system['expiry_date']}
Data Directory: {system['data_dir']}
Holidays Count: {len(system['holidays'])}

<b>🔄 Available Commands:</b>
/login - Authenticate with Zerodha
/status - This status check
/health - Comprehensive diagnostics
/help - Show all commands

<b>🔧 Manual Commands:</b>
<code>python3 integrated_e2e_trading_system.py --mode test</code>
<code>python3 integrated_e2e_trading_system.py --mode live</code>
            """
            
            self.send_telegram_message(status_message)
            
        except Exception as e:
            error_message = f"""
❌ <b>Status Check Error</b>

📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
❌ Error: {str(e)}

Basic system appears to be running since you received this message.
Try /health for comprehensive diagnostics.
            """
            self.send_telegram_message(error_message)
            logger.error(f"Status command error: {e}")
    
    def handle_help_command(self):
        """Handle /help command"""
        help_message = f"""
🤖 <b>Trading System Bot Commands</b>

📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}

<b>🔐 Authentication Commands:</b>
/login - Manual Zerodha authentication
         Only works during market hours
         
/status - Check system and token status
         Works anytime

/health - Comprehensive system diagnostics
         CPU, memory, disk, network, logs, processes
         
<b>📈 Market Information:</b>
Trading Hours: Mon-Fri 9:15 AM - 3:30 PM IST
Weekends: Markets closed
Holidays: Automatically detected

<b>🔧 Manual Script Commands:</b>
<code>python3 integrated_e2e_trading_system.py --mode test</code>
<code>python3 integrated_e2e_trading_system.py --mode live</code>
<code>python3 integrated_e2e_trading_system.py --mode setup</code>
<code>python3 integrated_e2e_trading_system.py --mode bot</code>

<b>🖥️ Server Commands:</b>
<code>sudo python3 postback_server.py</code> (HTTPS)
<code>python3 postback_server.py --http-only</code> (HTTP)

<b>🔍 System Endpoints:</b>
HTTPS: https://sensexbot.ddns.net/status
HTTP: http://sensexbot.ddns.net:8001/status

<b>💡 Tips:</b>
• Use /login if you missed 9 AM authentication
• Check /status before starting trading
• Use /health for troubleshooting issues
• Authentication required daily
• Tokens expire at market close

<b>⚠️ Error Recovery:</b>
If bot doesn't respond, use manual script commands on AWS instance.
        """
        self.send_telegram_message(help_message)
    
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
            
            # Verify chat ID matches configuration
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
            else:
                # Unknown command
                self.send_telegram_message(f"""
❓ <b>Unknown Command</b>

You sent: <code>{text[:50]}</code>

<b>Available commands:</b>
/login - Authenticate with Zerodha
/status - Check system status
/health - Comprehensive diagnostics
/help - Show this help

<b>Manual script option:</b>
<code>python3 integrated_e2e_trading_system.py --mode test</code>
                """)
                
        except Exception as e:
            logger.error(f"Error processing command: {e}")
            self.send_telegram_message(f"Error processing command: {str(e)[:100]}")
    
    def start_bot(self):
        """Start the Telegram bot listener"""
        self.running = True
        logger.info("Starting Telegram bot listener...")
        
        # Send startup message
        startup_message = f"""
🤖 <b>Trading System Bot Started</b>

📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
🔄 Status: Listening for commands

<b>Available commands:</b>
/login - Manual authentication
/status - System status
/health - Comprehensive diagnostics
/help - Show all commands

Bot is now monitoring for your commands!
        """
        self.send_telegram_message(startup_message)
        
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
                
                time.sleep(1)  # Small delay between polls
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Bot polling error: {e}")
                time.sleep(5)  # Wait before retry
        
        logger.info("Telegram bot stopped")
    
    def stop_bot(self):
        """Stop the Telegram bot listener"""
        self.running = False
        
        # Send shutdown message
        shutdown_message = f"""
🔴 <b>Trading System Bot Stopped</b>

📅 Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}

Bot commands are no longer available.
Use manual script commands on AWS instance.
        """
        self.send_telegram_message(shutdown_message)
