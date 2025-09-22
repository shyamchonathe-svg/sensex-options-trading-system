#!/usr/bin/env python3
"""
Debug Token Generator for Zerodha KiteConnect API
Standalone script for generating authentication tokens anytime
Perfect for backtesting, development, and debugging outside market hours
"""

import os
import sys
import json
import time
import requests
import logging
from datetime import datetime
import pytz
import threading
import urllib3
from pathlib import Path

# Disable SSL warnings for development
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class DebugTokenGenerator:
    def __init__(self, config_file='config.json'):
        self.setup_logging()
        self.config = self.load_config(config_file)
        self.ist_tz = pytz.timezone('Asia/Kolkata')
        
    def setup_logging(self):
        """Setup logging for the debug token generator"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler('debug_token_generator.log')
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def load_config(self, config_file):
        """Load configuration from JSON file"""
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            
            required_keys = ['api_key', 'api_secret']
            for key in required_keys:
                if key not in config:
                    raise ValueError(f"Missing required config key: {key}")
            
            # Add default postback URLs if not present
            if 'postback_urls' not in config:
                config['postback_urls'] = {
                    "primary": "https://sensexbot.ddns.net/postback",
                    "secondary": "https://sensexbot.ddns.net/redirect"
                }
            
            if 'server_host' not in config:
                config['server_host'] = 'sensexbot.ddns.net'
                
            self.logger.info("Configuration loaded successfully")
            return config
            
        except FileNotFoundError:
            self.logger.error(f"Config file {config_file} not found")
            # Return minimal config for manual entry
            return self.get_manual_config()
        except Exception as e:
            self.logger.error(f"Error loading config: {e}")
            return self.get_manual_config()
    
    def get_manual_config(self):
        """Get configuration manually from user input"""
        print("\n" + "="*60)
        print("ZERODHA DEBUG TOKEN GENERATOR")
        print("="*60)
        print("Configuration file not found or invalid.")
        print("Please provide your Zerodha API credentials:")
        print()
        
        api_key = input("Enter your Zerodha API Key: ").strip()
        api_secret = input("Enter your Zerodha API Secret: ").strip()
        
        if not api_key or not api_secret:
            print("Error: API key and secret are required!")
            sys.exit(1)
        
        config = {
            "api_key": api_key,
            "api_secret": api_secret,
            "postback_urls": {
                "primary": "https://sensexbot.ddns.net/postback",
                "secondary": "https://sensexbot.ddns.net/redirect"
            },
            "server_host": "sensexbot.ddns.net"
        }
        
        # Save config for future use
        try:
            with open('debug_config.json', 'w') as f:
                json.dump(config, f, indent=4)
            print(f"Configuration saved to debug_config.json")
        except Exception as e:
            print(f"Warning: Could not save config: {e}")
        
        return config
    
    def get_ist_time(self):
        """Get current IST time"""
        return datetime.now(self.ist_tz)
    
    def check_server_availability(self):
        """Check if any postback server is available"""
        server_urls = [
            f"https://{self.config['server_host']}",
            f"http://{self.config['server_host']}:8001"
        ]
        
        working_server = None
        for url in server_urls:
            try:
                response = requests.get(f"{url}/health", timeout=5, verify=False)
                if response.status_code == 200:
                    working_server = url
                    self.logger.info(f"Found working server: {url}")
                    break
            except:
                continue
        
        return working_server
    
    def generate_auth_url(self):
        """Generate Zerodha authentication URL"""
        postback_url = self.config['postback_urls']['primary']
        auth_url = (f"https://kite.zerodha.com/connect/login?"
                   f"api_key={self.config['api_key']}&"
                   f"v=3&"
                   f"postback_url={postback_url}")
        return auth_url
    
    def clear_existing_tokens(self, server_url):
        """Clear any existing tokens on the server"""
        try:
            requests.get(f"{server_url}/clear_token", timeout=5, verify=False)
            self.logger.info("Cleared existing tokens from server")
        except Exception as e:
            self.logger.warning(f"Could not clear existing tokens: {e}")
    
    def wait_for_token(self, server_url, timeout=300):
        """Wait for authentication token from postback server"""
        start_time = time.time()
        self.logger.info(f"Waiting for authentication (timeout: {timeout}s)...")
        
        while (time.time() - start_time) < timeout:
            try:
                response = requests.get(f"{server_url}/get_token", timeout=5, verify=False)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('status') == 'success' and 'request_token' in data:
                        request_token = data['request_token']
                        age = data.get('age_seconds', 0)
                        self.logger.info(f"Token received (age: {age}s)")
                        return request_token
                
                elif response.status_code == 410:
                    self.logger.error("Token expired on server")
                    return None
                    
            except requests.exceptions.RequestException as e:
                self.logger.debug(f"Server check failed: {e}")
                
                # Fallback: check for file-based token
                if os.path.exists('request_token.txt'):
                    try:
                        with open('request_token.txt', 'r') as f:
                            request_token = f.read().strip()
                        if request_token:
                            os.remove('request_token.txt')
                            self.logger.info("Token found in backup file")
                            return request_token
                    except:
                        pass
            
            time.sleep(3)
        
        self.logger.error("Authentication timeout - no token received")
        return None
    
    def exchange_token(self, request_token):
        """Exchange request token for access token"""
        try:
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=self.config['api_key'])
            
            self.logger.info("Exchanging request token for access token...")
            data = kite.generate_session(
                request_token=request_token,
                api_secret=self.config['api_secret']
            )
            
            return data["access_token"]
            
        except Exception as e:
            self.logger.error(f"Token exchange failed: {e}")
            return None
    
    def save_token(self, access_token, debug_mode=True):
        """Save access token to files"""
        timestamp = self.get_ist_time().strftime("%Y%m%d_%H%M%S")
        
        # Save to multiple locations for compatibility
        files_to_save = ['latest_token.txt']
        if debug_mode:
            files_to_save.append('debug_token.txt')
            files_to_save.append(f'debug_token_{timestamp}.txt')
        
        saved_files = []
        for filename in files_to_save:
            try:
                with open(filename, 'w') as f:
                    f.write(access_token)
                saved_files.append(filename)
                self.logger.info(f"Token saved to: {filename}")
            except Exception as e:
                self.logger.warning(f"Could not save to {filename}: {e}")
        
        return saved_files
    
    def send_telegram_notification(self, message):
        """Send notification via Telegram if configured"""
        if 'telegram_token' not in self.config or 'chat_id' not in self.config:
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.config['telegram_token']}/sendMessage"
            data = {
                "chat_id": self.config['chat_id'],
                "text": message,
                "parse_mode": "HTML"
            }
            
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                self.logger.info("Telegram notification sent")
                return True
            else:
                self.logger.warning(f"Telegram API error: {response.status_code}")
                return False
                
        except Exception as e:
            self.logger.warning(f"Telegram notification failed: {e}")
            return False
    
    def generate_debug_token(self):
        """Main method to generate debug token"""
        print("\n" + "="*60)
        print("ZERODHA DEBUG TOKEN GENERATOR")
        print("="*60)
        print(f"Time: {self.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}")
        print()
        print("This tool generates Zerodha authentication tokens anytime")
        print("Perfect for:")
        print("  • Backtesting strategies")
        print("  • Development & testing")
        print("  • Data analysis outside market hours")
        print("  • System integration testing")
        print()
        
        # Check server availability
        print("1. Checking postback server availability...")
        server_url = self.check_server_availability()
        
        if not server_url:
            print("❌ ERROR: No postback server available!")
            print("\nTo fix this:")
            print("1. SSH to your AWS instance")
            print("2. Run: sudo python3 postback_server.py")
            print("3. Or: python3 postback_server.py --http-only")
            print("\nThen try again.")
            return False
        
        print(f"✅ Server available: {server_url}")
        
        # Clear existing tokens
        print("\n2. Clearing any existing tokens...")
        self.clear_existing_tokens(server_url)
        
        # Generate auth URL
        print("\n3. Generating authentication URL...")
        auth_url = self.generate_auth_url()
        
        print(f"\n{'='*60}")
        print("AUTHENTICATION REQUIRED")
        print("="*60)
        print("Please click the link below to authenticate with Zerodha:")
        print()
        print(f"🔗 {auth_url}")
        print()
        print("After clicking:")
        print("1. Login with your Zerodha credentials")
        print("2. Complete any 2FA if prompted")
        print("3. You'll see a success page")
        print("4. Return here - token will be captured automatically")
        print()
        print("⏱️  Timeout: 5 minutes")
        print("🔄 Waiting for authentication...")
        
        # Send Telegram notification if configured
        telegram_message = f"""
