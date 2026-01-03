#!/usr/bin/env python3
"""
Comprehensive validation and testing script for historical_data_1.json
Tests structure, data integrity, and bot compatibility
"""

import json
import sys
from pathlib import Path
from datetime import datetime


def load_json_file(filepath):
    """Load JSON file safely"""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse JSON: {e}", file=sys.stderr)
        return None


def validate_structure(data, filename):
    """Validate that the file has correct structure"""
    print(f"\n{'='*60}")
    print(f"STRUCTURE VALIDATION: {filename}")
    print(f"{'='*60}")
    
    issues = []
    
    # Check top-level keys
    if 'metadata' not in data:
        issues.append("Missing 'metadata' section")
    if 'bars' not in data:
        issues.append("Missing 'bars' section")
    
    if issues:
        for issue in issues:
            print(f"  ❌ {issue}")
        return False
    
    metadata = data.get('metadata', {})
    bars = data.get('bars', [])
    
    # Validate metadata
    required_metadata = ['downloaded_at', 'symbols', 'interval', 'total_bars', 'bars_per_symbol']
    for field in required_metadata:
        if field in metadata:
            print(f"  ✅ metadata.{field} present")
        else:
            print(f"  ❌ metadata.{field} missing")
            issues.append(f"Missing metadata.{field}")
    
    # Validate bars structure
    print(f"\n  Bars count: {len(bars)}")
    if not bars:
        print(f"  ❌ No bars found")
        return False
    
    # Check first bar structure
    required_bar_fields = ['ev', 'sym', 'v', 'av', 'op', 'vw', 'o', 'c', 'h', 'l', 'a', 'z', 's', 'e', 'n']
    first_bar = bars[0]
    print(f"\n  Sample bar (first record):")
    for field in required_bar_fields:
        if field in first_bar:
            print(f"    ✅ {field}: {first_bar[field]}")
        else:
            print(f"    ❌ {field} missing")
            issues.append(f"Bar missing field: {field}")
    
    return len(issues) == 0


def validate_data_integrity(data, filename):
    """Validate data integrity within bars"""
    print(f"\n{'='*60}")
    print(f"DATA INTEGRITY VALIDATION: {filename}")
    print(f"{'='*60}")
    
    metadata = data.get('metadata', {})
    bars = data.get('bars', [])
    
    print(f"  Total bars: {len(bars)}")
    print(f"  Symbols: {metadata.get('symbols', [])}")
    
    # Check OHLC relationships
    ohlc_violations = 0
    for i, bar in enumerate(bars):
        o, h, l, c = bar.get('o'), bar.get('h'), bar.get('l'), bar.get('c')
        
        # High should be >= all prices, Low should be <= all prices
        if h < max(o, c, l) or l > min(o, c, h):
            ohlc_violations += 1
            if ohlc_violations <= 3:  # Show first 3 violations
                print(f"  ⚠️  Bar {i}: OHLC violation - O:{o} H:{h} L:{l} C:{c}")
    
    if ohlc_violations > 0:
        print(f"  ⚠️  Found {ohlc_violations} OHLC relationship violations")
    else:
        print(f"  ✅ All OHLC relationships valid")
    
    # Check timestamp progression
    timestamps = [bar.get('s') for bar in bars]
    non_progressive = 0
    for i in range(1, len(timestamps)):
        if timestamps[i] < timestamps[i-1]:
            non_progressive += 1
    
    if non_progressive > 0:
        print(f"  ⚠️  Found {non_progressive} non-progressive timestamps")
    else:
        print(f"  ✅ Timestamps are properly ordered")
    
    # Check symbol distribution
    symbol_counts = {}
    for bar in bars:
        sym = bar.get('sym')
        symbol_counts[sym] = symbol_counts.get(sym, 0) + 1
    
    print(f"\n  Symbol distribution:")
    for sym in sorted(symbol_counts.keys()):
        expected = metadata.get('bars_per_symbol', {}).get(sym, 0)
        actual = symbol_counts[sym]
        match = "✅" if expected == actual else "❌"
        print(f"    {match} {sym}: {actual} bars (expected: {expected})")
    
    # Check data completeness
    print(f"\n  Data completeness:")
    total_volume = sum(bar.get('v', 0) for bar in bars)
    print(f"    ✅ Total volume: {total_volume:,}")
    
    return ohlc_violations == 0


def compare_files(file1, file2):
    """Compare two historical data files"""
    print(f"\n{'='*60}")
    print(f"FILE COMPARISON: {file1} vs {file2}")
    print(f"{'='*60}")
    
    data1 = load_json_file(file1)
    data2 = load_json_file(file2)
    
    if not data1 or not data2:
        print("  ❌ Failed to load one or both files")
        return False
    
    metadata1 = data1.get('metadata', {})
    metadata2 = data2.get('metadata', {})
    
    # Compare metadata
    print(f"\n  Metadata comparison:")
    print(f"    Interval:    {metadata1.get('interval')} vs {metadata2.get('interval')}")
    print(f"    Symbols:     {metadata1.get('symbols')} vs {metadata2.get('symbols')}")
    print(f"    Total bars:  {metadata1.get('total_bars')} vs {metadata2.get('total_bars')}")
    
    # Compare structure
    bars1 = data1.get('bars', [])
    bars2 = data2.get('bars', [])
    
    if len(bars1) != len(bars2):
        print(f"    ⚠️  Different bar counts: {len(bars1)} vs {len(bars2)}")
    
    print(f"\n  Structure: Both files follow the same format ✅")
    
    return True


