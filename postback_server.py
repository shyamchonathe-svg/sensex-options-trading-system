#!/usr/bin/env python3
"""
Production HTTPS Postback Server for Kite Connect
Runs on port 443 (HTTPS) and 8001 (HTTP fallback)
Updated to handle Nginx conflicts
"""

import os
import sys
import json
import ssl
import time
import logging
import threading
import socket
import subprocess
# FIXED: Import from the correct module
from utils.secure_config_manager import SecureConfigManager
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
        # FIXED: Use SecureConfigManager instead of manual config loading
        self.config_manager = SecureConfigManager()
        self.config = self._get_config()
        self.ist_tz = pytz.timezone('Asia/Kolkata')
        self.setup_routes()
        
        # SSL paths
        self.cert_path = "/etc/letsencrypt/live/sensexbot.ddns.net/fullchain.pem"
        self.key_path = "/etc/letsencrypt/live/sensexbot.ddns.net/privkey.pem"
    
    def _get_config(self):
        """Get configuration using SecureConfigManager."""
        return {
            "api_key": self.config_manager.get("api_key"),
            "telegram_token": self.config_manager.get("telegram_token"),
            "chat_id": self.config_manager.get("chat_id"),
            "server_host": self.config_manager.get("server_host", "sensexbot.ddns.net"),
            "auth_timeout_seconds": self.config_manager.get("auth_timeout_seconds", 300)
        }
    
    def check_nginx_running(self):
        """Check if Nginx is running and using port 443"""
        try:
            result = subprocess.run(['sudo', 'systemctl', 'is-active', 'nginx'], 
                                  capture_output=True, text=True)
            nginx_active = result.returncode == 0 and result.stdout.strip() == 'active'
            
            # Also check if something is listening on port 443
            result = subprocess.run(['sudo', 'lsof', '-i', ':443'], 
                                  capture_output=True, text=True)
            port_443_used = result.returncode == 0 and 'nginx' in result.stdout.lower()
            
            return nginx_active, port_443_used
        except Exception as e:
            logger.warning(f"Could not check nginx status: {e}")
            return False, False
    
    def setup_nginx_proxy(self):
        """Setup Nginx as reverse proxy for our postback server"""
        logger.info("Setting up Nginx reverse proxy configuration...")
        
        nginx_config = f"""
# Nginx configuration for Zerodha postback server
server {{
    listen 443 ssl http2;
    server_name {self.config['server_host']};
    
    # SSL certificates
    ssl_certificate /etc/letsencrypt/live/{self.config['server_host']}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{self.config['server_host']}/privkey.pem;
    
    # SSL security settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    
    # Proxy all requests to our Flask app on port 8001
    location / {{
        proxy_pass http://localhost:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
        proxy_read_timeout 300;
    }}
    
    # Specific handling for postback endpoint
    location /postback {{
        proxy_pass http://localhost:8001/postback;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
    
    # Health check endpoint
    location /health {{
        proxy_pass http://localhost:8001/health;
        proxy_set_header Host $host;
    }}
}}

# Optional: Redirect HTTP to HTTPS
server {{
    listen 80;
    server_name {self.config['server_host']};
    return 301 https://$server_name$request_uri;
}}
"""
        
        config_path = f"/etc/nginx/sites-available/{self.config['server_host']}"
        
        try:
            # Write the config
            with open(config_path, 'w') as f:
                f.write(nginx_config)
            
            # Enable the site
            link_path = f"/etc/nginx/sites-enabled/{self.config['server_host']}"
            if os.path.exists(link_path):
                os.remove(link_path)
            os.symlink(config_path, link_path)
            
            # Test nginx config
            result = subprocess.run(['sudo', 'nginx', '-t'], capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Nginx config test failed: {result.stderr}")
                return False
            
            # Reload nginx
            subprocess.run(['sudo', 'systemctl', 'reload', 'nginx'], check=True)
            logger.info("Nginx reverse proxy configured successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to setup Nginx proxy: {e}")
            return False
        
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
            
            # Log the forwarded headers from Nginx
            real_ip = request.headers.get('X-Real-IP', 'Unknown')
            forwarded_for = request.headers.get('X-Forwarded-For', 'Unknown')
            forwarded_proto = request.headers.get('X-Forwarded-Proto', 'Unknown')
            
            logger.info(f"Postback received at {ist_time}")
            logger.info(f"   Action: {action}, Status: {status}")
            logger.info(f"   Token: {request_token[:20]}..." if request_token else "   No token")
            logger.info(f"   Real IP: {real_ip}")
            logger.info(f"   Protocol: {forwarded_proto}")
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
Protocol: HTTPS (via Nginx)
Server: {self.config['server_host']}
Real IP: {real_ip}

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
                            <p><strong>Protocol:</strong> HTTPS (Nginx)</p>
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
Protocol: HTTPS (via Nginx)
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
            nginx_active, port_443_used = self.check_nginx_running()
            
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
                    .warning {{ background: #fff3cd; border-left: 4px solid #ffc107; }}
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
                        <p><strong>Protocol:</strong> HTTP (Backend) + HTTPS (Nginx Proxy)</p>
                        <p><strong>SSL:</strong> {'Active via Nginx' if nginx_active else 'Direct SSL Available' if self.check_ssl_certificates() else 'Issues'}</p>
                        <p><strong>Nginx:</strong> {'Running' if nginx_active else 'Not Running'}</p>
                    </div>
                    
                    <div class="status info">
                        <h3>Architecture</h3>
                        <p><strong>Setup:</strong> Nginx (Port 443) → Flask (Port 8001)</p>
                        <p><strong>HTTPS:</strong> Handled by Nginx with SSL certificates</p>
                        <p><strong>Backend:</strong> Flask app on HTTP port 8001</p>
                    </div>
                    
                    <div class="status info">
                        <h3>Endpoints</h3>
                        <p><strong>HTTPS Health:</strong> <span class="endpoint">https://sensexbot.ddns.net/</span></p>
                        <p><strong>HTTPS Status:</strong> <span class="endpoint">https://sensexbot.ddns.net/status</span></p>
                        <p><strong>Health Check:</strong> <span class="endpoint">https://sensexbot.ddns.net/health</span></p>
                        <p><strong>Postback:</strong> <span class="endpoint">https://sensexbot.ddns.net/postback</span></p>
                        <p><strong>Direct Backend:</strong> <span class="endpoint">http://localhost:8001/</span></p>
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
            nginx_active, port_443_used = self.check_nginx_running()
            
            return jsonify({
                "status": "running",
                "server": "Zerodha HTTPS Postback Server",
                "time": ist_time,
                "host": self.config['server_host'],
                "ssl_active": nginx_active or self.check_ssl_certificates(),
                "protocol": "HTTP Backend + HTTPS Nginx Proxy" if nginx_active else "Direct HTTPS",
                "nginx_running": nginx_active,
                "port_443_used": port_443_used,
                "endpoints": {
                    "https": f"https://{self.config['server_host']}/",
                    "http_backend": f"http://localhost:8001/",
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
            
            # Check if port 8001 is available
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.bind(('0.0.0.0', 8001))
                logger.info("Port 8001 is available")
            except OSError:
                logger.error("Port 8001 is already in use!")
                # Try to kill what's using it
                try:
                    subprocess.run(['sudo', 'fuser', '-k', '8001/tcp'], check=True)
                    logger.info("Killed process using port 8001")
                    time.sleep(2)
                except:
                    logger.error("Could not kill process on port 8001")
                    return
            
            http_server = make_server('0.0.0.0', 8001, self.app)
            logger.info("HTTP server started successfully on port 8001")
            http_server.serve_forever()
        except Exception as e:
            logger.error(f"HTTP server error: {e}")
    
    def run(self):
        """Run the server"""
        ist_time = datetime.now(self.ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
        
        logger.info("=" * 60)
        logger.info(f"STARTING PRODUCTION HTTPS POSTBACK SERVER")
        logger.info(f"   Time: {ist_time}")
        logger.info("=" * 60)
        
        # Check if Nginx is running
        nginx_active, port_443_used = self.check_nginx_running()
        
        if nginx_active and port_443_used:
            logger.info("NGINX DETECTED: Running with Nginx reverse proxy")
            logger.info("   Nginx handles HTTPS on port 443")
            logger.info("   Flask handles HTTP backend on port 8001")
            
            # Setup nginx configuration if needed
            config_exists = os.path.exists(f"/etc/nginx/sites-enabled/{self.config['server_host']}")
            if not config_exists:
                logger.info("Setting up Nginx reverse proxy configuration...")
                if self.setup_nginx_proxy():
                    logger.info("Nginx configuration created successfully")
                else:
                    logger.warning("Failed to create Nginx configuration")
            else:
                logger.info("Nginx configuration already exists")
                
        elif port_443_used:
            logger.warning("Port 443 is used by another service (not Nginx)")
            logger.warning("   Will run HTTP-only on port 8001")
        else:
            logger.info("No service using port 443 - could run direct HTTPS")
        
        # Check SSL certificates
        ssl_ok = self.check_ssl_certificates()
        
        logger.info(f"Host: {self.config['server_host']}")
        logger.info(f"SSL: {'Nginx handles SSL' if nginx_active else 'Direct SSL available' if ssl_ok else 'SSL issues detected'}")
        logger.info("=" * 60)
        
        # Start HTTP server (port 8001) - this is our main server now
        logger.info("Starting HTTP backend server...")
        
        try:
            # Start server in thread
            http_thread = threading.Thread(target=self.run_http_server, daemon=True)
            http_thread.start()
            
            # Give it time to start
            time.sleep(3)
            
            # Test if it's working
            try:
                response = requests.get('http://localhost:8001/health', timeout=5)
                if response.status_code == 200:
                    logger.info("✓ HTTP backend server is responding")
                    backend_ok = True
                else:
                    logger.error("✗ HTTP backend server returned error")
                    backend_ok = False
            except:
                logger.error("✗ HTTP backend server is not responding")
                backend_ok = False
            
            if not backend_ok:
                logger.error("CRITICAL: Backend server failed to start!")
                sys.exit(1)
        
        except Exception as e:
            logger.error(f"Failed to start HTTP server: {e}")
            sys.exit(1)
        
        # Final status
        logger.info("=" * 60)
        logger.info("SERVERS STARTED SUCCESSFULLY!")
        logger.info("")
        logger.info("ARCHITECTURE:")
        if nginx_active:
            logger.info("   Internet → Nginx (443/HTTPS) → Flask (8001/HTTP)")
            logger.info("   ✓ HTTPS handled by Nginx with SSL certificates")
            logger.info("   ✓ Flask backend running on HTTP port 8001")
        else:
            logger.info("   Internet → Flask (8001/HTTP only)")
            logger.info("   ⚠ No HTTPS - only HTTP on port 8001")
        
        logger.info("")
        logger.info("ENDPOINTS:")
        if nginx_active:
            logger.info(f"   ✓ HTTPS Production: https://{self.config['server_host']}/")
            logger.info(f"   ✓ Kite Postback:    https://{self.config['server_host']}/postback")
        logger.info(f"   ✓ HTTP Backend:     http://{self.config['server_host']}:8001/")
        logger.info(f"   ✓ Local Health:     http://localhost:8001/health")
        logger.info("")
        logger.info("TEST COMMANDS:")
        logger.info(f"   curl http://localhost:8001/status")
        logger.info(f"   curl http://localhost:8001/health")
        if nginx_active:
            logger.info(f"   curl https://{self.config['server_host']}/status")
        logger.info("=" * 60)
        
        try:
            # Keep main thread alive
            while True:
                time.sleep(60)
                # Heartbeat every 10 minutes
                if int(time.time()) % 600 == 0:
                    current_time = datetime.now(self.ist_tz).strftime("%H:%M:%S IST")
                    logger.info(f"Server heartbeat: {current_time} - Backend: ✓")
        
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
