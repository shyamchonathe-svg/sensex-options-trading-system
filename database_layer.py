#!/usr/bin/env python3
"""
Database Layer - Manages SQLite database for trading sessions and positions
Supports trading session and position storage
"""

import sqlite3
import logging
from typing import Dict, Any
from datetime import datetime
import json


class DatabaseLayer:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._initialize_schema()
        self.logger.info(f"DatabaseLayer initialized with database: {db_path}")

    def _initialize_schema(self):
        """Initialize SQLite database schema."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Positions table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS positions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        strike INTEGER,
                        entry_price REAL,
                        exit_price REAL,
                        quantity INTEGER,
                        entry_time TEXT,
                        exit_time TEXT,
                        exit_reason TEXT,
                        pnl REAL,
                        metadata TEXT
                    )
                """)
                # Trading sessions table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trading_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT NOT NULL,
                        start_time TEXT,
                        end_time TEXT,
                        sensex_entry_price REAL,
                        positions_opened INTEGER,
                        positions_closed INTEGER,
                        total_pnl REAL,
                        total_signals INTEGER,
                        metadata TEXT,
                        UNIQUE(date)
                    )
                """)
                # System alerts table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS system_alerts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT,
                        alert_type TEXT,
                        message TEXT,
                        metadata TEXT
                    )
                """)
                conn.commit()
                self.logger.info("Database schema initialized")
        except sqlite3.Error as e:
            self.logger.error(f"Error initializing database schema: {e}")
            raise

    def save_position(self, position: Dict[str, Any]):
        """Save a position to the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO positions (
                        symbol, strike, entry_price, exit_price, quantity,
                        entry_time, exit_time, exit_reason, pnl, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    position.get('symbol'),
                    position.get('strike'),
                    position.get('entry_price'),
                    position.get('exit_price'),
                    position.get('quantity'),
                    position.get('entry_time').isoformat() if position.get('entry_time') else None,
                    position.get('exit_time').isoformat() if position.get('exit_time') else None,
                    position.get('exit_reason'),
                    position.get('pnl'),
                    json.dumps(position.get('metadata', {}))
                ))
                conn.commit()
                self.logger.info(f"Saved position: {position.get('symbol')} {position.get('quantity')} @ {position.get('entry_price')}")
        except sqlite3.Error as e:
            self.logger.error(f"Error saving position: {e}")
            raise

    def save_session(self, session: Dict[str, Any]):
        """Save or update a trading session in the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Check if session exists for the date
                cursor.execute("SELECT id FROM trading_sessions WHERE date = ?", (session.get('date'),))
                existing_session = cursor.fetchone()
                
                if existing_session:
                    # Update existing session
                    cursor.execute("""
                        UPDATE trading_sessions
                        SET start_time = ?, sensex_entry_price = ?, positions_opened = ?,
                            positions_closed = ?, total_pnl = ?, total_signals = ?, metadata = ?
                        WHERE date = ?
                    """, (
                        session.get('start_time').isoformat() if session.get('start_time') else None,
                        session.get('sensex_entry_price', 0.0),
                        session.get('positions_opened', 0),
                        session.get('positions_closed', 0),
                        session.get('total_pnl', 0.0),
                        session.get('total_signals', 0),
                        json.dumps(session.get('metadata', {})),
                        session.get('date')
                    ))
                    self.logger.info(f"Updated trading session: {session.get('date')}")
                else:
                    # Insert new session
                    cursor.execute("""
                        INSERT INTO trading_sessions (
                            date, start_time, sensex_entry_price, positions_opened,
                            positions_closed, total_pnl, total_signals, metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        session.get('date'),
                        session.get('start_time').isoformat() if session.get('start_time') else None,
                        session.get('sensex_entry_price', 0.0),
                        session.get('positions_opened', 0),
                        session.get('positions_closed', 0),
                        session.get('total_pnl', 0.0),
                        session.get('total_signals', 0),
                        json.dumps(session.get('metadata', {}))
                    ))
                    self.logger.info(f"Saved trading session: {session.get('date')}")
                conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Error saving trading session: {e}")
            raise

    def update_session(self, session: Dict[str, Any]):
        """Update an existing trading session in the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE trading_sessions
                    SET end_time = ?, positions_opened = ?, positions_closed = ?,
                        total_pnl = ?, total_signals = ?, metadata = ?
                    WHERE date = ?
                """, (
                    session.get('end_time').isoformat() if session.get('end_time') else None,
                    session.get('positions_opened', 0),
                    session.get('positions_closed', 0),
                    session.get('total_pnl', 0.0),
                    session.get('total_signals', 0),
                    json.dumps(session.get('metadata', {})),
                    session.get('date')
                ))
                conn.commit()
                self.logger.info(f"Updated trading session: {session.get('date')}")
        except sqlite3.Error as e:
            self.logger.error(f"Error updating trading session: {e}")
            raise

    def save_alert(self, alert_type: str, message: str, metadata: Dict[str, Any] = None):
        """Save a system alert to the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO system_alerts (timestamp, alert_type, message, metadata)
                    VALUES (?, ?, ?, ?)
                """, (
                    datetime.now().isoformat(),
                    alert_type,
                    message,
                    json.dumps(metadata or {})
                ))
                conn.commit()
                self.logger.info(f"Saved system alert: {alert_type}")
        except sqlite3.Error as e:
            self.logger.error(f"Error saving system alert: {e}")
            raise
