#!/usr/bin/env python3
"""
Enhanced LIVE trades dumper with Excel/CSV/JSON export
Compatible with pandas 2.2+ and openpyxl 3.1+
"""

import sqlite3
import json
from datetime import datetime
import sys
import os
from pathlib import Path
import pandas as pd

PROJECT_PATH = os.getenv('PROJECT_PATH', '/home/ubuntu/sensex-options-trading-system')
DB_PATH = f"{PROJECT_PATH}/trades.db"
DUMP_DIR = f"{PROJECT_PATH}/live_dumps"

def export_to_excel(trade_list, filename):
    """Export trades to Excel with formatting"""
    try:
        df = pd.DataFrame(trade_list)
        
        # Reorder columns for readability
        display_cols = [
            'timestamp', 'symbol', 'side', 'quantity', 'entry_price', 
            'pnl', 'roi_percent', 'signal_strength', 'status'
        ]
        available_cols = [col for col in display_cols if col in df.columns]
        df_display = df[available_cols].copy()
        
        # Format columns
        df_display['timestamp'] = pd.to_datetime(df_display['timestamp']).dt.strftime('%Y-%m-%d %H:%M')
        df_display['pnl'] = df_display['pnl'].round(2)
        df_display['roi_percent'] = df_display['roi_percent'].round(1)
        df_display['signal_strength'] = df_display['signal_strength'].round(1)
        
        # Create Excel writer
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            # Main trades sheet
            df_display.to_excel(writer, sheet_name='Trades', index=False)
            
            # Summary stats
            summary_data = {
                'Metric': ['Total Trades', 'Total P&L', 'Win Rate', 'Avg P&L/Trade', 
                          'Max Win', 'Max Loss', 'Best ROI', 'Worst ROI'],
                'Value': [
                    len(trade_list),
                    f"₹{sum(t.get('pnl', 0) for t in trade_list):,.2f}",
                    f"{len([t for t in trade_list if t.get('pnl', 0) > 0])/max(len(trade_list), 1)*100:.1f}%",
                    f"₹{sum(t.get('pnl', 0) for t in trade_list)/max(len(trade_list), 1):,.2f}",
                    f"₹{max(t.get('pnl', 0) for t in trade_list):,.2f}",
                    f"₹{min(t.get('pnl', 0) for t in trade_list):,.2f}",
                    f"{max(t.get('roi_percent', 0) for t in trade_list):.1f}%",
                    f"{min(t.get('roi_percent', 0) for t in trade_list):.1f}%"
                ]
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary', index=False)
            
            # Signal analysis (if conditions exist)
            if any('conditions' in t for t in trade_list):
                conditions_df = pd.DataFrame([
                    {**t, 'condition_ema': t['conditions'].get('ema_tightness', False),
                     'condition_volume': t['conditions'].get('volume_spike', False)}
                    for t in trade_list if 'conditions' in t
                ])
                if not conditions_df.empty:
                    conditions_summary = conditions_df.groupby(['condition_ema', 'condition_volume'])['pnl'].agg(['count', 'sum', 'mean']).round(2)
                    conditions_summary.to_excel(writer, sheet_name='Signal_Analysis')
        
        print(f"✅ Excel export: {filename}")
        return True
        
    except ImportError:
        print("⚠️ openpyxl not installed - skipping Excel export")
        return False
    except Exception as e:
        print(f"❌ Excel export failed: {e}")
        return False

def main():
    """Enhanced dump with multi-format export"""
    today = datetime.now().strftime('%Y-%m-%d')
    base_name = f"{DUMP_DIR}/{today}"
    
    # Ensure dump directory
    Path(DUMP_DIR).mkdir(exist_ok=True)
    
    try:
        conn = sqlite3.connect(DB_PATH)
        
        # Enhanced query with more fields
        trades_query = """
            SELECT 
                t.id,
                t.date,
                t.timestamp,
                t.symbol,
                t.side,
                t.quantity,
                t.price as entry_price,
                COALESCE(t.pnl, 0) as pnl,
                t.signal_strength,
                t.conditions,
                t.status,
                t.created_at,
                p.avg_price,
                p.current_price,
                COALESCE(p.unrealized_pnl, 0) as unrealized_pnl,
                p.updated_at as position_updated
            FROM trades t
            LEFT JOIN positions p ON t.id = p.trade_id
            WHERE t.date = ? AND t.mode = 'LIVE'
            ORDER BY t.timestamp
        """
        
        trades = conn.execute(trades_query, (today,)).fetchall()
        if not trades:
            print(f"ℹ️ No LIVE trades found for {today}")
            return
        
        # Get column names
        columns = [description[0] for description in conn.description]
        
        # Process trades with pandas for efficiency
        trade_list = []
        total_pnl = 0
        winning_trades = 0
        
        for row in trades:
            trade_dict = dict(zip(columns, row))
            
            # Data cleaning
            trade_dict['timestamp'] = str(trade_dict['timestamp'])
            if trade_dict['conditions']:
                try:
                    trade_dict['conditions'] = json.loads(trade_dict['conditions'])
                except:
                    trade_dict['conditions'] = {}
            else:
                trade_dict['conditions'] = {}
            
            # Enhanced calculations
            entry_cost = trade_dict['entry_price'] * trade_dict['quantity']
            if entry_cost > 0:
                trade_dict['roi_percent'] = (trade_dict['pnl'] / entry_cost) * 100
            else:
                trade_dict['roi_percent'] = 0
            
            # Duration calculation
            if (trade_dict['status'] == 'CLOSED' and 
                trade_dict['position_updated'] and 
                trade_dict['timestamp'] != trade_dict['position_updated']):
                
                try:
                    entry_time = pd.to_datetime(trade_dict['timestamp'])
                    exit_time = pd.to_datetime(trade_dict['position_updated'])
                    trade_dict['duration_minutes'] = (exit_time - entry_time).total_seconds() / 60
                except:
                    trade_dict['duration_minutes'] = None
            else:
                trade_dict['duration_minutes'] = None
            
            trade_list.append(trade_dict)
            
            total_pnl += trade_dict['pnl']
            if trade_dict['pnl'] > 0:
                winning_trades += 1
        
        conn.close()
        
        # Summary statistics (pandas-powered)
        df_summary = pd.DataFrame(trade_list)
        summary = {
            'date': today,
            'total_trades': len(trade_list),
            'total_pnl': round(total_pnl, 2),
            'win_rate': round((winning_trades / len(trade_list)) * 100, 1) if trade_list else 0,
            'avg_pnl_per_trade': round(df_summary['pnl'].mean(), 2) if len(trade_list) > 0 else 0,
            'std_pnl': round(df_summary['pnl'].std(), 2) if len(trade_list) > 1 else 0,
            'sharpe_ratio': round((df_summary['pnl'].mean() / df_summary['pnl'].std()) * np.sqrt(252), 2) if len(trade_list) > 1 and df_summary['pnl'].std() > 0 else 0,
            'max_win': round(df_summary['pnl'].max(), 2),
            'max_loss': round(df_summary['pnl'].min(), 2),
            'avg_roi': round(df_summary['roi_percent'].mean(), 1) if 'roi_percent' in df_summary.columns else 0,
            'trades': trade_list
        }
        
        # Multi-format export
        exports = 0
        
        # JSON (primary)
        json_file = f"{base_name}.json"
        with open(json_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"✅ JSON export: {json_file}")
        exports += 1
        
        # CSV (pandas optimized)
        csv_file = f"{base_name}.csv"
        df_summary.to_csv(csv_file, index=False)
        print(f"✅ CSV export: {csv_file}")
        exports += 1
        
        # Excel (if openpyxl available)
        xlsx_file = f"{base_name}.xlsx"
        if export_to_excel(trade_list, xlsx_file):
            exports += 1
        
        # Console summary
        print(f"\n📊 *LIVE TRADING SUMMARY* ({today})")
        print(f"{'='*50}")
        print(f"💰  Total P&L:     ₹{total_pnl:+,.2f}")
        print(f"📈  Win Rate:      {summary['win_rate']}%")
        print(f"⚡  Sharpe Ratio:  {summary['sharpe_ratio']}")
        print(f"📊  Total Trades:  {len(trade_list)}")
        print(f"🎯  Avg ROI:       {summary['avg_roi']:.1f}%")
        print(f"📁  Exports:       {exports} files")
        print(f"{'='*50}")
        
        if len(trade_list) > 0:
            print(f"\n🔥 Top 3 Winners:")
            winners = df_summary.nlargest(3, 'pnl')[['timestamp', 'symbol', 'pnl', 'roi_percent']]
            for _, row in winners.iterrows():
                print(f"  • {row['timestamp'][:16]} {row['symbol'][:12]}: ₹{row['pnl']:+6.2f} ({row['roi_percent']:+4.1f}%)")
            
            print(f"\n💀 Biggest 3 Losers:")
            losers = df_summary.nsmallest(3, 'pnl')[['timestamp', 'symbol', 'pnl', 'roi_percent']]
            for _, row in losers.iterrows():
                print(f"  • {row['timestamp'][:16]} {row['symbol'][:12]}: ₹{row['pnl']:+6.2f} ({row['roi_percent']:+4.1f}%)")
        
    except Exception as e:
        print(f"❌ ERROR: Failed to dump trades: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
