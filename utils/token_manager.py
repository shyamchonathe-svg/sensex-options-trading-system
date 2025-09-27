#!/usr/bin/env python3
"""
Token Manager - Centralized token handling
"""

import os
import json
import logging
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

class TokenManager:
    def __init__(self):
        self.ist_tz = pytz.timezone('Asia/Kolkata')
        self.token_config_file = '/home/ubuntu/main_trading/data/token_config.json'
        self.load_config()

    def load_config(self):
        """Load token configuration"""
        try:
            with open(self.token_config_file, 'r') as f:
                self.config = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load token config: {e}")
            self.config = {
                "request_token_file": "/home/ubuntu/main_trading/data/request_token.txt",
                "access_token_file": "/home/ubuntu/main_trading/data/access_token.txt",
                "token_backup_dir": "/home/ubuntu/main_trading/data/tokens",
                "token_timeout_seconds": 300
            }

    def get_request_token(self):
        """Get current request token"""
        try:
            token_file = self.config['request_token_file']
            if os.path.exists(token_file):
                with open(token_file, 'r') as f:
                    token = f.read().strip()
                
                # Check if token is still valid
                if os.path.exists(f"{token_file}.meta"):
                    with open(f"{token_file}.meta", 'r') as f:
                        metadata = json.load(f)
                    
                    token_time = datetime.fromisoformat(metadata['timestamp'])
                    age = (datetime.now(self.ist_tz) - token_time).total_seconds()
                    
                    if age > self.config['token_timeout_seconds']:
                        logger.warning(f"Request token expired: {age}s old")
                        return None
                
                return token
            return None
        except Exception as e:
            logger.error(f"Failed to get request token: {e}")
            return None

    def save_access_token(self, access_token):
        """Save access token with metadata"""
        try:
            timestamp = datetime.now(self.ist_tz)
            
            # Save main token
            token_file = self.config['access_token_file']
            with open(token_file, 'w') as f:
                f.write(access_token)
            
            # Save backup
            backup_file = f"{self.config['token_backup_dir']}/access_token_{timestamp.strftime('%Y%m%d_%H%M%S')}.txt"
            with open(backup_file, 'w') as f:
                f.write(access_token)
            
            # Save metadata
            metadata = {
                'token': access_token[:10] + '...',
                'timestamp': timestamp.isoformat(),
                'type': 'access_token',
                'server_time': timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')
            }
            
            with open(f"{token_file}.meta", 'w') as f:
                json.dump(metadata, f, indent=2)
            
            logger.info(f"Access token saved: {token_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save access token: {e}")
            return False

    def get_access_token(self):
        """Get current access token"""
        try:
            token_file = self.config['access_token_file']
            if os.path.exists(token_file):
                with open(token_file, 'r') as f:
                    return f.read().strip()
            return None
        except Exception as e:
            logger.error(f"Failed to get access token: {e}")
            return None
