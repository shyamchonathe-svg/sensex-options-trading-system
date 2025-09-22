#!/bin/bash
# Hands-Free Daily Cleanup Script
# Runs at midnight via cron: 0 0 * * * /path/to/cleanup.sh

set -e  # Exit on any error

# Configuration
PROJECT_PATH="${PROJECT_PATH:-/home/ubuntu/sensex-options-trading-system}"
DATA_RAW="$PROJECT_PATH/data_raw"
ARCHIVES="$PROJECT_PATH/archives"
LOGS="$PROJECT_PATH/logs"
LIVE_DUMPS="$PROJECT_PATH/live_dumps"
TRADING_MODE_FLAG="$PROJECT_PATH/.trading_mode"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOGS/cleanup.log"
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" | tee -a "$LOGS/cleanup.log"
}

# Ensure directories exist
mkdir -p "$DATA_RAW" "$ARCHIVES" "$LIVE_DUMPS" "$LOGS"

cd "$PROJECT_PATH"

log "Starting daily cleanup..."

# 1. ZIP AND ARCHIVE DAILY DATA (if exists)
if [ -d "$DATA_RAW" ] && [ "$(ls -A $DATA_RAW 2>/dev/null)" ]; then
    TODAY=$(date +%Y-%m-%d)
    ZIP_FILE="$ARCHIVES/${TODAY}.zip"
    
    log "Archiving daily data to $ZIP_FILE"
    if command -v zip >/dev/null 2>&1; then
        # Create zip of all raw data files
        find "$DATA_RAW" -name "*.csv" -o -name "*.json" | while read -r file; do
            zip -r -m "$ZIP_FILE" "$file" 2>/dev/null || true
        done
        
        # Clean raw directory
        rm -f "$DATA_RAW"/*.csv "$DATA_RAW"/*.json 2>/dev/null || true
        
        if [ -f "$ZIP_FILE" ]; then
            log "Successfully archived $ZIP_FILE ($(du -h "$ZIP_FILE" | cut -f1))"
        else
            error "Archive creation failed"
        fi
    else
        error "zip command not found"
    fi
else
    log "No raw data to archive"
fi

# 2. PRUNE OLD LOGS (keep 7 days)
log "Pruning logs older than 7 days"
find "$LOGS" -name "*.log" -mtime +7 -delete 2>/dev/null || true

# Rotate current logs if too large (>10MB)
for log_file in "$LOGS"/*.log; do
    if [ -f "$log_file" ] && [ $(stat -c%s "$log_file" 2>/dev/null || echo 0) -gt 10485760 ]; then
        mv "$log_file" "${log_file}.old"
        log "Rotated large log file: $log_file"
    fi
done

# 3. DUMP LIVE TRADES (only if was LIVE mode)
if [ -f "$TRADING_MODE_FLAG" ]; then
    MODE=$(cat "$TRADING_MODE_FLAG" 2>&1)
    if [ "$MODE" = "LIVE" ]; then
        log "Dumping LIVE trades for performance analysis"
        
        # Create dump script on-the-fly if dump_live_trades.py doesn't exist
        if [ ! -f "dump_live_trades.py" ]; then
            cat > dump_live_trades.py << 'EOF'
#!/usr/bin/env python3
import sqlite3
import json
from datetime import datetime
import sys
import os

PROJECT_PATH = os.getenv('PROJECT_PATH', '/home/ubuntu/sensex-options-trading-system')
DB_PATH = f"{PROJECT_PATH}/trades.db"
DUMP_DIR = f"{PROJECT_PATH}/live_dumps"

today = datetime.now().strftime('%Y-%m-%d')
dump_file = f"{DUMP_DIR}/{today}.json"

# Ensure dump directory
os.makedirs(DUMP_DIR, exist_ok=True)

try:
    conn = sqlite3.connect(DB_PATH)
    
    # Get today's LIVE trades
    trades = conn.execute("""
        SELECT t.*, p.avg_price, p.current_price, p.unrealized_pnl
        FROM trades t
        LEFT JOIN positions p ON t.id = p.trade_id
        WHERE t.date = ? AND t.mode = 'LIVE'
        ORDER BY t.timestamp
    """, (today,)).fetchall()
    
    columns = [description[0] for description in conn.description]
    trade_list = []
    
    for row in trades:
        trade_dict = dict(zip(columns, row))
        # Add calculated fields
        trade_dict['entry_time'] = trade_dict['timestamp']
        trade_dict['duration_minutes'] = 0  # Would calculate from exit time
        trade_dict['roi_percent'] = (trade_dict['pnl'] / (trade_dict['price'] * trade_dict['quantity'])) * 100 if trade_dict['quantity'] > 0 else 0
        trade_list.append(trade_dict)
    
    # Write JSON dump
    with open(dump_file, 'w') as f:
        json.dump({
            'date': today,
            'total_trades': len(trade_list),
            'total_pnl': sum(t['pnl'] for t in trade_list),
            'win_rate': len([t for t in trade_list if t['pnl'] > 0]) / max(len(trade_list), 1) * 100,
            'trades': trade_list
        }, f, indent=2, default=str)
    
    conn.close()
    print(f"Successfully dumped {len(trade_list)} LIVE trades to {dump_file}")
    
except Exception as e:
    print(f"ERROR: Failed to dump trades: {e}", file=sys.stderr)
    sys.exit(1)
EOF
            chmod +x dump_live_trades.py
        fi
        
        # Run dump
        if command -v python3 >/dev/null 2>&1; then
            OUTPUT=$(python3 dump_live_trades.py 2>&1)
            if [ $? -eq 0 ]; then
                log "LIVE dump completed: $OUTPUT"
            else
                error "LIVE dump failed: $OUTPUT"
            fi
        else
            error "python3 not found"
        fi
    else
        log "Not in LIVE mode - skipping trade dump"
    fi
else
    log "No trading mode flag - skipping LIVE dump"
fi

# 4. CLEANUP RUNTIME FLAGS
log "Cleaning up runtime flags"
rm -f "$TRADING_MODE_FLAG" "$PROJECT_PATH/.trading_disabled" 2>/dev/null || true

# 5. RESTART SERVICES (if needed)
log "Restarting data collector service"
sudo systemctl restart data_collector.service 2>/dev/null || true

# 6. SYSTEM HEALTH CHECK
log "Running final health check"
DISK_USAGE=$(df "$PROJECT_PATH" | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 85 ]; then
    error "High disk usage: ${DISK_USAGE}% - manual cleanup recommended"
    # Could add Telegram alert here
else
    log "Disk usage: ${DISK_USAGE}% - healthy"
fi

CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1 | cut -d',' -f1 2>/dev/null || echo "0")
if [ "$CPU_USAGE" -gt 90 ]; then
    warning "High CPU usage: ${CPU_USAGE}%"
else
    log "CPU usage: ${CPU_USAGE}% - healthy"
fi

log "Daily cleanup completed successfully"
