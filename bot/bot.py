"""
Async Momentum Trading Bot v2
- Polygon WebSocket for second-level aggregates
- Multi-symbol support
- State machine: IDLE → COMPRESSION → IN_TRADE → IDLE
- VWAP bias from provider field 'a'
- Compression persistence (≥3 bars)
- Expansion entry after compression
"""

import asyncio
import json
import websockets
from collections import deque
from statistics import mean
from datetime import datetime
import pytz
import os

# ======================
# CONFIG
# ======================

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
FAKE_TICKS = os.getenv("FAKE_TICKS", "false").lower() == "true"

# WebSocket URL - use fake server if FAKE_TICKS enabled
if FAKE_TICKS:
    WS_URL = "ws://localhost:8001"  # Fake Polygon WebSocket server
else:
    WS_URL = "wss://delayed.polygon.io/stocks"  # Real Polygon WebSocket

TIMEZONE = pytz.timezone("US/Eastern")

# Rolling buffers
MAX_BARS_5 = 5
MAX_BARS_10 = 10
MAX_BARS_30 = 30

# Compression & Expansion thresholds - RELAXED FOR TESTING
MIN_COMPRESSION_BARS = 1  # Very low for testing
RANGE_EXPAND_FACTOR = 1.2  # Very low for testing
VOLUME_EXPAND_FACTOR = 1.1  # Very low for testing
CLOSE_EDGE_PERCENT = 0.3  # Relaxed from 20% to 30%
RANGE_SHRINK_FACTOR = 1.3  # Relaxed from 1.1 to 1.3

# Exit conditions
TIME_EXIT_SECONDS = 15
TARGET_RR = 1.5  # Risk-reward multiplier

# Get symbols from env
SYMBOLS = os.getenv("SYMBOLS", "AAPL,TSLA").upper().split(",")

# ======================
# STATE MANAGEMENT
# ======================

class SymbolState:
    """Per-symbol trading state"""
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        
        # Rolling bars
        self.bars_5 = deque(maxlen=MAX_BARS_5)
        self.bars_10 = deque(maxlen=MAX_BARS_10)
        self.bars_30 = deque(maxlen=MAX_BARS_30)
        
        # State machine
        self.state = "IDLE"  # IDLE | COMPRESSION | IN_TRADE
        self.compression_bar_count = 0  # Count consecutive compression bars
        
        # Trade tracking
        self.current_position = None  # LONG | SHORT
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.entry_time = None  # Unix milliseconds
        
    def reset_compression(self):
        """Reset compression tracking"""
        self.compression_bar_count = 0
        self.state = "IDLE"
        
    def reset_trade(self):
        """Reset trade state"""
        self.current_position = None
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.entry_time = None
        self.reset_compression()


# Global state dictionary (keyed by symbol)
states = {sym: SymbolState(sym) for sym in SYMBOLS}


# ======================
# UTILITIES
# ======================

def to_et(timestamp_ms: int) -> datetime:
    """Convert Unix milliseconds to US/Eastern"""
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC).astimezone(TIMEZONE)


def is_regular_session(timestamp_ms: int) -> bool:
    """Check if timestamp is during 09:30-16:00 ET"""
    et = to_et(timestamp_ms)
    hour = et.hour
    minute = et.minute
    
    # 09:30 - 16:00
    if hour < 9:
        return False
    if hour == 9 and minute < 30:
        return False
    if hour >= 16:
        return False
    return True


def log_trade(level: str, symbol: str, *args):
    """Log trades with timestamp"""
    et = to_et(int(datetime.now(tz=pytz.UTC).timestamp() * 1000))
    time_str = et.strftime("%H:%M:%S")
    print(f"[{time_str}] {symbol:6} | {level:6} | {' '.join(str(a) for a in args)}")


# ======================
# STRATEGY LOGIC
# ======================

def get_vwap_bias(bar: dict, recent_bars: list) -> str:
    """
    Determine market bias using session VWAP (field 'a')
    
    Bullish: at least 2 of last 3 closes > VWAP
    Bearish: at least 2 of last 3 closes < VWAP
    Neutral: otherwise
    """
    if len(recent_bars) < 2:
        return "NEUTRAL"
    
    vwap = bar.get("a")
    if vwap is None:
        return "NEUTRAL"
    
    closes = [b["c"] for b in recent_bars[-3:]]
    bullish_count = sum(1 for c in closes if c > vwap)
    bearish_count = sum(1 for c in closes if c < vwap)
    
    # Need at least 2 out of last closes
    if bullish_count >= 2:
        return "BULLISH"
    elif bearish_count >= 2:
        return "BEARISH"
    return "NEUTRAL"


