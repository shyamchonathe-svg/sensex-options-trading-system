"""
Minimal telegram handler - no dependencies issues
"""
import time
import requests
import pytz
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class TelegramBotHandler:
    """Minimal telegram bot handler"""
    
    def __init__(self, config, trading_runner=None):
        self.config = config
        self.trading_runner = trading_runner
        self.telegram_token = config.get('telegram_token')
        self.chat_id = config.get('chat_id')
        self.ist_tz = pytz.timezone('Asia/Kolkata')
        self.running = False
    
    def send_telegram_message(self, message):
        """Send message using direct HTTP API call"""
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            response = requests.post(url, data=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send telegram message: {e}")
            return False
    
    def start_bot(self):
        """Minimal bot start"""
        self.running = True
        message = f"""
🤖 Bot Started
Time: {datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")}
Status: Basic mode (HTTP API only)
        """
        self.send_telegram_message(message)
    
    def stop_bot(self):
        """Stop bot"""
        self.running = False
