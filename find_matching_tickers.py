#!/usr/bin/env python3
"""
Find stock tickers from gainers API that match shortNames in instruments_response.json.
Returns the first 5 matches.
Supports multiple platforms: POLYGON and YAHOO.
"""

import requests
import json
import os
from typing import List, Dict, Any
from dotenv import load_dotenv

# Load environment variables (override existing to honor latest .env)
load_dotenv(override=True)


def load_instruments(filepath: str = "instruments_response.json") -> Dict[str, str]:
    """Load instruments and create a mapping of shortName to full instrument data."""
    try:
        with open(filepath, 'r') as f:
            instruments = json.load(f)
        return {inst['shortName']: inst for inst in instruments}
    except FileNotFoundError:
        print(f"Error: {filepath} not found")
        return {}
    except json.JSONDecodeError:
        print(f"Error: Failed to parse {filepath}")
        return {}


def fetch_gainers_polygon(api_key: str) -> List[Dict[str, Any]]:
    """Fetch stock gainers from Polygon API."""
    url = f"https://api.massive.com/v2/snapshot/locale/us/markets/stocks/gainers?apiKey={api_key}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get('tickers', [])
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Polygon gainers API: {e}")
        return []


def fetch_gainers_yahoo(screener_type: str = None) -> List[Dict[str, Any]]:
    """Fetch stocks from Yahoo Finance screener based on selected type.
    
    Args:
        screener_type: Type of screener to use:
            - day_gainers: Top % gainers today (default)
            - most_active: Highest trading volume
            - most_trending: Most momentum/social trending
            - day_losers: Top % losers (contrarian trades)
    """
    try:
        import urllib.request
        import json as json_module
        
        # Get screener type from parameter or environment variable
        if screener_type is None:
            screener_type = os.getenv('YAHOO_SCREENER_TYPE', 'day_gainers').lower()
        else:
            screener_type = screener_type.lower()
        
        print(f"Fetching stocks from Yahoo Finance screener: {screener_type}...")
        
        gainers = []
        
        try:
            # Map screener type to Yahoo Finance API parameter
            screener_map = {
                'day_gainers': 'day_gainers',
                'most_active': 'most_active',
                'most_trending': 'most_watched',  # most_trending -> most_watched
                'day_losers': 'day_losers'
            }
            
            screener_param = screener_map.get(screener_type, 'day_gainers')
            
            # Updated Yahoo Finance screener API endpoint
            url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/screenerResearch?scrIds={screener_param}&count=100"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
            
            req = urllib.request.Request(url, headers=headers)
            
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json_module.loads(response.read().decode())
                
                # Try to extract from various possible response formats
                quotes = []
                
                # Format 1: Direct quotes in result
                if 'finance' in data and 'result' in data['finance']:
                    results = data['finance']['result']
                    if results and len(results) > 0:
                        if 'quotes' in results[0]:
                            quotes = results[0]['quotes']
                
                # Format 2: Quotes at top level
                if not quotes and 'quotes' in data:
                    quotes = data['quotes']
                
                # Process quotes
                for quote in quotes[:100]:  # Limit to 100
                    ticker = quote.get('symbol', '')
                    regular_price = quote.get('regularMarketPrice', {})
                    if isinstance(regular_price, dict):
                        regular_price = regular_price.get('raw', 0)
                    
                    prev_close = quote.get('regularMarketPreviousClose', {})
                    if isinstance(prev_close, dict):
                        prev_close = prev_close.get('raw', 0)
                    
                    if ticker and regular_price and prev_close and prev_close > 0:
                        change = regular_price - prev_close
                        change_percent = (change / prev_close) * 100
                        
                        gainer = {
                            'ticker': ticker,
                            'todaysChangePerc': change_percent,
                            'todaysChange': change,
                            'currentPrice': regular_price,
                            'dayVolume': quote.get('regularMarketVolume', {}).get('raw', 0) if isinstance(quote.get('regularMarketVolume', {}), dict) else 0,
                        }
                        gainers.append(gainer)
                
                if gainers:
                    print(f"✓ Retrieved {len(gainers)} gainers from Yahoo Finance screener")
                    # Sort by percentage change (highest first)
                    gainers.sort(key=lambda x: x['todaysChangePerc'], reverse=True)
                    return gainers
                else:
                    print(f"⚠ No quotes found in response (API may have changed format)")
                    return []
            
        except urllib.error.HTTPError as e:
            print(f"✗ HTTP Error {e.code}: {e.reason}")
            print(f"  Endpoint: {screener_param}")
            return []
        except Exception as e:
            print(f"✗ Error fetching from screener API: {e}")
            return []
            
    except Exception as e:
        print(f"✗ Error fetching Yahoo Finance gainers: {e}")
        return []


