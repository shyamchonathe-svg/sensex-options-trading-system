#!/usr/bin/env python3
"""
Complete Risk Manager - Implements ALL your exact trading rules
3 trades max/day, halt after 2 SL hits, balance checking, dynamic sizing
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timedelta
import pytz
from dataclasses import dataclass
from enum import Enum
import json

# Local imports
from database_layer import DatabaseLayer
from notification_service import NotificationService
from config_manager import SecureConfigManager as ConfigManager
from kiteconnect import KiteConnect


class PositionStatus(Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


@dataclass
class Position:
    """Dataclass for position tracking"""
    symbol: str
    quantity: int
    entry_price: float
    entry_time: datetime
    strike: Optional[int] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    status: PositionStatus = PositionStatus.OPEN
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: Optional[str] = None
    pnl: float = 0.0
    risk_trade_number: Optional[int] = None
    risk_consecutive_losses: Optional[int] = None
    risk_session_pnl: Optional[float] = None
    risk_remaining_trades: Optional[int] = None


class RiskManager:
    def __init__(self, config: Dict[str, Any], database_layer: DatabaseLayer, 
                 notification_service: NotificationService):
        self.config = config
        self.database_layer = database_layer
        self.notification_service = notification_service
        self.logger = logging.getLogger(__name__)
        
        # YOUR EXACT RISK RULES
        self.max_daily_trades = self.config.get('max_daily_trades', 3)
        self.max_consecutive_losses = self.config.get('max_consecutive_losses', 2)
        self.max_daily_loss = self.config.get('max_daily_loss', -25000)
        self.max_exposure = self.config.get('max_exposure', 100000)
        self.min_balance_per_trade = self.config.get('min_balance_per_trade', 50000)
        self.min_lot_size = self.config.get('min_lot_size', 20)  # 1 lot minimum
        
        # Daily tracking - resets at market open
        self.trades_today = 0
        self.consecutive_losses = 0
        self.daily_pnl = 0.0
        self.current_positions_value = 0.0
        self.last_reset_date = None
        self.trading_halted = False
        
        # Timezone for market hours
        self.ist = pytz.timezone('Asia/Kolkata')
        
        # KiteConnect for balance checking (LIVE MODE ONLY)
        self.kite = None
        if not self.config.get('test_mode', False):
            self.kite = KiteConnect(api_key=config.get('api_key', ''))
            if config.get('access_token'):
                self.kite.set_access_token(config['access_token'])
        
        # Balance cache
        self._kite_balance_cache = None
        self._last_balance_check = None
        
        # Initialize from database
        asyncio.create_task(self._initialize_from_db())
        
        self.logger.info(f"""
