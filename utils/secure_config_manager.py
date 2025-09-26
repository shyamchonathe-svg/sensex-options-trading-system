#!/usr/bin/env python3
"""
Secure configuration manager
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

class SecureConfigManager:
    """Securely manage configuration"""
    
    def __init__(self, config_path: str = '/home/ubuntu/main_trading/config.json'):
        self.config_path = Path(config_path)
        self._config = self._load_config()
        
        required_keys = [
            'api_key', 'api_secret', 'telegram_token', 'telegram_chat_id',
            'trading_mode', 'server_host', 'auth_timeout_seconds', 'risk_management', 'strategy'
        ]
        missing = [key for key in required_keys if key not in self._config]
        if missing:
            logger.warning(f"Missing configuration keys: {missing}")
    
    def _load_config(self) -> dict:
        """Load configuration from file"""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            logger.info(f"Configuration loaded from {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            raise
    
    def get_all(self) -> dict:
        """Get all configuration settings"""
        return self._config
    
    def get_config(self) -> dict:
        """Alias for get_all"""
        return self.get_all()
    
    def get_access_token(self) -> str:
        """Get access token"""
        return self._config.get('access_token', '')
