import asyncio
import json
import os
import sys
import string
import time
import random
from datetime import datetime
from typing import Set, List, Dict

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

# Global historical data cache
HISTORICAL_DATA_CACHE: Dict[str, List[dict]] = {}  # {symbol: [bars]}

# Pause/Resume state management
IS_PAUSED = False
PAUSED_INDICES: Dict[str, int] = {}  # {symbol: index} - saved checkpoint when paused
PAUSE_LOCK = asyncio.Lock()  # For thread-safe pause state access


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
POLYGON_WS_URL = os.getenv("POLYGON_WS_URL", "wss://delayed.massive.com/stocks")
SYMBOL = os.getenv("SYMBOL", "AAPL")

# Multi-symbol support
SYMBOLS_ENV = os.getenv("SYMBOLS", "AAPL,MSFT,GOOGL,TSLA")
SYMBOLS = [s.strip().upper().split('#')[0].strip() for s in SYMBOLS_ENV.split(",") if s.strip() and not s.strip().startswith('#')]

# Mutable symbol list for hot-swap without restart
SYMBOLS_ACTIVE = list(SYMBOLS)
SYMBOL_LOCK = asyncio.Lock()

FETCH_INTERVAL = _parse_float_env("FETCH_INTERVAL", 60.0)

# FAKE_TICKS mode: use historical data instead of generating synthetic prices
FAKE_TICKS = os.getenv("FAKE_TICKS", "false").lower() == "true"

# Historical data file path - configurable via environment variable
# When FAKE_TICKS=true, load data from the file specified in HISTORICAL_DATA_FILE env var
_data_filename = os.getenv("HISTORICAL_DATA_FILE", "historical_data.json")
HISTORICAL_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / _data_filename


def load_historical_data() -> Dict[str, List[dict]]:
    """Load historical data from JSON file and organize by symbol."""
    global HISTORICAL_DATA_CACHE
    
    if HISTORICAL_DATA_CACHE:
        return HISTORICAL_DATA_CACHE
    
    try:
        if not HISTORICAL_DATA_FILE.exists():
            logger.error(f"Historical data file not found: {HISTORICAL_DATA_FILE}")
            return {}
        
        with open(HISTORICAL_DATA_FILE, 'r') as f:
            data = json.load(f)
        
        bars = data.get('bars', [])
        logger.info(f"Loaded {len(bars)} bars from historical data")
        
        # Organize bars by symbol
        symbol_bars = {}
        for bar in bars:
            symbol = bar.get('sym', '').upper()
            if symbol:
                if symbol not in symbol_bars:
                    symbol_bars[symbol] = []
                symbol_bars[symbol].append(bar)
        
        HISTORICAL_DATA_CACHE = symbol_bars
        logger.info(f"Organized into {len(symbol_bars)} symbols: {list(symbol_bars.keys())}")
        
        return symbol_bars
    
    except Exception as e:
        logger.error(f"Failed to load historical data: {e}", exc_info=True)
        return {}


async def get_active_symbols() -> List[str]:
    """Safely copy the current active symbols list."""
    async with SYMBOL_LOCK:
        return list(SYMBOLS_ACTIVE)


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
    """Fetch price snapshot - uses historical data when FAKE_TICKS is enabled."""
    target_symbol = (symbol or SYMBOL).upper()
    
    if FAKE_TICKS:
        # FAKE_TICKS mode: use historical data instead of synthetic prices
        if not HISTORICAL_DATA_CACHE:
            load_historical_data()
        
        if target_symbol not in HISTORICAL_DATA_CACHE:
            logger.warning(f"Symbol {target_symbol} not found in historical data")
            return {}
        
        # For FAKE_TICKS, we'll return empty here; actual data is streamed via aggregates_ws_loop
        logger.debug(f"FAKE_TICKS: {target_symbol} data available in cache ({len(HISTORICAL_DATA_CACHE[target_symbol])} bars)")
        return {}
    else:
        # REAL mode now handled via WebSocket aggregates; HTTP snapshot fetch disabled
        logger.debug("Real snapshot fetch skipped (using WebSocket aggregates)")
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


