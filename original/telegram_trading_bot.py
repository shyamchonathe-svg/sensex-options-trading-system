#!/usr/bin/env python3
"""
Telegram Trading Bot Controller - Full System Control
Commands: /test /paper /live /debug /stop /status /positions /trades /analytics
"""
import asyncio
import logging
import subprocess
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional
import pandas as pd
import random
import os
import sys

# Telegram imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from .ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from .constants import ParseMode

# Local imports
from secure_config_manager import config
from modes import TradingMode, create_mode_config
from risk_manager import RiskManager
from notification_service import NotificationService
from kiteconnect import KiteConnect
import aiosqlite

# Setup logging
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'telegram_bot.log', mode='a'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class TradingBot:
    """Complete trading system controller via Telegram."""
    
    def __init__(self):
        self.config = config.get_config()
        self.telegram_token = self.config.get("TELEGRAM_TOKEN", "")
        self.chat_id = self.config.get("TELEGRAM_CHAT_ID", "")
        
        if not self.telegram_token or not self.chat_id:
            raise ValueError("❌ TELEGRAM_TOKEN and TELEGRAM_CHAT_ID required in .env")
        
        self.mode_config
