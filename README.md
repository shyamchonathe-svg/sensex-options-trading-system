# Sensex Options Trading System - Architecture Documentation

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture Components](#architecture-components)
3. [Core Modules](#core-modules)
4. [Data Flow](#data-flow)
5. [Trading Strategy](#trading-strategy)
6. [Risk Management](#risk-management)
7. [Authentication & Security](#authentication--security)
8. [Monitoring & Notifications](#monitoring--notifications)
9. [Deployment Architecture](#deployment-architecture)
10. [Configuration Management](#configuration-management)

## System Overview

The Sensex Options Trading System is a sophisticated, automated trading platform designed for executing EMA-based mean-reversion strategies on BSE Sensex weekly options. The system operates in multiple modes (DEBUG/TEST/LIVE) with comprehensive risk management, real-time monitoring, and Telegram-based command interface.

### Key Features
- **Automated EMA Strategy**: 10/20 period EMA crossover with tightness filtering
- **Multi-Mode Operation**: Debug backtesting, paper trading, and live execution
- **Risk Management**: Position sizing, daily loss limits, consecutive loss protection
- **Real-time Monitoring**: Health checks, system diagnostics, performance tracking
- **Telegram Integration**: Command interface with authentication and status reporting
- **HTTPS Authentication**: Secure Zerodha KiteConnect integration via SSL postback server
- **Data Management**: SQLite with WAL mode, automated archiving, data validation

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SENSEX OPTIONS TRADING SYSTEM                │
└─────────────────────────────────────────────────────────────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          │                         │                         │
    ┌─────▼─────┐            ┌──────▼──────┐         ┌───────▼───────┐
    │   DEBUG   │            │    TEST     │         │     LIVE      │
    │   MODE    │            │    MODE     │         │     MODE      │
    │Backtesting│            │Paper Trading│         │Real Execution │
    └─────┬─────┘            └──────┬──────┘         └───────┬───────┘
          │                         │                        │
          └─────────────────────────┼─────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────┐
│                            CORE ORCHESTRATOR                        │
│                        (main.py + integrated_e2e)                   │
└─────────────────────┬───────────────────────────────┬───────────────┘
                      │                               │
    ┌─────────────────▼─────────────────┐   ┌─────────▼─────────────────┐
    │         AUTHENTICATION            │   │      TELEGRAM INTERFACE   │
    │                                   │   │                           │
    │  ┌─────────────────────────────┐  │   │  ┌─────────────────────┐  │
    │  │    HTTPS Postback Server    │  │   │  │   Bot Handler       │  │
    │  │  - SSL Certificate Mgmt     │  │   │  │  - /login /status   │  │
    │  │  - Token Management         │  │   │  │  - /health /help    │  │
    │  │  - Secure Authentication    │  │   │  │  - Command Processing│  │
    │  └─────────────────────────────┘  │   │  └─────────────────────┘  │
    └───────────────┬───────────────────┘   └─────────────────────────────┘
                    │                                       │
                    │        ┌──────────────────────────────┘
                    │        │
    ┌───────────────▼────────▼───────────────────────────────────────────┐
    │                        TRADING ENGINE                              │
    │                                                                    │
    │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐ │
    │  │  Strategy Core  │  │  Risk Manager   │  │   Position Manager  │ │
    │  │  - EMA Analysis │  │  - Daily Limits │  │  - Entry/Exit Logic │ │
    │  │  - Signal Gen   │  │  - Position Size│  │  - SL/TP Management │ │
    │  │  - Entry/Exit   │  │  - Consecutive  │  │  - Time-based Exits │ │
    │  │    Conditions   │  │    Loss Track   │  │  - P&L Tracking     │ │
    │  └─────────────────┘  └─────────────────┘  └─────────────────────┘ │
    └────────────┬────────────────────────────────────────┬──────────────┘
                 │                                        │
    ┌────────────▼─────────────────┐        ┌─────────────▼──────────────┐
    │        DATA LAYER            │        │      BROKER INTEGRATION    │
    │                              │        │                            │
    │  ┌─────────────────────────┐ │        │  ┌──────────────────────┐  │
    │  │   Market Data Collector │ │        │  │   KiteConnect API    │  │
    │  │  - WebSocket Feeds      │ │        │  │  - Order Placement   │  │
    │  │  - 3-min OHLC Data     │ │        │  │  - Quote Fetching    │  │
    │  │  - Real-time Validation│ │        │  │  - Historical Data   │  │
    │  └─────────────────────────┘ │        │  └──────────────────────┘  │
    │                              │        │                            │
    │  ┌─────────────────────────┐ │        │  ┌──────────────────────┐  │
    │  │   SQLite Database       │ │        │  │   Options Chain      │  │
    │  │  - WAL Mode             │ │        │  │  - Strike Selection  │  │
    │  │  - Trade Auditing      │ │        │  │  - Expiry Management │  │
    │  │  - Session Management  │ │        │  │  - Symbol Generation │  │
    │  └─────────────────────────┘ │        │  └──────────────────────┘  │
    └──────────────────────────────┘        └───────────────────────────┘
                 │                                        │
    ┌────────────▼─────────────────────────────────────────▼──────────────┐
    │                     MONITORING & UTILITIES                          │
    │                                                                     │
    │  ┌─────────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
    │  │ Health Monitor  │  │ Notification │  │    Data Management      │ │
    │  │ - CPU/Memory    │  │   Service    │  │  - Archiving (Zipper)   │ │
    │  │ - Disk Usage    │  │ - Telegram   │  │  - Data Validation      │ │
    │  │ - Network Check │  │   Alerts     │  │  - Cleanup Routines     │ │
    │  │ - Process Track │  │ - HTML Format│  │  - Storage Optimization │ │
    │  └─────────────────┘  └──────────────┘  └─────────────────────────┘ │
    └─────────────────────────────────────────────────────────────────────┘
```

## Architecture Components

### 1. Core Orchestrator Layer

#### **Main Entry Point (`main.py`)**
- **Purpose**: Central system orchestrator and mode controller
- **Key Features**:
  - Command-line argument parsing
  - Mode switching (DEBUG/TEST/LIVE)
  - Async task coordination
  - Error handling and recovery
- **Dependencies**: All core modules

#### **Integrated E2E Trading System (`integrated_e2e_trading_system.py`)**
- **Purpose**: Complete automated trading engine
- **Key Features**:
  - Full lifecycle trading automation
  - SQLite auditing with WAL mode
  - WebSocket reliability management
  - Comprehensive risk controls
  - Real-time P&L tracking
- **Architecture Pattern**: Event-driven with async processing

### 2. Trading Bot Layer

#### **Live Trading Bot (`sensex_trading_bot_live.py`)**
- **Purpose**: Real-time trading execution engine
- **Key Features**:
  - 3-minute cycle processing
  - Real-time EMA analysis
  - Live order placement
  - Telegram trade notifications
  - Position monitoring
- **Data Flow**: WebSocket → Analysis → Decision → Broker → Database

#### **Debug Trading Bot (`sensex_trading_bot_debug.py`)**
- **Purpose**: Backtesting and strategy validation
- **Key Features**:
  - Historical data analysis
  - Strategy condition evaluation
  - Performance metrics calculation
  - Debug trace generation
- **Use Case**: Strategy development and optimization

### 3. Authentication & Security Layer

#### **HTTPS Postback Server (`postback_server.py`)**
- **Purpose**: Secure Zerodha authentication handling
- **Key Features**:
  - SSL certificate management (Let's Encrypt)
  - Dual protocol support (HTTPS:443, HTTP:8001)
  - Token lifecycle management
  - Beautiful authentication UI
  - Telegram notifications on auth events
- **Security**: SSL/TLS encryption, token expiration, request validation

```python
# Authentication Flow
1. Trading system initiates authentication
2. Zerodha redirects to HTTPS postback URL
3. Server captures request_token
4. Exchanges token for access_token
5. Saves token securely with timestamp
6. Notifies via Telegram
7. Token available for trading session
```

### 4. Data Management Layer

#### **Data Collector (`data/data_collector.py`)**
- **Purpose**: Market data acquisition and real-time processing
- **Key Features**:
  - WebSocket connection management
  - 3:25 PM IST data collection
  - Market schedule integration
  - Data validation and cleaning
- **Pattern**: Scheduled collection with real-time processing

#### **Data Manager (`utils/data_manager.py`)**
- **Purpose**: Market data handling and validation
- **Key Features**:
  - Data freshness validation
  - WebSocket initialization
  - Historical data management
  - Cache optimization
- **Integration**: Connects data collection to trading logic

#### **Database Layer (`utils/database_layer.py`)**
- **Purpose**: Thread-safe data persistence
- **Key Features**:
  - SQLite with WAL mode for concurrent access
  - Trade auditing and history
  - Session management
  - Data integrity checks
- **Schema**:
```sql
-- Core Tables
trades: id, date, session_id, side, strike, quantity, 
        entry_price, exit_price, outcome, pnl, signal_strength, mode

positions: trade_id, symbol, current_price, unrealized_pnl, 
           entry_time, exit_time, status

sessions: date, start_time, end_time, total_pnl, trade_count, 
          max_drawdown, win_rate
```

### 5. Communication & Monitoring Layer

#### **Telegram Bot Handler (`telegram/telegram_bot_handler.py`)**
- **Purpose**: Interactive command interface for system control
- **Commands**:
  - `/login` - Manual authentication during trading hours
  - `/status` - System and market status check
  - `/health` - Comprehensive system diagnostics
  - `/help` - Command documentation
- **Features**:
  - Real-time health monitoring
  - System resource tracking
  - Network connectivity checks
  - Authentication status validation

#### **Notification Service (`utils/notification_service.py`)**
- **Purpose**: Comprehensive alert system
- **Notification Types**:
  - Trade alerts (entry/exit confirmations)
  - System status updates
  - Risk management alerts
  - Daily performance summaries
  - Error notifications
- **Formatting**: HTML-formatted messages with emojis for clarity

#### **Health Monitor (`utils/health_monitor.py`)**
- **Purpose**: System health and performance monitoring
- **Metrics Tracked**:
  - CPU and memory usage
  - Disk space utilization
  - Network connectivity
  - Data freshness validation
  - Process health checks
- **Alerting**: Proactive notifications for system issues

### 6. Broker Integration Layer

#### **Broker Adapter (`utils/broker_adapter.py`)**
- **Purpose**: KiteConnect API abstraction
- **Key Features**:
  - Order placement wrapper
  - Market data retrieval
  - Error handling and retry logic
  - Rate limit management
- **Order Types**: Market orders with MIS product type for intraday trading

#### **Options Chain Manager (`optimized_sensex_option_chain.py`)**
- **Purpose**: Complete options chain handling
- **Key Features**:
  - Weekly expiry calculation
  - Strike selection logic (ATM ± 500 points)
  - Symbol generation (SENSEX{YYMMDD}{STRIKE}{CE/PE})
  - Instrument caching for performance
- **Strike Logic**:
  - Morning: ATM strike (rounded to nearest 100)
  - Afternoon: ATM - 175 points for volatility adjustment

## Core Modules

### Trading Strategy Implementation (`utils.py`)

#### **TradingStrategy Class**
```python
class TradingStrategy:
    """EMA-based mean reversion strategy for Sensex options"""
    
    # Entry Conditions (CE - Call Options)
    - Green candle: close > open
    - Bullish EMA: EMA10 > EMA20
    - EMA tightness: |EMA10 - EMA20| ≤ 51
    - Proximity: min(|open-EMA10|, |low-EMA10|) < 21
    
    # Entry Conditions (PE - Put Options)  
    - Red candle: close < open
    - Bearish EMA: EMA10 < EMA20
    - EMA tightness: |EMA10 - EMA20| ≤ 51
    - Proximity: min(|open-EMA10|, |high-EMA10|) < 21
    
    # Exit Conditions
    - Stop Loss: EMA20 breach (trend reversal)
    - Take Profit: |close - EMA20| > 150 points
    - Time Exit: Max hold time (CE: 60min, PE: 30min)
    - EMA Crossover: Signal reversal detection
```

#### **TradingHoursValidator Class**
```python
class TradingHoursValidator:
    """Market timing and holiday validation"""
    
    - Trading Hours: 9:15 AM - 3:30 PM IST
    - Market Days: Monday to Friday
    - Holiday Support: Configurable holidays list
    - Weekend Detection: Automatic filtering
```

#### **TelegramNotifier Class**
```python
class TelegramNotifier:
    """Telegram messaging with HTML formatting"""
    
    - Rich formatting support
    - Error handling and retry logic
    - Message queuing for rate limits
    - Debug trace sanitization
```

## Data Flow

### Real-time Trading Data Flow

```
1. Market Opens (9:15 AM IST)
   ↓
2. WebSocket Connection Established
   ↓
3. Real-time Tick Data → 3-minute OHLC Aggregation
   ↓
4. EMA Calculation (10 & 20 period) 
   ↓
5. Entry Condition Evaluation
   ├─ CE Signal: Green + EMA10>EMA20 + Tightness + Proximity
   └─ PE Signal: Red + EMA10<EMA20 + Tightness + Proximity
   ↓
6. Risk Management Validation
   ├─ Daily loss limits
   ├─ Position sizing (2% account balance)
   └─ Consecutive loss protection
   ↓
7. Order Placement (if conditions met)
   ├─ Market order execution
   ├─ Position recording in database
   └─ Telegram notification
   ↓
8. Position Monitoring (every 3-minute cycle)
   ├─ Exit condition evaluation
   ├─ Stop loss / Take profit checks
   └─ Time-based exit logic
   ↓
9. Exit Execution (when conditions met)
   ├─ Market order closing
   ├─ P&L calculation and recording
   └─ Telegram trade confirmation
   ↓
10. End of Day (3:30 PM IST)
    ├─ Data archiving
    ├─ Daily summary generation
    └─ System cleanup
```

### Historical Data Processing Flow

```
1. Data Collection (3:25 PM IST daily)
   ↓
2. Historical Data Fetch (Previous day + current day)
   ↓
3. Data Validation and Cleaning
   ↓
4. EMA Calculation and Signal Generation
   ↓
5. Backtesting Against Historical Conditions
   ↓
6. Performance Metrics Calculation
   ↓
7. Strategy Optimization Recommendations
   ↓
8. Debug Report Generation
   ↓
9. Data Archiving (Daily/Weekly/Monthly)
```

## Trading Strategy

### EMA-Based Mean Reversion Strategy

#### **Core Concept**
The strategy exploits short-term mean reversion opportunities when Sensex price moves away from EMA equilibrium, particularly when the 10 and 20 period EMAs are tightly coupled (indicating low volatility and potential breakout conditions).

#### **Technical Indicators**
- **Primary**: EMA10, EMA20 (Exponential Moving Averages)
- **Timeframe**: 3-minute candlesticks
- **Lookback**: Previous trading day + current day data

#### **Entry Logic - CE (Call Options)**
```python
Entry Conditions (ALL must be true):
1. Green Candle: close > open (bullish momentum)
2. EMA Bullish: EMA10 > EMA20 (short-term strength)
3. EMA Tightness: |EMA10 - EMA20| ≤ 51 (low volatility, ready for breakout)
4. Price Proximity: min(|open-EMA10|, |low-EMA10|) < 21 (price near EMA10)

Entry Price: Current market price of selected CE option
Stop Loss: EMA20 level (trend reversal protection)
```

#### **Entry Logic - PE (Put Options)**
```python
Entry Conditions (ALL must be true):
1. Red Candle: close < open (bearish momentum)
2. EMA Bearish: EMA10 < EMA20 (short-term weakness)  
3. EMA Tightness: |EMA10 - EMA20| ≤ 51 (low volatility, ready for breakout)
4. Price Proximity: min(|open-EMA10|, |high-EMA10|) < 21 (price near EMA10)

Entry Price: Current market price of selected PE option
Stop Loss: EMA20 level (trend reversal protection)
```

#### **Exit Logic**
```python
Exit Conditions (ANY triggers exit):
1. Stop Loss: Price breaches EMA20 (trend reversal)
2. Take Profit: |current_price - EMA20| > 150 (momentum exhaustion)
3. Time Exit: 
   - CE positions: Maximum 20 candles (60 minutes)
   - PE positions: Maximum 10 candles (30 minutes)
4. EMA Crossover Reversal:
   - CE: EMA10 crosses below EMA20
   - PE: EMA10 crosses above EMA20
```

#### **Strike Selection Strategy**
```python
Morning Session (9:15 AM - 12:00 PM):
- Strike: ATM (At The Money, rounded to nearest 100)
- Range: ATM ± 500 points (11 strikes total)

Afternoon Session (12:00 PM - 3:30 PM):
- Strike: ATM - 175 points (volatility adjustment)
- Range: ATM ± 500 points (11 strikes total)

Expiry Preference: Current week (Thursday expiry)
Symbol Format: SENSEX{YYMMDD}{STRIKE}{CE/PE}
Example: SENSEX25091185000CE (Sept 11, 2025, 85000 CE)
```

## Risk Management

### Position Sizing Framework

```python
Position Sizing Logic:
- Base Capital: Account balance
- Risk Per Trade: 2% of account balance
- Lot Size: 25 units per lot (Sensex options)
- Maximum Position: Calculated based on option premium and risk allocation

Example:
Account Balance: ₹500,000
Risk Per Trade: ₹10,000 (2%)
Option Premium: ₹400
Maximum Lots: ⌊₹10,000 ÷ (₹400 × 25)⌋ = 1 lot
```

### Daily Risk Controls

```python
Daily Risk Limits:
- Maximum Daily Loss: ₹25,000 (configurable)
- Maximum Trades Per Day: 3 trades
- Maximum Consecutive Losses: 2 trades
- Daily Loss Calculation: Cumulative realized P&L

Risk Actions:
- Daily limit reached → Trading disabled for the day
- Consecutive loss limit → Reduced position sizing
- Maximum trades reached → No new positions
```

### Real-time Risk Monitoring

```python
Continuous Risk Checks:
- Pre-trade validation (limits, position size, market conditions)
- In-trade monitoring (unrealized P&L, time decay, market volatility)
- Post-trade analysis (performance attribution, risk metrics update)

Risk Alerts:
- Approaching daily loss limit (80% threshold)
- Consecutive losses detected
- Unusual market volatility
- System health degradation
```

## Authentication & Security

### HTTPS Postback Server Architecture

#### **SSL Certificate Management**
```python
Certificate Provider: Let's Encrypt
Domain: sensexbot.ddns.net
Certificate Path: /etc/letsencrypt/live/sensexbot.ddns.net/fullchain.pem
Private Key Path: /etc/letsencrypt/live/sensexbot.ddns.net/privkey.pem

Auto-renewal: Managed via certbot
Validation: Automatic certificate validity checking
```

#### **Authentication Flow**
```python
1. Trading System Initialization:
   - Check existing access token validity
   - If expired/missing, initiate authentication

2. Authentication Request:
   - Generate Zerodha login URL with redirect
   - Redirect URL: https://sensexbot.ddns.net/postback
   - Open browser for manual login (or automated)

3. Zerodha Callback:
   - User completes Zerodha 2FA
   - Zerodha redirects to postback server
   - Server captures request_token

4. Token Exchange:
   - Exchange request_token for access_token
   - Validate token with test API call
   - Store token securely with timestamp

5. Token Management:
   - Automatic expiry detection (daily basis)
   - Token refresh when needed
   - Secure token storage and retrieval
```

#### **Security Features**
```python
Security Measures:
- HTTPS encryption for all authentication traffic
- Token expiry validation (daily refresh required)
- Request source validation
- Error handling for invalid requests
- Telegram notifications for auth events
- Automatic token cleanup on expiry

Dual Protocol Support:
- Primary: HTTPS on port 443 (production)
- Fallback: HTTP on port 8001 (testing/development)
```

### Configuration Security

```python
Configuration Protection:
- API keys stored in config.json (not in code)
- File permission restrictions (600 permissions)
- No hardcoded credentials in source code
- Secure configuration loading with error handling

API Key Management:
- Zerodha API Key: Read-only trading permissions
- Telegram Bot Token: Encrypted communication
- Access Token: Daily refresh cycle
```

## Monitoring & Notifications

### Health Monitoring System

#### **System Metrics Tracking**
```python
Health Monitor Components:
- CPU Usage: Real-time percentage tracking
- Memory Usage: Available vs used memory analysis  
- Disk Space: Storage utilization monitoring
- Network Connectivity: API endpoint reachability
- Data Freshness: Real-time data validation
- Process Health: Trading bot status checks

Monitoring Frequency:
- Real-time: Every 3-minute trading cycle
- Background: 15-minute comprehensive health checks
- Daily: End-of-day system summary
```

#### **Alert Thresholds**
```python
Critical Alerts (Immediate Notification):
- CPU Usage > 80%
- Memory Usage > 85%  
- Disk Space < 10% free
- Network connectivity lost
- Data feed disruption > 5 minutes
- Trading bot unresponsive

Warning Alerts (Monitor Closely):
- CPU Usage > 60%
- Memory Usage > 70%
- Disk Space < 20% free
- API rate limits approaching
- Authentication token near expiry
```

### Telegram Integration

#### **Command Interface**
```python
Available Commands:
/login   - Manual authentication (trading hours only)
/status  - Quick system status check
/health  - Comprehensive diagnostics
/help    - Command documentation

Command Features:
- Market hours validation
- Authentication status checking
- System resource monitoring
- Network connectivity testing
- Trading bot status verification
```

#### **Notification Types**
```python
Trade Notifications:
- Entry confirmation with strike, price, time
- Exit confirmation with P&L calculation
- Stop loss triggered alerts
- Take profit achieved notifications

System Notifications:  
- Daily trading summary (P&L, trades, performance)
- Authentication status updates
- Health check alerts (warnings/critical)
- Error notifications with context
- Market hours and holiday notifications

Formatting:
- HTML markup for rich formatting
- Emojis for quick visual identification
- Code blocks for technical details
- Structured layout for readability
```

#### **Notification Examples**
```html
Trade Entry:
🟢 <b>CE Trade Entered</b>
Strike: 85000 CE
Entry: ₹445.50
Time: 10:32 AM IST
SL: ₹420.00
Basis: EMA Crossover + Tightness

Daily Summary:
📊 <b>Trading Summary - Sept 11, 2025</b>
Trades: 3 | Wins: 2 | Losses: 1
P&L: +₹2,850
Win Rate: 66.7%
Max Drawdown: -₹1,200
```

## Deployment Architecture

### Server Environment

#### **AWS EC2 Configuration**
```python
Server Details:
- Instance: ip-172-31-44-44 (AWS EC2)
- Operating System: Ubuntu Server
- Python Environment: Virtual environment (venv)
- Domain: sensexbot.ddns.net (Dynamic DNS)

Directory Structure:
/home/ubuntu/main_trading/     # Main codebase
├── config.json                # System configuration
├── main.py                    # Entry point
├── integrated_e2e_trading_system.py
├── postback_server.py         # Authentication server
├── sensex_trading_bot_live.py
├── sensex_trading_bot_debug.py
├── optimized_sensex_option_chain.py
├── utils.py                   # Core utilities
├── data/                      # Data collection
│   └── data_collector.py
├── utils/                     # Utility modules
│   ├── data_manager.py
│   ├── database_layer.py
│   ├── notification_service.py
│   ├── health_monitor.py
│   ├── trading_service.py
│   ├── secure_config_manager.py
│   ├── zipper.py
│   ├── broker_adapter.py
│   ├── enums.py
│   └── TradingHoursValidator.py
├── telegram/                  # Telegram integration
│   ├── telegram_bot.py
│   └── telegram_bot_handler.py
├── option_data/              # Market data storage
├── logs/                     # Application logs
└── data/zipped/             # Archived data
```

#### **Process Management**
```python
Service Management:
- Mode Control: File-based flags (.trading_mode, .trading_disabled)
- Session Management: Database-backed trading sessions
- Health Monitoring: Background threads for system metrics
- Data Archiving: Automated daily/weekly/monthly compression

Startup Sequence:
1. Configuration validation
2. Market hours verification  
3. Authentication token check
4. Database initialization
5. WebSocket connection setup
6. Trading bot initialization
7. Telegram bot activation
8. Health monitoring start
```

#### **Network Configuration**
```python
Network Setup:
- HTTPS: Port 443 (SSL/TLS encrypted)
- HTTP: Port 8001 (fallback/testing)
- Domain: sensexbot.ddns.net
- SSL: Let's Encrypt certificates
- Firewall: Configured for trading ports

Connectivity:
- Zerodha API: HTTPS connections
- Telegram API: HTTPS webhook/polling
- Market Data: WebSocket feeds
- DNS: Dynamic DNS for domain resolution
```

### Operational Procedures

#### **Daily Startup Sequence**
```python
Morning Routine (8:00 AM IST):
1. System health check via /health command
2. Market status verification
3. Authentication token validation
4. If token expired: Manual /login via Telegram
5. Database connectivity verification
6. WebSocket connection testing
7. Trading bot initialization

Market Open (9:15 AM IST):
1. Real-time data feed activation
2. Options chain initialization
3. Strike selection calculation
4. Risk parameters validation
5. Trading strategy activation
6. Monitoring systems online
```

#### **Daily Shutdown Sequence**
```python
Market Close (3:30 PM IST):
1. Position closure verification
2. Daily P&L calculation
3. Performance summary generation
4. Data archiving initiation
5. Log file rotation
6. System cleanup
7. Daily summary Telegram notification
```

## Configuration Management

### Configuration Structure (`config.json`)

```json
{
  "strategy": {
    "name": "EMA_Mean_Reversion",
    "version": "2.0",
    "description": "EMA 10/20 crossover with tightness filter"
  },
  "indicators": {
    "ema_short_period": 10,
    "ema_long_period": 20,
    "ema_tightness_threshold": 51,
    "premium_deviation_threshold": 15,
    "min_signal_strength": 80
  },
  "risk_management": {
    "max_daily_loss": 25000,
    "max_trades_per_day": 3,
    "max_consecutive_losses": 2,
    "risk_per_trade_percent": 2,
    "lot_size": 25,
    "stop_loss_percent": 2,
    "target_percent": 4
  },
  "market_timing": {
    "market_open": "09:15",
    "market_close": "15:30",
    "data_collection_time": "15:30"
  },
  "data_retention": {
    "hot_storage_days": 1,
    "archive_retention_days": 90,
    "log_retention_days": 7
  },
  "notifications": {
    "telegram_enabled": true,
    "health_check_interval_minutes": 15,
    "eod_summary_enabled": true
  }
}
```

### Configuration Categories

#### **Strategy Parameters**
```python
EMA Configuration:
- Short Period: 10 (fast-moving average)
- Long Period: 20 (slow-moving average)  
- Tightness Threshold: 51 points (convergence detection)
- Signal Strength: 80% minimum confidence

Timeframe Settings:
- Primary: 3-minute candlesticks
- Lookback: Previous + current trading day
- Analysis Window: Rolling 20-period calculation
```

#### **Risk Management Parameters**
```python
Position Limits:
- Daily Loss Limit: ₹25,000 (circuit breaker)
- Risk Per Trade: 2% of account balance
- Maximum Daily Trades: 3 positions
- Consecutive Loss Limit: 2 trades maximum

Stop Loss & Target:
- Stop Loss: 2% below entry price
- Target Profit: 4% above entry price
- Time-based Exit: 60min CE, 30min PE
- Lot Size: 25 units (standard Sensex options)
```

#### **Market Timing Configuration**
```python
Trading Hours:
- Market Open: 9:15 AM IST
- Market Close: 3:30 PM IST
- Data Collection: 3:25 PM IST (pre-close)
- Analysis Window: 9:15 AM - 3:30 PM IST

Holiday Management:
- Configurable holidays list
- Automatic weekend detection
- Market status validation
```

#### **Data Management Configuration**
```python
Storage Policy:
- Hot Storage: 1 day (active trading data)
- Archive Retention: 90 days (compressed historical data)
- Log Retention: 7 days (system logs)

Archiving Schedule:
- Daily: End-of-day compression
- Weekly: Performance summaries
- Monthly: Deep archive and cleanup
```

## Technical Specifications

### Dependencies & Libraries

#### **Core Trading Libraries**
```python
Trading & Market Data:
- kiteconnect: Zerodha broker integration
- pandas: Data manipulation and analysis
- numpy: Numerical computations
- talib: Technical analysis indicators

Database & Storage:
- sqlite3: Local database with WAL mode
- threading: Thread-safe database operations
- json: Configuration management
- pickle: Data serialization
```

#### **Web & Communication**
```python
Web Services:
- flask: HTTPS postback server
- requests: HTTP API interactions
- httpx: Async HTTP client (where needed)
- ssl: SSL/TLS certificate management

Telegram Integration:
- telegram-bot-python: Bot framework
- asyncio: Asynchronous message handling
- json: Message formatting
```

#### **System & Utilities**
```python
System Monitoring:
- psutil: System resource monitoring
- logging: Application logging
- schedule: Task scheduling
- pytz: Timezone handling (IST)

Data Processing:
- datetime: Time and date operations
- time: Performance timing
- os: File system operations
- threading: Concurrent processing
```

### Performance Optimizations

#### **Database Optimizations**
```python
SQLite Configuration:
- WAL Mode: Write-Ahead Logging for concurrent access
- Connection Pooling: Reuse database connections
- Index Strategy: Primary keys and query optimization
- Transaction Batching: Group related operations

Query Optimization:
- Prepared statements for repeated queries
- Efficient data types (INTEGER, REAL, TEXT)
- Minimal data loading (SELECT specific columns)
- Background cleanup of old records
```

#### **Memory Management**
```python
Memory Optimization:
- Data streaming instead of bulk loading
- Periodic garbage collection
- Limited historical data retention in memory
- Efficient pandas DataFrame operations

Resource Management:
- Connection pooling for external APIs
- WebSocket connection reuse
- File handle management
- Thread pool optimization
```

#### **Network Optimization**
```python
API Efficiency:
- Request rate limiting compliance
- Connection reuse with keep-alive
- Exponential backoff for retries
- Compressed data transfers where possible

WebSocket Management:
- Heartbeat monitoring (2-minute timeout)
- Auto-reconnection with exponential backoff
- Rate limit handling with queue management
- Data validation and integrity checks
```

## Error Handling & Recovery

### Error Classification System

#### **Critical Errors (System Halt)**
```python
Authentication Failures:
- Invalid/expired API credentials
- Postback server unreachable
- SSL certificate issues
- Token exchange failures

Data Pipeline Failures:
- Database corruption or inaccessibility
- WebSocket feed complete failure
- Historical data unavailable
- Configuration file corruption
```

#### **Warning Errors (Degraded Operation)**
```python
Connectivity Issues:
- Intermittent WebSocket disconnections
- API rate limit encounters
- Telegram notification failures
- Temporary broker API unavailability

Data Quality Issues:
- Missing tick data (< 5 minutes)
- Stale historical data
- Incomplete options chain data
- Minor calculation inconsistencies
```

#### **Recoverable Errors (Auto-Retry)**
```python
Transient Failures:
- Network timeouts
- Temporary API errors
- Database lock conflicts
- File system temporary unavailability
```

### Recovery Mechanisms

#### **Automatic Recovery**
```python
WebSocket Recovery:
1. Connection health monitoring (2-minute heartbeat)
2. Automatic reconnection on failure
3. Exponential backoff (1s, 2s, 4s, 8s, max 60s)
4. Data gap detection and backfill
5. Telegram notification on recovery

Database Recovery:
1. WAL mode automatic recovery
2. Connection pool refresh
3. Transaction rollback on failures
4. Backup restoration if needed
5. Data integrity verification
```

#### **Manual Recovery Procedures**
```python
Authentication Recovery:
1. Telegram /login command
2. Manual browser authentication
3. Token validation and storage
4. System restart if needed

System Recovery:
1. Health check via /health command
2. Component-wise status verification
3. Selective service restart
4. Full system restart as last resort
```

## Performance Metrics & Monitoring

### Trading Performance Metrics

#### **Strategy Performance**
```python
Key Performance Indicators:
- Win Rate: Percentage of profitable trades
- Average P&L: Mean profit/loss per trade
- Maximum Drawdown: Largest peak-to-trough decline
- Sharpe Ratio: Risk-adjusted returns
- Profit Factor: Gross profit / Gross loss

Daily Tracking:
- Number of trades executed
- Daily P&L (realized + unrealized)
- Risk utilization (% of daily limit used)
- Signal accuracy (entry condition success rate)
- Exit efficiency (optimal vs actual exit timing)
```

#### **System Performance**
```python
Technical Metrics:
- Order execution latency (entry/exit timing)
- Data processing speed (tick-to-decision time)
- System uptime (% availability during market hours)
- Error rate (failures per total operations)
- Memory/CPU utilization peaks

Reliability Metrics:
- WebSocket connection stability
- Database query performance
- API response times
- Notification delivery success rate
```

### Monitoring Dashboard Concepts

#### **Real-time Monitoring**
```python
Live System Status:
- Current market position (CE/PE/None)
- Unrealized P&L
- Time remaining to exit
- Current EMA levels and signals
- System health indicators

Market Condition Monitoring:
- Sensex current price vs EMA levels
- Volatility indicators
- Volume analysis
- Option premium levels
```

#### **Historical Analysis**
```python
Performance Trends:
- Daily P&L trends
- Win rate by time of day
- Best/worst performing strikes
- Strategy effectiveness by market conditions

System Health Trends:
- Resource utilization over time
- Error frequency patterns
- Performance degradation indicators
- Capacity planning metrics
```

## Security Considerations

### Data Security

#### **Sensitive Data Protection**
```python
API Key Security:
- Stored in config.json with restricted permissions (600)
- Never logged or transmitted in plain text
- Automatic expiration and refresh cycle
- Separate keys for different environments

Trade Data Security:
- Local SQLite database (not cloud-exposed)
- Regular encrypted backups
- Access control via file permissions
- Audit trail for all data modifications
```

#### **Communication Security**
```python
Network Security:
- HTTPS encryption for all external communications
- SSL certificate validation
- Telegram bot token protection
- No hardcoded credentials in source code

System Security:
- Ubuntu server with security updates
- Firewall configuration for required ports only
- SSH key-based authentication
- Regular security audit logs
```

### Operational Security

#### **Access Control**
```python
System Access:
- SSH key authentication required
- Telegram chat ID validation
- Command authorization checks
- Session timeout implementation

Monitoring & Alerting:
- Failed authentication attempt tracking
- Unusual system behavior detection
- Resource usage anomaly alerts
- Security event logging
```

## Troubleshooting Guide

### Common Issues & Solutions

#### **Authentication Problems**
```python
Issue: "Token expired" or authentication fails
Solutions:
1. Use Telegram /login command during market hours
2. Check HTTPS server status: curl -k https://sensexbot.ddns.net/status
3. Verify SSL certificates: sudo certbot certificates
4. Restart postback server: sudo python3 postback_server.py
5. Manual authentication: python3 integrated_e2e_trading_system.py --mode test
```

#### **WebSocket Connection Issues**
```python
Issue: "Data feed disconnected" or stale data
Solutions:
1. Check internet connectivity: ping api.zerodha.com
2. Verify API rate limits not exceeded
3. Restart trading bot with fresh connection
4. Monitor /health for connection status
5. Check Zerodha service status
```

#### **Database Problems**
```python
Issue: "Database locked" or transaction failures
Solutions:
1. Check disk space: df -h
2. Verify database file permissions
3. Close competing database connections
4. Restart system if WAL mode corrupted
5. Restore from backup if necessary
```

#### **Trading Bot Unresponsive**
```python
Issue: Bot not executing trades or responding
Solutions:
1. Check system resources: /health command
2. Verify market hours and trading day
3. Check risk limits not exceeded
4. Restart bot with fresh initialization
5. Review logs for error patterns
```

### Log Analysis

#### **Log File Locations**
```python
Application Logs:
- sensex_trading_bot.log (main trading activity)
- postback_server.log (authentication events)
- health_monitor.log (system monitoring)
- notification_service.log (Telegram communications)

System Logs:
- /var/log/syslog (system events)
- ~/.pm2/logs/ (process management, if using PM2)
- /var/log/nginx/ (web server logs, if applicable)
```

#### **Log Pattern Analysis**
```python
Critical Patterns to Monitor:
- "ERROR" entries (system failures)
- "Authentication failed" (credential issues)
- "WebSocket disconnected" (data feed problems)
- "Database locked" (transaction conflicts)
- "Rate limit exceeded" (API quota issues)

Performance Patterns:
- Order execution times
- Data processing delays
- Memory usage spikes
- Network timeout frequencies
```

## Future Enhancements

### Potential System Improvements

#### **Strategy Enhancements**
```python
Advanced Features:
- Multi-timeframe analysis (1min, 5min, 15min)
- Additional technical indicators (RSI, MACD, Bollinger Bands)
- Machine learning signal validation
- Adaptive position sizing based on volatility
- Portfolio optimization across multiple strikes

Market Expansion:
- Bank Nifty options support
- Equity futures integration
- Multi-instrument correlation analysis
- Cross-market arbitrage opportunities
```

#### **Technical Improvements**
```python
Performance Optimizations:
- Redis caching for frequently accessed data
- Real-time streaming analytics
- Distributed processing capabilities
- Advanced backtesting framework
- Cloud deployment options (AWS/GCP)

Monitoring Enhancements:
- Web-based dashboard
- Mobile app integration
- Advanced alerting rules
- Performance analytics
- Risk attribution analysis
```

#### **Integration Expansions**
```python
Broker Integration:
- Multiple broker support (ICICI Direct, Angel One)
- Cross-broker arbitrage detection
- Consolidated portfolio management
- Risk aggregation across accounts

External Data Sources:
- News sentiment analysis
- Economic calendar integration
- Market depth analysis
- Volatility surface modeling
- Alternative data feeds
```
# Start HTTPS postback server (in separate terminal)
sudo python3 postback_server.py

# Run in test mode (paper trading)
python3 main.py --mode test

# Run in live mode (real trading)
python3 main.py --mode live

# Run Telegram bot interface
python3 main.py --mode bot

## Conclusion

The Sensex Options Trading System represents a sophisticated, production-ready automated trading platform designed for robust, reliable operation in live market conditions. The architecture emphasizes:

- **Reliability**: Comprehensive error handling, automatic recovery, and health monitoring
- **Security**: HTTPS authentication, secure credential management, and encrypted communications
- **Scalability**: Modular design supporting multiple trading modes and easy feature expansion
- **Transparency**: Detailed logging, real-time monitoring, and comprehensive reporting
- **Risk Management**: Multi-layered risk controls protecting against various failure modes

The system's modular architecture, extensive monitoring capabilities, and robust error handling make it suitable for both individual traders and institutional deployment, while maintaining the flexibility to adapt to changing market conditions and regulatory requirements.
