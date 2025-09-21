#!/usr/bin/env python3
"""
SecureConfigManager - Loads .env configuration for EC2 deployment.
Handles token expiry and atomic updates for trading bot.
"""
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
import logging
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

class SecureConfigManager:
    """Loads .env configuration for EC2 deployment."""
    
    def __init__(self, env_file: str = '.env'):
        self.env_file = Path(env_file)
        if self.env_file.exists():
            load_dotenv(self.env_file)
        else:
            print(f"⚠️  Warning: {env_file} not found. Using environment variables only.")
        self._load_and_validate()
    
    def _load_and_validate(self):
        """Load all configuration variables with validation."""
        # Zerodha API
        self.ZAPI_KEY = os.getenv('ZAPI_KEY', '')
        self.ZAPI_SECRET = os.getenv('ZAPI_SECRET', '') 
        self.ACCESS_TOKEN = os.getenv('ACCESS_TOKEN', '')
        
        # Telegram
        self.TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '')
        self.TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
        
        # Trading Mode
        self.MODE = os.getenv('MODE', 'TEST').upper()
        
        # Auth Server
        self.POSTBACK_HOST = os.getenv('POSTBACK_HOST', 'localhost')
        self.POSTBACK_PORT = int(os.getenv('POSTBACK_PORT', '8080'))
        self.USE_HTTPS = os.getenv('USE_HTTPS', 'false').lower() == 'true'
        self.AUTH_TIMEOUT = int(os.getenv('AUTH_TIMEOUT', '300'))
        
        # Risk Management
        self.MAX_DAILY_TRADES = int(os.getenv('MAX_DAILY_TRADES', '3'))
        self.DAILY_LOSS_CAP = float(os.getenv('DAILY_LOSS_CAP', '25000'))
        self.CONSECUTIVE_LOSS_LIMIT = int(os.getenv('CONSECUTIVE_LOSS_LIMIT', '2'))
        self.LOT_SIZE = int(os.getenv('LOT_SIZE', '20'))
        self.POSITION_SIZE = int(os.getenv('POSITION_SIZE', '100'))
        
        # Technical Parameters
        self.EMA_FAST_PERIOD = int(os.getenv('EMA_FAST_PERIOD', '10'))
        self.EMA_SLOW_PERIOD = int(os.getenv('EMA_SLOW_PERIOD', '20'))
        self.RANGE_THRESHOLD_SENSEX = float(os.getenv('RANGE_THRESHOLD_SENSEX', '51'))
        self.RANGE_THRESHOLD_PREMIUM = float(os.getenv('RANGE_THRESHOLD_PREMIUM', '15'))
        self.TARGET_POINTS = float(os.getenv('TARGET_POINTS', '25'))
        self.STOP_LOSS_POINTS = float(os.getenv('STOP_LOSS_POINTS', '15'))
        
        # Instruments
        self.SENSEX_TOKEN = os.getenv('SENSEX_TOKEN', '256265')
        self.NIFTY_TOKEN = os.getenv('NIFTY_TOKEN', '260105')
        
        # Market Holidays
        holidays_str = os.getenv('MARKET_HOLIDAYS', '')
        self.MARKET_HOLIDAYS = [h.strip() for h in holidays_str.split(',') if h.strip()]
        
        # Validation
        self._validate_required()
        self._check_token_expiry()
        
        # Create directories
        for dir_name in ['auth_data', 'logs', 'data_raw', 'archives']:
            Path(dir_name).mkdir(exist_ok=True)
        
        print(f"✅ Config loaded - Mode: {self.MODE}, HTTPS: {self.USE_HTTPS}")
    
    def _validate_required(self):
        """Validate required environment variables."""
        required = {
            'ZAPI_KEY': self.ZAPI_KEY,
            'ZAPI_SECRET': self.ZAPI_SECRET,
            'TELEGRAM_TOKEN': self.TELEGRAM_TOKEN,
            'TELEGRAM_CHAT_ID': self.TELEGRAM_CHAT_ID
        }
        
        missing = [k for k, v in required.items() if not v]
        if missing:
            print(f"⚠️  WARNING: Missing env vars: {', '.join(missing)}")
            print("💡 Create .env file with your credentials")
    
    def _check_token_expiry(self):
        """Check if access token is expired."""
        if not self.ACCESS_TOKEN:
            return
        
        now = datetime.now(IST)
        # Zerodha tokens expire at 9 AM next day
        expiry_today = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now.date() > expiry_today.date():
            print("⚠️  ACCESS_TOKEN appears expired - use /auth to refresh")
            self.ACCESS_TOKEN = ''
    
    def update_access_token(self, new_token: str) -> bool:
        """Atomically update ACCESS_TOKEN in .env file."""
        if not new_token or len(new_token) != 32:
            print(f"❌ Invalid token length: {len(new_token) if new_token else 0}")
            return False
        
        try:
            # Create .env if it doesn't exist
            if not self.env_file.exists():
                print(f"📝 Creating new .env file: {self.env_file}")
                self.env_file.touch()
            
            # Read current .env content
            content = self.env_file.read_text(encoding='utf-8') if self.env_file.stat().st_size > 0 else ''
            lines = content.splitlines() if content else []
            
            # Update ACCESS_TOKEN line
            updated_lines = []
            updated = False
            
            for line in lines:
                if line.strip().startswith('ACCESS_TOKEN='):
                    updated_lines.append(f'ACCESS_TOKEN={new_token}')
                    updated = True
                else:
                    updated_lines.append(line)
            
            # Add if not present
            if not updated:
                updated_lines.append(f'\n# Daily Access Token (updated via /auth)')
                updated_lines.append(f'ACCESS_TOKEN={new_token}')
            
            # Atomic write
            temp_file = self.env_file.with_suffix('.tmp')
            temp_file.write_text('\n'.join(updated_lines) + '\n', encoding='utf-8')
            temp_file.replace(self.env_file)
            
            # Secure permissions
            self.env_file.chmod(0o600)
            
            # Update in-memory
            self.ACCESS_TOKEN = new_token
            
            print(f"✅ ACCESS_TOKEN updated (masked: {new_token[:8]}...)")
            return True
            
        except Exception as e:
            print(f"❌ Failed to update ACCESS_TOKEN: {e}")
            if 'temp_file' in locals() and temp_file.exists():
                temp_file.unlink()
            return False
    
    def get_auth_url(self) -> str:
        """Get complete auth server URL."""
        protocol = 'https' if self.USE_HTTPS else 'http'
        return f"{protocol}://{self.POSTBACK_HOST}:{self.POSTBACK_PORT}"
    
    def is_market_holiday(self) -> bool:
        """Check if today is a market holiday."""
        today = datetime.now(IST).strftime('%Y-%m-%d')
        return today in self.MARKET_HOLIDAYS
    
    def is_market_open(self) -> bool:
        """Check if market is currently open."""
        if self.is_market_holiday():
            return False
        
        now = datetime.now(IST)
        # Trading window: 9:18 AM - 3:15 PM IST
        if now.hour < 9 or now.hour > 15:
            return False
        if now.hour == 15 and now.minute > 15:
            return False
        if now.hour == 9 and now.minute < 18:
            return False
        
        return True
    
    def get_summary(self) -> Dict[str, Any]:
        """Get safe configuration summary."""
        return {
            'mode': self.MODE,
            'token_valid': bool(self.ACCESS_TOKEN),
            'auth_url': self.get_auth_url(),
            'https': self.USE_HTTPS,
            'lot_size': self.LOT_SIZE,
            'max_trades': self.MAX_DAILY_TRADES,
            'market_open': self.is_market_open(),
            'holidays_today': self.is_market_holiday(),
            'sensex_token': self.SENSEX_TOKEN
        }

# For direct testing
if __name__ == "__main__":
    config = SecureConfigManager()
    print("=== Configuration Summary ===")
    summary = config.get_summary()
    for key, value in summary.items():
        print(f"{key}: {value}")
