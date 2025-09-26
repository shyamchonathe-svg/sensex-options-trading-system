#!/usr/bin/env python3
"""
Minimal Telegram bot for data collector
"""
import logging
import requests
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

class TelegramBot:
    """Minimal Telegram bot for notifications"""
    
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.ist = pytz.timezone('Asia/Kolkata')
        logger.info("TelegramBot initialized")
    
    async def send_message(self, message: str):
        """Send a message via Telegram API"""
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
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
                logger.error(f"Telegram message failed: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
