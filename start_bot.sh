#!/bin/bash
# Telegram Trading Bot Controller
cd ~/main_trading || exit 1

echo "🤖 Starting Telegram Trading Bot Controller"
echo "📱 Full system control via Telegram"
echo "⚙️ Current mode: $(grep '^MODE=' .env | cut -d'=' -f2 || echo "TEST")"
echo ""

# Cleanup
pkill -f telegram_trading_bot.py 2>/dev/null || true
sleep 2

# Validate config
if ! grep -q '^TELEGRAM_TOKEN=' .env; then
    echo "❌ TELEGRAM_TOKEN missing in .env"
    echo "💡 Run: nano .env  # Add your bot token"
    exit 1
fi

if ! grep -q '^TELEGRAM_CHAT_ID=' .env; then
    echo "❌ TELEGRAM_CHAT_ID missing in .env"
    echo "💡 Get it: curl https://api.telegram.org/bot\$(grep TELEGRAM_TOKEN .env | cut -d'=' -f2)/getUpdates"
    exit 1
fi

# Start
mkdir -p logs
echo "🚀 Bot starting..."
echo "📱 Send /start to your bot"
echo "📊 Logs: tail -f logs/telegram_bot.log"
echo "🛑 Stop: Ctrl+C or ./stop_bot.sh"
echo ""

python3 telegram_trading_bot.py

echo "✅ Bot stopped"
