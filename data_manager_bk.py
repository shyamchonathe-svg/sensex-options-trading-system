#!/usr/bin/env python3
"""
Data Manager - Core Data Layer for Sensex Trading Bot
Provides unified interface for data access, validation, and indicator calculations
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import logging
from typing import Dict, List, Optional, Tuple, Union
import pytz
from dataclasses import dataclass
import os
from enum import Enum


class DataQuality(Enum):
    """Data quality levels for validation results"""
    EXCELLENT = "excellent"
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    POOR = "poor"
    UNUSABLE = "unusable"


@dataclass
class DataValidationResult:
    """Result of data validation with quality metrics"""
    quality: DataQuality
    total_rows: int
    expected_rows: int
    missing_percentage: float
    gap_count: int
    issues: List[str]
    recommendations: List[str]


@dataclass
class InstrumentData:
    """Container for instrument data with metadata"""
    symbol: str
    data: pd.DataFrame
    validation: DataValidationResult
    indicators_calculated: bool = False
    last_updated: datetime = None


class DataManager:
    """
    Unified data manager for both test and live modes.
    Handles CSV storage, data validation, indicator calculations, and caching.
    """
    
    def __init__(self, data_directory: str = "option_data", timezone: str = "Asia/Kolkata"):
        """
        Initialize DataManager
        
        Args:
            data_directory: Base directory for CSV storage
            timezone: Market timezone for timestamp handling
        """
        self.logger = logging.getLogger(__name__)
        self.data_dir = Path(data_directory)
        self.data_dir.mkdir(exist_ok=True)
        self.timezone = pytz.timezone(timezone)
        
        # Cache for loaded data
        self._data_cache: Dict[str, InstrumentData] = {}
        
        # Configuration
        self.trading_hours = {
            'start': (9, 15),  # 9:15 AM
            'end': (15, 30)    # 3:30 PM
        }
        
        # Expected data points per trading day (3-minute intervals)
        self.expected_daily_rows = self._calculate_expected_rows()
        
        self.logger.info(f"DataManager initialized with data directory: {self.data_dir}")
    
    def _calculate_expected_rows(self) -> int:
        """Calculate expected number of 3-minute candles per trading day"""
        start_minutes = self.trading_hours['start'][0] * 60 + self.trading_hours['start'][1]
        end_minutes = self.trading_hours['end'][0] * 60 + self.trading_hours['end'][1]
        total_minutes = end_minutes - start_minutes
        return total_minutes // 3
    
    def _get_file_path(self, symbol: str, date: str) -> Path:
        """Generate file path for symbol and date"""
        filename = f"{symbol}_{date}.csv"
        return self.data_dir / filename
    
    def _validate_data(self, df: pd.DataFrame, symbol: str, date: str) -> DataValidationResult:
        """
        Validate data completeness and quality
        
        Args:
            df: DataFrame to validate
            symbol: Instrument symbol
            date: Trading date
            
        Returns:
            DataValidationResult with quality assessment
        """
        issues = []
        recommendations = []
        
        if df.empty:
            return DataValidationResult(
                quality=DataQuality.UNUSABLE,
                total_rows=0,
                expected_rows=self.expected_daily_rows,
                missing_percentage=100.0,
                gap_count=0,
                issues=["No data available"],
                recommendations=["Fetch fresh data from API"]
            )
        
        # Check required columns
        required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            issues.append(f"Missing required columns: {missing_cols}")
        
        # Check data completeness
        total_rows = len(df)
        missing_percentage = max(0, (self.expected_daily_rows - total_rows) / self.expected_daily_rows * 100)
        
        # Check for data gaps (missing timestamps)
        gap_count = 0
        if not df.empty and 'timestamp' in df.columns:
            df_sorted = df.sort_values('timestamp')
            time_diffs = df_sorted['timestamp'].diff()
            expected_diff = pd.Timedelta(minutes=3)
            gaps = time_diffs > expected_diff * 1.5  # Allow some tolerance
            gap_count = gaps.sum()
        
        # Check for invalid values
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in numeric_cols:
            if col in df.columns:
                if df[col].isna().any():
                    issues.append(f"NaN values found in {col}")
                if (df[col] <= 0).any() and col != 'volume':  # Volume can be 0
                    issues.append(f"Invalid values (<=0) found in {col}")
        
        # Determine quality level
        if missing_percentage <= 5 and gap_count <= 2 and not issues:
            quality = DataQuality.EXCELLENT
        elif missing_percentage <= 10 and gap_count <= 5 and len(issues) <= 1:
            quality = DataQuality.GOOD
        elif missing_percentage <= 20 and gap_count <= 10:
            quality = DataQuality.ACCEPTABLE
            recommendations.append("Consider refetching data for better quality")
        elif missing_percentage <= 50:
            quality = DataQuality.POOR
            recommendations.append("Data quality is poor - results may be unreliable")
        else:
            quality = DataQuality.UNUSABLE
            recommendations.append("Data quality too poor for analysis")
        
        return DataValidationResult(
            quality=quality,
            total_rows=total_rows,
            expected_rows=self.expected_daily_rows,
            missing_percentage=missing_percentage,
            gap_count=gap_count,
            issues=issues,
            recommendations=recommendations
        )
    
    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate technical indicators for the dataset
        
        Args:
            df: OHLC DataFrame
            
        Returns:
            DataFrame with indicators added
        """
        if df.empty:
            return df
        
        # Create a copy to avoid modifying original
        result_df = df.copy()
        
        # Calculate EMAs
        result_df['ema10'] = result_df['close'].ewm(span=10, adjust=False).mean()
        result_df['ema20'] = result_df['close'].ewm(span=20, adjust=False).mean()
        
        # Add derived indicators
        result_df['ema_diff'] = result_df['ema10'] - result_df['ema20']
        result_df['ema_diff_abs'] = abs(result_df['ema_diff'])
        
        # Candle type identification
        result_df['is_green'] = result_df['close'] > result_df['open']
        result_df['candle_body'] = abs(result_df['close'] - result_df['open'])
        result_df['upper_shadow'] = result_df['high'] - result_df[['open', 'close']].max(axis=1)
        result_df['lower_shadow'] = result_df[['open', 'close']].min(axis=1) - result_df['low']
        
        # Price proximity to EMAs
        result_df['open_ema10_diff'] = abs(result_df['open'] - result_df['ema10'])
        result_df['low_ema10_diff'] = abs(result_df['low'] - result_df['ema10'])
        result_df['close_ema10_diff'] = abs(result_df['close'] - result_df['ema10'])
        result_df['min_ema10_proximity'] = result_df[['open_ema10_diff', 'low_ema10_diff']].min(axis=1)
        
        self.logger.debug(f"Calculated indicators for {len(result_df)} rows")
        return result_df
    
    def _load_from_csv(self, symbol: str, date: str) -> Optional[pd.DataFrame]:
        """
        Load data from CSV file
        
        Args:
            symbol: Instrument symbol
            date: Trading date (YYYY-MM-DD)
            
        Returns:
            DataFrame or None if file doesn't exist
        """
        file_path = self._get_file_path(symbol, date)
        
        if not file_path.exists():
            self.logger.warning(f"CSV file not found: {file_path}")
            return None
        
        try:
            df = pd.read_csv(file_path)
            
            # Ensure timestamp column exists and is properly formatted
            if 'timestamp' not in df.columns:
                self.logger.error(f"Timestamp column missing in {file_path}")
                return None
            
            # Parse timestamps and set timezone
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            df = df.dropna(subset=['timestamp'])
            
            # Set timezone if not already set
            if df['timestamp'].dt.tz is None:
                df['timestamp'] = df['timestamp'].dt.tz_localize(self.timezone)
            else:
                df['timestamp'] = df['timestamp'].dt.tz_convert(self.timezone)
            
            # Set timestamp as index
            df.set_index('timestamp', inplace=True)
            df.sort_index(inplace=True)
            
            self.logger.debug(f"Loaded {len(df)} rows from {file_path}")
            return df
            
        except Exception as e:
            self.logger.error(f"Error loading CSV {file_path}: {e}")
            return None
    
    def _combine_with_previous_day(self, current_df: pd.DataFrame, symbol: str, 
                                  current_date: str, market_holidays: List[str] = None) -> pd.DataFrame:
        """
        Combine current day data with previous trading day for indicator calculations
        
        Args:
            current_df: Current day DataFrame
            symbol: Instrument symbol
            current_date: Current trading date
            market_holidays: List of holiday dates to skip
            
        Returns:
            Combined DataFrame with previous day data
        """
        if market_holidays is None:
            market_holidays = []
        
        # Find previous trading day
        current = datetime.strptime(current_date, "%Y-%m-%d").date()
        prev_day = current - timedelta(days=1)
        
        # Skip weekends and holidays
        holiday_dates = [datetime.strptime(h, "%Y-%m-%d").date() for h in market_holidays]
        
        while prev_day.weekday() >= 5 or prev_day in holiday_dates:
            prev_day -= timedelta(days=1)
        
        prev_date_str = prev_day.strftime("%Y-%m-%d")
        
        # Load previous day data
        prev_df = self._load_from_csv(symbol, prev_date_str)
        
        if prev_df is None or prev_df.empty:
            self.logger.warning(f"No previous day data found for {symbol} on {prev_date_str}")
            return current_df
        
        # Combine DataFrames
        combined_df = pd.concat([prev_df, current_df])
        combined_df = combined_df.sort_index()
        
        # Remove duplicates (keep latest)
        combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
        
        self.logger.debug(f"Combined data: {len(prev_df)} prev + {len(current_df)} current = {len(combined_df)} total")
        return combined_df
    
    def save_data(self, symbol: str, date: str, data: pd.DataFrame) -> bool:
        """
        Save DataFrame to CSV file
        
        Args:
            symbol: Instrument symbol
            date: Trading date
            data: DataFrame to save
            
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            file_path = self._get_file_path(symbol, date)
            
            # Prepare data for saving
            save_df = data.copy()
            
            # Reset index to make timestamp a column
            if save_df.index.name == 'timestamp':
                save_df.reset_index(inplace=True)
            
            # Ensure required columns are present
            required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            save_df = save_df[required_cols + [col for col in save_df.columns if col not in required_cols]]
            
            # Save to CSV
            save_df.to_csv(file_path, index=False)
            
            self.logger.info(f"Saved {len(save_df)} rows to {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error saving data to CSV: {e}")
            return False
    
    def get_instrument_data(self, symbol: str, date: str, with_indicators: bool = True,
                           include_previous_day: bool = True, 
                           market_holidays: List[str] = None) -> Optional[InstrumentData]:
        """
        Get instrument data with validation and optional indicators
        
        Args:
            symbol: Instrument symbol
            date: Trading date (YYYY-MM-DD)
            with_indicators: Whether to calculate technical indicators
            include_previous_day: Whether to include previous day data for indicators
            market_holidays: List of market holidays
            
        Returns:
            InstrumentData object or None if data unavailable
        """
        cache_key = f"{symbol}_{date}_{with_indicators}_{include_previous_day}"
        
        # Check cache first
        if cache_key in self._data_cache:
            cached_data = self._data_cache[cache_key]
            if cached_data.last_updated and (datetime.now() - cached_data.last_updated).seconds < 300:
                self.logger.debug(f"Returning cached data for {cache_key}")
                return cached_data
        
        # Load from CSV
        df = self._load_from_csv(symbol, date)
        
        if df is None:
            self.logger.error(f"No data available for {symbol} on {date}")
            return None
        
        # Combine with previous day if requested
        if include_previous_day:
            df = self._combine_with_previous_day(df, symbol, date, market_holidays)
        
        # Calculate indicators if requested
        if with_indicators:
            df = self._calculate_indicators(df)
        
        # Validate data quality
        validation = self._validate_data(df, symbol, date)
        
        # Create InstrumentData object
        instrument_data = InstrumentData(
            symbol=symbol,
            data=df,
            validation=validation,
            indicators_calculated=with_indicators,
            last_updated=datetime.now()
        )
        
        # Cache the result
        self._data_cache[cache_key] = instrument_data
        
        # Log validation results
        if validation.quality in [DataQuality.POOR, DataQuality.UNUSABLE]:
            self.logger.warning(f"Data quality for {symbol} on {date}: {validation.quality.value}")
            for issue in validation.issues:
                self.logger.warning(f"  - {issue}")
        
        return instrument_data
    
    def append_latest_data(self, symbol: str, date: str, new_candle: Dict) -> bool:
        """
        Append new candle data to existing CSV
        
        Args:
            symbol: Instrument symbol
            date: Trading date
            new_candle: Dictionary with OHLCV data and timestamp
            
        Returns:
            True if appended successfully, False otherwise
        """
        try:
            # Load existing data
            existing_df = self._load_from_csv(symbol, date)
            
            if existing_df is None:
                # Create new DataFrame if file doesn't exist
                new_df = pd.DataFrame([new_candle])
                new_df['timestamp'] = pd.to_datetime(new_df['timestamp']).dt.tz_localize(self.timezone)
                new_df.set_index('timestamp', inplace=True)
            else:
                # Append to existing data
                new_row = pd.DataFrame([new_candle])
                new_row['timestamp'] = pd.to_datetime(new_row['timestamp']).dt.tz_localize(self.timezone)
                new_row.set_index('timestamp', inplace=True)
                
                new_df = pd.concat([existing_df, new_row])
                new_df = new_df[~new_df.index.duplicated(keep='last')]
                new_df.sort_index(inplace=True)
            
            # Save updated data
            success = self.save_data(symbol, date, new_df)
            
            if success:
                # Invalidate cache
                cache_keys_to_remove = [key for key in self._data_cache.keys() if key.startswith(f"{symbol}_{date}")]
                for key in cache_keys_to_remove:
                    del self._data_cache[key]
                
                self.logger.debug(f"Appended new candle for {symbol} on {date}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error appending data for {symbol}: {e}")
            return False
    
    def validate_data_completeness(self, symbol: str, date: str) -> DataValidationResult:
        """
        Validate data completeness without loading full dataset
        
        Args:
            symbol: Instrument symbol
            date: Trading date
            
        Returns:
            DataValidationResult
        """
        file_path = self._get_file_path(symbol, date)
        
        if not file_path.exists():
            return DataValidationResult(
                quality=DataQuality.UNUSABLE,
                total_rows=0,
                expected_rows=self.expected_daily_rows,
                missing_percentage=100.0,
                gap_count=0,
                issues=["File does not exist"],
                recommendations=["Fetch data from API"]
            )
        
        try:
            # Quick row count without loading full data
            with open(file_path, 'r') as f:
                row_count = sum(1 for line in f) - 1  # Subtract header
            
            missing_percentage = max(0, (self.expected_daily_rows - row_count) / self.expected_daily_rows * 100)
            
            # Basic quality assessment based on row count
            if missing_percentage <= 5:
                quality = DataQuality.EXCELLENT
            elif missing_percentage <= 10:
                quality = DataQuality.GOOD
            elif missing_percentage <= 20:
                quality = DataQuality.ACCEPTABLE
            elif missing_percentage <= 50:
                quality = DataQuality.POOR
            else:
                quality = DataQuality.UNUSABLE
            
            return DataValidationResult(
                quality=quality,
                total_rows=row_count,
                expected_rows=self.expected_daily_rows,
                missing_percentage=missing_percentage,
                gap_count=0,  # Would need full data to calculate
                issues=[],
                recommendations=[]
            )
            
        except Exception as e:
            self.logger.error(f"Error validating data completeness: {e}")
            return DataValidationResult(
                quality=DataQuality.UNUSABLE,
                total_rows=0,
                expected_rows=self.expected_daily_rows,
                missing_percentage=100.0,
                gap_count=0,
                issues=[f"Validation error: {e}"],
                recommendations=["Check file integrity"]
            )
    
    def cleanup_old_data(self, retention_days: int = 30) -> int:
        """
        Clean up old CSV files beyond retention period
        
        Args:
            retention_days: Number of days to keep
            
        Returns:
            Number of files deleted
        """
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        deleted_count = 0
        
        try:
            for file_path in self.data_dir.glob("*.csv"):
                # Extract date from filename
                parts = file_path.stem.split('_')
                if len(parts) >= 2:
                    date_part = parts[-1]  # Last part should be date
                    try:
                        file_date = datetime.strptime(date_part, "%Y-%m-%d")
                        if file_date < cutoff_date:
                            file_path.unlink()
                            deleted_count += 1
                            self.logger.info(f"Deleted old file: {file_path}")
                    except ValueError:
                        # Skip files that don't match expected format
                        continue
                        
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
        
        self.logger.info(f"Cleanup complete: {deleted_count} files deleted")
        return deleted_count
    
    def get_cache_stats(self) -> Dict:
        """Get statistics about the data cache"""
        return {
            'cached_items': len(self._data_cache),
            'cache_keys': list(self._data_cache.keys()),
            'memory_usage_mb': sum(
                data.data.memory_usage(deep=True).sum() 
                for data in self._data_cache.values()
            ) / (1024 * 1024)
        }
    
    def clear_cache(self) -> None:
        """Clear the data cache"""
        self._data_cache.clear()
        self.logger.info("Data cache cleared")
