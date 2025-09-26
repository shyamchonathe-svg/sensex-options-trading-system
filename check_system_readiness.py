#!/usr/bin/env python3
"""
System Readiness Checklist
Comprehensive pre-deployment validation
"""
import asyncio
import sys
from datetime import datetime
import subprocess
import os

from utils.secure_config_manager import SecureConfigManager
from modes import create_mode_config
from risk_manager import RiskManager
from notification_service import NotificationService
from integrated_e2e_trading_system import TokenValidator, LiveTradingGuard

async def check_environment():
    """Check environment and dependencies."""
    print("🔍 Checking environment...")
    
    checks = []
    
    # Python version
    python_version = sys.version_info
    if python_version.major == 3 and python_version.minor >= 8:
        checks.append("✅ Python: 3.8+ detected")
    else:
        checks.append("❌ Python: Requires 3.8+, found {}.{}.{}".format(
            python_version.major, python_version.minor, python_version.micro))
        return checks
    
    # Required directories
    required_dirs = ['logs', 'data_raw', 'test_results', 'auth_data']
    for dir_name in required_dirs:
        dir_path = os.path.join(os.getcwd(), dir_name)
        if os.path.exists(dir_path):
            checks.append(f"✅ {dir_name}: Exists")
        else:
            checks.append(f"⚠️  {dir_name}: Missing (will be created)")
    
    # .env file
    if os.path.exists('.env') and os.path.exists('.env.example'):
        if os.stat('.env').st_mode & 0o600 == 0o600:
            checks.append("✅ .env: Secure permissions (600)")
        else:
            checks.append("⚠️  .env: Insecure permissions (fix with chmod 600)")
    else:
        checks.append("❌ .env: Missing (copy .env.example and configure)")
    
    # Dependencies
    try:
        import kiteconnect
        import pandas
        import numpy
        import httpx
        checks.append("✅ Dependencies: kiteconnect, pandas, numpy, httpx")
    except ImportError as e:
        checks.append(f"❌ Dependencies: Missing {e.name} (pip install -r requirements.txt)")
    
    print("\n".join(checks))
    return all("✅" in check or "⚠️" in check for check in checks)

async def check_configuration():
    """Check configuration validity."""
    print("\n🔍 Checking configuration...")
    
    config_dict = config.get_config()
    mode_config = create_mode_config(config_dict)
    
    checks = []
    
    # Required config values
    required = ['ZAPI_KEY', 'ZAPI_SECRET', 'TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID']
    missing = [key for key in required if not config.get_raw_value(key)]
    
    if missing:
        checks.append(f"❌ Config: Missing {', '.join(missing)}")
    else:
        checks.append("✅ Config: All required values present")
    
    # Mode validation
    if mode_config.mode == "LIVE":
        min_balance = config_dict.get("MIN_BALANCE", 50000)
        checks.append(f"⚠️  LIVE Mode: Min balance ₹{min_balance:,} required")
    
    # Risk parameters
    max_trades = config_dict.get("MAX_TRADES_PER_DAY", 3)
    loss_cap = config_dict.get("DAILY_LOSS_CAP", 25000)
    if max_trades > 0 and loss_cap > 0:
        checks.append(f"✅ Risk: {max_trades} trades/day, ₹{loss_cap:,} loss cap")
    else:
        checks.append("❌ Risk: Invalid parameters")
    
    # Telegram
    if config_dict.get("ENABLE_NOTIFICATIONS", True):
        if config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID:
            checks.append("✅ Telegram: Configured")
        else:
            checks.append("⚠️  Telegram: Disabled or incomplete config")
    else:
        checks.append("⚠️  Telegram: Notifications disabled")
    
    print("\n".join(checks))
    return len([c for c in checks if "❌" in c]) == 0

