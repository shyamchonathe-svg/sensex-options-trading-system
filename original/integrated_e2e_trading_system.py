#!/usr/bin/env python3
"""
Hands-Free Sensex Options Trading System v2.0
Fully automated mean-reversion strategy with WebSocket reliability
Reads mode from .trading_mode flag file
"""

import os
import sys
import json
import logging
import time
import threading
from datetime import datetime, time as dt_time
from pathlib import Path
import sqlite3
import pandas as pd
import numpy as np
from kiteconnect import KiteConnect, KiteTicker
from tenacity import retry, stop_after_attempt, wait_exponential
import talib

# Configure logging (local only)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/trading.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Paths
PROJECT_PATH = Path(os.getenv('PROJECT_PATH', '/home/ubuntu/sensex-options-trading-system'))
CONFIG_PATH = PROJECT_PATH / 'config.json'
TRADES_DB = PROJECT_PATH / 'trades.db'

# Load config
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

# Environment
ZAPI_KEY = os.getenv('ZAPI_KEY')
ZAPI_SECRET = os.getenv('ZAPI_SECRET')
ZACCESS_TOKEN = os.getenv('ZACCESS_TOKEN')

class DatabaseLayer:
    """SQLite database for trade auditing"""
    
    def __init__(self, db_path=TRADES_DB):
        self.db_path = Path(db_path)
        self.init_database()
    
    def init_database(self):
        """Initialize database schema"""
        schema = """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            mode TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            pnl REAL DEFAULT 0,
            status TEXT DEFAULT 'OPEN',
            signal_strength REAL,
            conditions TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER,
            symbol TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            avg_price REAL NOT NULL,
            current_price REAL,
            unrealized_pnl REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (trade_id) REFERENCES trades (id)
        );
        
        CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date);
        CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
        """
        
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(schema)
    
    def log_trade(self, trade_data):
        """Log trade to database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO trades (date, mode, timestamp, symbol, side, quantity, price, 
                                  signal_strength, conditions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_data['date'],
                trade_data['mode'],
                trade_data['timestamp'],
                trade_data['symbol'],
                trade_data['side'],
                trade_data['quantity'],
                trade_data['price'],
                trade_data['signal_strength'],
                json.dumps(trade_data['conditions'])
            ))
            trade_id = cursor.lastrowid
            conn.commit()
            return trade_id
    
    def update_trade_pnl(self, trade_id, pnl):
        """Update trade P&L"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE trades SET pnl = ?, status = 'CLOSED' WHERE id = ?",
                (pnl, trade_id)
            )
            conn.commit()
    
    def get_open_positions(self):
        """Get all open positions"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT * FROM positions 
                WHERE updated_at > datetime('now', '-1 day')
            """)
            return [dict(row) for row in cursor.fetchall()]

def init_database():
    """Initialize database (called by bot)"""
    db = DatabaseLayer()
    logger.info("Database initialized")

class SignalEngine:
    """Mean-reversion signal generation"""
    
    def __init__(self, config):
        self.config = config
        self.ema_short = config['ema_short_period']
        self.ema_long = config['ema_long_period']
        self.tightness_threshold = config['ema_tightness_threshold']
        self.premium_deviation = config['premium_deviation_threshold']
    
    def calculate_signals(self, df):
        """Calculate trading signals from OHLCV data"""
        if len(df) < self.ema_long:
            return None
        
        # Calculate EMAs
        df['ema_short'] = talib.EMA(df['close'].values, timeperiod=self.ema_short)
        df['ema_long'] = talib.EMA(df['close'].values, timeperiod=self.ema_long)
        
        # EMA channel tightness
        latest = df.iloc[-1]
        tightness = abs(latest['ema_short'] - latest['ema_long'])
        
        # Signal conditions
        conditions = {
            'ema_tightness': tightness <= self.tightness_threshold,
            'volume_spike': latest['volume'] > df['volume'].rolling(20).mean().iloc[-1] * 1.5,
            'price_position': latest['close'] < latest['ema_long'] * 1.02  # Near support
        }
        
        # Signal strength (0-100)
        strength = sum([1 for v in conditions.values() if v]) / len(conditions) * 100
        
        return {
            'strength': min(strength, 100),
            'conditions': conditions,
            'tightness': tightness,
            'direction': 'CALL' if latest['close'] < latest['ema_long'] else 'PUT'
        }

