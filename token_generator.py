#!/usr/bin/env python3
"""
Zerodha Token Generator
Generates Kite auth URL and processes request_token to obtain access_token.
"""

import logging
import os
import json
import argparse
from datetime import datetime, time
import asyncio
from kiteconnect import KiteConnect
from utils.notification_service import NotificationService

logger = logging.getLogger(__name__)

class TokenGenerator:
    def __init__(self, config_path='/home/ubuntu/main_trading/config.json'):
        logger.info("Initializing TokenGenerator...")
        try:
            with open(config_path, 'r') as f:
                self.config = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            raise
        
        self.api_key = self.config.get('api_key')
        self.api_secret = self.config.get('api_secret')
        self.server_host = self.config.get('server_host', 'sensexbot.ddns.net')
        self.notification_service = NotificationService(self.config)
        self.kite = KiteConnect(api_key=self.api_key)
        self.token_file = '/home/ubuntu/main_trading/data/request_token.txt'
        self.auth_timeout = self.config.get('auth_timeout_seconds', 300)
        self.market_start = self.config.get('market_start', '09:15')
        self.market_end = self.config.get('market_end', '15:30')
        logger.info(f"Config loaded: server_host={self.server_host}, api_key={self.api_key[:5]}...")

    async def send_notification(self, alert_data):
        """Send notification with error handling."""
        try:
            result = await self.notification_service.send_system_alert(alert_data)
            if result:
                logger.info("✅ Notification sent successfully")
            else:
                logger.warning("⚠️ Notification failed to send")
            return result
        except Exception as e:
            logger.error(f"❌ Notification error: {e}")
            return False

    async def generate_auth_url(self):
        """Generate and send Kite auth URL via Telegram."""
        logger.info("Generating auth URL...")
        print("🔄 Generating authentication URL...")
        
        try:
            auth_url = self.kite.login_url()
            logger.info(f"Auth URL generated: {auth_url}")
            print(f"✅ Auth URL generated successfully")
            
            # Send to Telegram
            await self.send_notification({
                "type": "INFO",
                "component": "TokenGenerator",
                "message": f"Auth URL: {auth_url}",
                "mode": "LIVE/TEST",
                "action": "Click to authenticate"
            })
            
            print(f"📱 Notification sent to Telegram")
            print(f"🔗 AUTH URL: {auth_url}")
            return auth_url
            
        except Exception as e:
            logger.error(f"Failed to generate auth URL: {e}")
            print(f"❌ Failed to generate auth URL: {e}")
            
            await self.send_notification({
                "type": "ERROR",
                "component": "TokenGenerator",
                "message": f"Failed to generate auth URL: {str(e)[:100]}",
                "mode": "LIVE/TEST",
                "action": "Check API key and configuration"
            })
            raise

    async def watch_for_token(self):
        """Monitor for request_token and generate access_token during market hours."""
        logger.info("Starting watch_for_token...")
        print("📁 Starting token file monitor...")
        
        try:
            start_time = time(*map(int, self.market_start.split(':')))
            end_time = time(*map(int, self.market_end.split(':')))
            timeout_end = datetime.now().timestamp() + self.auth_timeout
            
            logger.info(f"Market hours: {self.market_start}-{self.market_end}, timeout in {self.auth_timeout}s")
            print(f"⏰ Market hours: {self.market_start}-{self.market_end}")
            print(f"⏳ Will timeout in {self.auth_timeout} seconds")
            print(f"📍 Looking for: {self.token_file}")

            check_count = 0
            while True:
                check_count += 1
                current_time = datetime.now().time()
                
                if check_count % 10 == 0:  # Print progress every 10 checks (20 seconds)
                    logger.info(f"Check #{check_count} - Still monitoring...")
                    print(f"🔍 Still monitoring... (check #{check_count})")

                if os.path.exists(self.token_file):
                    logger.info(f"Found token file: {self.token_file}")
                    print(f"✅ Found token file!")
                    
                    with open(self.token_file, 'r') as f:
                        request_token = f.read().strip()
                        
                    if not request_token:
                        logger.error("Token file is empty")
                        print("❌ Token file is empty")
                        await self.send_notification({
                            "type": "ERROR",
                            "component": "TokenGenerator",
                            "message": "Token file is empty",
                            "mode": "LIVE/TEST",
                            "action": "Check token file content"
                        })
                        return False
                    
                    if len(request_token) < 10:
                        logger.error("Invalid request_token: Length must be at least 10 characters")
                        print("❌ Invalid request_token: Length must be at least 10 characters")
                        await self.send_notification({
                            "type": "ERROR",
                            "component": "TokenGenerator",
                            "message": "Invalid request_token: Length must be at least 10 characters",
                            "mode": "LIVE/TEST",
                            "action": "Verify request_token in file"
                        })
                        if os.path.exists(self.token_file):
                            os.remove(self.token_file)
                        return False
                    
                    try:
                        logger.info(f"Processing request_token: {request_token[:10]}...")
                        print(f"🔄 Processing request token: {request_token[:10]}...")
                        
                        data = self.kite.generate_session(request_token, self.api_secret)
                        access_token = data['access_token']
                        self.config['access_token'] = access_token
                        
                        with open('/home/ubuntu/main_trading/config.json', 'w') as f:
                            json.dump(self.config, f, indent=4)
                            
                        logger.info("Access token generated and saved")
                        print(f"✅ Access token generated and saved!")
                        
                        await self.send_notification({
                            "type": "SUCCESS",
                            "component": "TokenGenerator",
                            "message": f"Access token generated: {access_token[:10]}...",
                            "mode": "LIVE/TEST",
                            "action": "None"
                        })
                        
                        os.remove(self.token_file)
                        logger.info("Token file removed - SUCCESS!")
                        print(f"🎉 SUCCESS: Authentication completed!")
                        return True
                        
                    except Exception as e:
                        logger.error(f"Failed to generate access_token: {e}")
                        print(f"❌ Failed to generate access token: {e}")
                        
                        await self.send_notification({
                            "type": "ERROR",
                            "component": "TokenGenerator",
                            "message": f"Access token generation failed: {str(e)[:100]}",
                            "mode": "LIVE/TEST",
                            "action": "Check request_token and API secret"
                        })
                        
                        if os.path.exists(self.token_file):
                            os.remove(self.token_file)
                        return False
                        
                if datetime.now().timestamp() > timeout_end:
                    logger.error("Authentication timeout")
                    print("⏰ Authentication timeout!")
                    
                    await self.send_notification({
                        "type": "ERROR",
                        "component": "TokenGenerator",
                        "message": "Authentication timed out",
                        "mode": "LIVE/TEST",
                        "action": "Restart token generator"
                    })
                    return False
                    
                await asyncio.sleep(2)  # Check every 2 seconds
                
        except Exception as e:
            logger.error(f"Error in watch_for_token: {e}")
            print(f"💥 Error in token monitor: {e}")
            
            await self.send_notification({
                "type": "ERROR",
                "component": "TokenGenerator",
                "message": f"Token watch error: {str(e)[:100]}",
                "mode": "LIVE/TEST",
                "action": "Check code and configuration"
            })
            raise

    async def run(self, debug=False):
        """Run the token generator in debug or normal mode."""
        logger.info(f"Running in {'debug' if debug else 'normal'} mode")
        print(f"🚀 Running in {'DEBUG' if debug else 'NORMAL'} mode")
        
        try:
            if debug:
                print("=== DEBUG MODE ===")
                await self.generate_auth_url()
                result = await self.watch_for_token()
                if result:
                    print("🎉 DEBUG MODE COMPLETED SUCCESSFULLY!")
                else:
                    print("❌ DEBUG MODE FAILED!")
            else:
                result = await self.watch_for_token()
                
        except Exception as e:
            logger.error(f"Fatal error in run: {e}")
            print(f"💥 FATAL ERROR: {e}")
            
            await self.send_notification({
                "type": "ERROR",
                "component": "TokenGenerator",
                "message": f"Fatal error: {str(e)[:100]}",
                "mode": "LIVE/TEST",
                "action": "Check logs and restart"
            })
            raise

async def main():
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('/home/ubuntu/main_trading/logs/token_generator.log'),
            logging.StreamHandler()
        ]
    )

    parser = argparse.ArgumentParser(description="Zerodha Token Generator")
    parser.add_argument('--debug', action='store_true', help="Run in debug mode")
    args = parser.parse_args()

    print("🚀 Starting Token Generator...")
    logger.info("Starting main...")
    
    try:
        token_generator = TokenGenerator()
        await token_generator.run(debug=args.debug)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"💥 FATAL ERROR: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
