#!/bin/bash
echo "🛑 Stopping Trading Bot & All Modes"
cd ~/main_trading || exit 1

echo "Killing bot..."
pkill -f telegram_trading_bot.py 2>/dev/null || true

echo "Emergency stop - all trading modes..."
pkill -f integrated_e2e_trading_system.py 2>/dev/null || true
pkill -f auth_server.py 2>/dev/null || true

sleep 2

echo "Force kill remaining..."
pkill -9 -f telegram_trading_bot.py 2>/dev/null || true
pkill -9 -f integrated_e2e_trading_system.py 2>/dev/null || true
pkill -9 -f auth_server.py 2>/dev/null || true

echo "✅ All processes stopped"
echo "📊 Final logs: tail -20 logs/telegram_bot.log"
