# Sensex Options Trading System - Architecture Documentation

## System Overview

This is a comprehensive automated trading system for Sensex options with Zerodha integration, designed to run on AWS EC2 with virtual environment isolation and systemd service management.

### Key Features
- **Multi-mode operation**: Debug (backtesting), Test (paper trading), Live (real money)
- **Secure authentication flow** with Zerodha KiteConnect API
- **Continuous operation** via systemd services
- **Comprehensive logging** and error handling
- **Telegram notifications** for system alerts and trade updates
- **Virtual environment isolation** for dependency management

---

## Directory Structure

```
/home/ubuntu/main_trading/
├── config.json                    # Main system configuration (encrypted credentials)
├── .env                           # Environment variables (API keys, tokens)
├── .trading_mode                  # Current trading mode flag file
├── main.py                        # System orchestrator and entry point
├── postback_server.py            # OAuth callback handler for Zerodha auth
├── debug_token_generator.py      # Authentication token management
├── manage_system.sh              # System management utilities
├── venv/                         # Python virtual environment
│   ├── bin/python3               # Isolated Python interpreter
│   └── lib/python3.10/site-packages/  # Dependencies
├── data/                         # Runtime data and token storage
│   ├── request_token.txt         # Current Zerodha request token
│   ├── request_token.txt.meta    # Token metadata (timestamp, source)
│   ├── access_token.txt          # Current Zerodha access token
│   ├── token_config.json         # Token management configuration
│   ├── tokens/                   # Token backups with timestamps
│   ├── raw/                      # Raw market data
│   └── archives/                 # Historical data archives
├── logs/                         # All system logs
│   ├── postback_server.log       # Authentication server logs
│   ├── trading.log               # Main trading system logs
│   ├── token_generator.log       # Token management logs
│   └── services/                 # Systemd service logs
├── services/                     # Systemd service definitions
│   ├── postback_server.service   # Authentication service
│   └── trading_system.service    # Main trading service
├── utils/                        # Utility modules
│   ├── secure_config_manager.py  # Configuration management
│   ├── notification_service.py   # Telegram notifications
│   ├── holiday_checker.py        # Trading day validation
│   ├── health_monitor.py         # System health monitoring
│   ├── data_manager.py           # Data collection and storage
│   ├── broker_adapter.py         # Zerodha API wrapper
│   ├── trading_service.py        # Core trading logic
│   └── database_layer.py         # Trade data persistence
├── telegram_bot_handler.py       # Telegram bot interface
└── nginx_setup.sh               # HTTPS proxy configuration
```

---

## Authentication Architecture

### Flow Diagram
```
Browser → Zerodha Login → OAuth Redirect → Postback Server → Token Storage → Trading System
```

### Components

#### 1. Postback Server (`postback_server.py`)
**Purpose**: Handles OAuth callbacks from Zerodha after user authentication

**Key Features**:
- Runs as systemd service on port 8001
- Handles both `/postback` and `/redirect` endpoints
- Saves tokens with metadata and backups
- Virtual environment compatible
- HTTPS proxy via nginx

**Critical Routes**:
- `GET/POST /postback` - Primary OAuth callback endpoint
- `GET/POST /redirect` - Secondary OAuth callback endpoint (alias)
- `GET /health` - System health check
- `GET /get_token` - Token retrieval for generators
- `GET /clear_token` - Token cleanup
- `GET /status` - Detailed system status

**Token Storage**:
```bash
/home/ubuntu/main_trading/data/request_token.txt       # Primary token
/home/ubuntu/main_trading/data/request_token.txt.meta  # Metadata
/home/ubuntu/main_trading/data/tokens/request_token_YYYYMMDD_HHMMSS.txt  # Backups
```

#### 2. Debug Token Generator (`debug_token_generator.py`)
**Purpose**: Manages the complete authentication flow for development and testing

**Process**:
1. Checks postback server availability
2. Generates Zerodha authentication URL
3. Waits for user authentication via postback
4. Exchanges request token for access token
5. Saves access token for system use

**Configuration Sources**:
- Primary: `.env` file (environment variables)
- Fallback: `config.json` 
- Manual: Interactive input if configs missing

**Generated URLs**:
```
Auth URL: https://kite.zerodha.com/connect/login?api_key=API_KEY&v=3&postback_url=https://sensexbot.ddns.net/postback
```

#### 3. Token Configuration (`data/token_config.json`)
```json
{
    "request_token_file": "/home/ubuntu/main_trading/data/request_token.txt",
    "access_token_file": "/home/ubuntu/main_trading/data/access_token.txt", 
    "token_backup_dir": "/home/ubuntu/main_trading/data/tokens",
    "token_timeout_seconds": 300,
    "backup_tokens": true,
    "max_token_age_hours": 6
}
```

---

## System Services Architecture

### Service Dependencies
```
nginx.service (HTTPS proxy)
    ↓
postback_server.service (Authentication)
    ↓  
trading_system.service (Main system)
```

