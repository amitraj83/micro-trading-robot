"""
Fake Polygon WebSocket Server for testing

Generates realistic aggregate bar (A) events that TRIGGER the bot's strategy
"""

import asyncio
import json
import logging
import random
import time
from datetime import datetime
import pytz
from typing import Dict, Set
from collections import deque
from statistics import mean

import websockets

logger = logging.getLogger(__name__)

# Connected clients
connected_clients: Set = set()

# Price state for each symbol
SYMBOL_STATES: Dict[str, dict] = {}

# Configuration
TIMEZONE = pytz.timezone("US/Eastern")
FAKE_TICK_INTERVAL = 1.0  # Generate a new bar every second


async def register_client(websocket):
    """Register a new client connection"""
    connected_clients.add(websocket)
    logger.info(f"Client connected to fake Polygon WebSocket. Total: {len(connected_clients)}")
    
    # Send auth response
    auth_msg = {
        "status": "success",
        "message": "Successfully authenticated"
    }
    await websocket.send(json.dumps(auth_msg))


async def unregister_client(websocket):
    """Unregister a client"""
    connected_clients.discard(websocket)
    logger.info(f"Client disconnected. Total: {len(connected_clients)}")


def generate_fake_bar(symbol: str) -> dict:
    """
    Generate fake Polygon bars that RELIABLY trigger bot's entry criteria:
    
    Bot Requirements:
    1. ≥2 compression bars (range < 1.1 * mean + volume < avg_volume)
    2. Then expansion bar (range ≥1.8 * avg_range + volume ≥1.5 * avg_volume)
    3. VWAP bias: ≥2 of last 3 closes > VWAP (BULLISH) or < VWAP (BEARISH)
    4. Close in top/bottom 20% of candle
    """
    
    # Initialize state if first time seeing symbol
    if symbol not in SYMBOL_STATES:
        base_price = random.uniform(20.0, 200.0)
        SYMBOL_STATES[symbol] = {
            "base_price": base_price,
            "last_close": base_price,
            "last_vwap": base_price,
            "accumulated_volume": random.randint(1000000, 50000000),
            "phase": "TREND",  # TREND -> COMPRESSION -> EXPANSION -> TREND
            "phase_bars": 0,
            "ranges": deque(maxlen=5),  # Track last 5 bar ranges for expansion calc
            "volumes": deque(maxlen=5),  # Track last 5 bar volumes
            "direction": random.choice([1, -1]),  # 1 for UP, -1 for DOWN
        }
    
    state = SYMBOL_STATES[symbol]
    
    # Phase machine that generates trade-triggering patterns
    if state["phase"] == "TREND":
        # 2-3 normal bars to build history
        direction = state["direction"]
        if random.random() < 0.4:  # Occasionally flip direction
            direction = -direction
            state["direction"] = direction
        
        price_change_pct = direction * random.uniform(0.01, 0.025)
        bar_volume = random.randint(200, 400)
        state["phase_bars"] += 1
        
        if state["phase_bars"] >= random.randint(2, 3):
            state["phase"] = "COMPRESSION"
            state["phase_bars"] = 0
    
    elif state["phase"] == "COMPRESSION":
        # 2 tight bars: small range + low volume to trigger compression detection
        # This satisfies: range < 1.1 * mean(range) AND volume < avg_volume
        
        # Calculate current average range and volume
        avg_range = mean(state["ranges"]) if state["ranges"] else 0.5
        avg_volume = mean(state["volumes"]) if state["volumes"] else 250
        
        # Make VERY tight bars - 30% of average range
        tight_range = avg_range * 0.3 if avg_range > 0 else 0.2
        
        # Slightly drift price, but within tight range
        drift_pct = random.uniform(-0.002, 0.002)
        price_change_pct = drift_pct
        
        # Low volume: 40% of average
        bar_volume = max(50, int(avg_volume * 0.4))
        
        open_price = state["last_close"]
        close_price = round(open_price * (1 + price_change_pct), 2)
        high_price = max(open_price, close_price) + random.uniform(0, tight_range * 0.2)
        low_price = min(open_price, close_price) - random.uniform(0, tight_range * 0.2)
        
        bar_range = high_price - low_price
        state["ranges"].append(bar_range)
        state["volumes"].append(bar_volume)
        
        state["phase_bars"] += 1
        
        if state["phase_bars"] >= 2:
            # Move to expansion phase after 2 compression bars
            state["phase"] = "EXPANSION"
            state["phase_bars"] = 0
    
    elif state["phase"] == "EXPANSION":
        # Big move + volume spike to trigger expansion
        # range ≥1.8 * avg_range AND volume ≥1.5 * avg_volume
        
        avg_range = mean(state["ranges"]) if state["ranges"] else 0.5
        avg_volume = mean(state["volumes"]) if state["volumes"] else 250
        
        # BIG MOVE: 2.5x average range
        expansion_range = avg_range * 2.5 if avg_range > 0 else 2.0
        
        direction = state["direction"]
        # Force big directional move
        price_change_pct = direction * random.uniform(0.03, 0.06)
        
        # High volume spike: 2x average
        bar_volume = max(400, int(avg_volume * 2.0))
        
        open_price = state["last_close"]
        close_price = round(open_price * (1 + price_change_pct), 2)
        
        # Large range to satisfy expansion requirement
        high_price = max(open_price, close_price) + random.uniform(expansion_range * 0.3, expansion_range * 0.7)
        low_price = min(open_price, close_price) - random.uniform(expansion_range * 0.3, expansion_range * 0.7)
        
        bar_range = high_price - low_price
        state["ranges"].append(bar_range)
        state["volumes"].append(bar_volume)
        
        state["phase_bars"] += 1
        
        if state["phase_bars"] >= 1:
            # After 1 expansion bar, reset to trend
            state["phase"] = "TREND"
            state["phase_bars"] = 0
    
    else:
        # Fallback for any undefined state
        open_price = state["last_close"]
        close_price = round(open_price * (1 + random.uniform(-0.01, 0.01)), 2)
        high_price = round(max(open_price, close_price) + random.uniform(0, 0.2), 2)
        low_price = round(min(open_price, close_price) - random.uniform(0, 0.2), 2)
        bar_volume = 200
        bar_range = high_price - low_price
        state["ranges"].append(bar_range)
        state["volumes"].append(bar_volume)
    
    # Ensure high/low are set
    if 'high_price' not in locals():
        open_price = state["last_close"]
        close_price = round(open_price * (1 + random.uniform(-0.01, 0.01)), 2)
        high_price = round(max(open_price, close_price) + 0.1, 2)
        low_price = round(min(open_price, close_price) - 0.1, 2)
        bar_volume = 200
    
    high_price = round(max(high_price, open_price, close_price) + 0.01, 2)
    low_price = round(min(low_price, open_price, close_price) - 0.01, 2)
    
    accumulated_volume = state["accumulated_volume"] + bar_volume
    
    # VWAP - tick volume weighted average
    vwap = round((open_price * 0.25 + high_price * 0.25 + low_price * 0.25 + close_price * 0.25), 4)
    
    # Session VWAP - drifts with price to maintain BULLISH/BEARISH bias
    # During UP phases, keep it below close. During DOWN phases, keep it above close.
    if state["direction"] == 1:  # UP trend
        # Bias: close should be above VWAP for BULLISH
        session_vwap = round(close_price * 0.92 + state["last_vwap"] * 0.08, 4)
    else:  # DOWN trend
        # Bias: close should be below VWAP for BEARISH
        session_vwap = round(close_price * 1.08 + state["last_vwap"] * 0.08, 4)
    
    avg_trade_size = random.randint(40, 90)
    
    # Timestamps
    current_time = int(time.time() * 1000)
    start_ms = current_time - 1000
    end_ms = current_time
    
    # Update state
    state["last_close"] = close_price
    state["last_vwap"] = session_vwap
    state["accumulated_volume"] = accumulated_volume
    
    # Build bar
    bar = {
        "ev": "A",
        "sym": symbol,
        "v": bar_volume,
        "av": accumulated_volume,
        "op": round(open_price, 2),
        "vw": vwap,
        "o": round(open_price, 2),
        "c": round(close_price, 2),
        "h": high_price,
        "l": low_price,
        "a": round(session_vwap, 4),  # Session VWAP for bias
        "z": avg_trade_size,
        "s": start_ms,
        "e": end_ms,
    }
    
    return bar


