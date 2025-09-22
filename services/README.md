# Services Documentation

## Available Services
- bot_daemon.service (Telegram bot)
- trading_system.service (Trading engine)
- data_collector.service (Market data)

## Setup
sudo cp services/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bot_daemon trading_system data_collector
