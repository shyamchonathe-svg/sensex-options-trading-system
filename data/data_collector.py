from kiteconnect import KiteTicker, KiteConnect
from tenacity import retry, stop_after_attempt, wait_exponential
import pandas as pd
import os
import datetime
import logging
from telegram.telegram_bot import sync_send_message
from utils.secure_config_manager import load_config

logger = logging.getLogger()

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=60))
def connect_websocket(kite, tokens):
    """Connect to Kite WebSocket with retry and heartbeat."""
    kws = KiteTicker(kite.api_key, kite.access_token)
    kws.on_connect = lambda ws, response: ws.subscribe(tokens)
    kws.on_close = lambda ws, code, reason: ws.stop()
    kws.on_error = lambda ws, code, reason: raise Exception(f"WebSocket error: {reason}")
    kws.on_reconnect = lambda ws, attempts: logger.info(f"Reconnecting WebSocket, attempt {attempts}")
    kws.on_ticks = on_ticks
    kws.connect()
    return kws

def on_ticks(ws, ticks):
    """Save WebSocket ticks to CSV."""
    date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    os.makedirs(f'/home/ubuntu/main_trading/data/live_dumps/{date_str}', exist_ok=True)
    df = pd.DataFrame(ticks)
    df.to_csv(f'/home/ubuntu/main_trading/data/live_dumps/{date_str}/options.csv', mode='a', index=False)

def collect_data(mode='test'):
    """Collect options, Sensex data, and trades daily."""
    logger.info(f"Collecting data in {mode} mode")
    config = load_config()
    kite = KiteConnect(api_key=config['api_key'])
    
    with open('/home/ubuntu/main_trading/kite_tokens/token.json') as f:
        kite.set_access_token(json.load(f)['access_token'])

    # Fetch Sensex data
    sensex = kite.quote('NSE:SENSEX')  # Adjust symbol
    date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    os.makedirs(f'/home/ubuntu/main_trading/data/live_dumps/{date_str}', exist_ok=True)
    pd.DataFrame([sensex]).to_csv(f'/home/ubuntu/main_trading/data/live_dumps/{date_str}/sensex.csv', index=False)

    # Fetch options data via WebSocket
    tokens = [12345]  # Replace with Sensex/option instrument tokens
    kws = connect_websocket(kite, tokens)

    # Collect trades in test mode
    if mode == 'test':
        trades = kite.orders()  # Adjust for test mode orders
        pd.DataFrame(trades).to_csv(f'/home/ubuntu/main_trading/data/live_dumps/{date_str}/trades.csv', index=False)
