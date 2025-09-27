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
