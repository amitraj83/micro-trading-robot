# ═══════════════════════════════════════════════════════════════════════════════════
# TREND-CAPTURE BOT RULES: EMA50/EMA20 + ATR-based Risk Management (FLEXIBLE VERSION)
# ═══════════════════════════════════════════════════════════════════════════════════
# Strategy: Identify trending moves, enter on pullbacks OR momentum breakouts,
# use ATR-based stops and 2× ATR trailing take-profit with relaxed confirmations
# ═══════════════════════════════════════════════════════════════════════════════════

PROFESSIONAL_RULES = {
    # ═════════════════════════════════════════════════════════════════════════════
    # 1️⃣ TREND DETECTION RULES
    # ═════════════════════════════════════════════════════════════════════════════
    "rule_1_ema_trend_detection": {
        "enabled": True,
        "description": "Identify trend using EMA50 (primary) and EMA20 (confirmation)",
        "ema_50_period": 50,
        "ema_20_period": 20,
        "uptrend_condition": "price > ema_50",
        "downtrend_condition": "price < ema_50",
        "fast_confirm": "price > ema_20 for uptrend, price < ema_20 for downtrend (optional)",
        "trend_strength_ema_distance_min_pct": 0.0,  # RELAXED: No minimum distance requirement
    },

    "rule_2_atr_volatility_measure": {
        "enabled": True,
        "description": "Calculate ATR for position sizing, stops, and TP scaling",
        "atr_period": 14,
        "atr_multiplier_stop_loss": 1.0,     # SL = 1× ATR from entry
        "atr_multiplier_take_profit": 2.0,   # TP = 2× ATR from entry (risk:reward 1:2)
        "min_atr_threshold_pct": 0.0,        # RELAXED: No minimum ATR - allow all volatility levels
    },

    # ═════════════════════════════════════════════════════════════════════════════
    # 2️⃣ ENTRY RULES
    # ═════════════════════════════════════════════════════════════════════════════
    "rule_3_pullback_entry": {
        "enabled": True,
        "description": "Enter on minor pullback (30-50%) OR momentum breakout beyond last swing",
        "pullback_optional": True,            # RELAXED: Pullback is now optional
        "pullback_min_pct": 0.30,              # Min 30% retracement if pullback occurs
        "pullback_max_pct": 0.50,              # Max 50% retracement if pullback occurs
        "lookback_bars_for_swing": 5,          # Bars to identify swing high/low
        "allow_momentum_breakout": True,       # Allow entry on momentum breakout beyond swing (no pullback needed)
        "uptrend_pullback": "last_low >= swing_low - (swing_high - swing_low) * 0.5 OR price > swing_high with momentum",
        "downtrend_pullback": "last_high <= swing_high + (swing_high - swing_low) * 0.5 OR price < swing_low with momentum",
    },

    "rule_4_momentum_confirmation": {
        "enabled": True,
        "description": "Price momentum ≥ 0.1% over last 1-3 ticks (PRIMARY entry trigger)",
        "min_momentum_pct": 0.001,              # 0.1% minimum momentum
        "momentum_lookback_ticks": 3,           # Check last 1-3 ticks
        "momentum_direction_matches_trend": True,
        "momentum_is_primary_trigger": True,    # RELAXED: Momentum alone can trigger entry if trend confirmed
    },

    "rule_5_volume_confirmation": {
        "enabled": True,
        "description": "Current volume ≥ 50-70% of recent average (optional for strong momentum)",
        "min_volume_pct_of_avg": 0.50,          # RELAXED: 50% threshold (down from 70%)
        "volume_lookback_bars": 20,             # Last N bars for average
        "volume_confirmation_optional": True,  # Optional if momentum is strong (≥0.2%)
    },

    "rule_6_avoid_choppy_zones": {
        "enabled": False,                       # RELAXED: Disabled - allow all volatility levels
        "description": "Skip entries during choppy/low volatility zones (DISABLED)",
        "min_atr_pct_threshold": 0.0,           # N/A
        "require_atr_expansion": False,
    },

    # ═════════════════════════════════════════════════════════════════════════════
    # 3️⃣ EXIT RULES (Critical)
    # ═════════════════════════════════════════════════════════════════════════════
    "rule_7_trend_reversal_exit": {
        "enabled": True,
        "description": "Exit when trend reverses: price closes below EMA50 (uptrend) or above (downtrend)",
        "uptrend_exit_condition": "price <= ema_50",
        "downtrend_exit_condition": "price >= ema_50",
        "require_close_confirmation": True,
    },

    "rule_8_atr_stop_loss": {
        "enabled": True,
        "description": "ATR-based stop-loss: 1× ATR below/above entry",
        "stop_loss_atr_multiplier": 1.0,
        "hard_stop_loss": True,
        "never_move_sl_against_position": True,
    },

    "rule_9_trailing_take_profit": {
        "enabled": True,
        "description": "Trailing TP at 2× ATR or trail with EMA20",
        "initial_tp_atr_multiplier": 2.0,      # Start at 2× ATR
        "trail_with_ema20": True,              # Trail profit using EMA20 as dynamic support
        "ema20_trailing_offset_pct": 0.0005,   # 0.05% below EMA20 for long
    },

    "rule_10_quick_loss_exit": {
        "enabled": True,
        "description": "Exit if no profit within 10-15 seconds of entry (increased buffer)",
        "max_seconds_without_profit": 15,       # RELAXED: Increased from 5 to 15 seconds
        "exit_if_below_breakeven_after_s": True,
        "exit_before_sl_if_no_movement": True,
    },

    # ═════════════════════════════════════════════════════════════════════════════
    # 4️⃣ RISK MANAGEMENT
    # ═════════════════════════════════════════════════════════════════════════════
    "rule_11_position_sizing": {
        "enabled": True,
        "description": "Fixed % of capital per trade, respecting ATR",
        "risk_per_trade_pct": 0.01,             # Risk 1% of capital per trade
        "position_size": 100.0,                 # Share count (will scale with ATR)
        "max_leverage": 5.0,
        "min_position_size": 1.0,
    },

    "rule_12_max_concurrent_trades": {
        "enabled": True,
        "description": "Max 1 open trade per symbol, global throttle 5 min",
        "max_trades_per_symbol": 1,
        "global_trades_limit": 1,
        "trade_cooldown_seconds": 300,          # 5 minute cooldown between trades
    },

    "rule_13_daily_kill_switch": {
        "enabled": True,
        "description": "Stop trading if daily loss ≤ -5%",
        "daily_loss_limit_pct": -0.05,
        "halt_on_kill_switch": True,
    },

    "rule_14_consecutive_loss_pause": {
        "enabled": True,
        "description": "3 consecutive losses → pause 120 seconds",
        "consecutive_losses_threshold": 3,
        "pause_seconds": 120,
        "reset_on_win": True,
    },

    # ═════════════════════════════════════════════════════════════════════════════
    # 5️⃣ LOGGING & DIAGNOSTICS
    # ═════════════════════════════════════════════════════════════════════════════
    "rule_15_comprehensive_logging": {
        "enabled": True,
        "description": "Log all ticks with trend, momentum, volume, entry type, and PnL",
        "log_format": "[tick #] timestamp | $price | Vol: volume | ⚪ LONG/SHORT | OPEN/CLOSED | Trades: X | PnL: ±X.XX",
        "log_details": "Trend: UP/DOWN | Momentum: X.XX% | EMA50: $X.XX | EMA20: $X.XX | ATR: $X.XX | Volume OK: Yes/No",
        "track_entry_reason": True,
        "track_exit_reason": True,
        "track_pnl": True,
        "track_time_in_trade": True,
        "track_atr_measurements": True,
        "track_ema_values": True,
    },

    # ═════════════════════════════════════════════════════════════════════════════
    # CONFIRMATION LOGIC (RELAXED / FLEXIBLE)
    # ═════════════════════════════════════════════════════════════════════════════
    "confirmation_logic": {
        "description": "Flexible entry confirmation - not all conditions required simultaneously",
        "entry_triggers": [
            "TREND (Price > EMA50 for UP, < EMA50 for DOWN) + MOMENTUM (≥0.1%)",
            "TREND + VOLUME (≥50% of avg)",
            "TREND + MOMENTUM (≥0.2%) [strong move - volume optional]",
        ],
        "required_minimum": "At least TREND + ONE of (MOMENTUM or VOLUME)",
        "pullback_optional": True,
        "ema20_confirmation": "Optional but preferred for added confirmation",
    },

    # ═════════════════════════════════════════════════════════════════════════════
    # PRIORITY ORDER (Execution sequence - no lower rule overrides higher)
    # ═════════════════════════════════════════════════════════════════════════════
    "rule_priority": [
        # 1. RISK & SURVIVAL (First check)
        "rule_13_daily_kill_switch",
        "rule_14_consecutive_loss_pause",
        "rule_12_max_concurrent_trades",
        "rule_11_position_sizing",

        # 2. EXIT & RISK (Most critical - exits always checked)
        "rule_8_atr_stop_loss",
        "rule_10_quick_loss_exit",
        "rule_7_trend_reversal_exit",
        "rule_9_trailing_take_profit",

        # 3. TREND & MARKET CONTEXT
        "rule_1_ema_trend_detection",
        "rule_2_atr_volatility_measure",
        "rule_6_avoid_choppy_zones",

        # 4. ENTRY CONDITIONS (Only checked when trend + risk rules pass)
        "rule_3_pullback_entry",
        "rule_4_momentum_confirmation",
        "rule_5_volume_confirmation",

        # 5. LOGGING & ANALYSIS (Last - after all decisions made)
        "rule_15_comprehensive_logging",
    ],
}
