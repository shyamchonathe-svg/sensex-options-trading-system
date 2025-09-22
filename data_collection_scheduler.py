#!/usr/bin/env python3
"""
Data Collection Scheduler - Runs continuously, triggers collection at 3:25 PM
"""

import asyncio
import logging
from datetime import datetime
import pytz
from config_manager import SecureConfigManager as ConfigManager
from optimized_sensex_option_chain import OptimizedSensexOptionChain
from data_collector import MarketCloseDataCollector
from notification_service import NotificationService


class DataCollectionScheduler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config_manager = ConfigManager()
        self.config = self.config_manager.get_config()
        self.ist = pytz.timezone('Asia/Kolkata')
        
        # Initialize services
        self.option_chain = OptimizedSensexOptionChain(
            self.config_manager.get_config()['api_key'],  # Will be fixed in security phase
            self.config_manager.get_config()['access_token']
        )
        self.data_collector = MarketCloseDataCollector(self.config_manager, self.option_chain)
        self.notification_service = NotificationService(
            self.config['telegram_token'],
            self.config['chat_id'],
            self.logger
        )
        
        self.running = False
        self.logger.info("DataCollectionScheduler initialized")

    async def start(self):
        """Start the scheduler - runs continuously"""
        self.running = True
        self.logger.info("Starting data collection scheduler...")
        
        # Send startup notification
        await self.notification_service.send_message(
            "🔄 <b>Data Collection Started</b>\n"
            "⏰ Monitoring for 3:25 PM market close trigger"
        )
        
        while self.running:
            try:
                # Check if it's time to collect data
                if await self.data_collector.should_collect_data():
                    self.logger.info("Market close detected - starting data collection")
                    result = await self.data_collector.collect_full_day_data()
                    
                    if result['status'] == 'SUCCESS':
                        await self.notification_service.send_message(
                            f"✅ <b>Data Collection Complete</b>\n"
                            f"📅 {result['date']}: {result['files_collected']} files collected"
                        )
                    else:
                        await self.notification_service.send_message(
                            f"❌ <b>Data Collection Failed</b>\n"
                            f"📅 {datetime.now(self.ist).strftime('%Y-%m-%d')}: {result['reason']}"
                        )
                
                # Wait 30 seconds before next check (near market close)
                # Wait 5 minutes otherwise
                wait_time = 30 if await self.data_collector.should_collect_data() else 300
                await asyncio.sleep(wait_time)
                
            except KeyboardInterrupt:
                self.logger.info("Scheduler interrupted by user")
                break
            except Exception as e:
                self.logger.error(f"Scheduler error: {e}")
                await self.notification_service.send_message(f"⚠️ Scheduler error: {str(e)[:100]}")
                await asyncio.sleep(60)  # Wait 1 minute on errors

    async def stop(self):
        """Stop the scheduler"""
        self.running = False
        await self.notification_service.send_message("🛑 <b>Data Collection Stopped</b>")
        self.logger.info("DataCollectionScheduler stopped")


async def main():
    """Main entry point"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('data_collection.log'),
            logging.StreamHandler()
        ]
    )
    
    scheduler = DataCollectionScheduler()
    try:
        await scheduler.start()
    except KeyboardInterrupt:
        await scheduler.stop()


if __name__ == "__main__":
    asyncio.run(main())
