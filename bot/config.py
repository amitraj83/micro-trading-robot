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

# Strategy Configuration - PRODUCTION GRADE (ALIGNED WITH NEW RULES)
STRATEGY_CONFIG = {
    # Window for momentum detection (seconds of tick history)
    "window_size": 100,  # Need at least 50 for EMA50, padding for safety
    
    # Entry thresholds - STRICT (Rule 2.1)
    "entry_threshold": 0.00012,  # 0.012% price move required (ultra-relaxed for calm markets)
    "volume_spike_multiplier": 0.3,  # Volume must be 0.3x rolling average (ultra-relaxed for penny stocks)
    "volatility_guard_threshold": 0.0015,  # 0.15% price movement required (Rule 1.1)
    
    # Momentum confirmation - require direction streak (Rule 2.1)
    "min_direction_streak": 3,  # At least 3 consecutive moves in same direction (UPGRADED)
    
    # Exit thresholds - tuned to hold trends longer
    "profit_target": 0.0100,  # 1.00% profit target (wider to let winners run)
    "stop_loss": 0.0050,  # 0.50% stop loss (gives room for continuation wiggle)
    "trend_sl_buffer": 1.5,  # If trend is still strong, widen SL by this multiplier
    "time_stop_seconds": 10,  # Exit if not profitable within 10s (Rule 4.2)

    # Trailing stop to lock gains while allowing extension
    "trailing_stop_activate_pct": 0.0020,  # Start trailing after +0.20%
    "trailing_stop_distance_pct": 0.0010,  # Exit if giveback ≥0.10% from best run
    
    # Momentum staleness detection (Rule 4.2 & 4.3)
    "flat_seconds": 8,  # If no move for 8 seconds, exit (Rule 4.2)
    
    # Trend alignment (Rule 2.2 - CRITICAL NEW FEATURE)
    "enforce_trend_alignment": True,  # ONLY trade WITH the trend
    "trend_lookback_seconds": 30,  # Look back 30s to determine trend
}

# Risk Management Configuration - PRODUCTION GRADE (Rule 5.x)
RISK_CONFIG = {
    "max_open_positions": 1,  # Only 1 trade at a time (Rule 2.3)
    "daily_loss_limit": -0.05,  # Stop trading if down 5% for the day (Rule 5.3)
    "cooldown_trades_after_loss": 3,  # Pause after 3 losses (Rule 5.4)
    "cooldown_seconds": 90,  # 90 second cooldown (Rule 5.4)
    "position_size": 75.0,  # Default/fallback fixed size (shares)
    "risk_per_trade_pct": 0.005,  # Risk 0.5% of equity per trade
    "min_position_size": 1,  # Floor to at least 1 share
    "max_leverage": 5.0,  # Max effective leverage: 5× (Rule 5.2)
    "max_trades_per_hour": 15,  # Max 15 trades per hour (Rule 5.5)
}

# WebSocket Configuration
WEBSOCKET_CONFIG = {
    "uri": "ws://localhost:8765",
    "reconnect_delay": 3,  # seconds
}

# Logging Configuration
LOG_CONFIG = {
    "log_file": "logs/trading_bot.log",  # Updated to store logs in the logs directory
    "level": "INFO",
}
