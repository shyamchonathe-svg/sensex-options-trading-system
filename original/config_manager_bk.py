#!/usr/bin/env python3
"""
Config Manager - Handles configuration loading and validation
"""

import json
import logging
import os


class ConfigManager:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.logger = logging.getLogger(__name__)
        self.config = self._load_config()
        self._validate_config()
        self.logger.info("Loaded config from config.json")

    def _load_config(self) -> dict:
        """Load configuration from JSON file."""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            return config
        except Exception as e:
            self.logger.error(f"Error loading config: {e}")
            raise

    def _validate_config(self):
        """Validate configuration and set defaults."""
        required_keys = ['api_key', 'api_secret', 'telegram_token', 'chat_id']
        for key in required_keys:
            if key not in self.config:
                self.logger.error(f"Missing required config key: {key}")
                raise ValueError(f"Missing required config key: {key}")
        
        # Set default instruments if not provided
        if 'instruments' not in self.config:
            self.logger.warning("No instruments specified, defaulting to ['SENSEX', 'NIFTY']")
            self.config['instruments'] = ['SENSEX', 'NIFTY']
        
        # Validate instruments
        valid_instruments = ['SENSEX', 'NIFTY']
        invalid_instruments = [inst for inst in self.config['instruments'] if inst not in valid_instruments]
        if invalid_instruments:
            self.logger.warning(f"Invalid instruments found: {invalid_instruments}. Filtering to valid instruments.")
            self.config['instruments'] = [inst for inst in self.config['instruments'] if inst in valid_instruments]
        
        if not self.config['instruments']:
            self.logger.warning("No valid instruments found, defaulting to ['SENSEX', 'NIFTY']")
            self.config['instruments'] = ['SENSEX', 'NIFTY']
        
        # Set default data_dir if not provided
        if 'data_dir' not in self.config:
            self.config['data_dir'] = 'option_data'

    def get_config(self) -> dict:
        """Return the configuration dictionary."""
        return self.config
