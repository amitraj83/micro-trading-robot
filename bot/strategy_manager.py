"""
Multi-symbol strategy manager.
Maintains independent strategy instances for each symbol.
Routes ticks to the appropriate strategy based on symbol.
"""

from typing import Dict, List, Any

# Support running both as a package import (bot.strategy_manager)
# and as a direct script/module import where the current working
# directory is the project root.
try:
    from strategy import MicroTradingStrategy
    from models import Tick
except ImportError:  # Fallback when imported as part of the bot package
    from bot.strategy import MicroTradingStrategy
    from bot.models import Tick


class StrategyManager:
    """Manages multiple trading strategies (one per symbol)."""
    
    def __init__(self, symbols: List[str]):
        """
        Initialize strategy manager with list of symbols.
        
        Args:
            symbols: List of ticker symbols (e.g., ["AAPL", "MSFT", "GOOGL", "TSLA"])
        """
        self.symbols = symbols
        self.strategies: Dict[str, MicroTradingStrategy] = {}
        
        # Initialize strategy for each symbol
        for symbol in symbols:
            self.strategies[symbol] = MicroTradingStrategy()
        
        print(f"[StrategyManager] Initialized {len(symbols)} strategies: {symbols}")

    def add_symbol(self, symbol: str):
        symbol = symbol.upper()
        if symbol in self.strategies:
            return
        self.symbols.append(symbol)
        self.strategies[symbol] = MicroTradingStrategy()
        print(f"[StrategyManager] Added strategy for {symbol}")

    def remove_symbol(self, symbol: str):
        symbol = symbol.upper()
        if symbol in self.strategies:
            self.strategies.pop(symbol)
        if symbol in self.symbols:
            self.symbols = [s for s in self.symbols if s != symbol]
        print(f"[StrategyManager] Removed strategy for {symbol}")
    
    def process_tick(self, symbol: str, tick: Tick) -> Dict[str, Any]:
        """
        Process a tick for a specific symbol.
        
        Args:
            symbol: Ticker symbol (e.g., "AAPL")
            tick: Tick data
            
        Returns:
            Event dict from strategy (action, reason, trade, metrics)
        """
        symbol = symbol.upper()
        
        if symbol not in self.strategies:
            print(f"[StrategyManager] Warning: {symbol} not in managed symbols")
            return {"action": None, "reason": "unknown_symbol"}
        
        return self.strategies[symbol].process_tick(tick)
    
    def get_strategy(self, symbol: str) -> MicroTradingStrategy:
        """Get strategy instance for a symbol."""
        return self.strategies.get(symbol.upper())
    
    def get_all_strategies(self) -> Dict[str, MicroTradingStrategy]:
        """Get all strategy instances."""
        return self.strategies
    
    def get_open_positions(self) -> Dict[str, Any]:
        """Get open positions across all symbols."""
        positions = {}
        for symbol, strategy in self.strategies.items():
            if strategy.open_trade:
                positions[symbol] = strategy.open_trade
        return positions
    
    def get_metrics(self, symbol: str = None) -> Dict[str, Any]:
        """
        Get metrics for a symbol or all symbols.
        
        Args:
            symbol: Optional symbol; if None, returns metrics for all
            
        Returns:
            Metrics dict
        """
        if symbol:
            strategy = self.strategies.get(symbol.upper())
            if strategy:
                return strategy.metrics
            return {}
        
        # Return all metrics
        all_metrics = {}
        for sym, strategy in self.strategies.items():
            all_metrics[sym] = strategy.metrics
        return all_metrics
