#!/usr/bin/env python3
"""
Market Close Data Collector - Runs at 3:25 PM to collect final 15 minutes
Saves complete dataset for debug mode replay
"""
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import logging
import os
import glob
import json
import pandas as pd
import pytz
from kiteconnect import KiteConnect
from config_manager import SecureConfigManager as ConfigManager
from optimized_sensex_option_chain import OptimizedSensexOptionChain
from notification_service import EnhancedNotificationService
class MarketCloseDataCollector:
    def __init__(self, config_manager: ConfigManager, option_chain: OptimizedSensexOptionChain):
        self.config_manager = config_manager
        self.config = config_manager.get_config()
        self.option_chain = option_chain
        self.logger = logging.getLogger(__name__)
        self.data_dir = self.config.get('data_dir', 'option_data')
        self.raw_data_dir = os.path.join(self.data_dir, 'raw_data')
        self.ist = pytz.timezone('Asia/Kolkata')
        
        # Ensure directories exist
        os.makedirs(self.raw_data_dir, exist_ok=True)
        os.makedirs(os.path.join(self.raw_data_dir, '2025-01'), exist_ok=True)  # Example
        
        self.logger.info("MarketCloseDataCollector initialized")

    async def should_collect_data(self) -> bool:
        """Check if it's time to collect data (3:25-3:30 PM IST)"""
        now = datetime.now(self.ist)
        market_close_time = now.replace(hour=15, minute=25, second=0, microsecond=0)
        five_minutes_later = market_close_time + timedelta(minutes=5)
        
        return market_close_time <= now <= five_minutes_later

    async def collect_full_day_data(self) -> Dict[str, Any]:
        """Collect complete day's data for all strikes"""
        try:
            if not await self.should_collect_data():
                self.logger.info("Not market close time - skipping data collection")
                return {'status': 'SKIPPED', 'reason': 'Not market close time'}
            
            today = datetime.now(self.ist).strftime('%Y-%m-%d')
            self.logger.info(f"Starting data collection for {today} at {datetime.now(self.ist).strftime('%H:%M:%S')}")
            
            # Create today's directory
            today_dir = os.path.join(self.raw_data_dir, today[:7], today)
            os.makedirs(today_dir, exist_ok=True)
            
            # Get current ATM strike
            sensex_price = await self.option_chain.get_sensex_spot_price()
            if not sensex_price:
                self.logger.error("Failed to get Sensex price")
                return {'status': 'ERROR', 'reason': 'No Sensex price'}
            
            atm_strike = int(sensex_price // 100) * 100
            strikes = list(range(atm_strike - 500, atm_strike + 600, 100))
            self.logger.info(f"Collecting data for strikes: {strikes}")
            
            all_data = {}
            collected_files = 0
            
            # Collect Sensex data first
            sensex_data = await self._collect_instrument_data('BSE:SENSEX', today, today_dir)
            if sensex_data:
                all_data['SENSEX'] = sensex_data
                collected_files += 1
            
            # Collect option data for all strikes
            for strike in strikes:
                symbols = self.option_chain.get_weekly_expiry_symbols(strike)
                if not symbols or 'error' in symbols:
                    self.logger.warning(f"No symbols for strike {strike}")
                    continue
                
                # Collect CE data
                ce_data = await self._collect_instrument_data(
                    symbols['ce_symbol'], today, today_dir
                )
                if ce_data is not None:
                    all_data[symbols['ce_symbol']] = ce_data
                    collected_files += 1
                
                # Collect PE data  
                pe_data = await self._collect_instrument_data(
                    symbols['pe_symbol'], today, today_dir
                )
                if pe_data is not None:
                    all_data[symbols['pe_symbol']] = pe_data
                    collected_files += 1
            
            # Save metadata
            metadata = {
                'collection_date': today,
                'collection_time': datetime.now(self.ist).isoformat(),
                'sensex_atm': atm_strike,
                'strikes_covered': strikes,
                'total_files': collected_files,
                'total_size_kb': sum(os.path.getsize(f) for f in glob.glob(f"{today_dir}/*.csv")),
                'sensex_range': {
                    'open': sensex_data['open'].iloc[0] if sensex_data is not None else 0,
                    'close': sensex_data['close'].iloc[-1] if sensex_data is not None else 0
                }
            }
            
            with open(os.path.join(today_dir, 'metadata.json'), 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Send confirmation
            await self._send_collection_confirmation(metadata, collected_files)
            
            self.logger.info(f"Data collection complete: {collected_files} files, {metadata['total_size_kb']}KB")
            return {
                'status': 'SUCCESS',
                'date': today,
                'files_collected': collected_files,
                'total_size_kb': metadata['total_size_kb'],
                'metadata': metadata
            }
            
        except Exception as e:
            self.logger.error(f"Data collection failed: {e}")
            return {'status': 'ERROR', 'reason': str(e)}

    async def _collect_instrument_data(self, symbol: str, date: str, output_dir: str) -> Optional[pd.DataFrame]:
        """Collect historical data for single instrument"""
        try:
            # Get instrument token
            exchange = "BFO" if "SENSEX" in symbol else "BSE"
            token = await self.option_chain.get_instrument_token(f"{exchange}:{symbol}")
            if not token:
                self.logger.warning(f"No token found for {symbol}")
                return None
            
            # Collect full day data (9:15 AM - 3:30 PM)
            data = self.option_chain.kite.historical_data(
                instrument_token=token,
                from_date=date,
                to_date=date,
                interval="3minute"
            )
            
            if not data:
                self.logger.warning(f"No data returned for {symbol}")
                return None
            
            # Convert to DataFrame
            df = pd.DataFrame(data)
            if df.empty:
                self.logger.warning(f"Empty DataFrame for {symbol}")
                return None
            
            # Handle timezone
            df['timestamp'] = pd.to_datetime(df['date']).dt.tz_localize('Asia/Kolkata')
            df = df.drop(columns=['date'])
            df.set_index('timestamp', inplace=True)
            
            # Calculate EMAs for faster replay
            df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
            df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
            
            # Filter to market hours (9:15 AM - 3:30 PM)
            market_open = pd.Timestamp(f"{date} 09:15:00+05:30")
            market_close = pd.Timestamp(f"{date} 15:30:00+05:30")
            df = df[(df.index >= market_open) & (df.index <= market_close)]
            
            # Save to CSV
            filename = os.path.join(output_dir, f"{symbol}_{date}.csv")
            df.to_csv(filename)
            
            self.logger.debug(f"Saved {len(df)} candles for {symbol}")
            return df
            
        except Exception as e:
            self.logger.error(f"Error collecting data for {symbol}: {e}")
            return None

    async def _send_collection_confirmation(self, metadata: Dict[str, Any], collected_files: int):
        """Send Telegram confirmation of data collection"""
        try:
            message = f"""
✅ <b>Daily Data Collection Complete</b>

📅 Date: {metadata['collection_date']}
⏰ Time: {datetime.now(self.ist).strftime('%H:%M:%S IST')}
📊 Files Collected: {collected_files}/22
💾 Total Size: {metadata['total_size_kb']:.0f}KB
🎯 ATM Strike: {metadata['sensex_atm']}
📈 Sensex Range: ₹{metadata['sensex_range']['open']:.0f} - ₹{metadata['sensex_range']['close']:.0f}

🔍 Ready for debug mode replay!
            """
            await self.notification_service.send_message(message)
        except Exception as e:
            self.logger.error(f"Failed to send collection confirmation: {e}")

    async def cleanup_old_data(self, retention_days: int = 90):
        """Clean up data older than retention period"""
        try:
            cutoff_date = (datetime.now(self.ist) - timedelta(days=retention_days)).strftime('%Y-%m-%d')
            
            for month_dir in glob.glob(f"{self.raw_data_dir}/*"):
                if os.path.isdir(month_dir):
                    for day_dir in glob.glob(f"{month_dir}/*"):
                        if day_dir.split('/')[-1] < cutoff_date:
                            # Archive to monthly ZIP if not already done
                            await self._archive_old_month(month_dir)
                            # Remove old directory
                            import shutil
                            shutil.rmtree(day_dir)
                            self.logger.info(f"Cleaned up old data: {day_dir}")
        except Exception as e:
            self.logger.error(f"Data cleanup failed: {e}")

    async def _archive_old_month(self, month_dir: str):
        """Create monthly ZIP archive for old data"""
        try:
            month_name = os.path.basename(month_dir)  # 2025-01
            monthly_zip = f"{self.raw_data_dir}/{month_name}-monthly.zip"
            
            if os.path.exists(monthly_zip):
                self.logger.info(f"Monthly archive already exists: {monthly_zip}")
                return
            
            import zipfile
            with zipfile.ZipFile(monthly_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
                for day_dir in glob.glob(f"{month_dir}/*"):
                    day_zip = f"{month_dir}/{os.path.basename(day_dir)}.zip"
                    if os.path.exists(day_zip):
                        zf.write(day_zip, os.path.basename(day_zip))
                    else:
                        # ZIP individual CSV files if no daily ZIP
                        for csv_file in glob.glob(f"{day_dir}/*.csv"):
                            zf.write(csv_file, f"{os.path.basename(day_dir)}/{os.path.basename(csv_file)}")
            
            self.logger.info(f"Created monthly archive: {monthly_zip}")
        except Exception as e:
            self.logger.error(f"Monthly archiving failed: {e}")
