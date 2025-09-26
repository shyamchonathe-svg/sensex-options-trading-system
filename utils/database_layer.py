#!/usr/bin/env python3
"""
Thread-safe SQLite database layer with WAL mode
"""
import sqlite3
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class DatabaseLayer:
    """Thread-safe SQLite database for trade auditing"""
    
    def __init__(self, db_path: str = "trades.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
    
    def _init_db(self):
        """Initialize database with proper settings and schema"""
        with self.get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA cache_size=10000;")
            conn.commit()
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL,
                    session_id TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    side TEXT NOT NULL,
                    strike INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    outcome TEXT,
                    pnl REAL,
                    signal_strength REAL,
                    mode TEXT DEFAULT 'TEST',
                    status TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    end_time DATETIME,
                    mode TEXT NOT NULL
                )
            """)
            
            conn.execute("""
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
                )
            """)
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_date_session ON trades(date, session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON trades(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_session_id ON sessions(session_id)")
            
            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")
    
    @contextmanager
    def get_connection(self):
        """Context manager for thread-safe database connections"""
        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            try:
                yield conn
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Database transaction failed: {e}")
                raise
            finally:
                conn.close()
    
    def save_session(self, session: Dict[str, Any]) -> bool:
        """Save a trading session"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO sessions (session_id, start_time, mode)
                    VALUES (?, ?, ?)
                """, (
                    session['session_id'],
                    session['start_time'],
                    session['mode'].value
                ))
                logger.info(f"Session saved: {session['session_id']}")
                return True
        except Exception as e:
            logger.error(f"Failed to save session: {e}")
            return False
    
    def update_session(self, session: Dict[str, Any]) -> bool:
        """Update a trading session"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE sessions 
                    SET end_time = ?
                    WHERE session_id = ?
                """, (
                    session['end_time'],
                    session['session_id']
                ))
                logger.info(f"Session updated: {session['session_id']}")
                return True
        except Exception as e:
            logger.error(f"Failed to update session: {e}")
            return False
    
    def save_position(self, position: Dict[str, Any]) -> bool:
        """Save a position"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO positions 
                    (trade_id, symbol, quantity, avg_price)
                    VALUES (?, ?, ?, ?)
                """, (
                    position.get('trade_id'),
                    position['symbol'],
                    position['quantity'],
                    position['entry_price']
                ))
                position_id = cursor.lastrowid
                logger.info(f"Position saved: {position_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to save position: {e}")
            return False
    
    def record_trade(self, trade_data: Dict[str, Any]) -> bool:
        """Record a new trade in the database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO trades 
                    (date, session_id, side, strike, quantity, entry_price, signal_strength, mode, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade_data['date'],
                    trade_data['session_id'],
                    trade_data['side'],
                    trade_data['strike'],
                    trade_data['quantity'],
                    trade_data['entry_price'],
                    trade_data.get('signal_strength', 0.0),
                    trade_data.get('mode', 'TEST'),
                    trade_data.get('status', 'OPEN')
                ))
                
                trade_id = cursor.lastrowid
                conn.commit()
                logger.info(f"Trade recorded with ID: {trade_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to record trade: {e}")
            return False
    
    def update_trade_outcome(self, trade_id: int, outcome: str, exit_price: float = None, pnl: float = None, status: str = None):
        """Update trade outcome when position is closed"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                update_fields = ["outcome = ?"]
                params = [outcome]
                
                if exit_price is not None:
                    update_fields.append("exit_price = ?")
                    params.append(exit_price)
                
                if pnl is not None:
                    update_fields.append("pnl = ?")
                    params.append(pnl)
                
                if status is not None:
                    update_fields.append("status = ?")
                    params.append(status)
                
                query = f"""
                    UPDATE trades 
                    SET {', '.join(update_fields)}
                    WHERE id = ?
                """
                params.append(trade_id)
                cursor.execute(query, params)
                conn.commit()
                logger.info(f"Trade {trade_id} outcome updated: {outcome}")
                
        except Exception as e:
            logger.error(f"Failed to update trade outcome: {e}")
    
    def get_daily_stats(self, date: datetime, session_id: str) -> Dict[str, Any]:
        """Get daily trading statistics"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT COALESCE(SUM(pnl), 0) 
                    FROM trades 
                    WHERE date = ? AND session_id = ?
                """, (date.date(), session_id))
                total_pnl = cursor.fetchone()[0]
                
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM trades 
                    WHERE date = ? AND session_id = ?
                """, (date.date(), session_id))
                trade_count = cursor.fetchone()[0]
                
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM trades t1
                    WHERE t1.date = ? AND t1.session_id = ?
                    AND t1.outcome = 'SL'
                    AND NOT EXISTS (
                        SELECT 1 FROM trades t2 
                        WHERE t2.date = t1.date 
                        AND t2.session_id = t1.session_id
                        AND t2.timestamp > t1.timestamp 
                        AND t2.outcome != 'SL'
                    )
                """, (date.date(), session_id))
                consecutive_sl = cursor.fetchone()[0]
                
                return {
                    'total_pnl': float(total_pnl),
                    'trade_count': int(trade_count),
                    'consecutive_sl': int(consecutive_sl)
                }
                
        except Exception as e:
            logger.error(f"Failed to get daily stats: {e}")
            return {'total_pnl': 0.0, 'trade_count': 0, 'consecutive_sl': 0}
    
    def get_recent_trades(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most recent trades"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, date, side, strike, quantity, entry_price, 
                           exit_price, outcome, pnl, timestamp, status
                    FROM trades 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                """, (limit,))
                
                columns = [description[0] for description in cursor.description]
                trades = []
                
                for row in cursor.fetchall():
                    trade_dict = dict(zip(columns, row))
                    trades.append(trade_dict)
                
                return trades
                
        except Exception as e:
            logger.error(f"Failed to get recent trades: {e}")
            return []
