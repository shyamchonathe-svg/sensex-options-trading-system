#!/usr/bin/env python3
"""
EnhancedNotificationService - With Automated Postback Auth
Integrates with your EC2 auth server at sensexbot.ddns.net:443
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
import httpx

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

from secure_config_manager import SecureConfigManager

logger = logging.getLogger(__name__)

class EnhancedNotificationService:
    """Your existing notification service + postback authentication."""
    
    def __init__(self, config: SecureConfigManager, controller=None):
        self.config = config
        self.controller = controller
        self.app = None
        self.auth_url = config.get_auth_url()
        
        # Track active authentication sessions
        self.active_auth_state = None
        self.auth_timeout_task = None
        
        self._initialize_bot()
    
    def _initialize_bot(self):
        """Initialize Telegram bot with enhanced handlers."""
        try:
            self.app = Application.builder().token(self.config.TELEGRAM_TOKEN).build()
            
            # Your existing command handlers
            self.app.add_handler(CommandHandler("start", self.start_command))
            self.app.add_handler(CommandHandler("status", self.status_command))
            self.app.add_handler(CommandHandler("risk", self.risk_command))
            self.app.add_handler(CommandHandler("positions", self.positions_command))
            
            # NEW: Authentication and mode handlers
            self.app.add_handler(CommandHandler("auth", self.auth_command))
            self.app.add_handler(CommandHandler("mode", self.mode_command))
            self.app.add_handler(CommandHandler("restart", self.restart_command))
            
            # Inline button callbacks
            self.app.add_handler(CallbackQueryHandler(self.button_callback))
            
            logger.info("✅ Enhanced Telegram bot initialized with postback auth")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Telegram bot: {e}")
            raise
    
    async def start_bot(self):
        """Start the Telegram bot."""
        if not self.app:
            raise RuntimeError("Bot not initialized")
        
        logger.info("🚀 Starting enhanced Telegram bot...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        
        # Send startup notification
        await self.send_startup_message()
        logger.info("✅ Telegram bot is running with postback authentication")
    
    async def send_startup_message(self):
        """Send enhanced startup notification."""
        token_status = "✅ Valid" if self.config.ACCESS_TOKEN else "🔐 Refresh Required"
        protocol_emoji = "🔒" if self.config.USE_HTTPS else "🔓"
        
        startup_message = (
            f"🤖 <b>Sensex Options Trading Bot v2.0</b>\n\n"
            f"🚀 <b>Enhanced Features Enabled:</b>\n"
            f"   • <b>Automated Token Refresh</b> via postback\n"
            f"   • {protocol_emoji} Auth Server: <code>{self.auth_url}</code>\n"
            f"   • EC2 Deployment: .env secured (Git excluded)\n\n"
            f"⚙️ <b>Configuration:</b>\n"
            f"   • Mode: <b>{self.config.MODE}</b>\n"
            f"   • Token Status: {token_status}\n"
            f"   • Lot Size: {self.config.LOT_SIZE}\n"
            f"   • Max Trades: {self.config.MAX_DAILY_TRADES}\n\n"
            f"💡 <b>New Authentication Flow:</b>\n"
            f"   <code>/auth</code> → Click button → <b>Automatic!</b>\n"
            f"   No more manual request_token copy-paste\n\n"
            f"📊 <b>Trading Ready:</b>\n"
            f"   • Market Hours: 9:18 AM - 3:15 PM IST\n"
            f"   • Next Cycle: {datetime.now().strftime('%H:%M')}\n"
            f"   • Market Status: {'🟢 Open' if self.config.is_market_open() else '🔴 Closed'}"
        )
        
        await self._send_message(startup_message)
    
    async def _send_message(self, message: str, parse_mode: str = "HTML", reply_markup=None):
        """Send message to configured chat ID."""
        try:
            await self.app.bot.send_message(
                chat_id=self.config.TELEGRAM_CHAT_ID,
                text=message,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            logger.debug(f"📱 Message sent to chat {self.config.TELEGRAM_CHAT_ID[:6]}...")
        except Exception as e:
            logger.error(f"❌ Failed to send message: {e}")
    
    # === NEW: AUTOMATED AUTHENTICATION ===
    
    async def auth_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle /auth command - Fully automated postback flow.
        
        Flow:
        1. Check if token is still valid
        2. Validate auth server health
        3. Generate login URL with inline button
        4. User clicks → Zerodha login → automatic postback
        5. Token updated on EC2 → success notification
        """
        
        # Check if token is still valid
        if self.config.ACCESS_TOKEN and not self.config._check_token_expiry():
            now = datetime.now()
            expiry_time = now.replace(hour=9, minute=0, second=0) + timedelta(days=1)
            time_left = expiry_time - now
            hours_left = time_left.seconds // 3600
            
            if hours_left > 2:  # More than 2 hours remaining
                await update.message.reply_text(
                    f"ℹ️ <b>Token is still valid</b>\n\n"
                    f"⏰ Expires in approximately {hours_left} hours\n"
                    f"💡 Use <code>/auth</code> tomorrow after 8 AM IST\n\n"
                    f"📊 Current status:\n"
                    f"   • Mode: <b>{self.config.MODE}</b>\n"
                    f"   • Server: <code>{self.auth_url}</code>",
                    parse_mode="HTML"
                )
                return
        
        # Check if authentication already in progress
        if self.active_auth_state:
            await update.message.reply_text(
                f"⏳ <b>Authentication in progress</b>\n\n"
                f"🔑 Current Session ID: <code>{self.active_auth_state[:8]}...</code>\n"
                f"⏰ Timeout: {self.config.AUTH_TIMEOUT // 60} minutes remaining\n\n"
                f"💡 Please complete the login in your browser first,\n"
                f"    then this session will update automatically.",
                parse_mode="HTML"
            )
            return
        
        # Step 1: Validate auth server health
        try:
            logger.info("🔍 Checking auth server health...")
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.auth_url}/health")
                
                if response.status_code != 200:
                    raise Exception(f"HTTP {response.status_code}")
                
                health_data = response.json()
                if health_data.get('status') != 'healthy':
                    raise Exception(f"Server unhealthy: {health_data}")
                
                logger.info(f"✅ Auth server healthy: {health_data.get('auth', {}).get('pending_requests', 0)} pending")
                
        except Exception as e:
            error_msg = (
                f"❌ <b>Auth Server Unavailable</b>\n\n"
                f"Cannot connect to authentication server:\n"
                f"   • URL: <code>{self.auth_url}</code>\n"
                f"   • Error: {str(e)[:100]}...\n\n"
                f"💡 <b>Troubleshooting:</b>\n"
                f"   • Ensure <code>auth_server.py</code> is running on EC2\n"
                f"   • Check <code>{self.auth_url}/health</code> manually\n"
                f"   • Verify DNS: <code>{self.config.POSTBACK_HOST}</code>\n"
                f"   • Port {self.config.POSTBACK_PORT}: {'HTTPS' if self.config.USE_HTTPS else 'HTTP'}",
                parse_mode="HTML"
            )
            await update.message.reply_text(error_msg)
            logger.error(f"❌ Auth server check failed: {e}")
            return
        
        # Step 2: Generate authentication URL
        try:
            logger.info("🔄 Generating authentication URL...")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.auth_url}/auth/generate")
                
                if response.status_code != 200:
                    raise Exception(f"HTTP {response.status_code}")
                
                auth_data = response.json()
                
                if not auth_data.get('success'):
                    raise Exception(f"Auth generation failed: {auth_data}")
            
            # Store active auth state
            self.active_auth_state = auth_data['state']
            login_url = auth_data['login_url']
            postback_url = auth_data['postback_url']
            
            # Create inline keyboard with login button
            keyboard = [[InlineKeyboardButton("🔐 Login to Zerodha", url=login_url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Calculate timeout
            timeout_minutes = self.config.AUTH_TIMEOUT // 60
            expiry_time = datetime.now() + timedelta(seconds=self.config.AUTH_TIMEOUT)
            
            # Send authentication message
            auth_message = (
                f"🔐 <b>Zerodha Authentication Required</b>\n\n"
                f"👆 <b>Click the button below</b> to authenticate with Zerodha Kite.\n\n"
                f"🎯 <b>Fully Automated Flow:</b>\n"
                f"   1️⃣ Click \"Login to Zerodha\"\n"
                f"   2️⃣ Enter your credentials\n"
                f"   3️⃣ <b>Automatic redirect</b> to {self.config.POSTBACK_HOST}\n"
                f"   4️⃣ Token updated on EC2 → Success notification!\n\n"
                f"⏰ <b>Session expires:</b> {expiry_time.strftime('%H:%M:%S IST')}\n"
                f"🔑 <b>Session ID:</b> <code>{self.active_auth_state[:8]}...</code>\n"
                f"🌐 <b>Postback URL:</b> <code>{postback_url}</code>\n\n"
                f"⚙️ <b>After success:</b> Bot will restart in <b>{self.config.MODE}</b> mode"
            )
            
            await update.message.reply_text(auth_message, parse_mode="HTML", reply_markup=reply_markup)
            
            # Start timeout monitoring
            self.auth_timeout_task = asyncio.create_task(
                self._monitor_auth_session(self.active_auth_state)
            )
            
            logger.info(f"✅ Auth session started: {self.active_auth_state[:8]}...")
            
        except Exception as e:
            logger.error(f"❌ Auth URL generation failed: {e}")
            await update.message.reply_text(
                f"❌ <b>Authentication Setup Failed</b>\n\n"
                f"Error generating login URL:\n"
                f"   • {str(e)[:100]}...\n\n"
                f"💡 <b>Please check:</b>\n"
                f"   • ZAPI_KEY and ZAPI_SECRET in .env\n"
                f"   • Auth server logs: <code>tail -f logs/auth_server.log</code>\n"
                f"   • EC2 security group allows port {self.config.POSTBACK_PORT}",
                parse_mode="HTML"
            )
    
    async def _monitor_auth_session(self, state: str):
        """Monitor authentication session and handle timeout."""
        try:
            await asyncio.sleep(self.config.AUTH_TIMEOUT)
            
            # Check if this is still the active session
            if self.active_auth_state == state:
                self.active_auth_state = None
                self.auth_timeout_task = None
                
                # Double-check server status
                try:
                    async with httpx.AsyncClient(timeout=3.0) as client:
                        response = await client.get(f"{self.auth_url}/pending")
                        pending_data = response.json()
                        
                        if pending_data.get('pending_count', 0) > 0:
                            timeout_message = (
                                f"⏰ <b>Authentication Session Expired</b>\n\n"
                                f"❌ Your login session has timed out after {self.config.AUTH_TIMEOUT // 60} minutes.\n\n"
                                f"💡 <b>To start fresh:</b>\n"
                                f"   • Use <code>/auth</code> command again\n"
                                f"   • Complete login within {self.config.AUTH_TIMEOUT // 60} minutes\n\n"
                                f"📊 <b>Server Status:</b>\n"
                                f"   • Pending requests: {pending_data.get('pending_count', 0)}\n"
                                f"   • Auth server: {'✅ Healthy' if pending_data.get('status') == 'ok' else '❌ Unreachable'}"
                            )
                            await self._send_message(timeout_message, parse_mode="HTML")
                            
                            logger.info(f"⏰ Auth session {state[:8]}... expired and cleaned up")
                            
                except Exception as e:
                    logger.warning(f"⚠️ Could not check server during timeout: {e}")
                    await self._send_message(
                        f"⏰ <b>Session Timeout</b>\n\n"
                        f"Authentication session expired. Use <code>/auth</code> to start new session.",
                        parse_mode="HTML"
                    )
                    
        except asyncio.CancelledError:
            logger.debug(f"Auth monitor for {state[:8]}... was cancelled")
    
    # === MODE SWITCHING ===
    
    async def mode_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /mode command for switching trading modes."""
        if not context.args:
            modes_message = (
                f"⚙️ <b>Available Trading Modes</b>\n\n"
                f"🔴 <b>LIVE</b> - Real trading with live orders\n"
                f"   • Requires valid ACCESS_TOKEN\n"
                f"   • Uses real money via Zerodha API\n\n"
                f"🟡 <b>TEST</b> - Paper trading simulation\n"
                f"   • Virtual ₹5,00,000 balance\n"
                f"   • No real money risk\n\n"
                f"🔵 <b>DEBUG</b> - Historical backtesting\n"
                f"   • Uses CSV data from archives/\n"
                f"   • Strategy development and validation\n\n"
                f"💡 <b>Usage:</b> <code>/mode LIVE</code> (or TEST, DEBUG)\n\n"
                f"⚠️ <b>LIVE mode requires valid token!</b>\n"
                f"   Use <code>/auth</code> first if needed."
            )
            await update.message.reply_text(modes_message, parse_mode="HTML")
            return
        
        new_mode = context.args[0].upper()
        valid_modes = ['LIVE', 'TEST', 'DEBUG']
        
        if new_mode not in valid_modes:
            await update.message.reply_text(
                f"❌ <b>Invalid Mode</b>\n\n"
                f"<code>{new_mode}</code> is not a valid trading mode.\n\n"
                f"Valid modes: {', '.join(valid_modes)}",
                parse_mode="HTML"
            )
            return
        
        # Special validation for LIVE mode
        if new_mode == 'LIVE':
            if not self.config.ACCESS_TOKEN:
                await update.message.reply_text(
                    f"⚠️ <b>Cannot Switch to LIVE Mode</b>\n\n"
                    f"❌ Missing valid ACCESS_TOKEN.\n\n"
                    f"💡 <b>First, authenticate:</b>\n"
                    f"   1. Use <code>/auth</code> command\n"
                    f"   2. Click \"Login to Zerodha\" button\n"
                    f"   3. Complete login → automatic token update\n"
                    f"   4. Then try <code>/mode LIVE</code> again",
                    parse_mode="HTML"
                )
                return
            
            # Double-check token expiry
            if self.config._check_token_expiry():
                await update.message.reply_text(
                    f"⚠️ <b>LIVE Mode - Token Expired</b>\n\n"
                    f"❌ Current ACCESS_TOKEN has expired.\n\n"
                    f"💡 <b>Refresh token first:</b>\n"
                    f"   • Use <code>/auth</code> to get new token\n"
                    f"   • Then switch to LIVE mode",
                    parse_mode="HTML"
                )
                return
        
        try:
            # Update configuration
            old_mode = self.config.MODE
            self.config.MODE = new_mode
            
            # Restart service if controller exists
            if self.controller:
                await self.controller.restart_service(new_mode=new_mode)
            
            # Mode emojis for visual feedback
            mode_emojis = {'LIVE': '🔴', 'TEST': '🟡', 'DEBUG': '🔵'}
            emoji = mode_emojis.get(new_mode, '⚪')
            
            # Success message
            success_message = (
                f"✅ <b>Trading Mode Updated!</b>\n\n"
                f"{emoji} <b>New Mode:</b> {new_mode}\n"
                f"⬅️ <b>Previous:</b> {old_mode}\n"
                f"⏰ Service restarted successfully\n\n"
                f"📊 <b>Next Steps:</b>\n"
            )
            
            if new_mode == 'LIVE':
                success_message += f"   • <b>⚠️  LIVE TRADING ACTIVE</b> - Real money at risk\n"
                success_message += f"   • Token validated: ✅ Valid until 9 AM tomorrow\n"
            elif new_mode == 'TEST':
                success_message += f"   • 🧪 Paper trading with virtual ₹5L balance\n"
            else:  # DEBUG
                success_message += f"   • 🔍 Historical backtesting mode\n"
            
            success_message += f"\n💡 Trading cycles start at 9:18 AM IST"
            
            await update.message.reply_text(success_message, parse_mode="HTML")
            logger.info(f"🔄 Mode switched: {old_mode} → {new_mode} via Telegram")
            
        except Exception as e:
            logger.error(f"❌ Mode switch failed: {e}")
            await update.message.reply_text(
                f"❌ <b>Mode Switch Failed</b>\n\n"
                f"Error: {str(e)[:100]}...\n\n"
                f"💡 Please check logs and try again.",
                parse_mode="HTML"
            )
    
    async def restart_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /restart command."""
        try:
            if self.controller:
                await self.controller.restart_service()
                restart_message = (
                    f"🔄 <b>Service Restarted Successfully!</b>\n\n"
                    f"⚙️ <b>Current Configuration:</b>\n"
                    f"   • Mode: <b>{self.config.MODE}</b>\n"
                    f"   • Auth Server: <code>{self.auth_url}</code>\n"
                    f"   • Token Status: {'✅ Valid' if self.config.ACCESS_TOKEN else '🔐 Refresh needed'}\n\n"
                    f"⏰ <b>Trading Cycles:</b>\n"
                    f"   • Next cycle: {datetime.now().strftime('%H:%M')}\n"
                    f"   • Market: {'🟢 Open' if self.config.is_market_open() else '🔴 Closed'}\n\n"
                    f"📊 System ready for operation"
                )
                await update.message.reply_text(restart_message, parse_mode="HTML")
            else:
                await update.message.reply_text(
                    f"ℹ️ <b>Restart Command Received</b>\n\n"
                    f"Trading controller not active in this session.\n"
                    f"💡 The main service will auto-restart on next cycle.\n\n"
                    f"⚙️ Current mode: <b>{self.config.MODE}</b>",
                    parse_mode="HTML"
                )
                
        except Exception as e:
            logger.error(f"❌ Restart command failed: {e}")
            await update.message.reply_text(
                f"❌ <b>Restart Failed</b>\n\n"
                f"Error: {str(e)[:100]}...\n"
                f"💡 Check server logs for details.",
                parse_mode="HTML"
            )
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard button callbacks."""
        query = update.callback_query
        await query.answer()
        
        callback_data = query.data
        
        # Route to appropriate command
        if callback_data == "auth":
            await self.auth_command(update, context)
        elif callback_data == "status":
            await self.status_command(update, context)
        elif callback_data == "mode":
            await self.mode_command(update, context)
        elif callback_data == "risk":
            await self.risk_command(update, context)
    
    # === YOUR EXISTING COMMANDS (Enhanced) ===
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced /start command with new features."""
        token_status = "✅ Valid" if self.config.ACCESS_TOKEN else "🔐 Refresh Required"
        market_status = "🟢 Open" if self.config.is_market_open() else "🔴 Closed"
        
        welcome_message = (
            f"🤖 <b>Welcome to Sensex Options Trading Bot!</b>\n\n"
            f"📈 <b>Automated Mean-Reversion Strategy</b>\n"
            f"• Sensex Weekly Options (CE/PE)\n"
            f"• EMA Channel Breakouts (10/20 periods)\n"
            f"• 3-minute cycles: 9:18 AM - 3:15 PM IST\n\n"
            f"🚀 <b>New: Automated Authentication!</b>\n"
            f"   • <code>/auth</code> → Click button → Automatic token refresh\n"
            f"   • No manual request_token copy-paste required!\n"
            f"   • EC2 deployment with .env security\n\n"
            f"⚙️ <b>Current Status:</b>\n"
            f"   • Mode: <b>{self.config.MODE}</b>\n"
            f"   • Token: {token_status}\n"
            f"   • Market: {market_status}\n"
            f"   • Auth Server: <code>{self.auth_url}</code>\n"
            f"   • Lot Size: {self.config.LOT_SIZE}\n\n"
            f"💡 <b>Quick Actions:</b>\n"
            f"   <code>/auth</code> - Get new access token (1-click)\n"
            f"   <code>/status</code> - Full system health\n"
            f"   <code>/mode LIVE</code> - Switch to live trading\n"
            f"   <code>/risk</code> - Risk management overview"
        )
        
        # Quick action buttons
        keyboard = [
            [InlineKeyboardButton("🔐 Get New Token", callback_data="auth")],
            [InlineKeyboardButton("📊 System Status", callback_data="status")],
            [InlineKeyboardButton("⚙️ Change Mode", callback_data="mode")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_message, parse_mode="HTML", reply_markup=reply_markup)
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced /status command with auth server integration."""
        try:
            # Check auth server health
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.auth_url}/health")
                health_data = response.json() if response.status_code == 200 else {}
        except Exception as e:
            logger.warning(f"Auth server status check failed: {e}")
            health_data = {"status": "unreachable"}
        
        # Token validation
        token_status = "✅ Valid"
        if not self.config.ACCESS_TOKEN:
            token_status = "❌ Missing"
        else:
            # Check approximate expiry
            now = datetime.now()
            expiry_approx = now.replace(hour=9, minute=0) + timedelta(days=1)
            hours_left = max(0, (expiry_approx - now).seconds // 3600)
            if hours_left < 3:
                token_status = f"⚠️  Expires in {hours_left}h"
        
        # Server status
        server_status = "✅ Healthy" if health_data.get('status') == 'healthy' else "❌ Unreachable"
        protocol_emoji = "🔒" if self.config.USE_HTTPS else "🔓"
        
        # Market status
        market_status = "🟢 Open" if self.config.is_market_open() else "🔴 Closed"
        if self.config.is_market_holiday():
            market_status = "🏖️ Holiday"
        
        status_message = (
            f"📊 <b>Trading System Status</b>\n\n"
            f"⚙️ <b>Trading Engine:</b>\n"
            f"   • Mode: <b>{self.config.MODE}</b>\n"
            f"   • Token: {token_status}\n"
            f"   • Lot Size: {self.config.LOT_SIZE}\n"
            f"   • Max Trades: {self.config.MAX_DAILY_TRADES}\n\n"
            f"🌐 <b>Auth Server:</b>\n"
            f"   • Status: {server_status}\n"
            f"   • {protocol_emoji} URL: <code>{self.auth_url}</code>\n"
            f"   • Pending Auths: {health_data.get('auth', {}).get('pending_requests', 0)}\n\n"
            f"📈 <b>Market:</b>\n"
            f"   • Status: {market_status}\n"
            f"   • Instrument: SENSEX (Token: {self.config.SENSEX_TOKEN})\n"
            f"   • Next Cycle: {datetime.now().strftime('%H:%M')}\n\n"
            f"🛡️ <b>Risk Limits:</b>\n"
            f"   • Daily Loss Cap: ₹{self.config.DAILY_LOSS_CAP:,}\n"
            f"   • Consecutive Loss Limit: {self.config.CONSECUTIVE_LOSS_LIMIT}"
        )
        
        await update.message.reply_text(status_message, parse_mode="HTML")
    
    async def risk_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Risk management overview."""
        risk_message = (
            f"🛡️ <b>Risk Management Overview</b>\n\n"
            f"⚠️ <b>Daily Limits:</b>\n"
            f"   • Maximum Trades: {self.config.MAX_DAILY_TRADES}\n"
            f"   • Loss Cap: <code>₹{self.config.DAILY_LOSS_CAP:,}</code>\n"
            f"   • Consecutive Loss Halt: {self.config.CONSECUTIVE_LOSS_LIMIT}\n\n"
            f"📊 <b>Position Sizing:</b>\n"
            f"   • Lot Size: {self.config.LOT_SIZE}\n"
            f"   • Position Value: ₹{self.config.POSITION_SIZE:,}\n"
            f"   • Instrument Token: {self.config.SENSEX_TOKEN}\n\n"
            f"🎯 <b>Strategy Parameters:</b>\n"
            f"   • EMA Periods: {self.config.EMA_FAST_PERIOD}/{self.config.EMA_SLOW_PERIOD}\n"
            f"   • Sensex Range Filter: ≤ {self.config.RANGE_THRESHOLD_SENSEX} points\n"
            f"   • Premium Range Filter: ≤ {self.config.RANGE_THRESHOLD_PREMIUM} points\n"
            f"   • Target/Stop Loss: {self.config.TARGET_POINTS}/{self.config.STOP_LOSS_POINTS} points\n\n"
            f"🔒 <b>Protections Active:</b>\n"
            f"   • Auto-halt after {self.config.CONSECUTIVE_LOSS_LIMIT} consecutive losses\n"
            f"   • Daily loss protection: ₹{self.config.DAILY_LOSS_CAP:,} cap\n"
            f"   • Position sizing based on account balance\n"
            f"   • EC2 .env file secured (chmod 600, Git ignored)\n"
            f"   • Atomic token updates with audit trail"
        )
        
        await update.message.reply_text(risk_message, parse_mode="HTML")
    
    async def positions_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Current positions overview."""
        # Your existing positions logic here
        # For now, placeholder implementation
        positions_message = (
            f"📈 <b>Open Positions</b>\n\n"
            f"ℹ️ <b>Position tracking active in:</b>\n"
            f"   • LIVE mode (real positions)\n"
            f"   • TEST mode (virtual positions)\n\n"
            f"⚙️ <b>Current Mode:</b> {self.config.MODE}\n"
            f"💡 <b>To view positions:</b>\n"
            f"   • Switch to LIVE or TEST mode first\n"
            f"   • Use <code>/mode LIVE</code> (requires valid token)\n"
            f"   • Or <code>/mode TEST</code> for simulation\n\n"
            f"📊 <b>When active, shows:</b>\n"
            f"   • Symbol, quantity, average price\n"
            f"   • Current P&L with emoji indicators\n"
            f"   • Total portfolio value and drawdown"
        )
        
        await update.message.reply_text(positions_message, parse_mode="HTML")
    
    # === TRADING NOTIFICATIONS (Your Existing Methods) ===
    
    async def notify_trade_signal(self, signal):
        """Notify about new trading signal."""
        # Your existing signal notification logic
        direction_emoji = "🟢" if signal.get('direction') == 'BUY' else "🔴"
        message = (
            f"📊 <b>New Trading Signal</b>\n\n"
            f"{direction_emoji} <b>{signal.get('direction', 'N/A')}</b>\n"
            f"📈 Symbol: <code>{signal.get('symbol', 'N/A')}</code>\n"
            f"💰 Entry Price: ₹{signal.get('entry_price', 0):,.0f}\n"
            f"🎯 Strike: {signal.get('strike_price', 'N/A')}\n"
            f"⏰ Time: {signal.get('timestamp', datetime.now()).strftime('%H:%M:%S')}\n"
            f"⚙️ Mode: <b>{self.config.MODE}</b>"
        )
        await self._send_message(message)
    
    async def send_alert(self, message: str, parse_mode: str = "HTML"):
        """Send alert message."""
        await self._send_message(message, parse_mode)
