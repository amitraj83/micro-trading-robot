#!/usr/bin/env python3
"""Quick test of API retry logic"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "bot"))

from strategy import MicroTradingStrategy

print("Creating strategy instance with retry logic...")
s = MicroTradingStrategy()

if s._allocation_per_position:
    print(f"✅ Success! Allocation: ${s._allocation_per_position:.2f}")
else:
    print("❌ Failed - API could not be reached")