🔧 <b>DEBUG Token Generator Started</b>

📅 Time: {self.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}
🛠️ Purpose: Development/Backtesting

<b>🔗 Authentication URL:</b>
{auth_url}

<b>⏱️ Instructions:</b>
1. Click the link above
2. Login to Zerodha
3. Complete authentication
4. Token will be generated automatically

<b>🔄 Waiting for your login...</b>
        """
        
        self.send_telegram_notification(telegram_message)
        
        # Wait for authentication
        print("\n4. Waiting for Zerodha authentication...")
        request_token = self.wait_for_token(server_url)
        
        if not request_token:
            print("\n❌ Authentication failed or timed out!")
            print("\nPossible issues:")
            print("• Didn't complete Zerodha login within 5 minutes")
            print("• Network connectivity problems")
            print("• Server communication issues")
            print("\nTry running the script again.")
            return False
        
        print(f"✅ Authentication successful! Request token received.")
        
        # Exchange for access token
        print("\n5. Exchanging for access token...")
        access_token = self.exchange_token(request_token)
        
        if not access_token:
            print("\n❌ Token exchange failed!")
            print("This usually indicates:")
            print("• Invalid API credentials")
            print("• Network issues with Zerodha API")
            print("• Request token expired")
            return False
        
        print(f"✅ Access token generated successfully!")
        
        # Save token
        print("\n6. Saving token...")
        saved_files = self.save_token(access_token, debug_mode=True)
        
        # Success summary
        print(f"\n{'='*60}")
        print("🎉 DEBUG TOKEN GENERATED SUCCESSFULLY!")
        print("="*60)
        print(f"Token: {access_token[:20]}...")
        print(f"Generated: {self.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}")
        print(f"Saved to: {', '.join(saved_files)}")
        print()
        print("✅ Ready for development work!")
        print()
        print("Use this token for:")
        print("  • Backtesting your strategies")
        print("  • Historical data analysis")
        print("  • System testing and development")
        print("  • API integration testing")
        print()
        print("Example usage in your Python scripts:")
        print("```python")
        print("from kiteconnect import KiteConnect")
        print()
        print("# Read the debug token")
        print("with open('debug_token.txt', 'r') as f:")
        print("    access_token = f.read().strip()")
        print()
        print("# Initialize KiteConnect")
        print(f"kite = KiteConnect(api_key='{self.config['api_key']}')")
        print("kite.set_access_token(access_token)")
        print()
        print("# Now you can use the API for development")
        print("# Example: Get historical data")
        print("# data = kite.historical_data(instrument_token, from_date, to_date, interval)")
        print("```")
        print()
        
        # Send success notification
        success_message = f"""