async def handle_client(websocket):
    """Handle incoming WebSocket client connections"""
    await register_client(websocket)
    subscribed_symbols: Set[str] = set()
    
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                action = data.get("action")
                
                if action == "subscribe":
                    # Extract symbol from params like "A.AAPL"
                    params = data.get("params", "")
                    if params.startswith("A."):
                        symbol = params[2:].upper()
                        subscribed_symbols.add(symbol)
                        logger.info(f"Client subscribed to {symbol}")
                
                elif action == "unsubscribe":
                    params = data.get("params", "")
                    if params.startswith("A."):
                        symbol = params[2:].upper()
                        subscribed_symbols.discard(symbol)
                        logger.info(f"Client unsubscribed from {symbol}")
            
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON: {message}")
    
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        await unregister_client(websocket)


async def broadcast_fake_bars():
    """
    Continuously generate and broadcast fake aggregate bars to all connected clients
    """
    logger.info("Fake bar broadcaster started")
    
    while True:
        try:
            await asyncio.sleep(FAKE_TICK_INTERVAL)
            
            if not connected_clients:
                continue
            
            # Generate bars for a set of common symbols
            test_symbols = ["AAPL", "SPCE", "MSFT", "TSLA", "GOOGL", "INBS", "ANGH", "ESHA", "NCL", "SIDU"]
            
            for symbol in test_symbols:
                bar = generate_fake_bar(symbol)
                
                # Send to all connected clients
                message = json.dumps(bar)
                disconnected = set()
                
                for client in connected_clients:
                    try:
                        await client.send(message)
                    except websockets.exceptions.ConnectionClosed:
                        disconnected.add(client)
                    except Exception as e:
                        logger.warning(f"Error sending to client: {e}")
                        disconnected.add(client)
                
                # Clean up disconnected clients
                for client in disconnected:
                    connected_clients.discard(client)
        
        except Exception as e:
            logger.error(f"Error in broadcast_fake_bars: {e}")


async def main(host: str = "localhost", port: int = 8001):
    """Start fake Polygon WebSocket server"""
    logger.info(f"Starting fake Polygon WebSocket server on {host}:{port}")
    
    # Start the bar broadcaster task
    asyncio.create_task(broadcast_fake_bars())
    
    # Start WebSocket server
    async with websockets.serve(handle_client, host, port):
        logger.info(f"Fake Polygon WebSocket server listening on ws://{host}:{port}")
        await asyncio.Event().wait()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server shutting down...")
