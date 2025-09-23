import json
import os
import logging

logger = logging.getLogger()

def load_config():
    """Load config securely."""
    config_path = '/home/ubuntu/main_trading/config.json'
    if not os.path.exists(config_path):
        logger.error("Config file not found")
        raise FileNotFoundError("Config file not found")
    with open(config_path) as f:
        return json.load(f)
