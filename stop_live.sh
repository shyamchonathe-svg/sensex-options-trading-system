#!/bin/bash
echo "🚨 EMERGENCY STOP - LIVE Mode Trading System"
echo "⚠️  This will immediately halt ALL real trading"
cd ~/main_trading || exit 1

echo "🛑 Sending shutdown signals..."
pkill -f "integrated_e2e_trading_system.py" 2>/dev/null || true
pkill -f "auth_server.py" 2>/dev/null || true

echo "⏳ Waiting for graceful shutdown..."
sleep 5

echo "💥 Force killing remaining processes..."
pkill -9 -f "integrated_e2e_trading_system.py" 2>/dev/null || true
pkill -9 -f "auth_server.py" 2>/dev/null || true

echo ""
echo "✅ LIVE trading EMERGENCY STOP complete"
echo "⚠️  Review all open positions immediately"
echo "📊 Emergency logs: tail -f logs/trading_live.log"
echo "🔍 Check Kite dashboard for any open orders"
