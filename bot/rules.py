# Professional Trading Rules Engine - NEW PRIORITY STACK
# RULE PRIORITY (ENFORCED ORDER):
# 1. Risk & Kill Switch
# 2. Exit Rules
# 3. Market & Regime Filters
# 4. Trend & Bias Rules
# 5. Entry Rules
# 6. Operational / Analytics
# No lower-priority rule may override a higher one.

PROFESSIONAL_RULES = {
    # ============================================================================
    # 1️⃣ MARKET, REGIME & VOLATILITY RULES (Decide IF trading is allowed)
    # ============================================================================
    "rule_1_1_volatility_gate": {
        "enabled": True,
        "description": "Volatility Gate - Trade ONLY if ALL conditions are true",
        "min_range_30s_pct": 0.002,  # 0.20% minimum range in 30s
        "min_range_10s_pct": 0.0015,  # 0.15% minimum movement in 10s
        "window_seconds_long": 30,
        "window_seconds_short": 10,
    },

    "rule_1_2_liquidity_spread_filter": {
        "enabled": True,
        "description": "Spread ≤ 50% of TP, cancel if spread widens",
        "max_spread_vs_profit": 0.5,
    },

    "rule_1_3_session_rule": {
        "enabled": True,
        "description": "Trade only during regular session; flat by 4 PM; no overnight holds",
        "session_end_time": "16:00",
        "no_overnight_holds": True,
    },

    "rule_1_4_market_regime_detection": {
        "enabled": True,
        "description": "Detect regime from last 5 one-minute candles; disable momentum in ranges",
        "lookback_candles": 5,
        "trending_hh_hl": True,
        "trending_lh_ll": True,
        "ranging_overlap": True,
        "flat_vwap": True,
        "disable_momentum_if_range": True,
    },

    # ============================================================================
    # 2️⃣ TREND, BIAS & CONTEXT RULES (Decide WHICH direction is allowed)
    # ============================================================================
    "rule_2_1_daily_bias_vwap": {
        "enabled": True,
        "description": "Bias from 1m VWAP and today change",
        "bullish_change_floor_pct": -0.003,  # >= -0.3%
        "bearish_change_cap_pct": 0.003,     # <= +0.3%
        "require_price_vs_vwap": True,
    },

    "rule_2_2_previous_day_levels": {
        "enabled": True,
        "description": "Prev day high/low/close context",
        "proximity_pct": 0.0015,  # ±0.15%
        "favor_shorts_near_high": True,
        "favor_longs_near_low": True,
        "allow_continuation_on_clean_break": True,
    },

    "rule_2_3_direction_confirmation": {
        "enabled": True,
        "description": "Direction confirmation for entry consideration",
        "min_consecutive_seconds": 3,
        "min_net_move_pct": 0.0008,
        "volume_spike_multiplier": 1.3,
    },

    "rule_2_4_trend_alignment": {
        "enabled": True,
        "description": "Trade only in bias direction; no counter-trend",
        "long_only_when_bias_up": True,
        "short_only_when_bias_down": True,
        "no_trade_when_unclear": True,
    },

    "rule_2_5_position_constraint": {
        "enabled": True,
        "description": "Max 1 open position; no same-direction stacking",
        "max_open_positions": 1,
    },

    # ============================================================================
    # 3️⃣ ENTRY RULES (Decide WHEN to enter)
    # ============================================================================
    "rule_3_1_momentum_quality_filter": {
        "enabled": True,
        "description": "Momentum strong and early",
        "min_momentum_strength_pct": 0.70,
        "max_entry_position_in_move": 0.30,
        "max_extended_move_pct": 0.012,
    },

    "rule_3_2_pullback_continuation": {
        "enabled": True,
        "description": "Trend → 2–3 tick pullback → continuation with volume spike",
        "min_pullback_ticks": 2,
        "max_pullback_ticks": 3,
        "require_volume_spike_on_continuation": True,
    },

    "rule_3_3_location_filter": {
        "enabled": True,
        "description": "Only enter at top/bottom 25% of 1m range",
        "top_quartile_long": True,
        "bottom_quartile_short": True,
    },

    "rule_3_4_vwap_interaction": {
        "enabled": True,
        "description": "VWAP as S/R; stretched ≥0.4% expects snapback",
        "stretch_threshold_pct": 0.004,
        "allow_counter_with_tight_tp": True,
    },

    # ============================================================================
    # 4️⃣ EXIT RULES (Most important)
    # ============================================================================
    "rule_4_1_fixed_asymmetric_rr": {
        "enabled": True,
        "description": "Fixed Asymmetric R:R",
        "tp_pct": 0.0008,
        "sl_pct": 0.0004,
        "risk_reward_ratio": 2.0,
    },

    "rule_4_2_smart_time_stop": {
        "enabled": True,
        "description": "Exit if not profitable quickly",
        "max_hold_seconds": 10,
        "exit_if_below_breakeven_after_s": 8,
        "exit_if_no_movement_seconds": 8,
    },

    "rule_4_3_momentum_failure_exit": {
        "enabled": True,
        "description": "Exit if momentum fails",
        "flat_ticks_threshold": 2,
        "momentum_reversal_pct": 0.30,
        "volume_collapse_threshold": 0.5,
    },

    "rule_4_4_early_profit_requirement": {
        "enabled": True,
        "description": "Trade must show profit within 2s or exit early",
        "max_seconds_to_show_profit": 2,
        "exit_before_sl_if_no_profit": True,
    },

    "rule_4_5_vwap_level_rejection_exit": {
        "enabled": True,
        "description": "Exit early if stall/reject at VWAP or prev-day level",
        "require_volume_confirmation": True,
    },

    # ============================================================================
    # 5️⃣ RISK MANAGEMENT RULES (Survival & scaling layer)
    # ============================================================================
    "rule_5_1_position_sizing": {
        "enabled": True,
        "description": "Position sizing and per-trade risk",
        "position_size": 75.0,
        "max_risk_pct": 0.0025,
        "account_size": 100.0,
    },

    "rule_5_2_leverage_cap": {
        "enabled": True,
        "description": "Max effective leverage",
        "max_leverage": 5.0,
    },

    "rule_5_3_daily_kill_switch": {
        "enabled": True,
        "description": "Stop trading if daily PnL ≤ -5%",
        "daily_loss_limit_pct": -0.05,
    },

    "rule_5_4_cooldown_rule": {
        "enabled": True,
        "description": "3 consecutive losses → pause 90s; reset on win",
        "consecutive_losses_threshold": 3,
        "cooldown_seconds": 90,
        "reset_on_win": True,
    },

    "rule_5_5_trade_frequency_limit": {
        "enabled": True,
        "description": "Max 15 trades per hour",
        "max_trades_per_hour": 15,
    },

    # ============================================================================
    # 6️⃣ OPERATIONAL & PERFORMANCE RULES
    # ============================================================================
    "rule_6_1_mandatory_logging": {
        "enabled": True,
        "description": "Log every trade with regime/bias context",
        "track_entry_exit_reason": True,
        "track_pnl": True,
        "track_slippage": True,
        "track_time_in_trade": True,
        "track_spread_at_entry": True,
        "track_hour_of_day": True,
        "track_regime": True,
        "track_bias": True,
    },

    "rule_6_2_performance_adaptation": {
        "enabled": True,
        "description": "Weekly adaptation: disable losing hours; tighten before loosening",
        "disable_negative_hours": True,
        "tighten_before_loosen": True,
    },

    # ============================================================================
    # PRIORITY ORDER (no lower rule may override a higher one)
    # ============================================================================
    "rule_priority": [
        # 1. Risk & Kill Switch
        "rule_5_3_daily_kill_switch",
        "rule_5_4_cooldown_rule",
        "rule_5_1_position_sizing",
        "rule_5_2_leverage_cap",
        "rule_5_5_trade_frequency_limit",

        # 2. Exit Rules
        "rule_4_4_early_profit_requirement",
        "rule_4_2_smart_time_stop",
        "rule_4_3_momentum_failure_exit",
        "rule_4_5_vwap_level_rejection_exit",
        "rule_4_1_fixed_asymmetric_rr",

        # 3. Market & Regime Filters
        "rule_1_1_volatility_gate",
        "rule_1_2_liquidity_spread_filter",
        "rule_1_3_session_rule",
        "rule_1_4_market_regime_detection",

        # 4. Trend & Bias Rules
        "rule_2_1_daily_bias_vwap",
        "rule_2_2_previous_day_levels",
        "rule_2_3_direction_confirmation",
        "rule_2_4_trend_alignment",
        "rule_2_5_position_constraint",

        # 5. Entry Rules
        "rule_3_1_momentum_quality_filter",
        "rule_3_2_pullback_continuation",
        "rule_3_3_location_filter",
        "rule_3_4_vwap_interaction",

        # 6. Operational / Analytics
        "rule_6_1_mandatory_logging",
        "rule_6_2_performance_adaptation",
    ],
}
