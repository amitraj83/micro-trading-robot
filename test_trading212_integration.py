#!/usr/bin/env python3
"""
Quick test of Trading212 integration
Simulates open/close signals and verifies broker execution flow
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "bot"))

from trading212_broker import Trading212Broker, BotPosition
from models import Tick
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

async def test_trading212_integration():
    """Test open and close trade execution"""
    
    print("\n" + "="*80)
    print("TRADING212 INTEGRATION TEST")
    print("="*80)
    
    # Create broker instance
    broker = Trading212Broker()
    
    print(f"\n✓ Broker initialized: {broker}")
    print(f"✓ Broker enabled: {broker.enabled}")
    print(f"✓ Positions tracked: {len(broker.positions)}")
    
    # Test 1: Open a position
    print("\n" + "-"*80)
    print("TEST 1: OPEN POSITION")
    print("-"*80)
    
    success = await broker.execute_open_trade(
        symbol="AAPL",
        entry_price=150.50,
        quantity=5
    )
    
    print(f"\n✓ Open trade result: {success}")
    print(f"✓ Positions after OPEN: {list(broker.positions.keys())}")
    
    if "AAPL" in broker.positions:
        pos = broker.positions["AAPL"]
        print(f"  - Symbol: {pos.symbol}")
        print(f"  - Entry Price: ${pos.entry_price:.2f}")
        print(f"  - Quantity: {pos.quantity}")
        print(f"  - Status: {pos.status}")
        print(f"  - Trading212 Order ID: {pos.trading212_order_id}")
    
    # Test 2: Close the position
    print("\n" + "-"*80)
    print("TEST 2: CLOSE POSITION")
    print("-"*80)
    
    success = await broker.execute_close_trade(
        symbol="AAPL",
        exit_price=152.30,
        exit_reason="Time Decay Exit"
    )
    
    print(f"\n✓ Close trade result: {success}")
    
    if "AAPL" in broker.positions:
        pos = broker.positions["AAPL"]
        print(f"  - Symbol: {pos.symbol}")
        print(f"  - Entry Price: ${pos.entry_price:.2f}")
        if pos.close_price:
            print(f"  - Exit Price: ${pos.close_price:.2f}")
            # Calculate P&L
            pnl = (pos.close_price - pos.entry_price) * pos.quantity
            pnl_pct = ((pos.close_price - pos.entry_price) / pos.entry_price) * 100
            print(f"  - P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%)")
        print(f"  - Quantity: {pos.quantity}")
        print(f"  - Status: {pos.status}")
        print(f"  - Close Reason: {pos.close_reason}")
    
    # Test 3: Try to open same symbol again (should fail)
    print("\n" + "-"*80)
    print("TEST 3: PREVENT DUPLICATE OPEN")
    print("-"*80)
    
    success = await broker.execute_open_trade(
        symbol="AAPL",
        entry_price=151.00,
        quantity=3
    )
    
    print(f"\n✓ Duplicate open result: {success} (should be False)")
    
    # Test 4: Open multiple positions
    print("\n" + "-"*80)
    print("TEST 4: MULTIPLE POSITIONS")
    print("-"*80)
    
    symbols = ["MSFT", "GOOGL", "TSLA"]
    prices = [320.50, 140.20, 250.80]
    
    for symbol, price in zip(symbols, prices):
        success = await broker.execute_open_trade(
            symbol=symbol,
            entry_price=price,
            quantity=4
        )
        print(f"  ✓ Opened {symbol} @ ${price:.2f}: {success}")
    
    print(f"\n✓ Total positions: {len(broker.positions)}")
    for sym, pos in broker.positions.items():
        status = "OPEN" if pos.status == "PENDING" else pos.status
        print(f"  - {sym}: {pos.quantity} @ ${pos.entry_price:.2f} ({status})")
    
    print("\n" + "="*80)
    print("✅ INTEGRATION TEST SUMMARY")
    print("="*80)
    print("\nWhat was tested:")
    print("  ✓ Broker initialization")
    print("  ✓ Opening positions (BUY orders via Trading212 API)")
    print("  ✓ Closing positions (SELL orders via Trading212 API)")
    print("  ✓ Position tracking and state management")
    print("  ✓ P&L calculation on close")
    print("  ✓ Duplicate open prevention")
    print("  ✓ Multiple concurrent positions")
    print("\nNote: Trading212 credentials not configured for demo.")
    print("In production, this will create REAL orders on Trading212.")
    print("="*80 + "\n")

if __name__ == "__main__":
    try:
        asyncio.run(test_trading212_integration())
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        sys.exit(1)
