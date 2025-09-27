#!/bin/bash
# Complete system fix script designed to work properly with virtual environment
# Run this INSIDE the activated virtual environment

set -e  # Exit on any error

echo "SENSEX TRADING SYSTEM - VENV FIX"
echo "================================"

# Check if we're in a virtual environment
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo "ERROR: This script must be run inside the virtual environment"
    echo "Please run: source venv/bin/activate"
    echo "Then run this script again"
    exit 1
fi

echo "Virtual environment detected: $VIRTUAL_ENV"
echo "Working directory: $(pwd)"

# Verify we're in the correct directory
if [[ ! -f "config.json" ]] || [[ ! -f "postback_server.py" ]]; then
    echo "ERROR: Please run this script from /home/ubuntu/main_trading"
    exit 1
fi

# 1. Fix permissions with proper error handling
echo "1. Fixing file permissions..."
sudo chown -R ubuntu:ubuntu /home/ubuntu/main_trading/data/ 2>/dev/null || echo "Some permission fixes failed (non-critical)"
sudo chmod -R 755 /home/ubuntu/main_trading/data/ 2>/dev/null || echo "Some chmod operations failed (non-critical)"

# Create directories safely
mkdir -p data/tokens data/temp logs/services archives/daily 2>/dev/null || true
echo "Directory structure created"

# 2. Install required Python packages in venv
echo "2. Installing/updating Python packages in virtual environment..."
pip install --upgrade pip
pip install flask requests kiteconnect pytz python-dotenv

# Verify installations
python3 -c "import flask, requests, kiteconnect, pytz; print('All required packages available')"
echo "Python dependencies verified"

# 3. Stop any existing processes
echo "3. Stopping existing processes..."
sudo pkill -f "postback_server.py" 2>/dev/null || true
sleep 2
echo "Existing processes stopped"

# 4. Create proper systemd services
echo "4. Creating systemd service files..."

mkdir -p services

# Postback server service
cat > services/postback_server.service << EOF
[Unit]
Description=Zerodha Postback Server (Venv)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/main_trading
Environment=PATH=$VIRTUAL_ENV/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=/home/ubuntu/main_trading
Environment=VIRTUAL_ENV=$VIRTUAL_ENV
ExecStart=$VIRTUAL_ENV/bin/python3 /home/ubuntu/main_trading/postback_server.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=postback-server

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/home/ubuntu/main_trading

# Process limits for free tier
TimeoutStartSec=30
TimeoutStopSec=30
KillMode=mixed

[Install]
WantedBy=multi-user.target
EOF

# Trading system service
cat > services/trading_system.service << EOF
[Unit]
Description=Sensex Options Trading System (Venv)
After=network-online.target postback_server.service
Wants=network-online.target
Requires=postback_server.service

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/main_trading
Environment=PATH=$VIRTUAL_ENV/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=/home/ubuntu/main_trading
Environment=VIRTUAL_ENV=$VIRTUAL_ENV
EnvironmentFile=/home/ubuntu/main_trading/.env

# Dynamic mode reading and execution
ExecStart=/bin/bash -c 'MODE=\$(cat /home/ubuntu/main_trading/.trading_mode 2>/dev/null || echo "TEST"); if [ "\$MODE" != "DISABLED" ]; then $VIRTUAL_ENV/bin/python3 /home/ubuntu/main_trading/main.py --mode \$(echo \$MODE | tr A-Z a-z); else echo "Trading disabled, sleeping..."; sleep infinity; fi'

ExecStop=/bin/bash -c 'echo "DISABLED" > /home/ubuntu/main_trading/.trading_mode'
ExecStopPost=/bin/bash -c 'if [ -f /home/ubuntu/main_trading/.trading_disabled ]; then rm -f /home/ubuntu/main_trading/.trading_disabled; fi'

Restart=on-failure
RestartSec=30
StartLimitIntervalSec=300
StartLimitBurst=3

# Resource limits for EC2 free tier
MemoryLimit=512M
CPUQuota=70%

