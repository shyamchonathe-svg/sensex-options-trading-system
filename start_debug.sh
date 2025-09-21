#!/bin/bash
# DEBUG Mode - Historical Strategy Analysis
cd ~/main_trading || exit 1

echo "🐛 Starting DEBUG Mode - Strategy Replay"
echo "🔍 Analyze historical signals (no trading)"
echo "📱 Use: /debug YYYY-MM-DD HH:MM in Telegram"
echo ""

# Cleanup
pkill -f "integrated_e2e_trading_system.py" 2>/dev/null || true
sleep 2

# Environment
export MODE=DEBUG
export HOST=127.0.0.1
export PORT=8081
export HTTPS=False
export LOG_LEVEL=DEBUG
export TELEGRAM_UPDATES=True

# Start
mkdir -p logs
echo "🚀 Starting DEBUG engine..."
echo "💡 Test: /debug 2024-09-20 10:30"
python3 integrated_e2e_trading_system.py

echo "✅ DEBUG mode stopped"