🔒 RiskManager Initialized - YOUR RULES:
📊 Max {self.max_daily_trades} trades per day
🛑 Halt after {self.max_consecutive_losses} SL hits
💰 Max daily loss: ₹{self.max_daily_loss}
📈 Max exposure: ₹{self.max_exposure}
💳 Min balance per trade: ₹{self.min_balance_per_trade}
🧪 Test mode: {self.config.get('test_mode', False)}
        """)

    async def _initialize_from_db(self):
        """Load current session state from database"""
        try:
            # Get last reset date
            last_reset = await self.database_layer.get_last_risk_reset()
            self.last_reset_date = last_reset
            
            # Get today's trades
            today = datetime.now(self.ist).date().isoformat()
            daily_trades = await self.database_layer.get_daily_trades(today)
            self.trades_today = len([t for t in daily_trades if t['status'] == 'OPEN'])
            
            # Calculate current P&L and consecutive losses
            closed_trades = [t for t in daily_trades if t['status'] == 'CLOSED']
            self.daily_pnl = sum(t.get('pnl', 0) for t in closed_trades)
            
            # Calculate consecutive losses (last N trades)
            recent_losses = 0
            for trade in reversed(closed_trades[-self.max_consecutive_losses*2:]):
                if trade.get('pnl', 0) < 0:
                    recent_losses += 1
                else:
                    break
            self.consecutive_losses = min(recent_losses, self.max_consecutive_losses)
            
            # Get current exposure from open positions
            open_positions = await self.database_layer.get_open_positions()
            self.current_positions_value = sum(
                p['quantity'] * p['entry_price'] for p in open_positions
            )
            
            self.logger.info(f"📊 Session loaded: {self.trades_today} trades, ₹{self.daily_pnl:.0f} P&L, {self.consecutive_losses} losses")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize from DB: {e}")
            # Start fresh on error
            await self._check_daily_reset()

    async def can_open_position(self, position: Dict[str, Any], 
                              is_test_mode: bool = False) -> Tuple[bool, str]:
        """
        YOUR EXACT RISK RULES IMPLEMENTATION
        
        Args:
            position: {'symbol', 'quantity', 'entry_price', ...}
            is_test_mode: True for paper trading
            
        Returns:
            (can_trade: bool, reason: str)
        """
        try:
            # RULE 0: Emergency halt check
            if self.trading_halted:
                return False, "🛑 EMERGENCY TRADING HALT ACTIVE"
            
            # RULE 1: Reset daily counters if new trading day
            await self._check_daily_reset()
            
            # RULE 2: Max 3 trades per day
            if self.trades_today >= self.max_daily_trades:
                reason = f"🚫 MAX {self.max_daily_trades} TRADES/DAY REACHED (#{self.trades_today})"
                await self._send_risk_alert(reason)
                return False, reason
            
            # RULE 3: Halt after 2 consecutive SL hits
            if self.consecutive_losses >= self.max_consecutive_losses:
                reason = f"🛑 HALTED: {self.max_consecutive_losses} CONSECUTIVE LOSSES"
                await self._send_risk_alert(reason)
                return False, reason
            
            # RULE 4: Daily P&L loss limit
            if self.daily_pnl < self.max_daily_loss:
                reason = f"💸 DAILY LOSS LIMIT: ₹{self.daily_pnl:.0f} < ₹{self.max_daily_loss}"
                await self._send_risk_alert(reason)
                return False, reason
            
            # RULE 5: Position size limit
            position_value = position['quantity'] * position['entry_price']
            if position_value > self.max_exposure:
                reason = f"📏 POSITION TOO LARGE: ₹{position_value:.0f} > ₹{self.max_exposure}"
                await self._send_risk_alert(reason)
                return False, reason
            
            # RULE 6: Balance verification (SIMPLIFIED FOR TEST MODE)
            if is_test_mode or self.config.get('test_mode', False):
                # 🧪 TEST MODE: Simple virtual balance check (1L default)
                virtual_balance = self.config.get('test_virtual_balance', 100000)  # 1L default
                required_balance = position_value * 1.1  # 10% buffer
                
                if virtual_balance < required_balance:
                    reason = f"💳 VIRTUAL BALANCE LOW: ₹{virtual_balance:.0f} < ₹{required_balance:.0f}"
                    return False, reason
                else:
                    reason = f"💰 VIRTUAL BALANCE OK: ₹{virtual_balance:.0f} ≥ ₹{required_balance:.0f}"
                    return True, reason
                    
            else:
                # LIVE MODE: Real balance verification with dynamic sizing
                available_balance = await self._get_available_balance()
                required_balance = position_value * 1.1  # 10% buffer for fees/slippage
                
                if available_balance < required_balance:
                    # DYNAMIC SIZING (LIVE TRADING ONLY)
                    max_affordable_qty = int((available_balance * 0.9) / position['entry_price'])
                    
                    if max_affordable_qty < self.min_lot_size:
                        # Cannot even afford 1 lot
                        reason = f"💳 INSUFFICIENT BALANCE: ₹{available_balance:.0f} < ₹{required_balance:.0f}"
                        await self._send_risk_alert(reason)
                        return False, reason
                    else:
                        # Reduce position size
                        original_qty = position['quantity']
                        position['quantity'] = max_affordable_qty - (max_affordable_qty % self.min_lot_size)  # Round to lot size
                        new_value = position['quantity'] * position['entry_price']
                        
                        reason = (f"💰 BALANCE ADJUSTMENT: {original_qty}→{position['quantity']} qty "
                                 f"(₹{new_value:.0f} fits ₹{available_balance:.0f} balance)")
                        
                        self.logger.warning(reason)
                        await self.notification_service.send_message(reason)
                        return True, reason  # Allow with reduced size
                else:
                    reason = f"💰 BALANCE OK: ₹{available_balance:.0f} ≥ ₹{required_balance:.0f}"
                    return True, reason
            
            # RULE 7: Market hours
            if not self._is_market_open():
                reason = "⏰ OUTSIDE MARKET HOURS (9:15 AM - 3:30 PM IST)"
                return False, reason
            
            # ALL RULES PASSED
            reason = f"✅ ALL {len(self._get_applicable_rules())} RISK RULES PASSED"
            return True, reason
            
        except Exception as e:
            self.logger.error(f"Risk check crashed: {e}", exc_info=True)
            return False, f"🚨 RISK SYSTEM ERROR: {str(e)}"

    def _get_applicable_rules(self) -> List[str]:
        """Get list of currently applicable risk rules"""
        rules = [
            f"Max {self.max_daily_trades} trades/day (#{self.trades_today}/{self.max_daily_trades})",
            f"Halt after {self.max_consecutive_losses} losses (#{self.consecutive_losses}/{self.max_consecutive_losses})",
            f"Daily loss limit ₹{self.max_daily_loss} (current: ₹{self.daily_pnl:.0f})",
            f"Exposure limit ₹{self.max_exposure} (current: ₹{self.current_positions_value:.0f})"
        ]
        return rules

    async def _send_risk_alert(self, reason: str):
        """Send risk violation alert"""
        try:
            risk_status = await self.get_risk_status()
            message = f"""
