#!/bin/bash

echo "Creating systemd service for postback server..."

# Create the service file
sudo tee /etc/systemd/system/postback-server.service << 'EOF'
[Unit]
Description=Zerodha Postback Server
After=network.target nginx.service
Wants=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/main_trading
Environment=PATH=/home/ubuntu/main_trading/venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/home/ubuntu/main_trading/venv/bin/python /home/ubuntu/main_trading/postback_server.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=postback-server

# Security settings
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=/home/ubuntu/main_trading
ProtectHome=yes

[Install]
WantedBy=multi-user.target
EOF

echo "Service file created at /etc/systemd/system/postback-server.service"

# Reload systemd
sudo systemctl daemon-reload

echo "Systemd reloaded. Available commands:"
echo ""
echo "Start service:    sudo systemctl start postback-server"
echo "Stop service:     sudo systemctl stop postback-server"
echo "Enable at boot:   sudo systemctl enable postback-server"
echo "Check status:     sudo systemctl status postback-server"
echo "View logs:        sudo journalctl -u postback-server -f"
echo "Restart service:  sudo systemctl restart postback-server"
echo ""
echo "To set it up now:"
echo "1. sudo systemctl enable postback-server  # Start at boot"
echo "2. sudo systemctl start postback-server   # Start now"
echo "3. sudo systemctl status postback-server  # Check status"
