#!/bin/bash
echo "🛑 Stopping PAPER Mode Trading System"
cd ~/main_trading || exit 1

pkill -f "integrated_e2e_trading_system.py" 2>/dev/null || true
pkill -f "auth_server.py" 2>/dev/null || true

sleep 3
pkill -9 -f "integrated_e2e_trading_system.py" 2>/dev/null || true
pkill -9 -f "auth_server.py" 2>/dev/null || true

echo "✅ PAPER mode stopped"
echo "📊 Review logs: tail -f logs/trading_paper.log"
