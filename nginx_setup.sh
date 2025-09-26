#!/bin/bash

# Nginx Configuration Setup for Zerodha Postback Server
echo "Setting up Nginx reverse proxy for Zerodha postback server..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run with sudo"
    exit 1
fi

DOMAIN="sensexbot.ddns.net"
CONFIG_FILE="/etc/nginx/sites-available/$DOMAIN"
ENABLED_FILE="/etc/nginx/sites-enabled/$DOMAIN"

echo "1. Creating Nginx configuration for $DOMAIN..."

# Create the configuration
cat > "$CONFIG_FILE" << 'EOF'
server {
    listen 443 ssl http2;
    server_name sensexbot.ddns.net;
    
    # SSL certificates
    ssl_certificate /etc/letsencrypt/live/sensexbot.ddns.net/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sensexbot.ddns.net/privkey.pem;
    
    # SSL security settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
    
    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    
    # Proxy all requests to Flask backend
    location / {
        proxy_pass http://localhost:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Server $host;
        
        # Timeouts
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
        proxy_read_timeout 300;
        
        # Buffer settings
        proxy_buffering on;
        proxy_buffer_size 128k;
        proxy_buffers 4 256k;
        proxy_busy_buffers_size 256k;
    }
    
    # Specific location for postback (most important)
    location /postback {
        proxy_pass http://localhost:8001/postback;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Log postback requests
        access_log /var/log/nginx/postback_access.log;
        error_log /var/log/nginx/postback_error.log;
    }
    
    # Health check endpoint
    location /health {
        proxy_pass http://localhost:8001/health;
        proxy_set_header Host $host;
        access_log off;  # Don't log health checks
    }
    
    # Status endpoint
    location /status {
        proxy_pass http://localhost:8001/status;
        proxy_set_header Host $host;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name sensexbot.ddns.net;
    
    # Redirect all HTTP requests to HTTPS
    return 301 https://$server_name$request_uri;
}
EOF

echo "✓ Configuration file created: $CONFIG_FILE"

echo "2. Removing any existing enabled configuration..."
if [ -L "$ENABLED_FILE" ]; then
    rm "$ENABLED_FILE"
    echo "✓ Removed existing symlink"
fi

echo "3. Enabling the new configuration..."
ln -s "$CONFIG_FILE" "$ENABLED_FILE"
echo "✓ Configuration enabled"

echo "4. Testing Nginx configuration..."
if nginx -t; then
    echo "✓ Nginx configuration test passed"
else
    echo "✗ Nginx configuration test failed!"
    echo "Check the error above and fix the configuration"
    exit 1
fi

echo "5. Checking if backend is running..."
if curl -s http://localhost:8001/health > /dev/null; then
    echo "✓ Backend server is responding"
else
    echo "⚠ Backend server is not responding on port 8001"
    echo "Make sure your postback_server.py is running"
fi

echo "6. Reloading Nginx..."
if systemctl reload nginx; then
    echo "✓ Nginx reloaded successfully"
else
    echo "✗ Failed to reload Nginx"
    exit 1
fi

echo ""
echo "🎉 Setup complete!"
echo ""
echo "Testing endpoints..."
echo "==================="

# Test the endpoints
echo "1. Testing HTTPS health endpoint:"
curl -s https://sensexbot.ddns.net/health || echo "Failed"

echo ""
echo "2. Testing HTTPS status endpoint:"
curl -s https://sensexbot.ddns.net/status || echo "Failed"

echo ""
echo "3. Testing HTTPS root endpoint:"
curl -s https://sensexbot.ddns.net/ | head -5 || echo "Failed"

echo ""
echo "4. Testing HTTP redirect:"
curl -s -I http://sensexbot.ddns.net/ | grep -i location || echo "No redirect found"

echo ""
echo "Configuration Summary:"
echo "====================="
echo "✓ Nginx listens on port 443 (HTTPS)"
echo "✓ Flask backend runs on port 8001 (HTTP)"
echo "✓ All HTTPS requests are proxied to Flask"
echo "✓ HTTP requests redirect to HTTPS"
echo ""
echo "Your Zerodha postback URL: https://sensexbot.ddns.net/postback"
echo ""
echo "Log files:"
echo "- General: /var/log/nginx/access.log"
echo "- Postback: /var/log/nginx/postback_access.log"
echo "- Errors: /var/log/nginx/error.log"