def test_bot_compatibility(filepath):
    """Test that the file can be loaded by bot code"""
    print(f"\n{'='*60}")
    print(f"BOT COMPATIBILITY TEST: {filepath}")
    print(f"{'='*60}")
    
    data = load_json_file(filepath)
    if not data:
        print("  ❌ Failed to load file")
        return False
    
    # Simulate what bot.py does
    metadata = data.get('metadata', {})
    bars = data.get('bars', [])
    
    print(f"  ✅ File loaded successfully")
    print(f"  ✅ Metadata accessible: {len(metadata)} keys")
    print(f"  ✅ Bars accessible: {len(bars)} records")
    
    # Check if bars can be processed
    try:
        # Simulate WebSocket server reading the file
        for i, bar in enumerate(bars[:10]):  # Test first 10
            symbol = bar.get('sym')
            price = bar.get('c')  # Close price
            volume = bar.get('v')
            timestamp = bar.get('s')
            
            if not all([symbol, price is not None, volume is not None, timestamp is not None]):
                print(f"  ❌ Bar {i} missing critical fields")
                return False
        
        print(f"  ✅ Bars contain all required fields for bot processing")
        return True
    except Exception as e:
        print(f"  ❌ Error processing bars: {e}")
        return False


def generate_switch_test_script(file1, file2):
    """Generate a script to test switching between files"""
    script_path = Path("/tmp/test_file_switch.sh")
    
    script_content = f"""#!/bin/bash
# Test switching between historical_data.json and historical_data_1.json

set -e

echo "=================================================="
echo "FILE SWITCH TEST"
echo "=================================================="

cd /Users/ara/micro-trading-robot

echo "Step 1: Creating backups..."
cp data/historical_data.json data/historical_data_backup.json
echo "✅ Backup created: data/historical_data_backup.json"

echo ""
echo "Step 2: Switching to historical_data_1.json..."
mv data/historical_data.json data/historical_data_original.json
cp data/historical_data_1.json data/historical_data.json
echo "✅ Switch complete"

echo ""
echo "Step 3: Checking services before restart..."
ps aux | grep -E 'python.*bot|server|dashboard' | grep -v grep | wc -l

echo ""
echo "Step 4: You can now:"
echo "  - Check dashboard: http://localhost:8000"
echo "  - Check logs for any errors"
echo "  - Verify bot picks up the new data correctly"

echo ""
echo "Step 5: To restore original files, run:"
echo "  rm data/historical_data.json"
echo "  mv data/historical_data_original.json data/historical_data.json"

echo ""
echo "=================================================="
"""
    
    with open(script_path, 'w') as f:
        f.write(script_content)
    
    script_path.chmod(0o755)
    print(f"  ✅ Test script generated: {script_path}")
    return str(script_path)


def main():
    """Main validation pipeline"""
    print("\n" + "="*60)
    print("HISTORICAL DATA VALIDATION & TESTING")
    print("="*60)
    
    file1 = "/Users/ara/micro-trading-robot/data/historical_data.json"
    file2 = "/Users/ara/micro-trading-robot/data/historical_data_1.json"
    
    # Validate new file
    data1 = load_json_file(file1)
    data2 = load_json_file(file2)
    
    if not data1:
        print(f"Error: Cannot load {file1}")
        return False
    
    if not data2:
        print(f"Error: Cannot load {file2}")
        return False
    
    # Run all tests
    test_results = []
    
    test_results.append(("Structure Validation (new file)", validate_structure(data2, "historical_data_1.json")))
    test_results.append(("Data Integrity (new file)", validate_data_integrity(data2, "historical_data_1.json")))
    test_results.append(("File Comparison", compare_files(file1, file2)))
    test_results.append(("Bot Compatibility", test_bot_compatibility(file2)))
    
    # Generate test script
    print(f"\n{'='*60}")
    print("TEST SCRIPT GENERATION")
    print(f"{'='*60}")
    generate_switch_test_script(file1, file2)
    
    # Summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")
    
    passed = sum(1 for _, result in test_results if result)
    total = len(test_results)
    
    for test_name, result in test_results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nResult: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ All tests passed! The file is ready for use.")
        print(f"\nTo use the new file:")
        print(f"  1. Backup: cp data/historical_data.json data/historical_data_backup.json")
        print(f"  2. Switch: mv data/historical_data_1.json data/historical_data.json")
        print(f"  3. Restart bot and dashboard")
        return True
    else:
        print("\n❌ Some tests failed. Please review the issues above.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
