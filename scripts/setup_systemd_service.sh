#!/bin/bash

# Setup script for Postback Server systemd service
# Run as: sudo bash setup_systemd_service.sh

set -e

echo "Setting up Postback Server as systemd service..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash $0"
    exit 1
fi

# Define paths
SERVICE_FILE="/etc/systemd/system/postback-server.service"
WORKING_DIR="/home/ubuntu/main_trading"
SCRIPT_PATH="$WORKING_DIR/postback_server.py"

# Check if the Python script exists
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "Error: postback_server.py not found at $SCRIPT_PATH"
    exit 1
fi

# Create the service file
echo "Creating systemd service file..."
cat > "$SERVICE_FILE" << 'EOF'
[Unit]
Description=Zerodha Postback HTTPS Server
After=network.target
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/main_trading
Environment=PATH=/usr/bin:/usr/local/bin:/home/ubuntu/.local/bin
ExecStart=/usr/bin/python3 /home/ubuntu/main_trading/postback_server.py
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
ReadOnlyPaths=/etc/letsencrypt

# Network settings
BindPaths=/etc/letsencrypt/live/sensexbot.ddns.net

# Process limits
TimeoutStartSec=30
TimeoutStopSec=30
KillMode=mixed

[Install]
WantedBy=multi-user.target
EOF

# Set proper permissions for SSL certificates (needed for port 443)
echo "Setting up SSL certificate permissions..."
if [ -d "/etc/letsencrypt/live/sensexbot.ddns.net" ]; then
    # Create ssl-cert group if it doesn't exist
    groupadd -f ssl-cert
    
    # Add ubuntu user to ssl-cert group
    usermod -a -G ssl-cert ubuntu
    
    # Set proper permissions
    chgrp -R ssl-cert /etc/letsencrypt/live/sensexbot.ddns.net
    chgrp -R ssl-cert /etc/letsencrypt/archive/sensexbot.ddns.net
    chmod -R 640 /etc/letsencrypt/live/sensexbot.ddns.net/privkey.pem
    chmod -R 640 /etc/letsencrypt/archive/sensexbot.ddns.net/privkey*.pem
    
    echo "SSL permissions configured"
else
    echo "Warning: SSL certificates not found at /etc/letsencrypt/live/sensexbot.ddns.net"
    echo "Please run: sudo certbot certonly --standalone --domains sensexbot.ddns.net"
fi

# Allow binding to privileged ports (443)
echo "Setting up capabilities for port 443..."

# Find the actual Python3 binary (resolve symlinks)
PYTHON3_REAL=$(readlink -f /usr/bin/python3)
echo "Real Python3 binary: $PYTHON3_REAL"

# Set capabilities on the real binary
if [ -f "$PYTHON3_REAL" ]; then
    setcap 'cap_net_bind_service=+ep' "$PYTHON3_REAL"
    echo "Capabilities set on $PYTHON3_REAL"
else
    echo "Warning: Could not find real Python3 binary"
    echo "You may need to run the server with sudo or use authbind"
fi

# Make the Python script executable
chmod +x "$SCRIPT_PATH"

# Set proper ownership
chown ubuntu:ubuntu "$WORKING_DIR" -R

# Reload systemd and enable the service
echo "Configuring systemd service..."
systemctl daemon-reload
systemctl enable postback-server.service

echo ""
echo "✅ Systemd service setup complete!"
echo ""
echo "📋 Available commands:"
echo "   sudo systemctl start postback-server    # Start the service"
echo "   sudo systemctl stop postback-server     # Stop the service"
echo "   sudo systemctl restart postback-server  # Restart the service"
echo "   sudo systemctl status postback-server   # Check status"
echo "   journalctl -u postback-server -f        # View live logs"
echo "   journalctl -u postback-server --since today  # View today's logs"
echo ""
echo "🚀 To start the service now:"
echo "   sudo systemctl start postback-server"
echo ""
echo "📊 To check if it's running:"
echo "   sudo systemctl status postback-server"
echo "   curl https://sensexbot.ddns.net/status"
echo ""