🚨 <b>RISK VIOLATION - TRADE BLOCKED</b>

❌ <b>Reason:</b> {reason}

📊 <b>Current Risk Status</b>
📈 Trades Today: {risk_status['trades_today']}/{self.max_daily_trades}
🔥 Consecutive Losses: {risk_status['consecutive_losses']}/{self.max_consecutive_losses}
💰 Session PnL: ₹{risk_status['daily_pnl']:.0f}/{self.max_daily_loss}
📉 Current Exposure: ₹{risk_status['current_positions_value']:.0f}/{self.max_exposure}
⏰ Market Open: {risk_status['market_open']}

🛡️ <b>Risk Protection Active</b>
            """
            await self.notification_service.send_message(message, parse_mode='HTML')
        except Exception as e:
            self.logger.error(f"Risk alert failed: {e}")

    async def _check_daily_reset(self):
        """Reset daily counters at market open (9:15 AM)"""
        try:
            now = datetime.now(self.ist)
            today = now.date().isoformat()
            
            # Check if new trading day
            if (self.last_reset_date != today and 
                now.weekday() < 5 and  # Monday-Friday
                now.replace(hour=9, minute=15) <= now):  # After market open
                
                self.logger.info(f"🌅 Daily reset for {today}")
                
                # Reset all counters
                self.trades_today = 0
                self.consecutive_losses = 0
                self.daily_pnl = 0.0
                self.current_positions_value = 0.0
                self.trading_halted = False
                self.last_reset_date = today
                
                # Update database
                await self.database_layer.set_last_risk_reset(today)
                
                # Send reset notification
                await self.notification_service.send_message(
                    f"""
🌅 <b>New Trading Day: {today}</b>

🔄 <b>All risk counters reset</b>
📊 Ready for {self.max_daily_trades} trades
🛡️ {self.max_consecutive_losses} SL limit active
💰 Daily loss limit: ₹{self.max_daily_loss}
📈 Max exposure: ₹{self.max_exposure}

🟢 <b>Trading RESUMED</b>
                    """,
                    parse_mode='HTML'
                )
                
        except Exception as e:
            self.logger.error(f"Daily reset error: {e}")

    async def record_position_opened(self, position: Dict[str, Any]):
        """Record successful position opening"""
        try:
            # Validate position data
            required_fields = ['symbol', 'quantity', 'entry_price']
            if not all(field in position for field in required_fields):
                raise ValueError(f"Missing required fields: {required_fields}")
            
            # Update trade counter
            self.trades_today += 1
            
            # Reset consecutive losses (new trade started)
            self.consecutive_losses = 0
            
            # Update exposure
            position_value = position['quantity'] * position['entry_price']
            self.current_positions_value += position_value
            
            # Add risk metadata
            position['risk_trade_number'] = self.trades_today
            position['risk_consecutive_losses'] = self.consecutive_losses
            position['risk_session_pnl'] = self.daily_pnl
            position['risk_remaining_trades'] = max(0, self.max_daily_trades - self.trades_today)
            position['entry_time'] = datetime.now(self.ist).isoformat()
            position['status'] = 'OPEN'
            
            # Convert to Position dataclass for consistency
            pos_obj = Position(
                symbol=position['symbol'],
                quantity=position['quantity'],
                entry_price=position['entry_price'],
                entry_time=datetime.now(self.ist),
                strike=position.get('strike'),
                stop_loss=position.get('stop_loss'),
                take_profit=position.get('take_profit'),
                risk_trade_number=position['risk_trade_number'],
                risk_consecutive_losses=position['risk_consecutive_losses'],
                risk_session_pnl=position['risk_session_pnl'],
                risk_remaining_trades=position['risk_remaining_trades']
            )
            
            # Save to database
            await self.database_layer.save_position(pos_obj.__dict__)
            
            self.logger.info(f"""
