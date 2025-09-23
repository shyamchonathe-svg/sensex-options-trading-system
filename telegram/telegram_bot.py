import asyncio
from telegram import Bot
from utils.secure_config_manager import load_config
import logging

logger = logging.getLogger()

async def send_telegram_message(message):
    """Send message to Telegram."""
    config = load_config()
    bot = Bot(token=config['telegram_token'])
    await bot.send_message(chat_id=config['telegram_chat_id'], text=message)
    logger.info(f"Telegram message sent: {message}")

def sync_send_message(message):
    """Synchronous wrapper."""
    asyncio.run(send_telegram_message(message))