🎉 <b>DEBUG Token Generated Successfully!</b>

📅 Time: {self.get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}
🔑 Token: {access_token[:20]}...
💾 Saved to: {', '.join(saved_files)}

<b>🛠️ Ready for Development!</b>

<b>✅ Perfect for:</b>
• Backtesting strategies
• Historical data analysis
• System testing & development
• API integration testing

<b>⚠️ Note:</b>
This is a development token. Market data may be limited outside trading hours.
        """
        
        self.send_telegram_notification(success_message)
        
        print("💡 Pro tip: You can run this script anytime to generate fresh tokens for development!")
        
        return True

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Debug Token Generator for Zerodha KiteConnect API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 debug_token_generator.py
  python3 debug_token_generator.py --config my_config.json
  python3 debug_token_generator.py --interactive

This tool generates Zerodha authentication tokens anytime for development purposes.
Perfect for backtesting, data analysis, and system testing outside market hours.
        """
    )
    
    parser.add_argument(
        '--config', 
        default='config.json',
        help='Configuration file path (default: config.json)'
    )
    
    parser.add_argument(
        '--interactive',
        action='store_true',
        help='Force interactive mode even if config exists'
    )
    
    args = parser.parse_args()
    
    try:
        # Force manual config if interactive mode
        if args.interactive:
            generator = DebugTokenGenerator()
            generator.config = generator.get_manual_config()
        else:
            generator = DebugTokenGenerator(args.config)
        
        success = generator.generate_debug_token()
        
        if success:
            print("\n🚀 Token generation completed successfully!")
            sys.exit(0)
        else:
            print("\n❌ Token generation failed!")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
