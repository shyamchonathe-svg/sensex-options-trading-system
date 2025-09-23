#!/usr/bin/env python3
"""
Telegram Bot Command Handler for Trading System
Handles /login, /status, /help commands
"""

import json
import time
import threading
import requests
import pytz
from datetime import datetime, date
import pandas as pd
import logging

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
        """Check if it's a trading day and within trading hours"""
        try:
            now = datetime.now(self.ist_tz)
            
            # Check if weekend
            if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
                return False, "Weekend - Markets closed"
            
            # Check trading hours (9:15 AM to 3:30 PM IST)
            market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
            market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
            
            if now < market_open:
                return False, f"Market opens at 9:15 AM IST. Current time: {now.strftime('%H:%M IST')}"
            elif now > market_close:
                return False, f"Market closed at 3:30 PM IST. Current time: {now.strftime('%H:%M IST')}"
            
            # Check if it's a known holiday (basic implementation)
            # You can enhance this with a proper holiday calendar
            known_holidays = [
                "2025-01-26",  # Republic Day
                "2025-03-14",  # Holi
                "2025-08-15",  # Independence Day
                "2025-10-02",  # Gandhi Jayanti
                # Add more holidays as needed
            ]
            
            today_str = now.strftime("%Y-%m-%d")
            if today_str in known_holidays:
                return False, f"Market holiday: {today_str}"
            
            return True, f"Trading hours active. Current time: {now.strftime('%H:%M IST')}"
            
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
    
    def handle_login_command(self):
        """Handle /login command"""
        try:
            ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
            
            # Check if it's trading hours
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
/help - Show all commands
                """
                self.send_telegram_message(response_message)
                return
            
            # Check if postback server is running
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
• Check status anytime: /status
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
        """Handle /status command"""
        try:
            ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
            is_trading, trading_status = self.is_trading_day_and_hours()
            
            # Check server status
            server_status = "🔴 Offline"
            if self.trading_runner.check_postback_server():
                server_status = "🟢 Online"
            
            # Check token status
            token_status = "❌ No Token"
            token_age = "N/A"
            try:
                import os
                if os.path.exists('latest_token.txt'):
                    with open('latest_token.txt', 'r') as f:
                        token = f.read().strip()
                    if token:
                        # Get token creation time from file modification time
                        token_file_time = datetime.fromtimestamp(os.path.getmtime('latest_token.txt'))
                        token_file_time = self.ist_tz.localize(token_file_time)
                        age_seconds = (datetime.now(self.ist_tz) - token_file_time).total_seconds()
                        
                        if age_seconds < 28800:  # Less than 8 hours (trading day)
                            token_status = f"✅ Valid ({token[:15]}...)"
                            token_age = f"{int(age_seconds/3600)}h {int((age_seconds%3600)/60)}m"
                        else:
                            token_status = "⚠️ Expired"
                            token_age = f"{int(age_seconds/3600)}h old"
            except:
                pass
            
            status_message = f"""
📊 <b>Trading System Status</b>

📅 Time: {ist_time}
⏰ Market: {trading_status}

<b>🖥️ Server Status:</b>
HTTPS Server: {server_status}
Host: sensexbot.ddns.net

<b>🔑 Authentication:</b>
Token: {token_status}
Age: {token_age}

<b>📈 Market Hours:</b>
Mon-Fri: 9:15 AM - 3:30 PM IST
Current: {'🟢 OPEN' if is_trading else '🔴 CLOSED'}

<b>🔄 Available Commands:</b>
/login - Authenticate with Zerodha
/status - This status check
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

<b>📈 Market Information:</b>
Trading Hours: Mon-Fri 9:15 AM - 3:30 PM IST
Weekends: Markets closed
Holidays: Automatically detected

<b>🔧 Manual Script Commands:</b>
<code>python3 integrated_e2e_trading_system.py --mode test</code>
<code>python3 integrated_e2e_trading_system.py --mode live</code>
<code>python3 integrated_e2e_trading_system.py --mode setup</code>

<b>🖥️ Server Commands:</b>
<code>sudo python3 postback_server.py</code> (HTTPS)
<code>python3 postback_server.py --http-only</code> (HTTP)

<b>🔍 System Endpoints:</b>
HTTPS: https://sensexbot.ddns.net/status
HTTP: http://sensexbot.ddns.net:8001/status

<b>💡 Tips:</b>
• Use /login if you missed 9 AM authentication
• Check /status before starting trading
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
