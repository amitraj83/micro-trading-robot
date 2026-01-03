"""
Bot Runner - Integrates new trading bot with WebSocket server

This module runs the async bot with the new MicroTradingStrategy in parallel with the 
WebSocket server, broadcasting bot trade events to connected UI clients.
"""

import asyncio
import json
import logging
from datetime import datetime
import pytz
from pathlib import Path
import os
import sys
import websockets

# Ensure the parent directory is in sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # Add bot dir itself

print("DEBUG: Starting bot runner...", flush=True)

# Setup logging
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "bot_runner.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

# Change to workspace root so relative paths work correctly
os.chdir(Path(__file__).resolve().parent.parent)

print("DEBUG: Importing trading_bot...", flush=True)

logger = logging.getLogger(__name__)

# Import the new trading bot with strategy (use relative imports to avoid bot.py conflict)
print("DEBUG: About to import TradingBotClient...", flush=True)
from trading_bot import TradingBotClient
print("DEBUG: TradingBotClient imported", flush=True)
from models import Tick
print("DEBUG: Tick imported", flush=True)
from config import STRATEGY_CONFIG
print("DEBUG: All imports done", flush=True)

TIMEZONE = pytz.timezone("US/Eastern")

# Global reference to broadcast callback
_broadcast_callback = None


def set_broadcast_callback(callback):
    """Set the callback for broadcasting bot events to UI clients"""
    global _broadcast_callback
    _broadcast_callback = callback


def log_bot_event(symbol: str, level: str, message: str):
    """
    Log bot event and broadcast to UI clients
    """
    et = datetime.now(tz=TIMEZONE)
    time_str = et.strftime("%H:%M:%S")
    formatted_msg = f"[{time_str}] {symbol:6} | {level:6} | {message}"
    
    # Log to file and stdout
    logger.info(formatted_msg)
    print(formatted_msg)
    
    # Broadcast to UI if callback set
    if _broadcast_callback:
        event = {
            "type": "BOT_EVENT",
            "symbol": symbol,
            "level": level,
            "message": formatted_msg,
            "timestamp": et.isoformat(),
        }
        try:
            asyncio.create_task(_broadcast_callback(event))
        except:
            pass


# Global bot client instance (created once, reused across connections)
_bot_client = None

