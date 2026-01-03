"""
WebSocket Server - Bot Integration

Bridges the trading bot with the UI dashboard.
- Ingests bot trade events (ENTER/EXIT)
- Streams them to connected UI clients
- Handles multi-symbol coordination
"""

import asyncio
import json
import logging
from datetime import datetime
import pytz
from typing import Set, Dict
import websockets

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state
connected_clients: Set[websockets.WebSocketServerProtocol] = set()
trade_events: Dict[str, list] = {}  # symbol -> list of trades

TIMEZONE = pytz.timezone("US/Eastern")
WS_HOST = "localhost"
WS_PORT = 8765


async def register_client(websocket):
    """Register a new connected client"""
    connected_clients.add(websocket)
    logger.info(f"Client connected. Total clients: {len(connected_clients)}")
    
    # Send existing trades to new client
    await websocket.send(json.dumps({
        "type": "INIT",
        "trades": trade_events,
        "timestamp": datetime.now(tz=TIMEZONE).isoformat()
    }))


async def unregister_client(websocket):
    """Unregister a disconnected client"""
    connected_clients.discard(websocket)
    logger.info(f"Client disconnected. Total clients: {len(connected_clients)}")


async def broadcast_trade_event(symbol: str, event: dict):
    """Broadcast a trade event to all connected clients"""
    if not connected_clients:
        return
    
    # Store trade event
    if symbol not in trade_events:
        trade_events[symbol] = []
    trade_events[symbol].append(event)
    
    # Broadcast to all clients
    message = json.dumps({
        "type": "TRADE_EVENT",
        "symbol": symbol,
        "event": event,
        "timestamp": datetime.now(tz=TIMEZONE).isoformat()
    })
    
    # Send to all connected clients
    if connected_clients:
        await asyncio.gather(
            *[client.send(message) for client in connected_clients],
            return_exceptions=True
        )
    
    logger.info(f"Broadcasted {event.get('action')} for {symbol}")


async def handle_client(websocket, path):
    """Handle WebSocket client connection"""
    await register_client(websocket)
    
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get("type")
                
                logger.info(f"[handle_client] Received message type: {msg_type}, keys: {list(data.keys())}")
                
                if msg_type == "PING":
                    await websocket.send(json.dumps({"type": "PONG"}))
                
                elif msg_type == "GET_TRADES":
                    # Client requests all trades
                    await websocket.send(json.dumps({
                        "type": "TRADES",
                        "data": trade_events,
                        "timestamp": datetime.now(tz=TIMEZONE).isoformat()
                    }))
                
                elif msg_type == "TRADE_EVENT" or data.get("action") in ("OPEN", "CLOSE"):
                    # Bot sending trade event - broadcast to all dashboard clients
                    symbol = data.get("symbol")
                    action = data.get("action")
                    
                    logger.info(f"[handle_client] Trade event received: {symbol} {action}")
                    
                    if symbol and action:
                        # Reformat to standard TRADE_EVENT format for dashboard
                        event_msg = {
                            "type": "TRADE_EVENT",
                            "symbol": symbol,
                            "action": action,
                            "reason": data.get("reason"),
                            "price": data.get("price"),
                            "trade": data.get("trade"),
                            "timestamp": datetime.now(tz=TIMEZONE).isoformat()
                        }
                        
                        # Store in trade history
                        if symbol not in trade_events:
                            trade_events[symbol] = []
                        trade_events[symbol].append(event_msg)
                        
                        # Broadcast to all connected clients
                        if connected_clients:
                            logger.info(f"[handle_client] Broadcasting {action} for {symbol} to {len(connected_clients)} clients")
                            await asyncio.gather(
                                *[client.send(json.dumps(event_msg)) for client in connected_clients],
                                return_exceptions=True
                            )
                        
                        logger.info(f"Broadcasted {action} for {symbol} to {len(connected_clients)} clients")
                    else:
                        logger.warning(f"[handle_client] Invalid trade event: symbol={symbol}, action={action}")
            
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON from client: {message}")
    
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        await unregister_client(websocket)


async def start_server():
    """Start the WebSocket server"""
    logger.info(f"Starting WebSocket server on ws://{WS_HOST}:{WS_PORT}")
    
    async with websockets.serve(handle_client, WS_HOST, WS_PORT):
        logger.info("WebSocket server running. Waiting for connections...")
        await asyncio.Future()  # Run forever


def log_bot_event(symbol: str, level: str, direction: str = None, **kwargs):
    """
    Log a bot event and broadcast to UI
    
    Example:
        log_bot_event("AAPL", "ENTER", direction="LONG", price=150.5, stop=149.9, target=152.0)
        log_bot_event("AAPL", "EXIT", reason="TARGET", price=152.1, pnl=1.6)
    """
    event = {
        "action": level,
        "timestamp": datetime.now(tz=TIMEZONE).isoformat(),
        **kwargs
    }
    
    if direction:
        event["direction"] = direction
    
    # Log to stdout
    print(f"[{datetime.now(tz=TIMEZONE).strftime('%H:%M:%S')}] {symbol:6} | {level:6} | {event}")
    
    # Broadcast to UI (async, non-blocking)
    asyncio.create_task(broadcast_trade_event(symbol, event))


if __name__ == "__main__":
    asyncio.run(start_server())
