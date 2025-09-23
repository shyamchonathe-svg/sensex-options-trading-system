import os
import datetime
import shutil
from telegram.telegram_bot import sync_send_message
import logging

logger = logging.getLogger()

def zip_daily_data():
    """Zip daily data and delete run logs."""
    date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    data_dir = f'/home/ubuntu/main_trading/data/live_dumps/{date_str}'
    zip_path = f'/home/ubuntu/main_trading/data/zipped/{date_str}.zip'
    if os.path.exists(data_dir):
        os.system(f"zip -r {zip_path} {data_dir}")
        shutil.rmtree(data_dir)
    os.system("find /home/ubuntu/main_trading/logs -type f -name '*.log' -delete")
    logger.info("Daily data zipped, logs deleted")

def zip_weekly_data():
    """Zip daily zips for the week (Friday)."""
    today = datetime.datetime.now()
    if today.weekday() != 4:  # Friday
        return
    week_end = today.strftime('%Y-%m-%d')
    week_start = (today - datetime.timedelta(days=4)).strftime('%Y-%m-%d')
    zip_path = f'/home/ubuntu/main_trading/data/zipped/week_{week_end}.zip'
    os.system(f"zip -r {zip_path} /home/ubuntu/main_trading/data/zipped/{week_start}*.zip")
    logger.info(f"Weekly zip created: {zip_path}")

def zip_monthly_data():
    """Zip weekly zips for the month (last day)."""
    today = datetime.datetime.now()
    last_day = (datetime.datetime(today.year, today.month + 1, 1) - datetime.timedelta(days=1)).day
    if today.day != last_day:
        return
    month = today.strftime('%Y-%m')
    zip_path = f'/home/ubuntu/main_trading/data/zipped/month_{month}.zip'
    os.system(f"zip -r {zip_path} /home/ubuntu/main_trading/data/zipped/week_{month}*.zip")
    logger.info(f"Monthly zip created: {zip_path}")

def check_disk_usage():
    """Check disk usage and alert if >80%."""
    usage = shutil.disk_usage('/home/ubuntu/main_trading/data')
    percentage = (usage.used / usage.total) * 100
    if percentage > 80:
        sync_send_message(f"Disk usage at {percentage:.1f}%! Archive to S3.")
    return percentage
