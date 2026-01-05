import os
from pathlib import Path


def load_env_from_file(path: str = ".env") -> None:
    """Load simple KEY=VALUE lines from a .env file if not already in os.environ."""
    env_path = Path(path)
    if not env_path.exists():
        return
    try:
        with env_path.open("r", encoding="utf-8") as f:
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
    except Exception:
        # Env loading is best-effort; swallow errors to avoid breaking runtime
        pass


# Load environment before reading values
load_env_from_file()

# Shared symbol(s) (UI/server/bot) - supports both single and multi-symbol
SYMBOL = os.getenv("SYMBOL", "AAPL")  # Fallback for legacy single-symbol
SYMBOLS_ENV = os.getenv("SYMBOLS", "AAPL,MSFT,GOOGL,TSLA")
# Parse symbols and strip comments/whitespace
SYMBOLS = [s.strip().upper().split('#')[0].strip() for s in SYMBOLS_ENV.split(",") if s.strip() and not s.strip().startswith('#')]

# Trading mode configuration
# Allow short positions by default so the strategy can trade both sides unless explicitly disabled via env.
ALLOW_SELL_POSITIONS = os.getenv("ALLOW_SELL_POSITIONS", "true").lower() in ("true", "1", "yes", "on")

# Range-based strategy parameters (from .env)
RANGE_LOOKBACK_MAX_MINUTES = int(os.getenv("RANGE_LOOKBACK_MAX_MINUTES", "120"))  # 2-hour max for bigger ranges
RANGE_LOOKBACK_MIN_MINUTES = int(os.getenv("RANGE_LOOKBACK_MIN_MINUTES", "30"))  # 30-min min (avoid micro-ranges)
RANGE_ENTRY_ZONE_PCT = float(os.getenv("RANGE_ENTRY_ZONE_PCT", "0.10"))
RANGE_EXIT_ZONE_PCT = float(os.getenv("RANGE_EXIT_ZONE_PCT", "0.90"))
FETCH_INTERVAL_SECONDS = int(os.getenv("FETCH_INTERVAL", "1"))

# Opening range strategy - FIXED window from session start (configurable for testing)
OPENING_RANGE_MINUTES = int(os.getenv("OPENING_RANGE_MINUTES", "5"))  # 5 min for testing, 30 min for production
RANGE_VALID_DURATION_MINUTES = int(os.getenv("RANGE_VALID_DURATION_MINUTES", "15"))  # How long locked range stays valid (minutes)
USE_OPENING_RANGE = os.getenv("USE_OPENING_RANGE", "true").lower() in ("true", "1", "yes", "on")

# Convert minutes to ticks (1 tick = FETCH_INTERVAL seconds)
RANGE_LOOKBACK_MAX_TICKS = int(RANGE_LOOKBACK_MAX_MINUTES * 60 / FETCH_INTERVAL_SECONDS)
RANGE_LOOKBACK_MIN_TICKS = int(RANGE_LOOKBACK_MIN_MINUTES * 60 / FETCH_INTERVAL_SECONDS)
OPENING_RANGE_TICKS = int(OPENING_RANGE_MINUTES * 60 / FETCH_INTERVAL_SECONDS)

# Parse time-decay exits from .env
def parse_time_decay_exits(env_str: str) -> list:
    """
    Parse TIME_DECAY_EXITS from .env format: "15:3,30:2,45:1,60:0.5"
    Returns: [{"minutes": 15, "profit_pct": 0.03}, {"minutes": 30, "profit_pct": 0.02}, ...]
    """
    if not env_str:
        return []
    
    try:
        tiers = []
        for pair in env_str.split(","):
            pair = pair.strip()
            if ":" not in pair:
                continue
            minutes_str, profit_str = pair.split(":", 1)
            minutes = int(minutes_str.strip())
            profit_pct = float(profit_str.strip()) / 100  # Convert from 3 to 0.03
            tiers.append({"minutes": minutes, "profit_pct": profit_pct})
        return sorted(tiers, key=lambda x: x["minutes"])
    except Exception as e:
        print(f"Warning: Failed to parse TIME_DECAY_EXITS: {e}")
        return []

