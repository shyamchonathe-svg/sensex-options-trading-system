#!/usr/bin/env python3
"""
Persistent Trading Bot - 24/7 Telegram-Controlled Orchestrator
YOUR DESIGN: Full phone control, auto-token, market timing, mode switching
"""

import asyncio
import logging
from datetime import datetime, timedelta
import pytz
import os
from typing import Dict, Any, Optional
from telegram import Bot
from .ext import Application, CommandHandler
from config_manager import SecureConfigManager as ConfigManager
from notification_service import NotificationService
from trading_service import EnhancedTradingService
from risk_manager import RiskManager
from utils.data_manager import DataManager
from database_layer import DatabaseLayer
from data_archive_manager import DataArchiveManager
from signal_detection_system import SignalOrchestrator
from optimized_sensex_option_chain import OptimizedSensexOptionChain


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s IST - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/persistent_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PersistentTradingBot:
    """
    YOUR DESIGN IMPLEMENTED: 24/7 Telegram-Controlled Trading System
    - Daily 9:00 AM auto-token refresh via phone link
    - 9:15 AM auto-resume for TEST/LIVE modes
    - /test /live /debug /stop - Full phone control
    - 3:25 PM auto force-close, 3:30 PM auto-pause
    - DEBUG mode 24/7 token-optional
    - /trade_summary - Daily statistics via Telegram
    """
    
    def __init__(self):
        self.logger = logger
        self.config_manager = ConfigManager()
        self.config = self.config_manager.get_config()
        
        # Services
        self.notification_service = None
        self.trading_service = None
        self.risk_manager = None
        self.data_manager = None
        self.database_layer = DatabaseLayer('trades.db')
        self.data_archive_manager = None
        self.option_chain = None
        self.signal_orchestrator = None
        
        # Bot
        self.telegram_bot = None
        self.application = None
        
        # State Management
        self.current_mode = 'stopped'  # test, live, debug, stopped
        self.is_running = False
        self.trading_active = False  # 9:15 AM - 3:30 PM only
        self.ist = pytz.timezone('Asia/Kolkata')
        
        # Daily tracking
        self.daily_start_time = None
        self.session_pnl = 0.0
        self.trades_today = 0
        
        self.logger.info("PersistentTradingBot initialized - Full Telegram control ready")

    async def initialize_services(self):
        """Initialize all services for 24/7 operation"""
        try:
            # Core services
            self.notification_service = NotificationService(
                self.config['telegram_token'],
                self.config['chat_id'],
                self.logger
            )
            
            # Data and trading
            self.data_manager = DataManager(self.config_manager)
            self.option_chain = OptimizedSensexOptionChain(
                self.config['api_key'],
                self.config['access_token']
            )
            self.signal_orchestrator = SignalOrchestrator(
                self.config.get('signal_config', {})
            )
            self.data_archive_manager = DataArchiveManager(
                self.config_manager, 
                self.signal_orchestrator
            )
            
            # Trading and risk
            self.risk_manager = RiskManager(
                self.config, 
                self.database_layer, 
                self.notification_service
            )
            self.trading_service = EnhancedTradingService(
                self.data_manager, 
                None,  # Broker adapter (mode-specific)
                self.notification_service,
                self.config_manager,
                self.database_layer
            )
            
            # Telegram application
            self.application = Application.builder().token(self.config['telegram_token']).build()
            
            # Register ALL command handlers
            self._register_command_handlers()
            
            self.logger.info("✅ All services initialized - 24/7 operation ready")
            
        except Exception as e:
            self.logger.error(f"❌ Service initialization failed: {e}")
            raise

    def _register_command_handlers(self):
        """Register all Telegram command handlers"""
        # System control
        self.application.add_handler(CommandHandler('start', self._start_command))
        self.application.add_handler(CommandHandler('help', self._help_command))
        self.application.add_handler(CommandHandler('status', self._status_command))
        self.application.add_handler(CommandHandler('health', self._health_command))
        self.application.add_handler(CommandHandler('risk', self._trade_summary_command))  # Your /trade_summary
        self.application.add_handler(CommandHandler('balance', self._balance_command))
        self.application.add_handler(CommandHandler('token', self._token_command))
        
        # Mode control (YOUR CORE DESIGN)
        self.application.add_handler(CommandHandler('test', self._test_command))
        self.application.add_handler(CommandHandler('live', self._live_command))
        self.application.add_handler(CommandHandler('debug', self._debug_command))
        self.application.add_handler(CommandHandler('stop', self._stop_command))
        
        # Emergency
        self.application.add_handler(CommandHandler('emergency_stop', self._emergency_stop_command))
        self.application.add_handler(CommandHandler('force_close', self._force_close_command))
        
        # Debug sub-commands
        self.application.add_handler(CommandHandler('debug_list', self._debug_list_command))
        self.application.add_handler(CommandHandler('debug_replay', self._debug_replay_command))
        self.application.add_handler(CommandHandler('debug_summary', self._debug_summary_command))

    async def start(self):
        """Start persistent 24/7 bot - YOUR DESIGN IMPLEMENTED"""
        try:
            self.logger.info("🚀 Starting Persistent Trading Bot - 24/7 Telegram Control")
            
            # Initialize services
            await self.initialize_services()
            
            # Start Telegram bot
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(drop_pending_updates=True)
            
            # Start background tasks - YOUR DAILY AUTO-FLOW
            asyncio.create_task(self._daily_auto_routine())  # 9:00 AM token + reset
            asyncio.create_task(self._market_timing_routine())  # 9:15 AM resume, 3:25 PM close
            
            # Send startup confirmation
            await self._send_startup_confirmation()
            
            self.logger.info("✅ Persistent Bot Fully Operational - Phone Control Active")
            
            # Main loop - keep bot alive 24/7
            while True:
                await asyncio.sleep(60)  # 1-minute heartbeat
                
        except KeyboardInterrupt:
            self.logger.info("👋 Bot interrupted by user - graceful shutdown")
        except Exception as e:
            self.logger.critical(f"💥 BOT CRASHED: {e}")
            await self.notification_service.send_message(f"💥 <b>CRITICAL BOT CRASH</b>\n{str(e)}")
        finally:
            await self._graceful_shutdown()

    async def _daily_auto_routine(self):
        """Daily 9:00 AM auto-token refresh + risk reset"""
        self.logger.info("🔄 Daily auto-routine started - 9:00 AM token refresh")
        
        while True:
            try:
                now = datetime.now(self.ist)
                
                # 9:00 AM - Daily token check + risk reset
                if now.hour == 9 and now.minute == 0:
                    self.logger.info("🕐 9:00 AM - Starting daily routine")
                    
                    # Auto-token refresh (if needed)
                    token_status = await self._check_token_and_refresh()
                    if token_status['refreshed']:
                        await self.notification_service.send_message(
                            f"✅ <b>Daily Token Refreshed - 9:00 AM</b>\n"
                            f"⏱️ Valid until: {token_status['expires_at']}\n"
                            f"🚀 Ready for 9:15 AM market open"
                        )
                    
                    # Daily risk reset
                    await self.risk_manager._check_daily_reset()
                    await self.notification_service.send_message(
                        f"🔄 <b>Daily Risk Reset - 9:00 AM</b>\n"
                        f"📊 Counters cleared: 0/{self.config['max_daily_trades']} trades\n"
                        f"🛡️ Ready for new trading day"
                    )
                
                await asyncio.sleep(60)  # Check every minute
                
            except Exception as e:
                self.logger.error(f"Daily routine error: {e}")
                await asyncio.sleep(300)  # 5-minute retry on error

    async def _market_timing_routine(self):
        """Market timing - auto-resume/pause trading windows"""
        self.logger.info("📈 Market timing started - 9:15 AM resume, 3:25 PM close")
        
        while True:
            try:
                now = datetime.now(self.ist)
                
                if now.weekday() < 5:  # Mon-Fri only
                    
                    # 9:15 AM - Market open, auto-resume TEST/LIVE
                    if (now.hour == 9 and now.minute == 15 and 
                        self.current_mode in ['test', 'live'] and 
                        not self.trading_active):
                        
                        await self._resume_trading()
                        await self.notification_service.send_message(
                            f"📈 <b>MARKET OPEN - 9:15 AM</b>\n"
                            f"🚀 {self.current_mode.upper()} mode resumed\n"
                            f"🔄 3-minute signal detection active"
                        )
                    
                    # 3:25 PM - Force close all positions (TEST/LIVE)
                    if (now.hour == 15 and now.minute == 25 and 
                        self.trading_active and self.current_mode in ['test', 'live']):
                        
                        await self._force_close_all_positions()
                        await self.notification_service.send_message(
                            f"🛑 <b>3:25 PM AUTO-CLOSE ACTIVE</b>\n"
                            f"📊 Force closing all {self.current_mode.upper()} positions\n"
                            f"⏰ Final summary at 3:45 PM"
                        )
                    
                    # 3:30 PM - Market close, auto-pause + send summary
                    if (now.hour == 15 and now.minute == 30 and 
                        self.trading_active and self.current_mode in ['test', 'live']):
                        
                        await self._pause_trading_and_summarize()
                        self.trading_active = False
                        await self.notification_service.send_message(
                            f"📊 <b>MARKET CLOSE - 3:30 PM</b>\n"
                            f"🛑 {self.current_mode.upper()} mode paused\n"
                            f"⏰ Auto-resume tomorrow 9:15 AM\n"
                            f"🔍 Use /debug for after-hours analysis"
                        )
                
                await asyncio.sleep(60)  # Check every minute
                
            except Exception as e:
                self.logger.error(f"Market timing error: {e}")
                await asyncio.sleep(300)  # 5-min retry

    async def _resume_trading(self):
        """Resume trading at 9:15 AM market open"""
        try:
            if self.current_mode in ['test', 'live'] and not self.trading_active:
                await self.trading_service.resume_trading()
                self.trading_active = True
                self.logger.info(f"📈 Trading resumed - {self.current_mode} mode")
        except Exception as e:
            self.logger.error(f"Resume trading error: {e}")

    async def _force_close_all_positions(self):
        """Force close at 3:25 PM"""
        try:
            if self.current_mode in ['test', 'live'] and self.trading_active:
                await self.trading_service.force_close_all_positions()
                self.logger.info("🛑 3:25 PM force-close completed")
        except Exception as e:
            self.logger.error(f"Force close error: {e}")

    async def _pause_trading_and_summarize(self):
        """Pause at 3:30 PM and send daily summary"""
        try:
            if self.current_mode in ['test', 'live'] and self.trading_active:
                # Pause trading
                await self.trading_service.pause_trading()
                self.trading_active = False
                
                # Generate summary
                summary = await self.trading_service.generate_session_summary()
                await self.notification_service.send_trade_summary(summary)
                
                self.logger.info("📊 3:30 PM - Trading paused + summary sent")
        except Exception as e:
            self.logger.error(f"Pause/summary error: {e}")

    async def _check_token_and_refresh(self) -> Dict[str, Any]:
        """Check token and auto-refresh if needed"""
        try:
            token_status = await self.token_manager.check_validity()
            
            if token_status['valid'] and token_status['remaining_minutes'] > 360:
                return token_status  # >6h remaining - good
            
            # Token needs refresh - send link to YOUR PHONE ONLY
            auth_url = await self.token_manager.generate_auth_url()
            if not auth_url:
                return {'valid': False, 'error': 'Postback server unavailable'}
            
            # Send to your specific chat_id
            await self.notification_service.send_message(
                chat_id=self.config['chat_id'],  # YOUR CHAT ONLY
                message=f"""
🔄 <b>Token Refresh Required</b>

⏰ Current token expires in {token_status['remaining_minutes']} minutes
🔗 <a href='{auth_url}'>Click to refresh (30 seconds)</a>

📋 <b>Process:</b>
1. Click link (opens Zerodha login)
2. Username + password + 2FA
3. "Authentication Successful" page
4. Bot auto-saves token
5. Trading continues automatically

⏱️ <b>New token valid:</b> 24 hours (until tomorrow 3:30 PM)
⚠️ <b>Required for:</b> TEST/LIVE modes (DEBUG works offline)
                """,
                parse_mode='HTML',
                disable_web_page_preview=False
            )
            
            # Wait for postback completion
            new_token = await self.token_manager.wait_for_postback(300)  # 5 min timeout
            if new_token:
                await self.token_manager.save_token(new_token)
                expires_at = (datetime.now(self.ist) + timedelta(hours=24)).strftime('%H:%M %Y-%m-%d')
                
                await self.notification_service.send_message(
                    self.config['chat_id'],
                    f"""
✅ <b>Token Refreshed Successfully</b>

⏱️ <b>New Token:</b> Valid until {expires_at}
🚀 <b>System Ready</b> - Trading continues automatically

📊 <b>Next Events:</b>
• 9:15 AM: Market open (if TEST/LIVE mode)
• 3:25 PM: Auto force-close (if trading)
• 3:30 PM: Market close + daily summary

💡 <b>Phone Control Active:</b>
/test /live /debug /stop /status /risk available 24/7
                    """,
                    parse_mode='HTML'
                )
                
                return {
                    'valid': True,
                    'refreshed': True,
                    'remaining_minutes': 1440,  # 24 hours
                    'expires_at': expires_at
                }
            else:
                await self.notification_service.send_message(
                    self.config['chat_id'],
                    f"❌ <b>Token Refresh Timeout</b>\n\n"
                    f"⏰ Waited 5 minutes - no postback received\n"
                    f"💡 <b>Manual Recovery:</b>\n"
                    f"• SSH to EC2: <code>ssh ubuntu@your-ec2</code>\n"
                    f"• Run: <code>python3 debug_token_generator.py</code>\n"
                    f"• Copy ACCESS_TOKEN to .env\n"
                    f"• Restart: <code>sudo systemctl restart persistent_bot.service</code>\n\n"
                    f"⚠️ <b>DEBUG mode still works</b> (token-optional)"
                )
                return {'valid': False, 'error': 'Timeout - manual recovery needed'}
                
        except Exception as e:
            self.logger.error(f"Token refresh error: {e}")
            return {'valid': False, 'error': str(e)}

    async def _graceful_shutdown(self):
        """Graceful shutdown sequence"""
        try:
            if self.is_running:
                await self.stop_trading()
            
            await self.notification_service.send_message(
                f"🛑 <b>PERSISTENT BOT SHUTDOWN</b>\n"
                f"⏰ {datetime.now(self.ist).strftime('%H:%M:%S IST')}\n"
                f"📊 Final Mode: {self.current_mode.upper()}\n"
                f"🔑 Token Status: {'Valid' if await self._check_token_validity() else 'Expired'}\n\n"
                f"💡 <b>To Restart:</b>\n"
                f"• Systemd: <code>sudo systemctl restart persistent_bot.service</code>\n"
                f"• Manual: <code>python3 persistent_bot.py</code>\n\n"
                f"📞 <b>Contact:</b> For emergency recovery assistance"
            )
            
            if self.application:
                await self.application.stop()
                await self.application.shutdown()
                
            self.logger.info("✅ Graceful shutdown complete")
            
        except Exception as e:
            self.logger.error(f"Shutdown error: {e}")

    # ... [All other methods from previous implementations] ...
    # Command handlers (_start_command, _help_command, etc.) remain the same


async def main():
    """Main entry point - Start persistent bot"""
    bot = PersistentTradingBot()
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("👋 Interrupted by user")
    except Exception as e:
        logger.critical(f"💥 CRITICAL STARTUP ERROR: {e}")
    finally:
        await bot._graceful_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
