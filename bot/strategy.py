from typing import Optional, Tuple
from datetime import datetime, timedelta
import os
import time
import requests
import time
import logging

# Support both direct module imports (cwd=root with bot on sys.path)
# and package imports (bot.strategy).
try:
    from models import Tick, Trade, StrategyMetrics
    from tick_buffer import TickBuffer
    from config import STRATEGY_CONFIG, RISK_CONFIG
    from rules import PROFESSIONAL_RULES
    from market_data import MockMarketDataProvider, DailyMarketData
except ImportError:  # Fallback when imported as part of the bot package
    from bot.models import Tick, Trade, StrategyMetrics
    from bot.tick_buffer import TickBuffer
    from bot.config import STRATEGY_CONFIG, RISK_CONFIG
    from bot.rules import PROFESSIONAL_RULES
    from bot.market_data import MockMarketDataProvider, DailyMarketData

logger = logging.getLogger(__name__)


class MicroTradingStrategy:
    """
    Trend-following strategy using bar-based EMA crossovers.
    
    For 1-2 hour trends, we use 1-minute bars with EMA20/EMA50:
    - EMA20 on 1-min bars = 20 minutes of trend data
    - EMA50 on 1-min bars = 50 minutes of trend data
    
    Entry: EMA20 crosses above EMA50 (Golden Cross) → LONG
           EMA20 crosses below EMA50 (Death Cross) → SHORT
    
    Exit: When opposite crossover occurs OR trailing stop hit
    """
    
    def __init__(self):
        # Per-symbol tick buffers (EMA/volatility on ticks, no bars)
        self.tick_buffers: dict = {}
        
        self.current_positions: dict = {}  # {symbol: Trade} - one position per symbol
        self.closed_trades: list = []
        self.metrics = StrategyMetrics()
        self.last_entry_time = None
        self.consecutive_losses_counter = 0
        self.cooldown_until = None  # Cooldown timer after losses
        self.rules_violated_log = []  # Track which rules are violated
        self.hourly_trade_count = 0
        self.hour_start_time = datetime.now()
        self.market_data_provider = MockMarketDataProvider()
        self.current_daily_data: Optional[DailyMarketData] = None

        # Portfolio cash cache (Trading212 or mock)
        self._cached_available_cash: Optional[float] = None
        self._cash_cache_ts: Optional[float] = None
        self._cash_cache_ttl = 30.0  # seconds
        
        # Track entry trend state for exit decisions
        # Track last EMA20>EMA50 state per symbol to detect crossovers
        self.prev_fast_above: dict = {}
        
        # Track consecutive ticks EMA20 has been below/above EMA50 (for buffered exits)
        self.crossover_buffer: dict = {}  # {symbol: tick_count}
        self.crossover_threshold = STRATEGY_CONFIG.get("crossover_buffer_ticks", 3)  # Require N ticks before exiting

        # Track previous range low per symbol (for entry detection before range updates)
        self.prev_range_low: dict = {}  # {symbol: previous_range_low}
        
        # Track entry zone to prevent multiple entries at same support level
        self.last_entry_zone: dict = {}  # {symbol: price_zone} to avoid re-triggering

        # Track opening range per symbol (for fixed window strategy)
        # Now includes two-phase system: BUILD (N min) -> LOCK (15 min validity)
        self.opening_range: dict = {}  # {symbol: {high, low, ticks, initialized, build_start_time, lock_time, validity_expires_at, position_locked}}
        self.opening_range_ticks = STRATEGY_CONFIG.get("opening_range_ticks", 300)  # 5 min default
        self.opening_range_validity_minutes = STRATEGY_CONFIG.get("opening_range_validity_minutes", 15)  # Range stays locked duration (configurable)
        self.use_opening_range = STRATEGY_CONFIG.get("use_opening_range", True)

        # Warmup requirement measured in ticks (not bars)
        self.warmup_ticks = STRATEGY_CONFIG.get("warmup_ticks", 50)

        # Log time-decay exit configuration on startup
        time_decay_exits = STRATEGY_CONFIG.get("time_decay_exits", [])
        if time_decay_exits:
            tiers_str = " | ".join([f"{t['minutes']}min→{t['profit_pct']*100:.1f}%" for t in sorted(time_decay_exits, key=lambda x: x["minutes"])])
            logger.info(f"⏰ TIME-DECAY EXIT STRATEGY ENABLED: {tiers_str}")
        else:
            logger.warning("⏰ TIME-DECAY EXIT STRATEGY DISABLED (no tiers configured)")

        # ===== ENTRY CONFIRMATION SYSTEM =====
        # Smart entry: Wait for post-touch confirmation before entering
        self.entry_confirmation_enabled = STRATEGY_CONFIG.get("entry_confirmation_enabled", True)
        self.entry_confidence_threshold = STRATEGY_CONFIG.get("entry_confidence_threshold", 0.65)
        self.entry_low_confidence_threshold = STRATEGY_CONFIG.get("entry_low_confidence_threshold", 0.50)
        self.entry_bounce_threshold = STRATEGY_CONFIG.get("entry_bounce_threshold", 0.005)
        self.entry_bounce_timeout_ticks = STRATEGY_CONFIG.get("entry_bounce_timeout_ticks", 20)
        self.entry_confirmation_ticks_min = STRATEGY_CONFIG.get("entry_confirmation_ticks_min", 3)
        self.entry_confirmation_ticks_max = STRATEGY_CONFIG.get("entry_confirmation_ticks_max", 5)
        
        # Track pending entries awaiting confirmation
        self.pending_entries: dict = {}  # {symbol: {touch_price, touch_time, touch_tick_idx, confidence, status, rejection_price, rejection_tick}}
        
        # Track confirmation buffers (ticks since support touch)
        self.confirmation_buffers: dict = {}  # {symbol: [prices after touch]}
        
        # Track volatility history for adaptive confirmation window
        self.volatility_history: dict = {}  # {symbol: [recent_pct_changes]}
        self.volatility_window = 20  # Track last N ticks for volatility calc
        
        # Track entry outcomes for adaptive recalibration (every 50 trades)
        self.entry_outcomes: list = []  # [{timestamp, symbol, confidence, entry_price, exit_price, pnl_pct, won}]
        self.adaptive_recalibration_interval = 50  # Recalibrate every N entries
        
        if self.entry_confirmation_enabled:
            logger.info(f"✅ ENTRY CONFIRMATION ENABLED: confidence_threshold={self.entry_confidence_threshold:.0%}, "
                       f"low_confidence_threshold={self.entry_low_confidence_threshold:.0%}, "
                       f"bounce_threshold={self.entry_bounce_threshold:.2%}, "
                       f"confirmation_window={self.entry_confirmation_ticks_min}-{self.entry_confirmation_ticks_max} ticks")
        else:
            logger.warning("⚠️  ENTRY CONFIRMATION DISABLED (immediate entry on signal)")


    def _compute_position_size(self, entry_price: float) -> Tuple[float, str]:
        """Dynamic position sizing: risk % of equity / (stop distance), capped by leverage, available cash, and multi-position allocation."""
        risk_pct = RISK_CONFIG.get("risk_per_trade_pct", 0)
        base_size = RISK_CONFIG.get("position_size", 1.0)
        min_size = max(RISK_CONFIG.get("min_position_size", 1), 1)
        stop_loss_pct = STRATEGY_CONFIG.get("stop_loss") or 0  # Handle None

        # Optional: cap by available cash from mock Trading212 portfolio (or live when integrated)
        use_mock_portfolio = RISK_CONFIG.get("use_trading212_mock")
        available_cash = RISK_CONFIG.get("mock_portfolio_available_cash") if use_mock_portfolio else self._get_portfolio_available_cash()

        # Max notional cap (works even when SL disabled)
        max_notional = RISK_CONFIG.get("max_position_notional", 0)

        # NEW: Multi-position cash reservation (Strategy A: Even Split)
        max_positions = RISK_CONFIG.get("max_open_positions", 1)
        cash_reserve_pct = RISK_CONFIG.get("cash_reserve_per_position_pct", 1.0)
        
        # Count currently open positions
        current_open = len(self.current_positions)
        
        # Calculate cash reserved for this position (even split among max positions)
        reserved_cash_for_position = None
        if available_cash and max_positions > 0:
            # Strategy A: Divide total available cash evenly among max positions
            # With cash_reserve_pct = 1.0: each position gets (available_cash / max_positions)
            reserved_cash_for_position = (available_cash / max_positions) * cash_reserve_pct
        
        # If misconfigured, fall back to fixed size with notional cap
        if risk_pct <= 0 or stop_loss_pct <= 0 or entry_price <= 0:
            shares = base_size
            if max_notional and entry_price > 0:
                cap_shares = int(max_notional / entry_price)
                shares = max(min_size, min(shares, cap_shares)) if cap_shares > 0 else min_size
            if reserved_cash_for_position and entry_price > 0:
                cash_cap_shares = int(reserved_cash_for_position / entry_price)
                shares = max(min_size, min(shares, cash_cap_shares)) if cash_cap_shares > 0 else min_size
            
            note = f"fixed sizing (position_size={base_size})"
            if max_positions > 1 and reserved_cash_for_position is not None:
                note += f" | multi-pos: {current_open}/{max_positions}, ${reserved_cash_for_position:.2f}/pos"
            return float(shares), note

        equity = 100.0 + self.metrics.total_pnl  # reference equity
        risk_dollars = equity * risk_pct
        per_share_risk = stop_loss_pct * entry_price

        if per_share_risk <= 0:
            return base_size, "fixed sizing (invalid per-share risk)"

        raw_shares = risk_dollars / per_share_risk
        shares = max(min_size, int(raw_shares))

        # Cap by max notional
        if max_notional and entry_price > 0:
            cap_shares = int(max_notional / entry_price)
            if cap_shares > 0:
                shares = max(min_size, min(shares, cap_shares))

        # Cap by reserved cash (multi-position allocation) instead of total cash
        if reserved_cash_for_position and entry_price > 0:
            cash_cap_shares = int(reserved_cash_for_position / entry_price)
            if cash_cap_shares > 0:
                shares = max(min_size, min(shares, cash_cap_shares))

        # Cap by leverage
        max_leverage = RISK_CONFIG.get("max_leverage", 0)
        leverage_note = ""
        if max_leverage and max_leverage > 0:
            max_leverage_shares = (equity * max_leverage) / entry_price
            if max_leverage_shares > 0:
                capped_shares = int(max_leverage_shares)
                if capped_shares < shares:
                    shares = max(min_size, capped_shares)
                    leverage_note = f", capped by {max_leverage}x leverage"

        note = (f"risk {risk_pct*100:.2f}% of ${equity:.2f}, stop {stop_loss_pct*100:.2f}%, "
                f"raw {raw_shares:.1f} -> size {shares}{leverage_note}")
        
        # Add multi-position allocation info
        if max_positions > 1 and reserved_cash_for_position is not None:
            note += f" | multi-pos: {current_open}/{max_positions} open, ${reserved_cash_for_position:.2f}/pos"
        
        if reserved_cash_for_position is not None:
            note += f", reserved cash cap ${reserved_cash_for_position:.2f}"
        if max_notional:
            note += f", notional cap ${max_notional:.0f}"
        return float(shares), note
    
    def check_rule_1_volatility(self, buf: TickBuffer) -> Tuple[bool, Optional[str]]:
        """RULE 1: Volatility filter - don't trade dead markets (per symbol)."""
        rule_cfg = PROFESSIONAL_RULES.get("rule_1_volatility_filter", {})
        if not rule_cfg.get("enabled", True):
            return True, None
        
        volatility = buf.calculate_volatility()
        min_threshold = rule_cfg.get("min_range_pct", 0.002)
        
        if volatility < min_threshold:
            rule_msg = f"RULE 1 VIOLATED: Volatility too low ({volatility*100:.3f}% < {min_threshold*100:.3f}%)"
            self.rules_violated_log.append(rule_msg)
            return False, rule_msg
        
        return True, None
    
    def check_rule_2_3_spread(self, entry_price: float, current_price: float) -> Tuple[bool, Optional[str]]:
        """RULE 2.3: Spread filter"""
        if not PROFESSIONAL_RULES["rule_2_3_spread_filter"]["enabled"]:
            return True, None
        
        tp_pct = PROFESSIONAL_RULES["rule_3_fixed_asymmetric_rr"]["tp_pct"]
        spread = abs(current_price - entry_price) / entry_price
        max_spread = tp_pct * PROFESSIONAL_RULES["rule_2_3_spread_filter"]["max_spread_vs_profit"]
        
        if spread > max_spread:
            rule_msg = f"RULE 2.3 VIOLATED: Spread ({spread*100:.3f}%) > max ({max_spread*100:.3f}%)"
            return False, rule_msg
        
        return True, None
    
    def calculate_volatility(self, symbol: str, buf: TickBuffer) -> float:
        """Calculate recent volatility as std dev of percentage changes.
        
        Returns volatility in range [0, 1] (0% to 100% moves per tick).
        """
        prices = buf.get_prices()
        if len(prices) < 2:
            return 0.01  # Assume minimal volatility if not enough data
        
        # Use recent N prices for volatility calculation
        lookback = min(len(prices), self.volatility_window)
        recent_prices = prices[-lookback:]
        
        # Calculate percentage changes
        pct_changes = []
        for i in range(1, len(recent_prices)):
            pct_change = abs((recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1])
            pct_changes.append(pct_change)
        
        if not pct_changes:
            return 0.01
        
        # Calculate std dev of pct changes
        avg_change = sum(pct_changes) / len(pct_changes)
        variance = sum((x - avg_change) ** 2 for x in pct_changes) / len(pct_changes)
        volatility = variance ** 0.5
        
        # Store for history tracking
        if symbol not in self.volatility_history:
            self.volatility_history[symbol] = []
        self.volatility_history[symbol].append(volatility)
        if len(self.volatility_history[symbol]) > self.volatility_window:
            self.volatility_history[symbol].pop(0)
        
        return volatility
    
    def calculate_adaptive_confirmation_window(self, symbol: str) -> int:
        """Calculate confirmation window size based on recent volatility.
        
        - Low volatility (<0.1%): 3 ticks (fast confirmation)
        - Medium volatility (0.1-0.3%): 4 ticks (normal)
        - High volatility (>0.3%): 5 ticks (safer confirmation)
        """
        volatility = self.calculate_volatility(symbol, self.tick_buffers.get(symbol))
        
        if volatility < 0.001:  # < 0.1%
            return self.entry_confirmation_ticks_min  # 3 ticks
        elif volatility < 0.003:  # 0.1-0.3%
            return (self.entry_confirmation_ticks_min + self.entry_confirmation_ticks_max) // 2  # 4 ticks
        else:  # > 0.3%
            return self.entry_confirmation_ticks_max  # 5 ticks
    
    def calculate_pre_touch_momentum_score(self, buf: TickBuffer) -> float:
        """Score the momentum of prices leading up to support touch.
        
        Returns: 0 = falling fast, 1 = falling slow/stable, 2 = rising
        """
        prices = buf.get_prices()
        if len(prices) < 5:
            return 1.0  # Neutral if not enough data
        
        # Analyze last 5 ticks velocity
        recent_5 = prices[-5:]
        velocity = (recent_5[-1] - recent_5[0]) / recent_5[0] if recent_5[0] > 0 else 0
        
        # Calculate magnitude of change
        magnitude = abs(velocity)
        
        if velocity >= 0:
            # Price stable or rising → Good, 2.0
            return 2.0
        elif magnitude < 0.001:  # < 0.1% falling
            # Falling slowly/steady → Good, 1.0
            return 1.0
        else:
            # Falling fast → Risky, 0.0
            return 0.0
    
    def calculate_support_strength_score(self, symbol: str, support_price: float) -> float:
        """Score how strong the support level is based on bounce history.
        
        Tracks how many times price bounced from this support recently.
        Returns: 0 = weak (first touch), 1 = medium (1-2 bounces), 2 = strong (3+ bounces), 3 = very strong (5+ bounces)
        """
        # Simple implementation: Count how many times we tested this support in recent history
        # This would require tracking support touches, which we'll simplify for now
        
        # For initial implementation, use opening range formation count
        if symbol in self.opening_range:
            or_data = self.opening_range[symbol]
            ticks_since_lock = or_data.get("ticks", 0)
            
            # More ticks = more mature range = stronger support
            if ticks_since_lock >= 100:
                return 3.0  # Very strong, range tested many times
            elif ticks_since_lock >= 60:
                return 2.0  # Strong, range well-formed
            elif ticks_since_lock >= 30:
                return 1.5  # Medium-strong
            else:
                return 1.0  # Weak/new support
        
        return 1.0  # Default to neutral
    
    def calculate_range_recency_score(self, symbol: str) -> float:
        """Score how fresh/recent the opening range is.
        
        Returns: 0 = stale (>10min old), 0.5 = older (5-10min), 1.0 = fresh (<5min)
        """
        if symbol not in self.opening_range:
            return 0.5  # Neutral if no range
        
        or_data = self.opening_range[symbol]
        lock_time = or_data.get("lock_time")
        
        if lock_time is None:
            return 0.5  # Still building or not initialized
        
        now = time.time()
        age_seconds = now - lock_time
        age_minutes = age_seconds / 60
        
        if age_minutes < 5:
            return 1.0  # Fresh
        elif age_minutes < 10:
            return 0.5  # Older
        else:
            return 0.0  # Stale
    
    def calculate_post_touch_reaction_score(self, symbol: str) -> float:
        """Score the reaction after support touch (measured by confirmation buffer).
        
        Analyzes the ticks that came after support touch:
        - Returns: 0 = majority DOWN, 1 = majority SIDEWAYS, 2 = majority UP
        """
        if symbol not in self.confirmation_buffers:
            return 1.0  # Neutral if not enough confirmation data yet
        
        buf = self.confirmation_buffers[symbol]
        if len(buf) < 2:
            return 1.0  # Not enough data yet
        
        # Compare touch price with recent prices to determine direction
        touch_price = buf[0]
        up_count = 0
        down_count = 0
        
        for price in buf[1:]:
            if price > touch_price + (touch_price * 0.0001):  # Up (account for rounding)
                up_count += 1
            elif price < touch_price - (touch_price * 0.0001):  # Down
                down_count += 1
            # else: sideways
        
        total = up_count + down_count
        if total == 0:
            return 1.0  # All sideways
        
        up_ratio = up_count / total
        
        if up_ratio >= 0.60:
            return 2.0  # Majority UP - strong bounce
        elif up_ratio >= 0.40:
            return 1.0  # Balanced/sideways
        else:
            return 0.0  # Majority DOWN - support failed
    
    def calculate_final_confidence(self, symbol: str, pre_touch_score: float, 
                                   support_strength_score: float, range_recency_score: float,
                                   post_touch_score: float) -> float:
        """Calculate final confidence score as weighted average.
        
        Weights:
        - pre_touch_momentum: 0.15
        - support_strength: 0.20
        - range_recency: 0.10
        - post_touch_reaction: 0.55 (most important!)
        
        Scores are normalized to 0-1 based on their max values:
        - pre_touch: max=2
        - support_strength: max=3
        - range_recency: max=1
        - post_touch: max=2
        """
        # Normalize scores to 0-1
        pre_touch_norm = pre_touch_score / 2.0
        support_strength_norm = support_strength_score / 3.0
        range_recency_norm = range_recency_score / 1.0
        post_touch_norm = post_touch_score / 2.0
        
        # Weighted average
        final = (
            0.15 * pre_touch_norm +
            0.20 * support_strength_norm +
            0.10 * range_recency_norm +
            0.55 * post_touch_norm
        )
        
        return min(final, 1.0)  # Cap at 1.0


    def check_entry_signals(self, symbol: str, buf: TickBuffer) -> Tuple[Optional[str], dict]:
        """Range-based entry: Trigger when price dips to/below PREVIOUS range_low.
        
        STRATEGY: Check previous range low BEFORE calculating new range. This captures
        entry opportunities before the range updates and moves the target away.
        
        Entry: Current price <= previous range_low → LONG
        
        Returns (entry_signal, calc_debug) for logging.
        """
        current_price = buf.get_latest_price()
        prices = buf.get_prices()
        
        # Log entry point for debugging
        if symbol in ["SPY", "QQQ"]:
            print(f"[check_entry_signals] {symbol}: current_price={current_price:.2f}, buf_len={len(prices)}")
        
        calc_debug = {
            "current_price": current_price,
            "range_high": None,
            "range_low": None,
            "range_pct": None,
            "position_in_range": None,
            "trigger_zone_low": STRATEGY_CONFIG.get("range_entry_zone_pct", 0.10),
            "min_lookback": STRATEGY_CONFIG.get("range_lookback_min_ticks", 5),
            "max_lookback": STRATEGY_CONFIG.get("range_lookback_max_ticks", 60),
        }
        
        if current_price is None:
            return None, calc_debug
        
        # ===== OPENING RANGE STRATEGY (TWO-PHASE SYSTEM) - INITIALIZE EARLY =====
        # Initialize opening range on FIRST tick, BEFORE min_lookback check
        # This allows range to build immediately even if buffer hasn't reached min_lookback yet
        if self.use_opening_range:
            now = time.time()
            
            # Initialize opening range on first tick
            if symbol not in self.opening_range:
                self.opening_range[symbol] = {
                    "high": current_price,
                    "low": current_price,
                    "ticks": 1,
                    "initialized": False,
                    "build_start_time": now,
                    "lock_time": None,
                    "validity_expires_at": None,
                    "position_locked": False,
                    "phase": "BUILDING",
                    # Volume-aware range data (NEW)
                    "volume_data": {
                        "prices": [],
                        "volumes": [],
                        "vol_median": None,
                        "vol_threshold": None,
                        "bear_zone_low": None,
                        "bear_zone_high": None,
                        "bull_zone_low": None,
                        "bull_zone_high": None,
                    }
                }
                if symbol in ["SPY", "QQQ"]:
                    print(f"[check_entry_signals] 🏗️  {symbol} NEW BUILDING RANGE CREATED (ticks=1) at {datetime.fromtimestamp(now).strftime('%H:%M:%S')}")
                logger.warning(f"🏗️  [{symbol}] NEW BUILDING RANGE CREATED (ticks=1) at {datetime.fromtimestamp(now).strftime('%H:%M:%S')}")
        
        # Now check if we have enough data for entry signals
        if len(prices) < calc_debug["min_lookback"]:
            return None, calc_debug
        
        # ===== CONTINUE RANGE PROCESSING NOW THAT WE HAVE ENOUGH DATA =====
        if self.use_opening_range:
            now = time.time()
            or_data = self.opening_range[symbol]
            
            # Debug logging for SPY/QQQ
            if symbol in ["SPY", "QQQ"]:
                print(f"[check_entry_signals] {symbol} opening_range state: phase={or_data.get('phase')}, ticks={or_data.get('ticks')}, initialized={or_data.get('initialized')}")
            
            # ===== CHECK IF RANGE NEEDS TO RESET =====
            # Conditions for reset:
            # 1. Validity window expired (15 min from lock_time) AND no open position
            # 2. Position just closed - reset immediately to Phase 1
            if or_data.get("validity_expires_at") is not None:
                if now >= or_data["validity_expires_at"] and not or_data.get("position_locked"):
                    # Validity expired, reset to Phase 1
                    logger.info(
                        f"[{symbol}] Range validity expired at {datetime.fromtimestamp(now).strftime('%H:%M:%S')}. "
                        f"Resetting to Phase 1 (BUILD)"
                    )
                    self.opening_range[symbol] = {
                        "high": current_price,
                        "low": current_price,
                        "ticks": 1,
                        "initialized": False,
                        "build_start_time": now,
                        "lock_time": None,
                        "validity_expires_at": None,
                        "position_locked": False,
                        "phase": "BUILDING",
                        # Volume-aware range data
                        "volume_data": {
                            "prices": [],
                            "volumes": [],
                            "vol_median": None,
                            "vol_threshold": None,
                            "bear_zone_low": None,
                            "bear_zone_high": None,
                            "bull_zone_low": None,
                            "bull_zone_high": None,
                        }
                    }
                    or_data = self.opening_range[symbol]
            
            # ===== PHASE 1: BUILDING =====
            if not or_data["initialized"]:
                or_data["ticks"] += 1
                or_data["high"] = max(or_data["high"], current_price)
                or_data["low"] = min(or_data["low"], current_price)
                
                # NEW: Collect volume data for volume-aware logic
                use_volume_aware = STRATEGY_CONFIG.get("use_volume_aware_range", False)
                if use_volume_aware:
                    or_data["volume_data"]["prices"].append(current_price)
                    current_volume = buf.get_latest_volume() if buf else 0
                    or_data["volume_data"]["volumes"].append(current_volume)
                
                if symbol in ["SPY", "QQQ"]:
                    print(f"[check_entry_signals] 🏗️  {symbol} BUILDING ticks incremented: {or_data['ticks']}/{self.opening_range_ticks}")
                
                # Check if build phase complete
                if or_data["ticks"] >= self.opening_range_ticks:
                    or_data["initialized"] = True
                    or_data["lock_time"] = now
                    or_data["validity_expires_at"] = now + (self.opening_range_validity_minutes * 60)
                    or_data["phase"] = "LOCKED"
                    
                    # NEW: Compute volume zones if enabled
                    use_volume_aware = STRATEGY_CONFIG.get("use_volume_aware_range", False)
                    if use_volume_aware:
                        self.compute_volume_zones(or_data)
                        # Log volume-aware analysis
                        vol_data = or_data["volume_data"]
                        logger.warning(
                            f"✅ [{symbol}] Phase 2 LOCKED (VOLUME-AWARE) after {or_data['ticks']} ticks:\n"
                            f"  Raw min/max:  ${or_data['low']:.4f} - ${or_data['high']:.4f}\n"
                            f"  Bear zone:    ${vol_data.get('bear_zone_low', or_data['low']):.4f} - ${vol_data.get('bear_zone_high', or_data['low']):.4f}\n"
                            f"  Bull zone:    ${vol_data.get('bull_zone_low', or_data['high']):.4f} - ${vol_data.get('bull_zone_high', or_data['high']):.4f}\n"
                            f"  Vol median:   {vol_data.get('vol_median', 0):.0f}\n"
                            f"  Valid until:  {datetime.fromtimestamp(or_data['validity_expires_at']).strftime('%H:%M:%S')}"
                        )
                    else:
                        # Old logic: raw min/max only
                        logger.warning(
                            f"✅ [{symbol}] Phase 2 LOCKED (RAW MIN/MAX) after {or_data['ticks']} ticks at {datetime.fromtimestamp(now).strftime('%H:%M:%S')}: "
                            f"${or_data['low']:.4f} - ${or_data['high']:.4f} "
                            f"(valid until {datetime.fromtimestamp(or_data['validity_expires_at']).strftime('%H:%M:%S')})"
                        )
                else:
                    # Still building, show progress
                    build_pct = (or_data["ticks"] / self.opening_range_ticks) * 100
                    if or_data["ticks"] == 1 or or_data["ticks"] % 10 == 0:  # Log first tick and every 10th
                        logger.warning(
                            f"🏗️  [{symbol}] BUILDING ({or_data['ticks']}/{self.opening_range_ticks} ticks, {build_pct:.0f}%): "
                            f"${or_data['low']:.4f} - ${or_data['high']:.4f}"
                        )
                    # Don't trade during build phase
                    return None, calc_debug
            
            # ===== PHASE 2: LOCKED & VALID =====
            if or_data["initialized"]:
                range_high = or_data["high"]
                range_low = or_data["low"]
                
                # Log validity window status
                time_left = or_data["validity_expires_at"] - now
                if time_left > 0 and not or_data.get("position_locked"):
                    mins_left = time_left / 60
                    logger.debug(f"[{symbol}] LOCKED range valid for {mins_left:.1f} more min")
                elif or_data.get("position_locked"):
                    logger.debug(f"[{symbol}] LOCKED range extended - position open")
            else:
                # Still building
                return None, calc_debug
        else:
            # ===== ROLLING RANGE STRATEGY (original) =====
            # Use up to 900 ticks (15 minutes) or available history, minimum 60 ticks (1 minute)
            lookback_ticks = min(len(prices), calc_debug["max_lookback"])
            lookback_ticks = max(lookback_ticks, calc_debug["min_lookback"])
            
            lookback_prices = prices[-lookback_ticks:]
            range_high = max(lookback_prices)
            range_low = min(lookback_prices)
        range_size = range_high - range_low
        
        calc_debug["range_high"] = range_high
        calc_debug["range_low"] = range_low
        calc_debug["range_pct"] = (range_size / range_low * 100) if range_low > 0 else 0
        calc_debug["range_phase"] = self.opening_range[symbol].get("phase", "N/A") if symbol in self.opening_range else "N/A"
        entry_signal = None
        
        if range_size > 0:
            # Calculate where current price sits in the range (0 = low, 1 = high)
            position_in_range = (current_price - range_low) / range_size
            calc_debug["position_in_range"] = position_in_range
            
            # ===== ENTRY LOGIC =====
            # Check if price touched/broke the PREVIOUS range_low (before range updates)
            prev_low = self.prev_range_low.get(symbol)
            
            if prev_low is None:
                # First tick for this symbol - just store the range_low
                logger.debug(f"[{symbol}] First tick - storing range_low=${range_low:.4f}")
                self.last_entry_zone[symbol] = None
            else:
                # Allow price up to ~0.5% above the previous low to catch support touches
                price_vs_prev_low = (current_price - prev_low) / prev_low if prev_low > 0 else 0.0
                calc_debug["price_vs_prev_low"] = price_vs_prev_low
                
                # Only trigger entry if price enters the zone for the FIRST time
                # Mark entry zone as rounded prev_low to prevent re-triggering
                entry_zone_key = round(prev_low, 2)  # Round to nearest cent
                last_zone = self.last_entry_zone.get(symbol)
                
                logger.debug(
                    f"[{symbol}] Range: ${range_low:.4f}-${range_high:.4f} | Price ${current_price:.4f} vs prev_low ${prev_low:.4f} "
                    f"(diff={price_vs_prev_low*100:+.3f}%, pos={position_in_range*100:.1f}%)"
                )
                
                # Entry only if: (1) price near prev_low, (2) not already entered at this level, (3) in lower 30% of range
                if (price_vs_prev_low <= 0.005 and 
                    entry_zone_key != last_zone and 
                    position_in_range <= 0.30):  # Only in lower 30% of range
                    
                    # ===== ENTRY CONFIRMATION SYSTEM =====
                    if self.entry_confirmation_enabled:
                        # ===== BOUNCE RE-EVALUATION FOR LOW-CONFIDENCE REJECTIONS =====
                        # Check if we have a pending entry waiting for bounce
                        if symbol in self.pending_entries:
                            pending = self.pending_entries[symbol]
                            if pending.get("status") == "low_confidence_waiting":
                                rejection_price = pending.get("rejection_price", current_price)
                                rejection_tick = pending.get("rejection_tick", 0)
                                ticks_since_rejection = len(prices) - rejection_tick
                                
                                # Check if price bounced enough to reconsider
                                bounce_pct = (current_price - rejection_price) / rejection_price if rejection_price > 0 else 0
                                
                                if bounce_pct >= self.entry_bounce_threshold:
                                    # Price bounced enough! Recalculate confidence with fresh data
                                    logger.info(
                                        f"🔄 BOUNCE DETECTED {symbol}: ${rejection_price:.4f} → ${current_price:.4f} "
                                        f"({bounce_pct*100:.2f}% bounce, {ticks_since_rejection} ticks) | "
                                        f"Re-evaluating entry..."
                                    )
                                    
                                    # Reset confirmation buffer to track new bounce
                                    self.confirmation_buffers[symbol] = [current_price]
                                    pending["status"] = "waiting_confirmation"
                                    pending["touch_price"] = current_price
                                    
                                    # Set reason for logging
                                    calc_debug["rejection_reason"] = (
                                        f"Re-evaluating after bounce: {bounce_pct*100:.2f}% bounce "
                                        f"(${rejection_price:.4f} → ${current_price:.4f}) in {ticks_since_rejection} ticks"
                                    )
                                    
                                    # Return to main confirmation logic by NOT entering here
                                    return None, calc_debug
                                
                                elif ticks_since_rejection >= self.entry_bounce_timeout_ticks:
                                    # Timeout - price didn't bounce, give up on this entry
                                    logger.warning(
                                        f"⏱️  BOUNCE TIMEOUT {symbol}: No bounce after {ticks_since_rejection} ticks | "
                                        f"Rejected at ${rejection_price:.4f}, now ${current_price:.4f} ({bounce_pct*100:.2f}%) | "
                                        f"Giving up, waiting for new support touch..."
                                    )
                                    
                                    # Set rejection reason for logging
                                    calc_debug["rejection_reason"] = (
                                        f"Bounce timeout: Expected {self.entry_bounce_threshold*100:.1f}% bounce within "
                                        f"{self.entry_bounce_timeout_ticks} ticks, got {bounce_pct*100:.2f}% in {ticks_since_rejection} ticks"
                                    )
                                    
                                    # Delete and wait for next entry signal
                                    del self.pending_entries[symbol]
                                    if symbol in self.confirmation_buffers:
                                        del self.confirmation_buffers[symbol]
                                    
                                    return None, calc_debug
                                
                                else:
                                    # Still waiting for bounce or timeout
                                    logger.debug(
                                        f"⏳ BOUNCE WAITING {symbol}: ${bounce_pct*100:+.2f}% (need {self.entry_bounce_threshold*100:.2f}%), "
                                        f"{ticks_since_rejection}/{self.entry_bounce_timeout_ticks} ticks"
                                    )
                                    calc_debug["rejection_reason"] = (
                                        f"Bounce waiting: Got {bounce_pct*100:.2f}% bounce "
                                        f"(need {self.entry_bounce_threshold*100:.1f}%) in {ticks_since_rejection}/"
                                        f"{self.entry_bounce_timeout_ticks} ticks"
                                    )
                                    return None, calc_debug
                        
                        # Stage 1: Support touched - create pending entry
                        if symbol not in self.pending_entries:
                            # Initialize pending entry with confidence calculation
                            pre_touch_score = self.calculate_pre_touch_momentum_score(buf)
                            support_strength_score = self.calculate_support_strength_score(symbol, current_price)
                            range_recency_score = self.calculate_range_recency_score(symbol)
                            
                            confidence = self.calculate_final_confidence(
                                symbol,
                                pre_touch_score,
                                support_strength_score,
                                range_recency_score,
                                0.5  # Default post-touch score while waiting
                            )
                            
                            now = time.time()
                            self.pending_entries[symbol] = {
                                "touch_price": current_price,
                                "touch_time": now,
                                "touch_tick_idx": len(prices),
                                "pre_touch_score": pre_touch_score,
                                "support_strength_score": support_strength_score,
                                "range_recency_score": range_recency_score,
                                "confidence": confidence,
                                "status": "waiting_confirmation"
                            }
                            
                            # Initialize confirmation buffer with touch price
                            self.confirmation_buffers[symbol] = [current_price]
                            
                            logger.info(
                                f"🎯 ENTRY SIGNAL {symbol}: Price ${current_price:.4f} near prev low ${prev_low:.4f} | "
                                f"📊 Pre-touch confidence: {confidence*100:.0f}% (momentum={pre_touch_score:.1f}, "
                                f"support={support_strength_score:.1f}, recency={range_recency_score:.2f}) | "
                                f"⏳ Waiting {self.calculate_adaptive_confirmation_window(symbol)} ticks for confirmation..."
                            )
                            # Set rejection reason for logging
                            calc_debug["rejection_reason"] = (
                                f"Support touch detected, waiting for confirmation: {self.calculate_adaptive_confirmation_window(symbol)} ticks "
                                f"(confidence={confidence*100:.0f}%)"
                            )
                            # Don't enter yet - wait for confirmation
                            return None, calc_debug
                        else:
                            # Stage 2: Confirmation window active - accumulate buffer
                            pending = self.pending_entries[symbol]
                            buf_len = len(self.confirmation_buffers[symbol])
                            confirmation_ticks_needed = self.calculate_adaptive_confirmation_window(symbol)
                            
                            # Add current price to confirmation buffer
                            self.confirmation_buffers[symbol].append(current_price)
                            
                            # Check if confirmation window is complete
                            if buf_len >= confirmation_ticks_needed:
                                # Calculate post-touch reaction score
                                post_touch_score = self.calculate_post_touch_reaction_score(symbol)
                                
                                # Recalculate final confidence with post-touch data
                                final_confidence = self.calculate_final_confidence(
                                    symbol,
                                    pending["pre_touch_score"],
                                    pending["support_strength_score"],
                                    pending["range_recency_score"],
                                    post_touch_score
                                )
                                
                                # Volume-enhanced entry: Apply volume signal adjustment if enabled
                                if STRATEGY_CONFIG.get("use_volume_enhanced_entry", False):
                                    buf = self.tick_buffers.get(symbol)
                                    current_volume = buf.get_latest_volume() if buf else 0
                                    if buf and current_volume > 0:
                                        volume_score_adjustment = self.calculate_volume_score(symbol, current_price, current_volume, buf)
                                        final_confidence += volume_score_adjustment / 100
                                        logger.warning(f"📊 VOLUME-ENHANCED {symbol}: Volume adjustment {volume_score_adjustment:+.0f}% → final confidence {final_confidence*100:.0f}%")
                                
                                logger.warning(
                                    f"📈 CONFIRMATION COMPLETE {symbol}: {buf_len} ticks | "
                                    f"Post-touch reaction: {post_touch_score:.1f} | "
                                    f"Final confidence: {final_confidence*100:.0f}%"
                                )
                                
                                # Check if confidence meets threshold
                                if final_confidence >= self.entry_confidence_threshold:
                                    # ENTRY CONFIRMED!
                                    logger.warning(
                                        f"✅ ENTRY CONFIRMED {symbol}: Final confidence {final_confidence*100:.0f}% >= "
                                        f"threshold {self.entry_confidence_threshold*100:.0f}% | "
                                        f"Entry price: ${current_price:.4f}"
                                    )
                                    
                                    # Mark zone to prevent re-entry
                                    self.last_entry_zone[symbol] = entry_zone_key
                                    
                                    # Clean up pending entry
                                    del self.pending_entries[symbol]
                                    if symbol in self.confirmation_buffers:
                                        del self.confirmation_buffers[symbol]
                                    
                                    entry_signal = "LONG"
                                else:
                                    # Confidence too low - implement second-chance logic
                                    if final_confidence >= self.entry_low_confidence_threshold:
                                        # Confidence between low_threshold and threshold
                                        # Mark as waiting for bounce instead of rejecting
                                        logger.info(
                                            f"⚠️  LOW CONFIDENCE {symbol}: {final_confidence*100:.0f}% "
                                            f"(threshold={self.entry_confidence_threshold*100:.0f}%, "
                                            f"low_threshold={self.entry_low_confidence_threshold*100:.0f}%) | "
                                            f"Waiting for bounce to reconsider..."
                                        )
                                        
                                        # Mark pending entry as low_confidence_waiting for second chance
                                        pending["status"] = "low_confidence_waiting"
                                        pending["rejection_price"] = current_price
                                        pending["rejection_tick"] = len(prices)
                                        pending["final_confidence"] = final_confidence
                                        
                                        # Set rejection reason for logging
                                        calc_debug["rejection_reason"] = (
                                            f"Low confidence rejection: {final_confidence*100:.0f}% "
                                            f"(need {self.entry_confidence_threshold*100:.0f}%, "
                                            f"waiting for {self.entry_bounce_threshold*100:.1f}% bounce)"
                                        )
                                        
                                        # Keep buffers for potential re-evaluation
                                        return None, calc_debug
                                    else:
                                        # Confidence below low_threshold - full rejection, no second chance
                                        logger.warning(
                                            f"❌ ENTRY REJECTED {symbol}: Final confidence {final_confidence*100:.0f}% < "
                                            f"low threshold {self.entry_low_confidence_threshold*100:.0f}% | "
                                            f"Waiting for next support touch..."
                                        )
                                        
                                        # Set rejection reason for logging
                                        calc_debug["rejection_reason"] = (
                                            f"Full confidence rejection: {final_confidence*100:.0f}% < "
                                            f"low threshold {self.entry_low_confidence_threshold*100:.0f}% | "
                                            f"(momentum={pending['pre_touch_score']:.1f}, "
                                            f"support={pending['support_strength_score']:.1f}, "
                                            f"recency={pending['range_recency_score']:.2f}, "
                                            f"post_touch={post_touch_score:.1f})"
                                        )
                                        
                                        # Delete pending entry - support failed
                                        del self.pending_entries[symbol]
                                        if symbol in self.confirmation_buffers:
                                            del self.confirmation_buffers[symbol]
                                        
                                        return None, calc_debug
                            else:
                                # Still waiting for more confirmation ticks
                                logger.debug(
                                    f"⏳ CONFIRMATION WAITING {symbol}: {buf_len}/{confirmation_ticks_needed} ticks | "
                                    f"Price: ${current_price:.4f}"
                                )
                                calc_debug["rejection_reason"] = (
                                    f"Confirmation window in progress: {buf_len}/{confirmation_ticks_needed} ticks "
                                    f"(waiting to confirm support touch)"
                                )
                                return None, calc_debug
                    else:
                        # Confirmation disabled - immediate entry
                        entry_signal = "LONG"
                        self.last_entry_zone[symbol] = entry_zone_key
                        logger.info(
                            f"✅ ENTRY {symbol}: Price ${current_price:.4f} near previous low ${prev_low:.4f} "
                            f"(diff: {price_vs_prev_low*100:.3f}%, range pos: {position_in_range*100:.1f}%)"
                        )
                else:
                    # Entry conditions not met - provide detailed rejection reason
                    if price_vs_prev_low <= 0.005 and entry_zone_key == last_zone:
                        rejection_reason = f"Already entered at zone ${entry_zone_key:.2f} (price ${current_price:.4f})"
                        logger.debug(f"[{symbol}] {rejection_reason}")
                        calc_debug["rejection_reason"] = rejection_reason
                    elif position_in_range > 0.30:
                        rejection_reason = f"Price in upper zone: {position_in_range*100:.1f}% of range (${range_low:.4f}-${range_high:.4f})"
                        logger.debug(f"[{symbol}] {rejection_reason}")
                        calc_debug["rejection_reason"] = rejection_reason
                    elif price_vs_prev_low > 0.005:
                        rejection_reason = f"Price too high vs support: {price_vs_prev_low*100:.3f}% above prev_low ${prev_low:.4f}"
                        logger.debug(f"[{symbol}] {rejection_reason}")
                        calc_debug["rejection_reason"] = rejection_reason
                    else:
                        rejection_reason = f"No support touch detected (price ${current_price:.4f}, range ${range_low:.4f}-${range_high:.4f})"
                        logger.debug(f"[{symbol}] {rejection_reason}")
                        calc_debug["rejection_reason"] = rejection_reason
            
            # Store current range_low for NEXT tick's comparison
            self.prev_range_low[symbol] = range_low
        
        return entry_signal, calc_debug
    
    def check_entry_signals_legacy(self) -> Optional[str]:
        """
        DEPRECATED: Old tick-based entry logic. Kept for reference.
        Use check_entry_signals(symbol) for bar-based trend trading.
        """
        if not self.tick_buffer.is_ready():
            return None
        
        # Get EMA values for trend detection
        ema50 = self.tick_buffer.calculate_ema_50()
        ema20 = self.tick_buffer.calculate_ema_20()
        current_price = self.tick_buffer.get_latest_price()
        
        if current_price is None or ema50 is None:
            return None
        
        # Get confirmation signals
        momentum_pct = self.tick_buffer.calculate_price_change()
        current_volume = self.tick_buffer.get_latest_volume()
        avg_volume = self.tick_buffer.calculate_avg_volume()
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        # Confirmation thresholds
        momentum_threshold = 0.0005
        momentum_ok = abs(momentum_pct) >= momentum_threshold
        volume_ok = volume_ratio >= 0.3
        
        # Get daily bias for context
        daily_bias = self.current_daily_data.daily_bias if self.current_daily_data else 1.0
        daily_change = self.current_daily_data.todays_change_pct if self.current_daily_data else 0.0
        daily_context = "DOWN" if daily_change < 0 else "UP" if daily_change > 0 else "NEUTRAL"
        
        if current_price > ema50:
            momentum_status = "[PRIMARY]" if momentum_ok else "[INFO]"
            volume_status = "[OK]" if volume_ok else "[WEAK]"
            
            if momentum_ok or volume_ok:
                logger.info(
                    f"🔴 SHORT ENTRY: Price ${current_price:.2f} < EMA50 ${ema50:.2f} | "
                    f"Momentum {momentum_status} {momentum_pct:+.3f}% | "
                    f"Volume {volume_status} {volume_ratio:.2f}x | "
                    f"EMA20 ${ema20:.2f} | "
                    f"Daily {daily_context} ({daily_change:+.2f}%)"
                )
                return "SHORT"
            else:
                logger.debug(
                    f"SHORT blocked: Price < EMA50 but no confirmation | "
                    f"Momentum {momentum_pct:+.3f}% (need ≥0.1%) | "
                    f"Volume {volume_ratio:.2f}x (need ≥0.5x)"
                )
        
        return None
    
    def check_exit_signals(self, symbol: str, current_price: float) -> Optional[str]:
        """Range-based exits + traditional stops.
        
        Exit if:
        1. Price near range high (top 10%) → take profit
        2. Stop loss hit
        3. Trailing stop triggered
        """
        if symbol not in self.current_positions:
            return None

        trade = self.current_positions[symbol]

        # PnL calc (CFD-style)
        if trade.direction == "LONG":
            pnl_pct = (current_price - trade.entry_price) / trade.entry_price
        else:
            pnl_pct = (trade.entry_price - current_price) / trade.entry_price

        # Max adverse excursion guard - DISABLED
        # mae_pct = STRATEGY_CONFIG.get("max_adverse_excursion_pct")
        # if mae_pct and mae_pct > 0 and pnl_pct <= -mae_pct:
        #     logger.info(
        #         f"⚠️ EXIT {symbol} {trade.direction}: MAE {pnl_pct*100:+.2f}% <= {-mae_pct*100:.2f}%"
        #     )
        #     return "MAE"

        # Track best favorable run for trailing protection
        if pnl_pct > trade.best_favorable_pct:
            trade.best_favorable_pct = pnl_pct
            trade.best_favorable_price = current_price

        # ====== RANGE-BASED EXIT: Near High ======
        buf = self.tick_buffers.get(symbol)
        if buf:
            prices = buf.get_prices()
            min_lookback = STRATEGY_CONFIG.get("range_lookback_min_ticks", 5)
            max_lookback = STRATEGY_CONFIG.get("range_lookback_max_ticks", 60)
            if len(prices) >= min_lookback:
                lookback_ticks = min(len(prices), max_lookback)
                lookback_ticks = max(lookback_ticks, min_lookback)
                
                lookback_prices = prices[-lookback_ticks:]
                range_high = max(lookback_prices)
                range_low = min(lookback_prices)
                range_size = range_high - range_low
                
                if range_size > 0:
                    position_in_range = (current_price - range_low) / range_size
                    exit_zone = STRATEGY_CONFIG.get("range_exit_zone_pct", 0.90)
                    
                    # EXIT signal: Price near range high (configurable threshold)
                    if position_in_range >= exit_zone and current_price >= trade.entry_price:
                        prev_price = prices[-2] if len(prices) >= 2 else current_price

                        # If price is still rising in the top zone, hold; exit on first dip
                        if trade.direction == "LONG" and current_price >= prev_price:
                            logger.debug(
                                f"HOLD {symbol} {trade.direction}: TOP ZONE rising | "
                                f"Price ${current_price:.2f} (prev ${prev_price:.2f}) | "
                                f"PnL: {pnl_pct*100:+.2f}%"
                            )
                        else:
                            logger.info(
                                f"📊 EXIT {symbol} {trade.direction}: RANGE TOP (dip) | "
                                f"Price ${current_price:.2f} in top {(1-position_in_range)*100:.1f}% "
                                f"(range: ${range_low:.2f}-${range_high:.2f}) | PnL: {pnl_pct*100:+.2f}%"
                            )
                            return "RANGE_HIGH"
                    elif position_in_range >= exit_zone and current_price < trade.entry_price:
                        logger.debug(
                            f"Skip RANGE_TOP exit: price below entry (${current_price:.2f} < ${trade.entry_price:.2f})"
                        )

        # Stop loss (hard safety cap)
        stop_loss_pct = STRATEGY_CONFIG.get("stop_loss")
        if stop_loss_pct and stop_loss_pct > 0 and pnl_pct <= -stop_loss_pct:
            logger.info(f"🛑 EXIT {symbol} {trade.direction}: STOP LOSS | PnL: {pnl_pct*100:+.2f}%")
            return "SL"

        # Trailing stop (lock in profits after significant gain)
        trail_activate = STRATEGY_CONFIG.get("trailing_stop_activate_pct", 0.01)
        trail_distance = STRATEGY_CONFIG.get("trailing_stop_distance_pct", 0.005)
        if trade.best_favorable_pct >= trail_activate:
            giveback = trade.best_favorable_pct - pnl_pct
            if giveback >= trail_distance:
                logger.info(
                    f"📊 EXIT {symbol} {trade.direction}: TRAILING STOP | "
                    f"Best: {trade.best_favorable_pct*100:+.2f}% → Current: {pnl_pct*100:+.2f}% | "
                    f"Giveback: {giveback*100:.2f}%"
                )
                return "TRAIL"

        # Profit target (optional)
        profit_target = STRATEGY_CONFIG.get("profit_target", 0.05)
        if profit_target and pnl_pct >= profit_target:
            logger.info(f"🎯 EXIT {symbol} {trade.direction}: PROFIT TARGET | PnL: {pnl_pct*100:+.2f}%")
            return "TP"

        # Time-decay exits: gradually lower profit thresholds as time passes
        # Time-Decay Exit: Unlocks capital from stalled trades
        elapsed_seconds = (datetime.now() - trade.entry_time).total_seconds()
        elapsed_minutes = elapsed_seconds / 60
        
        time_decay_exits = STRATEGY_CONFIG.get("time_decay_exits", [])
        if time_decay_exits:
            # Check tiers from longest to shortest time (earliest match wins)
            sorted_tiers = sorted(time_decay_exits, key=lambda x: x["minutes"], reverse=True)
            
            # Debug: Log current status for this trade
            logger.debug(
                f"📊 TIME_DECAY check for {symbol} {trade.direction}: "
                f"Elapsed={elapsed_minutes:.1f}min, P/L={pnl_pct*100:+.2f}%, "
                f"Price=${current_price:.2f}"
            )
            
            for threshold in sorted_tiers:
                minutes_req = threshold["minutes"]
                profit_req = threshold["profit_pct"]
                
                # Check if this tier is active
                if elapsed_minutes >= minutes_req:
                    # This tier is now active, check if P/L meets threshold
                    if pnl_pct >= profit_req:
                        logger.info(
                            f"🎯 EXIT {symbol} {trade.direction}: TIME_DECAY_{minutes_req}MIN | "
                            f"⏱️  Elapsed: {elapsed_minutes:.1f}min (threshold: {minutes_req}min) | "
                            f"💰 P/L: {pnl_pct*100:+.2f}% (threshold: {profit_req*100:+.1f}%) | "
                            f"📈 Price: ${current_price:.2f} | Entry: ${trade.entry_price:.2f}"
                        )
                        return "TIME_DECAY"
                    else:
                        # Tier is active but P/L not sufficient
                        logger.debug(
                            f"❌ TIME_DECAY_{minutes_req}MIN not triggered for {symbol}: "
                            f"P/L {pnl_pct*100:+.2f}% < threshold {profit_req*100:+.1f}%"
                        )
                        break  # Stop checking lower tiers since this is the first active one
                else:
                    # This tier not yet active
                    logger.debug(
                        f"⏳ TIME_DECAY_{minutes_req}MIN waiting: "
                        f"{minutes_req - elapsed_minutes:.1f}min remaining (current: {elapsed_minutes:.1f}min)"
                    )

        return None
    
    def check_exit_signals_legacy(self, symbol: str, current_price: float) -> Optional[str]:
        """
        DEPRECATED: Old tick-based exit logic. Kept for reference.
        """
        if symbol not in self.current_positions:
            return None
        
        trade = self.current_positions[symbol]
        elapsed_seconds = (datetime.now() - trade.entry_time).total_seconds()

        # Assess if the trend is still in our favor to optionally widen the stop
        price_change = self.tick_buffer.calculate_price_change()
        price_direction_streak = self.tick_buffer.get_price_direction_streak()
        min_streak = STRATEGY_CONFIG.get("min_direction_streak", 3)
        current_volume = self.tick_buffer.get_latest_volume()
        avg_volume = self.tick_buffer.calculate_avg_volume()
        volume_ratio = current_volume / avg_volume if avg_volume else 0
        trend_continuing = False
        if trade.direction == "LONG":
            trend_continuing = (
                price_change > 0 and
                price_direction_streak > 0 and abs(price_direction_streak) >= min_streak and
                volume_ratio >= 0.8
            )
        else:  # SHORT
            trend_continuing = (
                price_change < 0 and
                price_direction_streak < 0 and abs(price_direction_streak) >= min_streak and
                volume_ratio >= 0.8
            )
        sl_multiplier = STRATEGY_CONFIG.get("trend_sl_buffer", 1.0) if trend_continuing else 1.0
        
        # Calculate PnL correctly for CFD
        if trade.direction == "LONG":
            # LONG profits when price goes UP
            pnl_pct = (current_price - trade.entry_price) / trade.entry_price
        else:  # SHORT
            # SHORT profits when price goes DOWN
            pnl_pct = (trade.entry_price - current_price) / trade.entry_price

        # Track best favorable run for trailing protection
        if pnl_pct > trade.best_favorable_pct:
            trade.best_favorable_pct = pnl_pct
            trade.best_favorable_price = current_price
        
        # Check 1a: Stop loss (CFD) with optional trend buffer
        effective_sl = STRATEGY_CONFIG["stop_loss"] * sl_multiplier
        if pnl_pct <= -effective_sl:
            logger.debug(f"{trade.direction} SL hit: {pnl_pct*100:.2f}% (effective SL {effective_sl*100:.2f}%)")
            return "SL"

        # Check 1b: Trailing stop after activation threshold to lock gains
        trail_activate = STRATEGY_CONFIG.get("trailing_stop_activate_pct")
        trail_distance = STRATEGY_CONFIG.get("trailing_stop_distance_pct")
        if trail_activate and trail_distance and trade.best_favorable_pct >= trail_activate:
            giveback = trade.best_favorable_pct - pnl_pct
            if giveback >= trail_distance:
                logger.debug(
                    f"{trade.direction} TRAIL stop: best {trade.best_favorable_pct*100:.2f}% -> "
                    f"{pnl_pct*100:.2f}% (giveback {giveback*100:.2f}%)"
                )
                return "TRAIL"

        # Check 2: Profit target (CFD)
        if pnl_pct >= STRATEGY_CONFIG["profit_target"]:
            logger.debug(f"{trade.direction} TP hit: {pnl_pct*100:.2f}%")
            return "TP"
        
        # Check 3: Time stop only if trade is worse than -1% (otherwise let it run)
        if elapsed_seconds >= STRATEGY_CONFIG["time_stop_seconds"] and pnl_pct <= -0.01:
            return "TIME"
        
        # Check 4: Momentum stall (flat market - opposite direction emerging)
        recent_changes = self.tick_buffer.get_last_n_price_changes(STRATEGY_CONFIG["flat_seconds"])
        if recent_changes:
            # Check if trend reversed (opposite direction) with wider tolerance to avoid premature exits
            avg_recent_move = sum(recent_changes) / len(recent_changes)
            reversal_threshold = 0.0003  # 0.03% average move opposite direction
            
            if trade.direction == "LONG" and avg_recent_move < -reversal_threshold:
                return "FLAT"
            elif trade.direction == "SHORT" and avg_recent_move > reversal_threshold:
                return "FLAT"
        
        return None
    
    def can_trade(self, symbol: str = None) -> Tuple[bool, Optional[str]]:
        """Check if we're allowed to trade based on ALL risk rules
        
        Args:
            symbol: Optional symbol to check. If provided, only checks if THIS symbol has an open position.
                   If None, checks if ANY symbol has an open position (legacy behavior).
        """
        from datetime import timedelta
        
        # RULE PRIORITY: Risk rules first
        
        # RULE 4.2/13: Daily loss limit (KILL SWITCH)
        # Use the configured kill switch if present, otherwise fall back to RISK_CONFIG (-5% default).
        daily_loss_pct = self.metrics.get_daily_loss_pct()
        kill_switch_cfg = PROFESSIONAL_RULES.get("rule_13_daily_kill_switch", {})
        loss_limit_pct = kill_switch_cfg.get("daily_loss_limit_pct", RISK_CONFIG.get("daily_loss_limit", -0.05))

        if daily_loss_pct <= loss_limit_pct:
            rule_msg = (
                f"RULE 4.2 VIOLATED: Daily loss limit ({daily_loss_pct*100:.2f}% <= {loss_limit_pct*100:.2f}%)"
            )
            self.rules_violated_log.append(rule_msg)
            return False, rule_msg
        
        # RULE 4.1: Risk per trade - check if THIS SYMBOL or ANY symbol has open position
        if symbol:
            # Check only this specific symbol
            if symbol in self.current_positions:
                return False, f"Already have open position for {symbol}"
        else:
            # Legacy: check if ANY symbol has open position
            if len(self.current_positions) > 0:
                return False, "Already have open position"
        
        # RULE 4.4: Cooldown after consecutive losses
        if self.cooldown_until and datetime.now() < self.cooldown_until:
            remaining = (self.cooldown_until - datetime.now()).total_seconds()
            rule_msg = f"RULE 4.4 VIOLATED: Cooldown active ({remaining:.0f}s remaining)"
            return False, rule_msg
        
        # RULE 4.3: Max trades per hour
        now = datetime.now()
        if (now - self.hour_start_time).total_seconds() > 3600:
            self.hourly_trade_count = 0
            self.hour_start_time = now
        
        # Use RISK_CONFIG as the source of truth for max trades per hour (default 15)
        max_trades_hour = RISK_CONFIG.get("max_trades_per_hour", 15)
        if self.hourly_trade_count >= max_trades_hour:
            rule_msg = f"RULE 4.3 VIOLATED: Max {max_trades_hour} trades/hour reached"
            return False, rule_msg
        
        return True, None

    
    def check_rule_2_3_spread(self, entry_price: float, current_price: float) -> Tuple[bool, Optional[str]]:
        """RULE 2.3: Spread filter"""
        rule_config = PROFESSIONAL_RULES.get("rule_2_3_spread_filter", {})
        if not rule_config.get("enabled", True):
            return True, None
        
        tp_pct = PROFESSIONAL_RULES.get("rule_3_fixed_asymmetric_rr", {}).get("tp_pct", 0.0025)
        spread = abs(current_price - entry_price) / entry_price
        max_spread = tp_pct * rule_config.get("max_spread_vs_profit", 0.5)
        
        if spread > max_spread:
            rule_msg = f"RULE 2.3 VIOLATED: Spread ({spread*100:.3f}%) > max ({max_spread*100:.3f}%)"
            return False, rule_msg
        
        return True, None
    
    def _get_buffer(self, symbol: str) -> TickBuffer:
        """Return/create tick buffer for a symbol."""
        if symbol not in self.tick_buffers:
            self.tick_buffers[symbol] = TickBuffer(STRATEGY_CONFIG["window_size"])
        return self.tick_buffers[symbol]

    def _get_portfolio_available_cash(self) -> Optional[float]:
        """Fetch available cash from Trading212 (demo or live). Cached for a short TTL."""
        now = time.time()
        if self._cached_available_cash is not None and self._cash_cache_ts and (now - self._cash_cache_ts) < self._cash_cache_ttl:
            return self._cached_available_cash

        live = os.getenv("LIVE", "false").lower() == "true"
        if live:
            base = os.getenv("TRADING212_LIVE_ENVIRONMENT", "https://live.trading212.com/api/v0").rstrip("/")
            key = os.getenv("TRADING212_API_KEY", "")
            secret = os.getenv("TRADING212_API_SECRET", "")
        else:
            base = os.getenv("TRADING212_DEMO_ENVIRONMENT", "https://demo.trading212.com/api/v0").rstrip("/")
            key = os.getenv("TRADING212_DEMO_API_KEY", "")
            secret = os.getenv("TRADING212_DEMO_API_SECRET", "")

        if not key or not secret:
            return None

        url = f"{base}/equity/account/summary"
        try:
            resp = requests.get(url, auth=(key, secret), timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                cash_block = data.get("cash") or {}
                available = cash_block.get("availableToTrade")
                if available is not None:
                    self._cached_available_cash = float(available)
                    self._cash_cache_ts = now
                    return self._cached_available_cash
            return None
        except Exception:
            return None

    def process_tick(self, tick: Tick) -> dict:
        """
        Main strategy loop (tick-based EMA crossover, no bars).
        """
        buf = self._get_buffer(tick.symbol)
        buf.add_tick(tick)
        self.metrics.total_ticks += 1
        
        # Fetch daily market data
        self.current_daily_data = self.market_data_provider.get_daily_data()
        
        event = {
            "tick": tick,
            "action": None,
            "trade": None,
            "reason": None,
            "metrics": None,
            "no_trade_reason": None,
        }
        
        # ====== GLOBAL WARMUP: require a minimum number of ticks before trading ======
        ticks_seen = len(buf.ticks)
        if ticks_seen < self.warmup_ticks:
            event["no_trade_reason"] = (
                f"Warming up: {ticks_seen}/{self.warmup_ticks} ticks "
                f"({(ticks_seen / self.warmup_ticks) * 100:.0f}%)"
            )
            event["calc"] = {
                "warmup_progress": ticks_seen,
                "warmup_required": self.warmup_ticks,
            }
            event["metrics"] = self.get_current_metrics()
            return event

        # ====== CHECK EXIT FOR OPEN POSITIONS ======
        if tick.symbol in self.current_positions:
            logger.debug(f"🔍 EXIT CHECK for {tick.symbol}: Symbol in current_positions (keys: {list(self.current_positions.keys())})")
            exit_reason = self.check_exit_signals(tick.symbol, tick.price)
            logger.debug(f"🔍 check_exit_signals returned: {exit_reason}")
            
            if exit_reason:
                logger.info(f"🔍 EXIT SIGNAL {tick.symbol}: Reason={exit_reason}, calling _close_position()")
                trade_to_close = self.current_positions[tick.symbol]
                self._close_position(tick.symbol, tick.price, exit_reason)
                # Validate position was actually removed from tracking dict after close
                if tick.symbol not in self.current_positions:
                    event["action"] = "CLOSE"
                    event["trade"] = trade_to_close
                    event["reason"] = exit_reason
                    logger.info(f"🔍 EXIT COMPLETE {tick.symbol}: event['action']={event['action']} - Position removed from tracking")
                    logger.debug(f"✅ Position validation: {tick.symbol} confirmed removed from current_positions")
                else:
                    logger.error(f"❌ VALIDATION FAILED: Position still in current_positions for {tick.symbol} after _close_position call!")
                    logger.error(f"   Current positions keys: {list(self.current_positions.keys())}")
                    event["action"] = None  # Don't mark as CLOSE if still tracked
                    event["no_trade_reason"] = "Position close validation failed"
                
                # Update loss counter
                if trade_to_close.pnl < 0:
                    self.consecutive_losses_counter += 1
                else:
                    self.consecutive_losses_counter = 0
        
        # ====== CHECK ENTRY FOR NEW POSITIONS ======
        else:
            can_trade, reason = self.can_trade(tick.symbol)

            if not can_trade:
                event["no_trade_reason"] = reason
                event["calc"] = {"can_trade": False, "reason": reason}
                logger.debug(f"⛔ Cannot trade {tick.symbol}: {reason}")
            else:
                ema_fast = buf.calculate_ema_20()
                ema_slow = buf.calculate_ema_50()

                if ema_fast is None or ema_slow is None:
                    history_len = len(buf.ticks)
                    ema_fast_period = 20
                    ema_slow_period = 30  # calculate_ema_50 uses a shortened 30-period for warmup
                    lookback_required = max(ema_fast_period, ema_slow_period)
                    lookback_ok = history_len >= lookback_required
                    logger.debug(
                        f"EMA warmup {tick.symbol}: {history_len} ticks (need >= {lookback_required}) "
                        f"fast_period={ema_fast_period} slow_period={ema_slow_period}"
                    )

                    event["no_trade_reason"] = "EMA warmup"
                    event["calc"] = {
                        "ema_fast": ema_fast,
                        "ema_slow": ema_slow,
                        "fast_above": None,
                        "fast_above_effective": None,
                        "prev_fast_above": self.prev_fast_above.get(tick.symbol),
                        "ema_band_pct": STRATEGY_CONFIG.get("ema_neutral_band_pct", 0.0),
                        "ema_band_abs": None,
                        "ema_gap": None,
                        "crossover_type": None,
                        "recent_momentum": None,
                        "momentum_threshold": STRATEGY_CONFIG.get("entry_momentum_threshold", 0.002),
                        "prior_momentum": None,
                        "reversal_drop_pct": STRATEGY_CONFIG.get("entry_reversal_drop_pct", 0.003),
                        "lookback": STRATEGY_CONFIG.get("entry_reversal_lookback_ticks", 10),
                        "lookback_ok": lookback_ok,
                        "history_len": history_len,
                        "lookback_required": lookback_required,
                        "window_size": buf.window_size,
                    }
                else:
                    entry_signal, calc_debug = self.check_entry_signals(tick.symbol, buf)

                    # Enrich calc_debug so logs capture actual EMA state instead of None placeholders
                    ema_band_pct = STRATEGY_CONFIG.get("ema_neutral_band_pct", 0.0)
                    ema_gap = ema_fast - ema_slow
                    ema_band_abs = abs(ema_gap)
                    ema_band_pct_val = (abs(ema_gap) / ema_slow) if ema_slow else None
                    fast_above = ema_fast > ema_slow
                    fast_above_effective = fast_above
                    if ema_band_pct_val is not None and ema_band_pct and ema_band_pct_val < ema_band_pct:
                        fast_above_effective = None  # Treat as neutral inside the band

                    prev_fast_above = self.prev_fast_above.get(tick.symbol)
                    crossover_type = None
                    if prev_fast_above is not None and fast_above_effective is not None and fast_above_effective != prev_fast_above:
                        crossover_type = "GOLDEN" if fast_above_effective else "DEATH"

                    if fast_above_effective is not None:
                        self.prev_fast_above[tick.symbol] = fast_above_effective

                    calc_debug.update({
                        "ema_fast": ema_fast,
                        "ema_slow": ema_slow,
                        "fast_above": fast_above,
                        "fast_above_effective": fast_above_effective,
                        "prev_fast_above": prev_fast_above,
                        "ema_band_pct": ema_band_pct,
                        "ema_band_abs": ema_band_abs,
                        "ema_gap": ema_gap,
                        "crossover_type": crossover_type,
                        "recent_momentum": buf.calculate_momentum(),
                        "momentum_threshold": STRATEGY_CONFIG.get("entry_momentum_threshold", 0.002),
                        "prior_momentum": calc_debug.get("prior_momentum"),
                        "reversal_drop_pct": STRATEGY_CONFIG.get("entry_reversal_drop_pct", 0.003),
                        "lookback": calc_debug.get("lookback"),
                        "lookback_ok": calc_debug.get("lookback_ok", True),
                    })

                    event["calc"] = calc_debug

                    if entry_signal:
                        self._open_position(tick.symbol, tick.price, entry_signal)
                        # Validate position was actually added to tracking dict before marking OPEN
                        if tick.symbol in self.current_positions:
                            event["action"] = "OPEN"
                            event["trade"] = self.current_positions[tick.symbol]
                            event["reason"] = "RANGE_SUPPORT"  # Use actual entry signal type
                            logger.debug(f"✅ Position validated for {tick.symbol}: in current_positions with entry @ ${self.current_positions[tick.symbol].entry_price:.4f}")
                        else:
                            logger.error(f"❌ VALIDATION FAILED: Position not in current_positions for {tick.symbol} after _open_position call!")
                            event["no_trade_reason"] = "Position validation failed"
                    else:
                        # No entry signal - capture rejection reason if available
                        rejection_reason = calc_debug.get("rejection_reason")
                        if rejection_reason:
                            event["no_trade_reason"] = rejection_reason
                        else:
                            event["no_trade_reason"] = "Waiting for entry confirmation or support touch"
        
        event["metrics"] = self.get_current_metrics()
        return event
    
    def _open_position(self, symbol: str, entry_price: float, direction: str):
        """Open a new trade with daily market context"""
        daily_change = self.current_daily_data.todays_change_pct if self.current_daily_data else 0.0
        daily_context = "DOWN" if daily_change < 0 else "UP" if daily_change > 0 else "NEUTRAL"
        daily_bias = self.current_daily_data.daily_bias if self.current_daily_data else 1.0

        position_size, sizing_note = self._compute_position_size(entry_price)
        
        entry_time = datetime.now()
        trade = Trade(
            entry_time=entry_time,
            entry_price=entry_price,
            direction=direction,
            entry_reason="MOMENTUM_BURST",
            position_size=position_size,
            symbol=symbol,
        )
        self.current_positions[symbol] = trade
        
        entry_time_str = entry_time.strftime('%H:%M:%S')
        
        # ===== LOCK RANGE TO CURRENT POSITION =====
        # Set position_locked flag so range stays valid even after 15-min window expires
        if symbol in self.opening_range:
            self.opening_range[symbol]["position_locked"] = True
            lock_time = datetime.fromtimestamp(self.opening_range[symbol]["lock_time"]).strftime('%H:%M:%S')
            expires_at = datetime.fromtimestamp(self.opening_range[symbol]["validity_expires_at"]).strftime('%H:%M:%S')
            logger.info(
                f"[{symbol}] Position opened - range locked until close | "
                f"Range: ${self.opening_range[symbol]['low']:.4f}-${self.opening_range[symbol]['high']:.4f} "
                f"(locked at {lock_time}, was expiring at {expires_at})"
            )
        
        logger.info(
            f"🔓 OPEN {direction} {symbol} @ ${entry_price:.2f} | size {position_size:.0f} shares | "
            f"Daily {daily_context} ({daily_change:+.2f}%) bias={daily_bias:.1f}x | {sizing_note} | "
            f"📍 Entry time: {entry_time_str} (for TIME_DECAY tracking)"
        )
    
    def _close_position(self, symbol: str, exit_price: float, exit_reason: str):
        """Close the current position and reset range to Phase 1 (BUILD)"""
        from datetime import timedelta
        
        logger.info(f"🔍 _close_position CALLED for {symbol} @ ${exit_price} (reason: {exit_reason})")
        if symbol not in self.current_positions:
            logger.error(f"🔍 _close_position ERROR: {symbol} NOT in current_positions! Keys: {list(self.current_positions.keys())}")
            return
        
        trade = self.current_positions[symbol]
        logger.info(f"🔍 _close_position EXECUTING: Closing {trade.direction} position")
        trade.close(exit_price, exit_reason)
        self.closed_trades.append(trade)
        self.metrics.update_from_closed_trade(trade)
        
        # Track hourly trade count
        self.hourly_trade_count += 1
        
        # Implement RULE 4.4: Cooldown after consecutive losses
        if trade.pnl < 0:
            self.consecutive_losses_counter += 1
            
            if self.consecutive_losses_counter >= PROFESSIONAL_RULES.get("rule_4_4_cooldown_after_losses", {}).get("consecutive_losses_threshold", 2):
                cooldown_secs = PROFESSIONAL_RULES.get("rule_4_4_cooldown_after_losses", {}).get("cooldown_seconds", 300)
                self.cooldown_until = datetime.now() + timedelta(seconds=cooldown_secs)
                logger.warning(f"⏸️  RULE 4.4: Cooldown activated for {cooldown_secs}s after {self.consecutive_losses_counter} losses")
        else:
            self.consecutive_losses_counter = 0
        
        logger.info(f"✅ CLOSE {trade.direction} @ ${exit_price:.2f} ({exit_reason}) "
                   f"| PnL: ${trade.pnl:.2f} ({trade.pnl_pct*100:.2f}%)")
        
        # ===== RESET OPENING RANGE TO PHASE 1 (BUILD) IMMEDIATELY =====
        # When position closes, immediately reset the range so it rebuilds
        # for the next trading opportunity (don't wait for validity expiration)
        if symbol in self.opening_range:
            now = time.time()
            self.opening_range[symbol] = {
                "high": exit_price,
                "low": exit_price,
                "ticks": 1,
                "initialized": False,
                "build_start_time": now,
                "lock_time": None,
                "validity_expires_at": None,
                "position_locked": False,
                "phase": "BUILDING",
                # Volume-aware range data
                "volume_data": {
                    "prices": [],
                    "volumes": [],
                    "vol_median": None,
                    "vol_threshold": None,
                    "bear_zone_low": None,
                    "bear_zone_high": None,
                    "bull_zone_low": None,
                    "bull_zone_high": None,
                }
            }
            # Also clear entry zone tracking so new range can generate fresh entry signals
            self.last_entry_zone[symbol] = None
            self.prev_range_low[symbol] = exit_price  # Reset to current exit price as reference
            logger.info(f"[{symbol}] Position closed @ ${exit_price:.2f}. Range RESET to Phase 1 (BUILD) for next opportunity")
        
        del self.current_positions[symbol]
    
    def compute_volume_zones(self, or_data: dict) -> None:
        """
        Compute bear (low-price high-vol) and bull (high-price high-vol) zones.
        Updates or_data["volume_data"] in place.
        Called when Phase 1 (BUILDING) completes.
        """
        prices = or_data["volume_data"]["prices"]
        volumes = or_data["volume_data"]["volumes"]
        
        if not prices or not volumes or len(prices) < 10:
            # Not enough data; skip volume analysis
            return
        
        import statistics
        
        # Calculate volume threshold
        vol_median = statistics.median(volumes)
        vol_threshold = vol_median * 1.5  # High volume = 1.5x median
        or_data["volume_data"]["vol_median"] = vol_median
        or_data["volume_data"]["vol_threshold"] = vol_threshold
        
        # Split by price zone (low vs high)
        mid_price = (min(prices) + max(prices)) / 2
        low_price_pairs = [(p, v) for p, v in zip(prices, volumes) if p <= mid_price]
        high_price_pairs = [(p, v) for p, v in zip(prices, volumes) if p > mid_price]
        
        # Bear accumulation: high-vol in low-price zone
        low_high_vol = [p for p, v in low_price_pairs if v >= vol_threshold]
        if low_high_vol:
            or_data["volume_data"]["bear_zone_low"] = min(low_high_vol)
            or_data["volume_data"]["bear_zone_high"] = max(low_high_vol)
        
        # Bull accumulation: high-vol in high-price zone
        high_high_vol = [p for p, v in high_price_pairs if v >= vol_threshold]
        if high_high_vol:
            or_data["volume_data"]["bull_zone_low"] = min(high_high_vol)
            or_data["volume_data"]["bull_zone_high"] = max(high_high_vol)
    
    def get_post_volume_price_movement(self, symbol: str, buf) -> dict:
        """Analyze how price moved in the last 3 ticks leading into current volume bar.
        
        Returns dict with analysis of pre-volume price action:
        - price_changed_up: Price was rising before volume
        - price_changed_down: Price was falling before volume
        - max_move_up: Maximum price increase in last 3 ticks
        - max_move_down: Maximum price decrease in last 3 ticks
        - direction_strength: UP, DOWN, FLAT based on net movement
        """
        prices = buf.get_prices() if buf else []
        if not buf or len(prices) < 4:  # Need at least 4 ticks (3 past + current)
            return {}
        
        # Look at PREVIOUS 3 ticks before current
        current_idx = len(prices) - 1
        if current_idx < 3:
            return {}
        
        current_price = prices[current_idx]
        past_prices = prices[current_idx - 3:current_idx]  # Last 3 ticks before current
        
        if not past_prices or len(past_prices) < 3:
            return {}
        
        max_price = max(past_prices)
        min_price = min(past_prices)
        start_price = past_prices[0]  # Price 3 ticks ago
        
        max_move_up = max_price - start_price
        max_move_down = start_price - min_price
        
        # Determine direction based on net movement from 3 ticks ago to current
        net_move = current_price - start_price
        if net_move > 0:
            direction = "UP"
        elif net_move < 0:
            direction = "DOWN"
        else:
            direction = "FLAT"
        
        return {
            "price_changed_up": current_price > start_price,
            "price_changed_down": current_price < start_price,
            "max_move_up": max_move_up,
            "max_move_down": max_move_down,
            "direction_strength": direction,
            "net_move": net_move
        }
    
    def classify_volume_signal(self, volume: float, avg_volume: float, price_movement: dict) -> dict:
        """Classify volume signal as accumulation, distribution, or neutral.
        
        Uses volume ratio (current/average) and post-volume price direction:
        - ACCUMULATION: High vol + price UP → Buyers accumulated
        - DISTRIBUTION: High vol + price DOWN/FLAT → Sellers dumped
        - WEAK_ACCUM: Low vol + price UP → Weak buyers (caution)
        - NEUTRAL: Other combinations → No clear signal
        
        Returns dict with:
        - signal_type: Classification (ACCUM/DISTRIB/WEAK_ACCUM/NEUTRAL)
        - confidence_adjustment: Score adjustment (-50 to +25)
        - reason: Explanation string
        """
        if avg_volume <= 0:
            return {"signal_type": "NEUTRAL", "confidence_adjustment": 0, "reason": "No average volume"}
        
        volume_ratio = volume / avg_volume
        ratio_threshold = STRATEGY_CONFIG.get("volume_accumulation_ratio", 1.5)
        
        if not price_movement:
            return {"signal_type": "NEUTRAL", "confidence_adjustment": 0, "reason": "No price movement data"}
        
        direction = price_movement.get("direction_strength", "FLAT")
        is_high_volume = volume_ratio >= ratio_threshold
        
        # Classification logic
        if is_high_volume:
            if direction == "UP":
                return {
                    "signal_type": "ACCUMULATION",
                    "confidence_adjustment": 25,
                    "reason": f"High vol ({volume_ratio:.1f}x) + price UP = buyers accumulated"
                }
            elif direction in ["DOWN", "FLAT"]:
                return {
                    "signal_type": "DISTRIBUTION",
                    "confidence_adjustment": -50,
                    "reason": f"High vol ({volume_ratio:.1f}x) + price {direction} = distribution trap"
                }
        else:  # Low volume
            if direction == "UP":
                return {
                    "signal_type": "WEAK_ACCUM",
                    "confidence_adjustment": 5,
                    "reason": f"Low vol ({volume_ratio:.1f}x) + price UP = weak signal"
                }
        
        return {"signal_type": "NEUTRAL", "confidence_adjustment": 0, "reason": "No clear volume pattern"}
    
    def calculate_volume_score(self, symbol: str, current_price: float, current_volume: float, buf) -> float:
        """Calculate confidence adjustment based on volume and price action.
        
        Returns float adjustment (-50 to +25) to be added to base confidence score.
        Returns 0 if data is unavailable (graceful fallback).
        """
        try:
            # Get average volume from last 20 ticks
            volumes = buf.get_volumes() if buf else []
            if not buf or len(volumes) < 20:
                logger.warning(f"📊 VOLUME_CALC {symbol}: Insufficient volume data ({len(volumes) if buf else 0} ticks < 20 required) → +0%")
                return 0
            
            avg_volume = sum(volumes[-20:]) / 20
            if avg_volume <= 0:
                logger.warning(f"📊 VOLUME_CALC {symbol}: Avg volume is 0 → +0%")
                return 0
            
            # Analyze post-volume price movement
            price_movement = self.get_post_volume_price_movement(symbol, buf)
            if not price_movement:
                logger.warning(f"📊 VOLUME_CALC {symbol}: No price movement data → +0%")
                return 0
            
            # Classify the signal
            classification = self.classify_volume_signal(current_volume, avg_volume, price_movement)
            
            # Log the analysis
            signal_type = classification.get("signal_type", "UNKNOWN")
            adjustment = classification.get("confidence_adjustment", 0)
            reason = classification.get("reason", "")
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
            
            logger.warning(f"📊 VOLUME_CALC {symbol}: Vol={current_volume:.0f} Avg={avg_volume:.0f} Ratio={volume_ratio:.1f}x → {signal_type} {adjustment:+.0f}% ({reason})")
            
            return adjustment
            
        except Exception as e:
            logger.error(f"Error calculating volume score for {symbol}: {e}")
            return 0
    
    def get_current_metrics(self) -> dict:
        """Return current strategy metrics"""
        return {
            "total_ticks": self.metrics.total_ticks,
            "total_trades": self.metrics.total_trades,
            "closed_trades": len(self.closed_trades),
            "winning_trades": self.metrics.winning_trades,
            "losing_trades": self.metrics.losing_trades,
            "total_pnl": self.metrics.total_pnl,
            "daily_pnl": self.metrics.daily_pnl,
            "win_rate": self.metrics.win_rate,
            "max_drawdown": self.metrics.max_drawdown,
            "current_drawdown": self.metrics.current_drawdown,
            "consecutive_losses": self.metrics.consecutive_losses,
            "open_positions": len(self.current_positions),
        }
