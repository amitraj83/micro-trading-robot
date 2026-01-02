"""
Yahoo Finance Historical Data Loader
Downloads real market data from Yahoo Finance and converts to Polygon-like format
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class YahooDataLoader:
    """Load historical data from Yahoo Finance and format for bot"""
    
    def __init__(self, symbols: List[str], days_back: int = 7, interval: str = "1m"):
        """
        Initialize loader
        
        Args:
            symbols: List of stock symbols (e.g., ['QQQ', 'SPY', 'NVDA'])
            days_back: Days of history to fetch
            interval: Bar interval ('1m', '5m', '15m', '1h', '1d')
        """
        self.symbols = symbols
        self.days_back = days_back
        self.interval = interval
        self.data = None
        self.bar_iterator = None
        self.bars_list = []
        
    def download_data(self) -> bool:
        """Download data from Yahoo Finance"""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=self.days_back)
            
            logger.info(f"Downloading {self.days_back} days of {self.interval} data for: {self.symbols}")
            logger.info(f"Date range: {start_date.date()} to {end_date.date()}")
            
            self.data = yf.download(
                self.symbols,
                start=start_date,
                end=end_date,
                interval=self.interval,
                progress=False,
                threads=True
            )
            
            if self.data is None or len(self.data) == 0:
                logger.error("No data downloaded from Yahoo Finance")
                return False
            
            logger.info(f"✅ Downloaded {len(self.data)} bars")
            logger.info(f"Data shape: {self.data.shape}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to download data: {e}")
            return False
    
    def convert_to_polygon_format(self) -> List[Dict]:
        """
        Convert Yahoo Finance data to Polygon A (aggregate) bar format
        
        Returns:
            List of bars in Polygon format
        """
        if self.data is None:
            logger.error("No data loaded. Call download_data() first")
            return []
        
        bars = []
        
        # Handle single vs multiple symbols
        if len(self.symbols) == 1:
            # Single symbol - data is flat DataFrame
            df = self.data
            symbol = self.symbols[0]
            bars = self._process_single_symbol(df, symbol)
        else:
            # Multiple symbols - data is MultiIndex DataFrame
            for symbol in self.symbols:
                if symbol in self.data.columns.get_level_values(1):
                    df_symbol = self.data.xs(symbol, level=1, axis=1)
                    bars.extend(self._process_single_symbol(df_symbol, symbol))
        
        # Sort by timestamp
        bars.sort(key=lambda x: x['s'])
        self.bars_list = bars
        
        logger.info(f"✅ Converted {len(bars)} bars to Polygon format")
        return bars
    
    def _process_single_symbol(self, df: pd.DataFrame, symbol: str) -> List[Dict]:
        """Process single symbol DataFrame into Polygon bars"""
        bars = []
        
        for timestamp, row in df.iterrows():
            # Skip rows with NaN values
            if pd.isna(row).any():
                continue
            
            # Convert timestamp to milliseconds since epoch
            timestamp_ms = int(timestamp.timestamp() * 1000)
            timestamp_ns = timestamp_ms * 1_000_000
            
            bar = {
                "ev": "A",  # Aggregate bar event
                "sym": symbol,
                "v": int(row['Volume']),  # Volume
                "av": int(row['Volume']),  # Accumulated volume (same as volume)
                "op": float(row['Open']),  # Open
                "vw": float(row['Close']),  # VWAP (use close as proxy)
                "o": float(row['Open']),   # Open
                "c": float(row['Close']),  # Close
                "h": float(row['High']),   # High
                "l": float(row['Low']),    # Low
                "a": float(row['Close']),  # Session VWAP (use close as proxy)
                "z": 1,  # Trades in aggregate (dummy)
                "s": timestamp_ms,  # Start time
                "e": timestamp_ms + 60000,  # End time (1 min later)
                "n": 1  # Number of items in aggregate (dummy)
            }
            
            bars.append(bar)
        
        logger.info(f"  {symbol}: {len(bars)} bars")
        return bars
    
    def get_bars_iterator(self):
        """Get iterator over bars for streaming simulation"""
        if not self.bars_list:
            self.convert_to_polygon_format()
        
        self.bar_iterator = iter(self.bars_list)
        return self.bar_iterator
    
    def get_next_bar(self) -> Optional[Dict]:
        """Get next bar from iterator"""
        if self.bar_iterator is None:
            self.get_bars_iterator()
        
        try:
            return next(self.bar_iterator)
        except StopIteration:
            return None
    
    def reset_iterator(self):
        """Reset iterator to start"""
        self.bar_iterator = None
        if self.bars_list:
            self.bar_iterator = iter(self.bars_list)
    
    def get_stats(self) -> Dict:
        """Get data statistics"""
        if not self.bars_list:
            return {}
        
        stats = {
            "total_bars": len(self.bars_list),
            "symbols": self.symbols,
            "date_range": f"{datetime.fromtimestamp(self.bars_list[0]['s']/1000).date()} to {datetime.fromtimestamp(self.bars_list[-1]['s']/1000).date()}",
            "bars_per_symbol": {}
        }
        
        for symbol in self.symbols:
            count = sum(1 for bar in self.bars_list if bar['sym'] == symbol)
            stats["bars_per_symbol"][symbol] = count
        
        return stats
