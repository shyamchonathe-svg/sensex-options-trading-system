import json
import os
import logging
from typing import Dict, Any, Optional
import stat

logger = logging.getLogger(__name__)

class SecureConfigManager:
    """
    Secure configuration manager for handling API keys and sensitive settings.
    Supports both .env files and config.json with fallback logic.
    """
    
    def __init__(self, config_path: str = None):
        """
        Initialize the SecureConfigManager.
        
        Args:
            config_path (str): Optional path to config file. Auto-detects if None.
        """
        self.config_data = {}
        self.config_path = config_path or self._find_config_file()
        self._load_config()
    
    def _find_config_file(self) -> str:
        """Auto-detect configuration file location."""
        possible_paths = [
            '/home/ubuntu/main_trading/config.json',
            'config.json',
            './config.json'
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        # If no config.json found, we'll create one from .env
        return '/home/ubuntu/main_trading/config.json'
    
    def _load_env_file(self) -> Dict[str, Any]:
        """Load configuration from .env file and convert to expected format."""
        env_path = '/home/ubuntu/main_trading/.env'
        env_config = {}
        
        if os.path.exists(env_path):
            logger.info("Loading configuration from .env file")
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_config[key.strip()] = value.strip()
            
            # Convert .env format to expected config.json format
            config = {
                "api_key": env_config.get("ZAPI_KEY"),
                "api_secret": env_config.get("ZAPI_SECRET"),
                "telegram_token": env_config.get("TELEGRAM_TOKEN"),
                "chat_id": env_config.get("TELEGRAM_CHAT_ID"),
                "trading_mode": env_config.get("TRADING_MODE", "paper"),
                "server_host": "sensexbot.ddns.net",
                "auth_timeout_seconds": 300,
                "risk_management": {
                    "max_daily_loss": 25000,
                    "max_trades_per_day": 3,
                    "risk_per_trade_percent": 2
                },
                "strategy": {
                    "ema_short_period": 10,
                    "ema_long_period": 20,
                    "ema_tightness_threshold": 51
                }
            }
            
            # Save as config.json for future use
            try:
                with open(self.config_path, 'w') as f:
                    json.dump(config, f, indent=4)
                logger.info(f"Created config.json from .env at {self.config_path}")
            except Exception as e:
                logger.warning(f"Could not save config.json: {e}")
            
            return config
        
        return {}
    
    def _load_config(self) -> None:
        """Load configuration from file with security checks."""
        try:
            # First try to load from config.json
            if os.path.exists(self.config_path):
                self._check_file_permissions(self.config_path)
                
                with open(self.config_path, 'r') as f:
                    self.config_data = json.load(f)
                logger.info(f"Configuration loaded from {self.config_path}")
            
            # If config.json doesn't exist or is empty, try .env
            elif not self.config_data:
                self.config_data = self._load_env_file()
            
            # Validate required keys
            self._validate_config()
            
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {self.config_path}")
            # Try to load from .env as fallback
            self.config_data = self._load_env_file()
            if not self.config_data:
                raise FileNotFoundError("No configuration file found (config.json or .env)")
        
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            raise ValueError(f"Invalid JSON in config file: {e}")
        
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            raise
    
    def _check_file_permissions(self, file_path: str) -> None:
        """Check and fix file permissions for security."""
        try:
            file_stat = os.stat(file_path)
            
            # Check if file is readable by group/others (security risk)
            if file_stat.st_mode & 0o044:  # Check read permissions for group/other
                logger.warning(f"Config file {file_path} has overly permissive permissions")
                try:
                    os.chmod(file_path, 0o600)  # Set to read/write for owner only
                    logger.info(f"Fixed permissions for {file_path}")
                except PermissionError:
                    logger.warning("Could not fix file permissions. Continuing anyway.")
        
        except Exception as e:
            logger.warning(f"Could not check file permissions: {e}")
    
    def _validate_config(self) -> None:
        """Validate that required configuration keys are present."""
        required_keys = ['api_key', 'telegram_token', 'chat_id']
        missing_keys = []
        
        for key in required_keys:
            if not self.config_data.get(key):
                missing_keys.append(key)
        
        if missing_keys:
            logger.warning(f"Missing configuration keys: {missing_keys}")
            # Don't raise error, just warn - some modes might not need all keys
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by key.
        
        Args:
            key (str): Configuration key (supports dot notation for nested keys)
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        try:
            # Support dot notation for nested keys (e.g., 'risk_management.max_daily_loss')
            keys = key.split('.')
            value = self.config_data
            
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    return default
            
            return value
        
        except Exception:
            return default
    
    def get_all(self) -> Dict[str, Any]:
        """Get all configuration data."""
        return self.config_data.copy()
    
    def set(self, key: str, value: Any) -> None:
        """
        Set configuration value.
        
        Args:
            key (str): Configuration key (supports dot notation)
            value: Value to set
        """
        try:
            keys = key.split('.')
            config = self.config_data
            
            # Navigate to the parent of the target key
            for k in keys[:-1]:
                if k not in config or not isinstance(config[k], dict):
                    config[k] = {}
                config = config[k]
            
            # Set the final key
            config[keys[-1]] = value
            
        except Exception as e:
            logger.error(f"Error setting configuration key {key}: {e}")
            raise
    
    def save(self) -> None:
        """Save current configuration to file."""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config_data, f, indent=4)
            
            # Set secure permissions
            self._check_file_permissions(self.config_path)
            logger.info(f"Configuration saved to {self.config_path}")
            
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            raise

# Legacy function for backward compatibility
def load_config():
    """
    Legacy function for backward compatibility.
    Use SecureConfigManager class instead.
    """
    manager = SecureConfigManager()
    return manager.get_all()
