#!/usr/bin/env python3
"""Test script to verify WebSocket data flow"""
import json
import asyncio
import websockets

async def test_websocket():
    uri = "ws://localhost:8765"
    print("Connecting to", uri)
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✓ Connected")
            
            for i in range(3):
                message = await asyncio.wait_for(websocket.recv(), timeout=70)
                data = json.loads(message)
                
                if 'symbols' in data:
                    symbols = list(data['symbols'].keys())
                    print(f"\n[{i+1}] Received snapshot with {len(symbols)} symbols: {symbols}")
                    for symbol in symbols:
                        ticker_data = data['symbols'][symbol]
                        if 'ticker' in ticker_data and 'day' in ticker_data['ticker']:
                            price = ticker_data['ticker'].get('day', {}).get('c')
                            print(f"      {symbol}: ${price}")
                else:
                    print(f"\n[{i+1}] Unexpected message format (no 'symbols' key)")
                    print(f"      Keys: {list(data.keys())}")
                
    except asyncio.TimeoutError:
        print("✗ Timeout: No data received within 70 seconds")
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()

print("Testing WebSocket data flow...\n")
asyncio.run(test_websocket())
