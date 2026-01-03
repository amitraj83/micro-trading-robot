"""
Bar Aggregator - Converts ticks into OHLC bars for trend analysis

For 1-2 hour trend trading, we need timeframe-appropriate EMAs:
- 1-minute bars with EMA20 = 20 minutes of trend data
- 1-minute bars with EMA50 = 50 minutes of trend data  
- 5-minute bars with EMA20 = 100 minutes (~1.5 hours) of trend data

This module aggregates incoming ticks into proper OHLC bars and calculates
EMAs on those bars for multi-hour trend detection.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict


@dataclass
class Bar:
    """OHLC Bar representation"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    tick_count: int = 0
    
    def update(self, price: float, volume: int = 0):
        """Update bar with new tick"""
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += volume
        self.tick_count += 1


@dataclass
class TrendState:
    """Current trend state from EMA analysis"""
    direction: str  # "UP", "DOWN", "FLAT"
    ema_fast: float  # EMA20 value
    ema_slow: float  # EMA50 value
    price: float  # Current bar close
    strength: float  # Distance between EMAs as % of price
    bars_in_trend: int  # How many bars trend has persisted
    crossover: bool  # True if crossover just happened
    crossover_type: Optional[str]  # "GOLDEN" (bullish) or "DEATH" (bearish)