StandardOutput=journal
StandardError=journal
SyslogIdentifier=trading-system

[Install]
WantedBy=multi-user.target
EOF

echo "Service files created with venv paths"

# 5. Install systemd services
echo "5. Installing systemd services..."
sudo cp services/postback_server.service /etc/systemd/system/
sudo cp services/trading_system.service /etc/systemd/system/
sudo chmod 644 /etc/systemd/system/postback_server.service
sudo chmod 644 /etc/systemd/system/trading_system.service

sudo systemctl daemon-reload
sudo systemctl enable postback_server.service
sudo systemctl enable trading_system.service
echo "Services installed and enabled"

# 6. Create token configuration
echo "6. Creating token management configuration..."

cat > data/token_config.json << 'EOF'
{
    "request_token_file": "/home/ubuntu/main_trading/data/request_token.txt",
    "access_token_file": "/home/ubuntu/main_trading/data/access_token.txt",
    "token_backup_dir": "/home/ubuntu/main_trading/data/tokens",
    "token_timeout_seconds": 300,
    "backup_tokens": true,
    "max_token_age_hours": 6,
    "auto_cleanup_old_tokens": true
}
EOF

echo "Token configuration created"

# 7. Enhance the existing postback server
echo "7. Enhancing postback server..."

# Backup original if not already backed up
if [ ! -f postback_server.py.original ]; then
    cp postback_server.py postback_server.py.original
    echo "Original postback server backed up"
fi

