import asyncio
import json
import os
import sys
import string
import time
import random
from datetime import datetime
from typing import Set

import aiohttp
import websockets
import logging
from pathlib import Path

# Add parent directory to path so we can import bot module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

# Mutable symbol list for hot-swap without restart
SYMBOLS_ACTIVE = list(SYMBOLS)
SYMBOL_LOCK = asyncio.Lock()

FETCH_INTERVAL = _parse_float_env("FETCH_INTERVAL", 60.0)

# FAKE_TICKS mode: generate synthetic data for testing
FAKE_TICKS = os.getenv("FAKE_TICKS", "false").lower() == "true"

# Price cache for fake ticks and real data
PRICE_CACHE = {}  # {symbol: {"base_price": float, "last_price": float}}


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
    """Fetch live price snapshot - either from Polygon API or generate fake ticks"""
    target_symbol = symbol or SYMBOL
    
    if FAKE_TICKS:
        # FAKE_TICKS mode: generate synthetic price data with realistic variation
        if target_symbol not in PRICE_CACHE:
            # Initialize base price from a reasonable estimate (for testing)
            # Default: random price between $10-$300 for unknown symbols
            base_prices = {
                "RARE": 22.80,
                "FTAI": 197.68,
                "FRMI": 8.09,
                "UAA": 5.15,
                "AAPL": 230.0,
                "MSFT": 420.0,
                "GOOGL": 140.0,
                "TSLA": 250.0,
            }
            # For symbols not in base_prices, generate a realistic price
            if target_symbol in base_prices:
                base_price = base_prices[target_symbol]
            else:
                # Generate consistent fake price for unknown symbols using symbol hash
                import hashlib
                symbol_hash = int(hashlib.md5(target_symbol.encode()).hexdigest(), 16)
                base_price = 20.0 + ((symbol_hash % 280) * 1.0)  # $20 - $300
            
            PRICE_CACHE[target_symbol] = {
                "base_price": base_price,
                "last_price": base_price
            }
        
        cache = PRICE_CACHE[target_symbol]
        
        # Add realistic price variation (±0.5% per tick)
        price_change_pct = random.uniform(-0.005, 0.005)
        new_price = round(cache["last_price"] * (1 + price_change_pct), 2)
        
        # Clamp to reasonable bounds (±5% from base)
        min_price = cache["base_price"] * 0.95
        max_price = cache["base_price"] * 1.05
        new_price = max(min_price, min(max_price, new_price))
        
        cache["last_price"] = new_price
        
        logger.debug(f"FAKE_TICKS: Generated {target_symbol}: ${new_price}")
        
        # Always return a valid snapshot dict for FAKE_TICKS
        return {
            "ticker": {
                "ticker": target_symbol,
                "day": {"c": new_price, "v": random.randint(1000000, 10000000)},
                "min": {"c": new_price, "v": random.randint(500000, 5000000), "n": random.randint(1000, 10000)},
                "updated": int(time.time() * 1e9)
            }
        }
    else:
        # REAL mode: fetch from Polygon API v2 snapshot endpoint
        if not POLYGON_API_KEY:
            logger.error("POLYGON_API_KEY is missing; cannot fetch snapshot")
            return {}

        url = build_snapshot_url(target_symbol)
        params = {"apiKey": POLYGON_API_KEY}

        try:
            logger.info(f"📊 Fetching Polygon API: {target_symbol} | URL: {url}")
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"❌ Polygon API error {resp.status} for {target_symbol}: {text}")
                    return {}
                data = await resp.json()
                
                # The v2 snapshot endpoint returns "ticker" as a direct object
                if "ticker" in data:
                    ticker_data = data["ticker"]
                    # Try to get price from: minute data -> day data -> previous day data
                    price = ticker_data.get("min", {}).get("c") or ticker_data.get("day", {}).get("c") or ticker_data.get("prevDay", {}).get("c")
                    volume = ticker_data.get("min", {}).get("v") or ticker_data.get("day", {}).get("v") or 0
                    timestamp = ticker_data.get("updated")
                    
                    logger.info(f"✅ Polygon {target_symbol}: Price=${price}, Vol={volume}, Updated={timestamp}")
                    
                    # Return as-is since it's already in the format we expect
                    return data
                else:
                    logger.warning(f"⚠️  Polygon {target_symbol}: No 'ticker' object in response")
                
                return data
        except Exception as e:
            logger.error(f"❌ Polygon API exception for {target_symbol}: {e}")
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
        async for message in websocket:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from {client_id}: {message}")
                continue

            cmd = data.get("command")
            if cmd == "replace_symbol":
                slot = data.get("slot")
                symbol = data.get("symbol")
                result = await replace_symbol(slot, symbol)
                await websocket.send(json.dumps({"type": "replace_ack", **result}))
            else:
                logger.debug(f"Unknown command from {client_id}: {data}")
    
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Client disconnected: {client_id}")
    
    except Exception as e:
        logger.error(f"Error with client {client_id}: {e}")
    
    finally:
        connected_clients.discard(websocket)


