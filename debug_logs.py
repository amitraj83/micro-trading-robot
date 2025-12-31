#!/usr/bin/env python3
"""
Debug utility to analyze trading logs and diagnose issues
"""
import json
import sys
from bot.tick_logger import TickLogger

def print_recent_ticks(n=50):
    """Print recent ticks"""
    logger = TickLogger()
    ticks = logger.read_recent_ticks(n)
    
    if not ticks:
        print("No tick logs found")
        return
    
    print(f"\n{'='*100}")
    print(f"RECENT TICKS (Last {len(ticks)})")
    print(f"{'='*100}")
    print(f"{'Time':<20} {'Price':<10} {'Vol':<6} {'Action':<10} {'Reason':<15} {'Status':<10}")
    print(f"{'-'*100}")
    
    for tick in ticks:
        print(f"{tick['timestamp']:<20} ${tick['price']:<9.2f} {tick['volume']:<6} "
              f"{tick['action'] or 'NONE':<10} {tick['reason'] or '-':<15} {tick['position_state']:<10}")

def print_recent_trades(n=20):
    """Print recent trades"""
    logger = TickLogger()
    trades = logger.read_recent_trades(n)
    
    if not trades:
        print("No trade logs found")
        return
    
    print(f"\n{'='*120}")
    print(f"RECENT TRADES (Last {len(trades)})")
    print(f"{'='*120}")
    print(f"{'Time':<20} {'Dir':<6} {'Entry':<10} {'Exit':<10} {'Reason':<10} {'Duration':<10} {'P/L':<12}")
    print(f"{'-'*120}")
    
    for trade in trades:
        entry_time = trade['entry_time'].split('T')[1][:8] if 'T' in trade['entry_time'] else trade['entry_time']
        exit_time = trade['exit_time'].split('T')[1][:8] if trade['exit_time'] and 'T' in trade['exit_time'] else (trade['exit_time'] or '-')
        
        print(f"{entry_time:<20} {trade['direction']:<6} ${trade['entry_price']:<9.2f} "
              f"${trade['exit_price']:<9.2f} {trade['exit_reason']:<10} "
              f"{trade['duration_seconds']:.1f}s{'':<5} {trade['pnl_pct']*100:+.2f}%")

def analyze_price_drop(start_price: float, end_price: float):
    """Analyze why SHORT wasn't triggered during price drop"""
    logger = TickLogger()
    analysis = logger.find_price_drop(start_price, end_price)
    
    if not analysis:
        print("No tick logs found")
        return
    
    print(f"\n{'='*100}")
    print(f"PRICE DROP ANALYSIS: {start_price} → {end_price}")
    print(f"{'='*100}")
    print(f"Drop Percentage: {analysis['drop_pct']*100:.2f}%")
    print(f"Expected SHORT Trigger: {'YES' if analysis['expected_short_trigger'] else 'NO'}")
    print(f"Ticks in Range: {len(analysis['ticks_in_range'])}")
    
    if analysis['potential_issues']:
        print(f"\nPOTENTIAL ISSUES:")
        for i, issue in enumerate(analysis['potential_issues'], 1):
            print(f"  {i}. {issue}")
    
    print(f"\nTICKS DURING DROP:")
    print(f"{'-'*100}")
    print(f"{'Time':<20} {'Price':<10} {'Vol':<6} {'Action':<10} {'Position':<10}")
    print(f"{'-'*100}")
    
    for tick in analysis['ticks_in_range']:
        print(f"{tick['timestamp'].split('T')[1]:<20} ${tick['price']:<9.2f} {tick['volume']:<6} "
              f"{tick['action'] or 'NONE':<10} {tick['position_state']:<10}")

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 debug_logs.py ticks [N]       - Show last N ticks (default 50)")
        print("  python3 debug_logs.py trades [N]      - Show last N trades (default 20)")
        print("  python3 debug_logs.py drop <start> <end>  - Analyze price drop")
        print("\nExamples:")
        print("  python3 debug_logs.py ticks")
        print("  python3 debug_logs.py ticks 100")
        print("  python3 debug_logs.py trades")
        print("  python3 debug_logs.py drop 170 156")
        return
    
    command = sys.argv[1].lower()
    
    if command == "ticks":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        print_recent_ticks(n)
    
    elif command == "trades":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        print_recent_trades(n)
    
    elif command == "drop":
        if len(sys.argv) < 4:
            print("Usage: python3 debug_logs.py drop <start_price> <end_price>")
            return
        start = float(sys.argv[2])
        end = float(sys.argv[3])
        analyze_price_drop(start, end)
    
    else:
        print(f"Unknown command: {command}")

if __name__ == "__main__":
    main()