async def check_kite_connectivity():
    """Check KiteConnect API connectivity."""
    print("\n🔍 Checking KiteConnect connectivity...")
    
    token_validator = TokenValidator(config.get_config(), NotificationService(config.get_config()))
    
    if await token_validator.initialize_kite():
        try:
            profile = token_validator.kite.profile()
            checks = [f"✅ KiteConnect: Connected ({profile.get('user_id', 'unknown')})"]
            
            # Test market data
            quote = token_validator.kite.quote("NSE:NIFTY 50")
            ltp = float(quote[0]['ohlc']['close'])
            checks.append(f"✅ Market Data: NIFTY {ltp:,.0f}")
            
            # Test margins
            margins = token_validator.kite.margins()
            cash = margins['equity']['available']['cash']
            checks.append(f"✅ Margins: ₹{cash:,.0f} available")
            
        except Exception as e:
            checks = [f"❌ KiteConnect: API error - {str(e)[:100]}"]
    else:
        checks = ["❌ KiteConnect: Initialization failed (check ACCESS_TOKEN)"]
    
    print("\n".join(checks))
    return "✅" in checks[0]

async def check_risk_database():
    """Check risk management database."""
    print("\n🔍 Checking risk database...")
    
    risk_manager = RiskManager(config.get_config())
    summary = await risk_manager.get_daily_summary()
    
    checks = [
        f"✅ Database: Initialized",
        f"📊 Today: {summary['trades_today']} trades, ₹{summary['daily_pnl']:,.0f} P&L",
        f"📈 Win Rate: {summary['win_rate']:.1f}%",
        f"🛡️ Trading: {'Allowed' if summary['trading_allowed'] else 'Blocked'}"
    ]
    
    print("\n".join(checks))
    return True

async def check_systemd_services():
    """Check systemd service configuration."""
    print("\n🔍 Checking systemd services...")
    
    checks = []
    
    # Check if services exist
    service_files = [
        "/etc/systemd/system/trading-system@.service",
        "/etc/systemd/system/trading-auth@.service"
    ]
    
    for service_file in service_files:
        if os.path.exists(service_file):
            checks.append(f"✅ {os.path.basename(service_file)}: Configured")
        else:
            checks.append(f"⚠️  {os.path.basename(service_file)}: Missing")
    
    # Check current service status if running as root or with sudo
    try:
        if os.geteuid() == 0 or os.getenv("SUDO_USER"):
            result = subprocess.run(
                ["systemctl", "is-active", "trading-system@TEST.service"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                checks.append("✅ trading-system@TEST: Active")
            else:
                checks.append("⚠️  trading-system@TEST: Not running")
    except:
        checks.append("⚠️  Systemd: Check manually with systemctl")
    
    print("\n".join(checks))
    return all("✅" in check or "⚠️" in check for check in checks)

async def main():
    """Run complete system readiness check."""
    print(f"🔍 SYSTEM READINESS CHECK - {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("=" * 70)
    
    all_passed = True
    
    # Run all checks
    env_ok = await check_environment()
    config_ok = await check_configuration()
    kite_ok = await check_kite_connectivity()
    risk_ok = await check_risk_database()
    systemd_ok = await check_systemd_services()
    
    all_passed = env_ok and config_ok and kite_ok and risk_ok and systemd_ok
    
    # Summary
    print("\n" + "=" * 70)
    print("📋 READINESS SUMMARY")
    print("=" * 70)
    
    status_checks = [
        ("Environment", env_ok),
        ("Configuration", config_ok), 
        ("KiteConnect", kite_ok),
        ("Risk DB", risk_ok),
        ("Systemd", systemd_ok)
    ]
    
    for check_name, check_status in status_checks:
        status_emoji = "✅" if check_status else "❌"
        print(f"{status_emoji} {check_name}")
    
    final_status = "🚀 SYSTEM READY FOR DEPLOYMENT" if all_passed else "🛑 SYSTEM REQUIRES ATTENTION"
    print(f"\n{final_status}")
    
    # Exit code for automation
    sys.exit(0 if all_passed else 1)

if __name__ == "__main__":
    asyncio.run(main())
