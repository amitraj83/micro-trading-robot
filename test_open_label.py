#!/usr/bin/env python3
"""
Test script to trigger a TRADE_EVENT and verify Open label updates.
This directly sends a trade event via WebSocket to test the dashboard's label update logic.
"""
import asyncio
import websockets
import json
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

async def send_trade_event():
    """Send a TRADE_EVENT to the dashboard via WebSocket."""
    uri = "ws://localhost:8765"
    
    try:
        async with websockets.connect(uri) as websocket:
            logger.info(f"🔌 Connected to {uri}")
            
            # Send a trade event - simulating bot opening a position
            trade_event = {
                "type": "TRADE_EVENT",
                "action": "OPEN",
                "symbol": "QQQ",
                "trade": {
                    "entry_price": 110.75,
                    "direction": "LONG",
                    "timestamp": time.time()
                }
            }
            
            logger.info(f"📤 Sending TRADE_EVENT: {json.dumps(trade_event, indent=2)}")
            await websocket.send(json.dumps(trade_event))
            
            # Wait a moment to see dashboard response
            await asyncio.sleep(2)
            
            # Try to receive any response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                logger.info(f"📥 Received response: {response}")
            except asyncio.TimeoutError:
                logger.info("⏱️ No immediate response (expected)")
            
            logger.info("✅ Trade event sent successfully")
            logger.info("Check the dashboard UI to see if Open label now displays $110.75")
            
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return False
    
    return True

async def send_multiple_events():
    """Send multiple trade events to test various scenarios."""
    uri = "ws://localhost:8765"
    
    try:
        async with websockets.connect(uri) as websocket:
            logger.info(f"🔌 Connected to {uri}")
            
            # Test OPEN event for QQQ
            logger.info("\n=== Testing OPEN event for QQQ ===")
            event = {
                "type": "TRADE_EVENT",
                "action": "OPEN",
                "symbol": "QQQ",
                "trade": {"entry_price": 110.75, "direction": "LONG"}
            }
            logger.info(f"📤 Sending: {json.dumps(event)}")
            await websocket.send(json.dumps(event))
            await asyncio.sleep(1)
            
            # Test OPEN event for SPY
            logger.info("\n=== Testing OPEN event for SPY ===")
            event = {
                "type": "TRADE_EVENT",
                "action": "OPEN",
                "symbol": "SPY",
                "trade": {"entry_price": 184.50, "direction": "LONG"}
            }
            logger.info(f"📤 Sending: {json.dumps(event)}")
            await websocket.send(json.dumps(event))
            await asyncio.sleep(1)
            
            # Test CLOSE event
            logger.info("\n=== Testing CLOSE event for QQQ ===")
            event = {
                "type": "TRADE_EVENT",
                "action": "CLOSE",
                "symbol": "QQQ",
                "trade": {"exit_price": 111.20, "pnl": 45.00, "pnl_pct": 0.41}
            }
            logger.info(f"📤 Sending: {json.dumps(event)}")
            await websocket.send(json.dumps(event))
            await asyncio.sleep(1)
            
            logger.info("\n✅ All test events sent")
            logger.info("Check dashboard for:")
            logger.info("  - QQQ Open: $110.75 (should show)")
            logger.info("  - SPY Open: $184.50 (should show)")
            logger.info("  - QQQ Close: $111.20 (should show)")
            
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return False
    
    return True

if __name__ == "__main__":
    logger.info("🧪 Starting trade event test...\n")
    
    # Give system time to start
    time.sleep(1)
    
    # Run test
    success = asyncio.run(send_multiple_events())
    
    if success:
        logger.info("\n✅ Test completed - check dashboard for label updates")
        logger.info("If Open labels don't show, check trading_dashboard.log for errors")
    else:
        logger.error("❌ Test failed")
