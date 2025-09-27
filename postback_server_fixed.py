#!/usr/bin/env python3
"""
Fixed Postback Server for Zerodha Authentication
Properly handles token storage and communicates with token generator
"""

import os
import logging
import json
import time
from datetime import datetime
from flask import Flask, request, jsonify
import pytz

# Setup logging
os.makedirs('/home/ubuntu/main_trading/logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/ubuntu/main_trading/logs/postback_server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class FixedPostbackServer:
    def __init__(self):
        self.app = Flask(__name__)
        self.ist_tz = pytz.timezone('Asia/Kolkata')
        
        # Load configurations
        self.load_config()
        
        # Token storage
        self.request_token = None
        self.token_timestamp = None
        
        # Ensure data directories exist
        os.makedirs('/home/ubuntu/main_trading/data', exist_ok=True)
        os.makedirs('/home/ubuntu/main_trading/data/tokens', exist_ok=True)
        
        self.setup_routes()
        logger.info("Fixed Postback Server initialized")

    def load_config(self):
        """Load configuration files"""
        try:
            with open('/home/ubuntu/main_trading/config.json', 'r') as f:
                self.config = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config.json: {e}")
            self.config = {}
            
        try:
            with open('/home/ubuntu/main_trading/data/token_config.json', 'r') as f:
                self.token_config = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load token config: {e}")
            self.token_config = {
                "request_token_file": "/home/ubuntu/main_trading/data/request_token.txt",
                "access_token_file": "/home/ubuntu/main_trading/data/access_token.txt",
                "token_backup_dir": "/home/ubuntu/main_trading/data/tokens",
                "token_timeout_seconds": 300
            }

    def save_token_with_metadata(self, token):
        """Save token with timestamp and metadata"""
        timestamp = datetime.now(self.ist_tz)
        
        # Save main token file
        token_file = self.token_config['request_token_file']
        with open(token_file, 'w') as f:
            f.write(token)
        
        # Save backup with timestamp
        backup_file = f"{self.token_config['token_backup_dir']}/request_token_{timestamp.strftime('%Y%m%d_%H%M%S')}.txt"
        with open(backup_file, 'w') as f:
            f.write(token)
        
        # Save metadata
        metadata = {
            'token': token[:10] + '...',  # Partial token for logging
            'timestamp': timestamp.isoformat(),
            'source': 'zerodha_postback',
            'server_time': timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')
        }
        
        with open(f"{token_file}.meta", 'w') as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Token saved: {token_file}")
        logger.info(f"Backup saved: {backup_file}")

    def setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/')
        def home():
            return jsonify({
                'status': 'running',
                'service': 'Fixed Zerodha Postback Server',
                'timestamp': datetime.now(self.ist_tz).strftime('%Y-%m-%d %H:%M:%S %Z'),
                'version': '2.0'
            })

        @self.app.route('/health')
        def health():
            token_age = (datetime.now(self.ist_tz).timestamp() - self.token_timestamp) if self.token_timestamp else 0
            return jsonify({
                'status': 'healthy',
                'timestamp': datetime.now(self.ist_tz).strftime('%Y-%m-%d %H:%M:%S %Z'),
                'request_token': 'present' if self.request_token else None,
                'token_age_seconds': token_age,
                'needs_refresh': token_age > self.token_config.get('token_timeout_seconds', 300)
            })

        @self.app.route('/postback', methods=['GET', 'POST'])
        def postback():
            try:
                # Log the request
                logger.info(f"Postback received: {request.method}")
                logger.info(f"Args: {dict(request.args)}")
                logger.info(f"Form: {dict(request.form)}")
                
                # Get parameters
                request_token = request.form.get('request_token') or request.args.get('request_token')
                status = request.form.get('status') or request.args.get('status')
                action = request.form.get('action') or request.args.get('action')
                
                if status != 'success' or not request_token:
                    logger.error(f"Invalid postback: status={status}, token_present={bool(request_token)}")
                    return jsonify({'status': 'error', 'message': 'Invalid parameters'}), 400

                # Store token
                self.request_token = request_token
                self.token_timestamp = datetime.now(self.ist_tz).timestamp()
                
                # Save to files
                self.save_token_with_metadata(request_token)
                
                logger.info("✅ Request token received and saved successfully")
                
                return '''
                <html>
                    <head><title>✅ Authentication Successful</title></head>
                    <body style="font-family: Arial; text-align: center; padding: 50px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
                        <div style="background: white; padding: 40px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 500px; margin: 0 auto;">
                            <h1 style="color: #28a745; margin-bottom: 20px;">🎉 Authentication Successful!</h1>
                            <p style="font-size: 18px; margin: 15px 0;">Request token has been received and saved.</p>
                            <p style="color: #666; margin: 15px 0;">Token Generator will now process your authentication.</p>
                            <div style="background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                                <strong>✅ You can safely close this window now</strong>
                            </div>
                            <hr style="margin: 20px 0;">
                            <small style="color: #666;">Sensex Trading System v2.0 - Fixed Postback Server</small>
                        </div>
                    </body>
                </html>
                '''
                
            except Exception as e:
                logger.error(f"Postback error: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/get_token')
        def get_token():
            """Get current token for token generator"""
            try:
                if not self.request_token:
                    return jsonify({'status': 'no_token', 'message': 'No token available'}), 404
                
                token_age = datetime.now(self.ist_tz).timestamp() - self.token_timestamp
                timeout = self.token_config.get('token_timeout_seconds', 300)
                
                if token_age > timeout:
                    logger.warning(f"Token expired: age={token_age}s, timeout={timeout}s")
                    return jsonify({'status': 'expired', 'message': 'Token expired', 'age_seconds': token_age}), 410
                
                return jsonify({
                    'status': 'success',
                    'request_token': self.request_token,
                    'age_seconds': token_age,
                    'timestamp': datetime.fromtimestamp(self.token_timestamp, self.ist_tz).isoformat()
                })
                
            except Exception as e:
                logger.error(f"Get token error: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/clear_token')
        def clear_token():
            """Clear stored token"""
            try:
                self.request_token = None
                self.token_timestamp = None
                
                # Remove token file
                token_file = self.token_config['request_token_file']
                if os.path.exists(token_file):
                    os.remove(token_file)
                if os.path.exists(f"{token_file}.meta"):
                    os.remove(f"{token_file}.meta")
                
                logger.info("Token cleared successfully")
                return jsonify({'status': 'success', 'message': 'Token cleared'})
                
            except Exception as e:
                logger.error(f"Clear token error: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 500

    def run(self, host='0.0.0.0', port=8001):
        """Run the server"""
        try:
            logger.info(f"Starting Fixed Postback Server on {host}:{port}")
            self.app.run(host=host, port=port, debug=False, threaded=True)
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            raise

if __name__ == "__main__":
    server = FixedPostbackServer()
    server.run()
