#!/usr/bin/env python3
"""
Secure Configuration Manager for Trading System
Handles .env, config.json, and defaults with secret masking
"""
import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import secrets

logger = logging.getLogger(__name__)

class SecureConfigManager:
    """Securely manages configuration with multiple fallback sources."""
    
    def __init__(self, env_file: str = '.env', config_file: str = 'config.json'):
        self.env_file = Path(env_file)
        self.config_file = Path(config_file)
        self.config_cache: Optional[Dict[str, Any]] = None
        self._mask_length = 4
        
        # Default configuration
        self._defaults = {
            # Trading Mode
            "MODE": "TEST",
            "HOST": "127.0.0.1",
            "PORT": 8080,
            "HTTPS": False,
            
            # Zerodha API
            "ZAPI_KEY": "",
            "ZAPI_SECRET": "",
            "ACCESS_TOKEN": "",
            "SENSEX_TOKEN": 256265,  # BSE SENSEX instrument token
            
            # Trading Parameters
            "MAX_TRADES_PER_DAY": 3,
            "MAX_SL_HITS": 2,
            "DAILY_LOSS_CAP": 25000,
            "RISK_PER_TRADE": 0.01,  # 1% risk per trade
            "MIN_BALANCE": 50000,
            "EMA_FAST": 10,
            "EMA_SLOW": 20,
            "VOLATILITY_THRESHOLD": 0.02,  # 2% threshold
            "SL_PERCENT": 0.03,  # 3% stop loss
            "TP_PERCENT": 0.06,  # 6% take profit
            
            # Telegram
            "TELEGRAM_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
            "ENABLE_NOTIFICATIONS": True,
            
            # Data Management
            "DATA_RETENTION_HOT": 90,  # days
            "DATA_RETENTION_WARM": 730,  # 2 years
            "AUTH_TIMEOUT": 1800,  # 30 minutes
            
            # Logging
            "LOG_LEVEL": "INFO",
            "POSTBACK_HOST": "sensexbot.ddns.net",
            "POSTBACK_PORT": 443
        }
        
        self._load_config()
    
    def _load_env(self) -> Dict[str, str]:
        """Load environment variables from .env file."""
        env_data = {}
        if self.env_file.exists():
            try:
                for line in self.env_file.read_text().splitlines():
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            env_data[key.strip()] = value.strip()
                logger.info(f"✅ Loaded {len(env_data)} env vars from {self.env_file}")
            except Exception as e:
                logger.error(f"❌ Failed to load .env: {e}")
        
        # Override with system environment variables
        for key, value in os.environ.items():
            if key in self._defaults:
                env_data[key] = value
        
        return env_data
    
    def _load_json(self) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        json_data = {}
        if self.config_file.exists():
            try:
                json_data = json.loads(self.config_file.read_text())
                logger.info(f"✅ Loaded config from {self.config_file}")
            except Exception as e:
                logger.error(f"❌ Failed to load {self.config_file}: {e}")
        return json_data
    
    def _load_config(self):
        """Load configuration from all sources with priority."""
        env_data = self._load_env()
        json_data = self._load_json()
        
        # Merge with priority: env > json > defaults
        config = self._defaults.copy()
        config.update(json_data)
        config.update(env_data)
        
        # Validate required fields
        required = ['ZAPI_KEY', 'ZAPI_SECRET', 'TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID']
        missing = [key for key in required if not config.get(key)]
        
        if missing:
            raise ValueError(f"❌ Missing required config: {', '.join(missing)}")
        
        # Mask secrets
        self.config_cache = self._mask_secrets(config)
        logger.info("✅ Configuration loaded successfully")
    
    def _mask_secrets(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Mask sensitive values in configuration."""
        masked = config.copy()
        secrets_to_mask = ['ZAPI_KEY', 'ZAPI_SECRET', 'ACCESS_TOKEN', 'TELEGRAM_TOKEN']
        
        for key in secrets_to_mask:
            if key in masked and masked[key]:
                value = masked[key]
                if len(value) > (self._mask_length * 2):
                    masked[key] = f"{value[:self._mask_length]}...{value[-self._mask_length:]}"
                else:
                    masked[key] = f"{value[:2]}***"
        
        return masked
    
    def get_config(self) -> Dict[str, Any]:
        """Get complete configuration with masking."""
        if self.config_cache is None:
            self._load_config()
        return self.config_cache.copy()
    
    def get_raw_value(self, key: str) -> Any:
        """Get raw (unmasked) value for internal use."""
        # Reload env to get raw values
        env_data = self._load_env()
        return env_data.get(key, self._defaults.get(key))
    
    def reload_config(self):
        """Reload configuration from files."""
        logger.info("🔄 Reloading configuration...")
        self.config_cache = None
        self._load_config()
    
    def update_access_token(self, access_token: str) -> bool:
        """Atomically update access token in .env file."""
        try:
            if not self.env_file.exists():
                # Create .env file
                self.env_file.write_text(f"ACCESS_TOKEN={access_token}\n")
                self.env_file.chmod(0o600)
                logger.info(f"✅ Created .env with new token")
                return True
            
            # Read existing content
            lines = self.env_file.read_text().splitlines()
            updated = False
            
            # Update or add ACCESS_TOKEN line
            new_lines = []
            for line in lines:
                if line.strip().startswith('ACCESS_TOKEN='):
                    new_lines.append(f"ACCESS_TOKEN={access_token}")
                    updated = True
                else:
                    new_lines.append(line)
            
            if not updated:
                new_lines.append(f"ACCESS_TOKEN={access_token}")
            
            # Write atomically
            temp_file = self.env_file.with_suffix('.tmp')
            temp_file.write_text('\n'.join(new_lines) + '\n')
            temp_file.chmod(0o600)
            
            # Atomic replace
            self.env_file.unlink()
            temp_file.rename(self.env_file)
            
            logger.info("✅ Access token updated atomically")
            self.reload_config()
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to update access token: {e}")
            return False
    
    def __getattr__(self, name: str):
        """Dynamic attribute access to config values."""
        if self.config_cache is None:
            self._load_config()
        
        raw_value = self.get_raw_value(name)
        masked_value = self.config_cache.get(name, raw_value)
        
        # Return raw for sensitive operations, masked for logging
        sensitive_keys = ['ZAPI_KEY', 'ZAPI_SECRET', 'ACCESS_TOKEN', 'TELEGRAM_TOKEN']
        if name in sensitive_keys and raw_value:
            return raw_value
        return masked_value

# Global instance for easy access
config = SecureConfigManager()
