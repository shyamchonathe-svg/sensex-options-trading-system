#!/bin/bash
# TEST Mode - Mock Trading with Telegram Alerts
cd ~/main_trading || exit 1

echo "🧪 Starting TEST Mode Trading System"
echo "📱 Mock signals via Telegram - NO real orders"
echo "🌐 Internal: 127.0.0.1:8080"
echo ""

# Cleanup
pkill -f "integrated_e2e_trading_system.py" 2>/dev/null || true
sleep 2

# Environment
export MODE=TEST
export HOST=127.0.0.1
export PORT=8080
export HTTPS=False
export LOG_LEVEL=DEBUG
export TELEGRAM_UPDATES=True

# Start
mkdir -p logs
echo "🚀 Starting TEST engine..."
echo "📱 Expect: '🧪 TEST MODE - Would BUY 125 SENSEX...'"
python3 integrated_e2e_trading_system.py

echo "✅ TEST mode stopped"
