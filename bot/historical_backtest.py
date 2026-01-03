"""
Historical Backtest Engine
Download real market data from Yahoo Finance and replay through bot strategy
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import yfinance as yf
import pandas as pd
import time

# Support both package and module execution
try:
    from models import Tick
    from config import SYMBOLS as DEFAULT_SYMBOLS
except ImportError:  # When run as package (python -m bot.historical_backtest)
    from bot.models import Tick
    from bot.config import SYMBOLS as DEFAULT_SYMBOLS

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)


class HistoricalBacktestEngine:
    """
    Download historical OHLCV data and replay through bot
    """
    
    def __init__(self, symbols: Optional[List[str]] = None, days: int = 7):
        self.symbols = symbols or DEFAULT_SYMBOLS
        self.days = days
        self.data = None
        self.start_date = None
        self.end_date = None
        
    def download_data(self) -> pd.DataFrame:
        """
        Download 1-minute OHLCV bars from Yahoo Finance
        
        Returns:
            DataFrame with multi-index columns (OHLCV, Symbol)
        """
        self.end_date = datetime.now()
        self.start_date = self.end_date - timedelta(days=self.days)
        
        logger.info(f"📥 Downloading {len(self.symbols)} symbols from {self.start_date.date()} to {self.end_date.date()}")
        logger.info(f"   Symbols: {', '.join(self.symbols)}")
        
        try:
            self.data = yf.download(
                self.symbols,
                start=self.start_date,
                end=self.end_date,
                interval="1m",
                progress=False
            )
            
            if self.data is None or len(self.data) == 0:
                logger.error("❌ No data downloaded")
                return None
            
            logger.info(f"✅ Downloaded {len(self.data)} bars")
            logger.info(f"   Shape: {self.data.shape} (bars × OHLCV×symbols)")
            logger.info(f"   Date range: {self.data.index[0]} to {self.data.index[-1]}")
            
            # Log completeness per symbol
            for sym in self.symbols:
                if ('Close', sym) in self.data.columns:
                    non_null = self.data[('Close', sym)].notna().sum()
                    logger.info(f"   {sym}: {non_null} bars")
            
            return self.data
            
        except Exception as e:
            logger.error(f"❌ Download failed: {type(e).__name__}: {e}")
            return None
    
    def convert_row_to_polygon_bar(self, row: pd.Series, symbol: str, timestamp: pd.Timestamp) -> dict:
        """
        Convert pandas row to Polygon-like bar format
        
        Args:
            row: pandas Series with OHLCV data
            symbol: stock symbol
            timestamp: bar timestamp
            
        Returns:
            Dict matching Polygon aggregate bar format
        """
        # Handle multi-index columns (when multiple symbols)
        try:
            open_price = row[('Open', symbol)]
            high = row[('High', symbol)]
            low = row[('Low', symbol)]
            close = row[('Close', symbol)]
            volume = row[('Volume', symbol)]
        except (KeyError, TypeError):
            # Single symbol case (no multi-index)
            open_price = row['Open']
            high = row['High']
            low = row['Low']
            close = row['Close']
            volume = row['Volume']
        
        # Skip if any data is NaN
        if pd.isna([open_price, high, low, close, volume]).any():
            return None
        
        # Convert to Polygon bar format
        timestamp_ns = int(timestamp.timestamp() * 1e9)
        
        bar = {
            "ev": "A",  # Aggregate bar event
            "sym": symbol,
            "v": int(volume),  # Volume
            "av": int(volume),  # Aggregate volume (same as volume)
            "op": float(open_price),  # Open price
            "vw": float(close),  # VWAP (approximate with close for simplicity)
            "o": float(open_price),
            "c": float(close),
            "h": float(high),
            "l": float(low),
            "a": float(close),  # Session VWAP (approximate with close)
            "z": 1,  # Number of transactions
            "s": int(timestamp.timestamp()),  # Start time (seconds)
            "e": int(timestamp.timestamp()) + 60,  # End time (seconds)
            "t": timestamp_ns,  # Timestamp (nanoseconds)
        }
        
        return bar
    
    def get_bars_chronologically(self) -> List[tuple]:
        """
        Yield bars in chronological order across all symbols
        
        Yields:
            (timestamp, symbol, bar_dict) tuples
        """
        if self.data is None:
            logger.error("❌ No data loaded. Call download_data() first.")
            return
        
        # Iterate through timestamps (rows)
        for timestamp, row in self.data.iterrows():
            # For each symbol, yield the bar
            for symbol in self.symbols:
                try:
                    bar = self.convert_row_to_polygon_bar(row, symbol, timestamp)
                    if bar is not None:
                        yield (timestamp, symbol, bar)
                except Exception as e:
                    logger.debug(f"Skipping {symbol} at {timestamp}: {e}")
    
    async def run_backtest(self, handle_bar_func):
        """
        Replay bars through bot's handle_bar function
        
        Args:
            handle_bar_func: async function(bar_dict) to process each bar
        """
        if self.data is None:
            logger.error("❌ No data loaded. Call download_data() first.")
            return
        
        logger.info("\n" + "="*80)
        logger.info("🚀 STARTING HISTORICAL BACKTEST")
        logger.info("="*80)
        
        bar_count = 0
        start_time = time.time()
        
        try:
            # Feed bars chronologically to bot
            for timestamp, symbol, bar in self.get_bars_chronologically():
                try:
                    # Call bot's handle_bar (awaitable)
                    await handle_bar_func(bar)
                    bar_count += 1
                    
                    # Progress indicator every 100 bars
                    if bar_count % 100 == 0:
                        elapsed = time.time() - start_time
                        bars_per_sec = bar_count / elapsed
                        logger.info(f"   Processed {bar_count} bars ({bars_per_sec:.0f} bars/sec)")
                        
                except Exception as e:
                    logger.error(f"❌ Error processing bar {bar_count}: {e}")
                    continue
            
            elapsed = time.time() - start_time
            logger.info("\n" + "="*80)
            logger.info(f"✅ BACKTEST COMPLETE")
            logger.info(f"   Total bars: {bar_count}")
            logger.info(f"   Time elapsed: {elapsed:.1f}s")
            logger.info(f"   Speed: {bar_count/elapsed:.0f} bars/sec")
            logger.info("="*80 + "\n")
            
        except KeyboardInterrupt:
            logger.info("\n⏹️  Backtest interrupted by user")
        except Exception as e:
            logger.error(f"❌ Backtest failed: {e}")


async def run_historical_backtest_simple(
    symbols: Optional[List[str]] = None,
    days: int = 7,
    handle_bar_func = None
):
    """
    Simple wrapper to run backtest
    
    Usage:
        from bot.historical_backtest import run_historical_backtest_simple
        from bot.bot import handle_bar
        
        await run_historical_backtest_simple(
            symbols=["QQQ", "SPY"],
            days=7,
            handle_bar_func=handle_bar
        )
    """
    engine = HistoricalBacktestEngine(symbols=symbols, days=days)
    
    # Download data
    if engine.download_data() is None:
        logger.error("❌ Failed to download data")
        return
    
    # Run backtest
    if handle_bar_func is None:
        logger.error("❌ handle_bar_func required")
        return
    
    await engine.run_backtest(handle_bar_func)


if __name__ == "__main__":
    # Example: run backtest with default symbols
    import sys
    import os
    
    # You can override symbols via command line
    # python -m bot.historical_backtest QQQ SPY NVDA
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["QQQ"]
    
    logger.info(f"Running historical backtest with symbols: {symbols}")
    
    # SET SYMBOLS in environment BEFORE importing bot
    # This ensures bot initializes states for correct symbols
    os.environ["SYMBOLS"] = ",".join(symbols)
    os.environ["FAKE_TICKS"] = "true"  # Use fake mode (data loaded from file, not WS)
    
    # CRITICAL: Import bot AFTER setting SYMBOLS
    # This ensures bot.states is initialized with correct symbols
    from bot.bot import handle_bar, states
    
    logger.info(f"✅ Bot initialized with {len(states)} symbols: {list(states.keys())}")
    
    # Run backtest
    asyncio.run(run_historical_backtest_simple(
        symbols=symbols,
        days=7,
        handle_bar_func=handle_bar
    ))
