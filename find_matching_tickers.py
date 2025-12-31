#!/usr/bin/env python3
"""
Find stock tickers from gainers API that match shortNames in instruments_response.json.
Returns the first 5 matches.
"""

import requests
import json
from typing import List, Dict, Any


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


def fetch_gainers(api_key: str) -> List[Dict[str, Any]]:
    """Fetch stock gainers from the API."""
    url = f"https://api.massive.com/v2/snapshot/locale/us/markets/stocks/gainers?apiKey={api_key}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get('tickers', [])
    except requests.exceptions.RequestException as e:
        print(f"Error fetching gainers API: {e}")
        return []


def find_matching_tickers(api_key: str = "TEwsmbCFGd8dDANW3EY3IjmIohcLMrqj", limit: int = 5) -> List[Dict[str, Any]]:
    """
    Find stock tickers from gainers that match shortNames in instruments.
    Returns the first N matches (default 5).
    """
    print("Loading instruments...")
    instruments_map = load_instruments()
    
    if not instruments_map:
        print("No instruments loaded.")
        return []
    
    print(f"Loaded {len(instruments_map)} unique shortNames\n")
    
    print("Fetching gainers from API...")
    gainers = fetch_gainers(api_key)
    
    if not gainers:
        print("No gainers retrieved from API.")
        return []
    
    print(f"Fetched {len(gainers)} gainers\n")
    print("Searching for matches...\n")
    
    matches = []
    
    for ticker_data in gainers:
        ticker = ticker_data.get('ticker')
        
        if ticker in instruments_map:
            instrument = instruments_map[ticker]
            match = {
                'ticker': ticker,
                'shortName': ticker,
                'instrumentName': instrument.get('name', 'N/A'),
                'todaysChangePerc': ticker_data.get('todaysChangePerc', 0),
                'todaysChange': ticker_data.get('todaysChange', 0),
                'currentPrice': ticker_data.get('day', {}).get('c', 0),
                'dayOpen': ticker_data.get('day', {}).get('o', 0),
                'dayHigh': ticker_data.get('day', {}).get('h', 0),
                'dayLow': ticker_data.get('day', {}).get('l', 0),
                'dayVolume': ticker_data.get('day', {}).get('v', 0),
            }
            matches.append(match)
            print(f"✓ Match #{len(matches)}: {ticker}")
            print(f"  Name: {match['instrumentName']}")
            print(f"  Today's Change: {match['todaysChangePerc']:+.2f}%")
            print(f"  Current Price: ${match['currentPrice']:.2f}")
            print(f"  Day High/Low: ${match['dayHigh']:.2f} / ${match['dayLow']:.2f}")
            print(f"  Volume: {match['dayVolume']:,}\n")
            
            if len(matches) >= limit:
                break
    
    if not matches:
        print("No matches found.")
    else:
        print(f"\n{'='*60}")
        print(f"Found {len(matches)} matching ticker(s)")
        print(f"{'='*60}")
    
    return matches


def main():
    """Main entry point."""
    matches = find_matching_tickers(limit=5)
    
    if matches:
        print("\nMatches Summary (JSON):")
        print(json.dumps(matches, indent=2))


if __name__ == "__main__":
    main()