class BarAggregator:
    """
    Aggregates ticks into time-based bars and calculates EMAs for trend detection.
    
    For 1-2 hour trends:
    - bar_interval_seconds=60 (1-minute bars)
    - EMA20 on 1-min bars = 20 minutes of data
    - EMA50 on 1-min bars = 50 minutes of data
    
    For multi-hour trends:
    - bar_interval_seconds=300 (5-minute bars)
    - EMA20 on 5-min bars = 100 minutes (~1.5 hours) of data
    - EMA50 on 5-min bars = 250 minutes (~4 hours) of data
    """
    
    def __init__(
        self,
        bar_interval_seconds: int = 60,  # 1-minute bars by default
        ema_fast_period: int = 20,
        ema_slow_period: int = 50,
        max_bars: int = 200  # Keep last 200 bars in memory
    ):
        self.bar_interval_seconds = bar_interval_seconds
        self.ema_fast_period = ema_fast_period
        self.ema_slow_period = ema_slow_period
        self.max_bars = max_bars
        
        # Per-symbol bar storage
        self.bars: Dict[str, deque] = {}  # {symbol: deque of Bar}
        self.current_bar: Dict[str, Optional[Bar]] = {}  # {symbol: current incomplete bar}
        self.bar_start_time: Dict[str, Optional[datetime]] = {}  # {symbol: bar start timestamp}
        
        # EMA state per symbol
        self.ema_fast: Dict[str, Optional[float]] = {}
        self.ema_slow: Dict[str, Optional[float]] = {}
        self.prev_ema_fast: Dict[str, Optional[float]] = {}
        self.prev_ema_slow: Dict[str, Optional[float]] = {}
        
        # Trend tracking
        self.trend_direction: Dict[str, str] = {}  # {symbol: "UP"/"DOWN"/"FLAT"}
        self.bars_in_trend: Dict[str, int] = {}
    
    def _init_symbol(self, symbol: str):
        """Initialize storage for a new symbol"""
        if symbol not in self.bars:
            self.bars[symbol] = deque(maxlen=self.max_bars)
            self.current_bar[symbol] = None
            self.bar_start_time[symbol] = None
            self.ema_fast[symbol] = None
            self.ema_slow[symbol] = None
            self.prev_ema_fast[symbol] = None
            self.prev_ema_slow[symbol] = None
            self.trend_direction[symbol] = "FLAT"
            self.bars_in_trend[symbol] = 0
    
    def add_tick(self, symbol: str, price: float, volume: int = 0, timestamp: Optional[datetime] = None) -> Optional[Bar]:
        """
        Add a tick and aggregate into bars.
        
        Returns: Completed Bar if a bar just closed, None otherwise
        """
        self._init_symbol(symbol)
        
        if timestamp is None:
            timestamp = datetime.now()
        
        completed_bar = None
        
        # Check if we need to start a new bar
        if self.current_bar[symbol] is None:
            # Start first bar
            self.current_bar[symbol] = Bar(
                timestamp=timestamp,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
                tick_count=1
            )
            self.bar_start_time[symbol] = timestamp
        else:
            # Check if current bar should close
            elapsed = (timestamp - self.bar_start_time[symbol]).total_seconds()
            
            if elapsed >= self.bar_interval_seconds:
                # Close current bar and save it
                completed_bar = self.current_bar[symbol]
                self.bars[symbol].append(completed_bar)
                
                # Update EMAs with the completed bar
                self._update_emas(symbol, completed_bar.close)
                
                # Start new bar
                self.current_bar[symbol] = Bar(
                    timestamp=timestamp,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=volume,
                    tick_count=1
                )
                self.bar_start_time[symbol] = timestamp
            else:
                # Update current bar
                self.current_bar[symbol].update(price, volume)
        
        return completed_bar
    
    def _update_emas(self, symbol: str, close_price: float):
        """Update EMAs with new bar close price"""
        bars_list = list(self.bars[symbol])
        num_bars = len(bars_list)
        
        # Store previous values for crossover detection
        self.prev_ema_fast[symbol] = self.ema_fast[symbol]
        self.prev_ema_slow[symbol] = self.ema_slow[symbol]
        
        # Calculate fast EMA (EMA20)
        if num_bars >= self.ema_fast_period:
            if self.ema_fast[symbol] is None:
                # Initialize with SMA
                closes = [b.close for b in bars_list[-self.ema_fast_period:]]
                self.ema_fast[symbol] = sum(closes) / len(closes)
            else:
                # Update EMA
                k = 2 / (self.ema_fast_period + 1)
                self.ema_fast[symbol] = close_price * k + self.ema_fast[symbol] * (1 - k)
        
        # Calculate slow EMA (EMA50)
        if num_bars >= self.ema_slow_period:
            if self.ema_slow[symbol] is None:
                # Initialize with SMA
                closes = [b.close for b in bars_list[-self.ema_slow_period:]]
                self.ema_slow[symbol] = sum(closes) / len(closes)
            else:
                # Update EMA
                k = 2 / (self.ema_slow_period + 1)
                self.ema_slow[symbol] = close_price * k + self.ema_slow[symbol] * (1 - k)
        
        # Update trend direction
        self._update_trend_direction(symbol)
    
    def _update_trend_direction(self, symbol: str):
        """Update trend direction based on EMA relationship"""
        if self.ema_fast[symbol] is None or self.ema_slow[symbol] is None:
            self.trend_direction[symbol] = "FLAT"
            self.bars_in_trend[symbol] = 0
            return
        
        prev_direction = self.trend_direction[symbol]
        
        # Determine new direction
        if self.ema_fast[symbol] > self.ema_slow[symbol]:
            new_direction = "UP"
        elif self.ema_fast[symbol] < self.ema_slow[symbol]:
            new_direction = "DOWN"
        else:
            new_direction = "FLAT"
        
        # Track trend persistence
        if new_direction == prev_direction:
            self.bars_in_trend[symbol] += 1
        else:
            self.bars_in_trend[symbol] = 1
        
        self.trend_direction[symbol] = new_direction
    
    def get_trend_state(self, symbol: str) -> Optional[TrendState]:
        """
        Get current trend state for a symbol.
        
        Returns TrendState with:
        - direction: "UP" (bullish), "DOWN" (bearish), "FLAT" (no trend)
        - ema_fast/ema_slow: Current EMA values
        - strength: How far apart the EMAs are (trend strength)
        - bars_in_trend: How long the trend has persisted
        - crossover: True if a crossover just happened
        - crossover_type: "GOLDEN" (bullish) or "DEATH" (bearish)
        """
        self._init_symbol(symbol)
        
        if self.ema_fast[symbol] is None or self.ema_slow[symbol] is None:
            return None
        
        # Get current price from current bar or last completed bar
        current_price = None
        if self.current_bar[symbol]:
            current_price = self.current_bar[symbol].close
        elif self.bars[symbol]:
            current_price = self.bars[symbol][-1].close
        
        if current_price is None:
            return None
        
        # Calculate trend strength (EMA separation as % of price)
        strength = abs(self.ema_fast[symbol] - self.ema_slow[symbol]) / current_price
        
        # Detect crossover
        crossover = False
        crossover_type = None
        
        if self.prev_ema_fast[symbol] is not None and self.prev_ema_slow[symbol] is not None:
            prev_fast_above = self.prev_ema_fast[symbol] > self.prev_ema_slow[symbol]
            curr_fast_above = self.ema_fast[symbol] > self.ema_slow[symbol]
            
            if not prev_fast_above and curr_fast_above:
                crossover = True
                crossover_type = "GOLDEN"  # Bullish crossover
            elif prev_fast_above and not curr_fast_above:
                crossover = True
                crossover_type = "DEATH"  # Bearish crossover
        
        return TrendState(
            direction=self.trend_direction[symbol],
            ema_fast=self.ema_fast[symbol],
            ema_slow=self.ema_slow[symbol],
            price=current_price,
            strength=strength,
            bars_in_trend=self.bars_in_trend[symbol],
            crossover=crossover,
            crossover_type=crossover_type
        )
    
    def is_ready(self, symbol: str) -> bool:
        """Check if we have enough bars for EMA calculation"""
        self._init_symbol(symbol)
        return len(self.bars[symbol]) >= self.ema_slow_period
    
    def get_bars_count(self, symbol: str) -> int:
        """Get number of completed bars for symbol"""
        self._init_symbol(symbol)
        return len(self.bars[symbol])
    
    def get_warmup_progress(self, symbol: str) -> float:
        """Get warmup progress as percentage (0.0 to 1.0)"""
        self._init_symbol(symbol)
        return min(1.0, len(self.bars[symbol]) / self.ema_slow_period)
    
    def get_last_n_bars(self, symbol: str, n: int = 10) -> List[Bar]:
        """Get last N completed bars"""
        self._init_symbol(symbol)
        bars_list = list(self.bars[symbol])
        return bars_list[-n:] if bars_list else []
    
    def get_current_bar(self, symbol: str) -> Optional[Bar]:
        """Get the current incomplete bar"""
        self._init_symbol(symbol)
        return self.current_bar[symbol]


# Convenience function to create a bar aggregator for different timeframes
def create_trend_aggregator(timeframe: str = "1m") -> BarAggregator:
    """
    Create a BarAggregator configured for specific timeframe.
    
    Args:
        timeframe: "1m" (1-minute), "5m" (5-minute), "15m" (15-minute)
        
    Returns:
        Configured BarAggregator
    """
    configs = {
        "1m": {"bar_interval_seconds": 60, "ema_fast": 20, "ema_slow": 50},
        "5m": {"bar_interval_seconds": 300, "ema_fast": 20, "ema_slow": 50},
        "15m": {"bar_interval_seconds": 900, "ema_fast": 12, "ema_slow": 26},
    }
    
    config = configs.get(timeframe, configs["1m"])
    
    return BarAggregator(
        bar_interval_seconds=config["bar_interval_seconds"],
        ema_fast_period=config["ema_fast"],
        ema_slow_period=config["ema_slow"]
    )
