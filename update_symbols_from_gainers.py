#!/usr/bin/env python3
"""
Update SYMBOLS in .env file with top gainers from find_matching_tickers.
This script is called by restart.sh to dynamically update trading symbols.

Process:
1. Check if AUTO_UPDATE_SYMBOLS_FROM_GAINERS is enabled
2. Fetch confirmed gainers from find_matching_tickers (with Polygon validation if YAHOO)
3. Update .env SYMBOLS with confirmed gainers
4. Keep existing SYMBOLS if fewer than 4 confirmed
"""

import os
import re
import sys
from typing import List
from dotenv import load_dotenv
from find_matching_tickers import find_matching_tickers

# Load environment variables
load_dotenv()


def update_env_symbols(new_symbols: List[str], env_file: str = '.env') -> bool:
    """
    Update SYMBOLS in .env file with new comma-separated list.
    
    Args:
        new_symbols: List of ticker symbols to set
        env_file: Path to .env file (default: '.env')
    
    Returns:
        True if update successful, False otherwise
    """
    if not new_symbols:
        print("⚠ No symbols to update (empty list)")
        return False
    
    symbols_str = ','.join(new_symbols)
    
    try:
        # Read current .env
        with open(env_file, 'r') as f:
            content = f.read()
        
        # Replace SYMBOLS line (handles different spacing)
        pattern = r'SYMBOLS\s*=\s*[^\n]*'
        replacement = f'SYMBOLS={symbols_str}'
        new_content = re.sub(pattern, replacement, content)
        
        # Write back
        with open(env_file, 'w') as f:
            f.write(new_content)
        
        print(f"✓ Updated .env: SYMBOLS={symbols_str}")
        return True
        
    except Exception as e:
        print(f"✗ Error updating .env: {e}")
        return False


def get_current_symbols() -> List[str]:
    """Get current SYMBOLS from .env"""
    symbols = os.getenv('SYMBOLS', '').strip()
    if symbols:
        return [s.strip() for s in symbols.split(',')]
    return []


def main():
    """Main entry point."""
    print("="*80)
    print("AUTO-UPDATE SYMBOLS FROM GAINERS")
    print("="*80 + "\n")
    
    # Check if auto-update is enabled
    auto_update = os.getenv('AUTO_UPDATE_SYMBOLS_FROM_GAINERS', 'false').lower() == 'true'
    
    if not auto_update:
        print("ℹ AUTO_UPDATE_SYMBOLS_FROM_GAINERS is disabled")
        print("Using existing SYMBOLS from .env\n")
        return 0
    
    # Get current symbols for fallback
    current_symbols = get_current_symbols()
    print(f"Current SYMBOLS: {','.join(current_symbols)}\n")
    
    # Get configuration
    platform = os.getenv('DAY_GAINER_FETCH_PLATFORM', 'POLYGON').upper()
    api_key = os.getenv('POLYGON_API_KEY')
    validate = os.getenv('VALIDATE_GAINERS_WITH_POLYGON', 'true').lower() == 'true'
    screener_type = os.getenv('YAHOO_SCREENER_TYPE', 'day_gainers')
    
    print(f"Platform: {platform}")
    if platform == 'YAHOO':
        print(f"Screener Type: {screener_type}")
    print(f"Validate with Polygon: {validate}\n")
    
    # Fetch confirmed gainers (limit 20 for scrollable dashboard)
    # Only validate if YAHOO and VALIDATE_GAINERS_WITH_POLYGON is true
    matches = find_matching_tickers(
        api_key=api_key,
        platform=platform,
        limit=20,
        validate_with_polygon=(validate and platform == 'YAHOO'),
        screener_type=screener_type
    )
    
    if not matches:
        print(f"\n{'='*80}")
        print(f"⚠ No confirmed gainers found")
        print(f"{'='*80}\n")
        print(f"Keeping existing SYMBOLS: {','.join(current_symbols)}\n")
        return 0
    
    # Extract ticker symbols
    new_symbols = [match['ticker'] for match in matches]
    
    print(f"\n{'='*80}")
    print(f"Found {len(new_symbols)} confirmed gainers")
    print(f"{'='*80}\n")
    
    # Show details
    for idx, match in enumerate(matches, 1):
        print(f"{idx}. {match['ticker']:6} - {match['instrumentName']}")
        print(f"   Change: {match['todaysChangePerc']:+.2f}% | Price: ${match['currentPrice']:.2f}\n")
    
    # Handle fallback if fewer than 20
    if len(new_symbols) < 20:
        print(f"⚠ Only {len(new_symbols)} confirmed (target 20)")
        
        # Fill remaining with existing symbols
        fallback_symbols = [s for s in current_symbols if s not in new_symbols]
        needed = min(20 - len(new_symbols), len(fallback_symbols))
        
        for i in range(needed):
            if fallback_symbols:
                new_symbols.append(fallback_symbols.pop(0))
        
        print(f"Filled with fallback: {','.join(new_symbols)}\n")
    
    # Update .env file
    if update_env_symbols(new_symbols):
        print(f"\n✓ Successfully updated SYMBOLS in .env")
        return 0
    else:
        print(f"\n✗ Failed to update .env, keeping existing SYMBOLS")
        return 1


if __name__ == "__main__":
    sys.exit(main())