def validate_ticker_with_polygon(ticker: str, api_key: str) -> bool:
    """
    Validate if ticker exists in Polygon database.
    Makes GET request to /v3/reference/tickers/{ticker}
    Returns True if HTTP 200, False otherwise.
    """
    url = f"https://api.massive.com/v3/reference/tickers/{ticker}"
    try:
        response = requests.get(
            url,
            params={'apiKey': api_key},
            timeout=5
        )
        return response.status_code == 200
    except Exception as e:
        return False


def fetch_gainers(api_key: str = None, platform: str = None, screener_type: str = None) -> List[Dict[str, Any]]:
    """
    Fetch stocks based on configured platform and screener type.
    
    Args:
        api_key: API key for Polygon (required if platform is POLYGON)
        platform: Platform to use (POLYGON or YAHOO). Defaults to env var DAY_GAINER_FETCH_PLATFORM
        screener_type: Yahoo screener type (day_gainers, most_active, most_trending, day_losers).
                       Defaults to env var YAHOO_SCREENER_TYPE or 'day_gainers'
    
    Returns:
        List of tickers in standardized format
    """
    if platform is None:
        platform = os.getenv('DAY_GAINER_FETCH_PLATFORM', 'POLYGON').upper()
    
    print(f"Fetching stocks from {platform} platform...")
    
    if platform == 'POLYGON':
        if api_key is None:
            api_key = os.getenv('POLYGON_API_KEY')
        if not api_key:
            print("Error: POLYGON_API_KEY not set in environment")
            return []
        return fetch_gainers_polygon(api_key)
    elif platform == 'YAHOO':
        return fetch_gainers_yahoo(screener_type=screener_type)
    else:
        print(f"Error: Unknown platform '{platform}'. Use POLYGON or YAHOO")
        return []


def find_matching_tickers(api_key: str = None, platform: str = None, limit: int = 5, validate_with_polygon: bool = False, screener_type: str = None) -> List[Dict[str, Any]]:
    """
    Find stock tickers from gainers that match shortNames in instruments.
    
    Processing order (highest gain first):
    1. Filter: Check if ticker exists in instruments_response.json
    2. Filter: Validate with Polygon API /v3/reference/tickers/{ticker} if YAHOO
    3. Add confirmed tickers to list
    4. Stop when 4 confirmed or all gainers processed
    
    Args:
        api_key: API key for Polygon (optional, uses env var if not provided)
        platform: Platform to use (POLYGON or YAHOO, optional, uses env var if not provided)
        limit: Maximum number of matches to return (default based on platform)
        validate_with_polygon: Validate tickers with Polygon API (YAHOO only)
    
    Returns:
        List of matching ticker data sorted by todaysChangePerc (highest first)
    """
    if platform is None:
        platform = os.getenv('DAY_GAINER_FETCH_PLATFORM', 'POLYGON').upper()
    
    # Default limit based on platform
    if limit is None:
        limit = 4 if platform == 'YAHOO' else 5
    
    print("Loading instruments...")
    instruments_map = load_instruments()
    
    if not instruments_map:
        print("No instruments loaded.")
        return []
    
    print(f"Loaded {len(instruments_map)} unique shortNames\n")
    
    print("Fetching gainers from API...")
    gainers = fetch_gainers(api_key=api_key, platform=platform, screener_type=screener_type)
    
    if not gainers:
        print("No gainers retrieved from API.")
        return []
    
    print(f"Fetched {len(gainers)} gainers\n")
    print("Processing gainers (highest first)...\n")
    
    if api_key is None:
        api_key = os.getenv('POLYGON_API_KEY')
    
    matches = []
    
    # Process gainers top-to-bottom (already sorted by percentage gain)
    for ticker_data in gainers:
        ticker = ticker_data.get('ticker')
        change_pct = ticker_data.get('todaysChangePerc', 0)
        
        # Filter 1: Check if in instruments
        if ticker not in instruments_map:
            print(f"✗ {ticker:6} ({change_pct:+7.2f}%) - NOT in instruments")
            continue
        
        # Filter 2: Validate with Polygon (YAHOO only)
        if platform == 'YAHOO' and validate_with_polygon:
            if not validate_ticker_with_polygon(ticker, api_key):
                print(f"✗ {ticker:6} ({change_pct:+7.2f}%) - Polygon validation failed")
                continue
        
        # Confirmed! Add to matches
        instrument = instruments_map[ticker]
        match = {
            'ticker': ticker,
            'shortName': ticker,
            'instrumentName': instrument.get('name', 'N/A'),
            'todaysChangePerc': change_pct,
            'todaysChange': ticker_data.get('todaysChange', 0),
            'currentPrice': ticker_data.get('currentPrice', 0),
            'dayOpen': ticker_data.get('dayOpen', 0),
            'dayHigh': ticker_data.get('dayHigh', 0),
            'dayLow': ticker_data.get('dayLow', 0),
            'dayVolume': ticker_data.get('dayVolume', 0),
        }
        matches.append(match)
        print(f"✓ {ticker:6} ({change_pct:+7.2f}%) - CONFIRMED")
        
        # Check if we have enough
        if len(matches) >= limit:
            print(f"\n✓ Found {limit} confirmed gainers. Stopping.\n")
            break
    
    if not matches:
        print("⚠ No confirmed gainers found.")
    else:
        print(f"\n{'='*60}")
        print(f"Total confirmed: {len(matches)}")
        print(f"{'='*60}\n")
    
    return matches