✅ TRADE #{self.trades_today}/{self.max_daily_trades} OPENED
📊 {position['symbol']} x{position['quantity']} @ ₹{position['entry_price']:.2f}
🔥 Consecutive losses reset to 0
📈 Remaining trades: {self.max_daily_trades - self.trades_today}
📉 Exposure: ₹{self.current_positions_value:.0f}/{self.max_exposure}
            """)
            
            # Send detailed trade alert
            await self.notification_service.send_message(
                f"""
📈 <b>TRADE #{self.trades_today}/{self.max_daily_trades} OPENED</b>

📊 <b>Position Details</b>
📈 Symbol: {position['symbol']}
🔢 Strike: {position.get('strike', 'N/A')}
📏 Quantity: {position['quantity']}
💰 Entry: ₹{position['entry_price']:.2f}
🛡️ Stop Loss: ₹{position.get('stop_loss', 'N/A')}
🎯 Take Profit: ₹{position.get('take_profit', 'N/A')}

📋 <b>Risk Status</b>
📊 Trades Today: {self.trades_today}/{self.max_daily_trades}
🔥 Consecutive Losses: {self.consecutive_losses}/{self.max_consecutive_losses}
💰 Session PnL: ₹{self.daily_pnl:.0f}
📉 Current Exposure: ₹{self.current_positions_value:.0f}/{self.max_exposure}
📈 Remaining Trades: {position['risk_remaining_trades']}
                """,
                parse_mode='HTML'
            )
            
        except Exception as e:
            self.logger.error(f"Error recording position open: {e}", exc_info=True)
            raise

    async def record_position_closed(self, position: Dict[str, Any], pnl: float):
        """Record position closure with risk updates"""
        try:
            # Validate required fields
            required_fields = ['symbol', 'quantity', 'entry_price']
            if not all(field in position for field in required_fields):
                raise ValueError(f"Missing required fields for closure: {required_fields}")
            
            # Update session P&L
            self.daily_pnl += pnl
            
            # Update consecutive losses
            if pnl < 0:  # Loss
                self.consecutive_losses += 1
                self.logger.warning(f"🔥 Consecutive loss #{self.consecutive_losses}/{self.max_consecutive_losses}")
                
                if self.consecutive_losses >= self.max_consecutive_losses:
                    await self._send_trading_halt_alert()
            else:  # Win - reset counter
                self.consecutive_losses = 0
                self.logger.info("✅ Consecutive losses reset")
            
            # Update exposure (position closed)
            position_value = position['quantity'] * position['entry_price']
            self.current_positions_value = max(0, self.current_positions_value - position_value)
            
            # Add final risk metadata
            position['pnl'] = pnl
            position['exit_price'] = position.get('exit_price', position['entry_price'] + (pnl / position['quantity']))
            position['exit_time'] = datetime.now(self.ist).isoformat()
            position['risk_final_pnl'] = self.daily_pnl
            position['risk_consecutive_losses'] = self.consecutive_losses
            position['risk_remaining_trades'] = max(0, self.max_daily_trades - self.trades_today)
            position['status'] = 'CLOSED'
            
            # Calculate hold time
            if 'entry_time' in position and position['entry_time']:
                entry_dt = datetime.fromisoformat(position['entry_time'])
                exit_dt = datetime.fromisoformat(position['exit_time'])
                hold_minutes = (exit_dt - entry_dt).total_seconds() / 60
                position['hold_time'] = round(hold_minutes, 1)
            else:
                position['hold_time'] = 0
            
            # Save to database
            await self.database_layer.save_position(position)
            
            # Send closure alert
            status_emoji = "✅" if pnl > 0 else "❌"
            status_text = "WIN" if pnl > 0 else "LOSS"
            pnl_color = "🟢" if pnl > 0 else "🔴"
            
            await self.notification_service.send_message(
                f"""
{status_emoji} <b>TRADE CLOSED - #{position.get('risk_trade_number', 1)}</b>