def map_aggregate_to_snapshot(event: dict) -> dict | None:
    """Convert per-second aggregate payload to snapshot shape expected by the UI."""
    try:
        symbol = (event.get("sym") or "").upper()
        close_price = event.get("c")
        if not symbol or close_price is None:
            return None

        open_price = event.get("o") or close_price
        high_price = event.get("h") or close_price
        low_price = event.get("l") or close_price
        volume = event.get("v") or 0
        agg_volume = event.get("av") or volume
        trade_count = event.get("z") or 0
        start_ms = event.get("s") or int(time.time() * 1000)
        end_ms = event.get("e") or start_ms
        updated_ns = int(end_ms * 1_000_000)

        return {
            "ticker": {
                "ticker": symbol,
                "day": {
                    "o": open_price,
                    "h": high_price,
                    "l": low_price,
                    "c": close_price,
                    "v": agg_volume,
                    "vw": event.get("vw"),
                },
                "min": {
                    "o": open_price,
                    "h": high_price,
                    "l": low_price,
                    "c": close_price,
                    "v": volume,
                    "n": trade_count,
                    "t": start_ms,
                },
                "prevDay": {},
                "updated": updated_ns,
            }
        }
    except Exception as e:
        logger.error(f"Failed to map aggregate to snapshot: {e}", exc_info=True)
        return None


async def broadcast_symbols(symbol_snapshots: dict) -> None:
    """Broadcast symbol snapshots to all connected clients."""
    if not symbol_snapshots:
        return

    message = json.dumps({
        "timestamp": int(time.time() * 1e9),
        "symbols": symbol_snapshots,
    })

    disconnected_clients = set()
    for client in connected_clients:
        try:
            await client.send(message)
        except websockets.exceptions.ConnectionClosed:
            disconnected_clients.add(client)
        except Exception as e:
            logger.warning(f"Failed to send to client: {e}")
            disconnected_clients.add(client)

    for client in disconnected_clients:
        connected_clients.discard(client)

    logger.info(f"📡 Broadcasted {len(symbol_snapshots)} symbols to {len(connected_clients)} clients")


async def pause_stream() -> dict:
    """Pause the tick stream and save current indices."""
    global IS_PAUSED, PAUSED_INDICES
    async with PAUSE_LOCK:
        if IS_PAUSED:
            return {"status": "already_paused", "message": "Stream is already paused"}
        IS_PAUSED = True
        logger.warning("⏸️  STREAM PAUSED - No ticks will be sent to clients")
        return {"status": "paused", "message": "Stream paused successfully"}


async def resume_stream() -> dict:
    """Resume the tick stream from saved indices."""
    global IS_PAUSED
    async with PAUSE_LOCK:
        if not IS_PAUSED:
            return {"status": "already_running", "message": "Stream is already running"}
        IS_PAUSED = False
        logger.warning("▶️  STREAM RESUMED - Ticks resuming from checkpoint")
        return {"status": "resumed", "message": "Stream resumed successfully"}


