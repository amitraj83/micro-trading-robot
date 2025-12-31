#!/usr/bin/env python3
"""Quick analysis of trading logs"""
import json
import sys

def analyze_logs():
    """Analyze tick and trade logs"""
    
    print("\n" + "="*120)
    print("TICK ANALYSIS - Recent Activity")
    print("="*120)
    
    try:
        with open("/tmp/trading_ticks.jsonl", "r") as f:
            ticks = [json.loads(line) for line in f]
        
        if not ticks:
            print("No ticks found")
            return
        
        # Show last 30 ticks
        print(f"\n{'Tick#':<6} {'Price':<10} {'Vol':<4} {'Action':<10} {'Reason':<20} {'State':<8} {'PnL':<12}")
        print("-"*120)
        
        for tick in ticks[-30:]:
            tick_num = tick.get('tick_count', 0)
            price = tick.get('price', 0)
            vol = tick.get('volume', 0)
            action = tick.get('action') or '-'
            reason = tick.get('reason') or '-'
            state = tick.get('position_state', '-')
            pnl = tick['metrics'].get('daily_pnl', 0)
            
            print(f"{tick_num:<6} ${price:<9.2f} {vol:<4} {action:<10} {reason:<20} {state:<8} ${pnl:>10.2f}")
        
    except FileNotFoundError:
        print("No tick logs found at /tmp/trading_ticks.jsonl")
    
    print("\n" + "="*120)
    print("TRADE ANALYSIS")
    print("="*120)
    
    try:
        with open("/tmp/trading_trades.jsonl", "r") as f:
            trades = [json.loads(line) for line in f]
        
        if not trades:
            print("No trades found")
            return
        
        print(f"\nTotal Trades: {len(trades)}")
        
        wins = sum(1 for t in trades if t['pnl_pct'] > 0)
        losses = sum(1 for t in trades if t['pnl_pct'] < 0)
        total_pnl = sum(t['pnl'] for t in trades)
        
        print(f"Wins: {wins}, Losses: {losses}, Win Rate: {wins/len(trades)*100:.1f}%")
        print(f"Total P/L: ${total_pnl:.3f}")
        
        print(f"\n{'#':<3} {'Dir':<5} {'Entry':<10} {'Exit':<10} {'Reason':<10} {'Duration':<10} {'P/L':<12} {'%':<8}")
        print("-"*120)
        
        for i, trade in enumerate(trades[-20:], 1):
            entry = trade['entry_price']
            exit_p = trade['exit_price']
            reason = trade['exit_reason']
            dur = trade['duration_seconds']
            pnl = trade['pnl']
            pct = trade['pnl_pct']
            direction = trade['direction']
            
            print(f"{i:<3} {direction:<5} ${entry:<9.2f} ${exit_p:<9.2f} {reason:<10} {dur:<9.1f}s ${pnl:>10.3f} {pct*100:>+7.2f}%")
    
    except FileNotFoundError:
        print("No trade logs found at /tmp/trading_trades.jsonl")

def find_price_drop_issue(start_price, end_price):
    """Find why SHORT wasn't triggered during price drop"""
    
    print(f"\n" + "="*120)
    print(f"PRICE DROP ANALYSIS: {start_price} → {end_price}")
    print("="*120)
    
    try:
        with open("/tmp/trading_ticks.jsonl", "r") as f:
            ticks = [json.loads(line) for line in f]
        
        # Find ticks in the price range
        in_range = []
        for tick in ticks:
            price = tick['price']
            if min(start_price, end_price) <= price <= max(start_price, end_price):
                in_range.append(tick)
        
        print(f"\nTicks in range: {len(in_range)}")
        print(f"Price moved: {abs(start_price - end_price):.2f} ({abs(start_price - end_price)/start_price*100:.2f}%)")
        
        if not in_range:
            print("No ticks found in this price range")
            return
        
        # Analyze
        print(f"\n{'Time':<30} {'Price':<10} {'Vol':<4} {'Action':<10} {'Reason':<20} {'State':<8}")
        print("-"*120)
        
        for tick in in_range:
            ts = tick['timestamp']
            price = tick['price']
            vol = tick['volume']
            action = tick['action'] or '-'
            reason = tick['reason'] or '-'
            state = tick['position_state']
            
            print(f"{ts:<30} ${price:<9.2f} {vol:<4} {action:<10} {reason:<20} {state:<8}")
        
        # Analysis
        first = in_range[0]
        print(f"\n📊 ANALYSIS:")
        print(f"  • Position state when drop started: {first['position_state']}")
        
        # Check if SHORT was triggered
        short_trades = [t for t in in_range if t['action'] == 'CLOSE' and t['reason'] == 'TP']
        if short_trades:
            print(f"  ✓ SHORT position(s) WERE triggered: {len(short_trades)} trades closed")
        else:
            print(f"  ✗ NO SHORT position triggered during drop")
            
            # Why not?
            if first['position_state'] == 'OPEN':
                print(f"    → Reason: Position already OPEN (can't open new trade)")
            else:
                # Check why no entry
                print(f"    → Checking entry conditions...")
                
                # Calculate momentum
                prices = [t['price'] for t in in_range]
                price_change = (prices[-1] - prices[0]) / prices[0]
                print(f"    → Price change: {price_change*100:.3f}% (need < -0.05%)")
                
                volumes = [t['volume'] for t in in_range]
                avg_vol = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else 1
                vol_spike = volumes[-1] > avg_vol * 1.5
                print(f"    → Volume spike: {vol_spike} (current vol {volumes[-1]} vs avg {avg_vol:.0f})")
    
    except FileNotFoundError:
        print("No tick logs found")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "drop":
        if len(sys.argv) < 4:
            print("Usage: python3 analyze_logs.py drop <start_price> <end_price>")
            sys.exit(1)
        find_price_drop_issue(float(sys.argv[2]), float(sys.argv[3]))
    else:
        analyze_logs()
