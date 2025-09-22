#!/usr/bin/env python3
"""
Risk Manager with Atomic SQLite Operations
Enforces daily trading limits and position sizing
"""
import aiosqlite
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class RiskManager:
    """Manages trading risk with atomic database operations."""
    
    def __init__(self, config: Dict[str, Any], db_path: str = "trades.db"):
        self.config = config
        self.db_path = db_path
        self.lock = asyncio.Lock()
        self._init_db()
    
    async def _init_db(self):
        """Initialize SQLite database with risk tracking tables."""
        async with aiosqlite.connect(self.db_path) as db:
            # Daily limits table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_limits (
                    date TEXT PRIMARY KEY,
                    trades_today INTEGER DEFAULT 0,
                    sl_hits INTEGER DEFAULT 0,
                    daily_pnl REAL DEFAULT 0.0,
                    max_loss_reached BOOLEAN DEFAULT FALSE,
                    trading_halted BOOLEAN DEFAULT FALSE,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Individual trades table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT,
                    time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    symbol TEXT,
                    side TEXT,  -- BUY/SELL
                    quantity INTEGER,
                    entry_price REAL,
                    exit_price REAL,
                    pnl REAL,
                    sl_hit BOOLEAN DEFAULT FALSE,
                    mode TEXT,  -- TEST/PAPER/LIVE
                    order_id TEXT,
                    status TEXT DEFAULT 'OPEN'
                )
            """)
            
            # Positions table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT,
                    side TEXT,
                    quantity INTEGER,
                    average_price REAL,
                    entry_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    mode TEXT,
                    status TEXT DEFAULT 'ACTIVE'
                )
            """)
            
            await db.commit()
            logger.info(f"✅ Risk Manager database initialized: {self.db_path}")
    
    async def can_trade(self) -> Dict[str, Any]:
        """Check if trading is allowed based on all risk parameters."""
        async with self.lock:
            today = datetime.now().strftime('%Y-%m-%d')
            
            async with aiosqlite.connect(self.db_path) as db:
                # Get current daily stats
                cursor = await db.execute("""
                    SELECT trades_today, sl_hits, daily_pnl, max_loss_reached, trading_halted
                    FROM daily_limits WHERE date = ?
                """, (today,))
                result = await cursor.fetchone()
                
                if not result:
                    # First trade of the day - initialize
                    await self._initialize_daily_limits(db, today)
                    return {
                        "allowed": True,
                        "reason": "First trade of the day",
                        "trades_today": 0,
                        "sl_hits": 0,
                        "daily_pnl": 0.0,
                        "risk_level": "LOW"
                    }
                
                trades_today, sl_hits, daily_pnl, max_loss, halted = result
                
                # Check various risk conditions
                reasons = []
                
                # Trade count limit
                if trades_today >= self.config.get("MAX_TRADES_PER_DAY", 3):
                    reasons.append(f"Max trades reached: {trades_today}/{self.config.get('MAX_TRADES_PER_DAY', 3)}")
                
                # Stop loss hits limit
                if sl_hits >= self.config.get("MAX_SL_HITS", 2):
                    reasons.append(f"Max SL hits reached: {sl_hits}/{self.config.get('MAX_SL_HITS', 2)}")
                
                # Daily loss limit
                daily_loss_cap = self.config.get("DAILY_LOSS_CAP", 25000)
                if daily_pnl <= -daily_loss_cap:
                    reasons.append(f"Daily loss cap hit: ₹{daily_pnl:,.0f}/₹{daily_loss_cap:,}")
                    max_loss = True
                
                # Trading halt
                if halted:
                    reasons.append("Trading manually halted")
                
                allowed = len(reasons) == 0
                risk_level = "HIGH" if daily_pnl < -5000 else "MEDIUM" if daily_pnl < 0 else "LOW"
                
                return {
                    "allowed": allowed,
                    "reason": "; ".join(reasons) if not allowed else "All checks passed",
                    "trades_today": trades_today,
                    "sl_hits": sl_hits,
                    "daily_pnl": round(daily_pnl, 2),
                    "max_loss_reached": max_loss,
                    "trading_halted": halted,
                    "risk_level": risk_level,
                    "daily_loss_cap": self.config.get("DAILY_LOSS_CAP", 25000)
                }
    
    async def increment_trade_count(self, trade_type: str = "ENTRY") -> int:
        """Atomically increment daily trade count."""
        async with self.lock:
            today = datetime.now().strftime('%Y-%m-%d')
            
            async with aiosqlite.connect(self.db_path) as db:
                # Atomic update
                await db.execute("""
                    INSERT INTO daily_limits (date, trades_today, last_updated)
                    VALUES (?, COALESCE((SELECT trades_today FROM daily_limits WHERE date=?), 0) + 1, CURRENT_TIMESTAMP)
                    ON CONFLICT(date) DO UPDATE SET
                        trades_today = trades_today + 1,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE date = ?
                """, (today, today, today))
                
                await db.commit()
                
                # Get updated count
                cursor = await db.execute(
                    "SELECT trades_today FROM daily_limits WHERE date=?", (today,)
                )
                result = await cursor.fetchone()
                count = result[0] if result else 1
                
                logger.info(f"📊 Trade count incremented: {count}/{self.config.get('MAX_TRADES_PER_DAY', 3)}")
                return count
    
    async def record_trade(self, trade_data: Dict[str, Any]) -> int:
        """Record a trade in the database."""
        async with self.lock:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("""
                    INSERT INTO trades (date, symbol, side, quantity, entry_price, 
                                      pnl, sl_hit, mode, order_id, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade_data.get("date", datetime.now().strftime('%Y-%m-%d')),
                    trade_data.get("symbol"),
                    trade_data.get("side"),
                    trade_data.get("quantity", 0),
                    trade_data.get("entry_price", 0.0),
                    trade_data.get("pnl", 0.0),
                    trade_data.get("sl_hit", False),
                    trade_data.get("mode", "TEST"),
                    trade_data.get("order_id", ""),
                    trade_data.get("status", "CLOSED")
                ))
                
                trade_id = cursor.lastrowid
                await db.commit()
                
                # Update daily P&L
                await self._update_daily_pnl(db, trade_data.get("pnl", 0.0))
                
                # Check if SL hit
                if trade_data.get("sl_hit", False):
                    await self._increment_sl_hits(db)
                
                logger.info(f"💾 Trade recorded: ID={trade_id}, P&L=₹{trade_data.get('pnl', 0):,.0f}")
                return trade_id
    
    async def _update_daily_pnl(self, db, pnl: float):
        """Update daily P&L atomically."""
        today = datetime.now().strftime('%Y-%m-%d')
        await db.execute("""
            INSERT INTO daily_limits (date, daily_pnl, last_updated)
            VALUES (?, COALESCE((SELECT daily_pnl FROM daily_limits WHERE date=?), 0) + ?, CURRENT_TIMESTAMP)
            ON CONFLICT(date) DO UPDATE SET
                daily_pnl = daily_pnl + ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE date = ?
        """, (today, today, pnl, pnl, today))
        await db.commit()
    
    async def _increment_sl_hits(self, db):
        """Increment SL hits counter."""
        today = datetime.now().strftime('%Y-%m-%d')
        await db.execute("""
            UPDATE daily_limits SET
                sl_hits = sl_hits + 1,
                last_updated = CURRENT_TIMESTAMP
            WHERE date = ?
        """, (today,))
        await db.commit()
    
    async def _initialize_daily_limits(self, db, date: str):
        """Initialize daily limits for new trading day."""
        await db.execute("""
            INSERT INTO daily_limits (date, trades_today, sl_hits, daily_pnl)
            VALUES (?, 0, 0, 0.0)
        """, (date,))
        await db.commit()
    
    async def get_daily_summary(self) -> Dict[str, Any]:
        """Get daily trading summary."""
        today = datetime.now().strftime('%Y-%m-%d')
        
        async with aiosqlite.connect(self.db_path) as db:
            # Daily stats
            cursor = await db.execute("""
                SELECT trades_today, sl_hits, daily_pnl, max_loss_reached
                FROM daily_limits WHERE date = ?
            """, (today,))
            daily_stats = await cursor.fetchone() or (0, 0, 0.0, False)
            
            # Today's trades
            cursor = await db.execute("""
                SELECT COUNT(*), SUM(pnl), AVG(pnl)
                FROM trades WHERE date = ? AND status = 'CLOSED'
            """, (today,))
            trade_stats = await cursor.fetchone() or (0, 0.0, 0.0)
            
            # Win rate
            cursor = await db.execute("""
                SELECT COUNT(*) FROM trades 
                WHERE date = ? AND status = 'CLOSED' AND pnl > 0
            """, (today,))
            wins = (await cursor.fetchone())[0]
            total_trades = trade_stats[0]
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            
            return {
                "date": today,
                "trades_today": daily_stats[0],
                "sl_hits": daily_stats[1],
                "daily_pnl": round(daily_stats[2], 2),
                "max_loss_reached": daily_stats[3],
                "total_closed_trades": trade_stats[0],
                "total_pnl": round(trade_stats[1] or 0, 2),
                "avg_pnl_per_trade": round(trade_stats[2] or 0, 2),
                "win_rate": round(win_rate, 1),
                "trading_allowed": await self.can_trade()["allowed"]
            }
    
    async def halt_trading(self, reason: str):
        """Emergency halt for manual intervention."""
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE daily_limits SET trading_halted = TRUE, last_updated = CURRENT_TIMESTAMP
                WHERE date = ?
            """, (today,))
            await db.commit()
        
        logger.critical(f"🛑 EMERGENCY HALT: {reason}")
    
    async def resume_trading(self):
        """Resume trading after halt."""
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE daily_limits SET trading_halted = FALSE, last_updated = CURRENT_TIMESTAMP
                WHERE date = ?
            """, (today,))
            await db.commit()
        
        logger.info("✅ Trading resumed")