async def get_pause_status() -> dict:
    """Get current pause status."""
    global IS_PAUSED
    async with PAUSE_LOCK:
        return {"is_paused": IS_PAUSED, "status": "paused" if IS_PAUSED else "running"}


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

            # Handle trade events from bot
            if data.get("type") == "TRADE_EVENT":
                logger.info(f"📨 Received trade event from bot: {data.get('action')} for {data.get('symbol')}")
                # Broadcast to all OTHER clients (dashboard)
                broadcast_msg = json.dumps(data)
                # Make a copy to avoid "Set changed size during iteration" error
                clients_to_notify = [c for c in connected_clients if c != websocket]
                logger.info(f"📢 Notifying {len(clients_to_notify)} dashboard clients of {data.get('action')} for {data.get('symbol')}")
                for client in clients_to_notify:
                    try:
                        await client.send(broadcast_msg)
                        logger.info(f"✅ Sent {data.get('action')} event to client")
                    except Exception as e:
                        logger.warning(f"❌ Failed to send trade event to client: {e}")
                continue
            
            # Handle command messages (replace symbol, pause/resume, etc.)
            cmd = data.get("command")
            if cmd == "replace_symbol":
                slot = data.get("slot")
                symbol = data.get("symbol")
                result = await replace_symbol(slot, symbol)
                await websocket.send(json.dumps({"type": "replace_ack", **result}))
            elif cmd == "pause":
                result = await pause_stream()
                await websocket.send(json.dumps({"type": "pause_ack", **result}))
            elif cmd == "resume":
                result = await resume_stream()
                await websocket.send(json.dumps({"type": "resume_ack", **result}))
            elif cmd == "get_pause_status":
                result = await get_pause_status()
                await websocket.send(json.dumps({"type": "pause_status", **result}))
            else:
                if "command" in data or data.get("type"):
                    logger.debug(f"Unknown message from {client_id}: {data}")
    
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
                symbols_snapshot = await get_active_symbols()
                
                logger.info(f"🔄 Fetch cycle #{fetch_cycle}: Fetching {len(symbols_snapshot)} symbols: {symbols_snapshot}")
                
                # Fetch all symbols in parallel
                snapshot_tasks = [fetch_snapshot(session, symbol) for symbol in symbols_snapshot]
                snapshots = await asyncio.gather(*snapshot_tasks, return_exceptions=True)
                
                symbol_payload = {}
                successful_count = 0
                for symbol, snapshot in zip(symbols_snapshot, snapshots):
                    if isinstance(snapshot, dict) and snapshot and "ticker" in snapshot:
                        symbol_payload[symbol] = snapshot
                        successful_count += 1
                    else:
                        logger.warning(f"⚠️  Empty/invalid snapshot for {symbol}: {snapshot}")
                
                logger.info(f"✅ Broadcast cycle #{fetch_cycle}: Successfully fetched {successful_count}/{len(symbols_snapshot)} symbols")
                logger.debug(f"Combined message has {len(symbol_payload)} symbols")

                if symbol_payload:
                    await broadcast_symbols(symbol_payload)

            except Exception as e:
                logger.error(f"❌ Broadcaster error: {e}")

            await asyncio.sleep(FETCH_INTERVAL)


async def aggregates_ws_loop():
    """Stream aggregates - from WebSocket (real mode) or historical data (FAKE_TICKS mode)."""
    if FAKE_TICKS:
        await historical_data_streaming_loop()
    else:
        await polygon_aggregates_ws_loop()


async def historical_data_streaming_loop():
    """Stream historical data tick-by-tick to simulate live trading."""
    logger.info("Starting historical data streaming loop (FAKE_TICKS mode)")
    
    # Load historical data once
    load_historical_data()
    
    symbol_bars: Dict[str, List[dict]] = HISTORICAL_DATA_CACHE
    if not symbol_bars:
        logger.error("No historical data loaded!")
        await asyncio.sleep(5)
        return
    
    # Create iterators for each symbol
    symbol_indices: Dict[str, int] = {sym: 0 for sym in symbol_bars.keys()}
    tick_count = 0
    
    # Stream bars continuously, cycling through symbols
    while True:
        try:
            # Check if paused - if so, just wait and don't process ticks
            if IS_PAUSED:
                await asyncio.sleep(0.1)
                continue
            
            symbols = await get_active_symbols()
            if not symbols:
                logger.warning("No active symbols; sleeping...")
                await asyncio.sleep(1)
                continue
            
            symbol_updates = {}
            
            # Stream one bar per active symbol in each cycle
            for symbol in symbols:
                if symbol not in symbol_bars or not symbol_bars[symbol]:
                    logger.warning(f"No bars for symbol {symbol}")
                    continue
                
                bars = symbol_bars[symbol]
                idx = symbol_indices.get(symbol, 0)
                
                # Cycle through bars (when reaching the end, start over)
                if idx >= len(bars):
                    idx = 0
                    logger.info(f"Cycling {symbol} bars (restarted from beginning)")
                
                bar = bars[idx]
                symbol_indices[symbol] = idx + 1
                tick_count += 1
                
                # Convert bar to snapshot format
                snapshot = map_aggregate_to_snapshot(bar)
                if snapshot:
                    symbol_updates[symbol] = snapshot
            
            if symbol_updates:
                logger.debug(f"Historical tick #{tick_count}: Streaming {len(symbol_updates)} symbols")
                await broadcast_symbols(symbol_updates)
            
            # Sleep to simulate real-time (FETCH_INTERVAL = 1 second for 1-minute bars)
            await asyncio.sleep(FETCH_INTERVAL)
        
        except Exception as e:
            logger.error(f"Historical streaming error: {e}", exc_info=True)
            await asyncio.sleep(5)


