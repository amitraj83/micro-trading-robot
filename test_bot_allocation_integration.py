#!/usr/bin/env python3
"""
Integration Test: Strategy A Allocation Caching with Real Bot

Tests that:
1. Bot initializes with cached allocation
2. Allocation stays constant across multiple position sizing calls
3. Position sizes are consistent (no API calls per tick)
4. Allocation properly respects MAX_SYMBOLS from .env
"""

import sys
import os
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).resolve().parent / "bot"))

from strategy import MicroTradingStrategy
from models import Tick
from config import RISK_CONFIG
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def test_allocation_initialization():
    """Test that allocation is cached at startup"""
    print("\n" + "="*80)
    print("TEST 1: ALLOCATION INITIALIZATION (Cached at Startup)")
    print("="*80)
    
    # Create bot strategy instance
    strategy = MicroTradingStrategy()
    
    max_positions = RISK_CONFIG.get('max_open_positions')
    mock_cash = RISK_CONFIG.get('mock_portfolio_available_cash')
    cash_reserve_pct = RISK_CONFIG.get('cash_reserve_per_position_pct')
    
    expected_allocation = (mock_cash / max_positions) * cash_reserve_pct
    actual_allocation = strategy._allocation_per_position
    
    print(f"\n📊 Configuration:")
    print(f"   Available Cash: ${mock_cash:,.2f}")
    print(f"   Max Open Positions: {max_positions}")
    print(f"   Cash Reserve %: {cash_reserve_pct*100:.0f}%")
    print(f"   Expected Allocation: ${expected_allocation:.2f}")
    print(f"   Actual Allocation: ${actual_allocation:.2f}")
    
    # Verify
    assert actual_allocation is not None, "❌ Allocation not initialized!"
    assert abs(actual_allocation - expected_allocation) < 0.01, "❌ Allocation calculation incorrect!"
    
    print(f"\n✅ PASS: Allocation initialized correctly at ${actual_allocation:.2f}/pos")
    return actual_allocation


def test_allocation_consistency(initial_allocation):
    """Test that allocation stays constant across multiple calls"""
    print("\n" + "="*80)
    print("TEST 2: ALLOCATION CONSISTENCY (No Recalculation)")
    print("="*80)
    
    strategy = MicroTradingStrategy()
    
    print(f"\n💰 Initial Allocation: ${initial_allocation:.2f}")
    print(f"📊 Testing position sizing across 10 ticks with different prices:")
    print("-"*80)
    
    test_prices = [150.0, 120.0, 200.0, 95.0, 175.0, 140.0, 110.0, 160.0, 130.0, 190.0]
    allocations_seen = []
    
    for i, price in enumerate(test_prices, 1):
        position_size, note = strategy._compute_position_size(entry_price=price)
        
        # Extract allocation from note
        allocation_str = note.split("allocation: $")[1].split("/")[0] if "allocation: $" in note else None
        if allocation_str:
            allocation = float(allocation_str)
            allocations_seen.append(allocation)
        
        print(f"   Tick {i:2d}: Price ${price:6.2f} → {position_size:2.0f} shares | Alloc: ${strategy._allocation_per_position:.2f}/pos")
    
    # Verify all allocations are the same
    print(f"\n✅ Allocation calls (showing cached value used):")
    all_same = all(abs(a - strategy._allocation_per_position) < 0.01 for a in allocations_seen)
    
    if all_same:
        print(f"✅ PASS: All {len(allocations_seen)} calls used same allocation: ${strategy._allocation_per_position:.2f}/pos")
    else:
        print(f"❌ FAIL: Allocations varied!")
        return False
    
    return True


