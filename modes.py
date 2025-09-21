#!/usr/bin/env python3
"""
Trading Mode Configuration System
Defines modes and their specific configurations
"""
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Any
from datetime import datetime

class TradingMode(Enum):
    """Trading modes with distinct behaviors."""
    TEST = "TEST"
    PAPER = "PAPER"
    LIVE = "LIVE"
    DEBUG = "DEBUG"

@dataclass
class ModeConfig:
    """Configuration specific to each trading mode."""
    mode: TradingMode
    host: str
    port: int
    https: bool
    max_trades: int
    risk_per_trade: float
    enable_notifications: bool
    log_level: str
    kite_mode: str  # "mock", "paper", "live"
    allow_real_orders: bool
    slippage_model: str  # "none", "simple", "advanced"
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'ModeConfig':
        """Create ModeConfig from dictionary."""
        mode_map = {
            "TEST": TradingMode.TEST,
            "PAPER": TradingMode.PAPER,
            "LIVE": TradingMode.LIVE,
            "DEBUG": TradingMode.DEBUG
        }
        
        mode_str = config_dict.get("MODE", "TEST").upper()
        mode = mode_map.get(mode_str, TradingMode.TEST)
        
        # Mode-specific defaults
        mode_defaults = {
            TradingMode.TEST: {
                "host": "127.0.0.1",
                "port": 8080,
                "https": False,
                "max_trades": 5,
                "risk_per_trade": 0.005,
                "enable_notifications": True,
                "log_level": "DEBUG",
                "kite_mode": "mock",
                "allow_real_orders": False,
                "slippage_model": "none"
            },
            TradingMode.PAPER: {
                "host": "0.0.0.0",
                "port": 8080,
                "https": False,
                "max_trades": 3,
                "risk_per_trade": 0.01,
                "enable_notifications": True,
                "log_level": "INFO",
                "kite_mode": "paper",
                "allow_real_orders": False,
                "slippage_model": "simple"
            },
            TradingMode.LIVE: {
                "host": "0.0.0.0",
                "port": 443,
                "https": True,
                "max_trades": 2,
                "risk_per_trade": 0.015,
                "enable_notifications": True,
                "log_level": "WARNING",
                "kite_mode": "live",
                "allow_real_orders": True,
                "slippage_model": "advanced"
            },
            TradingMode.DEBUG: {
                "host": "127.0.0.1",
                "port": 8081,
                "https": False,
                "max_trades": 10,
                "risk_per_trade": 0.002,
                "enable_notifications": True,
                "log_level": "DEBUG",
                "kite_mode": "mock",
                "allow_real_orders": False,
                "slippage_model": "none"
            }
        }
        
        defaults = mode_defaults[mode]
        merged_config = {**defaults, **config_dict}
        
        return cls(
            mode=mode,
            host=merged_config.get("HOST", defaults["host"]),
            port=int(merged_config.get("PORT", defaults["port"])),
            https=merged_config.get("HTTPS", defaults["https"]),
            max_trades=int(merged_config.get("MAX_TRADES_PER_DAY", defaults["max_trades"])),
            risk_per_trade=float(merged_config.get("RISK_PER_TRADE", defaults["risk_per_trade"])),
            enable_notifications=merged_config.get("ENABLE_NOTIFICATIONS", defaults["enable_notifications"]),
            log_level=merged_config.get("LOG_LEVEL", defaults["log_level"]),
            kite_mode=merged_config.get("KITE_MODE", defaults["kite_mode"]),
            allow_real_orders=merged_config.get("ALLOW_REAL_ORDERS", defaults["allow_real_orders"]),
            slippage_model=merged_config.get("SLIPPAGE_MODEL", defaults["slippage_model"])
        )
    
    def get_mode_emoji(self) -> str:
        """Get emoji for current mode."""
        return {
            TradingMode.TEST: "🧪",
            TradingMode.PAPER: "📝",
            TradingMode.LIVE: "🔴",
            TradingMode.DEBUG: "🐛"
        }[self.mode]
    
    def get_mode_description(self) -> str:
        """Get human-readable mode description."""
        return {
            TradingMode.TEST: "TEST MODE - Mock trading with Telegram alerts (no real orders)",
            TradingMode.PAPER: "PAPER MODE - Simulated execution with realistic slippage",
            TradingMode.LIVE: "LIVE MODE - REAL MONEY TRADING (all safety checks active)",
            TradingMode.DEBUG: "DEBUG MODE - Verbose logging with mock execution"
        }[self.mode]

def create_mode_config(config_dict: Dict[str, Any]) -> ModeConfig:
    """Factory function for mode configuration."""
    return ModeConfig.from_dict(config_dict)
