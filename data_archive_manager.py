#!/usr/bin/env python3
"""
Data Archive Manager - Handles historical data storage and replay
Supports ZIP-based storage for efficient debug mode
"""

import os
import glob
import zipfile
import tempfile
import json
import pandas as pd
from datetime import datetime
import pytz
from typing import Dict, Any, List, Optional
import logging
from config_manager import SecureConfigManager as ConfigManager
from signal_detection_system import SignalOrchestrator
from models import TradingSession


class DataArchiveManager:
    def __init__(self, config_manager: ConfigManager, signal_orchestrator: SignalOrchestrator):
        self.config_manager = config_manager
        self.config = config_manager.get_config()
        self.signal_orchestrator = signal_orchestrator
        self.logger = logging.getLogger(__name__)
        
        # Data directories
        self.data_dir = self.config.get('data_dir', 'option_data')
        self.raw_data_dir = os.path.join(self.data_dir, 'raw_data')
        self.archive_dir = os.path.join(self.data_dir, 'archives')
        
        # Ensure directories exist
        os.makedirs(self.raw_data_dir, exist_ok=True)
        os.makedirs(self.archive_dir, exist_ok=True)
        
        self.ist = pytz.timezone('Asia/Kolkata')
        self.logger.info("DataArchiveManager initialized")

    def list_available_dates(self, limit: int = 30) -> List[str]:
        """List available trading dates (most recent first)"""
        try:
            # Look for daily directories in reverse chronological order
            all_dates = []
            
            # Check current month first
            current_month = datetime.now(self.ist).strftime('%Y-%m')
            month_path = os.path.join(self.raw_data_dir, current_month)
            if os.path.exists(month_path):
                dates = sorted(
                    [d for d in os.listdir(month_path) if self._is_valid_date_dir(d)],
                    reverse=True
                )
                all_dates.extend(dates)
            
            # Check monthly archives
            for archive_file in glob.glob(f"{self.archive_dir}/*-monthly.zip"):
                month_dates = self._extract_dates_from_monthly_archive(archive_file)
                all_dates.extend(month_dates)
            
            # Remove duplicates and sort
            unique_dates = sorted(list(set(all_dates)), reverse=True)
            return unique_dates[:limit]
            
        except Exception as e:
            self.logger.error(f"Error listing dates: {e}")
            return []

    def _is_valid_date_dir(self, dirname: str) -> bool:
        """Check if directory name is valid date format"""
        try:
            datetime.strptime(dirname, '%Y-%m-%d')
            return True
        except ValueError:
            return False

    def _extract_dates_from_monthly_archive(self, monthly_zip: str) -> List[str]:
        """Extract available dates from monthly ZIP archive"""
        try:
            dates = []
            with zipfile.ZipFile(monthly_zip, 'r') as zf:
                for zip_info in zf.infolist():
                    if zip_info.filename.endswith('.zip') and '-' in zip_info.filename:
                        # Extract date from daily ZIP filename
                        filename = zip_info.filename
                        date_match = self._extract_date_from_filename(filename)
                        if date_match:
                            dates.append(date_match)
            return dates
        except Exception as e:
            self.logger.warning(f"Error reading monthly archive {monthly_zip}: {e}")
            return []

    def _extract_date_from_filename(self, filename: str) -> Optional[str]:
        """Extract YYYY-MM-DD from ZIP filename"""
        import re
        match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
        return match.group(1) if match else None

    async def replay_trading_day(self, date_str: str) -> Dict[str, Any]:
        """Replay complete trading day for debug analysis"""
        try:
            self.logger.info(f"Starting debug replay for {date_str}")
            
            # Step 1: Load data for the day
            data_files = await self._load_day_data(date_str)
            if not data_files:
                return {
                    'status': 'ERROR',
                    'reason': f'No data available for {date_str}',
                    'date': date_str
                }
            
            # Step 2: Create temporary DataManager with loaded data
            temp_data_manager = await self._create_temp_data_manager(data_files)
            
            # Step 3: Simulate trading session
            session = TradingSession(date=date_str)
            signals_detected = 0
            trades_executed = 0
            total_pnl = 0.0
            trades = []
            trades_blocked = 0
            block_reasons = []
            
            # Simulate 3-minute cycles throughout trading day
            market_open = pd.Timestamp(f"{date_str} 09:15:00+05:30")
            market_close = pd.Timestamp(f"{date_str} 15:30:00+05:30")
            current_time = market_open
            
            while current_time <= market_close:
                try:
                    # Get market data up to current time
                    sensex_data = temp_data_manager.get_historical_data_up_to(
                        'SENSEX', current_time
                    )
                    option_data = temp_data_manager.get_option_data_up_to(current_time)
                    
                    if len(sensex_data) < 20:  # Need minimum data for EMAs
                        current_time += timedelta(minutes=3)
                        continue
                    
                    # Detect signals
                    signals = self.signal_orchestrator.detect_entry_signals(
                        sensex_data=sensex_data,
                        ce_data=option_data['ce'],
                        pe_data=option_data['pe'],
                        strike=option_data['atm_strike'],
                        ce_symbol=option_data['ce_symbol'],
                        pe_symbol=option_data['pe_symbol']
                    )
                    
                    signals_detected += len(signals)
                    
                    # Process each signal
                    for signal in signals:
                        if signal.is_valid:
                            # Simulate risk check
                            risk_ok, risk_reason = await self._simulate_risk_check(signal, session)
                            
                            if risk_ok:
                                # Simulate trade execution
                                trade_result = await self._simulate_trade_execution(signal, current_time)
                                if trade_result['status'] == 'FILLED':
                                    trades_executed += 1
                                    total_pnl += trade_result['pnl']
                                    trades.append(trade_result)
                                    session.total_pnl += trade_result['pnl']
                            else:
                                trades_blocked += 1
                                block_reasons.append(risk_reason)
                    
                    current_time += timedelta(minutes=3)
                    
                except Exception as cycle_error:
                    self.logger.warning(f"Error in cycle {current_time}: {cycle_error}")
                    current_time += timedelta(minutes=3)
            
            # Calculate metrics
            win_rate = len([t for t in trades if t['pnl'] > 0]) / len(trades) * 100 if trades else 0
            avg_trade_pnl = sum(t['pnl'] for t in trades) / len(trades) if trades else 0
            max_loss = min([t['pnl'] for t in trades]) if trades else 0
            max_dd = self._calculate_max_drawdown(trades)
            sharpe = self._calculate_sharpe_ratio(trades)
            avg_hold_time = sum(t['hold_minutes'] for t in trades) / len(trades) if trades else 0
            
            # Signal breakdown
            sensex_trades = len([t for t in trades if t['signal_source'] == 'sensex'])
            option_trades = len(trades) - sensex_trades
            sensex_win_rate = (len([t for t in trades if t['signal_source'] == 'sensex' and t['pnl'] > 0]) / 
                              max(sensex_trades, 1)) * 100
            option_win_rate = ((len([t for t in trades if t['signal_source'] == 'option' and t['pnl'] > 0]) / 
                              max(option_trades, 1))) * 100
            
            result = {
                'status': 'SUCCESS',
                'date': date_str,
                'atm_strike': data_files.get('metadata', {}).get('sensex_atm', 0),
                'sensex_open': data_files.get('SENSEX', pd.DataFrame()).get('open', [0]).iloc[0] if data_files.get('SENSEX') is not None else 0,
                'sensex_close': data_files.get('SENSEX', pd.DataFrame()).get('close', [0]).iloc[-1] if data_files.get('SENSEX') is not None else 0,
                'signals_detected': signals_detected,
                'trades_executed': trades_executed,
                'total_pnl': total_pnl,
                'win_rate': win_rate,
                'avg_trade_pnl': avg_trade_pnl,
                'max_loss': max_loss,
                'max_dd': max_dd,
                'sharpe': sharpe,
                'avg_hold_time': avg_hold_time,
                'sensex_trades': sensex_trades,
                'option_trades': option_trades,
                'sensex_win_rate': sensex_win_rate,
                'option_win_rate': option_win_rate,
                'trades_blocked': trades_blocked,
                'block_reasons': block_reasons[:3],  # Top 3 reasons
                'trades': trades
            }
            
            self.logger.info(f"Debug replay complete for {date_str}: {trades_executed} trades, ₹{total_pnl:.0f} PnL")
            return result
            
        except Exception as e:
            self.logger.error(f"Debug replay failed for {date_str}: {e}")
            return {
                'status': 'ERROR',
                'reason': str(e),
                'date': date_str
            }

    async def _load_day_data(self, date_str: str) -> Dict[str, pd.DataFrame]:
        """Load all data files for a specific day"""
        try:
            # Try to find data in raw_data first (recent data)
            month_path = os.path.join(self.raw_data_dir, date_str[:7])
            day_path = os.path.join(month_path, date_str)
            
            if os.path.exists(day_path):
                # Load from uncompressed daily directory
                return await self._load_uncompressed_data(day_path)
            
            # Try monthly archive
            monthly_archive = os.path.join(self.archive_dir, f"{date_str[:7]}-monthly.zip")
            if os.path.exists(monthly_archive):
                return await self._load_from_monthly_archive(monthly_archive, date_str)
            
            # Try daily ZIP directly
            daily_zip = os.path.join(self.archive_dir, f"{date_str}.zip")
            if os.path.exists(daily_zip):
                return await self._load_from_daily_zip(daily_zip)
            
            self.logger.warning(f"No data found for {date_str}")
            return {}
            
        except Exception as e:
            self.logger.error(f"Error loading day data {date_str}: {e}")
            return {}

    async def _load_uncompressed_data(self, day_path: str) -> Dict[str, pd.DataFrame]:
        """Load uncompressed data from daily directory"""
        try:
            data = {}
            
            # Load metadata first
            metadata_path = os.path.join(day_path, 'metadata.json')
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    data['metadata'] = json.load(f)
            
            # Load all CSV files
            for csv_file in glob.glob(f"{day_path}/*.csv"):
                symbol = os.path.basename(csv_file).replace(f"_{os.path.basename(day_path)}.csv", "")
                try:
                    df = pd.read_csv(csv_file, index_col='timestamp', parse_dates=True)
                    df.index = pd.to_datetime(df.index).tz_localize('Asia/Kolkata')
                    data[symbol] = df
                    self.logger.debug(f"Loaded {len(df)} candles for {symbol}")
                except Exception as e:
                    self.logger.warning(f"Error loading {csv_file}: {e}")
            
            return data
            
        except Exception as e:
            self.logger.error(f"Error loading uncompressed data: {e}")
            return {}

    async def _load_from_monthly_archive(self, monthly_zip: str, date_str: str) -> Dict[str, pd.DataFrame]:
        """Load data from monthly ZIP archive"""
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                with zipfile.ZipFile(monthly_zip, 'r') as zf:
                    zf.extractall(temp_dir)
                
                # Find the daily ZIP
                daily_zip_path = None
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        if file == f"{date_str}.zip":
                            daily_zip_path = os.path.join(root, file)
                            break
                    if daily_zip_path:
                        break
                
                if daily_zip_path:
                    return await self._load_from_daily_zip(daily_zip_path)
                else:
                    self.logger.warning(f"Daily ZIP not found for {date_str} in monthly archive")
                    return {}
                    
        except Exception as e:
            self.logger.error(f"Error loading from monthly archive: {e}")
            return {}

    async def _load_from_daily_zip(self, daily_zip_path: str) -> Dict[str, pd.DataFrame]:
        """Load data from daily ZIP file"""
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                with zipfile.ZipFile(daily_zip_path, 'r') as zf:
                    zf.extractall(temp_dir)
                
                # Load all extracted CSV files
                return await self._load_uncompressed_data(temp_dir)
                
        except Exception as e:
            self.logger.error(f"Error loading from daily ZIP: {e}")
            return {}

    async def _create_temp_data_manager(self, data_files: Dict[str, pd.DataFrame]) -> Any:
        """Create temporary DataManager for replay"""
        # This would need to be a mock DataManager that uses the loaded data
        # For now, return the data_files directly for signal detection
        return data_files

    async def _simulate_risk_check(self, signal: Any, session: TradingSession) -> Tuple[bool, str]:
        """Simulate risk manager for debug mode"""
        # Simple simulation - allow first 3 trades, then block
        trades_taken = len([t for t in session.trades if t['status'] == 'FILLED'])
        
        if trades_taken >= 3:
            return False, "Max 3 trades per day"
        
        # Simulate 2-loss rule (block after 2 consecutive losses)
        recent_losses = sum(1 for t in session.trades[-2:] if t['pnl'] < 0)
        if recent_losses >= 2:
            return False, "Max 2 consecutive losses"
        
        return True, "Risk OK"

    async def _simulate_trade_execution(self, signal: Any, entry_time: datetime) -> Dict[str, Any]:
        """Simulate trade execution for debug mode"""
        try:
            # Simulate realistic fill (entry price + 0.5% slippage)
            slippage = signal.entry_price * 0.005  # 0.5% slippage
            filled_price = signal.entry_price + slippage if signal.option_type == 'CE' else signal.entry_price - slippage
            
            # Simulate exit after random hold time (5-60 minutes)
            import random
            hold_minutes = random.randint(5, 60)
            exit_time = entry_time + timedelta(minutes=hold_minutes)
            
            # Simulate exit price based on signal quality
            price_movement = random.uniform(-0.15, 0.25)  # -15% to +25% typical range
            exit_price = filled_price * (1 + price_movement * signal.confidence)
            
            # Calculate PnL
            pnl = (exit_price - filled_price) * signal.quantity
            
            return {
                'status': 'FILLED',
                'entry_time': entry_time,
                'exit_time': exit_time,
                'entry_price': filled_price,
                'exit_price': exit_price,
                'quantity': signal.quantity,
                'pnl': pnl,
                'hold_minutes': hold_minutes,
                'signal_source': signal.source.value,
                'symbol': signal.symbol,
                'strike': signal.strike,
                'exit_reason': 'random'  # In real debug, use actual exit logic
            }
            
        except Exception as e:
            self.logger.error(f"Simulated trade error: {e}")
            return {'status': 'ERROR', 'reason': str(e)}

    def _calculate_max_drawdown(self, trades: List[Dict]) -> float:
        """Calculate maximum drawdown from trade sequence"""
        if not trades:
            return 0.0
        
        cumulative_pnl = 0
        peak = 0
        max_dd = 0
        
        for trade in trades:
            cumulative_pnl += trade['pnl']
            peak = max(peak, cumulative_pnl)
            drawdown = (peak - cumulative_pnl) / abs(peak) if peak != 0 else 0
            max_dd = max(max_dd, drawdown)
        
        return max_dd * 100  # As percentage

    def _calculate_sharpe_ratio(self, trades: List[Dict]) -> float:
        """Calculate Sharpe ratio from trade returns"""
        if not trades or len(trades) < 2:
            return 0.0
        
        returns = [trade['pnl'] for trade in trades if trade['pnl'] != 0]
        if not returns:
            return 0.0
        
        avg_return = sum(returns) / len(returns)
        std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5
        
        return avg_return / std_return if std_return != 0 else 0

    async def get_performance_summary(self, days: int = 7) -> Dict[str, Any]:
        """Get performance summary for last N days"""
        try:
            available_dates = self.list_available_dates(limit=days * 2)  # Get extra for safety
            recent_dates = available_dates[:days]
            
            if not recent_dates:
                return {'status': 'NO_DATA', 'period_days': days}
            
            total_trades = 0
            total_pnl = 0.0
            wins = 0
            recent_trades = []
            
            for date in recent_dates:
                replay = await self.replay_trading_day(date)
                if replay['status'] == 'SUCCESS':
                    total_trades += replay['trades_executed']
                    total_pnl += replay['total_pnl']
                    wins += len([t for t in replay['trades'] if t['pnl'] > 0])
                    
                    # Keep last 5 trades for display
                    for trade in replay['trades'][-1:]:  # One per day max
                        recent_trades.append({
                            'date': date,
                            'symbol': trade['symbol'],
                            'pnl': trade['pnl'],
                            'time': trade['entry_time'].strftime('%H:%M')
                        })
            
            win_rate = (wins / max(total_trades, 1)) * 100
            avg_pnl = total_pnl / max(total_trades, 1)
            
            return {
                'status': 'SUCCESS',
                'period_days': len(recent_dates),
                'total_trades': total_trades,
                'total_pnl': total_pnl,
                'win_rate': win_rate,
                'avg_pnl': avg_pnl,
                'recent_trades': recent_trades[-5:],  # Last 5 trades
                'trades': total_trades  # For backward compatibility
            }
            
        except Exception as e:
            self.logger.error(f"Performance summary error: {e}")
            return {'status': 'ERROR', 'reason': str(e)}
