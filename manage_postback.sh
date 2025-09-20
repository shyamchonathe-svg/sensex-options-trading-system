#!/bin/bash

# Postback Server Management Script
# Usage: ./manage_postback.sh [start|stop|restart|status|logs|install]

SERVICE_NAME="postback-server"

case "$1" in
    start)
        echo "🚀 Starting postback server..."
        sudo systemctl start $SERVICE_NAME
        sleep 2
        sudo systemctl status $SERVICE_NAME --no-pager
        ;;
    
    stop)
        echo "🛑 Stopping postback server..."
        sudo systemctl stop $SERVICE_NAME
        sudo systemctl status $SERVICE_NAME --no-pager
        ;;
    
    restart)
        echo "🔄 Restarting postback server..."
        sudo systemctl restart $SERVICE_NAME
        sleep 2
        sudo systemctl status $SERVICE_NAME --no-pager
        ;;
    
    status)
        echo "📊 Checking postback server status..."
        sudo systemctl status $SERVICE_NAME --no-pager
        echo ""
        echo "🌐 Testing endpoints..."
        echo "HTTPS Status:"
        curl -s https://sensexbot.ddns.net/status 2>/dev/null | jq . || echo "HTTPS endpoint not responding"
        echo ""
        echo "HTTP Status:"
        curl -s http://localhost:8001/status 2>/dev/null | jq . || echo "HTTP endpoint not responding"
        ;;
    
    logs)
        echo "📋 Showing postback server logs..."
        if [ "$2" = "live" ] || [ "$2" = "follow" ] || [ "$2" = "-f" ]; then
            echo "Following live logs (Press Ctrl+C to exit)..."
            journalctl -u $SERVICE_NAME -f
        else
            journalctl -u $SERVICE_NAME --since today
        fi
        ;;
    
    install)
        echo "⚙️  Installing postback server service..."
        if [ -f "setup_systemd_service.sh" ]; then
            sudo bash setup_systemd_service.sh
        else
            echo "Error: setup_systemd_service.sh not found"
            echo "Please create the setup script first"
            exit 1
        fi
        ;;
    
    enable)
        echo "✅ Enabling postback server to start on boot..."
        sudo systemctl enable $SERVICE_NAME
        echo "Service enabled for auto-start"
        ;;
    
    disable)
        echo "❌ Disabling postback server auto-start..."
        sudo systemctl disable $SERVICE_NAME
        echo "Service disabled from auto-start"
        ;;
    
    health)
        echo "🏥 Health check..."
        echo "Service Status:"
        systemctl is-active $SERVICE_NAME
        echo ""
        echo "Service Enabled:"
        systemctl is-enabled $SERVICE_NAME
        echo ""
        echo "Last 5 log entries:"
        journalctl -u $SERVICE_NAME -n 5 --no-pager
        echo ""
        echo "Network test:"
        curl -s https://sensexbot.ddns.net/health || echo "Health endpoint failed"
        ;;
    
    config)
        echo "⚙️  Service configuration:"
        echo "Service file: /etc/systemd/system/$SERVICE_NAME.service"
        echo ""
        cat /etc/systemd/system/$SERVICE_NAME.service 2>/dev/null || echo "Service file not found"
        ;;
    
    uninstall)
        echo "🗑️  Uninstalling postback server service..."
        read -p "Are you sure? This will stop and remove the service (y/N): " -r
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            sudo systemctl stop $SERVICE_NAME 2>/dev/null || true
            sudo systemctl disable $SERVICE_NAME 2>/dev/null || true
            sudo rm -f /etc/systemd/system/$SERVICE_NAME.service
            sudo systemctl daemon-reload
            echo "Service uninstalled"
        else
            echo "Uninstall cancelled"
        fi
        ;;
    
    *)
        echo "🔧 Postback Server Management"
        echo ""
        echo "Usage: $0 [command]"
        echo ""
        echo "Commands:"
        echo "   start      - Start the postback server"
        echo "   stop       - Stop the postback server"
        echo "   restart    - Restart the postback server"
        echo "   status     - Show service status and test endpoints"
        echo "   logs       - Show recent logs (use 'logs live' for real-time)"
        echo "   install    - Install the systemd service"
        echo "   enable     - Enable auto-start on boot"
        echo "   disable    - Disable auto-start on boot"
        echo "   health     - Comprehensive health check"
        echo "   config     - Show service configuration"
        echo "   uninstall  - Remove the systemd service"
        echo ""
        echo "Examples:"
        echo "   $0 start"
        echo "   $0 logs live"
        echo "   $0 status"
        echo ""
        exit 1
        ;;
esac
