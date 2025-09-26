#!/usr/bin/env python3
"""
Zipper module for compressing files and sending notifications
"""
import os
import datetime
import shutil
import logging
from telegram_handler import TelegramBotHandler
from utils.secure_config_manager import SecureConfigManager

logger = logging.getLogger(__name__)

class Zipper:
    """Handles zipping of daily, weekly, and monthly data, and disk usage monitoring."""
    
    def __init__(self, config_manager: SecureConfigManager):
        self.config_manager = config_manager
        self.config = config_manager.get_all()
        self.data_dir = self.config.get('data_dir', '/home/ubuntu/main_trading/data/live_dumps')
        self.zip_dir = self.config.get('zip_dir', '/home/ubuntu/main_trading/data/zipped')
        self.telegram = TelegramBotHandler(
            self.config.get('telegram_token'),
            self.config.get('telegram_chat_id')
        )
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.zip_dir, exist_ok=True)
        logger.info("Zipper initialized")
    
    def zip_daily_data(self):
        """Zip daily data and delete run logs."""
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        data_dir = os.path.join(self.data_dir, date_str)
        zip_path = os.path.join(self.zip_dir, f"{date_str}.zip")
        try:
            if os.path.exists(data_dir):
                os.system(f"zip -r {zip_path} {data_dir}")
                shutil.rmtree(data_dir)
                logger.info(f"Zipped daily data: {zip_path}")
                self.telegram.send_message(f"📦 Zipped daily data: {zip_path}")
            os.system("find /home/ubuntu/main_trading/logs -type f -name '*.log' -delete")
            logger.info("Logs deleted")
        except Exception as e:
            logger.error(f"Failed to zip daily data: {e}")
            self.telegram.send_message(f"❌ Failed to zip daily data: {str(e)[:200]}")
    
    def zip_weekly_data(self):
        """Zip daily zips for the week (Friday)."""
        today = datetime.datetime.now()
        if today.weekday() != 4:  # Friday
            return
        week_end = today.strftime('%Y-%m-%d')
        week_start = (today - datetime.timedelta(days=4)).strftime('%Y-%m-%d')
        zip_path = os.path.join(self.zip_dir, f"week_{week_end}.zip")
        try:
            os.system(f"zip -r {zip_path} {self.zip_dir}/{week_start}*.zip")
            logger.info(f"Weekly zip created: {zip_path}")
            self.telegram.send_message(f"📦 Weekly zip created: {zip_path}")
        except Exception as e:
            logger.error(f"Failed to zip weekly data: {e}")
            self.telegram.send_message(f"❌ Failed to zip weekly data: {str(e)[:200]}")
    
    def zip_monthly_data(self):
        """Zip weekly zips for the month (last day)."""
        today = datetime.datetime.now()
        last_day = (datetime.datetime(today.year, today.month + 1, 1) - datetime.timedelta(days=1)).day
        if today.day != last_day:
            return
        month = today.strftime('%Y-%m')
        zip_path = os.path.join(self.zip_dir, f"month_{month}.zip")
        try:
            os.system(f"zip -r {zip_path} {self.zip_dir}/week_{month}*.zip")
            logger.info(f"Monthly zip created: {zip_path}")
            self.telegram.send_message(f"📦 Monthly zip created: {zip_path}")
        except Exception as e:
            logger.error(f"Failed to zip monthly data: {e}")
            self.telegram.send_message(f"❌ Failed to zip monthly data: {str(e)[:200]}")
    
    def check_disk_usage(self):
        """Check disk usage and alert if >80%."""
        try:
            usage = shutil.disk_usage(self.data_dir)
            percentage = (usage.used / usage.total) * 100
            if percentage > 80:
                self.telegram.send_message(f"⚠️ Disk usage at {percentage:.1f}%! Archive to S3.")
            logger.info(f"Disk usage: {percentage:.1f}%")
            return percentage
        except Exception as e:
            logger.error(f"Failed to check disk usage: {e}")
            self.telegram.send_message(f"❌ Failed to check disk usage: {str(e)[:200]}")
            return 0.0
    
    async def unzip_data(self, date_str: str):
        """Unzip data for a specific date."""
        zip_path = os.path.join(self.zip_dir, f"{date_str}.zip")
        try:
            if os.path.exists(zip_path):
                os.system(f"unzip -o {zip_path} -d {self.data_dir}")
                logger.info(f"Unzipped data: {zip_path}")
                self.telegram.send_message(f"📤 Unzipped data: {zip_path}")
        except Exception as e:
            logger.error(f"Failed to unzip data: {e}")
            self.telegram.send_message(f"❌ Failed to unzip data: {str(e)[:200]}")