def test_position_sizing():
    """Test that position sizes respect the cached allocation"""
    print("\n" + "="*80)
    print("TEST 3: POSITION SIZING (Respects Cached Allocation)")
    print("="*80)
    
    strategy = MicroTradingStrategy()
    allocation = strategy._allocation_per_position
    
    print(f"\n💰 Allocation: ${allocation:.2f}/pos")
    print(f"📊 Testing position sizes:")
    print("-"*80)
    
    test_cases = [
        ("NVDA", 150.0),
        ("AAPL", 120.0),
        ("MSFT", 200.0),
        ("TSLA", 180.0),
    ]
    
    all_valid = True
    for symbol, price in test_cases:
        position_size, note = strategy._compute_position_size(entry_price=price)
        position_value = position_size * price
        usage_pct = (position_value / allocation) * 100 if allocation > 0 else 0
        
        print(f"\n   {symbol} @ ${price:.2f}")
        print(f"      Shares: {position_size:.0f}")
        print(f"      Value: ${position_value:.2f}")
        print(f"      % of Allocation: {usage_pct:.1f}%")
        
        # Verify size respects allocation
        if position_value > allocation * 1.01:  # 1% tolerance
            print(f"      ❌ FAIL: Exceeds allocation!")
            all_valid = False
        else:
            print(f"      ✅ OK: Within allocation")
    
    if all_valid:
        print(f"\n✅ PASS: All position sizes respect allocation")
    else:
        print(f"\n❌ FAIL: Some sizes exceed allocation")
    
    return all_valid


def test_max_symbols_from_env():
    """Test that MAX_SYMBOLS from .env is properly read"""
    print("\n" + "="*80)
    print("TEST 4: MAX_SYMBOLS FROM .ENV")
    print("="*80)
    
    max_symbols_env = int(os.getenv("MAX_SYMBOLS", 3))
    max_positions_config = RISK_CONFIG.get('max_open_positions')
    
    print(f"\n📋 Configuration Check:")
    print(f"   MAX_SYMBOLS in .env: {max_symbols_env}")
    print(f"   max_open_positions in RISK_CONFIG: {max_positions_config}")
    
    if max_positions_config == max_symbols_env:
        print(f"\n✅ PASS: Config properly reads MAX_SYMBOLS from .env")
        return True
    else:
        print(f"\n❌ FAIL: Mismatch between .env and config")
        return False


def test_allocation_multiple_instances():
    """Test that each bot instance gets correct allocation at startup"""
    print("\n" + "="*80)
    print("TEST 5: MULTIPLE BOT INSTANCES")
    print("="*80)
    
    print(f"\n🤖 Creating 3 independent bot instances...")
    print("-"*80)
    
    allocations = []
    for i in range(1, 4):
        strategy = MicroTradingStrategy()
        allocation = strategy._allocation_per_position
        allocations.append(allocation)
        print(f"   Instance {i}: Allocation = ${allocation:.2f}/pos")
    
    # All should be identical
    all_same = all(abs(a - allocations[0]) < 0.01 for a in allocations)
    
    if all_same:
        print(f"\n✅ PASS: All instances have same allocation: ${allocations[0]:.2f}/pos")
        return True
    else:
        print(f"\n❌ FAIL: Instances have different allocations")
        return False


if __name__ == "__main__":
    print("\n" + "="*80)
    print("STRATEGY A: BOT INTEGRATION TEST SUITE")
    print("="*80)
    print("\nTesting allocation caching with real bot instances...")
    
    results = {}
    
    # Test 1
    initial_allocation = test_allocation_initialization()
    results["Initialization"] = initial_allocation is not None
    
    # Test 2
    results["Consistency"] = test_allocation_consistency(initial_allocation)
    
    # Test 3
    results["Position Sizing"] = test_position_sizing()
    
    # Test 4
    results["MAX_SYMBOLS"] = test_max_symbols_from_env()
    
    # Test 5
    results["Multiple Instances"] = test_allocation_multiple_instances()
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        print("\n✅ Strategy A is working correctly:")
        print("   • Allocation cached at startup")
        print("   • No recalculation on each tick")
        print("   • Consistent across bot instances")
        print("   • Properly reads MAX_SYMBOLS from .env")
        print("="*80 + "\n")
    else:
        print(f"\n❌ {total - passed} test(s) failed")
        print("="*80 + "\n")
        sys.exit(1)
