import json
import datetime
import requests
from kiteconnect import KiteConnect
from telegram.telegram_bot import sync_send_message
from utils.secure_config_manager import load_config
import logging

logger = logging.getLogger()

def authenticate(mode='test'):
    """Authenticate with Zerodha."""
    config = load_config()
    kite = KiteConnect(api_key=config['api_key'])
    token_file = '/home/ubuntu/main_trading/kite_tokens/token.json'

    # Check existing token
    if os.path.exists(token_file):
        with open(token_file) as f:
            token_data = json.load(f)
        if token_data['expiry'] > datetime.datetime.now().isoformat():
            logger.info("Using existing token")
            return token_data['access_token']

    # Trigger auth at 9:00 AM for test mode
    if mode == 'test' and datetime.datetime.now().hour < 9:
        logger.info("Waiting for 9 AM auth trigger")
        return None

    # Send auth link
    auth_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={config['api_key']}"
    sync_send_message(f"Please authenticate: {auth_url}")
    logger.info("Sent auth URL to Telegram")

    # Wait for token via postback (modify if your postback logic differs)
    token = wait_for_token(config['postback_url'])
    if token:
        token_data = {
            'access_token': token,
            'expiry': (datetime.datetime.now() + datetime.timedelta(days=1)).isoformat()
        }
        os.makedirs('/home/ubuntu/main_trading/kite_tokens', exist_ok=True)
        with open(token_file, 'w') as f:
            json.dump(token_data, f)
        logger.info("Token saved")
        return token
    return None

def wait_for_token(postback_url):
    """Retrieve token from postback URL."""
    try:
        response = requests.get(postback_url, timeout=300)
        data = response.json()
        return data.get('access_token')  # Adjust based on your postback response
    except Exception as e:
        logger.error(f"Postback failed: {e}")
        return None