def is_compression_bar(bar: dict, recent_bars: list) -> bool:
    """
    Check if current bar shows compression (RELAXED):
    - max(range) < mean(range) * 1.3
    - last_volume < mean(volume) * 1.2
    """
    if len(recent_bars) < 1:
        return False
    
    ranges = [b["h"] - b["l"] for b in recent_bars]
    volumes = [b["v"] for b in recent_bars]
    
    current_range = bar["h"] - bar["l"]
    current_volume = bar["v"]
    
    avg_range = mean(ranges)
    avg_volume = mean(volumes)
    
    # RELAXED: allow more variance
    return (
        max(ranges + [current_range]) < avg_range * RANGE_SHRINK_FACTOR and
        current_volume < avg_volume * 1.2
    )


def is_expansion_bar(bar: dict, recent_bars: list) -> bool:
    """
    Check if current bar shows expansion:
    - Current range ≥ 1.8 × average range (last 5)
    - Current volume ≥ 1.5 × average volume (last 5)
    """
    if len(recent_bars) < 2:
        return False
    
    avg_range = mean([b["h"] - b["l"] for b in recent_bars])
    avg_volume = mean([b["v"] for b in recent_bars])
    
    current_range = bar["h"] - bar["l"]
    current_volume = bar["v"]
    
    return (
        current_range >= RANGE_EXPAND_FACTOR * avg_range and
        current_volume >= VOLUME_EXPAND_FACTOR * avg_volume
    )


def get_close_position(bar: dict) -> str:
    """
    Determine if close is near high or low
    
    Returns: "HIGH", "LOW", or "MID"
    """
    h = bar["h"]
    l = bar["l"]
    c = bar["c"]
    candle_range = h - l
    
    if candle_range < 0.001:  # Doji/no range
        return "MID"
    
    top_threshold = h - CLOSE_EDGE_PERCENT * candle_range
    bot_threshold = l + CLOSE_EDGE_PERCENT * candle_range
    
    if c >= top_threshold:
        return "HIGH"
    elif c <= bot_threshold:
        return "LOW"
    return "MID"


def should_enter(bar: dict, state: SymbolState, bias: str) -> str | None:
    """
    Entry conditions:
    - Not in neutral bias
    - Currently in COMPRESSION state
    - Bar shows expansion
    - Close position matches bias
    
    Returns: "LONG", "SHORT", or None
    """
    if bias == "NEUTRAL":
        return None
    
    if state.state != "COMPRESSION":
        return None
    
    if not is_expansion_bar(bar, list(state.bars_5)):
        return None
    
    close_pos = get_close_position(bar)
    
    if bias == "BULLISH" and close_pos == "HIGH":
        return "LONG"
    elif bias == "BEARISH" and close_pos == "LOW":
        return "SHORT"
    
    return None


def setup_trade(direction: str, bar: dict) -> tuple:
    """
    Setup entry/stop/target
    
    LONG:
      Stop = candle low
      Target = entry + (1.5 × range)
    
    SHORT:
      Stop = candle high
      Target = entry - (1.5 × range)
    """
    entry = bar["c"]
    candle_range = bar["h"] - bar["l"]
    
    if direction == "LONG":
        stop = bar["l"]
        target = entry + TARGET_RR * candle_range
    else:  # SHORT
        stop = bar["h"]
        target = entry - TARGET_RR * candle_range
    
    return entry, stop, target


def should_exit(bar: dict, state: SymbolState) -> str | None:
    """
    Exit conditions:
    1. Stop breached
    2. Target reached
    3. 15 seconds + unprofitable
    
    Returns: "STOP", "TARGET", "TIME_EXIT", or None
    """
    if state.current_position is None:
        return None
    
    now_ms = bar["e"]
    entry_ms = state.entry_time
    elapsed_ms = now_ms - entry_ms
    
    if state.current_position == "LONG":
        # Stop check
        if bar["l"] <= state.stop_price:
            return "STOP"
        # Target check
        if bar["h"] >= state.target_price:
            return "TARGET"
        # Time exit (≥15s AND unprofitable)
        if elapsed_ms >= TIME_EXIT_SECONDS * 1000:
            if bar["c"] <= state.entry_price:
                return "TIME_EXIT"
    
    elif state.current_position == "SHORT":
        # Stop check
        if bar["h"] >= state.stop_price:
            return "STOP"
        # Target check
        if bar["l"] <= state.target_price:
            return "TARGET"
        # Time exit (≥15s AND unprofitable)
        if elapsed_ms >= TIME_EXIT_SECONDS * 1000:
            if bar["c"] >= state.entry_price:
                return "TIME_EXIT"
    
    return None


