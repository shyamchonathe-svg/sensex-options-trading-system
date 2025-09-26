"""
Clean notification module - no conflicts
"""
import asyncio
import logging

try:
    from telegram import Bot
    TELEGRAM_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import telegram: {e}")
    TELEGRAM_AVAILABLE = False
    Bot = None

logger = logging.getLogger(__name__)

class NotificationService:
    """Simple notification service"""
    
    def __init__(self):
        if not TELEGRAM_AVAILABLE:
            raise ImportError("Telegram package not available")
            
        # Import config here to avoid circular imports
        try:
            from utils.secure_config_manager import SecureConfigManager
            config_manager = SecureConfigManager()
            config = config_manager.get_all()
            self.token = config['telegram_token']
            self.chat_id = config['telegram_chat_id']
            self.bot = Bot(token=self.token)
        except Exception as e:
            logger.error(f"Failed to initialize notification service: {e}")
            raise
    
    def send(self, message):
        """Send message synchronously"""
        try:
            asyncio.run(self.send_async(message))
            return True
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False
    
    async def send_async(self, message):
        """Send message asynchronously"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id, 
                text=message, 
                parse_mode='HTML'
            )
            logger.info("Notification sent successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False

# Global instance
_service = None

def get_service():
    global _service
    if _service is None:
        _service = NotificationService()
    return _service

def send_telegram_message(message):
    """Send telegram message"""
    try:
        return get_service().send(message)
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        return False