📊 <b>Position Results</b>
📈 Symbol: {position['symbol']}
🔢 Strike: {position.get('strike', 'N/A')}
📏 Quantity: {position['quantity']}
💰 Entry: ₹{position['entry_price']:.2f}
💰 Exit: ₹{position['exit_price']:.2f}
{pnl_color} PnL: ₹{pnl:.0f} ({status_text})
⏱️ Hold Time: {position.get('hold_time', 0)} minutes
📋 Exit Reason: {position.get('exit_reason', 'N/A')}

📋 <b>Updated Risk Status</b>
📈 Trades Today: {self.trades_today}/{self.max_daily_trades}
🔥 Consecutive Losses: {self.consecutive_losses}/{self.max_consecutive_losses}
💰 Session Total: ₹{self.daily_pnl:.0f}/{self.max_daily_loss}
📉 Remaining Trades: {max(0, self.max_daily_trades - self.trades_today)}
                """,
                parse_mode='HTML'
            )
            
            self.logger.info(f"""
✅ TRADE #{position.get('risk_trade_number', 1)} CLOSED
📊 {position['symbol']} PnL: ₹{pnl:.0f} ({status_text})
🔥 Consecutive losses: {self.consecutive_losses}/{self.max_consecutive_losses}
📈 Session PnL: ₹{self.daily_pnl:.0f}
            """)
            
        except Exception as e:
            self.logger.error(f"Error recording position close: {e}", exc_info=True)
            raise

    async def _send_trading_halt_alert(self):
        """Send emergency trading halt notification"""
        try:
            self.trading_halted = True
            await self.notification_service.send_message(
                f"""
🛑 <b>🚨 EMERGENCY TRADING HALT ACTIVATED</b> 🚨

🔥 <b>Risk Rule Triggered:</b>
📉 {self.max_consecutive_losses} CONSECUTIVE LOSSES REACHED

📊 <b>Current Session:</b>
📈 Trades Today: {self.trades_today}/{self.max_daily_trades}
💰 Session PnL: ₹{self.daily_pnl:.0f}
🔥 Losses Streak: {self.consecutive_losses}/{self.max_consecutive_losses}

🛡️ <b>Protection Active:</b>
• ❌ No new trades until market close
• 👁️  Existing positions monitored normally
• 🔄 Daily reset tomorrow at 9:15 AM

⚠️ <b>Manual Override:</b>
• Use /emergency_stop to close all positions
• Use /risk_reset to manually reset (DANGER!)

