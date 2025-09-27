import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/ubuntu/main_trading/test_telegram_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received /test command from user {update.effective_user.id}")
    await update.message.reply_text("Test command received!")

async def main():
    try:
        logger.info("Starting test Telegram bot")
        app = Application.builder().token("8427480734:AAFjkFwNbM9iUo0wa1Biwg8UHmJCvLs5vho").build()
        logger.info("Application built")
        app.add_handler(CommandHandler("test", test_command))
        logger.info("Command handler for /test added")
        await app.initialize()
        logger.info("Bot initialized")
        await app.start()
        logger.info("Bot started")
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot polling started")
    except Exception as e:
        logger.error(f"Bot failed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    logger.info("Starting test_telegram_bot.py")
    import asyncio
    asyncio.run(main())
