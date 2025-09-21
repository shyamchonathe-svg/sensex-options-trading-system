#!/bin/bash
# PAPER Mode - Simulated Trading with Slippage
cd ~/main_trading || exit 1

echo "📝 Starting PAPER Mode Trading System"
echo "📊 Simulated fills with realistic slippage"
echo "🌐 External: 0.0.0.0:8080"
echo ""

# Cleanup
pkill -f "integrated_e2e_trading_system.py" 2>/dev/null || true
sleep 2

# Environment
export MODE=PAPER
export HOST=0.0.0.0
export PORT=8080
export HTTPS=False
export LOG_LEVEL=INFO
export TELEGRAM_UPDATES=True

# Start
mkdir -p logs
echo "🚀 Starting PAPER engine..."
echo "📱 Expect: '📝 PAPER ORDER: BUY 100 SENSEX... (+0.87% slippage)'"
python3 integrated_e2e_trading_system.py

echo "✅ PAPER mode stopped"
