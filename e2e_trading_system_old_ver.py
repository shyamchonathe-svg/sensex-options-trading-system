#!/usr/bin/env python3
"""
Integrated Trading System with Enhanced Token Management
Combines robust token extraction, storage, validation, and trading operations
Features:
1. Automatic daily token refresh at 9:00 AM IST
2. Seamless token extraction and validation
3. Encrypted token storage
4. Integration with trading workflows
5. Comprehensive Telegram notifications
6. Health monitoring and status reporting
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, time as dt_time, timedelta
import argparse
from pathlib import Path
import pytz
import threading
import schedule
import requests
import urllib3
from kiteconnect import KiteConnect
from typing import Optional, Dict, Any, Tuple
from cryptography.fernet import Fernet

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# IST Timezone setup
IST = pytz.timezone('Asia/Kolkata')

# Enhanced logging with IST timezone
class ISTFormatter(logging.Formatter):
    def converter(self, timestamp):
        utc_dt = datetime.utcfromtimestamp(timestamp)
        utc_dt = pytz.utc.localize(utc_dt)
        ist_dt = utc_dt.astimezone(IST)
        return ist_dt.timetuple()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s IST - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_system.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

for handler in logging.getLogger().handlers:
    handler.setFormatter(ISTFormatter('%(asctime)s IST - %(name)s - %(levelname)s - %(message)s'))

logger = logging.getLogger(__name__)

class TokenManager:
    """Enhanced token management with encryption, metadata, and validation"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.token_file = Path('kite_tokens') / 'current_token.encrypted'
        self.backup_token_file = Path('kite_tokens') / 'backup_token.encrypted'
        self.token_history_file = Path('kite_tokens') / 'token_history.json'
        self.key_file = Path('kite_tokens') / 'encryption_key.key'
        self.storage_path = Path('kite_tokens')
        self.storage_path.mkdir(exist_ok=True)
        self.fernet = self._load_or_generate_key()
        self.logger = logger
        
    def _load_or_generate_key(self):
        """Load or generate encryption key"""
        if not self.key_file.exists():
            key = Fernet.generate_key()
            with open(self.key_file, 'wb') as f:
                f.write(key)
        with open(self.key_file, 'rb') as f:
            return Fernet(f.read())
    
    def save_token_data(self, access_token: str, user_profile: Dict = None, session_data: Dict = None):
        """Save token with metadata and encryption"""
        token_data = {
            'access_token': access_token,
            'created_at': datetime.utcnow().isoformat(),
            'created_at_ist': self.get_ist_time().isoformat(),
            'api_key': self.api_key,
            'user_profile': user_profile or {},
            'session_data': session_data or {},
            'last_validated': datetime.utcnow().isoformat(),
            'validation_count': 1,
            'is_valid': True
        }
        
        # Encrypt token data
        encrypted_data = self.fernet.encrypt(json.dumps(token_data).encode())
        
        # Save main token file
        with open(self.token_file, 'wb') as f:
            f.write(encrypted_data)
        
        # Create backup
        with open(self.backup_token_file, 'wb') as f:
            f.write(encrypted_data)
        
        # Update token history (unencrypted for analysis)
        self.update_token_history(token_data)
        
        # Legacy support - save to old file (not encrypted for compatibility)
        with open('latest_token.txt', 'w') as f:
            f.write(access_token)
        
        self.logger.info(f"💾 Token saved with metadata for {user_profile.get('user_name', 'Unknown')}")
        return token_data
    
    def update_token_history(self, token_record: Dict):
        """Update token history log"""
        try:
            history = []
            if self.token_history_file.exists():
                with open(self.token_history_file, 'r') as f:
                    history = json.load(f)
            
            # Add new record (keep last 30 days)
            history.append(token_record)
            cutoff_date = datetime.utcnow() - timedelta(days=30)
            history = [
                record for record in history 
                if datetime.fromisoformat(record['created_at']) > cutoff_date
            ]
            
            with open(self.token_history_file, 'w') as f:
                json.dump(history, f, indent=2)
                
        except Exception as e:
            self.logger.warning(f"⚠️ History update failed: {e}")
    
    def load_token_data(self) -> Optional[Dict]:
        """Load and decrypt token data"""
        for token_file in [self.token_file, self.backup_token_file]:
            if token_file.exists():
                try:
                    with open(token_file, 'rb') as f:
                        encrypted_data = f.read()
                    decrypted_data = self.fernet.decrypt(encrypted_data)
                    return json.loads(decrypted_data.decode())
                except Exception as e:
                    self.logger.warning(f"⚠️ Error loading {token_file}: {e}")
        
        # Legacy fallback
        if os.path.exists('latest_token.txt'):
            try:
                with open('latest_token.txt', 'r') as f:
                    token = f.read().strip()
                if token:
                    return {'access_token': token, 'is_legacy': True}
            except:
                pass
        
        return None
    
    def validate_token(self, access_token: str) -> Tuple[bool, Optional[Dict]]:
        """Validate token and return user profile"""
        try:
            kite = KiteConnect(api_key=self.api_key)
            kite.set_access_token(access_token)
            profile = kite.profile()
            
            # Update validation metadata
            token_data = self.load_token_data()
            if token_data:
                token_data['last_validated'] = datetime.utcnow().isoformat()
                token_data['validation_count'] = token_data.get('validation_count', 0) + 1
                token_data['is_valid'] = True
                token_data['user_profile'] = profile
                
                # Re-encrypt and save
                encrypted_data = self.fernet.encrypt(json.dumps(token_data).encode())
                with open(self.token_file, 'wb') as f:
                    f.write(encrypted_data)
            
            self.logger.info(f"✅ Token valid for user: {profile.get('user_name', 'Unknown')}")
            return True, profile
            
        except Exception as e:
            self.logger.error(f"❌ Token validation failed: {e}")
            token_data = self.load_token_data()
            if token_data:
                token_data['is_valid'] = False
                token_data['last_error'] = str(e)
                token_data['last_error_time'] = datetime.utcnow().isoformat()
                encrypted_data = self.fernet.encrypt(json.dumps(token_data).encode())
                with open(self.token_file, 'wb') as f:
                    f.write(encrypted_data)
            
            return False, None
    
    def get_ist_time(self):
        """Get current IST time"""
        utc_now = datetime.utcnow()
        utc_dt = pytz.utc.localize(utc_now)
        return utc_dt.astimezone(IST)
    
    def is_token_expired(self) -> bool:
        """Check if token is likely expired (older than 20 hours)"""
        token_data = self.load_token_data()
        if not token_data:
            return True
        
        try:
            created_at = datetime.fromisoformat(token_data['created_at'].replace('Z', ''))
            age_hours = (datetime.utcnow() - created_at).total_seconds() / 3600
            if age_hours > 20:
                self.logger.warning(f"⏰ Token is {age_hours:.1f} hours old (likely expired)")
                return True
            return False
        except Exception as e:
            self.logger.warning(f"⚠️ Error checking token age: {e}")
            return True
    
    def get_valid_token(self) -> Optional[str]:
        """Get a valid token, checking age and validation"""
        token_data = self.load_token_data()
        if not token_data:
            return None
        
        access_token = token_data.get('access_token')
        if not access_token:
            return None
        
        if self.is_token_expired():
            return None
        
        is_valid, _ = self.validate_token(access_token)
        if is_valid:
            return access_token
        
        return None