async def polygon_aggregates_ws_loop():
    """Stream per-second aggregates from provider WebSocket and broadcast to UI."""
    logger.info("Starting Polygon aggregates WebSocket streaming (real mode)")
    
    while True:
        symbols = await get_active_symbols()
        if not symbols:
            logger.warning("No active symbols to subscribe; sleeping...")
            await asyncio.sleep(1)
            continue

        subscribe_params = ",".join(f"A.{s}" for s in symbols)
        logger.info(f"Connecting to aggregates WS: {POLYGON_WS_URL} | symbols={symbols}")

        try:
            async with websockets.connect(POLYGON_WS_URL) as ws:
                if POLYGON_API_KEY:
                    await ws.send(json.dumps({"action": "auth", "params": POLYGON_API_KEY}))

                await ws.send(json.dumps({"action": "subscribe", "params": subscribe_params}))
                subscribed = set(symbols)
                logger.info(f"Subscribed to aggregates: {sorted(subscribed)}")

                while True:
                    raw = await ws.recv()
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON from WS: {raw}")
                        continue

                    events = data if isinstance(data, list) else [data]
                    symbol_updates = {}

                    for event in events:
                        if event.get("ev") == "status":
                            status = event.get("status")
                            message = event.get("message")
                            if status and status.lower() != "connected":
                                logger.warning(f"WS status: {status} - {message}")
                            else:
                                logger.info(f"WS status: {status} - {message}")
                            continue
                        if event.get("ev") != "A":
                            continue
                        snapshot = map_aggregate_to_snapshot(event)
                        if snapshot:
                            symbol = (event.get("sym") or "").upper()
                            symbol_updates[symbol] = snapshot

                    if symbol_updates:
                        logger.info(f"Aggregates received: {len(symbol_updates)} symbols")
                        await broadcast_symbols(symbol_updates)

                    # Detect symbol list changes and adjust subscriptions
                    current_symbols = set(await get_active_symbols())
                    if current_symbols != subscribed:
                        additions = current_symbols - subscribed
                        removals = subscribed - current_symbols

                        if additions:
                            await ws.send(json.dumps({
                                "action": "subscribe",
                                "params": ",".join(f"A.{s}" for s in additions)
                            }))
                            logger.info(f"Subscribed to new symbols: {sorted(additions)}")
                        if removals:
                            await ws.send(json.dumps({
                                "action": "unsubscribe",
                                "params": ",".join(f"A.{s}" for s in removals)
                            }))
                            logger.info(f"Unsubscribed symbols: {sorted(removals)}")

                        subscribed = current_symbols

        except Exception as e:
            logger.error(f"Aggregates WebSocket error: {e}", exc_info=True)
            await asyncio.sleep(3)



async def main():
    """Start the WebSocket server and broadcaster"""
    # Create the server
    async with websockets.serve(handler, "localhost", 8765):
        print("=" * 60)
        print("WebSocket Trading Server Started")
        print("=" * 60)
        print(f"Server running on ws://localhost:8765")
        if FAKE_TICKS:
            print(f"Data Mode: FAKE_TICKS (using historical data from {HISTORICAL_DATA_FILE})")
        else:
            print(f"Data Mode: REAL (using Polygon WebSocket aggregates)")
        print(f"Active Symbols: {SYMBOLS_ACTIVE}")
        print(f"Waiting for clients to connect...")
        print("=" * 60)
        logger.info(f"Data Mode: {'FAKE_TICKS (historical)' if FAKE_TICKS else 'REAL (WS aggregates)'}")

        
        # Run the data pipeline as a concurrent task
        # When FAKE_TICKS=true: stream historical data from JSON file
        # When FAKE_TICKS=false: stream live data from Polygon WebSocket
        asyncio.create_task(aggregates_ws_loop())
        
        # Start the trading bot (NEW)
        try:
            if FAKE_TICKS:
                from bot.runner import bot_task, set_broadcast_callback

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
                    for client in disconnected:
                        connected_clients.discard(client)

                set_broadcast_callback(broadcast_bot_event)
                logger.info("Starting trading bot (historical playback)...")
                asyncio.create_task(bot_task())
            else:
                logger.info("FAKE_TICKS=false → skipping historical bot runner integration")
        
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
