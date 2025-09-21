#!/bin/bash
# One-click Trading Bot Setup
set -e  # Exit on any error

cd ~/main_trading || { echo "❌ Not in main_trading directory"; exit 1; }

echo "🚀 Setting up Sensex Trading Bot..."
echo "📅 $(date)"
echo "🐍 Python: $(python3 --version)"
echo ""

# 1. Create directories
echo "📁 Creating directories..."
mkdir -p logs data_raw/{2024/09,2025/01} test_results auth_data temp_scripts

# 2. Fix .env
echo "⚙️  Configuring .env..."
if [[ ! -f .env ]]; then
    cp .env.example .env
    chmod 600 .env
    echo "✅ .env created - EDIT YOUR CREDENTIALS:"
    echo "   nano .env  # Add ZAPI_KEY, TELEGRAM_TOKEN, etc."
else
    echo "✅ .env exists"
fi

# 3. Install dependencies
echo "📦 Installing Python dependencies..."
cat > requirements.txt << 'EOF'
kiteconnect==4.2.0
pandas>=2.2.0,<3.0
numpy>=2.0,<3.0
httpx==0.25.2
httpcore==1.0.0
python-telegram-bot==20.7
python-dotenv==1.0.0
tenacity==8.2.3
python-dateutil==2.8.2
pytz==2023.3
plotly==5.17.0
aiosqlite==0.19.0
pytest==7.4.2
black==23.7.0
EOF

pip install -r requirements.txt --upgrade

# 4. Initialize database
echo "💾 Initializing trade database..."
python3 -c "
import asyncio
from risk_manager import RiskManager
async def init_db():
    rm = RiskManager({})
    await rm._init_db()
    print('✅ Database initialized')
asyncio.run(init_db())
"

# 5. Make scripts executable
echo "🔧 Setting up startup scripts..."
chmod +x start_*.sh stop_*.sh 2>/dev/null || true

# 6. Create missing startup scripts
if [[ ! -f start_test.sh ]]; then
    echo "📝 Creating start_test.sh..."
    cat > start_test.sh << 'EOF'
#!/bin/bash
cd ~/main_trading
echo "🧪 Starting TEST Mode - Mock Trading"
export MODE=TEST HOST=127.0.0.1 PORT=8080 HTTPS=False LOG_LEVEL=DEBUG
mkdir -p logs
nohup python3 integrated_e2e_trading_system.py > logs/trading_test.log 2>&1 &
echo "✅ TEST mode started (check logs/trading_test.log)"
EOF
    chmod +x start_test.sh
fi

if [[ ! -f start_paper.sh ]]; then
    echo "📝 Creating start_paper.sh..."
    cat > start_paper.sh << 'EOF'
#!/bin/bash
cd ~/main_trading
echo "📝 Starting PAPER Mode - Simulated Trading"
export MODE=PAPER HOST=0.0.0.0 PORT=8080 HTTPS=False LOG_LEVEL=INFO
mkdir -p logs
nohup python3 integrated_e2e_trading_system.py > logs/trading_paper.log 2>&1 &
echo "✅ PAPER mode started (check logs/trading_paper.log)"
EOF
    chmod +x start_paper.sh
fi

if [[ ! -f start_live.sh ]]; then
    echo "🔴 Creating start_live.sh..."
    cat > start_live.sh << 'EOF'
#!/bin/bash
cd ~/main_trading
echo "🔴 LIVE Mode - REAL TRADING ⚠️"
read -p "Confirm LIVE trading (type LIVE): " confirm
[[ "$confirm" != "LIVE" ]] && { echo "❌ Cancelled"; exit 1; }
export MODE=LIVE HOST=0.0.0.0 PORT=443 HTTPS=True LOG_LEVEL=WARNING
mkdir -p logs
nohup python3 integrated_e2e_trading_system.py > logs/trading_live.log 2>&1 &
echo "✅ LIVE mode started (check logs/trading_live.log)"
EOF
    chmod +x start_live.sh
fi

if [[ ! -f start_debug.sh ]]; then
    echo "🐛 Creating start_debug.sh..."
    cat > start_debug.sh << 'EOF'
#!/bin/bash
cd ~/main_trading
echo "🐛 Starting DEBUG Mode - Historical Analysis"
export MODE=DEBUG HOST=127.0.0.1 PORT=8081 HTTPS=False LOG_LEVEL=DEBUG
mkdir -p logs
python3 integrated_e2e_trading_system.py
EOF
    chmod +x start_debug.sh
fi

if [[ ! -f start_bot.sh ]]; then
    echo "🤖 Creating start_bot.sh..."
    cat > start_bot.sh << 'EOF'
#!/bin/bash
cd ~/main_trading
echo "🤖 Starting Telegram Trading Bot Controller"
pkill -f telegram_trading_bot.py 2>/dev/null || true
sleep 2
mkdir -p logs
python3 telegram_trading_bot.py
EOF
    chmod +x start_bot.sh
fi

if [[ ! -f stop_bot.sh ]]; then
    echo "🛑 Creating stop_bot.sh..."
    cat > stop_bot.sh << 'EOF'
#!/bin/bash
echo "🛑 Stopping Trading Bot..."
pkill -f telegram_trading_bot.py
pkill -f integrated_e2e_trading_system.py
pkill -f auth_server.py
echo "✅ All processes stopped"
EOF
    chmod +x stop_bot.sh
fi

# 7. Test configuration
echo ""
echo "✅ Setup complete!"
echo ""
echo "📋 NEXT STEPS:"
echo "1. Edit .env: nano .env"
echo "   - Add ZAPI_KEY, ZAPI_SECRET"
echo "   - Add TELEGRAM_TOKEN (from @BotFather)"
echo "   - Add TELEGRAM_CHAT_ID (from bot updates)"
echo ""
echo "2. Test bot: ./start_bot.sh"
echo "3. In Telegram: Send /start to your bot"
echo ""
echo "4. Quick test: /test → Wait for signals → /stop"
echo ""
echo "📊 Monitor: tail -f logs/telegram_bot.log"