async def event_broadcaster():
    """Continuously broadcast trading events for all symbols to all connected clients"""
    logger.info("Event broadcaster started")
    fetch_cycle = 0
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                fetch_cycle += 1
                async with SYMBOL_LOCK:
                    symbols_snapshot = list(SYMBOLS_ACTIVE)
                
                logger.info(f"🔄 Fetch cycle #{fetch_cycle}: Fetching {len(symbols_snapshot)} symbols: {symbols_snapshot}")
                
                # Fetch all symbols in parallel
                snapshot_tasks = [fetch_snapshot(session, symbol) for symbol in symbols_snapshot]
                snapshots = await asyncio.gather(*snapshot_tasks, return_exceptions=True)
                
                # Combine snapshots into one message
                combined_message = {
                    "timestamp": int(time.time() * 1e9),
                    "symbols": {}
                }
                
                successful_count = 0
                for symbol, snapshot in zip(symbols_snapshot, snapshots):
                    if isinstance(snapshot, dict) and snapshot and "ticker" in snapshot:
                        combined_message["symbols"][symbol] = snapshot
                        successful_count += 1
                    else:
                        logger.warning(f"⚠️  Empty/invalid snapshot for {symbol}: {snapshot}")
                
                logger.info(f"✅ Broadcast cycle #{fetch_cycle}: Successfully fetched {successful_count}/{len(symbols_snapshot)} symbols")
                logger.debug(f"Combined message has {len(combined_message['symbols'])} symbols")
                
                # Always broadcast even if some symbols failed, but require at least some data
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
                    logger.info(f"📡 Broadcast cycle #{fetch_cycle}: Sent to {len(connected_clients)} clients ({len(active_symbols)} symbols: {active_symbols})")

            except Exception as e:
                logger.error(f"❌ Broadcaster error: {e}")

            await asyncio.sleep(FETCH_INTERVAL)


async def main():
    """Start the WebSocket server and broadcaster"""
    # Create the server
    async with websockets.serve(handler, "localhost", 8765):
        print("=" * 60)
        print("WebSocket Trading Server Started")
        print("=" * 60)
        print(f"Server running on ws://localhost:8765")
        print(f"Data Mode: {'FAKE_TICKS (synthetic)' if FAKE_TICKS else 'REAL (Polygon API)'}")
        print(f"Waiting for clients to connect...")
        print("=" * 60)
        logger.info(f"Data Mode: {'FAKE_TICKS' if FAKE_TICKS else 'REAL'}")
        
        # Run the event broadcaster as a concurrent task
        asyncio.create_task(event_broadcaster())
        
        # Start the trading bot (NEW)
        try:
            from bot.runner import bot_task, set_broadcast_callback
            
            # Set callback for bot to broadcast events to UI clients
            async def broadcast_bot_event(event):
                """Broadcast bot event to all connected clients"""
                message = json.dumps(event)
                disconnected = set()
                for client in connected_clients:
                    try:
                        await client.send(message)
                    except Exception as e:
                        logger.warning(f"Failed to send to client: {e}")
                        disconnected.add(client)
                # Clean up disconnected clients
                for client in disconnected:
                    connected_clients.discard(client)
            
            set_broadcast_callback(broadcast_bot_event)
            logger.info("Starting trading bot...")
            asyncio.create_task(bot_task())
        
        except ImportError as e:
            logger.warning(f"Bot import failed: {e}. Running server only.")
        except Exception as e:
            logger.error(f"Bot startup failed: {e}", exc_info=True)
        
        # Keep the server running indefinitely
        await asyncio.Event().wait()


async def replace_symbol(slot: int, symbol: str) -> dict:
    """Replace a symbol at a given slot index. Returns status dict."""
    try:
        slot = int(slot)
    except (TypeError, ValueError):
        return {"ok": False, "error": "slot must be an integer"}

    if not isinstance(symbol, str) or not symbol.strip():
        return {"ok": False, "error": "symbol must be a non-empty string"}

    symbol = symbol.strip().upper().split('#')[0].strip()

    async with SYMBOL_LOCK:
        if slot < 0 or slot >= len(SYMBOLS_ACTIVE):
            return {"ok": False, "error": f"slot out of range (0-{len(SYMBOLS_ACTIVE)-1})"}

        old_symbol = SYMBOLS_ACTIVE[slot]
        if old_symbol == symbol:
            return {"ok": True, "symbol": symbol, "slot": slot, "message": "symbol unchanged"}

        SYMBOLS_ACTIVE[slot] = symbol
        logger.info(f"Symbol replaced in slot {slot}: {old_symbol} -> {symbol}")

    return {"ok": True, "symbol": symbol, "slot": slot}


if __name__ == "__main__":
    asyncio.run(main())
