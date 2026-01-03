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

# Load environment variables (always override to pick up latest .env edits)
load_dotenv(override=True)


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
        
        # Replace SYMBOLS line only (anchor line start to avoid hitting MAX_SYMBOLS)
        pattern = r'^\s*SYMBOLS\s*=\s*.*$'
        replacement = f'SYMBOLS={symbols_str}'
        new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        
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
    platform_raw = os.getenv('DAY_GAINER_FETCH_PLATFORM', 'POLYGON')
    platform_list = [p.strip().upper() for p in platform_raw.split(',') if p.strip()]
    if not platform_list:
        platform_list = ['POLYGON']
    api_key = os.getenv('POLYGON_API_KEY')
    validate = os.getenv('VALIDATE_GAINERS_WITH_POLYGON', 'true').lower() == 'true'
    screener_type = os.getenv('YAHOO_SCREENER_TYPE', 'day_gainers')
    # Cap how many symbols we keep; default 20 for dashboard grid
    try:
        max_symbols = int(os.getenv('MAX_SYMBOLS', '20'))
    except ValueError:
        max_symbols = 20
    max_symbols = max(1, max_symbols)
    
    print(f"Platforms (priority): {platform_list}")
    if 'YAHOO' in platform_list:
        print(f"Screener Type: {screener_type}")
    print(f"Validate with Polygon: {validate}\n")

    # Try platforms in order until we get matches
    matches = []
    used_platform = None
    for plat in platform_list:
        used_platform = plat
        matches = find_matching_tickers(
            api_key=api_key,
            platform=plat,
            limit=max_symbols,
            validate_with_polygon=(validate and plat == 'YAHOO'),
            screener_type=screener_type
        )
        if matches:
            break

    # If still nothing and YAHOO first, attempt POLYGON as last resort
    if not matches and 'POLYGON' not in platform_list:
        used_platform = 'POLYGON'
        matches = find_matching_tickers(
            api_key=api_key,
            platform='POLYGON',
            limit=max_symbols,
            validate_with_polygon=False,
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
    if len(new_symbols) < max_symbols:
        print(f"⚠ Only {len(new_symbols)} confirmed (target {max_symbols})")
        
        # Fill remaining with existing symbols
        fallback_symbols = [s for s in current_symbols if s not in new_symbols]
        needed = min(max_symbols - len(new_symbols), len(fallback_symbols))
        
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
