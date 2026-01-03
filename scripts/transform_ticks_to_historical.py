#!/usr/bin/env python3
"""
Transform trading ticks data to historical_data.json format
Converts JSON-lines tick data to aggregated 1-minute OHLC bars
"""

import json
import sys
from datetime import datetime
from collections import defaultdict
from pathlib import Path


def load_ticks_from_file(filepath):
    """Load JSON-lines format tick data"""
    ticks = []
    with open(filepath, 'r') as f:
        for line in f:
            if line.strip():
                try:
                    tick = json.loads(line)
                    ticks.append(tick)
                except json.JSONDecodeError as e:
                    print(f"Warning: Skipping invalid JSON line: {e}", file=sys.stderr)
                    continue
    return ticks


def aggregate_ticks_to_bars(ticks):
    """Aggregate ticks into 1-minute OHLC bars"""
    # Group ticks by symbol and minute
    bars_by_symbol_minute = defaultdict(list)
    
    for tick in ticks:
        symbol = tick.get('symbol', '').strip()
        timestamp = tick.get('timestamp', '')
        price = tick.get('price', 0)
        volume = tick.get('volume', 0)
        
        if not symbol or not price or not volume:
            continue
        
        # Parse timestamp and get minute boundary
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            # Create minute key: YYYY-MM-DD HH:MM
            minute_key = dt.strftime('%Y-%m-%d %H:%M')
            key = (symbol, minute_key, int(dt.timestamp() * 1000))  # millisecond timestamp
        except (ValueError, AttributeError):
            continue
        
        bars_by_symbol_minute[key].append({
            'price': price,
            'volume': volume,
            'timestamp': timestamp
        })
    
    # Convert grouped ticks to OHLC bars
    bars = []
    for (symbol, minute_key, timestamp_ms), ticks_in_bar in bars_by_symbol_minute.items():
        if not ticks_in_bar:
            continue
        
        # Sort by timestamp to ensure correct order
        sorted_ticks = sorted(ticks_in_bar, key=lambda x: x['timestamp'])
        
        prices = [t['price'] for t in sorted_ticks]
        volumes = [t['volume'] for t in sorted_ticks]
        
        open_price = prices[0]
        close_price = prices[-1]
        high_price = max(prices)
        low_price = min(prices)
        total_volume = sum(volumes)
        
        # Calculate volume-weighted average price
        vwap = sum(p * v for p, v in zip(prices, volumes)) / total_volume if total_volume > 0 else close_price
        
        # Polygon.io format
        bar = {
            "ev": "A",  # Aggregate
            "sym": symbol,
            "v": total_volume,  # Total volume
            "av": total_volume,  # Accumulated volume
            "op": open_price,  # Open
            "vw": vwap,  # Volume-weighted average price
            "o": open_price,
            "c": close_price,
            "h": high_price,
            "l": low_price,
            "a": vwap,  # Average price (using VWAP)
            "z": len(ticks_in_bar),  # Number of transactions
            "s": timestamp_ms,  # Start timestamp (milliseconds)
            "e": timestamp_ms + 59999,  # End timestamp (milliseconds, end of minute)
            "n": 1  # Number of items in aggregate
        }
        bars.append(bar)
    
    return bars


def build_historical_data_structure(bars):
    """Build the complete historical_data.json structure"""
    if not bars:
        print("Warning: No bars found in the data", file=sys.stderr)
        return None
    
    # Get unique symbols and count bars per symbol
    symbols = list(set(bar['sym'] for bar in bars))
    symbols.sort()
    
    bars_per_symbol = {}
    for symbol in symbols:
        bars_per_symbol[symbol] = len([b for b in bars if b['sym'] == symbol])
    
    # Get date range from timestamps
    timestamps = [bar['s'] for bar in bars]
    start_time = min(timestamps) if timestamps else None
    end_time = max(timestamps) if timestamps else None
    
    # Convert milliseconds to ISO format
    start_date = datetime.fromtimestamp(start_time / 1000).isoformat() if start_time else None
    end_date = datetime.fromtimestamp(end_time / 1000).isoformat() if end_time else None
    
    structure = {
        "metadata": {
            "downloaded_at": datetime.now().isoformat() + "Z",
            "symbols": symbols,
            "days_back": None,  # Not determinable from ticks
            "interval": "1m",
            "total_bars": len(bars),
            "bars_per_symbol": bars_per_symbol,
            "date_range": {
                "start": start_date,
                "end": end_date
            }
        },
        "bars": bars
    }
    
    return structure


def transform_and_save(input_file, output_file):
    """Main transformation pipeline"""
    print(f"Loading ticks from: {input_file}")
    ticks = load_ticks_from_file(input_file)
    print(f"Loaded {len(ticks)} ticks")
    
    if not ticks:
        print("Error: No ticks found in input file", file=sys.stderr)
        return False
    
    print("Aggregating ticks to 1-minute OHLC bars...")
    bars = aggregate_ticks_to_bars(ticks)
    print(f"Generated {len(bars)} bars")
    
    print("Building historical data structure...")
    historical_data = build_historical_data_structure(bars)
    
    if not historical_data:
        print("Error: Failed to build historical data structure", file=sys.stderr)
        return False
    
    # Save to file
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Saving to: {output_file}")
    with open(output_file, 'w') as f:
        json.dump(historical_data, f, indent=2)
    
    # Print summary
    metadata = historical_data['metadata']
    print("\n" + "="*60)
    print("TRANSFORMATION SUMMARY")
    print("="*60)
    print(f"Total bars:         {metadata['total_bars']}")
    print(f"Symbols:            {', '.join(metadata['symbols'])}")
    print(f"Bars per symbol:    {metadata['bars_per_symbol']}")
    print(f"Date range:         {metadata['date_range']['start']} to {metadata['date_range']['end']}")
    print(f"Output file:        {output_file}")
    print(f"Output file size:   {output_path.stat().st_size / 1024:.2f} KB")
    print("="*60)
    
    return True


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 transform_ticks_to_historical.py <input_ticks_file> <output_json_file>")
        print("\nExample:")
        print("  python3 transform_ticks_to_historical.py logs/trading_ticks-real-backup data/historical_data_1.json")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    if not Path(input_file).exists():
        print(f"Error: Input file not found: {input_file}", file=sys.stderr)
        sys.exit(1)
    
    success = transform_and_save(input_file, output_file)
    sys.exit(0 if success else 1)
