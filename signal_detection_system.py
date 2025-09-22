#!/usr/bin/env python3
"""
Signal Detection System - Domain Layer for Sensex Trading Bot
Separate signal detectors for Sensex and Option-based entry conditions
"""

import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import logging
from abc import ABC, abstractmethod


class SignalType(Enum):
    """Types of trading signals"""
    LONG_ENTRY = "long_entry"
    SHORT_ENTRY = "short_entry"  # Future use
    EXIT = "exit"
    NO_SIGNAL = "no_signal"


class SignalSource(Enum):
    """Source of the trading signal"""
    SENSEX_CHART = "sensex"
    OPTION_CHART = "option"
    COMBINED = "combined"


class OptionType(Enum):
    """Option types"""
    CALL = "CE"
    PUT = "PE"


@dataclass
class SignalCondition:
    """Individual condition within a signal"""
    name: str
    passed: bool
    value: Any
    threshold: Any = None
    description: str = ""


@dataclass 
class TradingSignal:
    """Complete trading signal with all metadata"""
    signal_type: SignalType
    option_type: OptionType
    source: SignalSource
    confidence: float
    timestamp: datetime
    entry_price: float
    stop_loss: float
    symbol: str
    strike: int
    conditions: List[SignalCondition] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_valid(self) -> bool:
        """Check if signal is valid for trading"""
        return (self.signal_type != SignalType.NO_SIGNAL and 
                self.confidence > 0 and 
                self.entry_price > 0)
    
    def get_condition_summary(self) -> Dict[str, bool]:
        """Get summary of all conditions"""
        return {condition.name: condition.passed for condition in self.conditions}
    
    def get_failed_conditions(self) -> List[str]:
        """Get list of failed condition names"""
        return [condition.name for condition in self.conditions if not condition.passed]


class BaseSignalDetector(ABC):
    """Abstract base class for signal detectors"""
    
    def __init__(self, name: str, config: Dict[str, Any] = None):
        self.name = name
        self.config = config or {}
        self.logger = logging.getLogger(f"{__name__}.{name}")
    
    @abstractmethod
    def detect_entry_signal(self, data: pd.DataFrame, **kwargs) -> TradingSignal:
        """Detect entry signal from data"""
        pass
    
    @abstractmethod
    def detect_exit_signal(self, data: pd.DataFrame, position_info: Dict, **kwargs) -> TradingSignal:
        """Detect exit signal for existing position"""
        pass


