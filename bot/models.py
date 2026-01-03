from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
import time

@dataclass
class Tick:
    """Single tick/trade data point"""
    price: float
    volume: int
    timestamp_ns: int
    symbol: str
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class Trade:
    """Executed trade record"""
    entry_time: datetime
    entry_price: float
    direction: str  # "LONG" or "SHORT"
    entry_reason: str  # "MOMENTUM_BURST"
    position_size: float = 1.0
    symbol: str = ""  # Trading symbol (e.g., "AAPL")
    position_id: int = 0  # NEW: Which range/position pair (1 or 2 for 2-position system)
    
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # "TP", "SL", "TIME", "FLAT"
    pnl: float = 0.0
    pnl_pct: float = 0.0
    best_favorable_pct: float = 0.0  # Tracks best run-up for trailing stops
    best_favorable_price: Optional[float] = None
    
    def is_closed(self) -> bool:
        return self.exit_time is not None
    
    def close(self, exit_price: float, exit_reason: str):
        """Close the trade"""
        self.exit_time = datetime.now()
        self.exit_price = exit_price
        self.exit_reason = exit_reason
        
        if self.direction == "LONG":
            self.pnl = (exit_price - self.entry_price) * self.position_size
            self.pnl_pct = (exit_price - self.entry_price) / self.entry_price
        else:  # SHORT
            self.pnl = (self.entry_price - exit_price) * self.position_size
            self.pnl_pct = (self.entry_price - exit_price) / self.entry_price
    
    def __str__(self):
        if self.is_closed():
            return (f"{self.direction} @ ${self.entry_price:.2f} → ${self.exit_price:.2f} "
                   f"({self.exit_reason}) | PnL: ${self.pnl:.2f} ({self.pnl_pct*100:.2f}%)")
        else:
            return f"{self.direction} @ ${self.entry_price:.2f} (OPEN)"


@dataclass
class StrategyMetrics:
    """Real-time metrics tracking"""
    total_ticks: int = 0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    daily_pnl: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    highest_equity: float = 100.0  # Starting equity
    lowest_equity: float = 100.0
    consecutive_losses: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    
    def update_from_closed_trade(self, trade: Trade):
        """Update metrics after trade closes"""
        self.total_trades += 1
        self.total_pnl += trade.pnl
        self.daily_pnl += trade.pnl
        
        if trade.pnl > 0:
            self.winning_trades += 1
            self.consecutive_losses = 0
            if self.avg_win == 0:
                self.avg_win = trade.pnl
            else:
                self.avg_win = (self.avg_win * (self.winning_trades - 1) + trade.pnl) / self.winning_trades
        else:
            self.losing_trades += 1
            self.consecutive_losses += 1
            if self.avg_loss == 0:
                self.avg_loss = trade.pnl
            else:
                self.avg_loss = (self.avg_loss * (self.losing_trades - 1) + trade.pnl) / self.losing_trades
        
        if self.total_trades > 0:
            self.win_rate = self.winning_trades / self.total_trades
        
        # Update equity tracking
        current_equity = 100.0 + self.total_pnl
        if current_equity > self.highest_equity:
            self.highest_equity = current_equity
        if current_equity < self.lowest_equity:
            self.lowest_equity = current_equity
        
        self.max_drawdown = min(self.max_drawdown, self.lowest_equity - 100.0)
        self.current_drawdown = self.highest_equity - current_equity
    
    def get_daily_loss_pct(self) -> float:
        """Return daily loss as percentage"""
        return self.daily_pnl / 100.0  # Assuming $100 starting capital
