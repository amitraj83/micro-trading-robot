#!/usr/bin/env python3
"""Test the dashboard data processing without tkinter mainloop"""

import asyncio
import json
import websockets
import threading
import time
from collections import deque

from bot.models import Tick
from bot.strategy_manager import StrategyManager
from bot.tick_logger import TickLogger
from bot.config import WEBSOCKET_CONFIG, SYMBOLS

class SimpleDashboardTest:
    def __init__(self, symbols=None):
        if symbols is None:
            symbols = SYMBOLS
        
        self.symbols = symbols
        self.prices = {sym: deque(maxlen=100) for sym in symbols}
        self.strategy_manager = StrategyManager(symbols)
        self.tick_counts = {sym: 0 for sym in symbols}
        self.logger = TickLogger()
        
        print(f"[INIT] Dashboard test initialized with {len(symbols)} symbols: {symbols}")
    
    def update_ui(self, data):
        """Process incoming WebSocket data"""
        try:
            symbols_data = data.get("symbols", {})
            print(f"\n[update_ui] Received data for {len(symbols_data)} symbols: {list(symbols_data.keys())}")
            
            total_pnl = 0.0
            total_trades = 0
            open_positions = 0
            
            for symbol, snapshot in symbols_data.items():
                print(f"[update_ui] Processing {symbol}...")
                self._process_symbol_tick(symbol, snapshot)
                
                # Calculate metrics
                strategy = self.strategy_manager.get_strategy(symbol)
                if strategy:
                    metrics = strategy.metrics
                    total_pnl += metrics.total_pnl
                    total_trades += metrics.total_trades
                    if strategy.current_position:
                        open_positions += 1
            
            print(f"[update_ui] Portfolio: P/L=${total_pnl:+.2f}, Trades={total_trades}, Open={open_positions}")
        
        except Exception as e:
            print(f"[ERROR] update_ui: {e}")
            import traceback
            traceback.print_exc()
    
    def _process_symbol_tick(self, symbol, snapshot):
        """Process tick for one symbol"""
        symbol = symbol.upper()
        
        try:
            # Extract data
            ticker = snapshot.get("ticker", {})
            day_data = ticker.get("day", {})
            
            price = day_data.get("c", 0)
            volume = day_data.get("v", 0)
            updated_ns = ticker.get("updated") or int(time.time() * 1e9)
            
            print(f"[_process_symbol_tick] {symbol}: Price=${price:.2f}, Volume={volume}")
            
            # Append to price history
            self.prices[symbol].append(price)
            self.tick_counts[symbol] += 1
            print(f"[_process_symbol_tick] {symbol}: Tick #{self.tick_counts[symbol]}")
            
            # Create Tick and process (correct parameters)
            tick = Tick(price=price, volume=volume, timestamp_ns=updated_ns, symbol=symbol)
            event = self.strategy_manager.process_tick(symbol, tick)
            
            print(f"[_process_symbol_tick] {symbol}: Strategy event - action={event.get('action')}, reason={event.get('reason')}")
            
            # Log the tick
            self.logger.log_tick(tick, event)
            print(f"[_process_symbol_tick] {symbol}: Tick logged")
        
        except Exception as e:
            print(f"[_process_symbol_tick] {symbol}: ERROR - {e}")
            import traceback
            traceback.print_exc()
    
    async def websocket_loop(self):
        """WebSocket connection loop"""
        uri = WEBSOCKET_CONFIG["uri"]
        print(f"[WebSocket] Connecting to {uri}...")
        
        async with websockets.connect(uri) as websocket:
            print(f"[WebSocket] Connected!")
            
            message_count = 0
            async for message in websocket:
                try:
                    data = json.loads(message)
                    print(f"[WebSocket] Message #{message_count + 1}: keys={list(data.keys())}")
                    
                    if "symbols" in data:
                        self.update_ui(data)
                    
                    message_count += 1
                    if message_count >= 5:
                        print(f"\n[TEST] Processed {message_count} messages. Test complete!")
                        return
                
                except Exception as e:
                    print(f"[WebSocket] Error: {e}")

async def main():
    dashboard = SimpleDashboardTest()
    await dashboard.websocket_loop()

if __name__ == "__main__":
    asyncio.run(main())