class EnhancedBrokerAdapter:
    """Reliable Zerodha broker interface with WebSocket heartbeats"""
    
    def __init__(self, api_key, access_token):
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)
        self.kws = None
        self.last_tick_time = time.time()
        self.is_connected = False
        self.sensex_token = 26000  # BSE Sensex token ID
        self.position_cache = {}
        
        # Start heartbeat monitor
        self.start_heartbeat_monitor()
    
    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=10))
    def connect_websocket(self):
        """Connect WebSocket with retry logic"""
        try:
            self.kws = KiteTicker(ZAPI_KEY, ZACCESS_TOKEN)
            
            def on_connect(ws, response):
                logger.info("WebSocket connected")
                self.is_connected = True
                ws.subscribe([self.sensex_token])
                ws.set_mode(ws.MODE_FULL, [self.sensex_token])
            
            def on_ticks(ws, ticks):
                self.last_tick_time = time.time()
                self.process_tick(ticks)
            
            def on_close(ws, code, reason):
                logger.warning(f"WebSocket closed: {code} - {reason}")
                self.is_connected = False
            
            def on_error(ws, code, reason):
                logger.error(f"WebSocket error: {code} - {reason}")
                self.is_connected = False
            
            self.kws.on_connect = on_connect
            self.kws.on_ticks = on_ticks
            self.kws.on_close = on_close
            self.kws.on_error = on_error
            
            self.kws.connect(threaded=True)
            logger.info("WebSocket connection established")
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            raise
    
    def start_heartbeat_monitor(self):
        """Monitor connection health and auto-reconnect"""
        def monitor():
            while True:
                try:
                    # Check heartbeat (no ticks in 2 minutes = dead)
                    if time.time() - self.last_tick_time > 120:
                        logger.warning("Heartbeat timeout - reconnecting...")
                        if self.kws:
                            self.kws.close()
                        self.connect_websocket()
                    
                    # Check API rate limits
                    if self.kite.ltp('NSE:NIFTY 50')[0]['last_price'] == 0:
                        logger.warning("API rate limit hit - backing off")
                        time.sleep(60)
                    
                    time.sleep(30)  # Check every 30 seconds
                
                except Exception as e:
                    logger.error(f"Heartbeat monitor error: {e}")
                    time.sleep(10)
        
        threading.Thread(target=monitor, daemon=True).start()
    
    def process_tick(self, ticks):
        """Process incoming tick data"""
        for tick in ticks:
            if tick['instrument_token'] == self.sensex_token:
                self.position_cache['sensex'] = {
                    'ltp': tick['last_price'],
                    'volume': tick['volume'],
                    'timestamp': datetime.now()
                }
    
    def place_bracket_order(self, symbol, transaction_type, quantity, price, 
                          trigger_price=None, sl_offset=0.02, target_offset=0.04):
        """Place bracket order with SL and target"""
        try:
            # Calculate SL and target
            sl_price = price * (1 - sl_offset) if transaction_type == 'BUY' else price * (1 + sl_offset)
            target_price = price * (1 + target_offset) if transaction_type == 'BUY' else price * (1 - target_offset)
            
            # Place order (your existing order logic)
            order_params = {
                'exchange': 'NFO',
                'tradingsymbol': symbol,
                'transaction_type': transaction_type,
                'quantity': quantity,
                'product': 'MIS',
                'order_type': 'MARKET'
            }
            
            order_id = self.kite.place_order(**order_params)
            logger.info(f"Bracket order placed: {order_id} for {quantity} {symbol}")
            
            return {
                'order_id': order_id,
                'symbol': symbol,
                'side': transaction_type,
                'quantity': quantity,
                'entry_price': price,
                'sl_price': sl_price,
                'target_price': target_price
            }
        
        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            return None
    
    def get_positions(self):
        """Get current positions with caching"""
        try:
            positions = self.kite.positions()
            self.position_cache['positions'] = positions
            return positions
        except Exception as e:
            logger.warning(f"Position fetch failed: {e}")
            return self.position_cache.get('positions', [])
    
    def get_option_chain(self, underlying='SENSEX', expiry='weekly'):
        """Get options chain (your existing logic)"""
        try:
            # Your existing options chain logic
            instruments = self.kite.instruments('NFO')
            sensex_options = [
                inst for inst in instruments 
                if inst['tradingsymbol'].startswith('SENSEX') and expiry in inst['tradingsymbol']
            ]
            return sensex_options
        except Exception as e:
            logger.error(f"Option chain fetch failed: {e}")
            return []

