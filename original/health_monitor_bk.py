#!/usr/bin/env python3
"""
Health Monitor and Error Recovery - System monitoring and automatic recovery for Trading Bot
Provides health checks, error recovery strategies, and system diagnostics
"""

import asyncio
import psutil
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import traceback
import threading
import time
import os
from pathlib import Path


class HealthStatus(Enum):
    """System health status levels"""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    FAILED = "failed"


class RecoveryAction(Enum):
    """Available recovery actions"""
    RESTART_SERVICE = "restart_service"
    CLEAR_CACHE = "clear_cache"
    REDUCE_LOAD = "reduce_load"
    EMERGENCY_STOP = "emergency_stop"
    NOTIFY_ADMIN = "notify_admin"
    WAIT_AND_RETRY = "wait_and_retry"


@dataclass
class HealthMetric:
    """Individual health metric"""
    name: str
    value: float
    threshold_warning: float
    threshold_critical: float
    unit: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    
    @property
    def status(self) -> HealthStatus:
        if self.value >= self.threshold_critical:
            return HealthStatus.CRITICAL
        elif self.value >= self.threshold_warning:
            return HealthStatus.WARNING
        else:
            return HealthStatus.HEALTHY


@dataclass
class SystemAlert:
    """System alert/incident"""
    id: str
    severity: HealthStatus
    component: str
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    resolved: bool = False
    resolution_time: Optional[datetime] = None
    recovery_actions: List[RecoveryAction] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryStrategy:
    """Error recovery strategy"""
    error_pattern: str
    actions: List[RecoveryAction]
    max_attempts: int = 3
    backoff_seconds: int = 30
    success_callback: Optional[Callable] = None
    failure_callback: Optional[Callable] = None


