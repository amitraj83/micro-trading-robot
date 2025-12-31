"""
Multi-Symbol Trading Dashboard
2x2 grid layout showing 4 symbols simultaneously.
"""

import asyncio
import json
import websockets
import tkinter as tk
from tkinter import ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from collections import deque
from datetime import datetime
import threading
import time

from bot.models import Tick
from bot.strategy_manager import StrategyManager
from bot.tick_logger import TickLogger
from bot.config import WEBSOCKET_CONFIG, SYMBOLS

# Configuration
MAX_DATA_POINTS = 100


class MultiSymbolDashboard:
    def __init__(self, root, symbols=None):
        if symbols is None:
            symbols = SYMBOLS
        
        self.root = root
        self.symbols = symbols
        self.root.title(f"Micro Trading Bot - Multi-Symbol ({len(symbols)} tickers)")
        self.root.geometry("1600x1000")
        
        # Data storage per symbol
        self.prices = {sym: deque(maxlen=MAX_DATA_POINTS) for sym in symbols}
        self.bid_prices = {sym: deque(maxlen=MAX_DATA_POINTS) for sym in symbols}
        self.ask_prices = {sym: deque(maxlen=MAX_DATA_POINTS) for sym in symbols}
        self.buy_signals = {sym: deque() for sym in symbols}  # (x, price, trade_id)
        self.sell_signals = {sym: deque() for sym in symbols}
        self.buy_close_signals = {sym: deque() for sym in symbols}
        self.sell_close_signals = {sym: deque() for sym in symbols}
        
        # Trading state
        self.strategy_manager = StrategyManager(symbols)
        self.tick_counts = {sym: 0 for sym in symbols}
        self.trade_counters = {sym: 0 for sym in symbols}
        self.connection_status = "Disconnected"
        self.logger = TickLogger()
        
        # UI components
        self.chart_frames = {}  # {symbol: {'canvas': ..., 'ax': ..., ...}}
        self.stat_labels = {}   # {symbol: {'price': ..., 'pnl': ..., ...}}
        self.event_texts = {}   # {symbol: tk.Text}
        
        # Setup UI
        self.setup_ui()
        
        # Start WebSocket connection in background thread
        self.ws_thread = threading.Thread(target=self.start_websocket, daemon=True)
        self.ws_thread.start()
    
    def setup_ui(self):
        """Setup the UI with 2x2 grid layout"""
        # Main container
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Header frame
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Title
        title_label = ttk.Label(header_frame, text=f"🤖 Multi-Symbol Trading Bot ({len(self.symbols)} tickers)", 
                               font=("Arial", 14, "bold"))
        title_label.pack(side=tk.LEFT)
        
        # Status
        self.status_label = ttk.Label(header_frame, text="Status: Connecting...", 
                                      font=("Arial", 10))
        self.status_label.pack(side=tk.RIGHT)
        
        # Global stats frame
        global_stats_frame = ttk.LabelFrame(main_frame, text="Portfolio Stats", padding=10)
        global_stats_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.global_pnl_label = ttk.Label(global_stats_frame, text="Total P/L: --", 
                                         font=("Arial", 11, "bold"))
        self.global_pnl_label.pack(side=tk.LEFT, padx=20)
        
        self.global_trades_label = ttk.Label(global_stats_frame, text="Trades: 0", 
                                            font=("Arial", 10))
        self.global_trades_label.pack(side=tk.LEFT, padx=20)
        
        self.open_positions_label = ttk.Label(global_stats_frame, text="Open Positions: 0/4", 
                                             font=("Arial", 10))
        self.open_positions_label.pack(side=tk.LEFT, padx=20)
        
        # 2x2 Grid for charts
        grid_frame = ttk.Frame(main_frame)
        grid_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        grid_frame.grid_rowconfigure(0, weight=1)
        grid_frame.grid_rowconfigure(1, weight=1)
        grid_frame.grid_columnconfigure(0, weight=1)
        grid_frame.grid_columnconfigure(1, weight=1)
        
        for i, symbol in enumerate(self.symbols):
            row = i // 2
            col = i % 2
            self.create_symbol_chart(grid_frame, symbol, row, col)
        
        # Event log at bottom
        events_frame = ttk.LabelFrame(main_frame, text="Event Log (All Symbols)", padding=5)
        events_frame.pack(fill=tk.X)
        
        scrollbar = ttk.Scrollbar(events_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.events_text = tk.Text(events_frame, height=4, yscrollcommand=scrollbar.set,
                                   font=("Courier", 8))
        self.events_text.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.events_text.yview)
    
    def create_symbol_chart(self, parent, symbol, row, col):
        """Create a chart frame for one symbol in the grid"""
        frame = ttk.LabelFrame(parent, text=f"{symbol} Trading", padding=5)
        frame.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
        
        # Stats sub-frame
        stats_frame = ttk.Frame(frame)
        stats_frame.pack(fill=tk.X, pady=(0, 5))
        
        price_label = ttk.Label(stats_frame, text="Price: --", font=("Arial", 10, "bold"))
        price_label.pack(side=tk.LEFT, padx=10)
        
        pnl_label = ttk.Label(stats_frame, text="P/L: --", font=("Arial", 9))
        pnl_label.pack(side=tk.LEFT, padx=10)
        
        trades_label = ttk.Label(stats_frame, text="Trades: 0", font=("Arial", 9))
        trades_label.pack(side=tk.LEFT, padx=10)
        
        self.stat_labels[symbol] = {
            'price': price_label,
            'pnl': pnl_label,
            'trades': trades_label
        }
        
        # Chart frame
        chart_subframe = ttk.Frame(frame)
        chart_subframe.pack(fill=tk.BOTH, expand=True)
        
        # Create figure
        fig = Figure(figsize=(6, 4), dpi=100)
        ax = fig.add_subplot(111)
        ax.set_title(f"{symbol} Price Chart")
        ax.set_xlabel("Time (Events)")
        ax.set_ylabel("Price ($)")
        ax.grid(True, alpha=0.3)
        
        # Embed matplotlib
        canvas = FigureCanvasTkAgg(fig, master=chart_subframe)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        self.chart_frames[symbol] = {
            'frame': frame,
            'canvas': canvas,
            'fig': fig,
            'ax': ax
        }
    
    def update_chart(self, symbol):
        """Update chart for a specific symbol"""
        if symbol not in self.chart_frames:
            return
        
        ax = self.chart_frames[symbol]['ax']
        ax.clear()
        
        if len(self.prices[symbol]) > 0:
            x_data = list(range(len(self.prices[symbol])))
            
            # Plot price line
            ax.plot(x_data, list(self.prices[symbol]), label="Price", 
                   color="#2E7D32", linewidth=2, marker='o', markersize=3, alpha=0.8)
            
            # Plot BUY signals
            if self.buy_signals[symbol]:
                buy_x = [x for x, p, tid in self.buy_signals[symbol]]
                buy_y = [p for x, p, tid in self.buy_signals[symbol]]
                ax.scatter(buy_x, buy_y, marker='^', color='#00D084', s=200, 
                          label="BUY", zorder=5, edgecolors='darkgreen', linewidths=1)
            
            # Plot SELL signals
            if self.sell_signals[symbol]:
                sell_x = [x for x, p, tid in self.sell_signals[symbol]]
                sell_y = [p for x, p, tid in self.sell_signals[symbol]]
                ax.scatter(sell_x, sell_y, marker='v', color='#FF6B6B', s=200, 
                          label="SELL", zorder=5, edgecolors='darkred', linewidths=1)
            
            # Plot close signals
            if self.buy_close_signals[symbol]:
                close_x = [x for x, p, tid in self.buy_close_signals[symbol]]
                close_y = [p for x, p, tid in self.buy_close_signals[symbol]]
                ax.scatter(close_x, close_y, marker='X', color='#00AA55', s=150, 
                          label="CLOSE", zorder=4, edgecolors='darkgreen', linewidths=1, alpha=0.7)
            
            if self.sell_close_signals[symbol]:
                close_x = [x for x, p, tid in self.sell_close_signals[symbol]]
                close_y = [p for x, p, tid in self.sell_close_signals[symbol]]
                ax.scatter(close_x, close_y, marker='X', color='#CC4444', s=150, 
                          label="CLOSE", zorder=4, edgecolors='darkred', linewidths=1, alpha=0.7)
            
            ax.legend(loc='upper left', fontsize=8)
            ax.set_title(f"{symbol} Price Chart")
            ax.set_xlabel("Time")
            ax.set_ylabel("Price ($)")
            ax.grid(True, alpha=0.3)
            
            # Set y-axis limits
            if self.prices[symbol]:
                price_min = min(self.prices[symbol])
                price_max = max(self.prices[symbol])
                padding = (price_max - price_min) * 0.1 if price_max != price_min else 1
                ax.set_ylim(price_min - padding, price_max + padding)
        
        self.chart_frames[symbol]['fig'].tight_layout()
        self.chart_frames[symbol]['canvas'].draw()
    
    def update_ui(self, data):
        """Update UI with multi-symbol data from WebSocket"""
        try:
            symbols_data = data.get("symbols", {})
            print(f"[DEBUG] Received data with symbols: {list(symbols_data.keys())}")
            
            total_pnl = 0
            total_trades = 0
            open_positions = 0
            
            for symbol, snapshot in symbols_data.items():
                self._process_symbol_tick(symbol, snapshot)
                
                # Calculate metrics
                strategy = self.strategy_manager.get_strategy(symbol)
                if strategy:
                    metrics = strategy.metrics
                    total_pnl += metrics.get("total_pnl", 0)
                    total_trades += metrics.get("trades_executed", 0)
                    if strategy.open_trade:
                        open_positions += 1
            
            # Update global stats
            pnl_color = "green" if total_pnl >= 0 else "red"
            self.global_pnl_label.config(text=f"Total P/L: ${total_pnl:+.2f}")
            self.global_trades_label.config(text=f"Trades: {total_trades}")
            self.open_positions_label.config(text=f"Open Positions: {open_positions}/{len(self.symbols)}")
        
        except Exception as e:
            print(f"[ERROR] Error updating UI: {e}")
            import traceback
            traceback.print_exc()
    
    def _process_symbol_tick(self, symbol, snapshot):
        """Process tick for one symbol"""
        symbol = symbol.upper()
        
        if symbol not in self.prices:
            return
        
        try:
            ticker = snapshot.get("ticker", {})
            day = ticker.get("day", {})
            minute = ticker.get("min", {})
            
            price = minute.get("c") or day.get("c")
            if price is None:
                return
            
            volume = minute.get("v") or day.get("v") or 0
            bid = round(price - 0.01, 2)
            ask = round(price + 0.01, 2)
            updated_ns = ticker.get("updated") or int(time.time() * 1e9)
            
            # Update prices
            window_full = len(self.prices[symbol]) == self.prices[symbol].maxlen
            self.prices[symbol].append(price)
            self.bid_prices[symbol].append(bid)
            self.ask_prices[symbol].append(ask)
            self.tick_counts[symbol] += 1
            
            # Create tick and process through strategy
            tick = Tick(price=price, volume=volume, timestamp_ns=updated_ns, symbol=symbol)
            event = self.strategy_manager.process_tick(symbol, tick)
            
            # Log tick
            self.logger.log_tick(tick, event)
            
            # Handle trade signals
            if event.get("action") == "OPEN":
                trade = event.get("trade")
                if trade:
                    self.trade_counters[symbol] += 1
                    if trade.direction == "LONG":
                        self.buy_signals[symbol].append((len(self.prices[symbol])-1, price, self.trade_counters[symbol]))
                    elif trade.direction == "SHORT":
                        self.sell_signals[symbol].append((len(self.prices[symbol])-1, price, self.trade_counters[symbol]))
            
            if event.get("action") == "CLOSE":
                trade = event.get("trade")
                if trade:
                    trade_id = self.trade_counters[symbol]
                    if trade.direction == "LONG":
                        self.buy_close_signals[symbol].append((len(self.prices[symbol])-1, trade.exit_price, trade_id))
                    elif trade.direction == "SHORT":
                        self.sell_close_signals[symbol].append((len(self.prices[symbol])-1, trade.exit_price, trade_id))
                    
                    # Log to event log
                    self.log_event(symbol, trade)
            
            # Update stats
            strategy = self.strategy_manager.get_strategy(symbol)
            if strategy:
                metrics = strategy.metrics
                pnl = metrics.get("total_pnl", 0)
                pnl_pct = metrics.get("win_rate", 0)
                
                self.stat_labels[symbol]['price'].config(text=f"Price: ${price:.2f}")
                self.stat_labels[symbol]['pnl'].config(text=f"P/L: ${pnl:+.2f}")
                self.stat_labels[symbol]['trades'].config(text=f"Trades: {metrics.get('trades_executed', 0)}")
            
            # Update chart
            self.update_chart(symbol)
        
        except Exception as e:
            print(f"Error processing {symbol} tick: {e}")
    
    def log_event(self, symbol, trade):
        """Log trade event to event log"""
        try:
            trade_str = (f"[{datetime.now().strftime('%H:%M:%S')}] {symbol} {trade.direction} @ "
                        f"${trade.entry_price:.2f} → ${trade.exit_price:.2f} | "
                        f"P/L: ${trade.pnl:+.3f} ({trade.pnl_pct*100:+.2f}%)\n")
            
            self.events_text.insert(tk.END, trade_str)
            
            # Color code
            if trade.pnl > 0:
                line_num = int(self.events_text.index(tk.END).split('.')[0]) - 1
                self.events_text.tag_add("profit", f"{line_num}.0", f"{line_num}.end")
                self.events_text.tag_config("profit", foreground="#00D084")
            elif trade.pnl < 0:
                line_num = int(self.events_text.index(tk.END).split('.')[0]) - 1
                self.events_text.tag_add("loss", f"{line_num}.0", f"{line_num}.end")
                self.events_text.tag_config("loss", foreground="#FF6B6B")
            
            self.events_text.see(tk.END)
            
            # Keep only last 20 events
            line_count = int(self.events_text.index('end-1c').split('.')[0])
            if line_count > 20:
                self.events_text.delete('1.0', '2.0')
        
        except Exception as e:
            print(f"Error logging event: {e}")
    
    def start_websocket(self):
        """Connect to WebSocket server and receive data"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.websocket_loop())
    
    async def websocket_loop(self):
        """WebSocket connection loop"""
        while True:
            try:
                uri = WEBSOCKET_CONFIG["uri"]
                async with websockets.connect(uri) as websocket:
                    self.connection_status = "Connected"
                    self.root.after(0, lambda: self.status_label.config(
                        text=f"Status: Connected | {sum(self.tick_counts.values())} ticks"))
                    
                    print(f"Connected to {uri}")
                    
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            if "symbols" in data:
                                self.root.after(0, self.update_ui, data)
                                self.root.after(0, lambda: self.status_label.config(
                                    text=f"Status: Connected | {sum(self.tick_counts.values())} total ticks"))
                        except json.JSONDecodeError:
                            pass
                        except Exception as e:
                            print(f"Error processing message: {e}")
            
            except ConnectionRefusedError:
                self.connection_status = "Disconnected"
                self.root.after(0, lambda: self.status_label.config(
                    text=f"Status: Disconnected (retrying...)"))
                print(f"Connection refused. Retrying in {WEBSOCKET_CONFIG['reconnect_delay']}s...")
                await asyncio.sleep(WEBSOCKET_CONFIG["reconnect_delay"])
            
            except Exception as e:
                self.connection_status = "Error"
                print(f"Connection error: {e}")
                await asyncio.sleep(WEBSOCKET_CONFIG["reconnect_delay"])


def main():
    """Entry point"""
    root = tk.Tk()
    app = MultiSymbolDashboard(root, symbols=SYMBOLS)
    root.mainloop()


if __name__ == "__main__":
    main()
