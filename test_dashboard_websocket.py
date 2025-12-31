#!/usr/bin/env python3
"""Test WebSocket connection and data flow for dashboard"""

import asyncio
import json
import websockets
from bot.config import WEBSOCKET_CONFIG

async def test_websocket():
    """Connect to WebSocket and print received data"""
    uri = WEBSOCKET_CONFIG["uri"]
    print(f"[TEST] Connecting to {uri}...")
    
    try:
        async with websockets.connect(uri) as websocket:
            print(f"[TEST] Connected successfully!")
            
            message_count = 0
            async for message in websocket:
                message_count += 1
                try:
                    data = json.loads(message)
                    print(f"\n[TEST] Message #{message_count}: {json.dumps(data, indent=2)[:200]}...")
                    
                    if "symbols" in data:
                        symbols = list(data["symbols"].keys())
                        print(f"[TEST] Symbols received: {symbols}")
                        print(f"[TEST] Timestamp: {data.get('timestamp', 'N/A')}")
                    
                    if message_count >= 3:
                        print(f"\n[TEST] Received {message_count} messages. Stopping.")
                        break
                
                except json.JSONDecodeError as e:
                    print(f"[TEST] JSON error: {e}")
                    print(f"[TEST] Raw message: {message[:100]}")
    
    except ConnectionRefusedError:
        print(f"[TEST] Connection refused - server not running at {uri}")
    except Exception as e:
        print(f"[TEST] Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_websocket())
