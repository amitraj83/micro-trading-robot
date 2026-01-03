#!/usr/bin/env python3
"""
Test script for pause/resume functionality.
This script connects to the WebSocket server and tests pause/resume commands.
"""

import asyncio
import json
import websockets
import time

async def test_pause_resume():
    """Test pause and resume functionality"""
    uri = "ws://localhost:8765"
    
    print("🔗 Connecting to WebSocket server...")
    async with websockets.connect(uri) as ws:
        print("✅ Connected!")
        
        # Receive a few ticks normally
        print("\n📊 Receiving 5 ticks (RUNNING)...")
        for i in range(5):
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            if "symbols" in data:
                symbols = list(data["symbols"].keys())
                print(f"  Tick {i+1}: {symbols}")
        
        # Send pause command
        print("\n⏸  Sending PAUSE command...")
        await ws.send(json.dumps({"command": "pause"}))
        ack = await ws.recv()
        print(f"  Server: {json.loads(ack)}")
        
        # Try to receive ticks while paused (should timeout)
        print("\n⏸  Waiting 5 seconds for ticks while PAUSED...")
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"  ❌ ERROR: Received tick while paused: {msg}")
        except asyncio.TimeoutError:
            print("  ✅ No ticks received (correct - stream is paused)")
        
        # Send resume command
        print("\n▶  Sending RESUME command...")
        await ws.send(json.dumps({"command": "resume"}))
        ack = await ws.recv()
        print(f"  Server: {json.loads(ack)}")
        
        # Receive ticks again
        print("\n📊 Receiving 5 ticks after RESUME...")
        for i in range(5):
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            if "symbols" in data:
                symbols = list(data["symbols"].keys())
                print(f"  Tick {i+1}: {symbols}")
        
        print("\n✅ All tests passed!")

if __name__ == "__main__":
    try:
        asyncio.run(test_pause_resume())
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