async def connect_to_historical_data_stream():
    """
    Connect to the historical data server and stream data to the bot
    
    The historical data server runs on ws://localhost:8001 and streams
    historical market data (1-minute bars) to the bot.
    """
    global _bot_client
    
    # Create bot client once (persists across reconnections)
    if _bot_client is None:
        logger.info("Creating new TradingBotClient instance")
        _bot_client = TradingBotClient()
    
    # Get symbols from environment
    symbols_str = os.getenv("SYMBOLS", "QQQ,SPY,NVDA,AAPL,MSFT")
    symbols = [s.strip() for s in symbols_str.split(",")]
    
    # Determine WebSocket URL based on FAKE_TICKS setting
    fake_ticks = os.getenv("FAKE_TICKS", "false").lower() == "true"
    if fake_ticks:
        ws_url = "ws://localhost:8001"  # Historical data server
        logger.info("🎬 FAKE_TICKS=true → Using historical data server at ws://localhost:8001")
    else:
        ws_url = os.getenv("WS_URL", "ws://localhost:8765")  # Real WebSocket server
    
    logger.info(f"Connecting to historical data stream at {ws_url}")
    logger.info(f"Subscribing to symbols: {', '.join(symbols)}")
    
    tick_count = 0
    trade_count = 0
    broadcast_ws = None  # Connection to main websocket server for broadcasting events
    
    # Helper to ensure broadcast connection exists
    async def broadcast_event(event):
        """Send event to dashboard via websocket server"""
        nonlocal broadcast_ws
        try:
            # Check if connection is closed or doesn't exist
            if broadcast_ws is None:
                broadcast_ws = await websockets.connect("ws://localhost:8765")
                logger.info("🔗 Broadcast connection established")
            
            # Try to send; if connection is dead, reconnect
            try:
                await broadcast_ws.send(json.dumps(event))
                logger.info(f"📤 Broadcasted event: {event.get('action')}")
            except (websockets.exceptions.ConnectionClosed, RuntimeError):
                # Connection died, reconnect and retry
                broadcast_ws = await websockets.connect("ws://localhost:8765")
                logger.info("🔗 Broadcast connection re-established (was closed)")
                await broadcast_ws.send(json.dumps(event))
                logger.info(f"📤 Broadcasted event (retry): {event.get('action')}")
        except Exception as e:
            logger.info(f"⚠️ Failed to broadcast event: {e}")
    
    try:
        async with websockets.connect(ws_url) as websocket:
            logger.info("✅ Connected to historical data server")
            
            # Subscribe to all symbols
            for symbol in symbols:
                subscribe_msg = {"type": "subscribe", "symbol": symbol}
                await websocket.send(json.dumps(subscribe_msg))
                logger.info(f"  → Subscribed to {symbol}")
            
            logger.info(f"Streaming ticks from {ws_url}...")
            
            # Stream ticks
            async for message in websocket:
                try:
                    bar_data = json.loads(message)
                    
                    # Log every tick for debugging
                    if tick_count < 10 or tick_count % 50 == 0:
                        logger.info(f"📈 Tick #{tick_count}: {bar_data.get('sym')} @ ${bar_data.get('c', 0):.2f}")
                    
                    # Convert bar to tick format
                    tick = Tick(
                        price=bar_data.get("c", 0),  # Close price
                        volume=bar_data.get("v", 0),  # Volume
                        timestamp_ns=int(bar_data.get("s", 0) * 1_000_000),  # Start time in ns
                        symbol=bar_data.get("sym", "UNKNOWN"),
                    )
                    
                    tick_count += 1
                    
                    # Process tick through strategy (using persistent client)
                    event = _bot_client.strategy.process_tick(tick)
                    
                    # Handle trade events
                    if event.get("action"):
                        trade_count += 1
                        action = event["action"]
                        reason = event.get("reason", "N/A")
                        pnl = event.get("metrics", {}).get("total_pnl", 0)
                        trade_obj = event.get("trade")
                        
                        # Log with more detail for exits
                        if action == "CLOSE" and trade_obj:
                            log_bot_event(
                                tick.symbol,
                                f"{action}",
                                f"Exit: {reason} | Entry: ${trade_obj.entry_price:.2f} | Exit: ${tick.price:.2f} | PnL: {pnl:+.2f}%"
                            )
                        else:
                            log_bot_event(
                                tick.symbol,
                                action,
                                f"{reason} | PnL: {pnl:+.2f}%"
                            )
                        
                        # Broadcast to UI - enhanced with more details
                        broadcast_msg = {
                            "type": "TRADE_EVENT",
                            "symbol": tick.symbol,
                            "action": action,
                            "reason": reason,
                            "price": tick.price,
                            "timestamp": datetime.now(tz=TIMEZONE).isoformat(),
                        }
                        
                        # Add trade details if available
                        if trade_obj:
                            broadcast_msg["trade"] = {
                                "direction": getattr(trade_obj, "direction", None),
                                "entry_price": getattr(trade_obj, "entry_price", None),
                                "pnl": getattr(trade_obj, "pnl", None),
                                "entry_time": str(getattr(trade_obj, "entry_time", None)),
                            }
                        
                        try:
                            await broadcast_event(broadcast_msg)
                        except Exception as e:
                            logger.debug(f"Failed to broadcast event: {e}")
                    
                    # Test event injection after 100 ticks (for debugging)
                    if tick_count == 100 and trade_count == 0:
                        logger.info("🧪 TEST: Injecting test OPEN event for QQQ after 100 ticks")
                        test_event = {
                            "type": "TRADE_EVENT",
                            "action": "OPEN",
                            "symbol": "QQQ",
                            "trade": {
                                "entry_price": tick.price - 0.50,  # Slightly below current price
                                "direction": "LONG",
                            },
                            "reason": "[TEST] Auto-injected event"
                        }
                        await broadcast_event(test_event)
                    
                    # Periodic status
                    if tick_count % 100 == 0:
                        logger.info(f"📊 Processed {tick_count} ticks, {trade_count} trades")
                    
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON: {message[:100]}")
                    continue
                except Exception as e:
                    logger.error(f"Error processing tick: {e}", exc_info=True)
                    continue
    
    except asyncio.CancelledError:
        logger.info(f"Bot cancelled. Processed {tick_count} ticks, {trade_count} trades")
        raise
    except Exception as e:
        logger.error(f"Connection error: {e}", exc_info=True)
        await asyncio.sleep(5)


async def run_bot():
    """
    Run the trading bot
    
    This version uses the new MicroTradingStrategy with EMA50/EMA20 detection
    and connects to the historical data server.
    """
    logger.info("Starting new trading bot with MicroTradingStrategy")
    
    try:
        await connect_to_historical_data_stream()
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)
        await asyncio.sleep(5)


async def bot_task():
    """Run bot as a repeating task (restarts on failure)"""
    while True:
        try:
            await run_bot()
        except asyncio.CancelledError:
            logger.info("Bot task cancelled")
            break
        except Exception as e:
            logger.error(f"Bot crashed: {e}. Restarting in 5 seconds...")
            await asyncio.sleep(5)
    
    # Broadcast to UI if callback set
    if _broadcast_callback:
        event = {
            "type": "BOT_EVENT",
            "symbol": symbol,
            "level": level,
            "message": message,
            "timestamp": et.isoformat(),
            "args": [str(a) for a in args]
        }
        asyncio.create_task(_broadcast_callback(event))


async def run_bot():
    """
    Run the trading bot
    
    This version uses the new MicroTradingStrategy with EMA50/EMA20 detection
    and connects to the historical data server.
    """
    logger.info("Starting new trading bot with MicroTradingStrategy")
    
    try:
        await connect_to_historical_data_stream()
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)
        await asyncio.sleep(5)


async def bot_task():
    """Run bot as a repeating task (restarts on failure)"""
    while True:
        try:
            await run_bot()
        except asyncio.CancelledError:
            logger.info("Bot task cancelled")
            break
        except Exception as e:
            logger.error(f"Bot crashed: {e}. Restarting in 5 seconds...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    print("DEBUG: Starting asyncio event loop...", flush=True)
    try:
        asyncio.run(bot_task())
    except KeyboardInterrupt:
        print("Bot stopped by user")
    except Exception as e:
        print(f"Bot error: {e}")
        import traceback
        traceback.print_exc()

