#!/usr/bin/env python3
"""
Health Monitor - Monitors system health and sends alerts
Phase 2: Disk usage, memory, CPU, and market data freshness
"""

import asyncio
import logging
import psutil
from datetime import datetime, timedelta
import pytz
from utils.secure_config_manager import SecureConfigManager
from utils.data_manager import DataManager

logger = logging.getLogger(__name__)

class HealthMonitor:
    def __init__(self, config_manager: SecureConfigManager, data_manager: DataManager,
                 logger_obj: logging.Logger, notification_service=None):
        self.config_manager = config_manager
        self.data_manager = data_manager
        self.logger = logger_obj
        self.notification_service = notification_service
        self.ist = pytz.timezone('Asia/Kolkata')
        self.config = config_manager.get_all()
        self.logger.info("HealthMonitor initialized")

    async def monitor_system(self):
        """Monitor system metrics and alert on issues."""
        try:
            while True:
                try:
                    # Check system metrics
                    cpu_usage = psutil.cpu_percent(interval=1)
                    memory = psutil.virtual_memory()
                    disk = psutil.disk_usage(self.config.get('data_dir', '/home/ubuntu/main_trading/data/live_dumps'))
                    
                    metrics = {
                        'cpu_usage_percent': cpu_usage,
                        'memory_usage_percent': memory.percent,
                        'disk_usage_percent': (disk.used / disk.total) * 100,
                        'timestamp': datetime.now(self.ist).strftime('%Y-%m-%d %H:%M:%S')
                    }
                    
                    self.logger.info("Saved system metrics")
                    
                    # Check data freshness
                    latest_data = self.data_manager.latest_data.get('SENSEX')
                    if not latest_data or (datetime.now(self.ist) - latest_data.index[-1]).total_seconds() > 600:
                        self.logger.warning("No data for SENSEX")
                        if self.notification_service:
                            await self.notification_service.send_message("⚠️ Stale market data detected")
                    
                    # Alert on high usage
                    if cpu_usage > 80 and self.notification_service:
                        await self.notification_service.send_message(f"⚠️ High CPU usage: {cpu_usage:.1f}%")
                    if memory.percent > 80 and self.notification_service:
                        await self.notification_service.send_message(f"⚠️ High memory usage: {memory.percent:.1f}%")
                    if metrics['disk_usage_percent'] > 80 and self.notification_service:
                        await self.notification_service.send_message(f"⚠️ High disk usage: {metrics['disk_usage_percent']:.1f}%")
                    
                    await asyncio.sleep(60)
                
                except Exception as e:
                    self.logger.error(f"Error monitoring system: {e}")
                    if self.notification_service:
                        await self.notification_service.send_message(f"❌ Health monitor error: {str(e)[:200]}")
                    await asyncio.sleep(60)
        
        except KeyboardInterrupt:
            self.logger.info("Health monitor stopped")