# ======================
# MAIN BAR HANDLER
# ======================

async def handle_bar(bar: dict):
    """
    Main strategy logic for each incoming bar
    """
    symbol = bar.get("sym")
    if symbol not in states:
        return
    
    # Session filter
    if not is_regular_session(bar["s"]):
        return
    
    state = states[symbol]
    
    # Buffer the bar
    state.bars_5.append(bar)
    state.bars_10.append(bar)
    state.bars_30.append(bar)
    
    # Need minimum bars to evaluate
    if len(state.bars_10) < 5:
        return
    
    # =========== STATE MACHINE ===========
    
    # Get current conditions
    bias = get_vwap_bias(bar, list(state.bars_10))
    compression = is_compression_bar(bar, list(state.bars_10))
    
    # --- IDLE STATE ---
    if state.state == "IDLE":
        # Transition to COMPRESSION if compression detected
        if compression:
            state.state = "COMPRESSION"
            state.compression_bar_count = 1
        return
    
    # --- COMPRESSION STATE ---
    elif state.state == "COMPRESSION":
        if compression:
            state.compression_bar_count += 1
            
            # Check for entry if we have enough compression bars
            if state.compression_bar_count >= MIN_COMPRESSION_BARS:
                direction = should_enter(bar, state, bias)
                if direction:
                    entry, stop, target = setup_trade(direction, bar)
                    state.current_position = direction
                    state.entry_price = entry
                    state.stop_price = stop
                    state.target_price = target
                    state.entry_time = bar["e"]
                    state.state = "IN_TRADE"
                    
                    log_trade(
                        "ENTER",
                        symbol,
                        f"DIR={direction}",
                        f"PRICE={entry:.4f}",
                        f"STOP={stop:.4f}",
                        f"TGT={target:.4f}"
                    )
        else:
            # Compression broken, back to IDLE
            state.reset_compression()
        return
    
    # --- IN_TRADE STATE ---
    elif state.state == "IN_TRADE":
        exit_reason = should_exit(bar, state)
        if exit_reason:
            exit_price = bar["c"]
            pnl = "N/A"
            
            if state.current_position == "LONG":
                pnl = f"+{(exit_price - state.entry_price):.4f}" if exit_price > state.entry_price else f"{(exit_price - state.entry_price):.4f}"
            else:
                pnl = f"+{(state.entry_price - exit_price):.4f}" if exit_price < state.entry_price else f"{(state.entry_price - exit_price):.4f}"
            
            log_trade(
                "EXIT",
                symbol,
                f"REASON={exit_reason}",
                f"PRICE={exit_price:.4f}",
                f"PNL={pnl}"
            )
            
            state.reset_trade()


# ======================
# WEBSOCKET HANDLER
# ======================

async def websocket_loop():
    """
    Connect to Polygon WebSocket and handle messages
    """
    try:
        async with websockets.connect(WS_URL) as ws:
            log_trade("INFO", "BOT", "Connected to Polygon WebSocket")
            
            # Subscribe to symbols
            for symbol in SYMBOLS:
                sub_msg = {
                    "action": "subscribe",
                    "params": f"A.{symbol}"
                }
                await ws.send(json.dumps(sub_msg))
                log_trade("INFO", "BOT", f"Subscribed to {symbol}")
            
            # Main message loop
            async for message in ws:
                try:
                    data = json.loads(message)
                    
                    # Handle both single objects and arrays from Polygon
                    events = data if isinstance(data, list) else [data]
                    
                    for event in events:
                        # Only process aggregate events
                        if event.get("ev") != "A":
                            continue
                        
                        # Handle the bar
                        await handle_bar(event)
                
                except json.JSONDecodeError:
                    log_trade("ERROR", "BOT", f"Invalid JSON: {message}")
                except Exception as e:
                    log_trade("ERROR", "BOT", f"Error processing message: {e}")
    
    except websockets.exceptions.WebSocketException as e:
        log_trade("ERROR", "BOT", f"WebSocket error: {e}")
    except KeyboardInterrupt:
        log_trade("INFO", "BOT", "Shutting down...")
    except Exception as e:
        log_trade("ERROR", "BOT", f"Unexpected error: {e}")


# ======================
# ENTRY POINT
# ======================

if __name__ == "__main__":
    if not POLYGON_API_KEY:
        print("ERROR: POLYGON_API_KEY not set in environment")
        exit(1)
    
    print(f"Starting bot for symbols: {', '.join(SYMBOLS)}")
    print(f"Trading session: 09:30-16:00 ET")
    print(f"Compression threshold: ≥{MIN_COMPRESSION_BARS} bars")
    print()
    
    asyncio.run(websocket_loop())
