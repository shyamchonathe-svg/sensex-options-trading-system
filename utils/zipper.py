import os
import datetime
import shutil
from telegram_handler import TelegramBotHandler
import logging

logger = logging.getLogger(__name__)

class Zipper:
    """Handles zipping of daily, weekly, and monthly data, and disk usage monitoring."""

    def __init__(self, config, telegram_bot=None):
        self.config = config
        self.telegram_bot = telegram_bot
        logger.info("Zipper initialized")

    def zip_daily_data(self):
        """Zip daily data and delete run logs."""
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        data_dir = f'/home/ubuntu/main_trading/data/live_dumps/{date_str}'
        zip_path = f'/home/ubuntu/main_trading/data/zipped/{date_str}.zip'
        if os.path.exists(data_dir):
            os.system(f"zip -r {zip_path} {data_dir}")
            shutil.rmtree(data_dir)
        os.system("find /home/ubuntu/main_trading/logs -type f -name '*.log' -delete")
        logger.info("Daily data zipped, logs deleted")

    def zip_weekly_data(self):
        """Zip daily zips for the week (Friday)."""
        today = datetime.datetime.now()
        if today.weekday() != 4:  # Friday
            return
        week_end = today.strftime('%Y-%m-%d')
        week_start = (today - datetime.timedelta(days=4)).strftime('%Y-%m-%d')
        zip_path = f'/home/ubuntu/main_trading/data/zipped/week_{week_end}.zip'
        os.system(f"zip -r {zip_path} /home/ubuntu/main_trading/data/zipped/{week_start}*.zip")
        logger.info(f"Weekly zip created: {zip_path}")

    def zip_monthly_data(self):
        """Zip weekly zips for the month (last day)."""
        today = datetime.datetime.now()
        last_day = (datetime.datetime(today.year, today.month + 1, 1) - datetime.timedelta(days=1)).day
        if today.day != last_day:
            return
        month = today.strftime('%Y-%m')
        zip_path = f'/home/ubuntu/main_trading/data/zipped/month_{month}.zip'
        os.system(f"zip -r {zip_path} /home/ubuntu/main_trading/data/zipped/week_{month}*.zip")
        logger.info(f"Monthly zip created: {zip_path}")

    def check_disk_usage(self):
        """Check disk usage and alert if >80%."""
        usage = shutil.disk_usage('/home/ubuntu/main_trading/data')
        percentage = (usage.used / usage.total) * 100
        if percentage > 80 and self.telegram_bot:
            self.telegram_bot.send_telegram_message(f"Disk usage at {percentage:.1f}%! Archive to S3.")
        return percentage