class HealthMonitor:
    """
    Comprehensive health monitoring system with automatic recovery
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize Health Monitor
        
        Args:
            config: Health monitoring configuration
        """
        self.logger = logging.getLogger(__name__)
        self.config = config or {}
        
        # Configuration
        self.check_interval = self.config.get('check_interval_seconds', 30)
        self.alert_threshold_count = self.config.get('alert_threshold_count', 3)
        self.recovery_timeout = self.config.get('recovery_timeout_seconds', 300)
        
        # System monitoring
        self.process = psutil.Process()
        self.system_metrics: Dict[str, HealthMetric] = {}
        self.alerts: Dict[str, SystemAlert] = {}
        self.alert_history: List[SystemAlert] = []
        
        # Recovery system
        self.recovery_strategies: List[RecoveryStrategy] = []
        self.recovery_attempts: Dict[str, int] = {}
        self.last_recovery_time: Dict[str, datetime] = {}
        
        # Monitoring state
        self.is_monitoring = False
        self.monitor_task = None
        self.callbacks: Dict[str, List[Callable]] = {
            'on_warning': [],
            'on_critical': [],
            'on_recovery': [],
            'on_failure': []
        }
        
        # Initialize default thresholds
        self._setup_default_metrics()
        self._setup_default_recovery_strategies()
        
        self.logger.info("HealthMonitor initialized")
    
    def _setup_default_metrics(self):
        """Setup default system metrics with thresholds"""
        self.metric_definitions = {
            'memory_usage_mb': {
                'threshold_warning': 256,
                'threshold_critical': 512,
                'unit': 'MB'
            },
            'memory_usage_percent': {
                'threshold_warning': 70,
                'threshold_critical': 85,
                'unit': '%'
            },
            'cpu_usage_percent': {
                'threshold_warning': 60,
                'threshold_critical': 80,
                'unit': '%'
            },
            'disk_usage_percent': {
                'threshold_warning': 80,
                'threshold_critical': 90,
                'unit': '%'
            },
            'error_rate_percent': {
                'threshold_warning': 10,
                'threshold_critical': 25,
                'unit': '%'
            },
            'response_time_seconds': {
                'threshold_warning': 60,
                'threshold_critical': 120,
                'unit': 's'
            },
            'api_failure_rate': {
                'threshold_warning': 5,
                'threshold_critical': 15,
                'unit': '%'
            }
        }
    
    def _setup_default_recovery_strategies(self):
        """Setup default error recovery strategies"""
        self.recovery_strategies = [
            RecoveryStrategy(
                error_pattern="memory",
                actions=[RecoveryAction.CLEAR_CACHE, RecoveryAction.REDUCE_LOAD],
                max_attempts=2,
                backoff_seconds=60
            ),
            RecoveryStrategy(
                error_pattern="api.*timeout",
                actions=[RecoveryAction.WAIT_AND_RETRY, RecoveryAction.REDUCE_LOAD],
                max_attempts=3,
                backoff_seconds=30
            ),
            RecoveryStrategy(
                error_pattern="broker.*connection",
                actions=[RecoveryAction.RESTART_SERVICE, RecoveryAction.NOTIFY_ADMIN],
                max_attempts=2,
                backoff_seconds=120
            ),
            RecoveryStrategy(
                error_pattern="disk.*full",
                actions=[RecoveryAction.CLEAR_CACHE, RecoveryAction.NOTIFY_ADMIN],
                max_attempts=1,
                backoff_seconds=0
            ),
            RecoveryStrategy(
                error_pattern=".*critical.*",
                actions=[RecoveryAction.EMERGENCY_STOP, RecoveryAction.NOTIFY_ADMIN],
                max_attempts=1,
                backoff_seconds=0
            )
        ]
    
    def add_callback(self, event: str, callback: Callable):
        """Add callback for health events"""
        if event in self.callbacks:
            self.callbacks[event].append(callback)
        else:
            self.logger.warning(f"Unknown callback event: {event}")
    
    def remove_callback(self, event: str, callback: Callable):
        """Remove callback for health events"""
        if event in self.callbacks and callback in self.callbacks[event]:
            self.callbacks[event].remove(callback)
    
    async def start_monitoring(self) -> bool:
        """Start health monitoring"""
        try:
            if self.is_monitoring:
                self.logger.warning("Health monitoring already running")
                return True
            
            self.is_monitoring = True
            self.monitor_task = asyncio.create_task(self._monitoring_loop())
            
            self.logger.info("Health monitoring started")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start health monitoring: {e}")
            return False
    
    async def stop_monitoring(self):
        """Stop health monitoring"""
        try:
            self.is_monitoring = False
            
            if self.monitor_task:
                self.monitor_task.cancel()
                await self.monitor_task
            
            self.logger.info("Health monitoring stopped")
            
        except Exception as e:
            self.logger.error(f"Error stopping health monitoring: {e}")
    
    async def _monitoring_loop(self):
        """Main monitoring loop"""
        while self.is_monitoring:
            try:
                # Collect system metrics
                await self._collect_system_metrics()
                
                # Check for alerts
                await self._check_alerts()
                
                # Process recovery actions
                await self._process_recovery_actions()
                
                # Clean up old alerts
                self._cleanup_old_alerts()
                
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(self.check_interval)
    
    async def _collect_system_metrics(self):
        """Collect current system metrics"""
        try:
            # Memory metrics
            memory_info = self.process.memory_info()
            memory_mb = memory_info.rss / (1024 * 1024)
            system_memory = psutil.virtual_memory()
            
            self._update_metric('memory_usage_mb', memory_mb)
            self._update_metric('memory_usage_percent', system_memory.percent)
            
            # CPU metrics
            cpu_percent = self.process.cpu_percent()
            self._update_metric('cpu_usage_percent', cpu_percent)
            
            # Disk metrics
            disk_usage = psutil.disk_usage('.')
            disk_percent = (disk_usage.used / disk_usage.total) * 100
            self._update_metric('disk_usage_percent', disk_percent)
            
            # Process-specific metrics
            num_threads = self.process.num_threads()
            num_fds = len(self.process.open_files())
            
            # Log metrics periodically
            if datetime.now().minute % 5 == 0:  # Every 5 minutes
                self.logger.debug(f"System metrics - Memory: {memory_mb:.1f}MB, "
                               f"CPU: {cpu_percent:.1f}%, Disk: {disk_percent:.1f}%, "
                               f"Threads: {num_threads}, FDs: {num_fds}")
            
        except Exception as e:
            self.logger.error(f"Error collecting system metrics: {e}")
    
    def _update_metric(self, name: str, value: float):
        """Update a system metric"""
        if name in self.metric_definitions:
            definition = self.metric_definitions[name]
            metric = HealthMetric(
                name=name,
                value=value,
                threshold_warning=definition['threshold_warning'],
                threshold_critical=definition['threshold_critical'],
                unit=definition['unit']
            )
            self.system_metrics[name] = metric
    
    async def _check_alerts(self):
        """Check metrics against thresholds and generate alerts"""
        for name, metric in self.system_metrics.items():
            alert_id = f"metric_{name}"
            
            if metric.status in [HealthStatus.WARNING, HealthStatus.CRITICAL]:
                # Check if alert already exists
                if alert_id not in self.alerts:
                    # Create new alert
                    alert = SystemAlert(
                        id=alert_id,
                        severity=metric.status,
                        component="system",
                        message=f"{name} is {metric.status.value}: {metric.value:.1f}{metric.unit} "
                               f"(threshold: {metric.threshold_warning if metric.status == HealthStatus.WARNING else metric.threshold_critical}{metric.unit})",
                        metadata={
                            'metric_name': name,
                            'metric_value': metric.value,
                            'threshold': metric.threshold_warning if metric.status == HealthStatus.WARNING else metric.threshold_critical
                        }
                    )
                    
                    self.alerts[alert_id] = alert
                    await self._trigger_alert(alert)
                
            else:
                # Metric is healthy, resolve alert if exists
                if alert_id in self.alerts:
                    await self._resolve_alert(alert_id)
    
    async def _trigger_alert(self, alert: SystemAlert):
        """Trigger alert and execute callbacks"""
        try:
            self.logger.warning(f"ALERT: {alert.message}")
            
            # Add to alert history
            self.alert_history.append(alert)
            
            # Execute appropriate callbacks
            if alert.severity == HealthStatus.WARNING:
                for callback in self.callbacks['on_warning']:
                    try:
                        await self._execute_callback(callback, alert)
                    except Exception as e:
                        self.logger.error(f"Error executing warning callback: {e}")
            
            elif alert.severity == HealthStatus.CRITICAL:
                for callback in self.callbacks['on_critical']:
                    try:
                        await self._execute_callback(callback, alert)
                    except Exception as e:
                        self.logger.error(f"Error executing critical callback: {e}")
                
                # Attempt automatic recovery for critical alerts
                await self._attempt_recovery(alert)
            
        except Exception as e:
            self.logger.error(f"Error triggering alert: {e}")
    
    async def _resolve_alert(self, alert_id: str):
        """Resolve an existing alert"""
        if alert_id in self.alerts:
            alert = self.alerts[alert_id]
            alert.resolved = True
            alert.resolution_time = datetime.now()
            
            self.logger.info(f"RESOLVED: {alert.message}")
            
            # Execute recovery callbacks
            for callback in self.callbacks['on_recovery']:
                try:
                    await self._execute_callback(callback, alert)
                except Exception as e:
                    self.logger.error(f"Error executing recovery callback: {e}")
            
            # Remove from active alerts
            del self.alerts[alert_id]
    
    async def _execute_callback(self, callback: Callable, alert: SystemAlert):
        """Execute callback function safely"""
        if asyncio.iscoroutinefunction(callback):
            await callback(alert)
        else:
            # Run in thread for blocking callbacks
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, callback, alert)
    
    async def _attempt_recovery(self, alert: SystemAlert):
        """Attempt automatic recovery for critical alerts"""
        try:
            # Find matching recovery strategy
            strategy = self._find_recovery_strategy(alert)
            if not strategy:
                self.logger.warning(f"No recovery strategy found for alert: {alert.id}")
                return
            
            # Check if we've exceeded max attempts
            attempts = self.recovery_attempts.get(alert.id, 0)
            if attempts >= strategy.max_attempts:
                self.logger.error(f"Max recovery attempts exceeded for alert: {alert.id}")
                await self._execute_failure_callbacks(alert, strategy)
                return
            
            # Check recovery timeout
            last_attempt = self.last_recovery_time.get(alert.id)
            if last_attempt:
                time_since_last = (datetime.now() - last_attempt).total_seconds()
                if time_since_last < strategy.backoff_seconds:
                    self.logger.debug(f"Recovery backoff active for alert: {alert.id}")
                    return
            
            # Execute recovery actions
            self.logger.info(f"Attempting recovery for alert: {alert.id} (attempt {attempts + 1})")
            
            recovery_success = True
            for action in strategy.actions:
                try:
                    await self._execute_recovery_action(action, alert)
                    alert.recovery_actions.append(action)
                except Exception as e:
                    self.logger.error(f"Recovery action {action.value} failed: {e}")
                    recovery_success = False
                    break
            
            # Update attempt tracking
            self.recovery_attempts[alert.id] = attempts + 1
            self.last_recovery_time[alert.id] = datetime.now()
            
            if recovery_success:
                self.logger.info(f"Recovery successful for alert: {alert.id}")
                if strategy.success_callback:
                    await self._execute_callback(strategy.success_callback, alert)
            else:
                self.logger.error(f"Recovery failed for alert: {alert.id}")
                if strategy.failure_callback:
                    await self._execute_callback(strategy.failure_callback, alert)
            
        except Exception as e:
            self.logger.error(f"Error in recovery attempt: {e}")
    
    def _find_recovery_strategy(self, alert: SystemAlert) -> Optional[RecoveryStrategy]:
        """Find matching recovery strategy for alert"""
        import re
        
        alert_text = f"{alert.component} {alert.message}".lower()
        
        for strategy in self.recovery_strategies:
            if re.search(strategy.error_pattern, alert_text, re.IGNORECASE):
                return strategy
        
        return None
    
    async def _execute_recovery_action(self, action: RecoveryAction, alert: SystemAlert):
        """Execute specific recovery action"""
        self.logger.info(f"Executing recovery action: {action.value}")
        
        if action == RecoveryAction.CLEAR_CACHE:
            await self._clear_caches()
        
        elif action == RecoveryAction.REDUCE_LOAD:
            await self._reduce_system_load()
        
        elif action == RecoveryAction.RESTART_SERVICE:
            await self._restart_service(alert.component)
        
        elif action == RecoveryAction.WAIT_AND_RETRY:
            await asyncio.sleep(30)  # Wait 30 seconds
        
        elif action == RecoveryAction.EMERGENCY_STOP:
            await self._emergency_stop()
        
        elif action == RecoveryAction.NOTIFY_ADMIN:
            await self._notify_admin(alert)
        
        else:
            self.logger.warning(f"Unknown recovery action: {action}")
    
    async def _clear_caches(self):
        """Clear system caches"""
        try:
            # This would integrate with your specific cache systems
            self.logger.info("Clearing system caches")
            
            # Example cache clearing operations
            import gc
            gc.collect()  # Force garbage collection
            
            # Clear any application-specific caches here
            # self.data_manager.clear_cache() if available
            # self.broker_adapter.cleanup_cache() if available
            
        except Exception as e:
            self.logger.error(f"Error clearing caches: {e}")
            raise
    
    async def _reduce_system_load(self):
        """Reduce system load"""
        try:
            self.logger.info("Reducing system load")
            
            # Implement load reduction strategies
            # - Increase sleep intervals
            # - Reduce concurrent operations
            # - Temporarily disable non-critical features
            
            # Example: Signal main application to reduce load
            # This would need integration with your main application
            
        except Exception as e:
            self.logger.error(f"Error reducing system load: {e}")
            raise
    
    async def _restart_service(self, component: str):
        """Restart specific service component"""
        try:
            self.logger.info(f"Restarting service component: {component}")
            
            # This would integrate with your service management
            # Example implementations:
            # - Restart broker connection
            # - Restart data manager
            # - Restart notification service
            
        except Exception as e:
            self.logger.error(f"Error restarting service {component}: {e}")
            raise
    
    async def _emergency_stop(self):
        """Execute emergency stop"""
        try:
            self.logger.critical("EMERGENCY STOP initiated")
            
            # Signal main application to stop immediately
            # This would need integration with your main controller
            
        except Exception as e:
            self.logger.error(f"Error in emergency stop: {e}")
            raise
    
    async def _notify_admin(self, alert: SystemAlert):
        """Notify administrator of critical issue"""
        try:
            self.logger.critical(f"Notifying admin of critical alert: {alert.message}")
            
            # This would integrate with your notification system
            # to send urgent admin notifications
            
        except Exception as e:
            self.logger.error(f"Error notifying admin: {e}")
            raise
    
    async def _execute_failure_callbacks(self, alert: SystemAlert, strategy: RecoveryStrategy):
        """Execute callbacks when recovery fails"""
        for callback in self.callbacks['on_failure']:
            try:
                await self._execute_callback(callback, alert)
            except Exception as e:
                self.logger.error(f"Error executing failure callback: {e}")
    
    async def _process_recovery_actions(self):
        """Process any pending recovery actions"""
        # This method can be used for scheduled recovery actions
        # or cleanup tasks that need to run periodically
        pass
    
    def _cleanup_old_alerts(self):
        """Clean up old resolved alerts from history"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=24)  # Keep 24 hours of history
            
            initial_count = len(self.alert_history)
            self.alert_history = [
                alert for alert in self.alert_history 
                if alert.timestamp > cutoff_time
            ]
            
            cleaned_count = initial_count - len(self.alert_history)
            if cleaned_count > 0:
                self.logger.debug(f"Cleaned up {cleaned_count} old alerts")
            
            # Clean up recovery attempt tracking
            old_attempts = []
            for alert_id, last_time in self.last_recovery_time.items():
                if last_time < cutoff_time:
                    old_attempts.append(alert_id)
            
            for alert_id in old_attempts:
                self.recovery_attempts.pop(alert_id, None)
                self.last_recovery_time.pop(alert_id, None)
            
        except Exception as e:
            self.logger.error(f"Error cleaning up old alerts: {e}")
    
    def add_custom_metric(self, name: str, value: float, threshold_warning: float, 
                         threshold_critical: float, unit: str = ""):
        """Add custom application metric"""
        self.metric_definitions[name] = {
            'threshold_warning': threshold_warning,
            'threshold_critical': threshold_critical,
            'unit': unit
        }
        self._update_metric(name, value)
    
    def update_custom_metric(self, name: str, value: float):
        """Update custom application metric"""
        if name in self.metric_definitions:
            self._update_metric(name, value)
        else:
            self.logger.warning(f"Metric {name} not defined")
    
    def add_recovery_strategy(self, strategy: RecoveryStrategy):
        """Add custom recovery strategy"""
        self.recovery_strategies.append(strategy)
        self.logger.info(f"Added recovery strategy for pattern: {strategy.error_pattern}")
    
    def get_system_health(self) -> Dict[str, Any]:
        """Get comprehensive system health report"""
        healthy_metrics = []
        warning_metrics = []
        critical_metrics = []
        
        for name, metric in self.system_metrics.items():
            metric_info = {
                'name': name,
                'value': metric.value,
                'unit': metric.unit,
                'status': metric.status.value,
                'timestamp': metric.timestamp.isoformat()
            }
            
            if metric.status == HealthStatus.HEALTHY:
                healthy_metrics.append(metric_info)
            elif metric.status == HealthStatus.WARNING:
                warning_metrics.append(metric_info)
            elif metric.status == HealthStatus.CRITICAL:
                critical_metrics.append(metric_info)
        
        # Determine overall health status
        if critical_metrics:
            overall_status = HealthStatus.CRITICAL
        elif warning_metrics:
            overall_status = HealthStatus.WARNING
        else:
            overall_status = HealthStatus.HEALTHY
        
        return {
            'overall_status': overall_status.value,
            'timestamp': datetime.now().isoformat(),
            'metrics': {
                'healthy': healthy_metrics,
                'warning': warning_metrics,
                'critical': critical_metrics
            },
            'active_alerts': len(self.alerts),
            'total_alerts_24h': len([
                alert for alert in self.alert_history 
                if alert.timestamp > datetime.now() - timedelta(hours=24)
            ]),
            'recovery_attempts': sum(self.recovery_attempts.values()),
            'monitoring_active': self.is_monitoring
        }
    
    def get_alert_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get alert history for specified period"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        recent_alerts = [
            alert for alert in self.alert_history 
            if alert.timestamp > cutoff_time
        ]
        
        return [
            {
                'id': alert.id,
                'severity': alert.severity.value,
                'component': alert.component,
                'message': alert.message,
                'timestamp': alert.timestamp.isoformat(),
                'resolved': alert.resolved,
                'resolution_time': alert.resolution_time.isoformat() if alert.resolution_time else None,
                'recovery_actions': [action.value for action in alert.recovery_actions]
            }
            for alert in recent_alerts
        ]
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics"""
        return {
            'monitoring_uptime_seconds': (datetime.now() - getattr(self, '_start_time', datetime.now())).total_seconds(),
            'total_alerts': len(self.alert_history),
            'active_alerts': len(self.alerts),
            'recovery_success_rate': self._calculate_recovery_success_rate(),
            'most_common_alerts': self._get_most_common_alerts(),
            'avg_resolution_time_seconds': self._calculate_avg_resolution_time(),
            'system_resources': {
                'memory_mb': self.process.memory_info().rss / (1024 * 1024),
                'cpu_percent': self.process.cpu_percent(),
                'threads': self.process.num_threads()
            }
        }
    
    def _calculate_recovery_success_rate(self) -> float:
        """Calculate recovery success rate"""
        resolved_alerts = [alert for alert in self.alert_history if alert.resolved]
        if not self.alert_history:
            return 0.0
        return len(resolved_alerts) / len(self.alert_history) * 100
    
    def _get_most_common_alerts(self) -> List[Dict[str, Any]]:
        """Get most common alert types"""
        alert_counts = {}
        for alert in self.alert_history[-100:]:  # Last 100 alerts
            key = f"{alert.component}:{alert.severity.value}"
            alert_counts[key] = alert_counts.get(key, 0) + 1
        
        return [
            {'type': alert_type, 'count': count}
            for alert_type, count in sorted(alert_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        ]
    
    def _calculate_avg_resolution_time(self) -> float:
        """Calculate average alert resolution time"""
        resolved_alerts = [
            alert for alert in self.alert_history 
            if alert.resolved and alert.resolution_time
        ]
        
        if not resolved_alerts:
            return 0.0
        
        total_time = sum(
            (alert.resolution_time - alert.timestamp).total_seconds()
            for alert in resolved_alerts
        )
        
        return total_time / len(resolved_alerts)
    
    async def run_health_check(self) -> Dict[str, Any]:
        """Run immediate comprehensive health check"""
        self.logger.info("Running comprehensive health check...")
        
        # Collect current metrics
        await self._collect_system_metrics()
        
        # Get health report
        health_report = self.get_system_health()
        
        # Add additional diagnostic information
        health_report['diagnostics'] = {
            'disk_free_gb': psutil.disk_usage('.').free / (1024**3),
            'network_connections': len(self.process.connections()),
            'open_files': len(self.process.open_files()),
            'process_uptime_hours': (datetime.now() - datetime.fromtimestamp(self.process.create_time())).total_seconds() / 3600,
            'python_version': os.sys.version,
            'platform': os.sys.platform
        }
        
        return health_report
    
    def export_health_data(self, filepath: str) -> bool:
        """Export health data to file"""
        try:
            import json
            
            health_data = {
                'export_timestamp': datetime.now().isoformat(),
                'system_health': self.get_system_health(),
                'alert_history': self.get_alert_history(hours=168),  # 7 days
                'performance_stats': self.get_performance_stats(),
                'configuration': {
                    'check_interval': self.check_interval,
                    'alert_threshold_count': self.alert_threshold_count,
                    'recovery_timeout': self.recovery_timeout
                }
            }
            
            with open(filepath, 'w') as f:
                json.dump(health_data, f, indent=2, default=str)
            
            self.logger.info(f"Health data exported to {filepath}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to export health data: {e}")
            return False
    
    def __enter__(self):
        """Context manager entry"""
        self._start_time = datetime.now()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        if self.is_monitoring:
            asyncio.create_task(self.stop_monitoring())
