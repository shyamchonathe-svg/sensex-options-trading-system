#!/usr/bin/env python3
"""
Integrated End-to-End Trading System
Main trading engine with 3-mode support and full risk management
"""
import asyncio
import logging
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np
import random
import secrets
from pathlib import Path

# Local imports
from secure_config_manager import config
from modes import TradingMode, create_mode_config
from risk_manager import RiskManager
from notification_service import NotificationService
from kiteconnect import KiteConnect

# Setup logging
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / f'trading_{config.MODE.lower()}.log', mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class TokenValidator:
    """Validates and refreshes access tokens."""
    
    def __init__(self, config: Dict[str, Any], notification_service: NotificationService):
        self.config = config
        self.notification_service = notification_service
        self.last_validation = 0
        self.min_interval = 300  # 5 minutes
        self.kite = None
    
    async def initialize_kite(self):
        """Initialize KiteConnect with current token."""
        try:
            self.kite = KiteConnect(api_key=self.config.ZAPI_KEY)
            self.kite.set_access_token(self.config.ACCESS_TOKEN)
            logger.info("✅ KiteConnect initialized with current token")
            return True
        except Exception as e:
            logger.error(f"❌ KiteConnect initialization failed: {e}")
            await self.notification_service.send_system_alert({
                "type": "ERROR",
                "component": "TokenValidator",
                "message": f"KiteConnect init failed: {str(e)[:100]}",
                "mode": self.config.MODE
            })
            return False
    
    async def validate_token(self) -> bool:
        """Validate token and refresh if needed."""
        now = pd.Timestamp.now().timestamp()
        if now - self.last_validation < self.min_interval:
            return True
        
        try:
            if not self.kite:
                await self.initialize_kite()
                if not self.kite:
                    return False
            
            # Test token with profile API
            profile = self.kite.profile()
            logger.debug(f"Token validation successful: {profile.get('user_id', 'unknown')}")
            
            # Check token age (rough estimate)
            last_login = profile.get('last_login', '1970-01-01')
            token_age = (pd.Timestamp.now() - pd.Timestamp(last_login)).total_seconds()
            
            if token_age > 24 * 3600 - 2 * 3600:  # Refresh if <2h remaining
                logger.warning("🔄 Token expiry approaching, refresh recommended")
                # Don't auto-refresh here, let manual process handle it
            
            self.last_validation = now
            return True
            
        except Exception as e:
            logger.error(f"💥 Token validation failed: {e}")
            await self.notification_service.send_system_alert({
                "type": "WARNING",
                "component": "TokenValidator",
                "message": f"Token validation failed: {str(e)[:100]}",
                "mode": self.config.MODE,
                "action": "Manual token refresh required"
            })
            return False

