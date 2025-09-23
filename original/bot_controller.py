"""
Main trading bot controller with error recovery and market hours check
"""
import time
import logging
from datetime import datetime
import os
import signal
import sys
from typing import Optional

from config_loader import ConfigLoader
from data_fetcher import DataFetcher
from strategy import Strategy  # Assuming your existing strategy.py
from risk_manager import RiskManager  # Assuming your existing risk_manager.py
from trading_service import TradingService  # Assuming your existing trading_service.py
from telegram_service import TelegramService  # Assuming your existing telegram_service.py
from database_layer import DatabaseLayer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot_controller.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class BotController:
    """Main trading bot orchestrator"""
    
    def __init__(self, mode: str = 'TEST'):
        logger.info(f"Initializing BotController in {mode} mode")
        
        # Load configuration
        try:
            self.config = ConfigLoader.load()
        except Exception as e:
            logger.error(f"Configuration load failed: {e}")
            sys.exit(1)
        
        # Initialize components
        self.mode = mode
        self.db = DatabaseLayer()
        self.session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.daily_trades = 0
        
        self.fetcher = DataFetcher(self.config)
        self.strategy = Strategy(self.config)
        self.risk_manager = RiskManager(self.config, self.db)
        self.trading_service = TradingService(self.config, self.mode)
        self.telegram = TelegramService(self.config)
        
        # Graceful shutdown flag
        self._running = True
        
        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info(f"BotController initialized successfully - Session ID: {self.session_id}")
    
    def _signal_handler(self, signum, frame):
        """Handle graceful shutdown signals"""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self._running = False
    
    def is_market_open(self) -> bool:
        """Check if market is currently open"""
        return self.fetcher.is_market_open()
    
    def run_trading_cycle(self) -> bool:
        """Execute one complete trading cycle"""
        cycle_start = datetime.now()
        logger.debug(f"Starting trading cycle at {cycle_start}")
        
        try:
            # 1. Market hours check
            if not self.is_market_open():
                logger.debug("Market is closed - skipping cycle")
                return True  # Not an error, just no trading
            
            # 2. Fetch market data
            logger.info("Fetching market data...")
            df = self.fetcher.fetch_historical_data(
                self.config['instrument_token'], 
                days_back=5
            )
            
            if df is None or df.empty:
                logger.warning("No market data available - skipping cycle")
                return True
            
            # 3. Fetch options chain
            options_chain = self.fetcher.fetch_options_chain()
            if options_chain is None:
                logger.warning("No options chain data - skipping cycle")
                return True
            
            # 4. Get current spot price
            spot_price = self.fetcher.get_current_spot(df)
            if spot_price is None:
                logger.warning("Could not determine spot price - skipping cycle")
                return True
            
            logger.info(f"Spot price: {spot_price:.2f}, Data points: {len(df)}")
            
            # 5. Generate trading signal
            logger.info("Generating trading signal...")
            signal = self.strategy.generate_signal(df, options_chain, spot_price)
            
            if signal is None:
                logger.debug("No trading signal generated")
                return True
            
            logger.info(f"Trading signal generated: {signal}")
            
            # 6. Risk management check
            logger.info("Performing risk assessment...")
            risk_result = self.risk_manager.assess_risk(
                signal, 
                self.daily_trades, 
                self.session_id
            )
            
            if not risk_result['approved']:
                logger.info(f"Risk check failed: {risk_result['reason']}")
                self.telegram.send_alert(
                    f"🚫 Trade rejected - {risk_result['reason']}\n"
                    f"Signal: {signal['direction']} {signal['strike']}"
                )
                return True
            
            # 7. Execute trade
            logger.info("Executing trade...")
            trade_result = self.trading_service.execute_trade(
                signal, 
                risk_result['quantity'], 
                self.mode,
                self.session_id
            )
            
            if trade_result['success']:
                self.daily_trades += 1
                # Record trade in database
                trade_data = {
                    'date': datetime.now().date(),
                    'session_id': self.session_id,
                    'side': signal['direction'].upper(),
                    'strike': signal['strike'],
                    'quantity': risk_result['quantity'],
                    'entry_price': trade_result['entry_price'],
                    'signal_strength': signal.get('signal_strength', 0.0),
                    'mode': self.mode
                }
                
                if self.db.record_trade(trade_data):
                    logger.info(f"Trade recorded successfully - Qty: {risk_result['quantity']}")
                
                # Send success alert
                self.telegram.send_alert(
                    f"✅ TRADE EXECUTED\n"
                    f"📈 Direction: {signal['direction'].upper()}\n"
                    f"🎯 Strike: {signal['strike']}\n"
                    f"📊 Quantity: {risk_result['quantity']}\n"
                    f"💰 Entry: ₹{trade_result['entry_price']:.2f}\n"
                    f"⚡ Strength: {signal.get('signal_strength', 0):.1f}%"
                )
            else:
                logger.error(f"Trade execution failed: {trade_result['error']}")
                self.telegram.send_alert(
                    f"❌ Trade failed: {trade_result['error']}\n"
                    f"Signal: {signal['direction']} {signal['strike']}"
                )
            
            return True
            
        except Exception as e:
            logger.error(f"Trading cycle failed with exception: {e}", exc_info=True)
            
            # Send critical alert
            error_msg = f"🚨 CRITICAL ERROR in trading cycle\n{str(e)}"
            self.telegram.send_alert(error_msg)
            
            # Don't exit - continue to next cycle
            return False
    
    def print_status(self):
        """Print current system status"""
        stats = self.db.get_daily_stats(datetime.now(), self.session_id)
        
        status_msg = (
            f"🤖 Bot Status: {'🟢 LIVE' if self.mode == 'LIVE' else '🟡 TEST'}\n"
            f"📊 Session: {self.session_id}\n"
            f"📈 Trades Today: {self.daily_trades}\n"
            f"💰 P&L: ₹{stats['total_pnl']:,.2f}\n"
            f"⚠️ Consecutive SL: {stats['consecutive_sl']}\n"
            f"🕐 Next cycle in: 3:00 min"
        )
        
        logger.info(status_msg)
        self.telegram.send_status(status_msg)
    
    def run(self):
        """Main trading loop"""
        logger.info("Starting main trading loop...")
        self.telegram.send_alert(f"🚀 Trading bot started in {self.mode} mode - Session: {self.session_id}")
        
        cycle_number = 0
        
        while self._running:
            try:
                cycle_number += 1
                logger.info(f"=== Starting cycle #{cycle_number} ===")
                
                # Execute trading cycle
                success = self.run_trading_cycle()
                
                if success:
                    # Print status every 5 cycles
                    if cycle_number % 5 == 0:
                        self.print_status()
                else:
                    logger.warning("Cycle failed - waiting longer before retry")
                    time.sleep(300)  # Wait 5 minutes on error
                
                # Wait for next cycle (3 minutes)
                if self._running:
                    logger.info("Cycle completed. Waiting 3 minutes for next cycle...")
                    time.sleep(180)
                
            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt")
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
                self.telegram.send_alert(f"🚨 Main loop error: {str(e)}")
                time.sleep(60)  # Wait 1 minute before retry
        
        # Graceful shutdown
        logger.info("Shutting down gracefully...")
        self.telegram.send_alert(f"🛑 Trading bot stopped - Session: {self.session_id}")
        logger.info("BotController shutdown complete")

def main():
    """Entry point for the trading bot"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Sensex Options Trading Bot')
    parser.add_argument('--mode', choices=['LIVE', 'TEST', 'DEBUG'], 
                       default='TEST', help='Trading mode')
    parser.add_argument('--once', action='store_true', 
                       help='Run one cycle and exit')
    
    args = parser.parse_args()
    
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    try:
        controller = BotController(mode=args.mode)
        
        if args.once:
            logger.info("Running single cycle mode...")
            controller.run_trading_cycle()
            controller.print_status()
        else:
            controller.run()
            
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
