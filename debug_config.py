#!/usr/bin/env python3
"""Debug script to verify config values being loaded."""

import sys
import os

# Change to bot directory for imports
sys.path.insert(0, '/Users/ara/micro-trading-robot')
os.chdir('/Users/ara/micro-trading-robot')

from bot.config import (
    OPENING_RANGE_MINUTES,
    OPENING_RANGE_TICKS,
    RANGE_LOOKBACK_MAX_MINUTES,
    RANGE_LOOKBACK_MAX_TICKS,
    FETCH_INTERVAL_SECONDS,
    USE_OPENING_RANGE,
    STRATEGY_CONFIG
)

print("=" * 60)
print("CONFIG VALUES LOADED")
print("=" * 60)

print(f"\n🔧 Environment Settings:")
print(f"  FETCH_INTERVAL_SECONDS = {FETCH_INTERVAL_SECONDS}")
print(f"  USE_OPENING_RANGE = {USE_OPENING_RANGE}")

print(f"\n📊 Opening Range Settings:")
print(f"  OPENING_RANGE_MINUTES = {OPENING_RANGE_MINUTES} min")
print(f"  OPENING_RANGE_TICKS = {OPENING_RANGE_TICKS} ticks")
print(f"  → Build duration: {OPENING_RANGE_MINUTES} minutes = {OPENING_RANGE_TICKS} ticks")

print(f"\n📈 Range Lookback Settings:")
print(f"  RANGE_LOOKBACK_MAX_MINUTES = {RANGE_LOOKBACK_MAX_MINUTES} min")
print(f"  RANGE_LOOKBACK_MAX_TICKS = {RANGE_LOOKBACK_MAX_TICKS} ticks")
print(f"  → Max lookback: {RANGE_LOOKBACK_MAX_MINUTES} minutes = {RANGE_LOOKBACK_MAX_TICKS} ticks")

print(f"\n🎯 STRATEGY_CONFIG Values:")
print(f"  opening_range_ticks = {STRATEGY_CONFIG.get('opening_range_ticks', 'NOT SET')}")
print(f"  range_lookback_max_ticks = {STRATEGY_CONFIG.get('range_lookback_max_ticks', 'NOT SET')}")
print(f"  window_size = {STRATEGY_CONFIG.get('window_size', 'NOT SET')}")

print("\n" + "=" * 60)
print("EXPECTED vs ACTUAL")
print("=" * 60)
print(f"\n✅ If OPENING_RANGE_MINUTES=1:")
print(f"   Expected build time: 1 min = 60 ticks")
print(f"   Actual in config: {STRATEGY_CONFIG.get('opening_range_ticks')} ticks")

if STRATEGY_CONFIG.get('opening_range_ticks') == 60:
    print("   ✓ CONFIG IS CORRECT")
elif STRATEGY_CONFIG.get('opening_range_ticks') == 900:
    print("   ✗ CONFIG IS WRONG - shows 900 (15 min) instead of 60")
else:
    print(f"   ? UNEXPECTED VALUE: {STRATEGY_CONFIG.get('opening_range_ticks')}")
