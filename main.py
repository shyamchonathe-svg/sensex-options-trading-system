import argparse
import logging
import re
import datetime
import os
from auth_data.debug_token_generator import authenticate
from data.data_collector import collect_data
from telegram.telegram_bot import sync_send_message
from utils.zipper import zip_daily_data, check_disk_usage

# Log redaction
class RedactingFilter(logging.Filter):
    def __init__(self, patterns):
        super().__init__()
        self.patterns = [re.compile(pattern) for pattern in patterns]
    def filter(self, record):
        record.msg = self.redact(str(record.msg))
        return True
    def redact(self, message):
        for pattern in self.patterns:
            message = pattern.sub('****', message)
        return message

logging.basicConfig(
    filename='/home/ubuntu/main_trading/logs/trading.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger()
logger.addFilter(RedactingFilter([r'api_key=\S+', r'token=\S+', r'secret=\S+']))

def run_debug_mode(date_str):
    logger.info(f"Starting debug mode for {date_str}")
    token = authenticate(mode='debug')
    if not token:
        logger.error("Debug mode auth failed")
        sync_send_message("Debug mode auth failed!")
        return
    os.makedirs('/home/ubuntu/main_trading/data/debug_temp', exist_ok=True)
    os.system(f"unzip -o /home/ubuntu/main_trading/data/zipped/{date_str}.zip -d /home/ubuntu/main_trading/data/debug_temp")
    results = run_strategy(f"/home/ubuntu/main_trading/data/debug_temp/{date_str}")
    sync_send_message(f"Debug {date_str}: {'Pass' if results['pass'] else 'Fail'}\nErrors: {results.get('errors', 'None')}")
    os.system("rm -rf /home/ubuntu/main_trading/data/debug_temp")
    logger.info(f"Debug mode for {date_str} completed")

def run_test_mode():
    logger.info("Starting test mode")
    token = authenticate(mode='test')
    if not token:
        logger.error("Test mode auth failed")
        sync_send_message("Test mode auth failed!")
        return
    collect_data(mode='test')
    logger.info("Test mode completed")

def run_strategy(data_path):
    import pandas as pd
    try:
        df = pd.read_csv(f"{data_path}/options.csv")
        # Replace with your strategy logic from sensex_trading_bot_debug.py
        return {'pass': True, 'errors': 'None'}
    except Exception as e:
        return {'pass': False, 'errors': str(e)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['debug', 'test'], required=True)
    parser.add_argument('--date', help='Date for debug mode (YYYY-MM-DD)')
    args = parser.parse_args()

    usage = check_disk_usage()
    if usage > 80:
        sync_send_message(f"Disk usage at {usage:.1f}%! Archive to S3.")

    if args.mode == 'debug':
        if not args.date:
            logger.error("Date required for debug mode")
            sync_send_message("Date required for debug mode!")
            return
        run_debug_mode(args.date)
    elif args.mode == 'test':
        run_test_mode()

if __name__ == "__main__":
    main()
