#!/usr/bin/env python3
"""
Telegram Notification Service for Trading System
Handles all trading alerts and status updates
"""
import httpx
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class NotificationService:
    """Handles all Telegram notifications for the trading system."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.telegram_token = config.get("TELEGRAM_TOKEN", "")
        self.chat_id = config.get("TELEGRAM_CHAT_ID", "")
        self.enabled = config.get("ENABLE_NOTIFICATIONS", True)
        self.base_url = f"https://api.telegram.org/bot{self.telegram_token}"
        
        if self.enabled and self.telegram_token and self.chat_id:
            logger.info("📱 Telegram notifications enabled")
        else:
            logger.warning("⚠️  Telegram notifications disabled")
    
    async def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send message to Telegram."""
        if not self.enabled:
            logger.debug(f"[NOTIFICATION] {message[:100]}...")
            return True
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": message,
                        "parse_mode": parse_mode
                    }
                )
                
                if response.status_code == 200:
                    logger.info("📱 Telegram message sent successfully")
                    return True
                else:
                    logger.error(f"❌ Telegram API error: {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Telegram notification failed: {e}")
            return False
    
    async def send_trade_alert(self, trade_data: Dict[str, Any], mode: str) -> bool:
        """Send detailed trade alert."""
        mode_emoji = {"TEST": "🧪", "PAPER": "📝", "LIVE": "🔴"}.get(mode, "⚙️")
        
        if trade_data.get("action") == "ENTRY":
            message = (
                f"{mode_emoji} <b>{mode} MODE - TRADE ENTRY</b>\n\n"
                f"📈 <b>Signal:</b> {trade_data.get('signal', 'N/A')}\n"
                f"🎯 <b>Symbol:</b> <code>{trade_data.get('symbol', 'N/A')}</code>\n"
                f"📊 <b>Side:</b> {trade_data.get('side', 'N/A').upper()}\n"
                f"📏 <b>Quantity:</b> {trade_data.get('quantity', 0)}\n"
                f"💰 <b>Entry Price:</b> ₹{trade_data.get('price', 0):,.2f}\n"
                f"⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S IST')}\n"
                f"📉 <b>Sensex:</b> {trade_data.get('sensex_price', 0):,.0f}\n\n"
                f"{'🔴 LIVE ORDER' if mode == 'LIVE' else f'{mode_emoji} SIMULATED'}\n"
                f"⚙️ <b>Risk:</b> {trade_data.get('risk_amount', 0):,.0f} ({trade_data.get('risk_percent', 0):.1f}%)\n"
                f"🛡️ <b>SL:</b> ₹{trade_data.get('stop_loss', 0):,.2f} | <b>TP:</b> ₹{trade_data.get('take_profit', 0):,.2f}"
            )
            
        elif trade_data.get("action") == "EXIT":
            pnl = trade_data.get("pnl", 0)
            pnl_emoji = "🟢" if pnl > 0 else "🔴"
            pnl_color = "🟢" if pnl > 0 else "🔴"
            
            message = (
                f"{mode_emoji} <b>{mode} MODE - TRADE EXIT</b>\n\n"
                f"🎯 <b>Symbol:</b> <code>{trade_data.get('symbol', 'N/A')}</code>\n"
                f"📊 <b>Side:</b> {trade_data.get('side', 'N/A').upper()}\n"
                f"💰 <b>P&L:</b> {pnl_emoji} ₹{pnl:,.0f}\n"
                f"📏 <b>Quantity:</b> {trade_data.get('quantity', 0)}\n"
                f"💵 <b>Exit Price:</b> ₹{trade_data.get('exit_price', 0):,.2f}\n"
                f"⏰ <b>Exit Time:</b> {datetime.now().strftime('%H:%M:%S IST')}\n"
                f"📉 <b>Reason:</b> {trade_data.get('exit_reason', 'N/A')}\n\n"
                f"📊 <b>Daily Summary:</b>\n"
                f"   • Trades: {trade_data.get('trades_today', 0)}\n"
                f"   • Win Rate: {trade_data.get('win_rate', 0):.1f}%\n"
                f"   • Total P&L: ₹{trade_data.get('daily_pnl', 0):,.0f}"
            )
        
        else:
            return False
        
        return await self.send_message(message)
    
    async def send_system_alert(self, alert_data: Dict[str, Any]) -> bool:
        """Send system status alerts."""
        alert_type = alert_data.get("type", "INFO")
        emoji = {"ERROR": "🚨", "WARNING": "⚠️", "INFO": "ℹ️", "SUCCESS": "✅"}.get(alert_type, "ℹ️")
        
        message = (
            f"{emoji} <b>SYSTEM {alert_type.upper()}</b>\n\n"
            f"⚙️ <b>Component:</b> {alert_data.get('component', 'System')}\n"
            f"💥 <b>Message:</b> {alert_data.get('message', 'N/A')}\n"
            f"⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S IST')}\n"
            f"📊 <b>Mode:</b> {alert_data.get('mode', 'N/A')}\n"
            f"🔧 <b>Action:</b> {alert_data.get('action', 'N/A')}"
        )
        
        return await self.send_message(message)
    
    async def send_daily_summary(self, summary: Dict[str, Any]) -> bool:
        """Send end-of-day summary."""
        mode_emoji = {"TEST": "🧪", "PAPER": "📝", "LIVE": "🔴"}.get(summary.get("mode", "TEST"), "⚙️")
        daily_pnl = summary.get("daily_pnl", 0)
        pnl_emoji = "🟢" if daily_pnl > 0 else "🔴" if daily_pnl < 0 else "🟡"
        
        message = (
            f"{mode_emoji} <b>DAILY TRADING SUMMARY</b>\n\n"
            f"📅 <b>Date:</b> {summary.get('date', 'N/A')}\n"
            f"⚙️ <b>Mode:</b> {summary.get('mode', 'N/A').upper()}\n"
            f"{pnl_emoji} <b>Daily P&L:</b> ₹{daily_pnl:,.0f}\n\n"
            f"📊 <b>Trading Stats:</b>\n"
            f"   • Total Trades: {summary.get('total_trades', 0)}\n"
            f"   • Winning Trades: {summary.get('winning_trades', 0)}\n"
            f"   • Win Rate: {summary.get('win_rate', 0):.1f}%\n"
            f"   • Avg P&L/Trade: ₹{summary.get('avg_pnl', 0):,.0f}\n"
            f"   • SL Hits: {summary.get('sl_hits', 0)}\n\n"
            f"🛡️ <b>Risk Status:</b>\n"
            f"   • Max Loss Reached: {'YES' if summary.get('max_loss', False) else 'NO'}\n"
            f"   • Trading Allowed: {'YES' if summary.get('trading_allowed', False) else 'NO'}\n"
            f"   • Risk Level: {summary.get('risk_level', 'LOW')}\n\n"
            f"{'🎉 PROFITABLE DAY!' if daily_pnl > 0 else '📉 LOSS DAY - REVIEW STRATEGY'}"
        )
        
        return await self.send_message(message)
    
    async def send_mode_status(self, mode_config: Dict[str, Any]) -> bool:
        """Send current mode status."""
        mode = mode_config.get("mode", "TEST")
        mode_emoji = {"TEST": "🧪", "PAPER": "📝", "LIVE": "🔴"}.get(mode, "⚙️")
        
        message = (
            f"{mode_emoji} <b>TRADING MODE ACTIVE</b>\n\n"
            f"⚙️ <b>Current Mode:</b> <b>{mode.upper()}</b>\n"
            f"🌐 <b>Server:</b> {mode_config.get('host')}:{mode_config.get('port')}\n"
            f"🔒 <b>Protocol:</b> {'HTTPS' if mode_config.get('https') else 'HTTP'}\n"
            f"📊 <b>Max Trades:</b> {mode_config.get('max_trades', 3)}/day\n"
            f"💰 <b>Risk/Trade:</b> {mode_config.get('risk_per_trade', 0.01)*100:.1f}%\n"
            f"🛡️ <b>Real Orders:</b> {'ENABLED ⚠️' if mode_config.get('allow_real_orders', False) else 'DISABLED ✅'}\n"
            f"📱 <b>Notifications:</b> {'ON' if mode_config.get('enable_notifications', True) else 'OFF'}\n\n"
            f"{mode_config.get('mode_description', '')}"
        )
        
        return await self.send_message(message)