def list_all_gainers(api_key: str = None, platform: str = None, limit: int = 10) -> List[Dict[str, Any]]:
    """
    List all top gainers from the platform (not filtered by instruments).
    Useful for testing and discovering gainers.
    
    Args:
        api_key: API key for Polygon (optional, uses env var if not provided)
        platform: Platform to use (POLYGON or YAHOO, optional, uses env var if not provided)
        limit: Maximum number of gainers to return (default 10)
    
    Returns:
        List of top gainer tickers sorted by todaysChangePerc (highest first)
    """
    if platform is None:
        platform = os.getenv('DAY_GAINER_FETCH_PLATFORM', 'POLYGON').upper()
    
    print(f"Fetching top {limit} gainers from {platform} platform...")
    gainers = fetch_gainers(api_key=api_key, platform=platform)
    
    if not gainers:
        print("No gainers retrieved.")
        return []
    
    # Sort by percentage change (highest first)
    gainers.sort(key=lambda x: x.get('todaysChangePerc', 0), reverse=True)
    
    # Limit to requested number
    top_gainers = gainers[:limit]
    
    print(f"\nTop {limit} Gainers:\n")
    for idx, gainer in enumerate(top_gainers, 1):
        ticker = gainer.get('ticker', 'N/A')
        change = gainer.get('todaysChangePerc', 0)
        price = gainer.get('currentPrice', 0)
        volume = gainer.get('dayVolume', 0)
        print(f"{idx:2}. {ticker:6} | Change: {change:+7.2f}% | Price: ${price:8.2f} | Volume: {volume:>12,}")
    
    return top_gainers


def main():
    """Main entry point."""
    # Get platform from env or use default
    platform = os.getenv('DAY_GAINER_FETCH_PLATFORM', 'POLYGON')
    api_key = os.getenv('POLYGON_API_KEY')
    
    print(f"Using platform: {platform}\n")
    
    # First, show top 10 gainers for testing
    print("="*80)
    print("TOP 10 GAINERS (TEST)")
    print("="*80)
    top_gainers = list_all_gainers(api_key=api_key, platform=platform, limit=10)
    
    if top_gainers:
        print(f"\nTop 10 Gainers Summary (JSON):")
        print(json.dumps(top_gainers, indent=2))
    
    print("\n" + "="*80)
    print("MATCHING TICKERS (filtered by instruments)")
    print("="*80 + "\n")
    
    # Then, find matches with instruments
    matches = find_matching_tickers(api_key=api_key, platform=platform)
    
    if matches:
        print("\nMatches Summary (JSON):")
        print(json.dumps(matches, indent=2))


if __name__ == "__main__":
    main()
