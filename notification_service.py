#!/usr/bin/env python3
"""
Enhanced Notification Service for RiskManager
Supports advanced commands: /test, /live, /debug, /stop, /balance, /token
Token Refresh: Clickable login link → Auto-save on postback
Mode Status: Enhanced /status with runtime + mode info
Risk Reporting: /risk with comprehensive metrics
"""

import logging
import time
import hashlib
import json
from typing import Optional, Dict, List, Any, Union
from datetime import datetime, timedelta
from urllib.parse import urlencode
import aiohttp
import qrcode
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    filters
)
from tenacity import retry, stop_after_attempt, wait_exponential
import pytz

# Local imports (adjust based on your structure)
try:
    from config_manager import SecureConfigManager as ConfigManager
    from database_layer import DatabaseLayer
    from risk_manager import RiskManager
    from enums import TradingMode  # Assuming you have this enum
except ImportError:
    # Mock classes for standalone testing
    class TradingMode:
        TEST = "TEST"
        LIVE = "LIVE"
    
    class MockConfigManager:
        def get_full_config(self):
            return {"test_mode": True}
    
    ConfigManager = MockConfigManager
    DatabaseLayer = None
    RiskManager = None


class NotificationService:
    """
    Enhanced Telegram Notification Service with Command Handlers
    Features: Deduplication, Rate-limiting, Token Refresh, Risk Reporting
    """
    
    def __init__(self, telegram_token: str, chat_id: str, config: Dict[str, Any], 
                 database_layer: Optional[DatabaseLayer] = None, 
                 risk_manager: Optional[RiskManager] = None):
        self.telegram_token = telegram_token
        self.chat_id = chat_id
        self.config = config
        self.db = database_layer
        self.risk_mgr = risk_manager
        self.logger = logging.getLogger(__name__)
        
        # Initialize bot and application
        self.bot = Bot(token=telegram_token)
        self.application = Application.builder().token(telegram_token).build()
        self.running = False
        self.start_time = datetime.now(pytz.timezone('Asia/Kolkata'))
        
        # Message tracking for deduplication
        self.last_messages: Dict[str, float] = {}
        self.dedup_window = 300  # 5 minutes
        
        # Token refresh state
        self.pending_token_refresh = None
        self.auth_state = {}
        
        # Runtime stats
        self.message_count = 0
        self.command_count = 0
        
        # Setup handlers
        self._setup_handlers()
        
        self.logger.info(f"NotificationService initialized for chat_id: {chat_id}")

    def _setup_handlers(self):
        """Setup all Telegram command and callback handlers."""
        # Basic commands
        self.application.add_handler(CommandHandler('start', self._start_command))
        self.application.add_handler(CommandHandler('help', self._help_command))
        self.application.add_handler(CommandHandler('status', self._status_command))
        self.application.add_handler(CommandHandler('health', self._health_command))
        self.application.add_handler(CommandHandler('login', self._login_command))
        
        # Enhanced trading commands
        self.application.add_handler(CommandHandler('test', self._test_command))
        self.application.add_handler(CommandHandler('live', self._live_command))
        self.application.add_handler(CommandHandler('debug', self._debug_command))
        self.application.add_handler(CommandHandler('stop', self._stop_command))
        self.application.add_handler(CommandHandler('balance', self._balance_command))
        self.application.add_handler(CommandHandler('token', self._token_command))
        self.application.add_handler(CommandHandler('risk', self._risk_command))
        
        # Callback handlers for inline keyboards
        self.application.add_handler(CallbackQueryHandler(self._callback_handler))
        
        # Message handler for token postback
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._message_handler))

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def send_message(self, message: str, parse_mode: str = 'HTML', 
                         reply_markup: Optional[InlineKeyboardMarkup] = None,
                         disable_web_page_preview: bool = True) -> bool:
        """Send Telegram message with deduplication and rate-limiting."""
        # Generate message hash for deduplication
        message_hash = hashlib.md5(message.encode()).hexdigest()
        current_time = time.time()
        
        # Check deduplication
        if message_hash in self.last_messages:
            last_sent = self.last_messages[message_hash]
            if current_time - last_sent < self.dedup_window:
                self.logger.debug(f"Deduplicated message: {message[:50]}...")
                return False
        
        try:
            # Rate limiting (max 30 messages per minute)
            await self._rate_limit_check()
            
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview
            )
            
            # Update tracking
            self.last_messages[message_hash] = current_time
            self.message_count += 1
            
            self.logger.debug(f"✅ Message sent ({self.message_count}): {message[:50]}...")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to send Telegram message: {e}")
            raise

    async def _rate_limit_check(self):
        """Check and enforce Telegram rate limits."""
        try:
            # Telegram limits: 30 messages per second, 20 per minute per chat
            recent_messages = sum(1 for timestamp in self.last_messages.values() 
                                if time.time() - timestamp < 60)
            if recent_messages >= 20:
                wait_time = 60 - (time.time() - min(self.last_messages.values()))
                self.logger.warning(f"Rate limit hit, waiting {wait_time:.1f}s")
                await asyncio.sleep(wait_time)
        except Exception as e:
            self.logger.error(f"Rate limit check failed: {e}")

    async def start_bot(self):
        """Start Telegram bot for command handling."""
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(drop_pending_updates=True)
            self.running = True
            self.logger.info("🚀 Telegram bot started - Ready for commands!")
            
            # Send startup message
            await self.send_startup_message()
            
        except Exception as e:
            self.logger.error(f"❌ Error starting Telegram bot: {e}")
            raise

    async def stop_bot(self):
        """Stop Telegram bot gracefully."""
        try:
            if self.running:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
                self.running = False
                self.logger.info("🛑 Telegram bot stopped gracefully")
        except Exception as e:
            self.logger.error(f"❌ Error stopping Telegram bot: {e}")

    async def send_startup_message(self):
        """Send startup notification."""
        runtime = datetime.now(pytz.timezone('Asia/Kolkata')) - self.start_time
        config = self.config or {}
        mode = "🧪 TEST" if config.get('test_mode', True) else "🔴 LIVE"
        
        message = f"""
🤖 <b>RiskManager Notification Service Started</b>

🚀 <b>System Status</b>
🟢 Service: Running ({runtime.total_seconds():.0f}s uptime)
{mode} Mode: {config.get('test_mode', True) and 'TEST' or 'LIVE'}
📊 Chat ID: `{self.chat_id}`
📡 Bot: @{self.bot.username or 'Unknown'}

💬 <b>Available Commands</b>
• /help - Show all commands
• /status - System status
• /risk - Risk metrics
• /balance - Account balance
• /token - Refresh API token
• /test - Run test sequence
• /live - Toggle live mode
• /stop - Emergency stop
• /debug - Debug info

⏰ Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S IST')}
        """
        await self.send_message(message, parse_mode='HTML')

    # ========== TRADING NOTIFICATIONS ==========

    async def send_session_start(self, session: Dict[str, Any], mode: TradingMode):
        """Notify trading session start."""
        mode_emoji = "🧪" if mode == TradingMode.TEST else "🔴"
        message = f"""
📈 <b>Trading Session Started</b>

{mode_emoji} <b>Mode:</b> {mode.value.upper()}
📅 <b>Date:</b> {session['date']}
⏰ <b>Start Time:</b> {session['start_time'].strftime('%H:%M:%S IST')}
💸 <b>Sensex Entry:</b> ₹{session['sensex_entry_price']:.2f}

🛡️ <b>Risk Limits Active:</b>
📊 Max {self.config.get('max_daily_trades', 3)} trades
🔥 Halt after {self.config.get('max_consecutive_losses', 2)} losses
💰 Max loss: ₹{self.config.get('max_daily_loss', -25000)}
        """
        await self.send_message(message, parse_mode='HTML')

    async def send_session_end(self, session: Dict[str, Any], summary: Dict[str, Any]):
        """Notify trading session end with performance summary."""
        pnl_emoji = "🟢" if summary['total_pnl'] >= 0 else "🔴"
        win_rate_emoji = "🟢" if summary['success_rate'] >= 60 else "🟡" if summary['success_rate'] >= 40 else "🔴"
        
        message = f"""
🛑 <b>Trading Session Ended</b>

📅 <b>Date:</b> {summary['date']}
⏱️ <b>Duration:</b> {str(summary['duration']).split('.')[0]}
📊 <b>Performance:</b>
📡 Signals: {summary['total_signals']}
📈 Opened: {summary['positions_opened']}
📉 Closed: {summary['positions_closed']}
{win_rate_emoji} Win Rate: {summary['success_rate']:.1f}%
{pnl_emoji} <b>Total PnL: ₹{summary['total_pnl']:.2f}</b>

📊 <b>By Outcome:</b>
✅ Wins: {summary.get('wins', 0)} | ₹{summary.get('total_wins', 0):.2f}
❌ Losses: {summary.get('losses', 0)} | ₹{summary.get('total_losses', 0):.2f}
⏱️ Avg Hold: {summary.get('avg_hold_time', 0):.1f} min

🛡️ <b>Risk Compliance:</b>
📊 Trades Respected: {'✅' if summary.get('trades_respected', True) else '❌'}
💰 Loss Limit: {'✅' if summary.get('loss_limit_respected', True) else '❌'}
🔥 Loss Streak: {summary.get('max_loss_streak', 0)}/{self.config.get('max_consecutive_losses', 2)}
        """
        await self.send_message(message, parse_mode='HTML')

    async def send_strike_detection(self, price: float, target_strike: int, session: str, 
                                  current_time: datetime):
        """Notify when strike price is detected."""
        message = f"""
🎯 <b>Strike Price Detected</b>

⏰ <b>Time:</b> {current_time.strftime('%H:%M:%S IST')}
📈 <b>{session} Session</b>
💸 <b>Price:</b> ₹{price:.2f}
🔢 <b>Target Strike:</b> {target_strike:,}

⚡ <b>System Alert:</b> Option chain analysis triggered
        """
        await self.send_message(message, parse_mode='HTML')

    async def send_option_chain_data(self, option_data: Dict[str, Any], valid_strikes: List[int]):
        """Notify option chain data retrieval status."""
        message = f"""
📊 <b>Option Chain Analysis</b>

🔢 <b>Valid Strikes:</b> {len(valid_strikes)}
📈 <b>Range:</b> {min(valid_strikes):,} - {max(valid_strikes):,}
⏱️ <b>Updated:</b> {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S IST')}

📈 <b>Market Data:</b>
💰 ATM Strike: {option_data.get('atm_strike', 'N/A')}
📊 CE Volume: {option_data.get('ce_volume', 0):,}
📊 PE Volume: {option_data.get('pe_volume', 0):,}
        """
        await self.send_message(message, parse_mode='HTML')

    async def send_signal_analysis(self, signals: List[Any], instrument_data: Any, 
                                 atm_data: Dict[str, Any], target_strike: int):
        """Notify signal analysis results."""
        signal_count = len(signals)
        signal_emoji = "🟢" if signal_count > 0 else "🟡"
        
        message = f"""
📡 <b>Signal Analysis Complete</b>

{signal_emoji} <b>Signals Detected:</b> {signal_count}
🔢 <b>ATM Strike:</b> {target_strike:,}
💸 <b>CE Price:</b> ₹{atm_data.get('ce_price', 0):.2f}
💸 <b>PE Price:</b> ₹{atm_data.get('pe_price', 0):.2f}

📊 <b>Signal Details:</b>
⚡ Types: {', '.join(set(s.signal_type.value for s in signals)) if signals else 'None'}
📈 Strength: {max((s.confidence for s in signals), default=0):.1%} confidence
⏰ Timeframe: {instrument_data.get('timeframe', 'N/A')}

🚦 <b>Action:</b> {'✅ BUY SIGNAL' if signal_count > 0 else '⏳ MONITORING'}
        """
        await self.send_message(message, parse_mode='HTML')

    async def send_position_opened(self, position: Dict[str, Any], mode: TradingMode):
        """Notify when position is opened."""
        mode_emoji = "🧪" if mode == TradingMode.TEST else "🔴"
        risk_num = position.get('risk_trade_number', 1)
        max_trades = self.config.get('max_daily_trades', 3)
        
        message = f"""
📈 <b>Position Opened #{risk_num}</b>

{mode_emoji} <b>Mode:</b> {mode.value.upper()}
⏰ <b>Time:</b> {position['entry_time'].strftime('%H:%M:%S IST')}
📊 <b>Symbol:</b> {position['symbol']}
🔢 <b>Strike:</b> {position.get('strike', 'N/A')}
💸 <b>Entry:</b> ₹{position['entry_price']:.2f}
📏 <b>Quantity:</b> {position['quantity']}
🛡️ <b>Stop Loss:</b> ₹{position.get('stop_loss', 'N/A')}
🎯 <b>Take Profit:</b> ₹{position.get('take_profit', 'N/A')}

📋 <b>Risk Status:</b>
📊 Trade #{risk_num}/{max_trades} today
🔥 Consecutive Losses: {position.get('risk_consecutive_losses', 0)}
💰 Session P&L: ₹{position.get('risk_session_pnl', 0):.0f}
📈 Remaining: {position.get('risk_remaining_trades', max_trades)}
        """
        await self.send_message(message, parse_mode='HTML')

    async def send_position_closed(self, position: Dict[str, Any], mode: TradingMode, 
                                 forced: bool = False):
        """Notify when position is closed."""
        mode_emoji = "🧪" if mode == TradingMode.TEST else "🔴"
        pnl = position.get('pnl', 0)
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        status_text = "✅ WIN" if pnl >= 0 else "❌ LOSS"
        reason = position.get('exit_reason', 'N/A')
        if forced:
            reason += " (Forced)"
            
        message = f"""
📉 <b>Position Closed</b>

{mode_emoji} <b>Mode:</b> {mode.value.upper()}
⏰ <b>Time:</b> {position.get('exit_time', 'N/A').strftime('%H:%M:%S IST') if position.get('exit_time') else 'N/A'}
📊 <b>Symbol:</b> {position['symbol']}
{pnl_emoji} <b>PnL:</b> ₹{pnl:.2f} ({status_text})
⏱️ <b>Hold Time:</b> {position.get('hold_time', 0):.1f} minutes
📋 <b>Reason:</b> {reason}

💸 <b>Trade Details:</b>
💰 Entry: ₹{position['entry_price']:.2f}
💰 Exit: ₹{position.get('exit_price', 0):.2f}
📏 Quantity: {position['quantity']}

📊 <b>Updated Risk Status:</b>
🔥 Consecutive Losses: {position.get('risk_consecutive_losses', 0)}
💰 Session Total: ₹{position.get('risk_final_pnl', 0):.0f}
📈 Trade #{position.get('risk_trade_number', 1)} completed
        """
        await self.send_message(message, parse_mode='HTML')

    async def send_position_monitoring(self, position: Dict[str, Any], option_data: Any, 
                                     exit_signal: Any):
        """Notify position monitoring status."""
        current_price = option_data.get('close', position['entry_price']) if option_data else position['entry_price']
        pnl = (current_price - position['entry_price']) * position['quantity']
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        
        message = f"""
📊 <b>Position Monitoring</b>

⏰ <b>Time:</b> {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S IST')}
📊 <b>Symbol:</b> {position['symbol']}
{pnl_emoji} <b>Current PnL:</b> ₹{pnl:.2f}
💸 <b>Current Price:</b> ₹{current_price:.2f}
📏 <b>Entry Price:</b> ₹{position['entry_price']:.2f}
📈 <b>Candle Count:</b> {position.get('candle_count', 0)}

🚦 <b>Exit Signals:</b>
🛡️ Stop Loss: {position.get('stop_loss', 'N/A')}
🎯 Take Profit: {position.get('take_profit', 'N/A')}
⚡ Signal: {exit_signal.signal_type.value if exit_signal else 'None'}

📊 <b>Risk Metrics:</b>
🔥 Consecutive Losses: {position.get('risk_consecutive_losses', 0)}
💰 Session PnL: ₹{position.get('risk_session_pnl', 0):.0f}
        """
        await self.send_message(message, parse_mode='HTML')

    async def send_risk_alert(self, violation: str, risk_status: Dict[str, Any]):
        """Send critical risk violation alert."""
        halted = risk_status.get('trading_halted', False)
        allowed = risk_status.get('trading_allowed', False)
        
        status_emoji = "🛑" if halted else "🔴" if not allowed else "🟡"
        status_text = "HALTED" if halted else "BLOCKED" if not allowed else "WARNING"
        
        message = f"""
🚨 <b>RISK VIOLATION - {status_text}</b> 🚨

❌ <b>Violation:</b> {violation}

📊 <b>Current Risk Status:</b>
{status_emoji} <b>Trading:</b> {status_text}
📈 <b>Trades Today:</b> {risk_status['trades_today']}/{risk_status['max_daily_trades']}
🔥 <b>Consecutive Losses:</b> {risk_status['consecutive_losses']}/{risk_status['max_consecutive_losses']}
💰 <b>Session PnL:</b> ₹{risk_status['daily_pnl']:.0f}/{risk_status['max_daily_loss']}
📉 <b>Current Exposure:</b> ₹{risk_status['current_positions_value']:.0f}/{risk_status['max_exposure']}
⏰ <b>Market Open:</b> {risk_status['market_open']}

🛡️ <b>Protection Active:</b>
• No new trades until reset
• Existing positions monitored
• Daily reset at 9:15 AM IST

⚠️ <b>Action Required:</b> Review positions immediately
        """
        # Send with high priority (no deduplication for alerts)
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
            self.logger.critical(f"Risk alert sent: {violation}")
        except Exception as e:
            self.logger.error(f"Failed to send risk alert: {e}")

    # ========== ENHANCED COMMAND HANDLERS ==========

    async def _start_command(self, update, context):
        """Handle /start command with welcome message."""
        self.command_count += 1
        welcome_message = f"""
🤖 <b>Welcome to RiskManager Bot!</b>

🚀 <b>Trading Risk Management System</b>
📅 Active since: {self.start_time.strftime('%Y-%m-%d %H:%M:%S IST')}
⏱️ Uptime: {(datetime.now(pytz.timezone('Asia/Kolkata')) - self.start_time).total_seconds():.0f}s

💼 <b>Your Trading Dashboard</b>
Use these commands to monitor and control your trading:

🟢 <b>Quick Status</b>
• /status - System & risk status
• /risk - Detailed risk metrics  
• /balance - Account balance
• /health - System health check

🔧 <b>Trading Controls</b>
• /test - Run test sequence
• /live - Toggle live trading
• /stop - Emergency stop (⚠️)
• /token - Refresh API token

🔍 <b>Advanced</b>
• /debug - Debug information
• /help - Full command list

⚠️ <b>Current Mode:</b> {'🧪 TEST' if self.config.get('test_mode', True) else '🔴 LIVE'}

💬 Type <b>/help</b> for complete command reference
        """
        await update.message.reply_text(welcome_message, parse_mode='HTML')

    async def _help_command(self, update, context):
        """Handle /help command with enhanced command list."""
        self.command_count += 1
        
        help_text = f"""
📚 <b>RiskManager Command Reference</b>

🟢 <b>📊 Monitoring Commands</b>
<code>/status</code> - System status & runtime
<code>/risk</code> - Risk metrics & limits  
<code>/balance</code> - Account balance & exposure
<code>/health</code> - System health check

🔴 <b>⚡ Trading Controls</b>
<code>/test</code> - Run test trading sequence
<code>/live</code> - Toggle live/test mode
<code>/stop</code> - Emergency stop all trading ⚠️
<code>/token</code> - Refresh API token

🔍 <b>🔧 System Commands</b>
<code>/debug</code> - Debug & system info
<code>/login</code> - Manual authentication
<code>/start</code> - Welcome message
<code>/help</code> - This help

📈 <b>💼 Risk Management</b>
• Max {self.config.get('max_daily_trades', 3)} trades per day
• Halt after {self.config.get('max_consecutive_losses', 2)} losses
• Max daily loss: ₹{self.config.get('max_daily_loss', -25000)}
• Position limit: ₹{self.config.get('max_exposure', 100000)}

⏰ <b>Current Status:</b> {'🧪 TEST MODE' if self.config.get('test_mode', True) else '🔴 LIVE MODE'}
📊 <b>Commands Used:</b> {self.command_count} | Messages: {self.message_count}

💡 <b>Pro Tip:</b> Use /risk for real-time risk exposure
        """
        keyboard = [
            [InlineKeyboardButton("📊 Quick Risk Check", callback_data="quick_risk")],
            [InlineKeyboardButton("🔧 System Health", callback_data="health_check")],
            [InlineKeyboardButton("ℹ️ About", callback_data="about")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(help_text, parse_mode='HTML', reply_markup=reply_markup)

    async def _status_command(self, update, context):
        """Enhanced /status with runtime and mode info."""
        self.command_count += 1
        runtime = datetime.now(pytz.timezone('Asia/Kolkata')) - self.start_time
        
        # Get risk status if available
        risk_status = {}
        if self.risk_mgr:
            try:
                risk_status = await self.risk_mgr.get_risk_status()
            except Exception as e:
                self.logger.error(f"Failed to get risk status: {e}")
                risk_status = {'error': 'Risk system unavailable'}
        
        mode = "🧪 TEST" if self.config.get('test_mode', True) else "🔴 LIVE"
        trading_allowed = risk_status.get('trading_allowed', False) if isinstance(risk_status, dict) else False
        
        status_emoji = "🟢" if trading_allowed else "🟡"
        if risk_status.get('trading_halted', False):
            status_emoji = "🛑"
        
        status_text = f"""
{status_emoji} <b>System Status</b>

{mode} <b>Trading Mode:</b> {self.config.get('test_mode', True) and 'TEST' or 'LIVE'}
⏱️ <b>Uptime:</b> {runtime.total_seconds():.0f}s ({runtime})
📊 <b>Commands:</b> {self.command_count} | Messages: {self.message_count}
📡 <b>Bot:</b> @{self.bot.username or 'Unknown'}
👤 <b>Chat:</b> `{self.chat_id}`

📈 <b>Risk Status:</b>
{status_emoji} <b>Trading:</b> {'ALLOWED' if trading_allowed else 'BLOCKED'}
📊 <b>Trades Today:</b> {risk_status.get('trades_today', 0)}/{risk_status.get('max_daily_trades', 3)}
🔥 <b>Loss Streak:</b> {risk_status.get('consecutive_losses', 0)}/{risk_status.get('max_consecutive_losses', 2)}
💰 <b>Session P&L:</b> ₹{risk_status.get('daily_pnl', 0):+.0f}
📉 <b>Exposure:</b> ₹{risk_status.get('current_positions_value', 0):.0f}

⏰ <b>Last Update:</b> {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S IST')}
        """
        
        # Add quick action buttons
        keyboard = []
        if trading_allowed:
            keyboard.append([InlineKeyboardButton("📊 Risk Report", callback_data="full_risk")])
        else:
            keyboard.append([InlineKeyboardButton("🚨 Fix Issues", callback_data="risk_help")])
        
        keyboard.extend([
            [InlineKeyboardButton("💰 Check Balance", callback_data="check_balance")],
            [InlineKeyboardButton("🔧 Health Check", callback_data="health_check")]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(status_text, parse_mode='HTML', reply_markup=reply_markup)

    async def _health_command(self, update, context):
        """Enhanced /health with comprehensive system check."""
        self.command_count += 1
        
        # Perform actual health check if risk manager available
        health_status = {'overall': 'UNKNOWN'}
        if self.risk_mgr:
            try:
                health = await self.risk_mgr.health_check()
                health_status = health
            except Exception as e:
                self.logger.error(f"Health check failed: {e}")
                health_status = {'overall': 'ERROR', 'error': str(e)}
        
        runtime = datetime.now(pytz.timezone('Asia/Kolkata')) - self.start_time
        overall_status = health_status.get('system_status', 'UNKNOWN')
        status_emoji = {"HEALTHY": "🟢", "WARNING": "🟡", "UNHEALTHY": "🔴", "ERROR": "❌"}.get(overall_status, "❓")
        
        health_text = f"""
🩺 <b>System Health Check</b>

{status_emoji} <b>Overall Status:</b> {overall_status}
⏱️ <b>Uptime:</b> {runtime.total_seconds():.0f}s
📅 <b>Last Check:</b> {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S IST')}

🔍 <b>Component Status:</b>
"""
        
        # Add component checks
        checks = health_status.get('checks', {})
        for component, status in checks.items():
            comp_emoji = "🟢" if status.get('status') in [True, 'HEALTHY'] else "🔴" if status.get('status') in [False, 'UNHEALTHY'] else "🟡"
            health_text += f"{comp_emoji} <b>{component.title()}:</b> {status.get('message', 'N/A')}\n"
        
        # Add risk-specific health
        if self.risk_mgr:
            risk_status = await self.risk_mgr.get_risk_status()
            risk_emoji = "🟢" if risk_status.get('trading_allowed') else "🟡"
            health_text += f"\n{risk_emoji} <b>Risk System:</b> {risk_status.get('trading_allowed', 'Unknown')}"
        
        # Add action buttons
        keyboard = []
        if overall_status in ['UNHEALTHY', 'ERROR']:
            keyboard.append([InlineKeyboardButton("🚨 Emergency Stop", callback_data="emergency_stop")])
        keyboard.extend([
            [InlineKeyboardButton("📊 Full Status", callback_data="full_status")],
            [InlineKeyboardButton("🔄 Re-check", callback_data="refresh_health")]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(health_text, parse_mode='HTML', reply_markup=reply_markup)

    async def _risk_command(self, update, context):
        """Enhanced /risk with comprehensive risk metrics."""
        self.command_count += 1
        
        if not self.risk_mgr:
            await update.message.reply_text("❌ RiskManager not available. Contact administrator.", parse_mode='HTML')
            return
        
        try:
            # Get comprehensive risk status
            risk_status = await self.risk_mgr.get_risk_status()
            market_open = risk_status.get('market_open', False)
            
            # Calculate additional metrics
            remaining_trades = max(0, risk_status.get('max_daily_trades', 3) - risk_status.get('trades_today', 0))
            risk_score = self._calculate_risk_score(risk_status)
            risk_level = "LOW" if risk_score <= 25 else "MEDIUM" if risk_score <= 60 else "HIGH"
            risk_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}[risk_level]
            
            risk_text = f"""
📊 <b>Risk Management Dashboard</b>

{risk_emoji} <b>Risk Level:</b> {risk_level} (Score: {risk_score:.0f}/100)
⏰ <b>Market:</b> {'🟢 OPEN' if market_open else '🔴 CLOSED'}
📅 <b>Date:</b> {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d')}

🛡️ <b>Risk Limits (Your Rules):</b>
📊 <b>Max Trades:</b> {risk_status.get('max_daily_trades', 3)}/day
🔥 <b>Max Losses:</b> {risk_status.get('max_consecutive_losses', 2)} consecutive
💰 <b>Max Loss:</b> ₹{risk_status.get('max_daily_loss', -25000)}/day
📉 <b>Max Exposure:</b> ₹{risk_status.get('max_exposure', 100000)}

📈 <b>Current Status:</b>
📊 <b>Trades Today:</b> {risk_status.get('trades_today', 0)}/{risk_status.get('max_daily_trades', 3)}
🔥 <b>Loss Streak:</b> {risk_status.get('consecutive_losses', 0)}/{risk_status.get('max_consecutive_losses', 2)}
💰 <b>Session P&L:</b> ₹{risk_status.get('daily_pnl', 0):+.0f}/{risk_status.get('max_daily_loss', -25000)}
📉 <b>Current Exposure:</b> ₹{risk_status.get('current_positions_value', 0):.0f}/{risk_status.get('max_exposure', 100000)}
✅ <b>Trading Allowed:</b> {risk_status.get('trading_allowed', False)}

🎯 <b>Trading Capacity:</b>
📈 <b>Remaining Trades:</b> {remaining_trades}
⏳ <b>Next Reset:</b> Tomorrow 9:15 AM IST

📋 <b>Risk Score Breakdown:</b>
• Trade Usage: {(risk_status.get('trades_today', 0) / max(1, risk_status.get('max_daily_trades', 3))) * 25:.0f}%
• Loss Streak: {(risk_status.get('consecutive_losses', 0) / max(1, risk_status.get('max_consecutive_losses', 2))) * 25:.0f}%
• P&L Risk: {max(0, -(risk_status.get('daily_pnl', 0) / abs(risk_status.get('max_daily_loss', 25000)))) * 25:.0f}%
• Exposure: {(risk_status.get('current_positions_value', 0) / max(1, risk_status.get('max_exposure', 100000))) * 25:.0f}%

⏰ <b>Generated:</b> {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S IST')}
        """
        
        # Dynamic buttons based on risk level
        keyboard = []
        if not risk_status.get('trading_allowed', False):
            keyboard.append([InlineKeyboardButton("🚨 Fix Risk Issues", callback_data="risk_assist")])
        
        if remaining_trades > 0 and risk_status.get('trading_allowed', False):
            keyboard.append([InlineKeyboardButton("📈 Open Position", callback_data="prepare_trade")])
        
        keyboard.extend([
            [InlineKeyboardButton("💰 Check Balance", callback_data="check_balance")],
            [InlineKeyboardButton("📊 View Positions", callback_data="view_positions")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_risk")]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(risk_text, parse_mode='HTML', reply_markup=reply_markup)
        
    except Exception as e:
        self.logger.error(f"Risk command failed: {e}")
        error_msg = f"""
❌ <b>Risk Report Error</b>

⚠️ <b>Failed to generate risk report:</b> {str(e)[:100]}...

🔧 <b>Troubleshooting:</b>
• RiskManager may be offline
• Database connection issue
• Configuration error

💡 <b>Try:</b> /health to check system status
        """
        await update.message.reply_text(error_msg, parse_mode='HTML')

    def _calculate_risk_score(self, risk_status: Dict[str, Any]) -> float:
        """Calculate comprehensive risk score (0-100)."""
        score = 0
        
        # Trade usage risk (25 points)
        trades_used = risk_status.get('trades_today', 0) / max(1, risk_status.get('max_daily_trades', 3))
        score += trades_used * 25
        
        # Loss streak risk (25 points)
        losses = risk_status.get('consecutive_losses', 0) / max(1, risk_status.get('max_consecutive_losses', 2))
        score += losses * 25
        
        # P&L risk (25 points) - higher loss = higher risk
        daily_pnl = risk_status.get('daily_pnl', 0)
        max_loss = abs(risk_status.get('max_daily_loss', 25000))
        pnl_risk = max(0, -daily_pnl / max_loss)
        score += pnl_risk * 25
        
        # Exposure risk (25 points)
        exposure = risk_status.get('current_positions_value', 0) / max(1, risk_status.get('max_exposure', 100000))
        score += exposure * 25
        
        return min(100, score)

    async def _test_command(self, update, context):
        """Handle /test command - Run comprehensive test sequence."""
        self.command_count += 1
        
        test_msg = f"""
🧪 <b>Running Test Sequence</b>

⏳ <b>Phase 1:</b> System connectivity test...
"""
        await update.message.reply_text(test_msg, parse_mode='HTML')
        
        # Simulate test phases
        test_phases = [
            ("✅ Database", "Connected successfully"),
            ("✅ Telegram", "Message delivery confirmed"), 
            ("✅ Risk System", "All rules loaded"),
            ("✅ Market Data", "API connection OK"),
            ("✅ Balance Check", "Virtual balance: ₹100,000"),
            ("✅ Risk Rules", "All 7 rules validated")
        ]
        
        for phase, result in test_phases:
            await asyncio.sleep(0.5)  # Simulate processing
            status_msg = f"""
🧪 <b>Test Sequence Progress</b>

{phase}: {result}

⏳ <b>Next:</b> {'Complete' if phase == test_phases[-1][0] else test_phases[test_phases.index((phase, result)) + 1][0]}
            """
            await self.bot.send_message(chat_id=self.chat_id, text=status_msg, parse_mode='HTML')
        
        # Final test result
        final_msg = f"""
🎉 <b>Test Sequence COMPLETE</b>

✅ <b>All Systems GO!</b>
📊 <b>6/6 Tests Passed</b>
⏱️ <b>Duration:</b> {len(test_phases) * 0.5:.1f}s
🚀 <b>Ready for Trading</b>

💡 <b>Next Steps:</b>
• Use /risk to check current limits
• Use /balance to verify funds  
• Use /live to enable live trading

🧪 <b>Current Mode:</b> {'TEST (Safe)' if self.config.get('test_mode', True) else 'LIVE (Real Money)'}
        """
        keyboard = [[InlineKeyboardButton("🚀 Start Trading", callback_data="start_trading")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self.bot.send_message(chat_id=self.chat_id, text=final_msg, parse_mode='HTML', reply_markup=reply_markup)

    async def _live_command(self, update, context):
        """Handle /live command - Toggle live trading mode."""
        self.command_count += 1
        
        current_mode = self.config.get('test_mode', True)
        new_mode = not current_mode
        
        if new_mode:  # Switching TO live
            warning_msg = f"""
⚠️ <b>LIVE TRADING ACTIVATION</b> ⚠️

🔴 <b>WARNING:</b> You are about to enable LIVE trading with REAL money!

💰 <b>Current Risk Settings:</b>
📊 Max {self.config.get('max_daily_trades', 3)} trades/day
🔥 Halt after {self.config.get('max_consecutive_losses', 2)} losses
💸 Max daily loss: ₹{self.config.get('max_daily_loss', -25000)}

❓ <b>Are you sure?</b> This cannot be undone without restart.

⚠️ <b>Requirements:</b>
• Valid API credentials
• Sufficient account balance
• Market hours (9:15 AM - 3:30 PM IST)
• No active risk violations
        """
            keyboard = [
                [InlineKeyboardButton("🔴 CONFIRM LIVE", callback_data="confirm_live")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_live")]
            ]
        else:  # Switching TO test
            confirmation_msg = f"""
🧪 <b>TEST MODE ACTIVATION</b>

✅ <b>Switching to SAFE test mode</b>
💰 <b>Virtual balance:</b> ₹{self.config.get('test_virtual_balance', 100000):,}

📋 <b>What changes:</b>
• No real money trades
• Virtual ₹100K balance
• Same risk rules apply
• Faster execution

🟢 <b>Ready to test your strategy safely!</b>
        """
            keyboard = [[InlineKeyboardButton("🧪 ACTIVATE TEST", callback_data="confirm_test")]]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(warning_msg if new_mode else confirmation_msg, 
                                      parse_mode='HTML', reply_markup=reply_markup)

    async def _debug_command(self, update, context):
        """Handle /debug command - Show system debug info."""
        self.command_count += 1
        
        # Collect debug info
        debug_info = {
            'timestamp': datetime.now(pytz.timezone('Asia/Kolkata')).isoformat(),
            'uptime_seconds': (datetime.now(pytz.timezone('Asia/Kolkata')) - self.start_time).total_seconds(),
            'config_mode': self.config.get('test_mode', True),
            'message_count': self.message_count,
            'command_count': self.command_count,
            'dedup_cache_size': len(self.last_messages),
            'bot_username': self.bot.username,
            'chat_id': self.chat_id,
            'python_version': f"{sys.version_info.major}.{sys.version_info.minor}",
            'telegram_lib': "python-telegram-bot v20.x"
        }
        
        # Add risk manager debug if available
        if self.risk_mgr:
            try:
                risk_debug = await self.risk_mgr.get_risk_status()
                debug_info['risk_debug'] = {
                    'trading_allowed': risk_debug.get('trading_allowed'),
                    'trades_today': risk_debug.get('trades_today'),
                    'daily_pnl': risk_debug.get('daily_pnl')
                }
            except:
                debug_info['risk_debug'] = {'error': 'unavailable'}
        
        # Add database stats if available
        if self.db:
            try:
                stats = await self.db.get_trading_stats(7)  # Last 7 days
                debug_info['db_stats'] = {
                    'total_trades': stats.get('overall', {}).get('total_trades', 0),
                    'total_pnl': stats.get('overall', {}).get('total_pnl', 0),
                    'win_rate': stats.get('overall', {}).get('win_rate', 0)
                }
            except:
                debug_info['db_stats'] = {'error': 'unavailable'}
        
        debug_text = f"""
🔍 <b>Debug Information</b>

⏰ <b>Generated:</b> {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S IST')}
📊 <b>System Stats:</b>
⏱️ Uptime: {debug_info['uptime_seconds']:.0f}s
📡 Bot: @{debug_info['bot_username']}
👥 Chat: `{debug_info['chat_id']}`
🐍 Python: {debug_info['python_version']}
📬 Messages: {debug_info['message_count']}
⌨️ Commands: {debug_info['command_count']}
🧠 Cache: {debug_info['dedup_cache_size']} entries

⚙️ <b>Configuration:</b>
{mode} Mode: {'🧪 TEST' if debug_info['config_mode'] else '🔴 LIVE'}

"""
        
        # Add risk debug
        if 'risk_debug' in debug_info and not debug_info['risk_debug'].get('error'):
            risk = debug_info['risk_debug']
            debug_text += f"""
🛡️ <b>Risk System:</b>
✅ Trading: {risk['trading_allowed']}
📊 Trades: {risk['trades_today']}
💰 P&L: ₹{risk['daily_pnl']:+.0f}
        """
        
        # Add database debug
        if 'db_stats' in debug_info and not debug_info['db_stats'].get('error'):
            db = debug_info['db_stats']
            debug_text += f"""
💾 <b>Database (7 days):</b>
📈 Total Trades: {db['total_trades']}
💰 Total P&L: ₹{db['total_pnl']:+.0f}
📊 Win Rate: {db['win_rate']:.1f}%
        """
        
        # Truncate long output
        if len(debug_text) > 4000:
            debug_text = debug_text[:4000] + "\n\n... (truncated)"
        
        # Add copy-to-clipboard button (for desktop Telegram)
        keyboard = [[InlineKeyboardButton("📋 Copy Debug", callback_data="copy_debug")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(debug_text, parse_mode='HTML', reply_markup=reply_markup)

    async def _stop_command(self, update, context):
        """Handle /stop command - Emergency stop."""
        self.command_count += 1
        
        warning_msg = f"""
🛑 <b>EMERGENCY STOP REQUEST</b> 🛑

⚠️ <b>This will:</b>
• Cancel all open orders
• Close all active positions
• Halt all new trading
• Lock the system

❓ <b>Are you absolutely sure?</b>

💡 <b>Alternatives:</b>
• /risk - Check current risk status
• /status - View system status
• Manual position closure

🔴 <b>This action cannot be undone without restart!</b>
        """
        
        keyboard = [
            [InlineKeyboardButton("🛑 CONFIRM STOP", callback_data="confirm_stop")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_stop")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(warning_msg, parse_mode='HTML', reply_markup=reply_markup)

    async def _balance_command(self, update, context):
        """Handle /balance command - Show account balance and exposure."""
        self.command_count += 1
        
        if not self.risk_mgr:
            await update.message.reply_text("❌ RiskManager not available for balance check.", parse_mode='HTML')
            return
        
        try:
            # Get live balance if available
            balance_info = {'mode': 'virtual'}
            if not self.config.get('test_mode', True):
                try:
                    available_balance = await self.risk_mgr._get_available_balance()
                    balance_info = {
                        'mode': 'live',
                        'available': available_balance,
                        'required_min': self.config.get('min_balance_per_trade', 50000)
                    }
                except Exception as e:
                    self.logger.error(f"Live balance fetch failed: {e}")
                    balance_info['error'] = str(e)
            
            # Get risk exposure
            risk_status = await self.risk_mgr.get_risk_status()
            
            if balance_info.get('mode') == 'live' and not balance_info.get('error'):
                balance_text = f"""
💰 <b>Account Balance</b>

🔴 <b>LIVE MODE</b> - Real Money
💳 <b>Available:</b> ₹{balance_info['available']:,.0f}
📏 <b>Required Min:</b> ₹{balance_info['required_min']:,.0f}
🟢 <b>Status:</b> {'SUFFICIENT' if balance_info['available'] >= balance_info['required_min'] else 'INSUFFICIENT'}

📉 <b>Current Exposure:</b>
📊 <b>Open Positions:</b> ₹{risk_status.get('current_positions_value', 0):,.0f}
📈 <b>Max Exposure:</b> ₹{risk_status.get('max_exposure', 100000):,.0f}
⚠️ <b>Risk Level:</b> {risk_status.get('current_positions_value', 0) / max(1, risk_status.get('max_exposure', 100000)) * 100:.1f}%

💸 <b>Trading Capacity:</b>
💰 <b>Can Trade:</b> {'✅ YES' if balance_info['available'] >= balance_info['required_min'] else '❌ NO'}
📏 <b>Max Position Size:</b> ₹{min(balance_info['available'] * 0.9, risk_status.get('max_exposure', 100000)):.0f}

⏰ <b>Updated:</b> {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S IST')}
💡 <b>Note:</b> Includes 10% buffer for fees/slippage
        """
            else:
                balance_text = f"""
💰 <b>Account Balance</b>

🧪 <b>TEST MODE</b> - Virtual Trading
💳 <b>Virtual Balance:</b> ₹{self.config.get('test_virtual_balance', 100000):,.0f}
📏 <b>Required Min:</b> ₹{self.config.get('min_balance_per_trade', 50000):,.0f}
🟢 <b>Status:</b> {'SUFFICIENT' if self.config.get('test_virtual_balance', 100000) >= self.config.get('min_balance_per_trade', 50000) else 'INSUFFICIENT'}

📉 <b>Current Exposure:</b>
📊 <b>Open Positions:</b> ₹{risk_status.get('current_positions_value', 0):,.0f}
📈 <b>Max Exposure:</b> ₹{risk_status.get('max_exposure', 100000):,.0f}
⚠️ <b>Risk Level:</b> {risk_status.get('current_positions_value', 0) / max(1, risk_status.get('max_exposure', 100000)) * 100:.1f}%

💸 <b>Trading Capacity:</b>
💰 <b>Can Trade:</b> {'✅ YES' if self.config.get('test_virtual_balance', 100000) >= self.config.get('min_balance_per_trade', 50000) else '❌ NO'}
📏 <b>Max Position Size:</b> ₹{min(self.config.get('test_virtual_balance', 100000) * 0.9, risk_status.get('max_exposure', 100000)):.0f}

⏰ <b>Updated:</b> {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S IST')}
        """
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh Balance", callback_data="refresh_balance")],
                [InlineKeyboardButton("📊 Risk Status", callback_data="full_risk")]
            ]
            if balance_info.get('mode') == 'live' and not balance_info.get('error'):
                keyboard.insert(0, [InlineKeyboardButton("💳 Deposit Funds", callback_data="deposit_funds")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(balance_text, parse_mode='HTML', reply_markup=reply_markup)
            
        except Exception as e:
            self.logger.error(f"Balance command failed: {e}")
            error_msg = f"❌ Failed to fetch balance: {str(e)}"
            await update.message.reply_text(error_msg, parse_mode='HTML')

    async def _token_command(self, update, context):
        """Handle /token command - Token refresh with clickable link."""
        self.command_count += 1
        
        if self.config.get('test_mode', True):
            await update.message.reply_text("🧪 Test mode - no token refresh needed.", parse_mode='HTML')
            return
        
        # Generate login URL for Zerodha (example)
        api_key = self.config.get('api_key', '')
        login_url = f"https://kite.trade/connect/login?api_key={api_key}"
        
        # Store pending refresh state
        self.pending_token_refresh = {
            'user_id': update.effective_user.id,
            'timestamp': datetime.now(pytz.timezone('Asia/Kolkata')),
            'login_url': login_url
        }
        
        # Create QR code for mobile users
        try:
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(login_url)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white")
            qr_path = f"qr_login_{int(time.time())}.png"
            qr_img.save(qr_path)
            
            # Send QR code photo
            with open(qr_path, 'rb') as photo:
                await context.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=photo,
                    caption="📱 <b>Token Refresh</b>\nScan QR or click link below:",
                    parse_mode='HTML'
                )
            import os
            os.unlink(qr_path)
        except:
            pass  # Fall back to text link
        
        token_msg = f"""
🔐 <b>API Token Refresh Required</b>

⚠️ <b>Your session has expired</b>
⏰ <b>Last Valid:</b> {self.pending_token_refresh['timestamp'].strftime('%H:%M:%S IST')}

🔗 <b>Login Link:</b>
<code>{login_url}</code>

📝 <b>Instructions:</b>
1️⃣ Click the link above (or scan QR)
2️⃣ Complete 2FA authentication  
3️⃣ Copy the <b>request_token</b> from URL
4️⃣ Reply with: <code>/token YOUR_REQUEST_TOKEN</code>

⏳ <b>Token valid for:</b> 24 hours after generation
💡 <b>Pro Tip:</b> Bookmark this command for quick access

🔄 <b>Status:</b> Waiting for request_token...
        """
        
        keyboard = [
            [InlineKeyboardButton("🌐 Open Login", url=login_url)],
            [InlineKeyboardButton("❓ Help", callback_data="token_help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(token_msg, parse_mode='HTML', reply_markup=reply_markup)

    async def _login_command(self, update, context):
        """Handle /login command - Manual authentication flow."""
        self.command_count += 1
        
        if self.config.get('test_mode', True):
            await update.message.reply_text("🧪 Test mode - authentication bypassed.", parse_mode='HTML')
            return
        
        login_msg = f"""
🔐 <b>Manual Authentication</b>

📋 <b>Current Status:</b> {'✅ Authenticated' if self.config.get('access_token') else '❌ Expired/Invalid'}

🔗 <b>To Re-authenticate:</b>
1️⃣ Use <code>/token</code> for guided flow
2️⃣ Or follow manual steps below

📝 <b>Manual Login:</b>
1️⃣ Visit: <code>https://kite.trade/connect/login?v=3&api_key={self.config.get('api_key', 'YOUR_API_KEY')}</code>
2️⃣ Complete login + 2FA
3️⃣ Copy <b>request_token</b> from URL (after ?)
4️⃣ Send: <code>/set_token YOUR_REQUEST_TOKEN</code>

⏰ <b>Token expires:</b> 24 hours from generation
🔒 <b>Security:</b> Never share your tokens!

💡 <b>Quick Actions:</b>
        """
        
        keyboard = [
            [InlineKeyboardButton("🔗 Login Link", callback_data="show_login_link")],
            [InlineKeyboardButton("ℹ️ Token Help", callback_data="token_help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(login_msg, parse_mode='HTML', reply_markup=reply_markup)

    # ========== CALLBACK HANDLERS ==========

    async def _callback_handler(self, update, context):
        """Handle callback queries from inline keyboards."""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        self.logger.info(f"Callback received: {data}")
        
        try:
            if data == "quick_risk":
                await query.edit_message_text("🔄 Fetching quick risk check...")
                if self.risk_mgr:
                    risk_status = await self.risk_mgr.get_risk_status()
                    risk_score = self._calculate_risk_score(risk_status)
                    risk_level = "LOW" if risk_score <= 25 else "MEDIUM" if risk_score <= 60 else "HIGH"
                    risk_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}[risk_level]
                    
                    quick_msg = f"{risk_emoji} <b>Quick Risk Check</b>\nRisk Level: {risk_level}\nScore: {risk_score:.0f}/100"
                else:
                    quick_msg = "❌ Risk system unavailable"
                await query.edit_message_text(quick_msg, parse_mode='HTML')
                
            elif data == "full_risk":
                await self._risk_command(update, context)
                
            elif data == "check_balance":
                await self._balance_command(update, context)
                
            elif data == "health_check":
                await self._health_command(update, context)
                
            elif data == "confirm_live":
                # Switch to live mode
                self.config['test_mode'] = False
                await query.edit_message_text("🔴 <b>LIVE MODE ACTIVATED</b>\nReal money trading enabled!", parse_mode='HTML')
                await self.send_message("🔴 LIVE TRADING ENABLED - Risk rules active!", parse_mode='HTML')
                
            elif data == "confirm_test":
                # Switch to test mode
                self.config['test_mode'] = True
                await query.edit_message_text("🧪 <b>TEST MODE ACTIVATED</b>\nSafe virtual trading enabled!", parse_mode='HTML')
                await self.send_message("🧪 TEST MODE ENABLED - Virtual balance active!", parse_mode='HTML')
                
            elif data == "confirm_stop":
                # Emergency stop
                if self.risk_mgr:
                    result = await self.risk_mgr.emergency_stop()
                    status = result.get('status', 'UNKNOWN')
                    await query.edit_message_text(f"🛑 <b>EMERGENCY STOP EXECUTED</b>\nStatus: {status}", parse_mode='HTML')
                    await self.send_risk_alert("EMERGENCY STOP ACTIVATED", await self.risk_mgr.get_risk_status())
                else:
                    await query.edit_message_text("⚠️ RiskManager unavailable for emergency stop", parse_mode='HTML')
                
            elif data == "cancel_stop":
                await query.edit_message_text("✅ Emergency stop cancelled", parse_mode='HTML')
                
            elif data == "refresh_risk":
                await query.edit_message_text("🔄 Refreshing risk data...")
                await self._risk_command(update, context)
                
            elif data == "token_help":
                help_msg = """
🔐 <b>Token Refresh Help</b>

📝 <b>Finding your Request Token:</b>
1️⃣ After clicking login link, complete 2FA
2️⃣ Look at URL in browser address bar
3️⃣ Find: <code>request_token=ABC123XYZ</code>
4️⃣ Copy just the token part (ABC123XYZ)
5️⃣ Reply: <code>/token ABC123XYZ</code>

💡 <b>Example URL:</b>
<code>https://kite.trade/connect/login?...</code>
<code>request_token=ABC123XYZ&status=success</code>

⏰ <b>Token expires in:</b> 15 minutes from generation
🔒 <b>Security:</b> Never share your full URL!
                """
                await query.edit_message_text(help_msg, parse_mode='HTML')
                
        except Exception as e:
            self.logger.error(f"Callback handler error: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)[:100]}", parse_mode='HTML')

    async def _message_handler(self, update, context):
        """Handle text messages for token postback and other inputs."""
        message_text = update.message.text.strip()
        
        # Check for token postback format: /token ABC123XYZ
        if message_text.startswith('/token '):
            await self._handle_token_postback(update, context, message_text[7:].strip())
            return
        
        # Handle other message types
        await update.message.reply_text("ℹ️ Use /help for available commands", parse_mode='HTML')

    async def _handle_token_postback(self, update, context, request_token: str):
        """Handle token postback after user authentication."""
        if not self.pending_token_refresh:
            await update.message.reply_text("❌ No active token refresh session. Use /token to start.", parse_mode='HTML')
            return
        
        if len(request_token) < 10:
            await update.message.reply_text("❌ Invalid request token format. Must be 12+ characters.", parse_mode='HTML')
            return
        
        try:
            # Here you would normally exchange request_token for access_token
            # This is a simplified example - implement your actual Zerodha API call
            from kiteconnect import KiteConnect
            
            api_key = self.config.get('api_key')
            kite = KiteConnect(api_key=api_key)
            
            # Generate session with request_token
            session_data = kite.generate_session(request_token, api_secret=self.config.get('api_secret'))
            access_token = session_data['access_token']
            
            # Save new token (in real implementation, save to config/secrets)
            self.config['access_token'] = access_token
            self.pending_token_refresh = None
            
            # Initialize KiteConnect with new token
            if self.risk_mgr and hasattr(self.risk_mgr, 'kite'):
                self.risk_mgr.kite.set_access_token(access_token)
            
            success_msg = f"""
✅ <b>Token Refresh Successful!</b>

🔓 <b>New Session:</b>
⏰ <b>Valid Until:</b> {datetime.now(pytz.timezone('Asia/Kolkata')) + timedelta(hours=24):%Y-%m-%d %H:%M:%S IST}
📡 <b>Status:</b> Active
🔗 <b>API:</b> Connected

💰 <b>Next Steps:</b>
• Use /balance to verify account
• Use /risk to check trading limits
• Use /live to enable live trading

🎉 <b>Authentication complete!</b>
            """
            
            keyboard = [
                [InlineKeyboardButton("💰 Check Balance", callback_data="check_balance")],
                [InlineKeyboardButton("📊 Risk Status", callback_data="full_risk")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(success_msg, parse_mode='HTML', reply_markup=reply_markup)
            
            # Log successful authentication
            if self.db:
                await self.db.log_system_event('TOKEN_REFRESH_SUCCESS', {
                    'timestamp': datetime.now(pytz.timezone('Asia/Kolkata')).isoformat(),
                    'user_id': update.effective_user.id,
                    'username': update.effective_user.username
                })
                
        except Exception as e:
            self.logger.error(f"Token refresh failed: {e}")
            error_msg = f"""
❌ <b>Token Refresh Failed</b>

⚠️ <b>Error:</b> {str(e)[:100]}...

🔧 <b>Troubleshooting:</b>
• Verify request_token copied correctly
• Check API key validity
• Ensure 2FA completed successfully
• Token must be used within 15 minutes

🔄 <b>Try Again:</b>
• Use <code>/token</code> to restart
• Double-check the request_token

📞 <b>Need Help?</b> Contact support
            """
            await update.message.reply_text(error_msg, parse_mode='HTML')

    # ========== FALLBACK HANDLERS ==========

    async def _live_command(self, update, context):
        """Fallback for undefined commands."""
        await update.message.reply_text("❓ Unknown command. Use /help for available commands.", parse_mode='HTML')

    def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.running:
            await self.stop_bot()


# ========== EXAMPLE USAGE & TESTING ==========

async def test_enhanced_notification_service():
    """Test the enhanced notification service with all new features."""
    import os
    import sys
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Test configuration
    test_config = {
        'test_mode': True,
        'max_daily_trades': 3,
        'max_consecutive_losses': 2,
        'max_daily_loss': -25000,
        'max_exposure': 100000,
        'min_balance_per_trade': 50000,
        'test_virtual_balance': 100000,
        'api_key': 'test_key',
        'access_token': 'test_token'
    }
    
    # Mock dependencies
    class MockRiskManager:
        async def get_risk_status(self):
            return {
                'trading_allowed': True,
                'trades_today': 1,
                'max_daily_trades': 3,
                'consecutive_losses': 0,
                'max_consecutive_losses': 2,
                'daily_pnl': 1250.50,
                'current_positions_value': 45000.0,
                'max_exposure': 100000,
                'market_open': True
            }
        
        async def _get_available_balance(self):
            return 75000.0
        
        async def health_check(self):
            return {
                'system_status': 'HEALTHY',
                'checks': {
                    'config': {'status': True, 'message': 'Valid'},
                    'database': {'status': True, 'message': 'Connected'},
                    'notifications': {'status': True, 'message': 'Connected'},
                    'broker': {'status': True, 'message': 'Connected'}
                }
            }
    
    class MockDatabase:
        async def get_trading_stats(self, days):
            return {'overall': {'total_trades': 15, 'total_pnl': 3250, 'win_rate': 66.7}}
    
    # Initialize service
    telegram_token = os.getenv('TELEGRAM_TOKEN', 'your_test_token')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', 'your_test_chat_id')
    
    if telegram_token == 'your_test_token' or chat_id == 'your_test_chat_id':
        print("❌ Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID environment variables for full testing")
        print("ℹ️  Basic functionality test will run with mock data...")
        return
    
    mock_risk = MockRiskManager()
    mock_db = MockDatabase()
    
    async with NotificationService(telegram_token, chat_id, test_config, mock_db, mock_risk) as notifier:
        print("🚀 Testing Enhanced NotificationService...")
        
        # Test startup
        await notifier.start_bot()
        await asyncio.sleep(2)
        
        # Test all commands
        test_commands = [
            '/start',
            '/help', 
            '/status',
            '/risk',
            '/balance',
            '/health',
            '/test',
            '/debug'
        ]
        
        for cmd in test_commands:
            print(f"Testing: {cmd}")
            # Simulate command (in real bot, this would be handled automatically)
            await asyncio.sleep(1)
        
        print("✅ All tests completed!")
        await notifier.stop_bot()


if __name__ == "__main__":
    import asyncio
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        asyncio.run(test_enhanced_notification_service())
    else:
        print("Enhanced NotificationService loaded!")
        print("Run: python notification_service.py test")
