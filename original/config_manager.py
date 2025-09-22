#!/usr/bin/env python3
"""
Secure Config Manager - Loads from .env + JSON with validation
"""

import json
import logging
import os
from dotenv import load_dotenv
from typing import Dict, Any


class SecureConfigManager:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.logger = logging.getLogger(__name__)
        
        # Load environment variables first (highest priority)
        load_dotenv()
        
        # Load JSON config (lower priority, for non-sensitive settings)
        self.json_config = self._load_json_config()
        
        # Build final config (env vars override JSON)
        self.config = self._build_secure_config()
        
        # Validate everything
        self._validate_config()
        
        self.logger.info("SecureConfigManager initialized - all credentials loaded from environment")

    def _load_json_config(self) -> Dict[str, Any]:
        """Load non-sensitive config from JSON file."""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                self.logger.info(f"Loaded JSON config from {self.config_path}")
                return config
            else:
                self.logger.warning(f"Config file not found: {self.config_path}, using defaults")
                return {}
        except Exception as e:
            self.logger.error(f"Error loading JSON config: {e}")
            return {}

    def _build_secure_config(self) -> Dict[str, Any]:
        """Build final config with environment variable priority."""
        # Sensitive credentials - ALWAYS from environment
        sensitive_config = {
            'api_key': os.getenv('ZAPI_KEY'),
            'api_secret': os.getenv('ZAPI_SECRET'),
            'telegram_token': os.getenv('TELEGRAM_TOKEN'),
            'chat_id': os.getenv('TELEGRAM_CHAT_ID', ''),
        }
        
        # Trading parameters - environment first, then JSON, then defaults
        trading_config = {
            'position_size': int(os.getenv('POSITION_SIZE', 
                                self.json_config.get('position_size', 100))),
            'lot_size': int(os.getenv('LOT_SIZE', 
                            self.json_config.get('lot_size', 20))),
            'max_daily_trades': int(os.getenv('MAX_DAILY_TRADES', 
                                   self.json_config.get('max_daily_trades', 3))),
            'max_consecutive_losses': int(os.getenv('MAX_CONSECUTIVE_LOSSES', 
                                         self.json_config.get('max_consecutive_losses', 2))),
            'max_daily_loss': int(os.getenv('MAX_DAILY_LOSS', 
                                 self.json_config.get('max_daily_loss', -25000))),
            'max_exposure': int(os.getenv('MAX_EXPOSURE', 
                               self.json_config.get('max_exposure', 100000))),
        }
        
        # Data configuration
        data_config = {
            'data_dir': os.getenv('DATA_DIR', self.json_config.get('data_dir', 'option_data')),
            'instruments': self.json_config.get('instruments', ['SENSEX']),
        }
        
        # Risk configuration
        risk_config = {
            'market_holidays': self.json_config.get('market_holidays', []),
        }
        
        # Combine all sections
        final_config = {
            **sensitive_config,
            **trading_config, 
            **data_config,
            **risk_config,
            # Add any other JSON config sections
            **{k: v for k, v in self.json_config.items() 
               if k not in ['api_key', 'api_secret', 'telegram_token', 'chat_id', 
                           'position_size', 'lot_size', 'data_dir', 'instruments']}
        }
        
        return final_config

    def _validate_config(self):
        """Validate all configuration and fail fast if critical issues."""
        # Critical: API credentials
        critical_keys = ['api_key', 'api_secret', 'telegram_token', 'chat_id']
        missing_critical = [key for key in critical_keys if not self.config.get(key)]
        if missing_critical:
            raise ValueError(f"CRITICAL: Missing environment variables: {missing_critical}")
        
        # Validate trading parameters
        if self.config['position_size'] <= 0:
            raise ValueError("POSITION_SIZE must be positive")
        if self.config['lot_size'] <= 0:
            raise ValueError("LOT_SIZE must be positive")
        if self.config['max_daily_trades'] < 1:
            raise ValueError("MAX_DAILY_TRADES must be at least 1")
        
        # Validate paths
        data_dir = self.config['data_dir']
        if not os.path.isabs(data_dir):
            self.config['data_dir'] = os.path.abspath(data_dir)
        
        # Validate instruments
        valid_instruments = ['SENSEX', 'NIFTY']
        self.config['instruments'] = [
            inst for inst in self.config['instruments'] 
            if inst.upper() in [v.upper() for v in valid_instruments]
        ]
        
        if not self.config['instruments']:
            self.config['instruments'] = ['SENSEX']
            self.logger.warning("No valid instruments, defaulting to SENSEX")
        
        self.logger.info(f"Configuration validated - {len(self.config)} parameters loaded")

    def get_config(self) -> Dict[str, Any]:
        """Return the complete validated configuration."""
        return self.config.copy()  # Return copy to prevent modification
    
    def get_sensitive_config(self) -> Dict[str, Any]:
        """Return only non-sensitive configuration for logging."""
        sensitive_keys = ['api_key', 'api_secret', 'telegram_token']
        safe_config = {k: v for k, v in self.config.items() if k not in sensitive_keys}
        return safe_config
    
    def reload_config(self):
        """Reload configuration (useful for runtime changes)."""
        self.logger.info("Reloading configuration...")
        self.config = self._build_secure_config()
        self._validate_config()
        self.logger.info("Configuration reloaded successfully")
