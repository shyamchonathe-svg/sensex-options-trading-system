#!/usr/bin/env python3
"""
Clean notification module
"""
import logging
from telegram_handler import TelegramBotHandler
from utils.secure_config_manager import SecureConfigManager

logger = logging.getLogger(__name__)

class NotificationService:
    """Simple notification service"""
    
    def __init__(self):
        try:
            config_manager = SecureConfigManager()
            config = config_manager.get_all()
            self.token = config['telegram_token']
            self.chat_id = config['telegram_chat_id']
            self.bot = TelegramBotHandler(config)
        except Exception as e:
            logger.error(f"Failed to initialize notification service: {e}")
            raise
    
    def send(self, message):
        """Send message synchronously"""
        try:
            self.bot.send_telegram_message(message)
            logger.info("Notification sent successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False
    
    async def send_async(self, message):
        """Send message asynchronously"""
        try:
            self.bot.send_telegram_message(message)
            logger.info("Notification sent successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False
    
    async def send_message(self, message):
        """Alias for send_async"""
        return await self.send_async(message)
    
    async def send_session_start(self, session: dict, mode):
        """Send session start notification"""
        message = f"""
📈 <b>Trading Session Started</b>
Session ID: {session['session_id']}
Mode: {mode.value}
Time: {session['start_time'].strftime('%Y-%m-%d %H:%M:%S')}
        """
        return await self.send_async(message)
    
    async def send_session_end(self, session: dict, summary: dict):
        """Send session end notification"""
        message = f"""
🛑 <b>Trading Session Ended</b>
Session ID: {session['session_id']}
Date: {summary['date']}
Duration: {str(summary['duration'])}
Total Signals: {summary['total_signals']}
Positions Opened: {summary['positions_opened']}
Positions Closed: {summary['positions_closed']}
Total P&L: ₹{summary['total_pnl']:.2f}
Success Rate: {summary['success_rate']:.2f}%
        """
        return await self.send_async(message)
    
    async def send_position_opened(self, position: dict, mode):
        """Send position opened notification"""
        message = f"""
📊 <b>Position Opened</b>
Symbol: {position['symbol']}
Strike: {position['strike']}
Entry Price: ₹{position['entry_price']:.2f}
Quantity: {position['quantity']}
Mode: {mode.value}
Time: {position['entry_time'].strftime('%Y-%m-%d %H:%M:%S')}
        """
        return await self.send_async(message)
    
    async def send_system_alert(self, alert: dict):
        """Send system alert"""
        message = f"""
🚨 <b>System Alert</b>
Type: {alert.get('type', 'UNKNOWN')}
Component: {alert.get('component', 'UNKNOWN')}
Message: {alert.get('message', 'No message')}
Mode: {alert.get('mode', 'UNKNOWN')}
        """
        return await self.send_async(message)
    
    async def send_daily_summary(self, summary: dict):
        """Send daily summary"""
        message = f"""
📊 <b>Daily Trading Summary</b>
Mode: {summary.get('mode', 'UNKNOWN')}
Date: {summary.get('date', 'UNKNOWN')}
Daily P&L: ₹{summary.get('daily_pnl', 0):.2f}
Total Trades: {summary.get('total_trades', 0)}
Winning Trades: {summary.get('winning_trades', 0)}
Win Rate: {summary.get('win_rate', 0):.2f}%
Avg P&L: ₹{summary.get('avg_pnl', 0):.2f}
SL Hits: {summary.get('sl_hits', 0)}
Max Loss Exceeded: {summary.get('max_loss', False)}
Trading Allowed: {summary.get('trading_allowed', True)}
Risk Level: {summary.get('risk_level', 'UNKNOWN')}
        """
        return await self.send_async(message)

# Global instance
_service = None

def get_service():
    global _service
    if _service is None:
        _service = NotificationService()
    return _service

def send_telegram_message(message):
    """Send telegram message"""
    try:
        return get_service().send(message)
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        return False
