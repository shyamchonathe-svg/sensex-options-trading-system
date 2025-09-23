#!/usr/bin/env python3
"""
Health Monitor - Monitors system health (CPU, memory, data freshness)
Sends alerts via NotificationService
"""

import asyncio
import logging
import psutil
from typing import Dict, Any
from config_manager import SecureConfigManager as ConfigManager
from data_manager import DataManager
from notification_service import NotificationService
from datetime import datetime
import json
import os


class HealthMonitor:
    def __init__(self, config_manager: ConfigManager, data_manager: DataManager,
                 logger: logging.Logger, notification_service: NotificationService):
        self.config_manager = config_manager
        self.data_manager = data_manager
        self.logger = logger
        self.notification_service = notification_service
        self.config = config_manager.get_config()
        self.logger.info("HealthMonitor initialized")

    async def monitor_system(self):
        """Monitor system health and send alerts."""
        while True:
            try:
                metrics = self._collect_metrics()
                self._save_metrics(metrics)
                if metrics['cpu_usage_percent'] > self.config.get('cpu_threshold', 80.0):
                    await self.notification_service.send_message(
                        f"⚠️ High CPU Usage: {metrics['cpu_usage_percent']:.1f}%"
                    )
                if metrics['memory_usage_percent'] > self.config.get('memory_threshold', 80.0):
                    await self.notification_service.send_message(
                        f"⚠️ High Memory Usage: {metrics['memory_usage_percent']:.1f}%"
                    )
                if not self.data_manager.is_data_fresh(self.config.get('data_freshness_threshold', 300)):
                    await self.notification_service.send_message("⚠️ Stale market data detected")
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                self.logger.error(f"Error monitoring system: {e}")
                await self.notification_service.send_message(f"❌ Health monitor error: {str(e)[:200]}")

    def _collect_metrics(self) -> Dict[str, Any]:
        """Collect system metrics."""
        try:
            cpu_usage = psutil.cpu_percent(interval=1)
            memory_usage = psutil.virtual_memory().percent
            data_fresh = self.data_manager.is_data_fresh()
            return {
                'timestamp': datetime.now().isoformat(),
                'cpu_usage_percent': cpu_usage,
                'memory_usage_percent': memory_usage,
                'data_freshness': data_fresh
            }
        except Exception as e:
            self.logger.error(f"Error collecting metrics: {e}")
            return {}

    def _save_metrics(self, metrics: Dict[str, Any]):
        """Save metrics to a file."""
        try:
            metrics_file = os.path.join(self.config.get('data_dir', 'option_data'), 'metrics.json')
            with open(metrics_file, 'w') as f:
                json.dump(metrics, f)
            self.logger.info("Saved system metrics")
        except Exception as e:
            self.logger.error(f"Error saving metrics: {e}")
