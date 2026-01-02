from collections import deque
from typing import List, Optional
import statistics

# Handle both module and package import contexts
try:
    from models import Tick, Trade
    from config import STRATEGY_CONFIG, RISK_CONFIG
except ImportError:  # Fallback when imported as part of the bot package
    from bot.models import Tick, Trade
    from bot.config import STRATEGY_CONFIG, RISK_CONFIG


class TickBuffer:
    """Manage incoming ticks and calculate momentum metrics"""
    
    def __init__(self, window_size: int = STRATEGY_CONFIG["window_size"]):
        self.window_size = window_size
        self.ticks: deque = deque(maxlen=window_size)
    
    def add_tick(self, tick: Tick):
        """Add a new tick to the buffer"""
        self.ticks.append(tick)
    
    def is_ready(self) -> bool:
        """Check if we have enough data"""
        return len(self.ticks) >= 3  # Need at least 3 points for momentum
    
    def get_prices(self) -> List[float]:
        return [t.price for t in self.ticks]
    
    def get_volumes(self) -> List[int]:
        return [t.volume for t in self.ticks]
    
    def get_latest_price(self) -> Optional[float]:
        return self.ticks[-1].price if self.ticks else None
    
    def calculate_price_change(self) -> float:
        """Calculate total price change in window"""
        if len(self.ticks) < 2:
            return 0.0
        return (self.ticks[-1].price - self.ticks[0].price) / self.ticks[0].price
    
    def calculate_volatility(self) -> float:
        """Calculate volatility from price changes"""
        prices = self.get_prices()
        if len(prices) < 2:
            return 0.0
        
        # Guard against zero first price
        if prices[0] == 0:
            return 0.0
        
        # Normalize prices as % changes from first price
        normalized_changes = [(p / prices[0]) - 1 for p in prices]
        return statistics.stdev(normalized_changes) if len(normalized_changes) > 1 else 0.0
    
    def calculate_momentum(self) -> float:
        """Calculate recent price momentum (velocity)"""
        if len(self.ticks) < 2:
            return 0.0
        
        prices = self.get_prices()
        # Simple momentum: recent average move vs old average move
        mid = len(prices) // 2
        
        recent_move = (prices[-1] - prices[mid]) / prices[mid]
        old_move = (prices[mid] - prices[0]) / prices[0]
        
        return recent_move - old_move
    
    def calculate_avg_volume(self, exclude_latest: int = 2) -> float:
        """Calculate average volume using only last 5-10 ticks (recent volume baseline)
        
        This prevents early buffer warmup spikes from inflating the volume baseline.
        Instead of using the full rolling history, we use only the last 5-10 ticks
        to compute a more realistic "recent market activity" baseline.
        
        Args:
            exclude_latest: Number of latest ticks to exclude from average (default 2)
            
        Returns:
            Average volume of recent ticks (not full buffer history)
        """
        volumes = self.get_volumes()
        
        # Use only the last 5-10 ticks for "recent volume average"
        # This avoids early warmup spikes (500K+) inflating the baseline
        recent_window = 8  # Use last 8 ticks for baseline
        
        # Get ticks for averaging, excluding the specified count from end
        if exclude_latest > 0:
            volumes = volumes[:-exclude_latest]
        
        # Use only recent window
        if len(volumes) > recent_window:
            volumes = volumes[-recent_window:]
        
        return sum(volumes) / len(volumes) if volumes else 1
    
    def get_latest_volume(self) -> int:
        return self.ticks[-1].volume if self.ticks else 0
    
    def get_price_direction_streak(self) -> int:
        """
        Get consecutive up/down movements
        Returns: positive for up streak, negative for down streak
        """
        if len(self.ticks) < 2:
            return 0
        
        prices = self.get_prices()
        streak = 0
        
        for i in range(1, len(prices)):
            if prices[i] > prices[i-1]:
                streak = max(1, streak + 1) if streak >= 0 else 1
            elif prices[i] < prices[i-1]:
                streak = min(-1, streak - 1) if streak <= 0 else -1
            else:
                streak = 0
        
        return streak
    
    def get_net_direction_over_window(self, window_size: int = 5) -> float:
        """
        Check if price moved UP or DOWN over last N ticks (net direction bias)
        Returns: positive if price UP overall, negative if DOWN overall, 0 if flat
        Used for: Confirming trend direction without requiring consecutive same-direction ticks
        """
        if len(self.ticks) < 2:
            return 0
        
        prices = self.get_prices()
        
        # Use last window_size ticks, but take all if fewer available
        start_idx = max(0, len(prices) - window_size)
        window = prices[start_idx:]
        
        if len(window) < 2:
            return 0
        
        # Return net direction: final - initial price
        net_move = window[-1] - window[0]
        return net_move
    
    def get_last_n_price_changes(self, n: int = 5) -> List[float]:
        """Get last N price changes as percentages"""
        prices = self.get_prices()[-n-1:]
        if len(prices) < 2:
            return []
        
        return [(prices[i+1] - prices[i]) / prices[i] for i in range(len(prices)-1)]
    
    def get_last_n_ranges(self, n: int = 3) -> List[float]:
        """Get last N price ranges (high - low) as percentages"""
        if len(self.ticks) < n:
            return []
        
        recent_ticks = list(self.ticks)[-n:]
        ranges = []
        
        # For each tick, calculate its range
        for tick in recent_ticks:
            # Approximate range as absolute price change from previous
            # In real data this would be tick.high - tick.low
            # For tick-by-tick, we estimate from price movement
            ranges.append(getattr(tick, 'range', 0.0) or 0.0001)
        
        return ranges
    
    def get_last_n_volumes(self, n: int = 3) -> List[int]:
        """Get last N volumes"""
        if len(self.ticks) < n:
            return []
        
        return [t.volume for t in list(self.ticks)[-n:]]
    
    def calculate_avg_range(self) -> float:
        """Calculate average range from all ticks in buffer"""
        ranges = self.get_last_n_ranges(len(self.ticks))
        return sum(ranges) / len(ranges) if ranges else 0.0001
    
    def calculate_ema(self, period: int = 20) -> Optional[float]:
        """
        Calculate Exponential Moving Average
        
        Args:
            period: EMA period (default 20)
            
        Returns:
            EMA value or None if not enough ticks
        """
        prices = self.get_prices()
        if len(prices) < period:
            return None
        
        # Calculate simple moving average for first value
        k = 2 / (period + 1)  # Smoothing factor
        
        # Start with SMA
        sma = sum(prices[:period]) / period
        ema = sma
        
        # Calculate EMA for remaining prices
        for price in prices[period:]:
            ema = price * k + ema * (1 - k)
        
        return ema
    
    def calculate_ema_50(self) -> Optional[float]:
        """Calculate 50-period EMA (for trend detection) - uses 30 period for faster warmup"""
        return self.calculate_ema(period=30)  # Reduced from 50 for faster warmup
    
    def calculate_ema_20(self) -> Optional[float]:
        """Calculate 20-period EMA (for trailing stops)"""
        return self.calculate_ema(period=20)
    
    def calculate_true_range(self, idx: int) -> float:
        """
        Calculate true range at index
        
        TR = max(high - low, abs(high - previous_close), abs(low - previous_close))
        
        For tick-by-tick data, we approximate using price ticks
        """
        if idx <= 0 or idx >= len(self.ticks):
            return 0.0
        
        current = self.ticks[idx]
        previous = self.ticks[idx - 1]
        
        # Approximate high/low as price extremes in tick
        # In reality: high = current.high, low = current.low
        current_high = current.price  # Would be tick.high in OHLC data
        current_low = current.price   # Would be tick.low in OHLC data
        previous_close = previous.price
        
        # True range calculation
        high_low = current_high - current_low  # Usually very small for single tick
        high_prev = abs(current_high - previous_close)
        low_prev = abs(current_low - previous_close)
        
        return max(high_low, high_prev, low_prev)
    
    def calculate_atr(self, period: int = 14) -> Optional[float]:
        """
        Calculate Average True Range
        
        Args:
            period: ATR period (default 14)
            
        Returns:
            ATR value or None if not enough ticks
        """
        if len(self.ticks) < period:
            return None
        
        # Calculate true ranges for each tick
        true_ranges = [self.calculate_true_range(i) for i in range(len(self.ticks))]
        
        # Calculate ATR using smoothed average
        if len(true_ranges) >= period:
            atr = sum(true_ranges[:period]) / period
            
            # Smooth the ATR for remaining values
            for tr in true_ranges[period:]:
                atr = (atr * (period - 1) + tr) / period
            
            return atr
        
        return None
    
    def is_price_above_ema50(self) -> bool:
        """Check if current price is above EMA50 (uptrend)"""
        ema50 = self.calculate_ema_50()
        current_price = self.get_latest_price()
        
        if ema50 is None or current_price is None:
            return False
        
        return current_price > ema50
    
    def is_price_below_ema50(self) -> bool:
        """Check if current price is below EMA50 (downtrend)"""
        ema50 = self.calculate_ema_50()
        current_price = self.get_latest_price()
        
        if ema50 is None or current_price is None:
            return True
        
        return current_price < ema50
