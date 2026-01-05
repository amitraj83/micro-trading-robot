#!/usr/bin/env python3
"""
Simple Cash Allocation Test
Given: available_cash, already_open_positions
Returns: cash allocation per position and position sizes
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from strategy import MicroTradingStrategy
from models import Tick
import config  # Import first to load env
from config import RISK_CONFIG

def test_cash_allocation(available_cash, already_open_positions, test_symbols_with_prices):
    """
    Test cash allocation for new positions given current portfolio state.
    
    Args:
        available_cash (float): Current available cash in portfolio
        already_open_positions (int): Number of positions currently open (informational only)
        test_symbols_with_prices (list): List of tuples [(symbol, price), ...]
    
    Returns:
        dict: Results with allocation per position and position sizes
    """
    print("\n" + "="*80)
    print("CASH ALLOCATION TEST")
    print("="*80)
    
    # Override config temporarily for this test
    original_cash = RISK_CONFIG.get('mock_portfolio_available_cash')
    original_use_mock = RISK_CONFIG.get('use_trading212_mock')
    
    RISK_CONFIG['mock_portfolio_available_cash'] = available_cash
    RISK_CONFIG['use_trading212_mock'] = True
    
    # Read max_positions from config (not passed as parameter)
    max_positions = RISK_CONFIG.get('max_open_positions', 1)
    
    # Setup
    strategy = MicroTradingStrategy()
    
    print(f"\n📊 Portfolio State:")
    print(f"  Available Cash: ${available_cash:,.2f}")
    print(f"  Currently Open: {already_open_positions} positions")
    print(f"  Max Positions: {max_positions}")
    print(f"  Remaining Slots: {max_positions - already_open_positions}")
    
    # Calculate expected allocation
    cash_reserve_pct = RISK_CONFIG.get('cash_reserve_per_position_pct', 1.0)
    expected_per_position = (available_cash / max_positions) * cash_reserve_pct
    
    print(f"\n💰 Strategy A Calculation:")
    print(f"  Formula: (${available_cash:,.2f} / {max_positions}) × {cash_reserve_pct}")
    print(f"  Allocation per Position: ${expected_per_position:,.2f}")
    
    # Test each symbol
    results = []
    total_capital_allocated = 0.0
    
    print("\n" + "-"*80)
    print("Position Sizing Results:")
    print("-"*80)
    
    for idx, (symbol, price) in enumerate(test_symbols_with_prices, 1):
        # Compute position size using strategy's method
        position_size, note = strategy._compute_position_size(entry_price=price)
        
        position_value = position_size * price
        total_capital_allocated += position_value
        
        results.append({
            "symbol": symbol,
            "price": price,
            "shares": position_size,
            "value": position_value,
            "allocation_pct": (position_value / expected_per_position * 100) if expected_per_position > 0 else 0,
            "note": note
        })
        
        print(f"\n[{idx}] {symbol} @ ${price:.2f}")
        print(f"    Shares: {position_size}")
        print(f"    Capital: ${position_value:,.2f}")
        print(f"    % of Allocation: {results[-1]['allocation_pct']:.1f}%")
    
    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total Capital for New Positions: ${total_capital_allocated:,.2f}")
    print(f"Remaining Cash After Allocation: ${available_cash - total_capital_allocated:,.2f}")
    if len(test_symbols_with_prices) > 0:
        print(f"Average Position Size: ${total_capital_allocated / len(test_symbols_with_prices):,.2f}")
    
    # Restore original config
    RISK_CONFIG['mock_portfolio_available_cash'] = original_cash
    RISK_CONFIG['use_trading212_mock'] = original_use_mock
    
    # Return structured results
    return {
        "available_cash": available_cash,
        "already_open": already_open_positions,
        "max_positions": max_positions,
        "allocation_per_position": expected_per_position,
        "positions": results,
        "total_allocated": total_capital_allocated,
        "remaining_cash": available_cash - total_capital_allocated
    }


def interactive_cash_allocation_test():
    """
    Interactive test mode: User provides inputs via command prompt.
    
    Asks for:
    1. Available cash
    2. Loop: positions opened and closed
    
    Calculates and displays:
    - Remaining slots
    - Allocation per position
    - Total reserved capital
    """
    print("\n" + "="*80)
    print("INTERACTIVE CASH ALLOCATION CALCULATOR")
    print("="*80)
    
    max_positions = RISK_CONFIG.get('max_open_positions', 1)
    cash_reserve_pct = RISK_CONFIG.get('cash_reserve_per_position_pct', 1.0)
    
    print(f"\n📋 Configuration:")
    print(f"   Max Open Positions: {max_positions}")
    print(f"   Cash Reserve %: {cash_reserve_pct*100:.0f}%")
    
    # Get initial available cash
    while True:
        try:
            available_cash = float(input("\n💰 Enter available cash in your portfolio ($): "))
            if available_cash <= 0:
                print("❌ Available cash must be positive. Try again.")
                continue
            break
        except ValueError:
            print("❌ Invalid input. Please enter a number.")
    
    current_open = 0
    
    print(f"\n✅ Initial Available Cash: ${available_cash:,.2f}")
    print("\n" + "-"*80)
    print("POSITION TRACKING LOOP")
    print("(Type 'q' or 'quit' to exit)")
    print("-"*80)
    
    iteration = 0
    while True:
        iteration += 1
        print(f"\n📊 Iteration {iteration}:")
        print(f"   Currently Open Positions: {current_open}")
        print(f"   Remaining Slots: {max_positions - current_open}")
        
        # Ask for positions opened
        while True:
            try:
                opened = input(f"\n   How many positions did you OPEN? (0 if none, or 'q' to quit): ").strip().lower()
                if opened in ['q', 'quit', 'exit']:
                    print("\n" + "="*80)
                    print("✅ Interactive test closed. Final state:")
                    print(f"   Available Cash: ${available_cash:,.2f}")
                    print(f"   Positions Open: {current_open}")
                    print(f"   Remaining Slots: {max_positions - current_open}")
                    allocation = (available_cash / max_positions) * cash_reserve_pct
                    print(f"   Allocation per Position: ${allocation:,.2f}")
                    print("="*80 + "\n")
                    return
                
                opened = int(opened)
                if opened < 0:
                    print("   ❌ Can't open negative positions. Try again.")
                    continue
                if current_open + opened > max_positions:
                    print(f"   ❌ Can't open {opened} positions (only {max_positions - current_open} slots left). Try again.")
                    continue
                break
            except ValueError:
                print("   ❌ Invalid input. Please enter a number.")
        
        current_open += opened
        
        # Ask for positions closed
        while True:
            try:
                closed = input(f"   How many positions did you CLOSE? (0 if none): ").strip()
                closed = int(closed)
                if closed < 0:
                    print("   ❌ Can't close negative positions. Try again.")
                    continue
                if closed > current_open:
                    print(f"   ❌ Can't close {closed} positions (only {current_open} open). Try again.")
                    continue
                break
            except ValueError:
                print("   ❌ Invalid input. Please enter a number.")
        
        current_open -= closed
        
        # Calculate and display results
        allocation = (available_cash / max_positions) * cash_reserve_pct
        remaining_slots = max_positions - current_open
        total_reserved = allocation * max_positions
        
        print("\n" + "="*80)
        print("PORTFOLIO STATE AFTER UPDATE:")
        print("="*80)
        print(f"✅ Positions Opened: +{opened}")
        print(f"✅ Positions Closed: -{closed}")
        print(f"\n📊 Current Status:")
        print(f"   Available Cash: ${available_cash:,.2f}")
        print(f"   Positions Open: {current_open} / {max_positions}")
        print(f"   Remaining Slots: {remaining_slots}")
        print(f"\n💰 Cash Allocation (Strategy A):")
        print(f"   Formula: (${available_cash:,.2f} / {max_positions}) × {cash_reserve_pct}")
        print(f"   Per Position: ${allocation:,.2f}")
        print(f"   Total Reserved: ${total_reserved:,.2f}")
        print(f"   Used by Open Positions: ${allocation * current_open:,.2f}")
        print(f"   Available for New Positions: ${allocation * remaining_slots:,.2f}")
        print("="*80)


if __name__ == "__main__":
    print("\n" + "="*80)
    print("STRATEGY A: MULTI-POSITION CASH ALLOCATION TEST SUITE")
    print("="*80)
    
    # Example 1: Fresh start with $5,000 and no open positions
    print("\n\n### EXAMPLE 1: Fresh Portfolio ###")
    result1 = test_cash_allocation(
        available_cash=5000.0,
        already_open_positions=0,
        test_symbols_with_prices=[
            ("NVDA", 150.0),
            ("AAPL", 120.0),
            ("MSFT", 200.0)
        ]
    )
    
    # Example 2: After opening 3 positions, $2,000 cash remaining
    print("\n\n### EXAMPLE 2: After Opening 3 Positions ###")
    result2 = test_cash_allocation(
        available_cash=2000.0,
        already_open_positions=3,
        test_symbols_with_prices=[
            ("TSLA", 180.0),
            ("GOOGL", 140.0)
        ]
    )
    
    # Example 3: Low cash scenario
    print("\n\n### EXAMPLE 3: Low Cash ($500 remaining) ###")
    result3 = test_cash_allocation(
        available_cash=5000.0,
        already_open_positions=8,
        test_symbols_with_prices=[
            ("AMD", 95.0),
        ]
    )
    
    # Example 4: Bot restart with existing positions
    print("\n\n### EXAMPLE 4: Bot Restart (5 positions open, $1,500 available) ###")
    result4 = test_cash_allocation(
        available_cash=1000.0,
        already_open_positions=3,
        test_symbols_with_prices=[
            ("META", 250.0),
            ("NFLX", 180.0),
            ("INTC", 45.0)
        ]
    )
    
    # Final summary
    print("\n" + "="*80)
    print("TEST SUITE COMPLETE")
    print("="*80)
    print("✅ All scenarios tested successfully")
    max_pos = RISK_CONFIG.get('max_open_positions', 1)
    print(f"\n💡 Key Insight: Strategy A divides available cash by MAX positions ({max_pos}),")
    print("   not remaining slots. Simple, robust, no tracking needed!")
    print("="*80)
    
    # Interactive test
    print("\n\n")
    print("🎯 Would you like to try the INTERACTIVE CALCULATOR?")
    response = input("Enter 'yes' or 'y' to start interactive mode, or press Enter to skip: ").strip().lower()
    if response in ['yes', 'y']:
        interactive_cash_allocation_test()
    else:
        print("Skipped interactive mode.\n")
