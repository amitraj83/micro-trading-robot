from typing import Optional, Tuple
from datetime import datetime
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
    """Momentum burst micro-trading strategy"""
    
    def __init__(self):
        self.tick_buffer = TickBuffer(STRATEGY_CONFIG["window_size"])
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

    def _compute_position_size(self, entry_price: float) -> Tuple[float, str]:
        """Dynamic position sizing: risk % of equity / (stop distance), capped by leverage."""
        risk_pct = RISK_CONFIG.get("risk_per_trade_pct", 0)
        base_size = RISK_CONFIG.get("position_size", 1.0)
        min_size = max(RISK_CONFIG.get("min_position_size", 1), 1)
        stop_loss_pct = STRATEGY_CONFIG.get("stop_loss", 0)

        # If misconfigured, fall back to fixed size
        if risk_pct <= 0 or stop_loss_pct <= 0 or entry_price <= 0:
            return base_size, "fixed sizing (config fallback)"

        equity = 100.0 + self.metrics.total_pnl  # reference equity
        risk_dollars = equity * risk_pct
        per_share_risk = stop_loss_pct * entry_price

        if per_share_risk <= 0:
            return base_size, "fixed sizing (invalid per-share risk)"

        raw_shares = risk_dollars / per_share_risk
        shares = max(min_size, int(raw_shares))

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
        return float(shares), note
    
    def can_trade(self) -> Tuple[bool, Optional[str]]:
        """Check if we're allowed to trade based on ALL risk rules"""
        
        # RULE PRIORITY: Risk rules first
        
        # RULE 4.2: Daily loss limit (KILL SWITCH)
        daily_loss_pct = self.metrics.get_daily_loss_pct()
        if daily_loss_pct <= PROFESSIONAL_RULES["rule_4_2_daily_loss_limit"]["daily_loss_limit_pct"]:
            rule_msg = f"RULE 4.2 VIOLATED: Daily loss limit ({daily_loss_pct*100:.2f}%)"
            self.rules_violated_log.append(rule_msg)
            return False, rule_msg
        
        # RULE 4.1: Risk per trade - check if ANY symbol has open position
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
        
        if self.hourly_trade_count >= PROFESSIONAL_RULES["rule_4_3_max_trades_per_hour"]["max_trades_per_hour"]:
            rule_msg = f"RULE 4.3 VIOLATED: Max {PROFESSIONAL_RULES['rule_4_3_max_trades_per_hour']['max_trades_per_hour']} trades/hour reached"
            return False, rule_msg
        
        return True, None
    
    def check_rule_1_volatility(self) -> Tuple[bool, Optional[str]]:
        """RULE 1: Volatility filter - don't trade dead markets"""
        if not PROFESSIONAL_RULES["rule_1_volatility_filter"]["enabled"]:
            return True, None
        
        volatility = self.tick_buffer.calculate_volatility()
        min_threshold = PROFESSIONAL_RULES["rule_1_volatility_filter"]["min_range_pct"]
        
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
    
    def check_entry_signals(self) -> Optional[str]:
        """
        EMA50/EMA20-based entry logic with momentum and volume confirmation
        
        Entry: Trend detection via EMA50 + Flexible confirmation (momentum OR volume)
        
        LONG (BUY): Price > EMA50 (uptrend) + (Momentum ≥0.1% OR Volume ≥50% baseline)
        SHORT (SELL): Price < EMA50 (downtrend) + (Momentum ≥0.1% OR Volume ≥50% baseline)
        
        Returns: "LONG", "SHORT", or None
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
        
        # Confirmation thresholds - RELAXED for more frequent entries
        momentum_threshold = 0.0005  # 0.05% (was 0.1%)
        momentum_ok = abs(momentum_pct) >= momentum_threshold
        volume_ok = volume_ratio >= 0.3  # 30% of baseline volume (was 50%)
        strong_momentum = abs(momentum_pct) >= 0.001  # 0.1% (was 0.2%)
        
        # Get daily bias for context
        daily_bias = self.current_daily_data.daily_bias if self.current_daily_data else 1.0
        daily_change = self.current_daily_data.todays_change_pct if self.current_daily_data else 0.0
        daily_context = "DOWN" if daily_change < 0 else "UP" if daily_change > 0 else "NEUTRAL"
        
        # ✅ LONG ENTRY: Trend UP (price > EMA50) + (Momentum OR Volume)
        if current_price > ema50:
            # Check flexible confirmation: momentum OR volume
            momentum_status = "[PRIMARY]" if momentum_ok else "[INFO]"
            volume_status = "[OK]" if volume_ok else "[WEAK]"
            
            if momentum_ok or volume_ok:
                logger.info(
                    f"🟢 LONG ENTRY: Price ${current_price:.2f} > EMA50 ${ema50:.2f} | "
                    f"Momentum {momentum_status} {momentum_pct:+.3f}% | "
                    f"Volume {volume_status} {volume_ratio:.2f}x | "
                    f"EMA20 ${ema20:.2f} | "
                    f"Daily {daily_context} ({daily_change:+.2f}%)"
                )
                return "LONG"
            else:
                logger.debug(
                    f"LONG blocked: Price > EMA50 but no confirmation | "
                    f"Momentum {momentum_pct:+.3f}% (need ≥0.1%) | "
                    f"Volume {volume_ratio:.2f}x (need ≥0.5x)"
                )
        
        # ✅ SHORT ENTRY: Trend DOWN (price < EMA50) + (Momentum OR Volume)
        elif current_price < ema50:
            try:
                from config import ALLOW_SELL_POSITIONS
            except ImportError:
                from bot.config import ALLOW_SELL_POSITIONS

            if not ALLOW_SELL_POSITIONS:
                # Long-only mode: always allow LONG when shorts disabled
                # (mean-reversion fallback - price below EMA50 may bounce back up)
                logger.info(
                    f"🟢 LONG (fallback, shorts disabled): Price ${current_price:.2f} < EMA50 ${ema50:.2f} | "
                    f"Momentum {momentum_pct:+.3f}% | Volume {volume_ratio:.2f}x | EMA20 ${ema20:.2f}"
                )
                return "LONG"
            
            # Check flexible confirmation: momentum OR volume
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
        """
        Check if we should exit current position (CFD-correct)
        
        For CFD: 
        - LONG: Profit if price goes UP, Loss if price goes DOWN
        - SHORT: Profit if price goes DOWN, Loss if price goes UP
        
        Returns: "TP", "SL", "TIME", "FLAT", or None
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
    
    def can_trade(self) -> Tuple[bool, Optional[str]]:
        """Check if we're allowed to trade based on ALL risk rules"""
        from datetime import timedelta
        
        # RULE PRIORITY: Risk rules first
        
        # RULE 4.2: Daily loss limit (KILL SWITCH)
        daily_loss_pct = self.metrics.get_daily_loss_pct()
        if daily_loss_pct <= PROFESSIONAL_RULES.get("rule_4_2_daily_loss_limit", {}).get("daily_loss_limit_pct", -0.01):
            rule_msg = f"RULE 4.2 VIOLATED: Daily loss limit ({daily_loss_pct*100:.2f}%)"
            self.rules_violated_log.append(rule_msg)
            return False, rule_msg
        
        # RULE 4.1: Risk per trade - check if ANY symbol has open position
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
        
        max_trades_hour = PROFESSIONAL_RULES.get("rule_4_3_max_trades_per_hour", {}).get("max_trades_per_hour", 15)
        if self.hourly_trade_count >= max_trades_hour:
            rule_msg = f"RULE 4.3 VIOLATED: Max {max_trades_hour} trades/hour reached"
            return False, rule_msg
        
        return True, None
    
    def check_rule_1_volatility(self) -> Tuple[bool, Optional[str]]:
        """RULE 1: Volatility filter - don't trade dead markets"""
        rule_config = PROFESSIONAL_RULES.get("rule_1_volatility_filter", {})
        if not rule_config.get("enabled", True):
            return True, None
        
        volatility = self.tick_buffer.calculate_volatility()
        min_threshold = rule_config.get("min_range_pct", 0.002)
        
        if volatility < min_threshold:
            rule_msg = f"RULE 1 VIOLATED: Volatility too low ({volatility*100:.3f}% < {min_threshold*100:.3f}%)"
            self.rules_violated_log.append(rule_msg)
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
    
    def process_tick(self, tick: Tick) -> dict:
        """
        Main strategy loop for each tick
        Returns: event dict with trade actions
        """
        self.tick_buffer.add_tick(tick)
        self.metrics.total_ticks += 1
        
        # Fetch daily market data once per process_tick (optional: could cache for efficiency)
        self.current_daily_data = self.market_data_provider.get_daily_data()
        
        event = {
            "tick": tick,
            "action": None,
            "trade": None,
            "reason": None,
            "metrics": None,
            "no_trade_reason": None,  # NEW: Track why we didn't trade
        }
        
        # Update any open position
        if tick.symbol in self.current_positions:
            exit_reason = self.check_exit_signals(tick.symbol, tick.price)
            
            if exit_reason:
                trade_to_close = self.current_positions[tick.symbol]
                self._close_position(tick.symbol, tick.price, exit_reason)
                event["action"] = "CLOSE"
                event["trade"] = trade_to_close
                event["reason"] = exit_reason
                
                # Update loss counter
                if trade_to_close.pnl < 0:
                    self.consecutive_losses_counter += 1
                else:
                    self.consecutive_losses_counter = 0
        
        # Try to open new position
        elif self.tick_buffer.is_ready():
            can_trade, reason = self.can_trade()
            
            if not can_trade:
                event["no_trade_reason"] = reason
                logger.debug(f"⛔ Cannot trade: {reason}")
            else:
                entry_signal = self.check_entry_signals()
                
                if entry_signal:
                    self._open_position(tick.symbol, tick.price, entry_signal)
                    event["action"] = "OPEN"
                    event["trade"] = self.current_positions[tick.symbol]
                    event["reason"] = "MOMENTUM_BURST"
                else:
                    # New diagnostics aligned with EMA50 logic
                    diagnostics = []

                    # Volatility check
                    rule_1_ok, rule_1_msg = self.check_rule_1_volatility()
                    if not rule_1_ok:
                        diagnostics.append(rule_1_msg)

                    # Trend + confirmation check
                    ema50 = self.tick_buffer.calculate_ema_50()
                    ema20 = self.tick_buffer.calculate_ema_20()
                    current_price = self.tick_buffer.get_latest_price()
                    momentum_pct = self.tick_buffer.calculate_price_change()
                    current_volume = self.tick_buffer.get_latest_volume()
                    avg_volume = self.tick_buffer.calculate_avg_volume()
                    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
                    momentum_threshold = 0.001  # 0.1%
                    confirmation_ok = (abs(momentum_pct) >= momentum_threshold) or (volume_ratio >= 0.5)

                    if ema50 is None or current_price is None:
                        diagnostics.append("EMA window not ready")
                    else:
                        if current_price > ema50:
                            if not confirmation_ok:
                                diagnostics.append(
                                    f"Long blocked: momentum {momentum_pct:+.3f}% (<0.1%) and volume {volume_ratio:.2f}x (<0.5x)"
                                )
                        elif current_price < ema50:
                            try:
                                from config import ALLOW_SELL_POSITIONS
                            except ImportError:
                                from bot.config import ALLOW_SELL_POSITIONS

                            if not ALLOW_SELL_POSITIONS:
                                diagnostics.append("Short blocked: ALLOW_SELL_POSITIONS=false")
                            elif not confirmation_ok:
                                diagnostics.append(
                                    f"Short blocked: momentum {momentum_pct:+.3f}% (<0.1%) and volume {volume_ratio:.2f}x (<0.5x)"
                                )
                        else:
                            diagnostics.append("Price ~ EMA50 (no trend)")

                    combined_reason = " | ".join(diagnostics) if diagnostics else "No clear signal"
                    event["no_trade_reason"] = combined_reason
                    logger.debug(f"⚠️ No entry: {combined_reason}")
        else:
            event["no_trade_reason"] = "Buffer not ready (warming up)"
        
        event["metrics"] = self.get_current_metrics()
        return event
    
    def _open_position(self, symbol: str, entry_price: float, direction: str):
        """Open a new trade with daily market context"""
        daily_change = self.current_daily_data.todays_change_pct if self.current_daily_data else 0.0
        daily_context = "DOWN" if daily_change < 0 else "UP" if daily_change > 0 else "NEUTRAL"
        daily_bias = self.current_daily_data.daily_bias if self.current_daily_data else 1.0

        position_size, sizing_note = self._compute_position_size(entry_price)
        
        trade = Trade(
            entry_time=datetime.now(),
            entry_price=entry_price,
            direction=direction,
            entry_reason="MOMENTUM_BURST",
            position_size=position_size,
            symbol=symbol,
        )
        self.current_positions[symbol] = trade
        logger.info(
            f"OPEN {direction} @ ${entry_price:.2f} | size {position_size:.0f} shares | "
            f"Daily {daily_context} ({daily_change:+.2f}%) bias={daily_bias:.1f}x | {sizing_note}"
        )
    
    def _close_position(self, symbol: str, exit_price: float, exit_reason: str):
        """Close the current position"""
        from datetime import timedelta
        
        if symbol not in self.current_positions:
            return
        
        trade = self.current_positions[symbol]
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
        
        logger.info(f"CLOSE {trade.direction} @ ${exit_price:.2f} ({exit_reason}) "
                   f"| PnL: ${trade.pnl:.2f} ({trade.pnl_pct*100:.2f}%)")
        
        del self.current_positions[symbol]
    
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