TIME_DECAY_EXITS_CONFIG = parse_time_decay_exits(os.getenv("TIME_DECAY_EXITS", "15:3,30:2,45:1,60:0.5"))

# Entry Confirmation Configuration - Smart Entry with Support Bounce Confirmation
ENTRY_CONFIRMATION_ENABLED = os.getenv("ENTRY_CONFIRMATION_ENABLED", "true").lower() == "true"
ENTRY_CONFIDENCE_THRESHOLD = float(os.getenv("ENTRY_CONFIDENCE_THRESHOLD", "0.65"))
ENTRY_LOW_CONFIDENCE_THRESHOLD = float(os.getenv("ENTRY_LOW_CONFIDENCE_THRESHOLD", "0.50"))
ENTRY_BOUNCE_THRESHOLD = float(os.getenv("ENTRY_BOUNCE_THRESHOLD", "0.005"))
ENTRY_BOUNCE_TIMEOUT_TICKS = int(os.getenv("ENTRY_BOUNCE_TIMEOUT_TICKS", "20"))
ENTRY_CONFIRMATION_TICKS_MIN = int(os.getenv("ENTRY_CONFIRMATION_TICKS_MIN", "3"))
ENTRY_CONFIRMATION_TICKS_MAX = int(os.getenv("ENTRY_CONFIRMATION_TICKS_MAX", "5"))

# Strategy Configuration - TREND TRADING (1-2 hour timeframe)
STRATEGY_CONFIG = {
    # Warmup
    "warmup_ticks": RANGE_LOOKBACK_MIN_TICKS,  # Warmup = min lookback period
    
    # Opening range strategy (fixed window from session start)
    "use_opening_range": USE_OPENING_RANGE,  # Use fixed opening range instead of rolling range
    "opening_range_ticks": OPENING_RANGE_TICKS,  # Number of ticks for opening range (5 min test, 30 min prod)
    "opening_range_validity_minutes": RANGE_VALID_DURATION_MINUTES,  # How long locked range stays valid
    "use_volume_aware_range": True,  # NEW: Calculate range using volume-aware bear/bull zone logic (default: False for backward compat)
    
    # Range-based entry/exit thresholds
    "range_lookback_max_ticks": RANGE_LOOKBACK_MAX_TICKS,  # 1-hour max (3600 ticks at 1sec interval)
    "range_lookback_min_ticks": RANGE_LOOKBACK_MIN_TICKS,  # 5-minute min (300 ticks at 1sec interval)
    "range_entry_zone_pct": RANGE_ENTRY_ZONE_PCT,  # Bottom 10% = buy zone
    "range_exit_zone_pct": 0.90,    # Top 10% = sell zone (position_in_range >= 0.90 means top 10%)

    # Exit buffering
    "crossover_buffer_ticks": 3,  # Require EMA20 to stay away from EMA50 for N ticks before exiting

    # Entry confirmation system
    "entry_confirmation_enabled": ENTRY_CONFIRMATION_ENABLED,
    "entry_confidence_threshold": ENTRY_CONFIDENCE_THRESHOLD,
    "entry_low_confidence_threshold": ENTRY_LOW_CONFIDENCE_THRESHOLD,
    "entry_bounce_threshold": ENTRY_BOUNCE_THRESHOLD,
    "entry_bounce_timeout_ticks": ENTRY_BOUNCE_TIMEOUT_TICKS,
    "entry_confirmation_ticks_min": ENTRY_CONFIRMATION_TICKS_MIN,
    "entry_confirmation_ticks_max": ENTRY_CONFIRMATION_TICKS_MAX,
    "use_volume_enhanced_entry": True,  # NEW: Enable volume + price direction analysis for entry (default: False for backward compat)
    "volume_accumulation_ratio": 1.5,  # NEW: Volume ratio > this = accumulation signal (1.5x average)

    # Entry confirmation
    "entry_momentum_threshold": 0.0008,  # Require 0.08% price move in favorable direction to confirm entry (very loose)
    "entry_reversal_lookback_ticks": 5,  # Require prior down/up drift before reversal (shorter lookback window)
    "entry_reversal_drop_pct": 0.001,  # Require at least -0.1% drop (for LONG) or +0.1% rise (for SHORT) before reversal (very loose)

    # Bar aggregation for trend detection
    "bar_interval_seconds": 60,  # 1-minute bars (60 seconds)
    
    # Window for tick buffer: must hold the full max lookback range
    "window_size": RANGE_LOOKBACK_MAX_TICKS,
    
    # Trend entry thresholds
    "min_bars_trend_continuation": 3,  # Bars trend must persist before continuation entry
    "min_trend_strength_pct": 0.001,  # 0.1% EMA separation required for trend strength
    
    # Exit thresholds - WIDER for trend trading
    "profit_target": 0.05,  # 5% profit target (optional, trends can run further)
    "stop_loss": None,  # Disable hard stop loss entirely
    "max_adverse_excursion_pct": None,  # Disabled - no MAE exit
    "trend_exit_wiggle_pct": 0.003,  # 0.3% wiggle room before trend exit
    
    # Trailing stop for trend trading
    "trailing_stop_activate_pct": 0.03,  # Activate trail only after 3% run-up
    "trailing_stop_distance_pct": 0.03,  # Require 3% giveback from best before closing
    
    # Time-decay exits: gradually lower profit thresholds as time passes
    # Unlocks capital from stalled trades (e.g., 15:3,30:2,45:1,60:0.5 = 3% at 15min, 2% at 30min, etc)
    "time_decay_exits": TIME_DECAY_EXITS_CONFIG,
    
    # Trend continuation parameters
    "trend_sl_buffer": 1.5,  # Widen SL by 1.5x if trend is strong

    # EMA neutral band: treat fast/slow as equal within this pct of slow EMA
    "ema_neutral_band_pct": 0.0012,  # 0.12% band; tighter to trigger more crossovers
    
    # Legacy parameters (kept for compatibility)
    "entry_threshold": 0.00012,
    "volume_spike_multiplier": 0.3,
    "volatility_guard_threshold": 0.0015,
    "min_direction_streak": 3,
    "time_stop_seconds": 10,
    "flat_seconds": 8,
    "enforce_trend_alignment": True,
    "trend_lookback_seconds": 30,
}

