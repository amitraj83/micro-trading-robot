# Market Data Module - Daily OHLCV + Support/Resistance
import random
from dataclasses import dataclass
from typing import Optional

@dataclass
class DailyMarketData:
    """Daily OHLCV and market context"""
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    todays_change_pct: float  # -0.456 means down 0.456%
    prev_close: float
    
    @property
    def daily_range(self) -> float:
        """High - Low"""
        return self.high_price - self.low_price
    
    @property
    def is_down_day(self) -> bool:
        """True if market is down today"""
        return self.todays_change_pct < 0
    
    @property
    def is_up_day(self) -> bool:
        """True if market is up today"""
        return self.todays_change_pct > 0
    
    @property
    def daily_bias(self) -> float:
        """
        Bias factor for entries:
        - Down day: SHORT bias = 1.5x (increase short probability)
        - Up day: LONG bias = 1.5x (increase long probability)
        - Returns: multiplier for direction probability
        """
        if self.is_down_day:
            return 1.5  # Favor SHORT
        elif self.is_up_day:
            return 1.5  # Favor LONG
        else:
            return 1.0  # Neutral


class MockMarketDataProvider:
    """Generates mock daily market data for testing"""
    
    def __init__(self, base_price: float = 160.0):
        self.base_price = base_price
        self.current_close = base_price
    
    def get_daily_data(self) -> DailyMarketData:
        """Generate realistic mock daily market data"""
        
        # Random daily change between -2% and +2%
        daily_change_pct = random.uniform(-0.02, 0.02)
        
        # Generate OHLCV based on daily change
        open_price = self.base_price
        close_price = open_price * (1 + daily_change_pct)
        
        # High/Low around the range
        if daily_change_pct > 0:
            # Up day: high above close, low near open
            high_price = close_price * 1.005
            low_price = open_price * 0.998
        else:
            # Down day: high near open, low below close
            high_price = open_price * 1.002
            low_price = close_price * 0.998
        
        # Random volume (realistic range)
        volume = random.randint(3_000_000, 5_000_000)
        
        # Previous close (yesterday's close)
        prev_close = self.base_price
        
        return DailyMarketData(
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
            volume=volume,
            todays_change_pct=daily_change_pct,
            prev_close=prev_close,
        )


class LiveMarketDataProvider:
    """Would fetch real market data from API (Polygon.io, Alpha Vantage, etc.)"""
    
    def get_daily_data(self) -> Optional[DailyMarketData]:
        """
        TODO: Implement API integration
        Example API: https://api.polygon.io/v1/open-close/AAPL/2025-12-30
        """
        raise NotImplementedError("API integration coming soon")
