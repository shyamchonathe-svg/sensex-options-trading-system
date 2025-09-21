#!/bin/bash
# LIVE Mode - REAL MONEY TRADING ⚠️
cd ~/main_trading || exit 1

echo "🔴🔴🔴 LIVE MODE - REAL TRADING ⚠️🔴🔴🔴"
echo "⚠️  This executes ACTUAL orders with real money!"
echo ""

# Safety confirmation
echo "SAFETY CHECK #1 - Type 'LIVE-YES-I-UNDERSTAND' to continue:"
read -r confirm1
if [[ "$confirm1" != "LIVE-YES-I-UNDERSTAND" ]]; then
    echo "❌ LIVE trading cancelled"
    exit 1
fi

echo "SAFETY CHECK #2 - Type 'PROCEED-ANYWAY' to proceed:"
read -r confirm2
if [[ "$confirm2" != "PROCEED-ANYWAY" ]]; then
    echo "❌ LIVE trading cancelled"
    exit 1
fi

# Cleanup
pkill -f "integrated_e2e_trading_system.py" 2>/dev/null || true
sleep 3

# Environment
export MODE=LIVE
export HOST=0.0.0.0
export PORT=443
export HTTPS=True
export LOG_LEVEL=WARNING
export TELEGRAM_UPDATES=True

# Pre-flight check
echo "🔍 Running LIVE safety checks..."
if command -v python3 >/dev/null 2>&1; then
    python3 -c "
from secure_config_manager import config
print('✅ Config loaded')
print(f'📊 Max trades: {config.MAX_TRADES_PER_DAY}')
print(f'💰 Loss cap: ₹{config.DAILY_LOSS_CAP:,}')
" || { echo "❌ Config check failed"; exit 1; }
fi

# Start
mkdir -p logs
echo ""
echo "🚀🚀🚀 LIVE TRADING ACTIVATED 🚀🚀🚀"
echo "📱 Expect: '🔴 LIVE ORDER: BUY 125 SENSEX... (Order ID: AO1234)'"
echo "🛑 EMERGENCY: ./stop_live.sh"
python3 integrated_e2e_trading_system.py

echo "✅ LIVE mode stopped"