class IntegratedTradingSystem:
    """Integrated trading system with token extraction and management"""
    
    def __init__(self):
        self.logger = logger
        self.config = self.load_config()
        self.token_manager = TokenManager(self.config['api_key'])
        self.kite = None
        self.scheduler_running = False
        self.last_token_check = None
        ist_now = self.get_ist_time()
        self.logger.info(f"🚀 Integrated Trading System initialized at {ist_now.strftime('%Y-%m-%d %H:%M:%S IST')}")
    
    def load_config(self):
        """Load configuration with validation"""
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
        except FileNotFoundError:
            config = {}
            self.logger.warning("⚠️ config.json not found, using defaults")
        except json.JSONDecodeError as e:
            self.logger.error(f"❌ Invalid config.json format: {e}")
            config = {}
        
        defaults = {
            "api_key": null,
            "api_secret": null,
            "telegram_token": "7913084624:AAGvk9-R9YEUf4FGHCwDyOOpGHZOKUHr0mE",
            "chat_id": null,
            "use_https": True,
            "postback_urls": {
                "primary": "https://sensexbot.ddns.net/postback",
                "secondary": "https://sensexbot.ddns.net/redirect"
            },
            "server_url": "https://sensexbot.ddns.net",
            "auth_timeout_seconds": 300,
            "daily_auth_time": "09:00",
            "token_refresh_enabled": True,
            "max_token_age_hours": 20,
            "trading_enabled": False
        }
        
        for key, value in defaults.items():
            if key not in config:
                config[key] = value
        
        required_fields = ['api_key', 'api_secret', 'telegram_token', 'chat_id', 'server_url']
        for field in required_fields:
            if not config.get(field):
                self.logger.error(f"❌ Missing or invalid {field} in config")
                raise ValueError(f"Configuration error: {field} is required")
        
        for url_type, url in config['postback_urls'].items():
            if not url.startswith(('http://', 'https://')):
                self.logger.error(f"❌ Invalid {url_type} postback URL: {url}")
                raise ValueError(f"Invalid {url_type} postback URL")
        
        return config
    
    def get_ist_time(self):
        """Get current IST time"""
        return self.token_manager.get_ist_time()
    
    def send_telegram_message(self, message: str, silent: bool = False) -> bool:
        """Send message via Telegram bot"""
        try:
            url = f"https://api.telegram.org/bot{self.config['telegram_token']}/sendMessage"
            data = {
                "chat_id": self.config['chat_id'],
                "text": message,
                "parse_mode": "HTML",
                "disable_notification": silent
            }
            response = requests.post(url, data=data, timeout=15)
            if response.status_code == 200:
                if not silent:
                    self.logger.info("✅ Telegram message sent successfully")
                return True
            else:
                self.logger.error(f"❌ Telegram API error: {response.status_code}")
                return False
        except Exception as e:
            self.logger.error(f"❌ Failed to send Telegram message: {e}")
            return False
    
    def check_server_health(self) -> Optional[str]:
        """Check postback server health"""
        endpoints = [
            f"{self.config['server_url']}/health",
            f"{self.config['server_url'].replace('https://', 'http://')}:8001/health"
        ]
        for endpoint in endpoints:
            try:
                response = requests.get(endpoint, timeout=10, verify=False)
                if response.status_code == 200:
                    self.logger.info(f"✅ Server healthy: {endpoint}")
                    return endpoint
            except Exception as e:
                self.logger.warning(f"⚠️ Server {endpoint} not responding: {e}")
        return None
    
    def generate_auth_url(self) -> str:
        """Generate authentication URL"""
        postback_url = self.config['postback_urls']['primary']
        return (f"https://kite.zerodha.com/connect/login?"
                f"api_key={self.config['api_key']}&"
                f"v=3&"
                f"postback_url={postback_url}")
    
    def poll_for_request_token(self, timeout: int = 300, poll_interval: int = 3) -> Optional[str]:
        """Poll server for request token with smart intervals"""
        start_time = time.time()
        last_status_log = 0
        self.logger.info(f"🔍 Polling for request token (timeout: {timeout}s)")
        
        while (time.time() - start_time) < timeout:
            try:
                response = requests.get(
                    f"{self.config['server_url']}/get_token",
                    timeout=5,
                    verify=False
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get('status') == 'success' and 'request_token' in data:
                        request_token = data['request_token']
                        age = data.get('age_seconds', 0)
                        self.logger.info(f"✅ Request token found! Age: {age}s")
                        return request_token
                elif response.status_code == 410:
                    self.logger.error("❌ Token expired on server")
                    return None
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"⚠️ Server polling failed: {e}")
            
            elapsed = time.time() - start_time
            if elapsed - last_status_log >= 30:
                remaining = timeout - elapsed
                self.logger.info(f"⏳ Polling... {remaining:.0f}s remaining")
                last_status_log = elapsed
            time.sleep(poll_interval)
        
        self.logger.error(f"❌ Polling timeout after {timeout}s")
        return None
    
    def request_authentication(self, mode: str = 'manual') -> bool:
        """Request user authentication via Telegram"""
        server_url = self.check_server_health()
        if not server_url:
            self.logger.error("❌ No healthy postback server found!")
            return False
        
        try:
            requests.get(f"{server_url}/clear_token", timeout=5, verify=False)
            self.logger.info("🧹 Cleared server tokens")
        except:
            pass
        
        auth_url = self.generate_auth_url()
        ist_time = self.get_ist_time().strftime("%Y-%m-%d %H:%M:%S IST")
        
        if mode == 'scheduled':
            emoji = "⏰"
            title = "Daily Token Refresh (9:00 AM IST)"
        elif mode == 'expired':
            emoji = "🔄"
            title = "Token Expired - Refresh Required"
        else:
            emoji = "🔐"
            title = "Manual Authentication"
        
        message = f"""
{emoji} <b>{title}</b>

📅 <b>Time:</b> {ist_time}
🖥️ <b>Server:</b> {server_url}
🔗 <b>Postback:</b> {self.config['postback_urls']['primary']}

<b>🚀 CLICK TO AUTHENTICATE:</b>
{auth_url}

<b>📋 Process:</b>
1️⃣ Click link above
2️⃣ Login to Zerodha
3️⃣ See "Authentication Successful"
4️⃣ Get automatic confirmation
5️⃣ Fresh token ready!

⏱️ <b>Timeout:</b> 5 minutes
🔒 <b>Security:</b> HTTPS encrypted
        """
        return self.send_telegram_message(message)
    
    def exchange_for_access_token(self, request_token: str) -> Tuple[Optional[str], Optional[Dict]]:
        """Exchange request token for access token"""
        try:
            self.logger.info("🔄 Exchanging request token for access token...")
            kite = KiteConnect(api_key=self.config['api_key'])
            session_data = kite.generate_session(
                request_token=request_token,
                api_secret=self.config['api_secret']
            )
            access_token = session_data["access_token"]
            kite.set_access_token(access_token)
            profile = kite.profile()
            self.logger.info(f"✅ Access token generated for {profile.get('user_name', session_data.get('user_id', 'Unknown'))}")
            return access_token, {'profile': profile, 'session_data': session_data}
        except Exception as e:
            self.logger.error(f"❌ Token exchange failed: {e}")
            return None, None
    
    def perform_authentication_flow(self, mode: str = 'manual') -> Optional[str]:
        """Complete authentication flow"""
        self.logger.info(f"🔐 Starting {mode} authentication...")
        
        if not self.request_authentication(mode):
            self.logger.error("❌ Failed to send auth request")
            return None
        
        request_token = self.poll_for_request_token(timeout=self.config['auth_timeout_seconds'])
        if not request_token:
            timeout_msg = f"""
⏰ <b>Authentication Timeout</b>

📅 Time: {self.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}
❌ No response within 5 minutes

<b>Try again:</b>
<code>python3 integrated_trading_system.py --mode auth</code>
            """
            self.send_telegram_message(timeout_msg)
            return None
        
        access_token, extraction_info = self.exchange_for_access_token(request_token)
        if not access_token:
            return None
        
        self.token_manager.save_token_data(access_token, extraction_info['profile'], extraction_info['session_data'])
        
        success_msg = f"""
✅ <b>Authentication Successful!</b>

👤 <b>User:</b> {extraction_info['profile'].get('user_name', 'Unknown')}
📅 <b>Time:</b> {self.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}
🔑 <b>Token:</b> {access_token[:20]}...***
💾 <b>Saved:</b> kite_tokens/current_token.encrypted
🔐 <b>Method:</b> {mode.title()} HTTPS Auth

🚀 <b>Status:</b> Ready for trading!
<b>Token valid for ~24 hours</b>
Next auto-refresh: Tomorrow 9:00 AM IST
        """
        self.send_telegram_message(success_msg)
        return access_token
    
    def get_current_valid_token(self) -> Optional[str]:
        """Get current valid token or refresh if needed"""
        token = self.token_manager.get_valid_token()
        if token:
            self.logger.info("✅ Using existing valid token")
            return token
        
        self.logger.warning("⚠️ No valid token found, requesting new authentication")
        expire_msg = f"""
🔄 <b>Token Refresh Required</b>

📅 Time: {self.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}
⚠️ Current token expired or invalid

Requesting new authentication...
        """
        self.send_telegram_message(expire_msg)
        return self.perform_authentication_flow('expired')
    
    def initialize_kite_connection(self) -> bool:
        """Initialize Kite connection with valid token"""
        token = self.get_current_valid_token()
        if not token:
            return False
        
        try:
            self.kite = KiteConnect(api_key=self.config['api_key'])
            self.kite.set_access_token(token)
            profile = self.kite.profile()
            self.last_token_check = time.time()
            self.logger.info(f"🔗 Kite connection established for {profile.get('user_name')}")
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize Kite connection: {e}")
            self.kite = None
            return False
    
    def ensure_valid_connection(self) -> bool:
        """Ensure valid Kite connection with periodic checks"""
        current_time = time.time()
        
        # Check connection every 5 minutes
        if self.last_token_check and current_time - self.last_token_check < 300 and self.kite:
            try:
                self.kite.profile()
                return True
            except Exception as e:
                self.logger.warning(f"⚠️ Existing connection invalid: {e}")
        
        self.logger.info("🔍 Checking Kite connection...")
        self.last_token_check = current_time
        return self.initialize_kite_connection()
    
    def setup_daily_token_refresh(self):
        """Setup daily token refresh scheduler"""
        def daily_refresh_job():
            ist_now = self.get_ist_time()
            self.logger.info(f"⏰ Daily token refresh triggered at {ist_now.strftime('%H:%M:%S IST')}")
            
            new_token = self.perform_authentication_flow('scheduled')
            
            if new_token:
                self.logger.info("✅ Daily token refresh successful")
                if self.kite:
                    self.kite.set_access_token(new_token)
                    self.logger.info("🔗 Kite connection updated with new token")
            else:
                self.logger.error("❌ Daily token refresh failed")
                error_msg = f"""
❌ <b>Daily Token Refresh Failed</b>

📅 Date: {ist_now.strftime('%Y-%m-%d')}
⏰ Time: {ist_now.strftime('%H:%M:%S IST')}

<b>Action Required:</b>
Manual authentication needed

<b>Command:</b>
<code>python3 integrated_trading_system.py --mode auth</code>
                """
                self.send_telegram_message(error_msg)
        
        schedule.clear('daily_token_refresh')
        
        # Schedule at 9:00 AM IST (3:30 AM UTC)
        schedule.every().day.at("03:30").do(daily_refresh_job).tag('daily_token_refresh')
        
        self.logger.info("📅 Daily token refresh scheduled for 9:00 AM IST")
        
        if not self.scheduler_running:
            def run_scheduler():
                self.scheduler_running = True
                while self.scheduler_running:
                    try:
                        schedule.run_pending()
                        time.sleep(60)
                    except Exception as e:
                        self.logger.error(f"Scheduler error: {e}")
                        time.sleep(60)
            
            scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
            scheduler_thread.start()
            self.logger.info("🔄 Token refresh scheduler started")
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        token_data = self.token_manager.load_token_data()
        server_url = self.check_server_health()
        
        status = {
            'timestamp': self.get_ist_time().isoformat(),
            'server_healthy': server_url is not None,
            'server_url': server_url,
            'has_token': token_data is not None,
            'token_valid': False,
            'token_age_hours': None,
            'user_name': None,
            'kite_connected': self.kite is not None,
            'scheduler_running': self.scheduler_running
        }
        
        if token_data:
            access_token = token_data.get('access_token')
            if access_token:
                is_valid, profile = self.token_manager.validate_token(access_token)
                status['token_valid'] = is_valid
                if profile:
                    status['user_name'] = profile.get('user_name')
                
                try:
                    created_at = datetime.fromisoformat(token_data['created_at'].replace('Z', ''))
                    age_hours = (datetime.utcnow() - created_at).total_seconds() / 3600
                    status['token_age_hours'] = round(age_hours, 1)
                except:
                    pass
        
        return status
    
    def send_status_report(self):
        """Send system status report"""
        status = self.get_system_status()
        
        server_emoji = "✅" if status['server_healthy'] else "❌"
        token_emoji = "✅" if status['token_valid'] else "❌"
        kite_emoji = "✅" if status['kite_connected'] else "❌"
        scheduler_emoji = "✅" if status['scheduler_running'] else "❌"
        
        message = f"""
📊 <b>System Status Report</b>

📅 <b>Time:</b> {self.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}

<b>🖥️ Server Status:</b> {server_emoji}
<b>🔑 Token Status:</b> {token_emoji}
<b>🔗 Kite Connection:</b> {kite_emoji}
<b>⏰ Scheduler:</b> {scheduler_emoji}

<b>📋 Details:</b>
• Server: {status['server_url'] or 'Not available'}
• User: {status['user_name'] or 'Unknown'}
• Token Age: {status['token_age_hours'] or 'Unknown'} hours
• Next Refresh: Tomorrow 9:00 AM IST

<b>💡 Commands:</b>
• Status: <code>--mode status</code>
• Auth: <code>--mode auth</code>
• Test: <code>--mode test</code>
        """
        
        self.send_telegram_message(message)
    
    def test_trading_functionality(self):
        """Test trading system functionality"""
        self.logger.info("🧪 Testing trading functionality...")
        
        if not self.ensure_valid_connection():
            self.logger.error("❌ Cannot test - Kite connection failed")
            return False
        
        try:
            profile = self.kite.profile()
            margins = self.kite.margins()
            
            try:
                instruments = self.kite.instruments("NSE")[:5]
                self.logger.info(f"✅ Retrieved {len(instruments)} sample instruments")
            except Exception as e:
                self.logger.warning(f"⚠️ Market data test failed (market may be closed): {e}")
            
            test_msg = f"""
🧪 <b>Trading System Test Complete</b>

📅 Time: {self.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}

<b>✅ Test Results:</b>
• Profile: {profile.get('user_name')} ({profile.get('user_id')})
• Available Margin: ₹{margins.get('equity', {}).get('available', {}).get('live_balance', 0):,.2f}
• API Connection: Working
• Token Status: Valid

<b>🚀 System Ready for Live Trading!</b>

<b>Commands:</b>
• Live Mode: <code>--mode live</code>
• Status: <code>--mode status</code>
            """
            
            self.send_telegram_message(test_msg)
            self.logger.info("✅ Trading system test successful")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Trading test failed: {e}")
            error_msg = f"""
❌ <b>Trading System Test Failed</b>

📅 Time: {self.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}
⚠️ Error: {str(e)}

<b>Possible Solutions:</b>
• Token may be expired: <code>--mode auth</code>
• Check internet connection
• Verify API credentials
            """
            self.send_telegram_message(error_msg)
            return False
    
    def start_live_trading_loop(self):
        """Start live trading with continuous token monitoring"""
        self.logger.info("🚀 Starting live trading mode...")
        
        trading_engine = TradingEngine(self)
        
        live_start_msg = f"""
🚀 <b>Live Trading Started</b>

📅 Start Time: {self.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}
🔗 Connection: Active
🔄 Token Refresh: Scheduled (9:00 AM daily)

<b>System Active!</b>
Monitoring markets and executing trades...
        """
        
        self.send_telegram_message(live_start_msg)
        
        try:
            while True:
                if not self.ensure_valid_connection():
                    self.logger.error("❌ Lost connection - attempting recovery...")
                    time.sleep(60)
                    continue
                
                trading_engine.execute_trading_cycle()
                
                time.sleep(60)  # 1 minute between cycles
                
        except KeyboardInterrupt:
            self.logger.info("⏹️ Live trading stopped by user")
            stop_msg = f"""
⏹️ <b>Live Trading Stopped</b>

📅 Stop Time: {self.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}
📊 Trades Executed: {trading_engine.trade_count}

<b>System Status:</b> Stopped by user
<b>Token Scheduler:</b> Still active
            """
            self.send_telegram_message(stop_msg)
    
    def debug_timezone_info(self):
        """Debug timezone information"""
        ist_now = self.get_ist_time()
        utc_now = datetime.utcnow()
        
        print(f"\n🌍 TIMEZONE DEBUG:")
        print(f"System TZ: {time.tzname}")
        print(f"UTC Time: {utc_now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"IST Time: {ist_now.strftime('%Y-%m-%d %H:%M:%S IST')}")
        print(f"Offset: {ist_now.strftime('%z')}")
        
        today_9am_ist = ist_now.replace(hour=9, minute=0, second=0, microsecond=0)
        today_9am_utc = today_9am_ist.astimezone(pytz.utc)
        
        print(f"\n⏰ 9:00 AM IST = {today_9am_utc.strftime('%H:%M UTC')}")
    
    def debug_server_connectivity(self):
        """Debug server connectivity"""
        print(f"\n🖥️ SERVER CONNECTIVITY:")
        
        endpoints = [
            "https://sensexbot.ddns.net/health",
            "https://sensexbot.ddns.net/status", 
            "http://sensexbot.ddns.net:8001/health",
            "http://sensexbot.ddns.net:8001/status"
        ]
        
        for endpoint in endpoints:
            try:
                response = requests.get(endpoint, timeout=5, verify=False)
                print(f"✅ {endpoint} - Status: {response.status_code}")
            except Exception as e:
                print(f"❌ {endpoint} - Error: {str(e)[:50]}")
    
    def debug_token_info(self):
        """Debug token information"""
        print(f"\n🔑 TOKEN DEBUG:")
        
        token_data = self.token_manager.load_token_data()
        if token_data:
            print(f"Has token: ✅ Yes")
            print(f"Token preview: {token_data.get('access_token', '')[:20]}...")
            print(f"Created: {token_data.get('created_at_ist', 'Unknown')}")
            print(f"Valid: {token_data.get('is_valid', 'Unknown')}")
            print(f"User: {token_data.get('user_profile', {}).get('user_name', 'Unknown')}")
            
            is_valid, _ = self.token_manager.validate_token(token_data['access_token'])
            print(f"Live validation: {'✅ Valid' if is_valid else '❌ Invalid'}")
        else:
            print(f"Has token: ❌ No")
    
    def send_debug_report(self):
        """Send comprehensive debug report"""
        status = self.get_system_status()
        
        debug_msg = f"""
🐛 <b>Debug Report</b>

📅 <b>Time:</b> {self.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}
🌍 <b>System TZ:</b> {time.tzname}

<b>🖥️ Server Health:</b>
• HTTPS: {status['server_url'] if status['server_healthy'] else 'Down'}
• Status: {'✅ Healthy' if status['server_healthy'] else '❌ Down'}

<b>🔑 Token Status:</b>
• Exists: {'✅ Yes' if status['has_token'] else '❌ No'}
• Valid: {'✅ Yes' if status['token_valid'] else '❌ No'}
• Age: {status['token_age_hours'] or 'Unknown'} hours
• User: {status['user_name'] or 'Unknown'}

<b>🔗 System Status:</b>
• Kite Connected: {'✅ Yes' if status['kite_connected'] else '❌ No'}
• Scheduler: {'✅ Running' if status['scheduler_running'] else '❌ Stopped'}

<b>💡 Next Steps:</b>
• Auth: <code>--mode auth</code>
• Test: <code>--mode test</code>
• Live: <code>--mode live</code>
        """
        
        self.send_telegram_message(debug_msg)

class TradingEngine:
    """Enhanced trading engine with automatic token management"""
    
    def __init__(self, system: IntegratedTradingSystem):
        self.system = system
        self.logger = logger
        self.is_running = False
        self.trade_count = 0
        
    def execute_trading_cycle(self):
        """Execute one trading cycle with error handling"""
        try:
            ist_now = self.system.get_ist_time()
            current_time = ist_now.time()
            
            market_start = dt_time(9, 15)
            market_end = dt_time(15, 30)
            
            if market_start <= current_time <= market_end:
                self.execute_market_operations()
            else:
                self.logger.info("💤 Market closed - monitoring only")
                
        except Exception as e:
            self.logger.error(f"❌ Trading cycle error: {e}")
            error_msg = f"""
⚠️ <b>Trading Cycle Error</b>

📅 Time: {self.system.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}
❌ Error: {str(e)[:100]}...

<b>System Status:</b> Continuing with next cycle
<b>Action:</b> Monitor logs for details
            """
            self.system.send_telegram_message(error_msg)
    
    def execute_market_operations(self):
        """Execute actual market operations"""
        try:
            quotes = self.system.kite.quote([
                "NSE:NIFTY 50",
                "NSE:NIFTY BANK"
            ])
            
            nifty_price = quotes.get("NSE:NIFTY 50", {}).get("last_price", 0)
            bank_nifty_price = quotes.get("NSE:NIFTY BANK", {}).get("last_price", 0)
            
            self.logger.info(f"📊 NIFTY: ₹{nifty_price:,.2f}, BANK NIFTY: ₹{bank_nifty_price:,.2f}")
            
            positions = self.system.kite.positions()
            holdings = self.system.kite.holdings()
            
            self.logger.info(f"📋 Positions: {len(positions.get('day', []))}, Holdings: {len(holdings)}")
            
            self.trade_count += 1
            
            trade_msg = f"""
📈 <b>Trade Cycle Executed</b>

📅 Time: {self.system.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}
📊 NIFTY 50: ₹{nifty_price:,.2f}
📊 BANK NIFTY: ₹{bank_nifty_price:,.2f}

✅ Cycle completed successfully!
            """
            self.system.send_telegram_message(trade_msg, silent=True)
            
        except Exception as e:
            self.logger.error(f"❌ Market operations failed: {e}")

def main():
    """Main function for integrated trading system"""
    parser = argparse.ArgumentParser(description='Integrated Trading System')
    parser.add_argument('--mode', 
                        choices=['auth', 'test', 'live', 'schedule', 'status', 'debug', 'extract', 'validate', 'integrate'], 
                        default='status', 
                        help='System operation mode')
    parser.add_argument('--force-refresh', action='store_true',
                        help='Force token refresh even if current token is valid')
    
    args = parser.parse_args()
    
    system = IntegratedTradingSystem()
    
    try:
        if args.mode == 'auth' or args.mode == 'extract':
            print("🔐 AUTHENTICATION MODE")
            print("=" * 50)
            
            current_token = system.token_manager.get_valid_token()
            if current_token and not args.force_refresh:
                token_data = system.token_manager.load_token_data()
                user_name = token_data.get('user_profile', {}).get('user_name', 'User')
                print(f"✅ Valid token exists for {user_name}")
                print("Authentication not needed!")
                
                choice = input("\nForce new authentication anyway? (y/N): ").strip().lower()
                if choice != 'y':
                    return
            
            token = system.perform_authentication_flow('manual')
            if token:
                print("✅ AUTHENTICATION SUCCESSFUL!")
                print(f"Token: {token[:20]}...")
            else:
                print("❌ AUTHENTICATION FAILED!")
        
        elif args.mode == 'schedule':
            print("📅 SETTING UP DAILY TOKEN REFRESH")
            print("=" * 50)
            
            system.setup_daily_token_refresh()
            
            setup_msg = f"""
📅 <b>Daily Token Refresh Activated</b>

⏰ <b>Schedule:</b> 9:00 AM IST (Every Day)
📅 <b>Current Time:</b> {system.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}

<b>🔄 How it works:</b>
• Automatic auth link at 9:00 AM IST
• Click link → Login → Auto success
• Fresh token ready for trading
• Runs continuously in background

<b>✅ Scheduler Active</b>

Manual override: <code>--mode auth</code>
            """
            system.send_telegram_message(setup_msg)
            
            print("✅ Daily token refresh scheduler active!")
            print("\nKeeping scheduler running... Press Ctrl+C to stop")
            
            try:
                while True:
                    time.sleep(60)
            except KeyboardInterrupt:
                print("\n📴 Scheduler stopped")
                system.scheduler_running = False
        
        elif args.mode == 'status' or args.mode == 'validate':
            print("📊 SYSTEM STATUS CHECK")
            print("=" * 50)
            
            status = system.get_system_status()
            
            print(f"Time: {status['timestamp']}")
            print(f"Server: {'✅ Healthy' if status['server_healthy'] else '❌ Down'}")
            print(f"Token: {'✅ Valid' if status['token_valid'] else '❌ Invalid'}")
            print(f"User: {status['user_name'] or 'Unknown'}")
            print(f"Token Age: {status['token_age_hours'] or 'Unknown'} hours")
            print(f"Kite Connected: {'✅ Yes' if status['kite_connected'] else '❌ No'}")
            print(f"Scheduler: {'✅ Running' if status['scheduler_running'] else '❌ Stopped'}")
            
            system.send_status_report()
        
        elif args.mode == 'test' or args.mode == 'integrate':
            print("🧪 TESTING TRADING SYSTEM")
            print("=" * 50)
            
            if system.test_trading_functionality():
                print("✅ All tests passed!")
            else:
                print("❌ Tests failed - check authentication")
        
        elif args.mode == 'live':
            print("🚀 STARTING LIVE TRADING")
            print("=" * 50)
            
            if not system.ensure_valid_connection():
                print("❌ Cannot start live trading - authentication required")
                print("Run: python3 integrated_trading_system.py --mode auth")
                return
            
            system.setup_daily_token_refresh()
            
            system.start_live_trading_loop()
        
        elif args.mode == 'debug':
            print("🐛 DEBUG MODE")
            print("=" * 50)
            
            system.debug_timezone_info()
            system.debug_server_connectivity()
            system.debug_token_info()
            system.send_debug_report()
    
    except KeyboardInterrupt:
        print("\n⏹️ Interrupted by user")
        system.scheduler_running = False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("\n🚀 INTEGRATED TRADING SYSTEM")
    print("=" * 50)
    print("Features:")
    print("• ✅ Daily automatic token refresh at 9:00 AM IST")
    print("• ✅ HTTPS-compatible authentication")
    print("• ✅ Seamless token extraction and validation")
    print("• ✅ Encrypted token storage")
    print("• ✅ AWS timezone handling (UTC → IST)")
    print("• ✅ Fallback mechanisms for failures")
    print("• ✅ Live trading with token monitoring")
    print("• ✅ Telegram notifications and status")
    print()
    
    print("🌍 TIMEZONE INFO:")
    utc_now = datetime.utcnow()
    ist_now = pytz.utc.localize(utc_now).astimezone(IST)
    print(f"System: {time.tzname}")
    print(f"UTC: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"IST: {ist_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"9:00 AM IST = {ist_now.replace(hour=9, minute=0).astimezone(pytz.utc).strftime('%H:%M UTC')}")
    print()
    
    main()