class TradingModeHandler:
    """Handles mode-specific trading behavior."""
    
    def __init__(self, config: Dict[str, Any], notification_service: NotificationService):
        self.config = config
        self.notification_service = notification_service
        self.mode = config.get("MODE", "TEST")
        self.is_live = self.mode == "LIVE"
        self.is_paper = self.mode == "PAPER"
        self.is_test = self.mode == "TEST"
        
        # Mode-specific state
        if self.is_test:
            self.mock_positions = {}
            self.mock_pnl = 0.0
            self.mock_trades_today = 0
            logger.info("🧪 TEST MODE: Mock trading engine initialized")
        
        if self.is_paper:
            self.paper_positions = {}
            self.paper_pnl = 0.0
            logger.info("📝 PAPER MODE: Simulated trading engine initialized")
    
    async def place_order(self, order_params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute order based on trading mode."""
        order_params["mode"] = self.mode
        
        if self.is_live:
            return await self._execute_live_order(order_params)
        elif self.is_paper:
            return await self._execute_paper_order(order_params)
        elif self.is_test:
            return await self._execute_test_order(order_params)
        else:
            logger.error(f"❌ Unknown trading mode: {self.mode}")
            return {"status": "ERROR", "error": f"Unknown mode: {self.mode}"}
    
    async def _execute_live_order(self, order_params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute real order in LIVE mode."""
        try:
            if not self.config.ACCESS_TOKEN:
                return {"status": "ERROR", "error": "No access token"}
            
            kite = KiteConnect(api_key=self.config.ZAPI_KEY)
            kite.set_access_token(self.config.ACCESS_TOKEN)
            
            # Place actual order
            order = kite.place_order(
                variety=kite.VARIETY_REGULAR,
                exchange=kite.EXCHANGE_NFO,
                tradingsymbol=order_params["symbol"],
                transaction_type=kite.TRANSACTION_TYPE_BUY if order_params["side"] == "BUY" else kite.TRANSACTION_TYPE_SELL,
                quantity=order_params["quantity"],
                product=kite.PRODUCT_MIS,
                order_type=kite.ORDER_TYPE_LIMIT,
                price=order_params["price"],
                validity=kite.VALIDITY_DAY,
                squareoff=order_params.get("squareoff"),
                stoploss=order_params.get("stoploss")
            )
            
            logger.info(f"🔴 LIVE ORDER: {order_params['side']} {order_params['quantity']} "
                       f"{order_params['symbol']} @ ₹{order_params['price']:.2f} -> {order['status']}")
            
            await self.notification_service.send_trade_alert(order_params, self.mode)
            
            return {
                "status": "COMPLETE" if order.get("status") == "COMPLETE" else order.get("status", "PENDING"),
                "order_id": order.get("order_id"),
                "exchange_order_id": order.get("exchange_order_id"),
                "price": order_params["price"],
                "quantity": order_params["quantity"],
                "mode": self.mode
            }
            
        except Exception as e:
            logger.error(f"💥 LIVE order failed: {e}")
            await self.notification_service.send_system_alert({
                "type": "ERROR",
                "component": "LiveTrading",
                "message": f"Order execution failed: {str(e)[:100]}",
                "mode": self.mode
            })
            return {"status": "ERROR", "error": str(e)}
    
    async def _execute_paper_order(self, order_params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute simulated order in PAPER mode with realistic slippage."""
        try:
            # Simulate realistic fill with slippage
            base_price = order_params["price"]
            slippage = random.uniform(-0.015, 0.015)  # ±1.5% slippage for options
            fill_price = base_price * (1 + slippage)
            
            # 5% chance of partial fill
            if random.random() < 0.05:
                fill_quantity = int(order_params["quantity"] * random.uniform(0.5, 0.95))
                status = "PARTIAL"
            else:
                fill_quantity = order_params["quantity"]
                status = "COMPLETE"
            
            # Generate order ID
            order_id = f"PAPER_{int(datetime.now().timestamp())}_{random.randint(1000, 9999)}"
            
            # Track paper position
            position_key = f"{order_params['symbol']}_{order_params['side']}"
            if position_key not in self.paper_positions:
                self.paper_positions[position_key] = {
                    "quantity": 0,
                    "average_price": 0.0,
                    "entry_time": datetime.now()
                }
            
            current_pos = self.paper_positions[position_key]
            if order_params["side"] == "BUY":
                if current_pos["quantity"] > 0:
                    # Average existing position
                    total_cost = (current_pos["quantity"] * current_pos["average_price"] + 
                                fill_quantity * fill_price)
                    current_pos["quantity"] += fill_quantity
                    current_pos["average_price"] = total_cost / current_pos["quantity"]
                else:
                    current_pos["quantity"] = fill_quantity
                    current_pos["average_price"] = fill_price
            else:  # SELL
                current_pos["quantity"] -= fill_quantity
                if current_pos["quantity"] <= 0:
                    # Close position, calculate P&L
                    if current_pos["quantity"] < 0:
                        self.paper_pnl += abs(current_pos["quantity"]) * fill_price
                    del self.paper_positions[position_key]
            
            logger.info(f"📝 PAPER ORDER: {order_params['side']} {fill_quantity} "
                       f"{order_params['symbol']} @ ₹{fill_price:.2f} "
                       f"(slippage: {slippage*100:+.2f}%) -> {status}")
            
            order_result = {
                "status": status,
                "order_id": order_id,
                "fill_price": fill_price,
                "fill_quantity": fill_quantity,
                "slippage": slippage,
                "mode": self.mode
            }
            
            await self.notification_service.send_trade_alert({
                **order_params,
                "action": "ENTRY",
                "price": fill_price,
                "quantity": fill_quantity,
                "slippage": f"{slippage*100:+.2f}%"
            }, self.mode)
            
            return order_result
            
        except Exception as e:
            logger.error(f"💥 Paper order failed: {e}")
            return {"status": "ERROR", "error": str(e)}
    
    async def _execute_test_order(self, order_params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute mock order in TEST mode with Telegram alert only."""
        try:
            # Generate realistic mock fill
            base_price = order_params["price"]
            mock_slippage = random.uniform(-0.01, 0.01)  # ±1% for testing
            fill_price = base_price * (1 + mock_slippage)
            
            # Always complete for testing
            fill_quantity = order_params["quantity"]
            
            # Generate mock order ID
            order_id = f"TEST_{int(datetime.now().timestamp())}_{secrets.token_hex(4).upper()}"
            
            # Track mock statistics (no actual positions)
            self.mock_trades_today += 1
            self.mock_pnl += (fill_price * fill_quantity * 
                            (1 if order_params["side"] == "SELL" else -1))
            
            logger.info(f"🧪 TEST ORDER: Would execute {order_params['side']} {fill_quantity} "
                       f"{order_params['symbol']} @ ₹{fill_price:.2f} "
                       f"(mock slippage: {mock_slippage*100:+.2f}%)")
            
            # Detailed Telegram alert for TEST mode (exact entry details)
            alert_data = {
                "action": "ENTRY",
                "signal": order_params.get("signal", "EMA_BREAKOUT"),
                "symbol": order_params["symbol"],
                "side": order_params["side"],
                "quantity": fill_quantity,
                "price": fill_price,
                "sensex_price": order_params.get("sensex_price", 0),
                "risk_amount": order_params.get("risk_amount", 0),
                "risk_percent": order_params.get("risk_percent", 0),
                "stop_loss": order_params.get("stop_loss", 0),
                "take_profit": order_params.get("take_profit", 0),
                "time": datetime.now().strftime('%H:%M:%S IST'),
                "slippage": f"{mock_slippage*100:+.2f}%"
            }
            
            await self.notification_service.send_trade_alert(alert_data, self.mode)
            
            # Also log to file for analysis
            test_log = {
                "timestamp": datetime.now().isoformat(),
                "mode": self.mode,
                "action": "MOCK_ENTRY",
                "symbol": order_params["symbol"],
                "side": order_params["side"],
                "quantity": fill_quantity,
                "entry_price": fill_price,
                "sensex_price": order_params.get("sensex_price", 0),
                "ema_fast": order_params.get("ema_fast", 0),
                "ema_slow": order_params.get("ema_slow", 0),
                "signal_strength": order_params.get("signal_strength", "MEDIUM"),
                "risk_amount": order_params.get("risk_amount", 0),
                "mock_order_id": order_id
            }
            
            # Save to test results
            test_results_dir = Path("test_results")
            test_results_dir.mkdir(exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            result_file = test_results_dir / f"test_trade_{timestamp}.json"
            result_file.write_text(json.dumps(test_log, indent=2))
            
            return {
                "status": "MOCK_COMPLETE",
                "order_id": order_id,
                "fill_price": fill_price,
                "fill_quantity": fill_quantity,
                "mode": self.mode,
                "mock_pnl": round(self.mock_pnl, 2),
                "trades_today": self.mock_trades_today
            }
            
        except Exception as e:
            logger.error(f"💥 Test order failed: {e}")
            return {"status": "ERROR", "error": str(e)}
    
    async def get_positions(self) -> Dict[str, Any]:
        """Get current positions by mode."""
        if self.is_live:
            try:
                kite = KiteConnect(api_key=self.config.ZAPI_KEY)
                kite.set_access_token(self.config.ACCESS_TOKEN)
                positions = kite.positions()
                return positions
            except Exception as e:
                logger.error(f"Failed to get live positions: {e}")
                return {"net": []}
        
        elif self.is_paper:
            # Convert paper positions to Kite format
            net_positions = []
            for symbol_side, pos in self.paper_positions.items():
                if pos["quantity"] != 0:
                    symbol = symbol_side.split("_")[0]
                    net_positions.append({
                        "tradingsymbol": symbol,
                        "netqty": pos["quantity"],
                        "average_price": pos["average_price"]
                    })
            return {"net": net_positions}
        
        elif self.is_test:
            # Mock positions for testing
            mock_positions = []
            for symbol_side, pos in self.mock_positions.items():
                if pos["quantity"] != 0:
                    symbol = symbol_side.split("_")[0]
                    mock_positions.append({
                        "tradingsymbol": symbol,
                        "netqty": pos["quantity"],
                        "average_price": pos["average_price"],
                        "mode": "MOCK"
                    })
            return {"net": mock_positions}
        
        return {"net": []}

class SignalGenerator:
    """Generates trading signals based on EMA channels."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.ema_fast_period = config.get("EMA_FAST", 10)
        self.ema_slow_period = config.get("EMA_SLOW", 20)
        self.volatility_threshold = config.get("VOLATILITY_THRESHOLD", 0.02)
        self.min_signal_strength = 0.001  # 0.1% minimum deviation
    
    def generate_signal(self, prices: pd.Series, current_sensex: float) -> Optional[Dict[str, Any]]:
        """Generate trading signal from price series."""
        if len(prices) < self.ema_slow_period:
            return None
        
        # Calculate EMAs
        ema_fast = prices.ewm(span=self.ema_fast_period).mean().iloc[-1]
        ema_slow = prices.ewm(span=self.ema_slow_period).mean().iloc[-1]
        
        # Calculate channel and volatility
        channel_width = abs(ema_fast - ema_slow) / ema_slow
        price_position = (current_sensex - ema_slow) / ema_slow
        
        # Volatility check (channel should be narrow for mean reversion)
        if channel_width > self.volatility_threshold:
            logger.debug(f"High volatility: {channel_width:.4f} > {self.volatility_threshold}")
            return None
        
        # Signal generation
        signal_strength = abs(price_position)
        
        if signal_strength < self.min_signal_strength:
            return None
        
        # Long signal: price significantly above upper channel
        if price_position > 0.002:  # 0.2% above slow EMA
            return {
                "signal": "LONG",
                "strength": signal_strength,
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
                "channel_width": channel_width,
                "price_position": price_position,
                "confidence": min(signal_strength * 100, 95)  # Cap at 95%
            }
        
        # Short signal: price significantly below lower channel  
        elif price_position < -0.002:  # 0.2% below slow EMA
            return {
                "signal": "SHORT", 
                "strength": signal_strength,
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
                "channel_width": channel_width,
                "price_position": price_position,
                "confidence": min(signal_strength * 100, 95)
            }
        
        return None

class LiveTradingGuard:
    """Safety checks for LIVE trading."""
    
    def __init__(self, config: Dict[str, Any], notification_service: NotificationService):
        self.config = config
        self.notification_service = notification_service
        self.market_open = False
        self.trading_session_active = False
    
    async def pre_trade_checklist(self) -> bool:
        """Run comprehensive pre-trade checklist for LIVE mode."""
        checklist = []
        critical_issues = 0
        
        now = datetime.now()
        market_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
        
        # 1. Market hours
        if market_start <= now <= market_end:
            checklist.append("✅ MARKET HOURS: Open")
            self.market_open = True
        else:
            checklist.append(f"❌ MARKET HOURS: Closed (Next: {market_start.strftime('%H:%M') if now < market_start else market_start.strftime('%H:%M') + ' tomorrow'})")
            critical_issues += 1
            self.market_open = False
        
        # 2. Token validation
        try:
            kite = KiteConnect(api_key=self.config.ZAPI_KEY)
            kite.set_access_token(self.config.ACCESS_TOKEN)
            profile = kite.profile()
            checklist.append(f"✅ TOKEN: Valid ({profile.get('user_id', 'unknown')})")
        except Exception as e:
            checklist.append(f"❌ TOKEN: Invalid ({str(e)[:50]}...)")
            critical_issues += 1
        
        # 3. Balance check
        try:
            kite = KiteConnect(api_key=self.config.ZAPI_KEY)
            kite.set_access_token(self.config.ACCESS_TOKEN)
            margins = kite.margins()
            cash = margins['equity']['available']['cash']
            min_balance = self.config.get("MIN_BALANCE", 50000)
            
            if cash >= min_balance:
                checklist.append(f"✅ BALANCE: ₹{cash:,.0f} (Min: ₹{min_balance:,})")
            else:
                checklist.append(f"⚠️  BALANCE: ₹{cash:,.0f} < ₹{min_balance:,} (Low balance warning)")
                critical_issues += 1
        except Exception as e:
            checklist.append(f"❌ BALANCE: Check failed ({str(e)[:50]}...)")
            critical_issues += 1
        
        # 4. Pending orders check
        try:
            kite = KiteConnect(api_key=self.config.ZAPI_KEY)
            kite.set_access_token(self.config.ACCESS_TOKEN)
            orders = kite.orders()
            pending_orders = [o for o in orders if o['status'] in ['PENDING', 'OPEN']]
            
            if len(pending_orders) == 0:
                checklist.append("✅ ORDERS: No pending orders")
            else:
                checklist.append(f"⚠️  ORDERS: {len(pending_orders)} pending orders")
        except Exception as e:
            checklist.append(f"❌ ORDERS: Check failed ({str(e)[:50]}...)")
            critical_issues += 1
        
        # 5. Risk manager status
        try:
            risk_status = await RiskManager(self.config).can_trade()
            if risk_status["allowed"]:
                checklist.append(f"✅ RISK: {risk_status['risk_level']} (Allowed)")
            else:
                checklist.append(f"❌ RISK: {risk_status['reason']}")
                critical_issues += 1
        except Exception as e:
            checklist.append(f"❌ RISK: Check failed ({str(e)[:50]}...)")
            critical_issues += 1
        
        # Send checklist
        checklist_message = "🔍 <b>LIVE TRADING PRE-FLIGHT CHECKLIST</b>\n\n" + "\n".join(checklist)
        await self.notification_service.send_message(checklist_message)
        
        # Determine trading status
        all_checks_passed = critical_issues == 0 and self.market_open
        self.trading_session_active = all_checks_passed
        
        status_emoji = "🚀" if all_checks_passed else "🛑"
        status_msg = f"{status_emoji} <b>LIVE TRADING {'ACTIVE' if all_checks_passed else 'BLOCKED'}</b>"
        if not all_checks_passed:
            status_msg += f"\n💥 <i>{critical_issues} critical issues</i>"
        
        await self.notification_service.send_message(status_msg)
        
        logger.info(f"LIVE checklist: {'PASSED' if all_checks_passed else 'FAILED'} ({critical_issues} issues)")
        return all_checks_passed

class BotController:
    """Main trading controller orchestrating all components."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.mode_config = create_mode_config(config)
        self.notification_service = NotificationService(config)
        self.risk_manager = RiskManager(config)
        self.token_validator = TokenValidator(config, self.notification_service)
        self.trading_mode_handler = TradingModeHandler(config, self.notification_service)
        self.signal_generator = SignalGenerator(config)
        self.live_guard = LiveTradingGuard(config, self.notification_service)
        
        # Trading state
        self.running = False
        self.last_signal_time = None
        self.min_signal_interval = 1800  # 30 minutes between signals
        self.sensex_prices = pd.Series(dtype=float)
        
        # Market hours
        self.market_start = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
        self.market_end = datetime.now().replace(hour=15, minute=30, second=0, microsecond=0)
        
        logger.info(f"🤖 BotController initialized - Mode: {self.mode_config.mode.value}")
        logger.info(self.mode_config.get_mode_description())
    
    async def initialize(self):
        """Initialize all components."""
        logger.info("🔄 Initializing trading system...")
        
        # Send mode status
        await self.notification_service.send_mode_status(self.mode_config.__dict__)
        
        # Initialize token validator
        if not await self.token_validator.initialize_kite():
            logger.error("❌ Failed to initialize KiteConnect")
            return False
        
        # Run LIVE mode checklist if applicable
        if self.mode_config.mode == TradingMode.LIVE:
            if not await self.live_guard.pre_trade_checklist():
                logger.error("❌ LIVE mode checklist failed")
                return False
        
        # Validate risk manager
        risk_status = await self.risk_manager.can_trade()
        logger.info(f"Risk status: {risk_status['allowed']} ({risk_status.get('reason', 'Ready')})")
        
        # Initialize price history
        self.sensex_prices = pd.Series(dtype=float)
        
        logger.info("✅ System initialization complete")
        return True
    
    async def get_market_data(self) -> Optional[float]:
        """Get current Sensex price."""
        try:
            if not self.token_validator.kite:
                await self.token_validator.initialize_kite()
                if not self.token_validator.kite:
                    return None
            
            # Get LTP for Sensex
            quote = self.token_validator.kite.quote("NSE:NIFTY 50")  # Using NIFTY as proxy for Sensex
            ltp = float(quote[0]['ohlc']['close'])
            
            # Update price history
            self.sensex_prices = pd.concat([self.sensex_prices, pd.Series([ltp])]).tail(50)
            
            return ltp
            
        except Exception as e:
            logger.error(f"Failed to get market data: {e}")
            await self.notification_service.send_system_alert({
                "type": "WARNING",
                "component": "MarketData",
                "message": f"Failed to fetch Sensex price: {str(e)[:100]}",
                "mode": self.mode_config.mode.value
            })
            return None
    
    async def find_option_symbol(self, sensex_price: float, signal: str) -> Optional[str]:
        """Find appropriate option symbol based on signal."""
        # Simplified option symbol generation for demo
        # In production, this would query KiteConnect for actual option chain
        
        strike_interval = 100
        atm_strike = round(sensex_price / strike_interval) * strike_interval
        
        if signal == "LONG":
            strike = atm_strike  # ATM Call
            symbol = f"SENSEX{datetime.now().strftime('%y%b%d')}C{int(strike)}"
        else:  # SHORT
            strike = atm_strike  # ATM Put
            symbol = f"SENSEX{datetime.now().strftime('%y%b%d')}P{int(strike)}"
        
        # Mock option price (in production, get from KiteConnect)
        option_price = sensex_price * random.uniform(0.02, 0.05)  # 2-5% of underlying
        
        logger.debug(f"Option selection: {symbol} @ ₹{option_price:.2f} (ATM: {atm_strike})")
        return symbol, option_price
    
    async def calculate_position_size(self, sensex_price: float, option_price: float, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate position size based on risk parameters."""
        risk_per_trade = self.mode_config.risk_per_trade
        account_balance = 100000  # Mock balance - in production, get from KiteConnect
        
        # Risk amount
        risk_amount = account_balance * risk_per_trade
        
        # Position sizing (simplified - 1 lot = 25 shares for Sensex options)
        lot_size = 25
        max_quantity = int(risk_amount / (option_price * 0.03))  # 3% risk per option
        quantity = min(max_quantity, 5 * lot_size)  # Max 5 lots
        quantity = (quantity // lot_size) * lot_size  # Round to lot size
        
        # Risk calculations
        entry_price = option_price
        stop_loss = entry_price * (1 - 0.03)  # 3% stop loss
        take_profit = entry_price * (1 + 0.06)  # 6% take profit
        
        risk_per_share = entry_price - stop_loss
        total_risk = quantity * risk_per_share
        
        # Adjust quantity to match risk amount
        if total_risk > 0:
            adjusted_quantity = int((risk_amount / risk_per_share) // lot_size * lot_size)
            quantity = min(adjusted_quantity, quantity)
        
        return {
            "quantity": quantity,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_amount": quantity * risk_per_share,
            "risk_percent": (quantity * risk_per_share) / account_balance,
            "lot_size": lot_size
        }
    
    async def execute_trade(self, signal: Dict[str, Any], sensex_price: float) -> bool:
        """Execute complete trade workflow."""
        try:
            # Risk check
            risk_status = await self.risk_manager.can_trade()
            if not risk_status["allowed"]:
                logger.warning(f"Trade blocked by risk manager: {risk_status['reason']}")
                await self.notification_service.send_system_alert({
                    "type": "WARNING",
                    "component": "RiskManager",
                    "message": f"Trade blocked: {risk_status['reason']}",
                    "mode": self.mode_config.mode.value
                })
                return False
            
            # Find option
            option_symbol, option_price = await self.find_option_symbol(sensex_price, signal["signal"])
            if not option_symbol:
                logger.warning("No suitable option found")
                return False
            
            # Calculate position
            position_data = await self.calculate_position_size(sensex_price, option_price, signal)
            if position_data["quantity"] == 0:
                logger.warning("Position size calculated as 0")
                return False
            
            # Prepare order parameters
            side = "BUY" if signal["signal"] == "LONG" else "SELL"
            order_params = {
                "symbol": option_symbol,
                "side": side,
                "quantity": position_data["quantity"],
                "price": position_data["entry_price"],
                "signal": signal["signal"],
                "sensex_price": sensex_price,
                "ema_fast": signal["ema_fast"],
                "ema_slow": signal["ema_slow"],
                "signal_strength": signal["strength"],
                "risk_amount": position_data["risk_amount"],
                "risk_percent": position_data["risk_percent"],
                "stop_loss": position_data["stop_loss"],
                "take_profit": position_data["take_profit"]
            }
            
            # Execute based on mode
            order_result = await self.trading_mode_handler.place_order(order_params)
            
            if order_result.get("status") in ["COMPLETE", "MOCK_COMPLETE"]:
                # Record trade
                trade_data = {
                    "date": datetime.now().strftime('%Y-%m-%d'),
                    "symbol": option_symbol,
                    "side": side,
                    "quantity": position_data["quantity"],
                    "entry_price": order_result.get("fill_price", position_data["entry_price"]),
                    "pnl": 0.0,  # Will be updated on exit
                    "sl_hit": False,
                    "mode": self.mode_config.mode.value,
                    "order_id": order_result.get("order_id", ""),
                    "status": "OPEN"
                }
                
                await self.risk_manager.record_trade(trade_data)
                await self.risk_manager.increment_trade_count()
                
                self.last_signal_time = pd.Timestamp.now()
                logger.info(f"✅ Trade executed: {side} {position_data['quantity']} {option_symbol}")
                return True
            else:
                logger.error(f"❌ Trade execution failed: {order_result.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            logger.error(f"💥 Trade execution error: {e}")
            await self.notification_service.send_system_alert({
                "type": "ERROR",
                "component": "TradeExecution",
                "message": f"Trade execution failed: {str(e)[:100]}",
                "mode": self.mode_config.mode.value
            })
            return False
    
    async def trading_loop(self):
        """Main trading loop."""
        logger.info("🚀 Starting trading loop...")
        self.running = True
        
        consecutive_errors = 0
        max_errors = 5
        
        while self.running:
            try:
                # Check if within market hours
                now = datetime.now()
                today_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
                today_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
                
                if not (today_start <= now <= today_end):
                    if now.hour < 9 or (now.hour >= 16) or (now.hour == 15 and now.minute > 30):
                        await asyncio.sleep(300)  # Sleep 5 minutes outside market hours
                        continue
                
                # Token validation
                if not await self.token_validator.validate_token():
                    logger.warning("Token validation failed, waiting for manual refresh...")
                    await asyncio.sleep(300)
                    continue
                
                # Get market data
                sensex_price = await self.get_market_data()
                if sensex_price is None:
                    consecutive_errors += 1
                    if consecutive_errors >= max_errors:
                        logger.error("Too many consecutive data errors, pausing...")
                        await self.notification_service.send_system_alert({
                            "type": "ERROR",
                            "component": "MarketData",
                            "message": "Too many consecutive data fetch failures",
                            "mode": self.mode_config.mode.value,
                            "action": "Manual intervention required"
                        })
                        await asyncio.sleep(1800)  # Wait 30 minutes
                        consecutive_errors = 0
                    continue
                
                consecutive_errors = 0
                
                # Generate signal (only if enough price history)
                if len(self.sensex_prices) >= self.signal_generator.ema_slow_period:
                    signal = self.signal_generator.generate_signal(self.sensex_prices, sensex_price)
                    
                    if signal:
                        # Check signal timing
                        if (self.last_signal_time is None or 
                            (pd.Timestamp.now() - self.last_signal_time).total_seconds() > self.min_signal_interval):
                            
                            logger.info(f"📡 SIGNAL: {signal['signal']} (Strength: {signal['strength']:.4f}, "
                                       f"Confidence: {signal['confidence']:.1f}%)")
                            
                            # LIVE mode additional safety check
                            if self.mode_config.mode == TradingMode.LIVE:
                                if not await self.live_guard.pre_trade_checklist():
                                    logger.warning("LIVE trade blocked by safety checklist")
                                    continue
                            
                            # Execute trade
                            trade_successful = await self.execute_trade(signal, sensex_price)
                            
                            if trade_successful:
                                logger.info("✅ Trade workflow completed successfully")
                            else:
                                logger.warning("⚠️  Trade workflow failed")
                        else:
                            logger.debug("Signal ignored: too soon after last trade")
                    else:
                        logger.debug("No signal generated")
                
                # Send periodic status (every hour)
                if now.minute == 0:
                    risk_status = await self.risk_manager.can_trade()
                    positions = await self.trading_mode_handler.get_positions()
                    
                    status_msg = (
                        f"📊 <b>STATUS UPDATE {self.mode_config.get_mode_emoji()}</b>\n\n"
                        f"⏰ <b>Time:</b> {now.strftime('%H:%M IST')}\n"
                        f"📉 <b>Sensex:</b> {sensex_price:,.0f}\n"
                        f"🛡️ <b>Risk:</b> {risk_status['risk_level']} ({'Allowed' if risk_status['allowed'] else 'Blocked'})\n"
                        f"📈 <b>Positions:</b> {len(positions.get('net', []))}\n"
                        f"{'🔴 LIVE TRADING ACTIVE' if self.mode_config.mode == TradingMode.LIVE else ''}"
                    )
                    
                    await self.notification_service.send_message(status_msg)
                
                # Sleep between iterations
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except KeyboardInterrupt:
                logger.info("🛑 Received shutdown signal")
                break
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"💥 Unexpected error in trading loop: {e}")
                await self.notification_service.send_system_alert({
                    "type": "ERROR",
                    "component": "TradingLoop",
                    "message": f"Unexpected error: {str(e)[:100]}",
                    "mode": self.mode_config.mode.value
                })
                
                if consecutive_errors >= max_errors:
                    logger.critical("Too many consecutive errors, emergency shutdown")
                    break
                
                await asyncio.sleep(60)  # Wait 1 minute on error
    
    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("🔄 Shutting down trading system...")
        self.running = False
        
        # Send final summary
        summary = await self.risk_manager.get_daily_summary()
        summary["mode"] = self.mode_config.mode.value
        await self.notification_service.send_daily_summary(summary)
        
        # Close database connections
        await self.risk_manager.close()
        
        logger.info("✅ Trading system shutdown complete")

async def main():
    """Main entry point."""
    try:
        # Load configuration
        config_dict = config.get_config()
        logger.info(f"🚀 Starting {config_dict['MODE']} Mode Trading System")
        
        # Initialize controller
        controller = BotController(config_dict)
        
        # Initialize system
        if not await controller.initialize():
            logger.error("❌ System initialization failed")
            sys.exit(1)
        
        # Start trading loop
        await controller.trading_loop()
        
    except KeyboardInterrupt:
        logger.info("👋 Interrupted by user")
    except Exception as e:
        logger.critical(f"💥 Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("👋 Trading system stopped")

if __name__ == "__main__":
    # Set mode from environment if provided
    if os.getenv("MODE"):
        os.environ["MODE"] = os.getenv("MODE")
        config.reload_config()
    
    asyncio.run(main())