#### 1. Postback Server Service
**File**: `/etc/systemd/system/postback_server.service`
**Purpose**: Continuous OAuth callback handling

**Key Settings**:
- User: `ubuntu` (non-root for security)
- Working Directory: `/home/ubuntu/main_trading`
- Python: `/home/ubuntu/main_trading/venv/bin/python3`
- Auto-restart on failure
- Resource limits for free tier compatibility

**Management Commands**:
```bash
sudo systemctl start postback_server
sudo systemctl status postback_server  
sudo systemctl logs postback_server
```

#### 2. Trading System Service
**File**: `/etc/systemd/system/trading_system.service`
**Purpose**: Main trading operations with dynamic mode switching

**Dynamic Mode Selection**:
- Reads from `/home/ubuntu/main_trading/.trading_mode`
- Supported modes: `DEBUG`, `TEST`, `LIVE`, `DISABLED`
- Auto-restart on mode changes

**Resource Management**:
- Memory limit: 512MB (EC2 free tier)
- CPU quota: 70%
- Automatic cleanup on shutdown

---

## Network Architecture

### HTTPS Proxy Setup
**File**: `/etc/nginx/sites-available/sensexbot.ddns.net`

```
Internet (HTTPS:443) → Nginx → Flask Server (HTTP:8001)
```

**Key Features**:
- SSL termination at nginx level
- Let's Encrypt certificate management
- Security headers and rate limiting
- Specific postback request logging

**Critical Endpoints**:
- `https://sensexbot.ddns.net/postback` - OAuth callback
- `https://sensexbot.ddns.net/health` - Health monitoring
- `https://sensexbot.ddns.net/status` - System status

---

## Trading System Components

#### 1. Main Orchestrator (`main.py`)
**Purpose**: System entry point and mode coordinator

**Mode Operations**:
- **Debug Mode**: Historical backtesting with CSV data
- **Test Mode**: Paper trading with live data
- **Live Mode**: Real money trading

**Key Responsibilities**:
- Service initialization and health monitoring
- Mode-based operation switching  
- Resource management and cleanup
- Error handling and notifications

#### 2. Configuration Management (`utils/secure_config_manager.py`)
**Purpose**: Centralized, secure configuration handling

**Configuration Sources** (in priority order):
1. Environment variables (`.env`)
2. Main config file (`config.json`)  
3. Default fallback values

**Security Features**:
- Encrypted sensitive data storage
- Access logging and audit trails
- Credential redaction in logs

#### 3. Notification System (`utils/notification_service.py`)
**Purpose**: Multi-channel system notifications

**Notification Types**:
- System alerts (startup, shutdown, errors)
- Trading signals (entry, exit, P&L)
- Daily summaries and reports
- Health monitoring alerts

**Channels**:
- Telegram bot integration
- Log file notifications
- Console output

#### 4. Health Monitoring (`utils/health_monitor.py`) 
**Purpose**: Continuous system health assessment

**Monitored Components**:
- Service availability and responsiveness
- Token validity and expiration
- Network connectivity to Zerodha API
- Resource usage (memory, CPU, disk)
- Trading session status

---

## Data Management Architecture

#### 1. Data Collection (`data/data_collector.py`)
**Purpose**: Real-time market data acquisition and storage

**Data Sources**:
- Zerodha KiteConnect WebSocket feeds
- RESTful API endpoints for historical data
- Market instrument master files

**Storage Strategy**:
- Real-time data: Memory buffers with disk backup
- Historical data: Compressed archives by date
- Metadata: JSON format with indexing

#### 2. Database Layer (`utils/database_layer.py`)
**Purpose**: Trade data persistence and analytics

**Schema Design**:
- Trades table: Entry/exit details, P&L tracking
- Sessions table: Daily trading session metadata
- Positions table: Real-time position tracking
- Signals table: Generated trading signals

---

## Management and Operations

#### 1. System Management Script (`manage_system.sh`)
**Purpose**: Unified system control interface

**Available Commands**:
```bash
./manage_system.sh start          # Start all services
./manage_system.sh stop           # Stop all services  
./manage_system.sh restart        # Restart services
./manage_system.sh status         # Show service status
./manage_system.sh logs           # View recent logs
./manage_system.sh test-postback  # Test authentication endpoints
./manage_system.sh set-mode MODE  # Change trading mode
./manage_system.sh venv-test      # Test virtual environment
./manage_system.sh manual-start   # Manual startup for debugging
```

#### 2. Mode Management
**File**: `/home/ubuntu/main_trading/.trading_mode`

**Mode Values**:
- `DEBUG`: Historical backtesting mode
- `TEST`: Paper trading with live data
- `LIVE`: Real money trading  
- `DISABLED`: System idle/maintenance mode

**Mode Switching Process**:
1. Write new mode to `.trading_mode` file
2. Restart trading_system service
3. Service reads mode and initializes accordingly
4. Notification sent on successful mode change

---

## Security Architecture

#### 1. Credential Management
**Storage Locations**:
- API keys: `.env` file (restricted permissions)
- Access tokens: `data/` directory with metadata
- Backup tokens: Timestamped files with rotation