class SensexSignalDetector(BaseSignalDetector):
    """
    Sensex chart-based signal detector using EMA conditions
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        default_config = {
            'ema_short': 10,
            'ema_long': 20,
            'ema_diff_threshold': 15,
            'proximity_threshold': 21,
            'volume_threshold': 0,  # Minimum volume requirement
            'confidence_base': 0.8
        }
        if config:
            default_config.update(config)
        
        super().__init__("SensexSignalDetector", default_config)
    
    def _check_green_candle(self, latest_data: pd.Series) -> SignalCondition:
        """Check if latest candle is green (bullish)"""
        is_green = latest_data['close'] > latest_data['open']
        return SignalCondition(
            name="Green Candle",
            passed=is_green,
            value=f"close:{latest_data['close']:.2f}, open:{latest_data['open']:.2f}",
            description="Close price should be greater than open price"
        )
    
    def _check_ema_alignment(self, latest_data: pd.Series) -> SignalCondition:
        """Check if EMA10 > EMA20 (bullish alignment)"""
        ema10 = latest_data['ema10']
        ema20 = latest_data['ema20']
        is_aligned = ema10 > ema20
        return SignalCondition(
            name="EMA Alignment",
            passed=is_aligned,
            value=f"ema10:{ema10:.2f}, ema20:{ema20:.2f}",
            threshold="EMA10 > EMA20",
            description="10-period EMA should be above 20-period EMA"
        )
    
    def _check_ema_convergence(self, latest_data: pd.Series) -> SignalCondition:
        """Check if EMAs are converging (difference < threshold)"""
        ema_diff = abs(latest_data['ema10'] - latest_data['ema20'])
        threshold = self.config['ema_diff_threshold']
        is_converging = ema_diff < threshold
        return SignalCondition(
            name="EMA Convergence",
            passed=is_converging,
            value=f"|ema10-ema20|:{ema_diff:.2f}",
            threshold=f"< {threshold}",
            description=f"EMA difference should be less than {threshold}"
        )
    
    def _check_price_proximity(self, latest_data: pd.Series) -> SignalCondition:
        """Check if price is close to EMA10"""
        open_ema_diff = abs(latest_data['open'] - latest_data['ema10'])
        low_ema_diff = abs(latest_data['low'] - latest_data['ema10'])
        min_diff = min(open_ema_diff, low_ema_diff)
        threshold = self.config['proximity_threshold']
        is_close = min_diff < threshold
        
        return SignalCondition(
            name="Price Proximity",
            passed=is_close,
            value=f"min(|open-ema10|:{open_ema_diff:.2f}, |low-ema10|:{low_ema_diff:.2f}):{min_diff:.2f}",
            threshold=f"< {threshold}",
            description=f"Price should be within {threshold} points of EMA10"
        )
    
    def _check_volume(self, latest_data: pd.Series) -> SignalCondition:
        """Check volume requirements"""
        volume = latest_data.get('volume', 0)
        threshold = self.config['volume_threshold']
        is_sufficient = volume >= threshold
        return SignalCondition(
            name="Volume Check",
            passed=is_sufficient,
            value=volume,
            threshold=f">= {threshold}",
            description=f"Volume should be at least {threshold}"
        )
    
    def detect_entry_signal(self, sensex_data: pd.DataFrame, strike: int = None, 
                           symbol: str = "SENSEX", **kwargs) -> TradingSignal:
        """
        Detect Sensex-based entry signal
        
        Args:
            sensex_data: Sensex OHLCV data with indicators
            strike: Target strike price
            symbol: Option symbol (for metadata)
            
        Returns:
            TradingSignal with detection results
        """
        if sensex_data.empty:
            return TradingSignal(
                signal_type=SignalType.NO_SIGNAL,
                option_type=OptionType.CALL,
                source=SignalSource.SENSEX_CHART,
                confidence=0.0,
                timestamp=datetime.now(),
                entry_price=0.0,
                stop_loss=0.0,
                symbol=symbol,
                strike=strike or 0,
                conditions=[],
                metadata={'error': 'No Sensex data available'}
            )
        
        latest_data = sensex_data.iloc[-1]
        current_time = datetime.now()
        
        # Check all entry conditions
        conditions = [
            self._check_green_candle(latest_data),
            self._check_ema_alignment(latest_data),
            self._check_ema_convergence(latest_data),
            self._check_price_proximity(latest_data),
            self._check_volume(latest_data)
        ]
        
        # Calculate confidence based on passed conditions
        passed_conditions = sum(1 for c in conditions if c.passed)
        total_conditions = len(conditions)
        confidence = (passed_conditions / total_conditions) * self.config['confidence_base']
        
        # Determine signal type
        signal_type = SignalType.LONG_ENTRY if passed_conditions == total_conditions else SignalType.NO_SIGNAL
        
        # Calculate entry price and stop loss (for CE options based on Sensex signal)
        entry_price = latest_data['close']  # This would be option price in actual implementation
        stop_loss = latest_data['ema10']
        
        return TradingSignal(
            signal_type=signal_type,
            option_type=OptionType.CALL,  # Sensex signals typically for CE
            source=SignalSource.SENSEX_CHART,
            confidence=confidence,
            timestamp=current_time,
            entry_price=entry_price,
            stop_loss=stop_loss,
            symbol=symbol,
            strike=strike or 0,
            conditions=conditions,
            metadata={
                'sensex_price': latest_data['close'],
                'ema10': latest_data['ema10'],
                'ema20': latest_data['ema20'],
                'passed_conditions': f"{passed_conditions}/{total_conditions}"
            }
        )
    
    def detect_exit_signal(self, sensex_data: pd.DataFrame, position_info: Dict, **kwargs) -> TradingSignal:
        """
        Detect Sensex-based exit signal for existing position
        
        Args:
            sensex_data: Current Sensex data
            position_info: Current position details
            
        Returns:
            TradingSignal for exit or no signal
        """
        if sensex_data.empty:
            return TradingSignal(
                signal_type=SignalType.NO_SIGNAL,
                option_type=OptionType.CALL,
                source=SignalSource.SENSEX_CHART,
                confidence=0.0,
                timestamp=datetime.now(),
                entry_price=0.0,
                stop_loss=0.0,
                symbol=position_info.get('symbol', ''),
                strike=position_info.get('strike', 0)
            )
        
        latest_data = sensex_data.iloc[-1]
        current_price = latest_data['close']
        entry_price = position_info.get('entry_price', 0)
        stop_loss = position_info.get('stop_loss', 0)
        
        # Check exit conditions
        conditions = []
        
        # Stop loss hit
        sl_hit = current_price <= stop_loss
        conditions.append(SignalCondition(
            name="Stop Loss",
            passed=sl_hit,
            value=f"current:{current_price:.2f}, sl:{stop_loss:.2f}",
            description="Price hit stop loss level"
        ))
        
        # Check if any exit condition is met
        exit_triggered = any(c.passed for c in conditions)
        signal_type = SignalType.EXIT if exit_triggered else SignalType.NO_SIGNAL
        confidence = 1.0 if exit_triggered else 0.0
        
        return TradingSignal(
            signal_type=signal_type,
            option_type=OptionType.CALL,
            source=SignalSource.SENSEX_CHART,
            confidence=confidence,
            timestamp=datetime.now(),
            entry_price=current_price,
            stop_loss=stop_loss,
            symbol=position_info.get('symbol', ''),
            strike=position_info.get('strike', 0),
            conditions=conditions,
            metadata={
                'exit_reason': 'stop_loss' if sl_hit else 'none',
                'pnl': current_price - entry_price
            }
        )


class OptionSignalDetector(BaseSignalDetector):
    """
    Option-specific signal detector based on option price action
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        default_config = {
            'ema_short': 10,
            'ema_long': 20,
            'ema_diff_threshold': 15,
            'proximity_threshold': 21,
            'min_option_price': 5,  # Minimum option premium
            'max_option_price': 1000,  # Maximum option premium
            'confidence_base': 0.8
        }
        if config:
            default_config.update(config)
        
        super().__init__("OptionSignalDetector", default_config)
    
    def _check_option_green_candle(self, latest_data: pd.Series) -> SignalCondition:
        """Check if option candle is green"""
        is_green = latest_data['close'] > latest_data['open']
        return SignalCondition(
            name="Option Green Candle",
            passed=is_green,
            value=f"close:{latest_data['close']:.2f}, open:{latest_data['open']:.2f}",
            description="Option close should be greater than open"
        )
    
    def _check_option_ema_alignment(self, latest_data: pd.Series) -> SignalCondition:
        """Check option EMA alignment"""
        ema10 = latest_data['ema10']
        ema20 = latest_data['ema20']
        is_aligned = ema10 > ema20
        return SignalCondition(
            name="Option EMA Alignment",
            passed=is_aligned,
            value=f"ema10:{ema10:.2f}, ema20:{ema20:.2f}",
            threshold="EMA10 > EMA20",
            description="Option EMA10 should be above EMA20"
        )
    
    def _check_option_ema_convergence(self, latest_data: pd.Series) -> SignalCondition:
        """Check option EMA convergence"""
        ema_diff = abs(latest_data['ema10'] - latest_data['ema20'])
        threshold = self.config['ema_diff_threshold']
        is_converging = ema_diff < threshold
        return SignalCondition(
            name="Option EMA Convergence",
            passed=is_converging,
            value=f"|ema10-ema20|:{ema_diff:.2f}",
            threshold=f"< {threshold}",
            description=f"Option EMA difference should be less than {threshold}"
        )
    
    def _check_option_proximity(self, latest_data: pd.Series) -> SignalCondition:
        """Check option price proximity to EMA10"""
        open_ema_diff = abs(latest_data['open'] - latest_data['ema10'])
        low_ema_diff = abs(latest_data['low'] - latest_data['ema10'])
        min_diff = min(open_ema_diff, low_ema_diff)
        threshold = self.config['proximity_threshold']
        is_close = min_diff < threshold
        
        return SignalCondition(
            name="Option Price Proximity",
            passed=is_close,
            value=f"min(|open-ema10|:{open_ema_diff:.2f}, |low-ema10|:{low_ema_diff:.2f}):{min_diff:.2f}",
            threshold=f"< {threshold}",
            description=f"Option price should be within {threshold} points of EMA10"
        )
    
    def _check_option_premium_range(self, latest_data: pd.Series) -> SignalCondition:
        """Check if option premium is in tradeable range"""
        price = latest_data['close']
        min_price = self.config['min_option_price']
        max_price = self.config['max_option_price']
        in_range = min_price <= price <= max_price
        
        return SignalCondition(
            name="Option Premium Range",
            passed=in_range,
            value=price,
            threshold=f"{min_price} <= price <= {max_price}",
            description=f"Option premium should be between {min_price} and {max_price}"
        )
    
    def detect_entry_signal(self, option_data: pd.DataFrame, option_type: OptionType,
                           symbol: str, strike: int, **kwargs) -> TradingSignal:
        """
        Detect option-based entry signal
        
        Args:
            option_data: Option OHLCV data with indicators
            option_type: CE or PE
            symbol: Option symbol
            strike: Strike price
            
        Returns:
            TradingSignal with detection results
        """
        if option_data.empty:
            return TradingSignal(
                signal_type=SignalType.NO_SIGNAL,
                option_type=option_type,
                source=SignalSource.OPTION_CHART,
                confidence=0.0,
                timestamp=datetime.now(),
                entry_price=0.0,
                stop_loss=0.0,
                symbol=symbol,
                strike=strike,
                conditions=[],
                metadata={'error': 'No option data available'}
            )
        
        latest_data = option_data.iloc[-1]
        current_time = datetime.now()
        
        # Check all entry conditions
        conditions = [
            self._check_option_green_candle(latest_data),
            self._check_option_ema_alignment(latest_data),
            self._check_option_ema_convergence(latest_data),
            self._check_option_proximity(latest_data),
            self._check_option_premium_range(latest_data)
        ]
        
        # Calculate confidence
        passed_conditions = sum(1 for c in conditions if c.passed)
        total_conditions = len(conditions)
        confidence = (passed_conditions / total_conditions) * self.config['confidence_base']
        
        # Determine signal type
        signal_type = SignalType.LONG_ENTRY if passed_conditions == total_conditions else SignalType.NO_SIGNAL
        
        # Entry price and stop loss
        entry_price = latest_data['close']
        stop_loss = latest_data['ema10']
        
        return TradingSignal(
            signal_type=signal_type,
            option_type=option_type,
            source=SignalSource.OPTION_CHART,
            confidence=confidence,
            timestamp=current_time,
            entry_price=entry_price,
            stop_loss=stop_loss,
            symbol=symbol,
            strike=strike,
            conditions=conditions,
            metadata={
                'option_price': entry_price,
                'ema10': latest_data['ema10'],
                'ema20': latest_data['ema20'],
                'passed_conditions': f"{passed_conditions}/{total_conditions}"
            }
        )
    
    def detect_exit_signal(self, option_data: pd.DataFrame, position_info: Dict, **kwargs) -> TradingSignal:
        """
        Detect option-based exit signal
        
        Args:
            option_data: Current option data
            position_info: Position details
            
        Returns:
            TradingSignal for exit or no signal
        """
        if option_data.empty:
            return TradingSignal(
                signal_type=SignalType.NO_SIGNAL,
                option_type=OptionType.CALL,
                source=SignalSource.OPTION_CHART,
                confidence=0.0,
                timestamp=datetime.now(),
                entry_price=0.0,
                stop_loss=0.0,
                symbol=position_info.get('symbol', ''),
                strike=position_info.get('strike', 0)
            )
        
        latest_data = option_data.iloc[-1]
        current_price = latest_data['close']
        entry_price = position_info.get('entry_price', 0)
        stop_loss = position_info.get('stop_loss', 0)
        candle_count = position_info.get('candle_count', 0)
        
        conditions = []
        
        # Stop loss condition
        sl_hit = current_price <= stop_loss
        conditions.append(SignalCondition(
            name="Option Stop Loss",
            passed=sl_hit,
            value=f"current:{current_price:.2f}, sl:{stop_loss:.2f}",
            description="Option price hit stop loss"
        ))
        
        # Time-based exit (after certain number of candles)
        time_exit = candle_count >= 10  # Example: exit after 10 candles (30 minutes)
        conditions.append(SignalCondition(
            name="Time Exit",
            passed=time_exit,
            value=f"candles:{candle_count}",
            threshold=">= 10",
            description="Time-based exit condition"
        ))
        
        # Profit target (optional)
        profit_pct = (current_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
        profit_target_hit = profit_pct >= 20  # 20% profit target
        conditions.append(SignalCondition(
            name="Profit Target",
            passed=profit_target_hit,
            value=f"profit:{profit_pct:.1f}%",
            threshold=">= 20%",
            description="Profit target reached"
        ))
        
        # Check if any exit condition is met
        exit_triggered = any(c.passed for c in conditions)
        signal_type = SignalType.EXIT if exit_triggered else SignalType.NO_SIGNAL
        confidence = 1.0 if exit_triggered else 0.0
        
        exit_reason = 'none'
        if sl_hit:
            exit_reason = 'stop_loss'
        elif time_exit:
            exit_reason = 'time_exit'
        elif profit_target_hit:
            exit_reason = 'profit_target'
        
        return TradingSignal(
            signal_type=signal_type,
            option_type=position_info.get('option_type', OptionType.CALL),
            source=SignalSource.OPTION_CHART,
            confidence=confidence,
            timestamp=datetime.now(),
            entry_price=current_price,
            stop_loss=stop_loss,
            symbol=position_info.get('symbol', ''),
            strike=position_info.get('strike', 0),
            conditions=conditions,
            metadata={
                'exit_reason': exit_reason,
                'pnl': current_price - entry_price,
                'pnl_percent': profit_pct,
                'candle_count': candle_count
            }
        )


class SignalOrchestrator:
    """
    Orchestrates multiple signal detectors and resolves conflicts
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        
        # Initialize detectors
        self.sensex_detector = SensexSignalDetector(self.config.get('sensex', {}))
        self.option_detector = OptionSignalDetector(self.config.get('option', {}))
        
        # Signal resolution settings
        self.min_confidence = self.config.get('min_confidence', 0.8)
        self.signal_timeout_minutes = self.config.get('signal_timeout', 10)
        self.last_signal_time = None
        
    def detect_entry_signals(self, sensex_data: pd.DataFrame, ce_data: pd.DataFrame,
                           pe_data: pd.DataFrame, strike: int, ce_symbol: str, 
                           pe_symbol: str) -> List[TradingSignal]:
        """
        Detect entry signals from all sources
        
        Args:
            sensex_data: Sensex OHLCV data
            ce_data: Call option data
            pe_data: Put option data
            strike: Strike price
            ce_symbol: Call option symbol
            pe_symbol: Put option symbol
            
        Returns:
            List of valid trading signals
        """
        signals = []
        
        try:
            # Sensex-based signal (for CE)
            sensex_signal = self.sensex_detector.detect_entry_signal(
                sensex_data, strike=strike, symbol=ce_symbol
            )
            
            if sensex_signal.is_valid and sensex_signal.confidence >= self.min_confidence:
                signals.append(sensex_signal)
                self.logger.info(f"Sensex signal detected: {sensex_signal.confidence:.2f} confidence")
            
            # Option-based signals
            ce_signal = self.option_detector.detect_entry_signal(
                ce_data, OptionType.CALL, ce_symbol, strike
            )
            
            if ce_signal.is_valid and ce_signal.confidence >= self.min_confidence:
                signals.append(ce_signal)
                self.logger.info(f"CE option signal detected: {ce_signal.confidence:.2f} confidence")
            
            pe_signal = self.option_detector.detect_entry_signal(
                pe_data, OptionType.PUT, pe_symbol, strike
            )
            
            if pe_signal.is_valid and pe_signal.confidence >= self.min_confidence:
                signals.append(pe_signal)
                self.logger.info(f"PE option signal detected: {pe_signal.confidence:.2f} confidence")
            
        except Exception as e:
            self.logger.error(f"Error detecting entry signals: {e}")
        
        return self._resolve_signal_conflicts(signals)
    
    def detect_exit_signals(self, current_position: Dict, sensex_data: pd.DataFrame,
                          option_data: pd.DataFrame) -> Optional[TradingSignal]:
        """
        Detect exit signals for current position
        
        Args:
            current_position: Position information
            sensex_data: Current Sensex data
            option_data: Current option data
            
        Returns:
            Exit signal or None
        """
        try:
            # Check position source and use appropriate detector
            entry_basis = current_position.get('entry_basis', 'option')
            
            if entry_basis == 'sensex':
                exit_signal = self.sensex_detector.detect_exit_signal(sensex_data, current_position)
            else:
                exit_signal = self.option_detector.detect_exit_signal(option_data, current_position)
            
            if exit_signal.signal_type == SignalType.EXIT:
                self.logger.info(f"Exit signal detected: {exit_signal.metadata.get('exit_reason', 'unknown')}")
                return exit_signal
                
        except Exception as e:
            self.logger.error(f"Error detecting exit signals: {e}")
        
        return None
    
    def _resolve_signal_conflicts(self, signals: List[TradingSignal]) -> List[TradingSignal]:
        """
        Resolve conflicts when multiple signals are detected
        
        Args:
            signals: List of detected signals
            
        Returns:
            Filtered list of signals
        """
        if not signals:
            return signals
        
        # Check signal timeout
        current_time = datetime.now()
        if (self.last_signal_time and 
            (current_time - self.last_signal_time).total_seconds() < self.signal_timeout_minutes * 60):
            self.logger.info("Signal timeout active - ignoring new signals")
            return []
        
        # Filter by confidence
        high_confidence_signals = [s for s in signals if s.confidence >= self.min_confidence]
        
        if not high_confidence_signals:
            return []
        
        # Resolve CE vs PE conflicts (prefer higher confidence)
        ce_signals = [s for s in high_confidence_signals if s.option_type == OptionType.CALL]
        pe_signals = [s for s in high_confidence_signals if s.option_type == OptionType.PUT]
        
        if ce_signals and pe_signals:
            # Both CE and PE signals - choose highest confidence
            best_ce = max(ce_signals, key=lambda x: x.confidence)
            best_pe = max(pe_signals, key=lambda x: x.confidence)
            
            if best_ce.confidence > best_pe.confidence:
                resolved_signals = [best_ce]
                self.logger.info(f"Conflict resolved: Chose CE (confidence: {best_ce.confidence:.2f})")
            elif best_pe.confidence > best_ce.confidence:
                resolved_signals = [best_pe]
                self.logger.info(f"Conflict resolved: Chose PE (confidence: {best_pe.confidence:.2f})")
            else:
                # Equal confidence - prefer Sensex-based signal
                sensex_signals = [s for s in [best_ce, best_pe] if s.source == SignalSource.SENSEX_CHART]
                if sensex_signals:
                    resolved_signals = [sensex_signals[0]]
                    self.logger.info("Conflict resolved: Chose Sensex-based signal")
                else:
                    resolved_signals = [best_ce]  # Default to CE
                    self.logger.info("Conflict resolved: Default to CE")
        
        elif ce_signals:
            resolved_signals = ce_signals
        else:
            resolved_signals = pe_signals
        
        # Update last signal time if we have valid signals
        if resolved_signals:
            self.last_signal_time = current_time
        
        return resolved_signals
    
    def get_signal_summary(self, signals: List[TradingSignal]) -> Dict[str, Any]:
        """
        Generate summary of detected signals
        
        Args:
            signals: List of signals
            
        Returns:
            Summary dictionary
        """
        summary = {
            'total_signals': len(signals),
            'signal_types': [s.signal_type.value for s in signals],
            'option_types': [s.option_type.value for s in signals],
            'sources': [s.source.value for s in signals],
            'avg_confidence': sum(s.confidence for s in signals) / len(signals) if signals else 0,
            'max_confidence': max(s.confidence for s in signals) if signals else 0,
            'symbols': list(set(s.symbol for s in signals)),
            'strikes': list(set(s.strike for s in signals))
        }
        
        # Add condition details for failed signals
        failed_conditions = {}
        for signal in signals:
            if not signal.is_valid:
                failed_conditions[signal.symbol] = signal.get_failed_conditions()
        
        if failed_conditions:
            summary['failed_conditions'] = failed_conditions
        
        return summary