🆘 <b>CONTACT SUPPORT IMMEDIATELY</b>
                """,
                parse_mode='HTML'
            )
            self.logger.critical("TRADING HALTED - MAX CONSECUTIVE LOSSES REACHED")
        except Exception as e:
            self.logger.error(f"Halt alert failed: {e}")

    async def get_risk_status(self) -> Dict[str, Any]:
        """Get comprehensive risk status"""
        try:
            return {
                'trading_allowed': (not self.trading_halted and
                                  self.trades_today < self.max_daily_trades and 
                                  self.consecutive_losses < self.max_consecutive_losses and
                                  self.daily_pnl >= self.max_daily_loss),
                'trading_halted': self.trading_halted,
                'trades_today': self.trades_today,
                'max_daily_trades': self.max_daily_trades,
                'consecutive_losses': self.consecutive_losses,
                'max_consecutive_losses': self.max_consecutive_losses,
                'daily_pnl': self.daily_pnl,
                'max_daily_loss': self.max_daily_loss,
                'current_positions_value': self.current_positions_value,
                'max_exposure': self.max_exposure,
                'remaining_trades': max(0, self.max_daily_trades - self.trades_today),
                'risk_rules_active': True,
                'market_open': self._is_market_open(),
                'last_updated': datetime.now(self.ist).isoformat(),
                'timestamp': datetime.now(self.ist).isoformat()
            }
        except Exception as e:
            self.logger.error(f"Risk status error: {e}")
            return {'error': str(e), 'timestamp': datetime.now(self.ist).isoformat()}

    async def _get_available_balance(self) -> float:
        """Get actual available balance from Zerodha"""
        try:
            if not self.kite:
                raise Exception("KiteConnect not initialized for live trading")
            
            # Check cache first (30-second cache)
            now = datetime.now(self.ist)
            if (self._kite_balance_cache and 
                self._last_balance_check and 
                (now - self._last_balance_check).total_seconds() < 30):
                return self._kite_balance_cache['balance']
            
            # Fetch fresh balance
            margins = self.kite.margins()
            available = float(margins['equity']['available']['live_balance'])
            
            # Update cache
            self._kite_balance_cache = {
                'balance': available,
                'timestamp': now,
                'margins': margins
            }
            self._last_balance_check = now
            
            self.logger.debug(f"Fresh balance: ₹{available:.0f}")
            return available
            
        except Exception as e:
            self.logger.error(f"Balance fetch error: {e}")
            # Return conservative estimate on error
            emergency_balance = self.config.get('emergency_balance', 50000)
            self.logger.warning(f"Using emergency balance: ₹{emergency_balance}")
            return emergency_balance

    def _is_market_open(self) -> bool:
        """Check if within market hours (9:15 AM - 3:30 PM IST, Mon-Fri)"""
        now = datetime.now(self.ist)
        
        # Weekend check
        if now.weekday() >= 5:  # Sat=5, Sun=6
            return False
        
        # Market hours check
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        
        # Holiday check (from config)
        today_str = now.strftime('%Y-%m-%d')
        holidays = self.config.get('market_holidays', [])
        is_holiday = today_str in holidays
        
        return not is_holiday and market_open <= now <= market_close

    async def emergency_stop(self):
        """Emergency stop - halt all trading activities"""
        try:
            self.logger.critical("EMERGENCY STOP INITIATED")
            self.trading_halted = True
            
            # Get current status before halt
            status = await self.get_risk_status()
            
            await self.notification_service.send_message(
                f"""
🚨 <b>EMERGENCY STOP EXECUTED</b> 🚨

🛑 <b>All trading activities HALTED</b>
📊 Status at halt: {json.dumps(status, indent=2, default=str)}
⏰ Timestamp: {datetime.now(self.ist).strftime('%Y-%m-%d %H:%M:%S IST')}

⚠️ <b>MANUAL INTERVENTION REQUIRED</b>
• Review all open positions
• Contact support team immediately
• Do not restart without approval

🔒 <b>System locked until manual reset</b>
                """,
                parse_mode='HTML'
            )
            
            # Log to database
            await self.database_layer.log_system_event('EMERGENCY_STOP', status)
            
            return {
                'status': 'HALTED', 
                'timestamp': datetime.now(self.ist).isoformat(),
                'previous_status': status
            }
            
        except Exception as e:
            self.logger.error(f"Emergency stop failed: {e}", exc_info=True)
            return {'status': 'ERROR', 'reason': str(e)}

    async def manual_risk_reset(self):
        """Manual reset of risk counters (DANGER - use carefully)"""
        try:
            if not self.config.get('allow_manual_reset', False):
                raise PermissionError("Manual reset disabled in config")
            
            self.logger.warning("MANUAL RISK RESET EXECUTED")
            
            # Reset counters
            self.trades_today = 0
            self.consecutive_losses = 0
            self.daily_pnl = 0.0
            self.current_positions_value = 0.0
            self.trading_halted = False
            self.last_reset_date = datetime.now(self.ist).date().isoformat()
            
            # Log the reset
            await self.database_layer.log_system_event('MANUAL_RISK_RESET', {
                'timestamp': datetime.now(self.ist).isoformat(),
                'user': 'MANUAL',
                'reason': 'Manual override'
            })
            
            await self.notification_service.send_message(
                f"""
🔄 <b>MANUAL RISK RESET EXECUTED</b>

⚠️ <b>Warning: Manual override performed</b>
📊 All counters reset to zero
🟢 Trading RESUMED
⏰ {datetime.now(self.ist).strftime('%Y-%m-%d %H:%M:%S IST')}

🛡️ <b>New Session Status:</b>
📈 Trades available: {self.max_daily_trades}
🔥 Consecutive losses: 0
💰 Session P&L: ₹0
📉 Exposure: ₹0