# Create enhanced postback server
cat > postback_server.py << 'EOF'
#!/usr/bin/env python3
"""
Enhanced Postback Server for Zerodha Authentication
Compatible with virtual environment and improved token handling
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

class EnhancedPostbackServer:
    def __init__(self):
        self.app = Flask(__name__)
        self.ist_tz = pytz.timezone('Asia/Kolkata')
        
        # Load configurations
        self.load_config()
        
        # Token storage
        self.request_token = None
        self.token_timestamp = None
        
        # Ensure directories exist
        os.makedirs('/home/ubuntu/main_trading/data', exist_ok=True)
        os.makedirs('/home/ubuntu/main_trading/data/tokens', exist_ok=True)
        
        self.setup_routes()
        logger.info("Enhanced Postback Server initialized")

    def load_config(self):
        """Load configuration files"""
        try:
            with open('/home/ubuntu/main_trading/config.json', 'r') as f:
                self.config = json.load(f)
            logger.info("Main config loaded")
        except Exception as e:
            logger.error(f"Failed to load config.json: {e}")
            self.config = {}
            
        try:
            with open('/home/ubuntu/main_trading/data/token_config.json', 'r') as f:
                self.token_config = json.load(f)
            logger.info("Token config loaded")
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
        try:
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
                'token': token[:10] + '...',  # Partial token for security
                'timestamp': timestamp.isoformat(),
                'source': 'zerodha_postback',
                'server_time': timestamp.strftime('%Y-%m-%d %H:%M:%S %Z'),
                'full_token_length': len(token)
            }
            
            with open(f"{token_file}.meta", 'w') as f:
                json.dump(metadata, f, indent=2)
            
            logger.info(f"Token saved: {token_file}")
            logger.info(f"Backup saved: {backup_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save token: {e}")
            return False

    def cleanup_old_tokens(self):
        """Clean up old token files"""
        try:
            import glob
            token_pattern = f"{self.token_config['token_backup_dir']}/request_token_*.txt"
            token_files = glob.glob(token_pattern)
            
            # Keep only the 10 most recent
            if len(token_files) > 10:
                token_files.sort()
                for old_file in token_files[:-10]:
                    os.remove(old_file)
                    logger.info(f"Cleaned up old token: {old_file}")
                    
        except Exception as e:
            logger.warning(f"Token cleanup failed: {e}")

    def setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/')
        def home():
            return jsonify({
                'status': 'running',
                'service': 'Enhanced Zerodha Postback Server',
                'timestamp': datetime.now(self.ist_tz).strftime('%Y-%m-%d %H:%M:%S %Z'),
                'version': '2.1-venv',
                'virtual_env': os.environ.get('VIRTUAL_ENV', 'Not detected')
            })

        @self.app.route('/health')
        def health():
            try:
                token_age = (datetime.now(self.ist_tz).timestamp() - self.token_timestamp) if self.token_timestamp else 0
                return jsonify({
                    'status': 'healthy',
                    'timestamp': datetime.now(self.ist_tz).strftime('%Y-%m-%d %H:%M:%S %Z'),
                    'request_token': 'present' if self.request_token else None,
                    'token_age_seconds': token_age,
                    'needs_refresh': token_age > self.token_config.get('token_timeout_seconds', 300),
                    'virtual_env': os.environ.get('VIRTUAL_ENV', 'Not detected')
                })
            except Exception as e:
                logger.error(f"Health check error: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/postback', methods=['GET', 'POST'])
        def postback():
            try:
                # Log the request details
                logger.info(f"Postback received: {request.method}")
                logger.info(f"Args: {dict(request.args)}")
                logger.info(f"Form: {dict(request.form)}")
                logger.info(f"Headers: {dict(request.headers)}")
                
                # Extract parameters
                request_token = request.form.get('request_token') or request.args.get('request_token')
                status = request.form.get('status') or request.args.get('status')
                action = request.form.get('action') or request.args.get('action')
                
                # Validate parameters
                if status != 'success' or not request_token:
                    logger.error(f"Invalid postback: status={status}, token_present={bool(request_token)}")
                    return jsonify({
                        'status': 'error', 
                        'message': 'Invalid parameters',
                        'received_status': status,
                        'received_token': bool(request_token)
                    }), 400

                # Store token
                self.request_token = request_token
                self.token_timestamp = datetime.now(self.ist_tz).timestamp()
                
                # Save to files with metadata
                if self.save_token_with_metadata(request_token):
                    logger.info("Request token received and saved successfully")
                    
                    # Cleanup old tokens
                    self.cleanup_old_tokens()
                    
                    return '''
                    <html>
                        <head>
                            <title>Authentication Successful</title>
                            <meta name="viewport" content="width=device-width, initial-scale=1">
                        </head>
                        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto; margin: 0; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center;">
                            <div style="background: white; padding: 40px; border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.1); max-width: 500px; text-align: center;">
                                <div style="font-size: 48px; margin-bottom: 20px;">🎉</div>
                                <h1 style="color: #28a745; margin-bottom: 20px; font-size: 28px;">Authentication Successful!</h1>
                                <p style="font-size: 16px; margin: 15px 0; color: #333;">Your Zerodha authentication has been completed successfully.</p>
                                <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #28a745;">
                                    <strong style="color: #155724;">✅ Token Generated and Saved</strong>
                                    <br><small style="color: #666; margin-top: 5px; display: block;">The system can now proceed with trading operations</small>
                                </div>
                                <p style="font-size: 14px; color: #666; margin: 20px 0;">You can safely close this window now.</p>
                                <hr style="margin: 30px 0; border: none; border-top: 1px solid #eee;">
                                <small style="color: #999;">Sensex Trading System v2.1 | Enhanced Postback Server</small>
                            </div>
                        </body>
                    </html>
                    '''
                else:
                    return jsonify({'status': 'error', 'message': 'Failed to save token'}), 500
                    
            except Exception as e:
                logger.error(f"Postback processing error: {e}")
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
                    return jsonify({
                        'status': 'expired', 
                        'message': 'Token expired', 
                        'age_seconds': token_age,
                        'timeout_seconds': timeout
                    }), 410
                
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
                
                # Remove token files
                token_file = self.token_config['request_token_file']
                for file_path in [token_file, f"{token_file}.meta"]:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logger.info(f"Removed: {file_path}")
                
                logger.info("Token cleared successfully")
                return jsonify({'status': 'success', 'message': 'Token cleared'})
                
            except Exception as e:
                logger.error(f"Clear token error: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/status')
        def status():
            """Detailed status endpoint"""
            try:
                token_age = (datetime.now(self.ist_tz).timestamp() - self.token_timestamp) if self.token_timestamp else 0
                
                return jsonify({
                    'server_status': 'running',
                    'virtual_env': os.environ.get('VIRTUAL_ENV', 'Not detected'),
                    'python_executable': os.sys.executable,
                    'working_directory': os.getcwd(),
                    'timestamp': datetime.now(self.ist_tz).strftime('%Y-%m-%d %H:%M:%S %Z'),
                    'token': {
                        'present': bool(self.request_token),
                        'age_seconds': token_age,
                        'expired': token_age > self.token_config.get('token_timeout_seconds', 300)
                    },
                    'config': {
                        'timeout_seconds': self.token_config.get('token_timeout_seconds', 300),
                        'backup_enabled': self.token_config.get('backup_tokens', True)
                    }
                })
            except Exception as e:
                logger.error(f"Status error: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 500

    def run(self, host='0.0.0.0', port=8001):
        """Run the Flask server"""
        try:
            logger.info(f"Starting Enhanced Postback Server on {host}:{port}")
            logger.info(f"Virtual Environment: {os.environ.get('VIRTUAL_ENV', 'Not detected')}")
            logger.info(f"Python Executable: {os.sys.executable}")
            self.app.run(host=host, port=port, debug=False, threaded=True)
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            raise

if __name__ == "__main__":
    try:
        server = EnhancedPostbackServer()
        server.run()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
EOF

chmod +x postback_server.py
echo "Enhanced postback server created"

# 8. Create management utilities
echo "8. Creating management utilities..."

cat > manage_system.sh << 'EOF'
#!/bin/bash
# System management script for venv-based trading system

VENV_PATH="/home/ubuntu/main_trading/venv"
PROJECT_PATH="/home/ubuntu/main_trading"

case "$1" in
    start)
        echo "Starting trading system services..."
        sudo systemctl start postback_server
        sleep 2
        sudo systemctl start trading_system
        echo "Services started"
        ;;
    stop)
        echo "Stopping trading system services..."
        sudo systemctl stop trading_system
        sudo systemctl stop postback_server
        echo "Services stopped"
        ;;
    restart)
        echo "Restarting trading system services..."
        sudo systemctl restart postback_server
        sleep 2
        sudo systemctl restart trading_system
        echo "Services restarted"
        ;;
    status)
        echo "=== SERVICE STATUS ==="
        sudo systemctl status postback_server --no-pager -l
        echo
        sudo systemctl status trading_system --no-pager -l
        echo
        echo "=== PROCESS STATUS ==="
        ps aux | grep -E "(postback|main.py)" | grep -v grep || echo "No trading processes found"
        ;;
    logs)
        echo "=== RECENT LOGS ==="
        echo "Postback Server:"
        sudo journalctl -u postback_server --no-pager -n 10
        echo
        echo "Trading System:"
        sudo journalctl -u trading_system --no-pager -n 10
        ;;
    test-postback)
        echo "=== TESTING POSTBACK SERVER ==="
        
        echo "1. Testing local HTTP endpoint:"
        if curl -s --max-time 5 http://localhost:8001/health; then
            echo -e "\n✅ Local HTTP: SUCCESS"
        else
            echo -e "\n❌ Local HTTP: FAILED"
        fi
        
        echo -e "\n2. Testing HTTPS endpoint:"
        if curl -s --max-time 5 https://sensexbot.ddns.net/health; then
            echo -e "\n✅ HTTPS: SUCCESS" 
        else
            echo -e "\n❌ HTTPS: FAILED"
        fi
        
        echo -e "\n3. Testing status endpoint:"
        curl -s --max-time 5 http://localhost:8001/status | head -10
        ;;
    set-mode)
        if [ -z "$2" ]; then
            echo "Usage: $0 set-mode [DEBUG|TEST|LIVE|DISABLED]"
            echo "Current mode: $(cat $PROJECT_PATH/.trading_mode 2>/dev/null || echo 'NOT SET')"
            exit 1
        fi
        echo "$2" > "$PROJECT_PATH/.trading_mode"
        echo "Trading mode set to: $2"
        if [ "$2" != "DISABLED" ]; then
            echo "Restarting trading system to apply new mode..."
            sudo systemctl restart trading_system
        else
            echo "Trading system disabled"
        fi
        ;;
    venv-test)
        echo "=== VIRTUAL ENVIRONMENT TEST ==="
        source "$VENV_PATH/bin/activate"
        echo "Virtual env: $VIRTUAL_ENV"
        echo "Python: $(which python3)"
        echo "Testing imports:"
        python3 -c "
import sys
print(f'Python version: {sys.version}')
try:
    import flask, requests, kiteconnect, pytz
    print('✅ All required packages available')
except ImportError as e:
    print(f'❌ Missing package: {e}')
"
        ;;
    manual-start)
        echo "Starting postback server manually for testing..."
        cd "$PROJECT_PATH"
        source "$VENV_PATH/bin/activate"
        echo "Virtual env activated: $VIRTUAL_ENV"
        echo "Starting postback server..."
        python3 postback_server.py
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|test-postback|set-mode|venv-test|manual-start}"
        echo
        echo "Commands:"
        echo "  start         - Start all services"  
        echo "  stop          - Stop all services"
        echo "  restart       - Restart all services"
        echo "  status        - Show service status"
        echo "  logs          - Show recent logs"
        echo "  test-postback - Test postback endpoints"
        echo "  set-mode MODE - Set trading mode (DEBUG|TEST|LIVE|DISABLED)"
        echo "  venv-test     - Test virtual environment"
        echo "  manual-start  - Start postback server manually"
        exit 1
        ;;
esac
EOF

chmod +x manage_system.sh
echo "Management script created"

# 9. Set initial configuration
echo "9. Setting initial configuration..."
echo "TEST" > .trading_mode
echo "Initial trading mode set to TEST"

# 10. Start the postback server
echo "10. Starting postback server..."
sudo systemctl start postback_server
sleep 3

# Check if it started successfully
if sudo systemctl is-active --quiet postback_server; then
    echo "✅ Postback server started successfully"
else
    echo "❌ Postback server failed to start - checking logs..."
    sudo journalctl -u postback_server --no-pager -n 5
fi

# 11. Final system test
echo "11. Running final system tests..."

echo "Testing postback server endpoints..."
if curl -s --max-time 5 http://localhost:8001/health > /dev/null; then
    echo "✅ Local endpoint responding"
else
    echo "❌ Local endpoint not responding"
fi

if curl -s --max-time 5 https://sensexbot.ddns.net/health > /dev/null; then
    echo "✅ HTTPS endpoint responding"  
else
    echo "❌ HTTPS endpoint not responding"
fi

echo
echo "SYSTEM SETUP COMPLETE"
echo "====================="
echo
echo "Virtual Environment: $VIRTUAL_ENV"
echo "Postback URL: https://sensexbot.ddns.net/postback"
echo "Management Script: ./manage_system.sh"
echo
echo "Next Steps:"
echo "1. Test the system:"
echo "   ./manage_system.sh test-postback"
echo
echo "2. Generate authentication token:"
echo "   python3 debug_token_generator.py"
echo
echo "3. Start trading system:"
echo "   ./manage_system.sh set-mode TEST"
echo
echo "4. Monitor system:"
echo "   ./manage_system.sh status"
echo "   ./manage_system.sh logs"
echo
echo "If you encounter issues:"
echo "- Check virtual environment: ./manage_system.sh venv-test"
echo "- Start manually for debugging: ./manage_system.sh manual-start"
echo "- View detailed logs: ./manage_system.sh logs"
