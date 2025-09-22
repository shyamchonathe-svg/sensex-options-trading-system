#!/usr/bin/env python3
"""
Production HTTPS Postback Server for Kite Connect
Runs on port 443 (HTTPS) and 8001 (HTTP fallback)
"""

import os
import sys
import json
import ssl
import time
import logging
import threading
from config_manager import SecureConfigManager as ConfigManager
from datetime import datetime
from flask import Flask, request, jsonify
from werkzeug.serving import make_server
import requests
import pytz

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('postback_server.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

class ProductionPostbackServer:
    def __init__(self):
        self.app = Flask(__name__)
        self.request_token = None
        self.token_timestamp = None
        self.config = self.load_config()
        self.ist_tz = pytz.timezone('Asia/Kolkata')
        self.setup_routes()
        
        # SSL paths
        self.cert_path = "/etc/letsencrypt/live/sensexbot.ddns.net/fullchain.pem"
        self.key_path = "/etc/letsencrypt/live/sensexbot.ddns.net/privkey.pem"
        
    def load_config(self):
        """Load configuration"""
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
            return {
                "api_key": config.get("api_key"),
                "telegram_token": config.get("telegram_token"),
                "chat_id": config.get("chat_id"),
                "server_host": config.get("server_host", "sensexbot.ddns.net"),
                "auth_timeout_seconds": config.get("auth_timeout_seconds", 300)
            }
        except Exception as e:
            logger.error(f"Config error: {e}")
            return {
                "api_key": null,
                "telegram_token": null,
                "chat_id": null,
                "server_host": "sensexbot.ddns.net",
                "auth_timeout_seconds": 300
            }
    
    def check_ssl_certificates(self):
        """Check if SSL certificates are accessible"""
        try:
            # Check if files exist and are readable
            if not os.path.exists(self.cert_path):
                logger.error(f"Certificate not found: {self.cert_path}")
                return False
            
            if not os.path.exists(self.key_path):
                logger.error(f"Private key not found: {self.key_path}")
                return False
            
            # Try to read the files
            with open(self.cert_path, 'r') as f:
                cert_content = f.read()
            
            with open(self.key_path, 'r') as f:
                key_content = f.read()
            
            if not cert_content or not key_content:
                logger.error("Certificate files are empty")
                return False
            
            # Test SSL context creation
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(self.cert_path, self.key_path)
            
            logger.info("SSL certificates verified successfully")
            return True
            
        except PermissionError:
            logger.error("Permission denied reading SSL certificates")
            logger.error("Run: sudo chown root:ssl-cert /etc/letsencrypt/live/sensexbot.ddns.net/privkey.pem")
            logger.error("Run: sudo chmod 640 /etc/letsencrypt/live/sensexbot.ddns.net/privkey.pem")
            return False
        except Exception as e:
            logger.error(f"SSL certificate error: {e}")
            return False
    
    def handle_postback_logic(self):
        """Common postback handling logic"""
        try:
            ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
            
            request_token = request.args.get('request_token')
            action = request.args.get('action', 'login')
            status = request.args.get('status', 'success')
            
            logger.info(f"Postback received at {ist_time}")
            logger.info(f"   Action: {action}, Status: {status}")
            logger.info(f"   Token: {request_token[:20]}..." if request_token else "   No token")
            logger.info(f"   User Agent: {request.headers.get('User-Agent', 'Unknown')}")
            
            if request_token and status == 'success':
                # Store token
                self.request_token = request_token
                self.token_timestamp = datetime.now(self.ist_tz)
                
                # Save to file as backup
                try:
                    with open('request_token.txt', 'w') as f:
                        f.write(request_token)
                    logger.info("Token saved to file")
                except Exception as e:
                    logger.warning(f"Could not save token to file: {e}")
                
                # Send Telegram notification
                self.send_telegram_notification(f"""
<b>Kite Authentication Successful!</b>

Time: {ist_time}
Token: <code>{request_token[:20]}...</code>
Protocol: HTTPS
Server: {self.config['server_host']}

Your trading system is authenticated!
Token expires in {self.config['auth_timeout_seconds']} seconds
                """)
                
                # Return beautiful success page
                return f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Authentication Successful</title>
                    <meta charset="utf-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <style>
                        body {{
                            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                            margin: 0; padding: 0;
                            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                            min-height: 100vh;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            color: white;
                        }}
                        .container {{
                            background: rgba(255,255,255,0.1);
                            padding: 40px;
                            border-radius: 20px;
                            backdrop-filter: blur(10px);
                            border: 1px solid rgba(255,255,255,0.2);
                            text-align: center;
                            max-width: 500px;
                            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
                        }}
                        .success-icon {{ font-size: 64px; margin-bottom: 20px; }}
                        h1 {{ margin: 20px 0; font-size: 28px; }}
                        .token-box {{
                            background: rgba(0,0,0,0.3);
                            padding: 15px;
                            border-radius: 10px;
                            font-family: 'Courier New', monospace;
                            margin: 20px 0;
                            word-break: break-all;
                            font-size: 14px;
                        }}
                        .info {{ font-size: 16px; line-height: 1.6; opacity: 0.9; }}
                        .countdown {{ font-size: 14px; opacity: 0.7; margin-top: 30px; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="success-icon">🎉</div>
                        <h1>Authentication Successful!</h1>
                        
                        <div class="info">
                            <p><strong>Time:</strong> {ist_time}</p>
                            <p><strong>Protocol:</strong> HTTPS</p>
                            <div class="token-box">
                                <strong>Token:</strong><br>
                                {request_token[:20]}...
                            </div>
                            <p>Your Zerodha account has been successfully authenticated with your trading system.</p>
                            <p><strong>You can now close this window.</strong></p>
                        </div>
                        
                        <div class="countdown">
                            <p>Server: {self.config['server_host']}</p>
                            <p>Auto-closing in <span id="countdown">10</span> seconds</p>
                        </div>
                    </div>
                    
                    <script>
                        let seconds = 10;
                        const countdownEl = document.getElementById('countdown');
                        
                        const timer = setInterval(() => {{
                            seconds--;
                            countdownEl.textContent = seconds;
                            
                            if (seconds <= 0) {{
                                clearInterval(timer);
                                window.close();
                            }}
                        }}, 1000);
                    </script>
                </body>
                </html>
                """
            
            else:
                # Authentication failed
                error_reason = request.args.get('error_type', 'Authentication failed')
                
                logger.error(f"Authentication failed: {error_reason}")
                
                self.send_telegram_notification(f"""
<b>Kite Authentication Failed</b>

Time: {ist_time}
Reason: {error_reason}
Protocol: HTTPS
Server: {self.config['server_host']}

Please try again or check your Zerodha credentials.
                """)
                
                return f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Authentication Failed</title>
                    <meta charset="utf-8">
                    <style>
                        body {{
                            font-family: Arial, sans-serif;
                            background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
                            color: white; text-align: center; padding: 50px;
                        }}
                        .container {{
                            background: rgba(255,255,255,0.1);
                            padding: 40px; border-radius: 15px;
                            backdrop-filter: blur(10px);
                        }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h1>Authentication Failed</h1>
                        <p><strong>Time:</strong> {ist_time}</p>
                        <p><strong>Reason:</strong> {error_reason}</p>
                        <p>Please try authenticating again.</p>
                    </div>
                </body>
                </html>
                """, 400
                
        except Exception as e:
            logger.error(f"Postback handling error: {e}")
            return jsonify({"error": "Internal server error"}), 500

    def setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/')
        def health_check():
            ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
            
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Zerodha Postback Server</title>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; background: #f0f8ff; }}
                    .container {{ background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
                    .status {{ padding: 15px; margin: 10px 0; border-radius: 5px; }}
                    .success {{ background: #d4edda; border-left: 4px solid #28a745; }}
                    .info {{ background: #d1ecf1; border-left: 4px solid #17a2b8; }}
                    h1 {{ color: #007bff; margin-top: 0; }}
                    .endpoint {{ font-family: monospace; background: #f8f9fa; padding: 5px; border-radius: 3px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>Zerodha HTTPS Postback Server</h1>
                    
                    <div class="status success">
                        <h3>Server Status: RUNNING</h3>
                        <p><strong>Time:</strong> {ist_time}</p>
                        <p><strong>Host:</strong> {self.config['server_host']}</p>
                        <p><strong>Protocol:</strong> HTTPS + HTTP</p>
                        <p><strong>SSL:</strong> {'Active' if self.check_ssl_certificates() else 'Issues'}</p>
                    </div>
                    
                    <div class="status info">
                        <h3>Endpoints</h3>
                        <p><strong>HTTPS Health:</strong> <span class="endpoint">https://sensexbot.ddns.net/</span></p>
                        <p><strong>HTTPS Status:</strong> <span class="endpoint">https://sensexbot.ddns.net/status</span></p>
                        <p><strong>Health Check:</strong> <span class="endpoint">https://sensexbot.ddns.net/health</span></p>
                        <p><strong>Postback:</strong> <span class="endpoint">https://sensexbot.ddns.net/postback</span></p>
                        <p><strong>HTTP Fallback:</strong> <span class="endpoint">http://sensexbot.ddns.net:8001/</span></p>
                    </div>
                    
                    <div class="status info">
                        <h3>Token Status</h3>
                        <p><strong>Available:</strong> {'Yes' if self.request_token else 'No'}</p>
                        <p><strong>Age:</strong> {self.get_token_age()}s</p>
                        <p><strong>Timeout:</strong> {self.config['auth_timeout_seconds']}s</p>
                    </div>
                    
                    <div class="status info">
                        <h3>Quick Actions</h3>
                        <p><a href="/status">JSON Status</a> | <a href="/get_token">Get Token</a> | <a href="/clear_token">Clear Token</a></p>
                    </div>
                </div>
            </body>
            </html>
            """
        
        @self.app.route('/health')
        def health():
            """Health check endpoint for trading system detection"""
            return jsonify({"status": "ok", "server": "running"})
        
        @self.app.route('/status')
        def status_api():
            ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
            
            return jsonify({
                "status": "running",
                "server": "Zerodha HTTPS Postback Server",
                "time": ist_time,
                "host": self.config['server_host'],
                "ssl_active": self.check_ssl_certificates(),
                "protocol": "HTTPS",
                "endpoints": {
                    "https": f"https://{self.config['server_host']}/",
                    "http": f"http://{self.config['server_host']}:8001/",
                    "postback": f"https://{self.config['server_host']}/postback",
                    "health": f"https://{self.config['server_host']}/health"
                },
                "token": {
                    "available": bool(self.request_token),
                    "age_seconds": self.get_token_age(),
                    "timeout_seconds": self.config['auth_timeout_seconds']
                }
            })
        
        @self.app.route('/postback')
        def postback():
            return self.handle_postback_logic()
        
        @self.app.route('/redirect')
        def redirect_handler():
            # Both /postback and /redirect should handle the same logic
            return self.handle_postback_logic()
        
        @self.app.route('/get_token')
        def get_token():
            if not self.request_token:
                return jsonify({"status": "error", "message": "No token available"}), 404
            
            age = self.get_token_age()
            
            if age > self.config['auth_timeout_seconds']:
                self.request_token = None
                self.token_timestamp = None
                return jsonify({"status": "error", "message": "Token expired"}), 410
            
            return jsonify({
                "status": "success",
                "request_token": self.request_token,
                "timestamp": self.token_timestamp.strftime("%Y-%m-%d %H:%M:%S IST"),
                "age_seconds": age,
                "protocol": "HTTPS"
            })
        
        @self.app.route('/clear_token')
        def clear_token():
            self.request_token = None
            self.token_timestamp = None
            
            try:
                if os.path.exists('request_token.txt'):
                    os.remove('request_token.txt')
            except:
                pass
            
            return jsonify({"status": "success", "message": "Token cleared"})
    
    def get_token_age(self):
        if not self.token_timestamp:
            return 0
        return int((datetime.now(self.ist_tz) - self.token_timestamp).total_seconds())
    
    def send_telegram_notification(self, message):
        try:
            if not self.config['telegram_token']:
                logger.warning("No Telegram token configured")
                return False
            
            url = f"https://api.telegram.org/bot{self.config['telegram_token']}/sendMessage"
            data = {
                "chat_id": self.config['chat_id'],
                "text": message,
                "parse_mode": "HTML"
            }
            
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                logger.info("Telegram notification sent")
                return True
            else:
                logger.error(f"Telegram API error: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Telegram notification error: {e}")
            return False
    
    def create_ssl_context(self):
        """Create SSL context"""
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(self.cert_path, self.key_path)
            return context
        except Exception as e:
            logger.error(f"SSL context creation failed: {e}")
            return None
    
    def run_http_server(self):
        """Run HTTP server on port 8001"""
        try:
            logger.info("Starting HTTP server on port 8001...")
            http_server = make_server('0.0.0.0', 8001, self.app)
            http_server.serve_forever()
        except Exception as e:
            logger.error(f"HTTP server error: {e}")
    
    def run_https_server(self):
        """Run HTTPS server on port 443"""
        try:
            ssl_context = self.create_ssl_context()
            if not ssl_context:
                logger.error("Cannot start HTTPS server - SSL context failed")
                return
            
            logger.info("Starting HTTPS server on port 443...")
            https_server = make_server('0.0.0.0', 443, self.app, ssl_context=ssl_context)
            https_server.serve_forever()
        except Exception as e:
            logger.error(f"HTTPS server error: {e}")
    
    def run(self):
        """Run the server"""
        ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
        
        logger.info("=" * 60)
        logger.info(f"STARTING PRODUCTION HTTPS POSTBACK SERVER")
        logger.info(f"   Time: {ist_time}")
        logger.info("=" * 60)
        
        # Check SSL certificates
        ssl_ok = self.check_ssl_certificates()
        
        if not ssl_ok:
            logger.error("SSL certificate issues detected!")
            logger.error("   Please run the SSL setup commands first:")
            logger.error("   sudo certbot certonly --standalone --domains sensexbot.ddns.net")
            logger.error("   sudo chown root:ssl-cert /etc/letsencrypt/live/sensexbot.ddns.net/privkey.pem")
            logger.error("   sudo chmod 640 /etc/letsencrypt/live/sensexbot.ddns.net/privkey.pem")
            sys.exit(1)
        
        logger.info(f"Host: {self.config['server_host']}")
        logger.info(f"SSL: Active")
        logger.info("=" * 60)
        
        # Start servers in threads
        threads = []
        
        # HTTP server (port 8001) - for fallback and testing
        http_thread = threading.Thread(target=self.run_http_server, daemon=True)
        http_thread.start()
        threads.append(http_thread)
        
        # HTTPS server (port 443) - main production server
        https_thread = threading.Thread(target=self.run_https_server, daemon=True)
        https_thread.start()
        threads.append(https_thread)
        
        # Give servers time to start
        time.sleep(2)
        
        logger.info("SERVERS STARTED SUCCESSFULLY!")
        logger.info("")
        logger.info("ENDPOINTS:")
        logger.info(f"   HTTPS Production: https://{self.config['server_host']}/")
        logger.info(f"   HTTP Testing:     http://{self.config['server_host']}:8001/")
        logger.info(f"   Health Check:     https://{self.config['server_host']}/health")
        logger.info(f"   Kite Postback:    https://{self.config['server_host']}/postback")
        logger.info("")
        logger.info("TEST COMMANDS:")
        logger.info(f"   curl https://{self.config['server_host']}/status")
        logger.info(f"   curl http://localhost:8001/health")
        logger.info("=" * 60)
        
        try:
            # Keep main thread alive
            while True:
                time.sleep(60)
                # Heartbeat every 10 minutes
                if int(time.time()) % 600 == 0:
                    current_time = datetime.now(self.ist_tz).strftime("%H:%M:%S IST")
                    logger.info(f"Server heartbeat: {current_time}")
        
        except KeyboardInterrupt:
            logger.info("Server stopped by user")
        except Exception as e:
            logger.error(f"Server error: {e}")

def main():
    """Main function"""
    try:
        server = ProductionPostbackServer()
        server.run()
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
