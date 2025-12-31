import asyncio
import json
import os
import string
import time
from datetime import datetime
from typing import Set

import aiohttp
import websockets
import logging
from pathlib import Path

# Logging setup - send server logs to logs/websocket_server.log
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "websocket_server.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Store connected clients
connected_clients: Set = set()


def generate_request_id():
    """Generate a random request ID"""
    return ''.join(os.urandom(16).hex())


def load_env_from_file(path: str = ".env") -> None:
    """Load simple KEY=VALUE lines from a .env file if not already in os.environ."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception as e:
        logger.error(f"Failed to load .env: {e}")


# Load environment values early
load_env_from_file()

def _parse_float_env(key: str, default: float) -> float:
    raw = os.getenv(key)
    if not raw:
        return default
    cleaned = raw.split("#", 1)[0].strip()
    try:
        return float(cleaned)
    except ValueError:
        logger.warning(f"Invalid float for {key}: {raw!r}, using default {default}")
        return default


POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
POLYGON_BASE_URL = os.getenv("POLYGON_BASE_URL", "")
POLYGON_SNAPSHOT_PATH = os.getenv("POLYGON_SNAPSHOT_PATH", "")
SYMBOL = os.getenv("SYMBOL", "AAPL")

# Multi-symbol support
SYMBOLS_ENV = os.getenv("SYMBOLS", "AAPL,MSFT,GOOGL,TSLA")
SYMBOLS = [s.strip().upper().split('#')[0].strip() for s in SYMBOLS_ENV.split(",") if s.strip() and not s.strip().startswith('#')]

FETCH_INTERVAL = _parse_float_env("FETCH_INTERVAL", 60.0)


def build_snapshot_url(symbol: str = None) -> str:
    """Build snapshot URL for a specific symbol (or SYMBOL fallback)."""
    base = POLYGON_BASE_URL.rstrip("/")
    path = POLYGON_SNAPSHOT_PATH
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path = path + "/"
    target_symbol = (symbol or SYMBOL).upper()
    return f"{base}{path}{target_symbol}"


SNAPSHOT_URL = build_snapshot_url()


async def fetch_snapshot(session: aiohttp.ClientSession, symbol: str = None) -> dict:
    """Fetch snapshot for a specific symbol (or SYMBOL fallback)."""
    if not POLYGON_API_KEY:
        logger.error("POLYGON_API_KEY is missing; cannot fetch snapshot")
        return {}

    url = build_snapshot_url(symbol)
    params = {"apiKey": POLYGON_API_KEY}

    try:
        async with session.get(url, params=params, timeout=10) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error(f"Snapshot fetch failed {resp.status} for {symbol or SYMBOL}: {text}")
                return {}
            return await resp.json()
    except Exception as e:
        logger.error(f"Error fetching snapshot for {symbol or SYMBOL}: {e}")
        return {}


def map_snapshot_to_event(data: dict) -> dict | None:
    ticker = data.get("ticker") or {}
    day = ticker.get("day") or {}
    minute = ticker.get("min") or {}

    last_price = day.get("c") or minute.get("c")
    if last_price is None:
        logger.warning("Missing last price in snapshot; skipping event")
        return None

    # Derive bid/ask around the last price (deterministic, no randomness)
    bid_price = round(last_price - 0.01, 2)
    ask_price = round(last_price + 0.01, 2)

    bid_size = max(1, int(minute.get("n", 1)))
    ask_size = max(1, int(minute.get("v", 1)))

    updated_ns = ticker.get("updated")
    quote_ms = minute.get("t")
    quote_ns = int(quote_ms * 1_000_000) if quote_ms else updated_ns
    fallback_ts = int(time.time() * 1e9)

    return {
        "request_id": generate_request_id(),
        "results": {
            "P": round(last_price, 2),
            "S": bid_size,
            "T": ticker.get("ticker", SYMBOL),
            "X": 11,  # Fixed exchange code
            "p": bid_price,
            "q": quote_ns or fallback_ts,
            "s": ask_size,
            "t": updated_ns or fallback_ts,
            "x": 11,
            "y": quote_ns or updated_ns or fallback_ts,
            "z": 1,
        },
        "status": data.get("status", "OK"),
    }


async def handler(websocket):
    """Handle new client connections"""
    client_id = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
    connected_clients.add(websocket)
    logger.info(f"Client connected: {client_id}")
    
    try:
        # Keep the connection open and wait for incoming messages
        async for message in websocket:
            logger.debug(f"Received from {client_id}: {message}")
            # Just echo back for now (optional)
    
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Client disconnected: {client_id}")
    
    except Exception as e:
        logger.error(f"Error with client {client_id}: {e}")
    
    finally:
        connected_clients.discard(websocket)


async def event_broadcaster():
    """Continuously broadcast trading events for all symbols to all connected clients"""
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                # Fetch all symbols in parallel
                snapshot_tasks = [fetch_snapshot(session, symbol) for symbol in SYMBOLS]
                snapshots = await asyncio.gather(*snapshot_tasks, return_exceptions=True)
                
                # Combine snapshots into one message
                combined_message = {
                    "timestamp": int(time.time() * 1e9),
                    "symbols": {}
                }
                
                for symbol, snapshot in zip(SYMBOLS, snapshots):
                    if isinstance(snapshot, dict) and snapshot:
                        combined_message["symbols"][symbol] = snapshot
                
                if combined_message["symbols"] and connected_clients:
                    message = json.dumps(combined_message)
                    disconnected_clients = set()
                    for client in connected_clients:
                        try:
                            await client.send(message)
                        except websockets.exceptions.ConnectionClosed:
                            disconnected_clients.add(client)

                    for client in disconnected_clients:
                        connected_clients.discard(client)

                    active_symbols = list(combined_message["symbols"].keys())
                    logger.info(f"Snapshot broadcasted to {len(connected_clients)} clients ({len(active_symbols)} symbols: {active_symbols})")

            except Exception as e:
                logger.error(f"Error in broadcaster: {e}")

            await asyncio.sleep(FETCH_INTERVAL)


async def main():
    """Start the WebSocket server and broadcaster"""
    # Create the server
    async with websockets.serve(handler, "localhost", 8765):
        print("=" * 60)
        print("WebSocket Trading Server Started")
        print("=" * 60)
        print(f"Server running on ws://localhost:8765")
        print(f"Waiting for clients to connect...")
        print("=" * 60)
        
        # Run the event broadcaster alongside the server
        await event_broadcaster()


if __name__ == "__main__":
    asyncio.run(main())