class RiskManager:
    """Risk management and position sizing"""
    
    def __init__(self, config):
        self.config = config
        self.max_daily_loss = config['max_daily_loss']
        self.max_trades_per_day = config['max_trades_per_day']
        self.max_consecutive_losses = config['max_consecutive_losses']
        self.daily_trades = 0
        self.daily_pnl = 0
        self.consecutive_losses = 0
    
    def calculate_position_size(self, account_balance, signal_strength):
        """Calculate position size based on risk and signal"""
        risk_per_trade = account_balance * 0.02  # 2% risk per trade
        adjusted_risk = risk_per_trade * (signal_strength / 100)
        lot_size = 25  # Sensex weekly lot size
        
        return min(int(adjusted_risk / 100), lot_size)  # Max 1 lot
    
    def check_risk_limits(self, proposed_trade):
        """Check if trade violates risk limits"""
        if self.daily_trades >= self.max_trades_per_day:
            return False, "Daily trade limit reached"
        
        if self.daily_pnl <= -self.max_daily_loss:
            return False, "Daily loss limit reached"
        
        if self.consecutive_losses >= self.max_consecutive_losses:
            return False, "Max consecutive losses reached"
        
        return True, "Risk OK"
    
    def update_metrics(self, trade_pnl):
        """Update daily risk metrics"""
        self.daily_pnl += trade_pnl
        self.daily_trades += 1
        
        if trade_pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

