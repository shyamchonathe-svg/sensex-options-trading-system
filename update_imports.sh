#!/bin/bash
FILES=(
    "integrated_e2e_trading_system.py"
    "broker_adapter.py"
    "data_manager.py"
    "trading_service.py"
    "bot_controller.py"
    "health_monitor.py"
    "sensex_trading_bot_live.py"
    "sensex_trading_bot_debug.py"
    "fetch_sensex_options_data.py"
    "sensex_instrument.py"
)

for file in "${FILES[@]}"; do
    if [[ -f "$file" ]]; then
        echo "Updating $file..."
        sed -i 's|from config_manager import ConfigManager|from config_manager import SecureConfigManager as ConfigManager|g' "$file"
        echo "✅ $file updated"
    else
        echo "⚠️  $file not found - skipping"
    fi
done

echo "🎉 All imports updated!"
