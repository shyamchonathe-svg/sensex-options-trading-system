import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

class SecureConfigManager:
    def __init__(self, config_path: str = "/home/ubuntu/main_trading/config.json"):  # Updated path
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            logger.info(f"Configuration loaded from {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"Failed to load config: {e}", exc_info=True)
            raise

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        return self.config

    def update(self, key: str, value: Any) -> None:
        try:
            self.config[key] = value
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
            logger.info(f"Configuration updated: {key}")
        except Exception as e:
            logger.error(f"Failed to update config: {e}", exc_info=True)
            raise