⚠️ <b>USE WITH CAUTION - MONITOR CLOSELY</b>
                """,
                parse_mode='HTML'
            )
            
            return {'status': 'RESET_SUCCESS', 'timestamp': datetime.now(self.ist).isoformat()}
            
        except Exception as e:
            self.logger.error(f"Manual reset failed: {e}")
            return {'status': 'ERROR', 'reason': str(e)}

    async def get_daily_report(self) -> Dict[str, Any]:
        """Generate end-of-day risk report"""
        try:
            risk_status = await self.get_risk_status()
            today = datetime.now(self.ist).date().isoformat()
            daily_trades = await self.database_layer.get_daily_trades(today)
            
            # Calculate performance metrics
            closed_trades = [t for t in daily_trades if t['status'] == 'CLOSED']
            wins = sum(1 for trade in closed_trades if trade.get('pnl', 0) > 0)
            losses = sum(1 for trade in closed_trades if trade.get('pnl', 0) < 0)
            total_pnl = sum(trade.get('pnl', 0) for trade in closed_trades)
            win_rate = round((wins / len(closed_trades) * 100) if closed_trades else 0, 2)
            
            # Risk compliance
            max_trades_respected = len(closed_trades) <= self.max_daily_trades
            loss_limit_respected = total_pnl >= self.max_daily_loss
            
            report = {
                'date': today,
                'total_trades': len(daily_trades),
                'closed_trades': len(closed_trades),
                'wins': wins,
                'losses': losses,
                'win_rate': win_rate,
                'total_pnl': total_pnl,
                'avg_win': round(sum(t.get('pnl', 0) for t in closed_trades if t.get('pnl', 0) > 0) / max(wins, 1), 2),
                'avg_loss': round(sum(t.get('pnl', 0) for t in closed_trades if t.get('pnl', 0) < 0) / max(losses, 1), 2),
                'current_risk_status': risk_status,
                'compliance': {
                    'max_trades_respected': max_trades_respected,
                    'loss_limit_respected': loss_limit_respected,
                    'consecutive_losses': risk_status['consecutive_losses'] < self.max_consecutive_losses
                },
                'risk_violations': await self._get_daily_violations(today)
            }
            
            # Send daily report
            await self._send_daily_report(report)
            
            return report
            
        except Exception as e:
            self.logger.error(f"Daily report error: {e}", exc_info=True)
            return {'error': str(e), 'timestamp': datetime.now(self.ist).isoformat()}

    async def _get_daily_violations(self, date: str) -> List[str]:
        """Get risk violations for a specific date"""
        try:
            violations = await self.database_layer.get_risk_violations(date)
            return [v['reason'] for v in violations if 'RISK VIOLATION' in v['reason']]
        except Exception as e:
            self.logger.error(f"Daily violations error: {e}")
            return []

    async def _send_daily_report(self, report: Dict[str, Any]):
        """Send end-of-day risk report"""
        try:
            win_rate_emoji = "🟢" if report['win_rate'] >= 60 else "🟡" if report['win_rate'] >= 40 else "🔴"
            pnl_emoji = "🟢" if report['total_pnl'] > 0 else "🔴"
            compliance_score = sum(report['compliance'].values())
            compliance_emoji = "🟢" if compliance_score == 3 else "🟡" if compliance_score == 2 else "🔴"
            
            message = f"""
📊 <b>DAILY TRADING REPORT - {report['date']}</b>

📈 <b>Performance Summary</b>
{win_rate_emoji} Win Rate: {report['win_rate']}%
📊 Total Trades: {report['total_trades']} | Closed: {report['closed_trades']}
✅ Wins: {report['wins']} | Avg Win: ₹{report['avg_win']:+.0f}
❌ Losses: {report['losses']} | Avg Loss: ₹{report['avg_loss']:+.0f}
{pnl_emoji} Total PnL: ₹{report['total_pnl']:+.0f}

{compliance_emoji} <b>Risk Compliance</b>
📋 Violations Today: {len(report['risk_violations'])}
📈 Max Trades: {'✅ YES' if report['compliance']['max_trades_respected'] else '❌ NO'}
💰 Loss Limit: {'✅ YES' if report['compliance']['loss_limit_respected'] else '❌ NO'}
🔥 Loss Streak: {'✅ OK' if report['compliance']['consecutive_losses'] else '❌ BREACHED'}

