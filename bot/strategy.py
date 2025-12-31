from typing import Optional, Tuple
from datetime import datetime
import time
from bot.models import Tick, Trade, StrategyMetrics
from bot.tick_buffer import TickBuffer
from bot.config import STRATEGY_CONFIG, RISK_CONFIG
from bot.rules import PROFESSIONAL_RULES
from bot.market_data import MockMarketDataProvider, DailyMarketData
import logging

logger = logging.getLogger(__name__)


class MicroTradingStrategy:
    """Momentum burst micro-trading strategy"""
    
    def __init__(self):
        self.tick_buffer = TickBuffer(STRATEGY_CONFIG["window_size"])
        self.current_position: Optional[Trade] = None
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
        
        # RULE 4.1: Risk per trade
        if self.current_position is not None:
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
        Check if conditions are met for entry (CFD-correct)
        
        STRICT ENTRY: Only enter on strong momentum + volume + direction confirmation
        Applies DAILY BIAS: DOWN days favor SHORT, UP days favor LONG
        
        LONG (BUY CFD): Profit when price goes UP
        SHORT (SELL CFD): Profit when price goes DOWN
        
        Returns: "LONG", "SHORT", or None
        """
        if not self.tick_buffer.is_ready():
            return None
        
        # RULE 1: Volatility filter check (PROFESSIONAL RULE)
        rule_1_ok, rule_1_msg = self.check_rule_1_volatility()
        if not rule_1_ok:
            logger.debug(rule_1_msg)
            return None
        
        # Check 2: Price momentum - explicit direction detection
        price_change = self.tick_buffer.calculate_price_change()
        price_direction_streak = self.tick_buffer.get_price_direction_streak()
        
        # Check 3: Direction confirmation - require streak (STRICTER)
        min_streak = STRATEGY_CONFIG.get("min_direction_streak", 3)
        if abs(price_direction_streak) < min_streak:
            logger.debug(f"Direction streak too weak: {price_direction_streak} < ±{min_streak}")
            return None
        
        # Check 4: Volume spike (STRICTER - 2.0x instead of 1.5x)
        current_volume = self.tick_buffer.get_latest_volume()
        avg_volume = self.tick_buffer.calculate_avg_volume()
        volume_spike = current_volume > avg_volume * STRATEGY_CONFIG["volume_spike_multiplier"]
        
        if not volume_spike:
            logger.debug(f"Volume spike insufficient: {current_volume} < {avg_volume * STRATEGY_CONFIG['volume_spike_multiplier']:.1f}")
            return None
        
        # Get daily bias
        daily_bias = self.current_daily_data.daily_bias if self.current_daily_data else 1.0
        daily_change = self.current_daily_data.todays_change_pct if self.current_daily_data else 0.0
        daily_context = "DOWN" if daily_change < 0 else "UP" if daily_change > 0 else "NEUTRAL"
        
        # CFD Entry Logic: STRICT confirmation with DAILY BIAS
        
        # LONG (BUY CFD) - Profit from UPTREND
        # Conditions: Price rising + strong momentum + volume spike + direction confirmed
        # Bias: Extra confidence on UP days (daily_bias = 1.5)
        if (price_change >= STRATEGY_CONFIG["entry_threshold"] and 
            price_direction_streak > 0):
            logger.info(f"🟢 LONG signal: change={price_change*100:.3f}%, streak={price_direction_streak}, vol_spike={current_volume/avg_volume:.1f}x | Daily {daily_context} ({daily_change:+.2f}%) bias={daily_bias}")
            return "LONG"
        
        # SHORT (SELL CFD) - Profit from DOWNTREND (only if enabled in config)
        # Conditions: Price falling + strong momentum + volume spike + direction confirmed
        # Bias: Extra confidence on DOWN days (daily_bias = 1.5)
        elif (price_change <= -STRATEGY_CONFIG["entry_threshold"] and 
              price_direction_streak < 0):
            # Check if SHORT/SELL positions are allowed
            from bot.config import ALLOW_SELL_POSITIONS
            if ALLOW_SELL_POSITIONS:
                logger.info(f"🔴 SHORT signal: change={price_change*100:.3f}%, streak={price_direction_streak}, vol_spike={current_volume/avg_volume:.1f}x | Daily {daily_context} ({daily_change:+.2f}%) bias={daily_bias}")
                return "SHORT"
            else:
                logger.info(f"⚪ SHORT signal filtered (ALLOW_SELL_POSITIONS=false): change={price_change*100:.3f}%, streak={price_direction_streak}")
                return None
        
        return None
    
    def check_exit_signals(self, current_price: float) -> Optional[str]:
        """
        Check if we should exit current position (CFD-correct)
        
        For CFD: 
        - LONG: Profit if price goes UP, Loss if price goes DOWN
        - SHORT: Profit if price goes DOWN, Loss if price goes UP
        
        Returns: "TP", "SL", "TIME", "FLAT", or None
        """
        if self.current_position is None:
            return None
        
        trade = self.current_position
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
        
        # RULE 4.1: Risk per trade
        if self.current_position is not None:
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
        if self.current_position is not None:
            exit_reason = self.check_exit_signals(tick.price)
            
            if exit_reason:
                trade_to_close = self.current_position
                self._close_position(tick.price, exit_reason)
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
                    self._open_position(tick.price, entry_signal)
                    event["action"] = "OPEN"
                    event["trade"] = self.current_position
                    event["reason"] = "MOMENTUM_BURST"
                else:
                    # Log why we didn't enter
                    no_trade_reasons = []
                    
                    # Check volatility
                    rule_1_ok, rule_1_msg = self.check_rule_1_volatility()
                    if not rule_1_ok:
                        no_trade_reasons.append(rule_1_msg)
                    
                    # Check direction streak
                    price_direction_streak = self.tick_buffer.get_price_direction_streak()
                    min_streak = STRATEGY_CONFIG.get("min_direction_streak", 3)
                    if abs(price_direction_streak) < min_streak:
                        no_trade_reasons.append(f"Direction streak weak: {price_direction_streak} (need ±{min_streak})")
                    
                    # Check volume
                    current_volume = self.tick_buffer.get_latest_volume()
                    avg_volume = self.tick_buffer.calculate_avg_volume()
                    volume_multiplier = STRATEGY_CONFIG["volume_spike_multiplier"]
                    if current_volume <= avg_volume * volume_multiplier:
                        no_trade_reasons.append(f"Volume low: {current_volume} (need >{avg_volume * volume_multiplier:.1f})")
                    
                    # Check price momentum
                    price_change = self.tick_buffer.calculate_price_change()
                    threshold = STRATEGY_CONFIG["entry_threshold"]
                    if abs(price_change) < threshold:
                        no_trade_reasons.append(f"Momentum weak: {abs(price_change)*100:.3f}% (need ≥{threshold*100:.3f}%)")
                    
                    combined_reason = " | ".join(no_trade_reasons) if no_trade_reasons else "No clear signal"
                    event["no_trade_reason"] = combined_reason
                    logger.debug(f"⚠️ No entry: {combined_reason}")
        else:
            event["no_trade_reason"] = "Buffer not ready (warming up)"
        
        event["metrics"] = self.get_current_metrics()
        return event
    
    def _open_position(self, entry_price: float, direction: str):
        """Open a new trade with daily market context"""
        daily_change = self.current_daily_data.todays_change_pct if self.current_daily_data else 0.0
        daily_context = "DOWN" if daily_change < 0 else "UP" if daily_change > 0 else "NEUTRAL"
        daily_bias = self.current_daily_data.daily_bias if self.current_daily_data else 1.0

        position_size, sizing_note = self._compute_position_size(entry_price)
        
        self.current_position = Trade(
            entry_time=datetime.now(),
            entry_price=entry_price,
            direction=direction,
            entry_reason="MOMENTUM_BURST",
            position_size=position_size,
        )
        logger.info(
            f"OPEN {direction} @ ${entry_price:.2f} | size {position_size:.0f} shares | "
            f"Daily {daily_context} ({daily_change:+.2f}%) bias={daily_bias:.1f}x | {sizing_note}"
        )
    
    def _close_position(self, exit_price: float, exit_reason: str):
        """Close the current position"""
        from datetime import timedelta
        
        if self.current_position is None:
            return
        
        self.current_position.close(exit_price, exit_reason)
        self.closed_trades.append(self.current_position)
        self.metrics.update_from_closed_trade(self.current_position)
        
        # Track hourly trade count
        self.hourly_trade_count += 1
        
        # Implement RULE 4.4: Cooldown after consecutive losses
        if self.current_position.pnl < 0:
            self.consecutive_losses_counter += 1
            
            if self.consecutive_losses_counter >= PROFESSIONAL_RULES.get("rule_4_4_cooldown_after_losses", {}).get("consecutive_losses_threshold", 2):
                cooldown_secs = PROFESSIONAL_RULES.get("rule_4_4_cooldown_after_losses", {}).get("cooldown_seconds", 300)
                self.cooldown_until = datetime.now() + timedelta(seconds=cooldown_secs)
                logger.warning(f"⏸️  RULE 4.4: Cooldown activated for {cooldown_secs}s after {self.consecutive_losses_counter} losses")
        else:
            self.consecutive_losses_counter = 0
        
        logger.info(f"CLOSE {self.current_position.direction} @ ${exit_price:.2f} ({exit_reason}) "
                   f"| PnL: ${self.current_position.pnl:.2f} ({self.current_position.pnl_pct*100:.2f}%)")
        
        self.current_position = None
    
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
            "open_position": self.current_position is not None,
        }
