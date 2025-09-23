"""
Secure configuration loader with environment validation
"""
import os
import json
from typing import Dict, Any
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

class ConfigLoader:
    """Loads and validates configuration from .env and config.json"""
    
    REQUIRED_ENV_VARS = [
        'ZAPI_KEY',
        'ZAPI_SECRET', 
        'TELEGRAM_TOKEN',
        'TELEGRAM_CHAT_ID'
    ]
    
    @staticmethod
    def load() -> Dict[str, Any]:
        """Load and validate all configuration"""
        # Load environment variables
        load_dotenv()
        
        # Validate required environment variables
        missing_vars = []
        for var in ConfigLoader.REQUIRED_ENV_VARS:
            if not os.getenv(var):
                missing_vars.append(var)
        
        if missing_vars:
            error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Load trading parameters from config.json
        try:
            with open('config.json', 'r') as f:
                trading_params = json.load(f)
        except FileNotFoundError:
            logger.error("config.json not found. Creating default...")
            default_config = {
                "ema_short": 10,
                "ema_long": 20,
                "channel_threshold": 0.5,
                "max_daily_trades": 3,
                "max_daily_loss": 25000,
                "min_position_size": 20,
                "max_position_size": 100,
                "instrument_token": 260105,  # SENSEX
                "trading_symbol": "SENSEX",
                "interval": "3minute"
            }
            with open('config.json', 'w') as f:
                json.dump(default_config, f, indent=2)
            trading_params = default_config
        
        # Combine environment and trading config
        config = trading_params.copy()
        config.update({
            'ZAPI_KEY': os.getenv('ZAPI_KEY'),
            'ZAPI_SECRET': os.getenv('ZAPI_SECRET'),
            'TELEGRAM_TOKEN': os.getenv('TELEGRAM_TOKEN'),
            'TELEGRAM_CHAT_ID': os.getenv('TELEGRAM_CHAT_ID')
        })
        
        logger.info("Configuration loaded successfully")
        return config