**Access Control**:
- File permissions: 600 (owner read/write only)
- Service isolation: Dedicated ubuntu user
- Network restrictions: Nginx proxy with security headers

#### 2. Token Lifecycle
**Request Token Flow**:
1. User authenticates via browser
2. Zerodha redirects to postback server
3. Token saved with metadata and backup
4. Token Generator exchanges for access token
5. Access token stored for trading operations
6. Automatic cleanup of expired tokens

**Security Measures**:
- Token timeout: 5 minutes for request tokens
- Automatic rotation of access tokens
- Encrypted storage of sensitive credentials
- Audit logging of all token operations

---

## Troubleshooting Guide

### Authentication Issues

#### Problem: "404 Not Found" on OAuth redirect
**Diagnosis**:
```bash
# Check if both endpoints work
curl -s https://sensexbot.ddns.net/postback
curl -s https://sensexbot.ddns.net/redirect

# Check nginx configuration
sudo nginx -t
```
**Resolution**:
- Ensure `/redirect` route exists in `postback_server.py`
- Verify nginx proxy configuration
- Check service status: `sudo systemctl status postback_server`

#### Problem: "Token too short" error
**Diagnosis**:
```bash
# Check token file contents
cat /home/ubuntu/main_trading/data/request_token.txt
wc -c /home/ubuntu/main_trading/data/request_token.txt
```
**Resolution**:
- Clear token files: `rm /home/ubuntu/main_trading/data/request_token*`
- Restart postback server: `sudo systemctl restart postback_server`
- Re-run authentication: `python3 debug_token_generator.py`

### Service Issues

#### Problem: "Port 8001 already in use"
**Diagnosis**:
```bash
sudo lsof -ti:8001
ps aux | grep postback_server
```
**Resolution**:
```bash
# Kill conflicting processes
sudo pkill -f "postback_server.py"
sudo systemctl restart postback_server
```

#### Problem: Virtual environment not detected
**Diagnosis**:
```bash
./manage_system.sh venv-test
which python3
echo $VIRTUAL_ENV
```
**Resolution**:
- Ensure services use correct Python path
- Check systemd service file: `ExecStart=/home/ubuntu/main_trading/venv/bin/python3`

### Network Issues

#### Problem: HTTPS endpoints return 502 Bad Gateway
**Diagnosis**:
```bash
# Test direct Flask connection
curl -s http://localhost:8001/health

# Check nginx error logs  
sudo tail -f /var/log/nginx/error.log
```
**Resolution**:
- Restart postback server: `sudo systemctl restart postback_server`
- Check nginx configuration: `sudo nginx -t && sudo systemctl reload nginx`

---

## Development Workflow

### Setting Up Development Environment
```bash
# 1. Clone and setup
cd /home/ubuntu/main_trading
source venv/bin/activate

# 2. Install/update dependencies
pip install -r requirements.txt

# 3. Configure credentials
cp .env.example .env
# Edit .env with your API keys

# 4. Test authentication flow
python3 debug_token_generator.py

# 5. Start in test mode
./manage_system.sh set-mode TEST
./manage_system.sh status
```

### Making Changes
```bash
# 1. Make code changes
# 2. Test locally if needed
./manage_system.sh manual-start

# 3. Commit and deploy
git add .
git commit -m "Description of changes"
git push origin hands-free-v2

# 4. Restart services
./manage_system.sh restart
```

### Monitoring Operations
```bash
# Real-time service monitoring
watch -n 5 './manage_system.sh status'

# Log monitoring
tail -f logs/postback_server.log
tail -f logs/trading.log

# System resource monitoring  
htop
df -h
```

---

## API Integration Details

### Zerodha KiteConnect Integration

**Authentication Flow**:
1. Generate auth URL with API key and postback URL
2. User completes OAuth flow in browser
3. Receive request token via postback
4. Exchange request token + API secret for access token
5. Use access token for all subsequent API calls

**API Endpoints Used**:
- `/session/token` - Token exchange
- `/instruments` - Instrument master data
- `/orders` - Order placement and management
- `/positions` - Position tracking
- `/portfolio/holdings` - Portfolio information

**Error Handling**:
- Rate limit management (3 requests/second)
- Token refresh on expiration
- Network retry logic with exponential backoff
- Graceful degradation on API unavailability

---

## Performance Considerations

### Resource Optimization
- Memory-efficient data structures for real-time processing
- Disk I/O minimization with smart caching
- Network request batching and compression
- CPU usage optimization with async processing

### Scalability Features
- Horizontal scaling via service replication
- Database sharding for large datasets
- Load balancing for multiple trading strategies
- Microservice architecture for component independence

### Monitoring Metrics
- System uptime and availability
- API response times and success rates
- Trading performance metrics (Sharpe ratio, drawdown)
- Resource utilization trends

This architecture ensures reliable, scalable, and maintainable automated trading operations while providing comprehensive debugging capabilities and operational transparency.
