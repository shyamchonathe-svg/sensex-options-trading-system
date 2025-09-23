#!/usr/bin/env python3
"""
Data Collector - Collects Sensex/options data at 3:25 PM IST with WebSocket retries
Integrated with scheduler logic for market close trigger
"""

import asyncio
import logging
from datetime import datetime, time
import pytz
from kiteconnect import KiteConnect, KiteTicker
from tenacity import retry, stop_after_attempt, wait_exponential
from utils.secure_config_manager import SecureConfigManager
from telegram.telegram_bot import TelegramBot
from utils.data_manager import DataManager
import pandas as pd

logger = logging.getLogger(__name__)

class DataCollector:
    def __init__(self):
        self.config_manager = SecureConfigManager()
        self.config = self.config_manager.get_config()
        self.ist = pytz.timezone('Asia/Kolkata')
        self.kite = KiteConnect(api_key=self.config['api_key'])
        self.kite.set_access_token(self.config_manager.get_access_token())
        self.ticker = KiteTicker(self.config['api_key'], self.config_manager.get_access_token())
        self.telegram_bot = TelegramBot(self.config['telegram_token'], self.config['telegram_chat_id'])
        self.data_manager = DataManager(self.config_manager)
        self.running = False
        self.tokens = [26000]  # BSE Sensex token
        logger.info("DataCollector initialized")

    async def should_collect_data(self):
        now = datetime.now(self.ist)
        current_time = now.time()
        target_time = time(15, 25)
        return now.weekday() < 5 and target_time <= current_time < time(15, 30)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def collect_data(self):
        try:
            self.ticker.on_ticks = self.on_ticks
            self.ticker.on_error = self.on_error
            self.ticker.on_close = self.on_close
            self.ticker.on_connect = self.on_connect
            self.ticker.connect()
            await asyncio.sleep(300)  # Collect for 5 minutes
            self.ticker.close()
        except Exception as e:
            logger.error(f"Data collection error: {e}")
            await self.telegram_bot.send_message(f"❌ Data collection failed: {str(e)[:100]}")
            raise

    def on_ticks(self, ws, ticks):
        try:
            date_str = datetime.now(self.ist).strftime("%Y-%m-%d")
            df = pd.DataFrame(ticks)
            df['datetime'] = pd.to_datetime(df['timestamp'])
            df.set_index('datetime', inplace=True)
            filename = f"option_data/SENSEX_{date_str}.csv"
            self.data_manager.save_data(df, filename)
            self.data_manager.latest_data['SENSEX'] = df
            logger.info(f"Saved ticks for {date_str}")
        except Exception as e:
            logger.error(f"Error saving ticks: {e}")

    def on_connect(self, ws, response):
        ws.subscribe(self.tokens)
        ws.set_mode(ws.MODE_FULL, self.tokens)
        logger.info("WebSocket connected")

    def on_close(self, ws, code, reason):
        logger.info(f"WebSocket closed: {code} {reason}")

    def on_error(self, ws, code, reason):
        logger.error(f"WebSocket error: {code} {reason}")

    async def start(self):
        self.running = True
        logger.info("Starting data collection scheduler...")
        await self.telegram_bot.send_message("🔄 Data Collection Started\n⏰ Monitoring for 3:25 PM trigger")
        while self.running:
            try:
                if await self.should_collect_data():
                    logger.info("Market close detected - starting data collection")
                    await self.collect_data()
                    await self.telegram_bot.send_message(f"✅ Data Collection Complete\n📅 {datetime.now(self.ist).strftime('%Y-%m-%d')}")
                wait_time = 30 if await self.should_collect_data() else 300
                await asyncio.sleep(wait_time)
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                await self.telegram_bot.send_message(f"⚠️ Scheduler error: {str(e)[:100]}")
                await asyncio.sleep(60)

    async def stop(self):
        self.running = False
        if self.ticker:
            self.ticker.close()
        await self.telegram_bot.send_message("🛑 Data Collection Stopped")
        logger.info("DataCollector stopped")

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/collect.log'),
            logging.StreamHandler()
        ]
    )
    collector = DataCollector()
    try:
        await collector.start()
    except KeyboardInterrupt:
        await collector.stop()

if __name__ == "__main__":
    asyncio.run(main())
