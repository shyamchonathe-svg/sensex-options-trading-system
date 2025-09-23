#!/usr/bin/env python3
"""
Test script to verify security cleanup worked
"""

import os
import subprocess
import sys

def test_security_cleanup():
    print("🔍 TESTING SECURITY CLEANUP...")
    
    # Test 1: .env file exists and is secure
    if not os.path.exists('.env'):
        print("❌ .env file missing!")
        return False
    
    permissions = oct(os.stat('.env').st_mode)[-3:]
    if permissions != '600':
        print(f"⚠️  .env permissions incorrect: {permissions} (should be 600)")
    else:
        print("✅ .env file secure (600 permissions)")
    
    # Test 2: No hardcoded credentials remain
    credentials = [
        "xpft4r4qmsoq0p9b",
        "6c96tog8pgp8wiqti9ox7b7nx4hej8g9",
        "8427480734:AAFjkFwNbM9iUo0wa1Biwg8UHmJCvLs5vho",
        "1639045622"
    ]
    
    for cred in credentials:
        result = subprocess.run(['grep', '-r', cred, '.'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(f"❌ HARDCODED CREDENTIAL FOUND: {cred}")
            print(f"Files: {result.stdout}")
            return False
        else:
            print(f"✅ No trace of: {cred[:10]}...")
    
    # Test 3: ConfigManager loads correctly
    try:
        print("\n🔑 TESTING CONFIG LOADING...")
        from config_manager import SecureConfigManager as ConfigManager
        config_manager = ConfigManager()
        config = config_manager.get_config()
        
        required_keys = ['api_key', 'api_secret', 'telegram_token', 'chat_id']
        missing_keys = [key for key in required_keys if not config.get(key)]
        
        if missing_keys:
            print(f"❌ Missing config keys: {missing_keys}")
            return False
        
        print("✅ All required config keys loaded:")
        for key in required_keys:
            value_preview = config[key][:10] + "..." if config[key] else "EMPTY"
            print(f"  {key}: {value_preview}")
        
        # Test sensitive config hiding
        safe_config = config_manager.get_sensitive_config()
        if any(key in safe_config for key in required_keys):
            print("❌ get_sensitive_config() exposes credentials!")
            return False
        
        print("✅ get_sensitive_config() hides credentials")
        
    except Exception as e:
        print(f"❌ Config loading failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test 4: Main system startup
    print("\n🚀 TESTING MAIN SYSTEM STARTUP...")
    try:
        from integrated_e2e_trading_system import main
        # This would require full async setup - just verify imports work
        print("✅ Main system imports successful")
    except Exception as e:
        print(f"❌ Main system import failed: {e}")
        return False
    
    print("\n🎉 SECURITY CLEANUP VERIFICATION PASSED!")
    return True

if __name__ == "__main__":
    success = test_security_cleanup()
    sys.exit(0 if success else 1)
