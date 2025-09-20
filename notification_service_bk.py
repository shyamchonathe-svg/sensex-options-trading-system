#!/usr/bin/env python3
"""
Notification Service - Infrastructure Layer for Sensex Trading Bot
Handles all Telegram notifications with structured message templates
"""

import requests
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
import logging
from dataclasses import dataclass
from enum import Enum

from trading_service import TradingSession, Position, TradingMode
from signal_detection_system import TradingSignal, SignalType, OptionType, SignalSource


class NotificationLevel(Enum):
    """Notification priority levels"""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    DEBUG = "debug"
    SIGNAL = "signal"
    TRADE = "trade"


@dataclass
class MessageTemplate:
    """Message template with formatting options"""
    title: str
    body: str
    parse_mode: str = "HTML"
    disable_web_page_preview: bool = True


class NotificationService:
    """
    Handles all notifications via Telegram with structured templates
    """
    
    def __init__(self, telegram_token: str, chat_id: str, config: Dict[str, Any] = None):
        """
        Initialize notification service
        
        Args:
            telegram_token: Telegram bot token
            chat_id: Target chat ID
            config: Notification configuration
        """
        self.logger = logging.getLogger(__name__)
        self.telegram_token = telegram_token
        self.chat_id = chat_id
        self.config = config or {}
        
        # API endpoint
        self.api_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
        
        # Notification settings
        self.enabled_levels = set(self.config.get('enabled_levels', [
            NotificationLevel.ERROR.value,
            NotificationLevel.SIGNAL.value,
            NotificationLevel.TRADE.value,
            NotificationLevel.INFO.value
        ]))
        
        self.max_retries = self.config.get('max_retries', 3)
        self.timeout_seconds = self.config.get('timeout', 10)
        
        self.logger.info(f"NotificationService initialized with levels: {self.enabled_levels}")
    
    def _send_message(self, message: str, parse_mode: str = "HTML", 
                     disable_web_page_preview: bool = True, level: NotificationLevel = NotificationLevel.INFO) -> bool:
        """
        Send message via Telegram API
        
        Args:
            message: Message text
            parse_mode: Telegram parse mode
            disable_web_page_preview: Disable link previews
            level: Notification level
            
        Returns:
            True if sent successfully
        """
        if level.value not in self.enabled_levels:
            self.logger.debug(f"Notification level {level.value} disabled, skipping message")
            return True
        
        payload = {
            'chat_id': self.chat_id,
            'text': message,
            'parse_mode': parse_mode,
            'disable_web_page_preview': disable_web_page_preview
        }
        
        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    self.api_url, 
                    json=payload, 
                    timeout=self.timeout_seconds
                )
                
                if response.status_code == 200:
                    self.logger.debug(f"Message sent successfully (attempt {attempt + 1})")
                    return True
                else:
                    self.logger.warning(f"Telegram API error: {response.status_code} - {response.text}")
                    
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"Telegram request failed (attempt {attempt + 1}): {e}")
                
            if attempt < self.max_retries - 1:
                import time
                time.sleep(2 ** attempt)  # Exponential backoff
        
        self.logger.error(f"Failed to send message after {self.max_retries} attempts")
        return False
    
    def send_session_start(self, session: TradingSession, mode: TradingMode) -> bool:
        """Send trading session start notification"""
        message = (
            f"🚀 <b>Sensex Trading Bot Started</b>\n\n"
            f"📊 <b>Session Details:</b>\n"
            f"   📅 Date: {session.date}\n"
            f"   ⏰ Start Time: {session.start_time.strftime('%H:%M:%S')}\n"
            f"   💼 Mode: {mode.value.upper()}\n"
            f"   💰 Sensex Entry: ₹{session.sensex_entry_price:,.2f}\n\n"
            f"🎯 <b>Strategy:</b> EMA-based Sensex & Option Logic\n"
            f"⏱️ <b>Cycle:</b> Every 3 minutes\n"
            f"📱 <b>Status:</b> Monitoring market conditions..."
        )
        
        return self._send_message(message, level=NotificationLevel.INFO)
    
    def send_session_end(self, session: TradingSession, summary: Dict[str, Any]) -> bool:
        """Send trading session end notification"""
        success_rate = summary.get('success_rate', 0)
        duration = summary.get('duration', 0)
        
        # Format duration
        if hasattr(duration, 'total_seconds'):
            duration_str = f"{duration.total_seconds() / 3600:.1f} hours"
        else:
            duration_str = "N/A"
        
        message = (
            f"🛑 <b>Trading Session Ended</b>\n\n"
            f"📊 <b>Session Summary:</b>\n"
            f"   📅 Date: {session.date}\n"
            f"   ⏱️ Duration: {duration_str}\n"
            f"   📈 Total Signals: {summary.get('total_signals', 0)}\n"
            f"   📊 Positions Opened: {summary.get('positions_opened', 0)}\n"
            f"   ✅ Positions Closed: {summary.get('positions_closed', 0)}\n"
            f"   💰 Total P&L: ₹{summary.get('total_pnl', 0):.2f}\n"
            f"   📊 Success Rate: {success_rate:.1f}%\n"
            f"   ⚠️ Errors: {summary.get('errors', 0)}"
        )
        
        return self._send_message(message, level=NotificationLevel.INFO)
    
    def send_strike_detection(self, sensex_price: float, target_strike: int, 
                            session: str, current_time: datetime) -> bool:
        """Send Step 1: Strike price detection notification"""
        message = (
            f"🎯 <b>Step 1: Strike Price Detection</b>\n\n"
            f"📊 <b>Sensex Spot:</b> ₹{sensex_price:,.2f}\n"
            f"🎯 <b>Target Strike:</b> {target_strike}\n"
            f"📅 <b>Session:</b> {session}\n"
            f"⏰ <b>Time:</b> {current_time.strftime('%H:%M:%S')}\n"
            f"🔍 <b>Logic:</b> {'ATM' if session == 'Morning' else 'ATM-175'}"
        )
        
        return self._send_message(message, level=NotificationLevel.INFO)
    
    def send_option_chain_data(self, option_data: Dict[str, Any], valid_strikes: List[int]) -> bool:
        """Send Step 2: Option chain data notification"""
        message = f"📋 <b>Step 2: Weekly Options Data</b>\n\n"
        
        for strike in sorted(valid_strikes):
            if strike in option_data:
                data = option_data[strike]
                message += (
                    f"🎯 <b>Strike: {strike}</b>\n"
                    f"   📈 CE: <code>{data['ce_symbol']}</code> - ₹{data['ce_price']:,.2f}\n"
                    f"   📉 PE: <code>{data['pe_symbol']}</code> - ₹{data['pe_price']:,.2f}\n\n"
                )
        
        message += f"⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"
        
        return self._send_message(message, level=NotificationLevel.INFO)
    
    def send_signal_analysis(self, signals: List[TradingSignal], sensex_latest: Any,
                           atm_data: Dict[str, Any], target_strike: int) -> bool:
        """Send Step 3: Signal analysis notification"""
        message = f"📊 <b>Step 3: Signal Analysis</b>\n\n"
        
        # ATM Data Summary
        message += (
            f"🎯 <b>ATM Strike: {target_strike}</b>\n"
            f"📈 <b>CE:</b> <code>{atm_data['ce_symbol']}</code> - ₹{atm_data['ce_price']:,.2f}\n"
            f"📉 <b>PE:</b> <code>{atm_data['pe_symbol']}</code> - ₹{atm_data['pe_price']:,.2f}\n"
            f"📊 <b>Sensex:</b> ₹{sensex_latest['close']:,.2f}\n\n"
        )
        
        if signals:
            message += f"✅ <b>Signals Detected: {len(signals)}</b>\n"
            for signal in signals:
                confidence_icon = "🔥" if signal.confidence > 0.9 else "✅" if signal.confidence > 0.7 else "⚡"
                message += (
                    f"   {confidence_icon} {signal.option_type.value} - "
                    f"{signal.source.value.title()} (Confidence: {signal.confidence:.1%})\n"
                )
        else:
            message += "❌ <b>No Valid Signals</b>\n"
        
        message += f"\n⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"
        
        return self._send_message(message, level=NotificationLevel.SIGNAL)
    
    def send_position_opened(self, position: Position, mode: TradingMode, **kwargs) -> bool:
        """Send position opened notification"""
        mode_icon = "🔴" if mode == TradingMode.LIVE else "🟡"
        
        message = (
            f"{mode_icon} <b>Position Opened ({mode.value.upper()})</b>\n\n"
            f"🏷️ <b>Symbol:</b> <code>{position.symbol}</code>\n"
            f"🎯 <b>Type:</b> {position.option_type.value}\n"
            f"💰 <b>Strike:</b> {position.strike}\n"
            f"📈 <b>Entry Price:</b> ₹{position.entry_price:,.2f}\n"
            f"🛡️ <b>Stop Loss:</b> ₹{position.stop_loss:,.2f}\n"
            f"📊 <b>Quantity:</b> {position.quantity}\n"
            f"🎯 <b>Basis:</b> {position.entry_basis.value if hasattr(position.entry_basis, 'value') else position.entry_basis}\n"
            f"⏰ <b>Entry Time:</b> {position.entry_time.strftime('%H:%M:%S')}\n"
            f"🔢 <b>Confidence:</b> {position.metadata.get('confidence', 0):.1%}"
        )
        
        return self._send_message(message, level=NotificationLevel.TRADE)
    
    def send_position_closed(self, position: Position, mode: TradingMode, forced: bool = False, **kwargs) -> bool:
        """Send position closed notification"""
        mode_icon = "🔴" if mode == TradingMode.LIVE else "🟡"
        pnl_icon = "💚" if position.pnl > 0 else "❌" if position.pnl < 0 else "➖"
        forced_text = " (FORCED)" if forced else ""
        
        message = (
            f"{mode_icon} <b>Position Closed ({mode.value.upper()}){forced_text}</b>\n\n"
            f"🏷️ <b>Symbol:</b> <code>{position.symbol}</code>\n"
            f"🎯 <b>Type:</b> {position.option_type.value}\n"
            f"💰 <b>Strike:</b> {position.strike}\n"
            f"📈 <b>Entry:</b> ₹{position.entry_price:,.2f}\n"
            f"📉 <b>Exit:</b> ₹{position.exit_price:,.2f}\n"
            f"🚪 <b>Reason:</b> {position.exit_reason}\n"
            f"⏱️ <b>Duration:</b> {position.candle_count} candles ({position.candle_count * 3} mins)\n"
            f"{pnl_icon} <b>P&L:</b> ₹{position.pnl:,.2f}\n"
            f"📊 <b>Return:</b> {(position.pnl / (position.entry_price * position.quantity) * 100):+.1f}%"
        )
        
        return self._send_message(message, level=NotificationLevel.TRADE)
    
    def send_position_monitoring(self, position: Position, current_data: Any, 
                               exit_signal: Optional[TradingSignal] = None) -> bool:
        """Send position monitoring update"""
        current_price = current_data['close'] if current_data is not None else position.entry_price
        unrealized_pnl = (current_price - position.entry_price) * position.quantity
        pnl_icon = "💚" if unrealized_pnl > 0 else "❌" if unrealized_pnl < 0 else "➖"
        
        message = (
            f"👁️ <b>Position Monitoring</b>\n\n"
            f"🏷️ <b>Symbol:</b> <code>{position.symbol}</code>\n"
            f"💰 <b>Current Price:</b> ₹{current_price:,.2f}\n"
            f"📈 <b>Entry Price:</b> ₹{position.entry_price:,.2f}\n"
            f"🛡️ <b>Stop Loss:</b> ₹{position.stop_loss:,.2f}\n"
            f"🕒 <b>Candles:</b> {position.candle_count}\n"
            f"{pnl_icon} <b>Unrealized P&L:</b> ₹{unrealized_pnl:,.2f}"
        )
        
        if exit_signal and exit_signal.signal_type == SignalType.EXIT:
            message += f"\n\n⚠️ <b>Exit Signal:</b> {exit_signal.metadata.get('exit_reason', 'Unknown')}"
        
        return self._send_message(message, level=NotificationLevel.DEBUG)
    
    def send_signal_debug(self, signal: TradingSignal, signal_type: str = "Entry") -> bool:
        """Send detailed signal debugging information"""
        confidence_icon = "🔥" if signal.confidence > 0.9 else "✅" if signal.confidence > 0.7 else "⚡"
        
        message = (
            f"🔍 <b>{signal_type} Signal Debug - {signal.source.value.title()}</b>\n\n"
            f"🏷️ <b>Symbol:</b> <code>{signal.symbol}</code>\n"
            f"🎯 <b>Type:</b> {signal.option_type.value}\n"
            f"💰 <b>Strike:</b> {signal.strike}\n"
            f"{confidence_icon} <b>Confidence:</b> {signal.confidence:.1%}\n"
            f"💲 <b>Entry Price:</b> ₹{signal.entry_price:,.2f}\n"
            f"🛡️ <b>Stop Loss:</b> ₹{signal.stop_loss:,.2f}\n"
        )
        
        if signal.conditions:
            message += f"\n📋 <b>Conditions Check:</b>\n"
            for condition in signal.conditions:
                status = "✅" if condition.passed else "❌"
                message += f"   {status} {condition.name}: {condition.value}\n"
        
        if signal.metadata:
            message += f"\n📊 <b>Metadata:</b>\n"
            for key, value in signal.metadata.items():
                if isinstance(value, (int, float)):
                    if key.endswith('_price') or key.startswith('ema'):
                        message += f"   {key}: ₹{value:,.2f}\n"
                    else:
                        message += f"   {key}: {value}\n"
                else:
                    message += f"   {key}: {value}\n"
        
        return self._send_message(message, level=NotificationLevel.DEBUG)
    
    def send_error_notification(self, error_type: str, error_message: str, 
                              context: Dict[str, Any] = None) -> bool:
        """Send error notification"""
        message = (
            f"🚨 <b>Error: {error_type}</b>\n\n"
            f"❌ <b>Message:</b> {error_message}\n"
            f"⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"
        )
        
        if context:
            message += f"\n\n📋 <b>Context:</b>\n"
            for key, value in context.items():
                message += f"   {key}: {value}\n"
        
        return self._send_message(message, level=NotificationLevel.ERROR)
    
    def send_data_quality_alert(self, symbol: str, validation_result: Any) -> bool:
        """Send data quality alert"""
        quality_icons = {
            'excellent': '💚',
            'good': '🟢', 
            'acceptable': '🟡',
            'poor': '🟠',
            'unusable': '🔴'
        }
        
        quality = validation_result.quality.value
        icon = quality_icons.get(quality, '❓')
        
        message = (
            f"{icon} <b>Data Quality Alert</b>\n\n"
            f"🏷️ <b>Symbol:</b> <code>{symbol}</code>\n"
            f"📊 <b>Quality:</b> {quality.title()}\n"
            f"📈 <b>Rows:</b> {validation_result.total_rows}/{validation_result.expected_rows}\n"
            f"📉 <b>Missing:</b> {validation_result.missing_percentage:.1f}%\n"
            f"🔍 <b>Gaps:</b> {validation_result.gap_count}"
        )
        
        if validation_result.issues:
            message += f"\n\n⚠️ <b>Issues:</b>\n"
            for issue in validation_result.issues[:3]:  # Limit to first 3 issues
                message += f"   • {issue}\n"
        
        if validation_result.recommendations:
            message += f"\n💡 <b>Recommendations:</b>\n"
            for rec in validation_result.recommendations[:2]:  # Limit to first 2 recommendations
                message += f"   • {rec}\n"
        
        return self._send_message(message, level=NotificationLevel.WARNING)
    
    def send_cycle_performance(self, cycle_results: Dict[str, Any]) -> bool:
        """Send trading cycle performance notification"""
        step_icons = {
            True: "✅",
            False: "❌"
        }
        
        message = (
            f"⏱️ <b>Cycle Performance</b>\n\n"
            f"🕐 <b>Time:</b> {cycle_results.get('timestamp', 'N/A')}\n"
            f"⏱️ <b>Duration:</b> {cycle_results.get('cycle_duration_seconds', 0):.1f}s\n"
            f"{step_icons.get(cycle_results.get('step1_completed', False))} <b>Step 1:</b> Strike Detection\n"
            f"{step_icons.get(cycle_results.get('step2_completed', False))} <b>Step 2:</b> Option Data\n"
            f"{step_icons.get(cycle_results.get('step3_completed', False))} <b>Step 3:</b> Signal Analysis\n"
            f"📊 <b>Signals:</b> {cycle_results.get('signals_detected', 0)}\n"
            f"🔄 <b>Position Changes:</b> {'Yes' if cycle_results.get('positions_changed') else 'No'}"
        )
        
        if cycle_results.get('errors'):
            message += f"\n\n⚠️ <b>Errors:</b>\n"
            for error in cycle_results['errors'][:2]:  # Limit to first 2 errors
                message += f"   • {error}\n"
        
        return self._send_message(message, level=NotificationLevel.DEBUG)
    
    def send_market_data_initialized(self, date: str, symbols_count: int, 
                                   strikes: List[int]) -> bool:
        """Send market data initialization notification"""
        message = (
            f"📂 <b>Market Data Initialized</b>\n\n"
            f"📅 <b>Date:</b> {date}\n"
            f"📊 <b>Symbols:</b> {symbols_count} instruments\n"
            f"🎯 <b>Strike Range:</b> {min(strikes)} - {max(strikes)}\n"
            f"⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}\n"
            f"✅ <b>Status:</b> Ready for trading"
        )
        
        return self._send_message(message, level=NotificationLevel.INFO)
    
    def send_custom_message(self, title: str, content: str, 
                          level: NotificationLevel = NotificationLevel.INFO) -> bool:
        """Send custom formatted message"""
        message = f"📢 <b>{title}</b>\n\n{content}"
        return self._send_message(message, level=level)
    
    def send_heartbeat(self, status: Dict[str, Any]) -> bool:
        """Send periodic heartbeat with system status"""
        uptime_icon = "💚" if status.get('session_active') else "🟡"
        position_icon = "📈" if status.get('position_active') else "⏸️"
        
        message = (
            f"💓 <b>System Heartbeat</b>\n\n"
            f"{uptime_icon} <b>Session:</b> {'Active' if status.get('session_active') else 'Inactive'}\n"
            f"{position_icon} <b>Position:</b> {'Open' if status.get('position_active') else 'None'}\n"
            f"🔧 <b>Mode:</b> {status.get('mode', 'Unknown').upper()}\n"
            f"⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"
        )
        
        if status.get('session'):
            session = status['session']
            message += (
                f"\n\n📊 <b>Session Stats:</b>\n"
                f"   Signals: {session.get('total_signals', 0)}\n"
                f"   Opened: {session.get('positions_opened', 0)}\n"
                f"   Closed: {session.get('positions_closed', 0)}\n"
                f"   P&L: ₹{session.get('total_pnl', 0):,.2f}"
            )
        
        return self._send_message(message, level=NotificationLevel.DEBUG)
    
    def send_configuration_update(self, config_changes: Dict[str, Any]) -> bool:
        """Send configuration update notification"""
        message = (
            f"⚙️ <b>Configuration Updated</b>\n\n"
            f"🔄 <b>Changes Applied:</b>\n"
        )
        
        for key, value in config_changes.items():
            message += f"   • {key}: {value}\n"
        
        message += f"\n⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"
        
        return self._send_message(message, level=NotificationLevel.INFO)
    
    def test_connection(self) -> bool:
        """Test Telegram connection"""
        test_message = (
            f"🔧 <b>Connection Test</b>\n\n"
            f"✅ Telegram API is working correctly\n"
            f"⏰ Test Time: {datetime.now().strftime('%H:%M:%S')}\n"
            f"🤖 Bot Token: ...{self.telegram_token[-8:]}\n"
            f"💬 Chat ID: {self.chat_id}"
        )
        
        return self._send_message(test_message, level=NotificationLevel.DEBUG)
    
    def get_notification_stats(self) -> Dict[str, Any]:
        """Get notification service statistics"""
        return {
            'enabled_levels': list(self.enabled_levels),
            'max_retries': self.max_retries,
            'timeout_seconds': self.timeout_seconds,
            'telegram_token_length': len(self.telegram_token),
            'chat_id': self.chat_id,
            'api_url': self.api_url
        }