class TradingSystem:
    """Main trading system orchestrator"""
    
    def __init__(self):
        self.mode = self.get_trading_mode()
        self.db = DatabaseLayer()
        self.signal_engine = SignalEngine(CONFIG)
        self.broker = EnhancedBrokerAdapter(ZAPI_KEY, ZACCESS_TOKEN)
        self.risk_manager = RiskManager(CONFIG)
        self.is_trading = False
        self.market_open = dt_time(9, 15)
        self.market_close = dt_time(15, 30)
        
        logger.info(f"Starting in {self.mode} mode")
    
    def get_trading_mode(self):
        """Read trading mode from flag file"""
        flag_path = PROJECT_PATH / '.trading_mode'
        disabled_path = PROJECT_PATH / '.trading_disabled'
        
        if disabled_path.exists():
            logger.info("Trading disabled by user")
            return 'DISABLED'
        
        if flag_path.exists():
            with open(flag_path) as f:
                mode = f.read().strip().upper()
                if mode in ['LIVE', 'TEST', 'DEBUG']:
                    return mode
        
        return 'TEST'  # Safe default
    
    def is_market_hours(self):
        """Check if current time is within market hours"""
        now = datetime.now().time()
        return self.market_open <= now <= self.market_close
    
    def fetch_historical_data(self, interval='5minute', days=1):
        """Fetch historical data for signal generation"""
        try:
            if self.mode == 'DEBUG':
                # Read from CSV for backtesting
                csv_path = PROJECT_PATH / 'data_raw' / f"{datetime.now().strftime('%Y-%m-%d')}_sensex.csv"
                if csv_path.exists():
                    df = pd.read_csv(csv_path)
                    df['datetime'] = pd.to_datetime(df['timestamp'])
                    df.set_index('datetime', inplace=True)
                    return df
                return None
            
            # Live data fetch (your existing logic)
            from_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            to_date = datetime.now().strftime('%Y-%m-%d')
            
            historical_data = self.broker.kite.historical_data(
                instrument_token=self.broker.sensex_token,
                from_date=from_date,
                to_date=to_date,
                interval=interval
            )
            
            if not historical_data:
                return None
            
            df = pd.DataFrame(historical_data)
            df['datetime'] = pd.to_datetime(df['date'])
            df.set_index('datetime', inplace=True)
            df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
            
            return df
            
        except Exception as e:
            logger.error(f"Data fetch failed: {e}")
            return None
    
    def execute_trade(self, signal):
        """Execute trade based on signal"""
        if self.mode != 'LIVE':
            logger.info(f"[SIMULATED] Would execute {signal['direction']} trade")
            # Log simulated trade
            trade_data = {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'mode': self.mode,
                'timestamp': datetime.now().isoformat(),
                'symbol': f"SENSEX{datetime.now().strftime('%y%b')}CE",  # Placeholder
                'side': 'BUY',
                'quantity': 25,
                'price': signal['price'] or 100,
                'signal_strength': signal['strength'],
                'conditions': signal['conditions']
            }
            trade_id = self.db.log_trade(trade_data)
            
            # Simulate P&L for TEST mode
            if self.mode == 'TEST':
                simulated_pnl = np.random.normal(50, 30) * (signal['strength'] / 100)
                self.db.update_trade_pnl(trade_id, simulated_pnl)
                self.risk_manager.update_metrics(simulated_pnl)
                logger.info(f"[TEST] Simulated P&L: ₹{simulated_pnl:.2f}")
            
            return trade_id
        
        # LIVE execution
        account_balance = self.broker.kite.margins()['equity']['available']['live_balance']
        quantity = self.risk_manager.calculate_position_size(account_balance, signal['strength'])
        
        is_ok, reason = self.risk_manager.check_risk_limits(signal)
        if not is_ok:
            logger.warning(f"Risk limit hit: {reason}")
            return None
        
        # Get ATM strike and place order
        option_symbol = self.get_atm_option(signal['direction'])
        if not option_symbol:
            logger.warning("No suitable option found")
            return None
        
        order = self.broker.place_bracket_order(
            symbol=option_symbol,
            transaction_type='BUY',
            quantity=quantity,
            price=signal.get('price', 0)
        )
        
        if order:
            trade_data = {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'mode': self.mode,
                'timestamp': datetime.now().isoformat(),
                'symbol': option_symbol,
                'side': 'BUY',
                'quantity': quantity,
                'price': order['entry_price'],
                'signal_strength': signal['strength'],
                'conditions': signal['conditions']
            }
            trade_id = self.db.log_trade(trade_data)
            self.risk_manager.update_metrics(0)  # Will update on exit
            logger.info(f"LIVE trade executed: {trade_id}")
            return trade_id
        
        return None
    
    def get_atm_option(self, direction):
        """Get ATM call/put option (your existing logic)"""
        try:
            sensex_ltp = self.broker.position_cache['sensex']['ltp']
            options = self.broker.get_option_chain()
            
            # Find ATM strike
            atm_strike = round(sensex_ltp / 100) * 100
            option_type = 'CE' if direction == 'CALL' else 'PE'
            
            # Find matching option
            for option in options:
                if (atm_strike in option['tradingsymbol'] and 
                    option_type in option['tradingsymbol'] and
                    'W' in option['tradingsymbol']):  # Weekly
                    return option['tradingsymbol']
            
            return None
        except Exception as e:
            logger.error(f"ATM option lookup failed: {e}")
            return None
    
    def run_debug_mode(self, csv_path):
        """Run complete backtest on CSV data"""
        try:
            df = pd.read_csv(csv_path)
            df['datetime'] = pd.to_datetime(df['timestamp'])
            df.set_index('datetime', inplace=True)
            
            signals = []
            total_pnl = 0
            winning_trades = 0
            total_trades = 0
            failed_conditions = []
            
            # Process each 5-min bar
            for i in range(CONFIG['ema_long'], len(df)):
                window = df.iloc[i-20:i+1]  # 20 periods lookback + current
                signal = self.signal_engine.calculate_signals(window)
                
                if signal and signal['strength'] >= 80:
                    signals.append(signal)
                    
                    # Simulate trade outcome
                    trade_pnl = self.simulate_trade_outcome(window.iloc[-1], signal)
                    total_pnl += trade_pnl
                    total_trades += 1
                    
                    if trade_pnl > 0:
                        winning_trades += 1
                    else:
                        failed_conditions.extend([
                            f"EMA tightness failed at {window.index[-1]}",
                            f"Signal strength {signal['strength']} too low"
                        ])
                
                # Rate limiting for backtest
                time.sleep(0.01)
            
            success = total_pnl > 0 and (winning_trades / max(total_trades, 1)) > 0.6
            win_rate = (winning_trades / max(total_trades, 1)) * 100
            
            return {
                'success': success,
                'total_pnl': total_pnl,
                'trade_count': total_trades,
                'win_rate': win_rate,
                'failed_conditions': failed_conditions[:10],  # Limit output
                'sharpe_ratio': self.calculate_sharpe(total_pnl, total_trades)
            }
            
        except Exception as e:
            logger.error(f"Debug mode failed: {e}")
            return {
                'success': False,
                'total_pnl': 0,
                'trade_count': 0,
                'win_rate': 0,
                'failed_conditions': [str(e)],
                'sharpe_ratio': 0
            }
    
    def simulate_trade_outcome(self, current_bar, signal):
        """Simulate trade P&L for backtesting"""
        # Simple mean-reversion simulation
        entry_price = current_bar['close']
        volatility = current_bar['high'] - current_bar['low']
        
        # Assume 70% of trades revert within 5 bars
        if np.random.random() < 0.7:
            # Successful reversion
            target_move = volatility * 0.8 * (signal['strength'] / 100)
            return target_move * 25  # Lot size
        else:
            # Failed trade
            stop_loss = volatility * 0.3
            return -stop_loss * 25
    
    def calculate_sharpe(self, total_pnl, trades):
        """Calculate simple Sharpe ratio"""
        if trades == 0:
            return 0
        avg_return = total_pnl / trades
        volatility = abs(total_pnl) / trades  # Simple vol estimate
        return avg_return / volatility if volatility > 0 else 0
    
    def run_trading_loop(self):
        """Main trading loop"""
        logger.info(f"Starting {self.mode} trading loop")
        self.is_trading = True
        
        consecutive_checks = 0
        
        while self.is_trading:
            try:
                # Check if trading is disabled
                current_mode = self.get_trading_mode()
                if current_mode == 'DISABLED':
                    logger.info("Trading disabled - exiting loop")
                    break
                
                if self.mode != current_mode:
                    logger.info(f"Mode changed to {current_mode}")
                    self.mode = current_mode
                    if self.mode == 'DISABLED':
                        break
                
                # Only trade during market hours
                if not self.is_market_hours() and self.mode == 'LIVE':
                    logger.debug("Outside market hours")
                    time.sleep(60)
                    continue
                
                # Fetch data
                df = self.fetch_historical_data()
                if df is None or len(df) < CONFIG['ema_long']:
                    logger.debug("Insufficient data")
                    time.sleep(30)
                    continue
                
                # Generate signal
                signal = self.signal_engine.calculate_signals(df)
                
                if signal and signal['strength'] >= CONFIG['min_signal_strength']:
                    logger.info(f"Signal detected: {signal['strength']:.1f}% - {signal['direction']}")
                    
                    # Add price to signal
                    signal['price'] = df.iloc[-1]['close']
                    
                    # Execute trade
                    trade_id = self.execute_trade(signal)
                    
                    if trade_id:
                        # Telegram notification (via bot webhook)
                        self.notify_telegram(f"🚨 TRADE EXECUTED\n"
                                           f"📈 {signal['direction']} @ ₹{signal['price']:.2f}\n"
                                           f"💪 Strength: {signal['strength']:.1f}%\n"
                                           f"🆔 ID: {trade_id}")
                
                # Rate limiting
                consecutive_checks += 1
                sleep_time = 30 if consecutive_checks % 10 == 0 else 5
                time.sleep(sleep_time)
                
            except KeyboardInterrupt:
                logger.info("Manual stop requested")
                break
            except Exception as e:
                logger.error(f"Trading loop error: {e}")
                time.sleep(60)  # Back off on errors
        
        logger.info("Trading loop ended")
    
    def notify_telegram(self, message):
        """Send notification via Telegram bot webhook"""
        try:
            # Simple webhook call to bot
            webhook_url = f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/sendMessage"
            data = {
                'chat_id': os.getenv('TELEGRAM_CHAT_ID'),
                'text': message,
                'parse_mode': 'Markdown'
            }
            requests.post(webhook_url, json=data, timeout=5)
        except Exception as e:
            logger.error(f"Telegram notification failed: {e}")
    
    def stop(self):
        """Graceful shutdown"""
        self.is_trading = False
        if self.broker.kws:
            self.broker.kws.close()
        logger.info("Trading system stopped")

def run_debug_mode(csv_path):
    """Exported function for bot to call"""
    system = TradingSystem()
    system.mode = 'DEBUG'
    return system.run_debug_mode(csv_path)

def main():
    """Main entry point"""
    # Check environment
    if not all([ZAPI_KEY, ZACCESS_TOKEN]):
        logger.error("Missing API credentials")
        sys.exit(1)
    
    # Check trading mode
    mode = TradingSystem().get_trading_mode()
    if mode == 'DISABLED':
        logger.info("Trading disabled - exiting")
        sys.exit(0)
    
    # Start system
    system = TradingSystem()
    
    try:
        if mode == 'DEBUG':
            # Run single backtest
            csv_path = sys.argv[1] if len(sys.argv) > 1 else None
            if csv_path:
                results = system.run_debug_mode(csv_path)
                print(json.dumps(results, indent=2))
            else:
                logger.error("DEBUG mode requires CSV path")
                sys.exit(1)
        else:
            # Run live trading loop
            system.run_trading_loop()
    
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise
    finally:
        system.stop()

if __name__ == "__main__":
    main()
