#!/usr/bin/env python3
"""
Pre-download historical market data from Yahoo Finance and save to JSON file.
This avoids repeated API calls during testing and enables offline testing.

Usage:
    python download_historical_data.py                 # Download once
    python download_historical_data.py --regenerate    # Force refresh
"""

import json
import logging
from pathlib import Path
from datetime import datetime
import sys
import asyncio

# Add websocket_server to path for imports
sys.path.insert(0, str(Path(__file__).parent / "websocket_server"))

from yahoo_data_loader import YahooDataLoader

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HistoricalDataDownloader:
    """Downloads and caches historical market data to JSON file."""
    
    def __init__(self, 
                 output_path: str = "data/historical_data.json",
                 symbols: list = None,
                 days_back: int = 7,
                 interval: str = "1m"):
        """
        Initialize downloader.
        
        Args:
            output_path: Path to save JSON file
            symbols: List of symbols to download
            days_back: Number of days of history to download
            interval: Bar interval (1m, 5m, 1h, 1d, etc.)
        """
        self.output_path = Path(output_path)
        self.symbols = symbols or ["QQQ", "SPY", "NVDA", "AAPL", "MSFT"]
        self.days_back = days_back
        self.interval = interval
        
        # Create data directory if it doesn't exist
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
    
    async def download(self, force_regenerate: bool = False) -> bool:
        """
        Download historical data and save to JSON file.
        
        Args:
            force_regenerate: If True, download even if file exists
            
        Returns:
            True if successful, False otherwise
        """
        # Check if file already exists and skip if not forced
        if self.output_path.exists() and not force_regenerate:
            logger.info(f"Data file already exists: {self.output_path}")
            logger.info("Use --regenerate to force refresh")
            return True
        
        logger.info(f"Downloading {self.days_back}-day history for {len(self.symbols)} symbols...")
        logger.info(f"Symbols: {', '.join(self.symbols)}")
        
        try:
            # Create data loader
            loader = YahooDataLoader(
                symbols=self.symbols,
                days_back=self.days_back,
                interval=self.interval
            )
            
            # Download data (synchronous)
            if not loader.download_data():
                logger.error("Failed to download data from Yahoo Finance")
                return False
            
            # Get all bars
            bars = loader.convert_to_polygon_format()
            stats = loader.get_stats()
            
            # Create output JSON structure
            output_data = {
                "metadata": {
                    "downloaded_at": datetime.utcnow().isoformat() + "Z",
                    "symbols": self.symbols,
                    "days_back": self.days_back,
                    "interval": self.interval,
                    "total_bars": len(bars),
                    "bars_per_symbol": stats.get("bars_per_symbol", {}),
                    "date_range": {
                        "start": stats.get("start_date"),
                        "end": stats.get("end_date")
                    }
                },
                "bars": bars
            }
            
            # Save to JSON file
            with open(self.output_path, 'w') as f:
                json.dump(output_data, f, indent=2)
            
            logger.info(f"✓ Successfully downloaded {len(bars)} bars")
            logger.info(f"✓ Saved to {self.output_path}")
            logger.info(f"✓ Date range: {output_data['metadata']['date_range']['start']} to {output_data['metadata']['date_range']['end']}")
            logger.info(f"✓ Bars per symbol: {output_data['metadata']['bars_per_symbol']}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error downloading data: {e}", exc_info=True)
            return False


async def main():
    """Main entry point."""
    # Check for --regenerate flag
    force_regenerate = "--regenerate" in sys.argv
    
    if force_regenerate:
        logger.info("Force regenerating data (--regenerate flag)")
    
    # Create downloader and download
    downloader = HistoricalDataDownloader(
        output_path="data/historical_data.json",
        symbols=["QQQ", "SPY", "NVDA", "AAPL", "MSFT"],
        days_back=7,
        interval="1m"
    )
    
    success = await downloader.download(force_regenerate=force_regenerate)
    
    if success:
        logger.info("Data download complete. Ready for testing.")
        return 0
    else:
        logger.error("Data download failed.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
