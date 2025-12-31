from collections import deque
from typing import List, Optional
import statistics
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
        """Calculate price volatility (std dev) in window"""
        prices = self.get_prices()
        if len(prices) < 2:
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
    
    def calculate_avg_volume(self, exclude_latest: int = 1) -> float:
        """Calculate average volume excluding last N ticks"""
        volumes = self.get_volumes()[:-exclude_latest] if exclude_latest > 0 else self.get_volumes()
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
    
    def get_last_n_price_changes(self, n: int = 5) -> List[float]:
        """Get last N price changes as percentages"""
        prices = self.get_prices()[-n-1:]
        if len(prices) < 2:
            return []
        
        return [(prices[i+1] - prices[i]) / prices[i] for i in range(len(prices)-1)]
