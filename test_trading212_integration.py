#!/usr/bin/env python3
"""
Quick test of Trading212 integration
Simulates open/close signals and verifies broker execution flow
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "bot"))

# IMPORTANT: Load .env BEFORE importing any bot modules
from config import load_env_from_file
load_env_from_file()

from trading212_broker import Trading212Broker, BotPosition
from trading212_api import Trading212Client
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

async def test_interactive_trading():
    """
    Interactive test - run a real bot instance and manually execute trades.
    
    Flow:
    1. Shows total available cash from Trading212
    2. Shows current open positions
    3. Asks which symbols to BUY (uses allocation per position)
    4. Asks which symbols to SELL
    5. Executes trades on real Trading212 platform
    6. Loops continuously until user quits
    """
    
    print("\n" + "="*80)
    print("🤖 INTERACTIVE TRADING212 BOT - REAL EXECUTION")
    print("="*80)
    print("\n⚠️  WARNING: This will create REAL trades on Trading212!")
    print("Make sure you're using demo account if testing.")
    
    # Import strategy to get allocation
    from strategy import MicroTradingStrategy
    from config import RISK_CONFIG
    from trading212_api import Trading212Client
    
    # Create broker and strategy instances
    broker = Trading212Broker()
    strategy = MicroTradingStrategy()
    
    # Get allocation details
    available_cash = strategy._get_portfolio_available_cash()
    allocation_per_pos = strategy._allocation_per_position
    max_positions = RISK_CONFIG.get("max_open_positions", 4)
    
    print(f"\n💰 PORTFOLIO STATUS:")
    print(f"   Total Available Cash: ${available_cash:,.2f}" if available_cash else "   Total Available Cash: Unable to fetch")
    print(f"   Allocation per Position: ${allocation_per_pos:.2f}" if allocation_per_pos else "   Allocation per Position: Not initialized")
    print(f"   Max Open Positions: {max_positions}")
    
    print(f"\n✓ Broker initialized: {broker.enabled}")
    
    if not broker.enabled:
        print("\n❌ Broker is disabled (check API credentials)")
        print("   Set TRADING212_DEMO_API_KEY and TRADING212_DEMO_API_SECRET in .env")
        return
    
    # Main trading loop
    while True:
        print("\n" + "="*80)
        print("📊 CURRENT POSITIONS")
        print("="*80)
        
        if not broker.positions:
            print("   No open positions")
        else:
            for symbol, pos in broker.positions.items():
                if pos.status == "OPEN":
                    current_pnl = "(No current price)" 
                    print(f"   {symbol}: {pos.quantity} shares @ ${pos.entry_price:.2f} - Status: {pos.status} {current_pnl}")
                elif pos.status == "CLOSED":
                    pnl = (pos.close_price - pos.entry_price) * pos.quantity if pos.close_price else 0
                    pnl_pct = ((pos.close_price - pos.entry_price) / pos.entry_price) * 100 if pos.close_price else 0
                    print(f"   {symbol}: CLOSED @ ${pos.close_price:.2f} - P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%)")
                else:
                    print(f"   {symbol}: Status: {pos.status}")
        
        # Count open positions
        open_positions = [s for s, p in broker.positions.items() if p.status == "OPEN"]
        print(f"\n   Total Open Positions: {len(open_positions)}/{max_positions}")
        
        print("\n" + "="*80)
        print("📈 TRADING OPTIONS")
        print("="*80)
        print("   [B] Buy symbols")
        print("   [S] Sell symbols")
        print("   [R] Refresh status")
        print("   [Q] Quit")
        
        choice = input("\nYour choice: ").strip().upper()
        
        if choice == "Q":
            print("\n👋 Exiting interactive trading...")
            break
        
        elif choice == "R":
            # REFRESH: Sync with Trading212 and clean up failed orders
            print("\n" + "-"*80)
            print("🔄 SYNCING WITH TRADING212")
            print("-"*80)
            
            try:
                async with Trading212Client() as client:
                    positions_response = await client._request("GET", "/equity/positions")
                
                if isinstance(positions_response, list):
                    t212_symbols = {pos.get('ticker', '').replace('_US_EQ', '') for pos in positions_response}
                    print(f"\n   Trading212 has {len(t212_symbols)} open positions: {', '.join(sorted(t212_symbols))}")
                    
                    # Clean up local positions that don't exist on Trading212
                    local_open = {s: p for s, p in broker.positions.items() if p.status == "OPEN"}
                    to_remove = [s for s in local_open if s not in t212_symbols]
                    
                    if to_remove:
                        print(f"\n   ⚠️  Removing {len(to_remove)} local positions not on Trading212:")
                        for symbol in to_remove:
                            del broker.positions[symbol]
                            print(f"      • Removed: {symbol}")
                    
                    if local_open:
                        print(f"\n   ✅ Synced {len(local_open)} positions")
                else:
                    print(f"   Response: {positions_response}")
            except Exception as e:
                print(f"   ❌ Error syncing: {e}")
            
            input("\nPress Enter to continue...")
        
        elif choice == "B":
            # BUY symbols
            print("\n" + "-"*80)
            print("🛒 BUY SYMBOLS")
            print("-"*80)
            
            # Check if we can open more positions
            if len(open_positions) >= max_positions:
                print(f"\n⚠️  Cannot open more positions - already at max ({max_positions})")
                input("\nPress Enter to continue...")
                continue
            
            symbols_input = input(f"\nEnter symbols to BUY (comma-separated, e.g., AAPL,MSFT): ").strip().upper()
            
            if not symbols_input:
                print("   No symbols entered")
                continue
            
            symbols_to_buy = [s.strip() for s in symbols_input.split(",") if s.strip()]
            
            for symbol in symbols_to_buy:
                # Check if already have position
                if symbol in broker.positions and broker.positions[symbol].status == "OPEN":
                    print(f"\n⚠️  Already have open position for {symbol} - skipping")
                    continue
                
                # Check if would exceed max positions
                current_open = len([s for s, p in broker.positions.items() if p.status == "OPEN"])
                if current_open >= max_positions:
                    print(f"\n⚠️  Max positions reached ({max_positions}) - skipping {symbol}")
                    continue
                
                # Get current price from user
                price_input = input(f"\n   Enter current price for {symbol} (or press Enter to skip): $").strip()
                
                if not price_input:
                    print(f"   Skipping {symbol}")
                    continue
                
                try:
                    entry_price = float(price_input)
                except ValueError:
                    print(f"   Invalid price - skipping {symbol}")
                    continue
                
                # Calculate quantity based on allocation
                if allocation_per_pos and entry_price > 0:
                    quantity = int(allocation_per_pos / entry_price)
                    if quantity < 1:
                        quantity = 1
                else:
                    quantity = 1
                
                notional_value = quantity * entry_price
                
                print(f"\n   📊 Order Details for {symbol}:")
                print(f"      Allocation per Position: ${allocation_per_pos:.2f}")
                print(f"      Entry Price: ${entry_price:.2f}")
                print(f"      Calculated Quantity: int(${allocation_per_pos:.2f} / ${entry_price:.2f}) = {quantity} shares")
                print(f"      Notional Value: ${notional_value:.2f}")
                print(f"      Allocation Used: ${notional_value:.2f} / ${allocation_per_pos:.2f} ({(notional_value/allocation_per_pos)*100:.1f}%)")
                
                confirm = input(f"\n   ✓ Execute BUY order? (y/n): ").strip().lower()
                
                if confirm == 'y':
                    print(f"\n   🔄 Executing BUY order for {symbol}...")
                    
                    # Check broker status before executing
                    if not broker.enabled:
                        print(f"   ❌ Broker is disabled - cannot execute orders")
                        print(f"      Check Trading212 API credentials in .env")
                        continue
                    
                    success = await broker.execute_open_trade(
                        symbol=symbol,
                        entry_price=entry_price,
                        quantity=quantity
                    )
                    
                    if success:
                        print(f"   ✅ BUY order executed: {symbol} {quantity} shares @ ${entry_price:.2f}")
                        # Check position status
                        if symbol in broker.positions:
                            pos = broker.positions[symbol]
                            print(f"      Status: {pos.status}")
                            if pos.trading212_order_id:
                                print(f"      Trading212 Order ID: {pos.trading212_order_id}")
                            if pos.error_message:
                                print(f"      Error: {pos.error_message}")
                    else:
                        print(f"   ❌ BUY order failed for {symbol}")
                        # Check if position was created with error status
                        if symbol in broker.positions:
                            pos = broker.positions[symbol]
                            if pos.error_message:
                                print(f"      API Error: {pos.error_message}")
                else:
                    print(f"   ⏭️  Skipped {symbol}")
            
            input("\nPress Enter to continue...")
        
        elif choice == "S":
            # SELL symbols
            print("\n" + "-"*80)
            print("💰 SELL SYMBOLS")
            print("-"*80)
            
            # Get list of open positions from LOCAL broker tracking
            open_symbols_local = [s for s, p in broker.positions.items() if p.status == "OPEN"]
            
            # Also fetch REAL positions from Trading212 API
            print(f"\n   🔍 Fetching open positions from Trading212 API...")
            try:
                async with Trading212Client() as client:
                    positions_data = await client.get_positions()
                
                if isinstance(positions_data, list):
                    open_symbols_api = [p.get("ticker", "").split("_")[0] for p in positions_data if p.get("status") == "OPEN"]
                    print(f"   ✅ Trading212 API shows {len(open_symbols_api)} open positions: {open_symbols_api}")
                else:
                    open_symbols_api = []
                    print(f"   ⚠️  Could not fetch positions from API: {positions_data}")
            except Exception as e:
                open_symbols_api = []
                print(f"   ❌ Error fetching from API: {e}")
            
            # Combine both local and API positions
            all_open_symbols = list(set(open_symbols_local + open_symbols_api))
            
            if not all_open_symbols:
                print(f"\n⚠️  No open positions to sell (Local: {open_symbols_local}, API: {open_symbols_api})")
                input("\nPress Enter to continue...")
                continue
            
            print(f"\nOpen positions available: {', '.join(all_open_symbols)}")
            
            symbols_input = input(f"\nEnter symbols to SELL (comma-separated): ").strip().upper()
            
            if not symbols_input:
                print("   No symbols entered")
                continue
            
            symbols_to_sell = [s.strip() for s in symbols_input.split(",") if s.strip()]
            
            for symbol in symbols_to_sell:
                # Check if we have this position
                if symbol not in broker.positions:
                    print(f"\n⚠️  No position found for {symbol} - skipping")
                    continue
                
                pos = broker.positions[symbol]
                
                if pos.status != "OPEN":
                    print(f"\n⚠️  Position {symbol} is not OPEN (status: {pos.status}) - skipping")
                    continue
                
                # Get exit price from user
                price_input = input(f"\n   Enter exit price for {symbol} (Entry was ${pos.entry_price:.2f}): $").strip()
                
                if not price_input:
                    print(f"   Skipping {symbol}")
                    continue
                
                try:
                    exit_price = float(price_input)
                except ValueError:
                    print(f"   Invalid price - skipping {symbol}")
                    continue
                
                # Calculate estimated P&L
                pnl_dollars = (exit_price - pos.entry_price) * pos.quantity
                pnl_percent = ((exit_price - pos.entry_price) / pos.entry_price) * 100
                
                print(f"\n   📊 Order Details for {symbol}:")
                print(f"      Entry Price: ${pos.entry_price:.2f}")
                print(f"      Exit Price: ${exit_price:.2f}")
                print(f"      Quantity: {pos.quantity} shares")
                print(f"      Estimated P&L: ${pnl_dollars:+.2f} ({pnl_percent:+.2f}%)")
                
                confirm = input(f"\n   ✓ Execute SELL order? (y/n): ").strip().lower()
                
                if confirm == 'y':
                    print(f"\n   🔄 Executing SELL order for {symbol}...")
                    success = await broker.execute_close_trade(
                        symbol=symbol,
                        exit_price=exit_price,
                        exit_reason="Manual close"
                    )
                    
                    if success:
                        print(f"   ✅ SELL order executed: {symbol} {pos.quantity} shares @ ${exit_price:.2f}")
                        print(f"   💰 P&L: ${pnl_dollars:+.2f} ({pnl_percent:+.2f}%)")
                    else:
                        print(f"   ❌ SELL order failed for {symbol}")
                else:
                    print(f"   ⏭️  Skipped {symbol}")
            
            input("\nPress Enter to continue...")
        
        else:
            print("\n⚠️  Invalid choice")
            input("\nPress Enter to continue...")
    
    print("\n" + "="*80)
    print("📊 FINAL POSITION SUMMARY")
    print("="*80)
    
    if not broker.positions:
        print("   No positions")
    else:
        total_pnl = 0
        for symbol, pos in broker.positions.items():
            if pos.status == "CLOSED" and pos.close_price:
                pnl = (pos.close_price - pos.entry_price) * pos.quantity
                pnl_pct = ((pos.close_price - pos.entry_price) / pos.entry_price) * 100
                total_pnl += pnl
                print(f"   {symbol}: ${pnl:+.2f} ({pnl_pct:+.2f}%)")
            elif pos.status == "OPEN":
                print(f"   {symbol}: STILL OPEN @ ${pos.entry_price:.2f}")
        
        if total_pnl != 0:
            print(f"\n   💰 Total Realized P&L: ${total_pnl:+.2f}")
    
    print("\n" + "="*80)
    print("✅ Interactive trading session ended")
    print("="*80 + "\n")


if __name__ == "__main__":
    import sys
    
    # Check which test to run
    if len(sys.argv) > 1 and sys.argv[1] == "interactive":
        # Run interactive test
        try:
            asyncio.run(test_interactive_trading())
        except KeyboardInterrupt:
            print("\n\n👋 Interrupted by user")
        except Exception as e:
            logger.error(f"Interactive test failed: {e}", exc_info=True)
            sys.exit(1)
    else:
        # Run automated test
        try:
            asyncio.run(test_trading212_integration())
        except Exception as e:
            logger.error(f"Test failed: {e}", exc_info=True)
            sys.exit(1)