# Risk Management Configuration - PRODUCTION GRADE (Rule 5.x)
RISK_CONFIG = {
    "max_open_positions": 3,  # Allow up to 3 simultaneous trades
    "cash_reserve_per_position_pct": 1.0,  # Strategy A: 100% / max_positions (even split, conservative)
    # Alternative strategies:
    # - 0.5: Strategy B (50% reserve per position, keep 50% unallocated)
    # - 0.33: Strategy C (33% reserve per position, keep 67% unallocated)
    "daily_loss_limit": -0.05,  # Stop trading if down 5% for the day (Rule 5.3)
    "cooldown_trades_after_loss": 3,  # Pause after 3 losses (Rule 5.4)
    "cooldown_seconds": 90,  # 90 second cooldown (Rule 5.4)
    "position_size": 75.0,  # Default/fallback fixed size (shares)
    "risk_per_trade_pct": 0.005,  # Risk 0.5% of equity per trade
    "min_position_size": 1,  # Floor to at least 1 share
    "max_leverage": 5.0,  # Max effective leverage: 5× (Rule 5.2)
    "max_trades_per_hour": 60,  # Allow up to 60 trades per hour for backtests (was 15)
    "max_position_notional": 5000.0,  # Cap dollars allocated per trade when stop loss is disabled
    "use_trading212_mock": os.getenv("MOCK_PORTFOLIO", "true").lower() in ("true", "1", "yes", "on"),
    "mock_portfolio_available_cash": float(os.getenv("MOCK_PORTFOLIO_CASH", "5000")),
}

# WebSocket Configuration
WEBSOCKET_CONFIG = {
    "uri": "ws://localhost:8765",
    "reconnect_delay": 3,  # seconds
}

# Logging Configuration
LOG_CONFIG = {
    "log_file": "logs/trading_bot.log",  # Updated to store logs in the logs directory
    "level": "DEBUG",
}
