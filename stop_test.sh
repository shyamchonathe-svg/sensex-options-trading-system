#!/bin/bash
echo "🛑 Stopping TEST Mode Trading System"
cd ~/main_trading || exit 1

# Kill processes
pkill -f "integrated_e2e_trading_system.py" 2>/dev/null || true
pkill -f "auth_server.py" 2>/dev/null || true

# Wait for graceful shutdown
sleep 3

# Kill any remaining processes
pkill -9 -f "integrated_e2e_trading_system.py" 2>/dev/null || true
pkill -9 -f "auth_server.py" 2>/dev/null || true

echo "✅ TEST mode stopped"
echo "📊 Review logs: tail -f logs/trading_test.log"
echo "📁 Test results: ls -la test_results/"