💼 <b>Tomorrow's Status</b>
📊 Trades Available: {report['current_risk_status']['remaining_trades']}
🔥 Consecutive Losses: {report['current_risk_status']['consecutive_losses']}
🛡️ Trading Allowed: {report['current_risk_status']['trading_allowed']}

📅 <b>Generated:</b> {datetime.now(self.ist).strftime('%H:%M:%S IST')}
            """
            
            await self.notification_service.send_message(message, parse_mode='HTML')
            
        except Exception as e:
            self.logger.error(f"Daily report send failed: {e}")

    async def validate_config(self) -> Tuple[bool, str]:
        """Validate risk management configuration"""
        try:
            issues = []
            
            # Validate numeric values
            if self.max_daily_trades < 1:
                issues.append("max_daily_trades must be >= 1")
            if self.max_consecutive_losses < 1:
                issues.append("max_consecutive_losses must be >= 1")
            if self.max_daily_loss >= 0:
                issues.append("max_daily_loss should be negative")
            if self.max_exposure < self.min_balance_per_trade:
                issues.append("max_exposure should be >= min_balance_per_trade")
            if self.min_lot_size < 1:
                issues.append("min_lot_size must be >= 1")
            
            # Validate test mode settings
            if self.config.get('test_mode', False):
                if self.config.get('test_virtual_balance', 100000) < self.min_balance_per_trade:
                    issues.append("test_virtual_balance too low for min_balance_per_trade")
            
            # Validate live mode settings
            if not self.config.get('test_mode', False):
                if not self.config.get('api_key'):
                    issues.append("api_key required for live trading")
                if not self.config.get('access_token'):
                    issues.append("access_token required for live trading")
            
            if issues:
                return False, f"❌ Config validation failed: {'; '.join(issues)}"
            else:
                return True, f"✅ Risk configuration validated successfully ({'LIVE' if not self.config.get('test_mode', False) else 'TEST'} MODE)"
                
        except Exception as e:
            return False, f"🚨 Config validation error: {str(e)}"

    async def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check"""
        try:
            results = {
                'timestamp': datetime.now(self.ist).isoformat(),
                'system_status': 'HEALTHY',
                'checks': {}
            }
            
            # Config validation
            config_valid, config_msg = await self.validate_config()
            results['checks']['config'] = {'status': config_valid, 'message': config_msg}
            
            # Database connectivity
            try:
                await self.database_layer.ping()
                results['checks']['database'] = {'status': True, 'message': 'Connected'}
            except Exception as e:
                results['checks']['database'] = {'status': False, 'message': str(e)}
                results['system_status'] = 'UNHEALTHY'
            
            # Notification service
            try:
                await self.notification_service.test_connection()
                results['checks']['notifications'] = {'status': True, 'message': 'Connected'}
            except Exception as e:
                results['checks']['notifications'] = {'status': False, 'message': str(e)}
                results['system_status'] = 'UNHEALTHY'
            
            # Broker connectivity (live mode only)
            if not self.config.get('test_mode', False) and self.kite:
                try:
                    await self._get_available_balance()
                    results['checks']['broker'] = {'status': True, 'message': 'Connected'}
                except Exception as e:
                    results['checks']['broker'] = {'status': False, 'message': str(e)}
                    results['system_status'] = 'UNHEALTHY'
            else:
                results['checks']['broker'] = {'status': 'N/A', 'message': 'Test mode - broker not checked'}
            
            # Risk status
            risk_status = await self.get_risk_status()
            results['checks']['risk_status'] = risk_status
            if not risk_status.get('trading_allowed', False):
                results['system_status'] = 'WARNING'
            
            # Market hours
            results['checks']['market_open'] = self._is_market_open()
            
            # Send health report if unhealthy
            if results['system_status'] != 'HEALTHY':
                await self.notification_service.send_message(
                    f"🚨 <b>RISK MANAGER HEALTH ALERT</b>\n"
                    f"Status: {results['system_status']}\n"
                    f"Check details: {json.dumps(results['checks'], indent=2, default=str)[:500]}...",
                    parse_mode='HTML'
                )
            
            return results
            
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            return {'error': str(e), 'timestamp': datetime.now(self.ist).isoformat()}
