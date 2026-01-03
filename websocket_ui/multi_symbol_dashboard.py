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
from matplotlib.ticker import ScalarFormatter
from scipy.interpolate import make_interp_spline
from collections import deque
from datetime import datetime
import threading
import time
import asyncio
import contextlib
import numpy as np

from bot.models import Tick
from bot.strategy_manager import StrategyManager
from bot.tick_logger import TickLogger
from bot.config import WEBSOCKET_CONFIG, SYMBOLS
from bot.trading212_broker import get_trading212_broker

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
        self.tick_counts = {sym: 0 for sym in symbols}  # Track total ticks received
        self.buy_signals = {sym: deque() for sym in symbols}  # (absolute_tick_idx, price, trade_id)
        self.sell_signals = {sym: deque() for sym in symbols}
        self.buy_close_signals = {sym: deque() for sym in symbols}
        self.sell_close_signals = {sym: deque() for sym in symbols}
        
        # Trading state
        self.strategy_manager = StrategyManager(symbols)
        self.tick_counts = {sym: 0 for sym in symbols}
        self.trade_counters = {sym: 0 for sym in symbols}
        self.total_trades = 0  # Total trades across all symbols
        self.total_pnl = 0.0   # Total P/L across all symbols
        self.trades_by_symbol = {sym: [] for sym in symbols}  # Track closed trades per symbol
        self.open_prices = {sym: None for sym in symbols}  # Current open trade entry price
        self.close_prices = {sym: None for sym in symbols}  # Last closed trade exit price
        self.connection_status = "Disconnected"
        self.logger = TickLogger()
        
        # Trading212 broker for order execution
        self.trading212_broker = None
        
        # UI components
        self.chart_frames = {}  # {symbol: {'canvas': ..., 'ax': ..., ...}}
        self.stat_labels = {}   # {symbol: {'price': ..., 'pnl': ..., ...}}
        self.event_texts = {}   # {symbol: tk.Text}

        # Command queue for sending control messages (e.g., replace symbol) to the server
        self.ws_command_queue = None
        self.ws_loop = None
        self.ws_connection = None
        
        # Setup UI
        self.setup_ui()
        
        # Start WebSocket connection in background thread
        self.ws_thread = threading.Thread(target=self.start_websocket, daemon=True)
        self.ws_thread.start()

    def enqueue_ws_command(self, payload: dict):
        """Thread-safe enqueue of a WebSocket control command"""
        if not self.ws_loop or not self.ws_command_queue:
            print("[Replace] WebSocket not ready; cannot send command yet")
            return
        try:
            self.ws_loop.call_soon_threadsafe(self.ws_command_queue.put_nowait, payload)
        except Exception as e:
            print(f"[Replace] Failed to enqueue command: {e}")

    def on_pause_click(self):
        """Handle PAUSE button click"""
        print("[Pause] Sending pause command to server")
        self.enqueue_ws_command({"command": "pause"})
        # Disable pause button, enable resume button
        self.pause_button.config(state=tk.DISABLED)
        self.resume_button.config(state=tk.NORMAL)
        self.status_label.config(text="Status: ⏸  PAUSED")

    def on_resume_click(self):
        """Handle RESUME button click"""
        print("[Resume] Sending resume command to server")
        self.enqueue_ws_command({"command": "resume"})
        # Enable pause button, disable resume button
        self.pause_button.config(state=tk.NORMAL)
        self.resume_button.config(state=tk.DISABLED)
        self.status_label.config(text="Status: ▶  RUNNING")

    def handle_replace_symbol(self):
        """Handle replace button click"""
        old_symbol = self.symbol_var.get().strip().upper()
        if not old_symbol:
            print("[Replace] No symbol selected")
            return

        new_symbol = self.new_ticker_var.get().strip().upper()
        if not new_symbol:
            print("[Replace] New ticker is empty")
            return

        if old_symbol == new_symbol:
            print("[Replace] Symbol unchanged")
            return

        # Find slot of old symbol
        try:
            slot = self.symbols.index(old_symbol)
        except ValueError:
            print(f"[Replace] Symbol {old_symbol} not found")
            return

        # Update UI locally
        self.rebind_symbol_slot(slot, old_symbol, new_symbol)

        # Send command to server to update its active list
        self.enqueue_ws_command({"command": "replace_symbol", "slot": slot, "symbol": new_symbol})

        print(f"[Replace] Requested swap: {old_symbol} -> {new_symbol}")

    def rebind_symbol_slot(self, slot: int, old_symbol: str, new_symbol: str):
        """Rebind UI data structures for a slot to a new symbol"""
        # Update symbols list
        self.symbols[slot] = new_symbol
        self.symbol_combo['values'] = list(self.symbols)

        # Update strategy manager mappings
        self.strategy_manager.remove_symbol(old_symbol)
        self.strategy_manager.add_symbol(new_symbol)

        # Helper to reset dict entry
        def reset_dict_entry(store, factory):
            store.pop(old_symbol, None)
            store[new_symbol] = factory()

        # Reset data stores
        reset_dict_entry(self.prices, lambda: deque(maxlen=MAX_DATA_POINTS))
        reset_dict_entry(self.bid_prices, lambda: deque(maxlen=MAX_DATA_POINTS))
        reset_dict_entry(self.ask_prices, lambda: deque(maxlen=MAX_DATA_POINTS))
        reset_dict_entry(self.buy_signals, lambda: deque())
        reset_dict_entry(self.sell_signals, lambda: deque())
        reset_dict_entry(self.buy_close_signals, lambda: deque())
        reset_dict_entry(self.sell_close_signals, lambda: deque())
        reset_dict_entry(self.tick_counts, lambda: 0)
        reset_dict_entry(self.trade_counters, lambda: 0)

        # Move chart/stat widgets to new key and retitle
        if old_symbol in self.chart_frames:
            self.chart_frames[new_symbol] = self.chart_frames.pop(old_symbol)
            # No more chart title - instead update the stats line at the top
            self.chart_frames[new_symbol]['canvas'].draw()

        if old_symbol in self.stat_labels:
            self.stat_labels[new_symbol] = self.stat_labels.pop(old_symbol)
            self.stat_labels[new_symbol]['price'].config(text="Price: --")
            self.stat_labels[new_symbol]['pnl'].config(text="P/L: --")
            self.stat_labels[new_symbol]['trades'].config(text="Trades: 0")
            self.stat_labels[new_symbol]['open'].config(text="Open: --")
            self.stat_labels[new_symbol]['close'].config(text="Close: --")
            self.stat_labels[new_symbol]['range_status'].config(text="Range: --")
            self.stat_labels[new_symbol]['range_level'].config(text="--")

        if old_symbol in self.event_texts:
            self.event_texts[new_symbol] = self.event_texts.pop(old_symbol)
            self.event_texts[new_symbol].delete('1.0', tk.END)
            self.event_texts[new_symbol].insert(tk.END, f"Swapped to {new_symbol}\n")

        # Force immediate redraw/clear of chart
        if new_symbol in self.chart_frames:
            self.update_chart(new_symbol)
    
    def setup_ui(self):
        """Setup the UI with 10x2 grid layout (scrollable)"""
        # Main container
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Connection status with control buttons
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(0, 5))
        self.status_label = ttk.Label(status_frame, text="Status: Connecting...", font=("Arial", 10))
        self.status_label.pack(side=tk.LEFT)
        
        # Pause/Resume buttons
        button_frame = ttk.Frame(status_frame)
        button_frame.pack(side=tk.RIGHT)
        self.pause_button = ttk.Button(button_frame, text="⏸  PAUSE", command=self.on_pause_click)
        self.pause_button.pack(side=tk.LEFT, padx=5)
        self.resume_button = ttk.Button(button_frame, text="▶  RESUME", command=self.on_resume_click, state=tk.DISABLED)
        self.resume_button.pack(side=tk.LEFT, padx=5)

        # 10x2 Grid for charts with scrollbar
        grid_container = ttk.Frame(main_frame)
        grid_container.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Canvas with scrollbar for 10x2 grid
        canvas = tk.Canvas(grid_container, bg="white")
        scrollbar = ttk.Scrollbar(grid_container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        # Match inner frame width to canvas to avoid right-side whitespace
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(canvas_window, width=e.width)
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Configure mousewheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Configure grid (10 rows, 2 columns)
        for i in range(10):
            scrollable_frame.grid_rowconfigure(i, weight=1)
        for i in range(2):
            scrollable_frame.grid_columnconfigure(i, weight=1)
        
        for i, symbol in enumerate(self.symbols[:20]):  # Limit to 20 symbols
            row = i // 2
            col = i % 2
            self.create_symbol_chart(scrollable_frame, symbol, row, col)
        
        # Bottom controls frame - Portfolio Stats and Replace Symbol side by side
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Portfolio Stats (left side)
        global_stats_frame = ttk.LabelFrame(bottom_frame, text="Portfolio Stats", padding=10)
        global_stats_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        self.global_pnl_label = ttk.Label(global_stats_frame, text="Total P/L: $0.00", 
                                         font=("Arial", 11, "bold"))
        self.global_pnl_label.pack(side=tk.LEFT, padx=20)
        
        self.global_trades_label = ttk.Label(global_stats_frame, text="Trades: 0", 
                                            font=("Arial", 10))
        self.global_trades_label.pack(side=tk.LEFT, padx=20)
        
        self.open_positions_label = ttk.Label(global_stats_frame, text=f"Open Positions: 0/{len(self.symbols)}", 
                                             font=("Arial", 10))
        self.open_positions_label.pack(side=tk.LEFT, padx=20)

        # Replace Symbol controls (right side)
        replace_frame = ttk.LabelFrame(bottom_frame, text="Replace Symbol", padding=10)
        replace_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))

        ttk.Label(replace_frame, text="Symbol:").pack(side=tk.LEFT, padx=(0, 5))
        self.symbol_var = tk.StringVar(value=self.symbols[0] if self.symbols else "")
        self.symbol_combo = ttk.Combobox(replace_frame, textvariable=self.symbol_var, width=10, state="readonly")
        self.symbol_combo['values'] = list(self.symbols)
        self.symbol_combo.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(replace_frame, text="With:").pack(side=tk.LEFT, padx=(0, 5))
        self.new_ticker_var = tk.StringVar()
        self.new_ticker_entry = ttk.Entry(replace_frame, textvariable=self.new_ticker_var, width=12)
        self.new_ticker_entry.pack(side=tk.LEFT, padx=(0, 10))

        replace_btn = ttk.Button(replace_frame, text="Replace", command=self.handle_replace_symbol)
        replace_btn.pack(side=tk.LEFT)
    
    def create_symbol_chart(self, parent, symbol, row, col):
        """Create a chart frame for one symbol in the grid"""
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
        
        # Single line stats frame - all stats in one row
        stats_frame = ttk.Frame(frame)
        stats_frame.pack(fill=tk.X, pady=(0, 5))
        
        # Add symbol label first
        symbol_label = ttk.Label(stats_frame, text=f"{symbol}", font=("Arial", 11, "bold"))
        symbol_label.pack(side=tk.LEFT, padx=5)
        
        # Separator
        ttk.Separator(stats_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        
        price_label = ttk.Label(stats_frame, text="Price: --", font=("Arial", 9))
        price_label.pack(side=tk.LEFT, padx=3)
        
        pnl_label = ttk.Label(stats_frame, text="P/L: --", font=("Arial", 9))
        pnl_label.pack(side=tk.LEFT, padx=3)
        
        trades_label = ttk.Label(stats_frame, text="Trades: 0", font=("Arial", 9))
        trades_label.pack(side=tk.LEFT, padx=3)
        
        open_label = ttk.Label(stats_frame, text="Open: --", font=("Arial", 9, "bold"), foreground="green")
        open_label.pack(side=tk.LEFT, padx=3)
        
        close_label = ttk.Label(stats_frame, text="Close: --", font=("Arial", 9), foreground="red")
        close_label.pack(side=tk.LEFT, padx=3)
        
        range_status_label = ttk.Label(stats_frame, text="Range: --", font=("Arial", 9), foreground="blue")
        range_status_label.pack(side=tk.LEFT, padx=3)
        
        range_level_label = ttk.Label(stats_frame, text="--", font=("Arial", 8))
        range_level_label.pack(side=tk.LEFT, padx=3)
        
        self.stat_labels[symbol] = {
            'price': price_label,
            'pnl': pnl_label,
            'trades': trades_label,
            'open': open_label,
            'close': close_label,
            'range_status': range_status_label,
            'range_level': range_level_label
        }
        
        # Chart frame
        chart_subframe = ttk.Frame(frame)
        chart_subframe.pack(fill=tk.BOTH, expand=True)
        
        # Create figure without title
        fig = Figure(figsize=(6, 4), dpi=100)
        ax = fig.add_subplot(111)
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
            print(f"[update_chart] {symbol}: Not in chart_frames")
            return
        
        print(f"[update_chart] {symbol}: Updating chart with {len(self.prices[symbol])} prices")
        
        ax = self.chart_frames[symbol]['ax']
        ax.clear()
        # Force plain number formatting (no scientific notation)
        ax.ticklabel_format(style='plain', axis='y')
        ax.yaxis.set_major_formatter(ScalarFormatter(useOffset=False))
        
        if len(self.prices[symbol]) > 0:
            x_data = list(range(len(self.prices[symbol])))
            
            # Calculate the offset: how many ticks were received before the current window started
            num_current_prices = len(self.prices[symbol])
            oldest_tick_idx = self.tick_counts[symbol] - num_current_prices
            
            # Plot price line with smooth curved spline interpolation
            prices_list = list(self.prices[symbol])
            if len(x_data) > 3:
                # Use spline for smooth curves
                spl = make_interp_spline(x_data, prices_list, k=3)
                x_smooth = np.linspace(min(x_data), max(x_data), 300)
                y_smooth = spl(x_smooth)
                ax.plot(x_smooth, y_smooth, label="Price", 
                       color="#2E7D32", linewidth=2.5, alpha=0.9)
                ax.scatter(x_data, prices_list, color="#2E7D32", s=12, alpha=0.6, zorder=5)
            else:
                ax.plot(x_data, prices_list, label="Price", 
                       color="#2E7D32", linewidth=2.5, marker='o', markersize=3, alpha=0.8)
            
            print(f"[update_chart] {symbol}: Plotted {len(x_data)} price points (oldest tick idx: {oldest_tick_idx})")
            
            # Plot BUY signals (filter by visible range and convert to relative x)
            if self.buy_signals[symbol]:
                visible_buy = [(abs_idx, p, tid) for abs_idx, p, tid in self.buy_signals[symbol] 
                               if oldest_tick_idx <= abs_idx < self.tick_counts[symbol]]
                if visible_buy:
                    buy_x = [abs_idx - oldest_tick_idx for abs_idx, p, tid in visible_buy]
                    buy_y = [p for abs_idx, p, tid in visible_buy]
                    ax.scatter(buy_x, buy_y, marker='^', color='#00D084', s=200, 
                              label="BUY", zorder=5, edgecolors='darkgreen', linewidths=1)
                    print(f"[update_chart] {symbol}: Plotted {len(buy_x)} BUY signals")
            
            # Plot SELL signals
            if self.sell_signals[symbol]:
                visible_sell = [(abs_idx, p, tid) for abs_idx, p, tid in self.sell_signals[symbol] 
                                if oldest_tick_idx <= abs_idx < self.tick_counts[symbol]]
                if visible_sell:
                    sell_x = [abs_idx - oldest_tick_idx for abs_idx, p, tid in visible_sell]
                    sell_y = [p for abs_idx, p, tid in visible_sell]
                    ax.scatter(sell_x, sell_y, marker='v', color='#FF6B6B', s=200, 
                              label="SELL", zorder=5, edgecolors='darkred', linewidths=1)
                    print(f"[update_chart] {symbol}: Plotted {len(sell_x)} SELL signals")
            
            # Plot close signals
            if self.buy_close_signals[symbol]:
                visible_close = [(abs_idx, p, tid) for abs_idx, p, tid in self.buy_close_signals[symbol] 
                                 if oldest_tick_idx <= abs_idx < self.tick_counts[symbol]]
                if visible_close:
                    close_x = [abs_idx - oldest_tick_idx for abs_idx, p, tid in visible_close]
                    close_y = [p for abs_idx, p, tid in visible_close]
                    ax.scatter(close_x, close_y, marker='X', color='#00AA55', s=150, 
                              label="CLOSE", zorder=4, edgecolors='darkgreen', linewidths=1, alpha=0.7)
            
            if self.sell_close_signals[symbol]:
                visible_close = [(abs_idx, p, tid) for abs_idx, p, tid in self.sell_close_signals[symbol] 
                                 if oldest_tick_idx <= abs_idx < self.tick_counts[symbol]]
                if visible_close:
                    close_x = [abs_idx - oldest_tick_idx for abs_idx, p, tid in visible_close]
                    close_y = [p for abs_idx, p, tid in visible_close]
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
        else:
            print(f"[update_chart] {symbol}: No prices to plot yet")
        
        self.chart_frames[symbol]['fig'].tight_layout()
        self.chart_frames[symbol]['canvas'].draw()
        print(f"[update_chart] {symbol}: Canvas drawn")
    
    def update_ui(self, data):
        """Update UI with multi-symbol data from WebSocket"""
        try:
            symbols_data = data.get("symbols", {})
            print(f"\n[update_ui] Received snapshot with {len(symbols_data)} symbols: {list(symbols_data.keys())}")
            
            total_pnl = 0
            total_trades = 0
            open_positions = 0
            
            for symbol, snapshot in symbols_data.items():
                print(f"[update_ui] Processing {symbol}...")
                self._process_symbol_tick(symbol, snapshot)
                
                # Calculate metrics - sum up all symbols' P/L and trades
                strategy = self.strategy_manager.get_strategy(symbol)
                if strategy:
                    metrics = strategy.metrics
                    # Accumulate P/L and trades from this symbol's strategy
                    total_pnl += metrics.total_pnl
                    total_trades += metrics.total_trades
                    # Check if symbol has open position
                    if symbol in strategy.current_positions:
                        open_positions += 1
            
            # Update global stats with calculated totals from all symbols' local strategies
            pnl_color = "green" if total_pnl >= 0 else "red"
            self.global_pnl_label.config(text=f"Total P/L: ${total_pnl:+.2f}", foreground=pnl_color)
            self.global_trades_label.config(text=f"Trades: {total_trades}")
            self.open_positions_label.config(text=f"Open Positions: {open_positions}/{len(self.symbols)}")
            
            print(f"[update_ui] DONE - Total P/L: ${total_pnl:+.2f}, Trades: {total_trades}, Open Positions: {open_positions}\n")
        
        except Exception as e:
            print(f"[ERROR] update_ui: {e}")
            import traceback
            traceback.print_exc()
    
    def _process_symbol_tick(self, symbol, snapshot):
        """Process tick for one symbol"""
        symbol = symbol.upper()
        
        if symbol not in self.prices:
            print(f"[_process_symbol_tick] Symbol {symbol} not in prices dict (available: {list(self.prices.keys())})")
            return
        
        try:
            ticker = snapshot.get("ticker", {})
            day = ticker.get("day", {})
            minute = ticker.get("min", {})
            prev_day = ticker.get("prevDay", {})
            
            # Try to get price: minute > day > prevDay (fallback to yesterday's close if market closed)
            price = minute.get("c") or day.get("c") or prev_day.get("c")
            if price is None or price == 0:
                print(f"[_process_symbol_tick] {symbol}: No price found in snapshot")
                return
            
            print(f"[_process_symbol_tick] {symbol}: Processing price ${price:.2f}")
            
            volume = minute.get("v") or day.get("v") or prev_day.get("v") or 0
            bid = round(price - 0.01, 2)
            ask = round(price + 0.01, 2)
            updated_ns = ticker.get("updated") or int(time.time() * 1e9)
            
            # Update prices
            window_full = len(self.prices[symbol]) == self.prices[symbol].maxlen
            self.prices[symbol].append(price)
            self.bid_prices[symbol].append(bid)
            self.ask_prices[symbol].append(ask)
            self.tick_counts[symbol] += 1
            
            print(f"[_process_symbol_tick] {symbol}: Added price to deque. Tick count: {self.tick_counts[symbol]}")
            
            # Create tick and process through strategy
            tick = Tick(price=price, volume=volume, timestamp_ns=updated_ns, symbol=symbol)
            event = self.strategy_manager.process_tick(symbol, tick)
            
            print(f"[_process_symbol_tick] {symbol}: Strategy event: {event.get('action')} - {event.get('reason')}")

            # If strategy unknown or no metrics, skip logging/stat updates
            if event is None or event.get('reason') == 'unknown_symbol' or 'metrics' not in event:
                print(f"[_process_symbol_tick] {symbol}: Skipping stats/log (unknown symbol or missing metrics)")
                return
            
            # Log tick
            self.logger.log_tick(tick, event)
            
            # Handle trade signals
            if event.get("action") == "OPEN":
                trade = event.get("trade")
                if trade and hasattr(trade, 'entry_price') and trade.entry_price is not None:
                    self.trade_counters[symbol] += 1
                    print(f"[_process_symbol_tick] {symbol}: OPEN signal - trade #{self.trade_counters[symbol]}")
                    
                    # Cache the entry price for this symbol and clear previous close price
                    entry_price = trade.entry_price
                    self.open_prices[symbol] = entry_price
                    self.close_prices[symbol] = None  # Clear previous close price when new position opens
                    print(f"[_process_symbol_tick] {symbol}: Set open_prices[{symbol}] = ${entry_price:.2f}, cleared close_prices")
                    
                    # Update UI Open label with thread-safe call
                    def update_open_label(ep=entry_price, sym=symbol):
                        try:
                            label_text = f"Open: ${ep:.2f}"
                            print(f"[update_open_label] Updating {sym} Open label to: {label_text}")
                            self.stat_labels[sym]['open'].config(text=label_text, foreground="green")
                            # Clear the Close label when new position opens
                            self.stat_labels[sym]['close'].config(text="Close: --")
                            print(f"[update_open_label] ✅ Updated Open label for {sym} to: {label_text}, cleared Close")
                        except Exception as e:
                            print(f"[update_open_label] ERROR: {e}")
                            import traceback
                            traceback.print_exc()
                    
                    self.root.after(0, update_open_label)
                    
                    if trade.direction == "LONG":
                        self.buy_signals[symbol].append((self.tick_counts[symbol]-1, price, self.trade_counters[symbol]))
                        
                        # Execute BUY trade on Trading212
                        if self.trading212_broker:
                            asyncio.create_task(self.trading212_broker.execute_open_trade(
                                symbol=symbol,
                                entry_price=price,
                                quantity=1.0
                            ))
                            print(f"[_process_symbol_tick] {symbol}: Trading212 BUY order queued")
                    
                    elif trade.direction == "SHORT":
                        self.sell_signals[symbol].append((self.tick_counts[symbol]-1, price, self.trade_counters[symbol]))
            
            if event.get("action") == "CLOSE":
                trade = event.get("trade")
                if trade and hasattr(trade, 'exit_price') and trade.exit_price is not None:
                    print(f"[_process_symbol_tick] {symbol}: CLOSE signal - P/L: ${trade.pnl:.3f}")
                    
                    # Cache the close price (exit price) for this symbol
                    exit_price = trade.exit_price
                    entry_price = trade.entry_price
                    self.close_prices[symbol] = exit_price
                    print(f"[_process_symbol_tick] {symbol}: Set close_prices[{symbol}] = ${exit_price:.2f}")
                    
                    # Update UI labels with thread-safe call - show both Open and Close prices
                    def update_close_labels(exit_p=exit_price, ep=entry_price, sym=symbol):
                        try:
                            print(f"[update_close_labels] Updating {sym} Close label")
                            self.stat_labels[sym]['close'].config(text=f"Close: ${exit_p:.2f}", foreground="red")
                            print(f"[update_close_labels] Close label updated to: Close: ${exit_p:.2f}")
                            # Keep showing the open price (cached) - don't clear it
                            self.stat_labels[sym]['open'].config(text=f"Open: ${ep:.2f}", foreground="green")
                            print(f"[update_close_labels] Open label kept at: Open: ${ep:.2f}")
                            print(f"  ✅ Updated Close label for {sym} to: ${exit_p:.2f}, Open cached: ${ep:.2f}")
                        except Exception as e:
                            print(f"[update_close_labels] ERROR: {e}")
                            import traceback
                            traceback.print_exc()
                    
                    self.root.after(0, update_close_labels)
                    
                    trade_id = self.trade_counters[symbol]
                    if trade.direction == "LONG":
                        self.buy_close_signals[symbol].append((self.tick_counts[symbol]-1, trade.exit_price, trade_id))
                        
                        # Execute SELL to close position on Trading212
                        if self.trading212_broker:
                            asyncio.create_task(self.trading212_broker.execute_close_trade(
                                symbol=symbol,
                                exit_price=trade.exit_price,
                                exit_reason=trade.exit_reason
                            ))
                            print(f"[_process_symbol_tick] {symbol}: Trading212 SELL order queued ({trade.exit_reason})")
                    
                    elif trade.direction == "SHORT":
                        self.sell_close_signals[symbol].append((self.tick_counts[symbol]-1, trade.exit_price, trade_id))
                    
                    self.log_event(symbol, trade)
            
            # Update stats
            strategy = self.strategy_manager.get_strategy(symbol)
            if strategy:
                metrics = strategy.metrics
                pnl = metrics.total_pnl
                
                print(f"[_process_symbol_tick] {symbol}: Updating UI labels - Price: ${price:.2f}, P/L: ${pnl:.2f}")
                
                self.stat_labels[symbol]['price'].config(text=f"Price: ${price:.2f}")
                self.stat_labels[symbol]['pnl'].config(text=f"P/L: ${pnl:+.2f}")
                self.stat_labels[symbol]['trades'].config(text=f"Trades: {metrics.total_trades}")
                # Update range information
                if hasattr(strategy, 'opening_range'):
                    print(f"[update_ui] {symbol}: strategy.opening_range exists, keys={list(strategy.opening_range.keys())}")
                    if symbol in strategy.opening_range:
                        or_data = strategy.opening_range[symbol]
                        phase = or_data.get("phase", "N/A")
                        
                        if phase == "BUILDING":
                            ticks = or_data.get("ticks", 0)
                            total_ticks = strategy.opening_range_ticks
                            build_pct = (ticks / total_ticks * 100) if total_ticks > 0 else 0
                            range_low = or_data.get("low", 0)
                            range_high = or_data.get("high", 0)
                            
                            print(f"[update_ui] 🏗️  {symbol} BUILDING: {ticks}/{total_ticks} ticks ({build_pct:.0f}%) | Range: ${range_low:.4f}-${range_high:.4f}")
                            print(f"[update_ui] {symbol} DEBUG: or_data keys = {or_data.keys()}, initialized={or_data.get('initialized')}")
                            
                            self.stat_labels[symbol]['range_status'].config(
                                text=f"Building ({ticks}/{total_ticks})",
                                foreground="orange"
                            )
                            self.stat_labels[symbol]['range_level'].config(
                                text=f"${range_low:.4f} - ${range_high:.4f} ({build_pct:.0f}%)"
                            )
                        
                        elif phase == "LOCKED":
                            range_low = or_data.get("low", 0)
                            range_high = or_data.get("high", 0)
                            position_locked = or_data.get("position_locked", False)
                            validity_expires = or_data.get("validity_expires_at", 0)
                            
                            import time as time_module
                            now = time_module.time()
                            time_left = max(0, validity_expires - now)
                            
                            print(f"[update_ui] 🔒 {symbol} LOCKED: ${range_low:.4f}-${range_high:.4f} | position_locked={position_locked}, time_left={time_left:.0f}s")
                            
                            if position_locked:
                                status_text = "LOCKED (Position Open)"
                                color = "purple"
                            else:
                                mins_left = time_left / 60
                                status_text = f"LOCKED ({mins_left:.1f}m)"
                                color = "green" if time_left > 300 else "orange" if time_left > 60 else "red"
                            
                            self.stat_labels[symbol]['range_status'].config(
                                text=status_text,
                                foreground=color
                            )
                            self.stat_labels[symbol]['range_level'].config(
                                text=f"${range_low:.4f} - ${range_high:.4f}"
                            )
                        else:
                            print(f"[update_ui] ❌ {symbol} Phase N/A or unknown: {phase}")
                            self.stat_labels[symbol]['range_status'].config(text="Range: --", foreground="gray")
                            self.stat_labels[symbol]['range_level'].config(text="--")
                    else:
                        print(f"[update_ui] {symbol}: NOT in strategy.opening_range")
                else:
                    print(f"[update_ui] {symbol}: strategy.opening_range attribute does NOT exist!")
                
                # Update open/close prices (NEW: handle multiple positions)
                if symbol in strategy.current_positions and len(strategy.current_positions[symbol]) > 0:
                    # Show info for all open positions
                    positions_info = []
                    for pos in strategy.current_positions[symbol]:
                        positions_info.append(f"Pos#{pos.position_id}: ${pos.entry_price:.2f}")
                    
                    # Use the first position for main display
                    first_pos = strategy.current_positions[symbol][0]
                    entry_price = first_pos.entry_price
                    self.open_prices[symbol] = entry_price
                    
                    positions_text = " | ".join(positions_info)
                    self.stat_labels[symbol]['open'].config(
                        text=f"Open: {positions_text}",
                        foreground="green"
                    )
                    print(f"[_process_symbol_tick] {symbol}: {len(strategy.current_positions[symbol])} open position(s)")
                else:
                    # Position closed - keep showing last trade's entry price during BUILDING phase
                    # Only clear if we have no cached value (truly no recent trades)
                    if self.open_prices[symbol] is not None:
                        # Keep showing cached entry price - it persists until next trade opens
                        print(f"[_process_symbol_tick] {symbol}: Positions closed, keeping cached Open: ${self.open_prices[symbol]:.2f}")
                    else:
                        # No cached value - show empty
                        self.stat_labels[symbol]['open'].config(text="Open: --")
                
                # Update close price if available (cached from last closed trade)
                if self.close_prices[symbol] is not None:
                    self.stat_labels[symbol]['close'].config(
                        text=f"Close: ${self.close_prices[symbol]:.2f}",
                        foreground="red"
                    )
                    print(f"[_process_symbol_tick] {symbol}: Showing cached Close: ${self.close_prices[symbol]:.2f}")
                else:
                    self.stat_labels[symbol]['close'].config(text="Close: --")
            
            # Update chart
            print(f"[_process_symbol_tick] {symbol}: Updating chart (prices count: {len(self.prices[symbol])})")
            self.update_chart(symbol)
        
        except Exception as e:
            print(f"[_process_symbol_tick] {symbol}: ERROR - {e}")
            import traceback
            traceback.print_exc()
    
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
        self.ws_loop = loop
        self.ws_command_queue = asyncio.Queue()
        loop.run_until_complete(self.websocket_loop())
    
    async def websocket_loop(self):
        """WebSocket connection loop"""
        # Initialize Trading212 broker
        self.trading212_broker = await get_trading212_broker()
        await self.trading212_broker.init_client()
        
        while True:
            try:
                uri = WEBSOCKET_CONFIG["uri"]
                async with websockets.connect(uri) as websocket:
                    self.ws_connection = websocket
                    self.connection_status = "Connected"
                    print(f"[WebSocket] Connected to {uri}")
                    self.root.after(0, lambda: self.status_label.config(
                        text=f"Status: Connected | Waiting for data..."))

                    # Start command sender task
                    sender_task = asyncio.create_task(self.send_commands(websocket))
                    
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            msg_keys = list(data.keys())
                            print(f"[WebSocket] Received message with keys: {msg_keys}")
                            
                            # Handle symbol data (regular snapshots)
                            if "symbols" in data:
                                print(f"[WebSocket] Calling update_ui with {len(data['symbols'])} symbols")
                                self.root.after(0, lambda d=data: self.update_ui(d))
                            
                            # Handle trade events (OPEN/CLOSE)
                            elif data.get("type") == "TRADE_EVENT":
                                symbol = data.get("symbol")
                                action = data.get("action")  # "OPEN" or "CLOSE"
                                reason = data.get("reason")
                                price = data.get("price")
                                print(f"[WebSocket] ✅ Trade event received: {symbol} {action} @ ${price} ({reason})")
                                print(f"[WebSocket] Full event: {data}")
                                self.root.after(0, lambda d=data: self.handle_trade_event(d))
                            
                            else:
                                print(f"[WebSocket] ⚠️ Message doesn't match patterns. Keys: {msg_keys}")
                                if data.get("action"):
                                    print(f"[WebSocket] Message has 'action' field: {data.get('action')} - might be a trade event missing type!")
                        
                        except json.JSONDecodeError as e:
                            print(f"[WebSocket] JSON decode error: {e}")
                        except Exception as e:
                            print(f"[WebSocket] Error processing message: {e}")
                            import traceback
                            traceback.print_exc()
                    sender_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await sender_task
            
            except ConnectionRefusedError:
                self.connection_status = "Disconnected"
                print(f"[WebSocket] Connection refused - retrying in {WEBSOCKET_CONFIG['reconnect_delay']}s...")
                self.root.after(0, lambda: self.status_label.config(
                    text=f"Status: Disconnected (retrying...)"))
                await asyncio.sleep(WEBSOCKET_CONFIG["reconnect_delay"])
            
            except Exception as e:
                self.connection_status = "Error"
                print(f"[WebSocket] Connection error: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(WEBSOCKET_CONFIG["reconnect_delay"])

    def handle_trade_event(self, event):
        """Handle OPEN/CLOSE trade events from the bot"""
        try:
            symbol = event.get("symbol")
            action = event.get("action")  # "OPEN" or "CLOSE"
            reason = event.get("reason", "N/A")
            price = event.get("price", 0)
            trade_data = event.get("trade", {})
            
            if not symbol or symbol not in self.prices:
                print(f"[handle_trade_event] Unknown symbol: {symbol}")
                return
            
            print(f"[handle_trade_event] {symbol}: {action} @ ${price:.2f} ({reason})")
            print(f"[handle_trade_event] Trade data: {trade_data}")
            print(f"[handle_trade_event] Event keys: {list(event.keys())}")
            
            # Get current tick count
            current_tick_idx = len(self.prices[symbol]) - 1
            
            if action == "OPEN":
                # Log the open trade signal
                direction = trade_data.get("direction", "UNKNOWN")
                entry_price = trade_data.get("entry_price", price)
                
                # Ensure entry_price is a valid number
                if entry_price is None:
                    entry_price = price
                
                print(f"  → Opening {direction} position at ${entry_price:.2f}")
                print(f"  → Direction: {direction}, Entry Price: {entry_price}, Type: {type(entry_price)}")
                
                # Track open price for this symbol
                self.open_prices[symbol] = entry_price
                self.close_prices[symbol] = None  # Clear previous close price
                
                # Debug: Check if symbol is in stat_labels
                if symbol not in self.stat_labels:
                    print(f"  ❌ ERROR: {symbol} not in stat_labels!")
                    print(f"     Available symbols: {list(self.stat_labels.keys())}")
                    return
                
                # Debug: Check if 'open' key exists
                if 'open' not in self.stat_labels[symbol]:
                    print(f"  ❌ ERROR: 'open' key not in stat_labels[{symbol}]!")
                    print(f"     Available keys: {list(self.stat_labels[symbol].keys())}")
                    return
                
                # Update UI label with thread-safe call - pass entry_price directly to avoid closure issues
                def update_open_label(ep=entry_price, sym=symbol):
                    try:
                        label_text = f"Open: ${ep:.2f}"
                        print(f"  [update_open_label] Setting text to: {label_text} for {sym}")
                        self.stat_labels[sym]['open'].config(text=label_text, foreground="green")
                        # Cache the entry price for persistence during BUILDING phase
                        self.open_prices[sym] = ep
                        print(f"  ✅ Updated Open label for {sym} to: {label_text} (cached)")
                    except Exception as e:
                        print(f"  ❌ Error updating Open label for {sym}: {e}")
                        import traceback
                        traceback.print_exc()
                
                self.root.after(0, update_open_label)
                
                # Add to appropriate signals list (buy/sell based on direction)
                if direction == "LONG":
                    self.buy_signals[symbol].append((current_tick_idx, price, self.trade_counters[symbol]))
                    print(f"  → Added to buy signals at tick {current_tick_idx}")
                elif direction == "SHORT":
                    self.sell_signals[symbol].append((current_tick_idx, price, self.trade_counters[symbol]))
                    print(f"  → Added to sell signals at tick {current_tick_idx}")
            
            elif action == "CLOSE":
                # Log the close trade signal
                print(f"[handle_trade_event] CLOSE action detected for {symbol}")
                entry_price = trade_data.get("entry_price", 0)
                pnl = trade_data.get("pnl", 0)
                print(f"[handle_trade_event] Entry: ${entry_price:.2f}, Exit: ${price:.2f}, PnL: {pnl:+.2f}%")
                
                # Track close price for this symbol
                self.close_prices[symbol] = price
                print(f"[handle_trade_event] Set close_prices[{symbol}] = ${price:.2f}")
                # DO NOT clear open_prices - keep it cached to show during BUILDING phase
                
                # Update UI labels with thread-safe calls - pass values directly to avoid closure issues
                def update_close_labels(exit_p=price, sym=symbol, ep=entry_price):
                    try:
                        print(f"[update_close_labels] START: Updating {sym} Close label")
                        self.stat_labels[sym]['close'].config(text=f"Close: ${exit_p:.2f}", foreground="red")
                        print(f"[update_close_labels] Close label updated to: Close: ${exit_p:.2f}")
                        # Keep showing the open price (cached) - don't clear it
                        self.stat_labels[sym]['open'].config(text=f"Open: ${ep:.2f}", foreground="green")
                        print(f"[update_close_labels] Open label updated to: Open: ${ep:.2f}")
                        print(f"  ✅ Updated Close label for {sym} to: ${exit_p:.2f}, Open cached: ${ep:.2f}")
                    except Exception as e:
                        print(f"[update_close_labels] ERROR: {e}")
                        import traceback
                        traceback.print_exc()
                
                print(f"[handle_trade_event] Scheduling update_close_labels via root.after(0)")
                self.root.after(0, update_close_labels)
                print(f"[handle_trade_event] Scheduled. Continuing to track close signals...")
                
                self.root.after(0, update_close_labels)
                
                # Track trades and P/L
                self.total_trades += 1
                self.total_pnl += pnl
                
                # Determine if this was a long or short close based on reason
                direction = trade_data.get("direction", "UNKNOWN")
                
                # Add to appropriate close signals list
                if direction == "LONG":
                    self.buy_close_signals[symbol].append((current_tick_idx, price, 0))
                    print(f"  → Added to buy close signals at tick {current_tick_idx}")
                elif direction == "SHORT":
                    self.sell_close_signals[symbol].append((current_tick_idx, price, 0))
                    print(f"  → Added to sell close signals at tick {current_tick_idx}")
                
                # Update global stats (thread-safe via root.after)
                pnl_color = "green" if self.total_pnl >= 0 else "red"
                
                def update_global_stats():
                    try:
                        self.global_pnl_label.config(text=f"Total P/L: ${self.total_pnl:+.2f}", foreground=pnl_color)
                        self.global_trades_label.config(text=f"Trades: {self.total_trades}")
                        print(f"  ✅ Updated global stats: Trades={self.total_trades}, P/L=${self.total_pnl:+.2f}")
                    except Exception as e:
                        print(f"  ❌ Error updating global stats: {e}")
                
                self.root.after(0, update_global_stats)
            
            # Force chart update to show the new signals
            print(f"[handle_trade_event] Updating chart for {symbol}")
            self.update_chart(symbol)
        
        except Exception as e:
            print(f"[handle_trade_event] Error processing trade event: {e}")
            import traceback
            traceback.print_exc()

    async def send_commands(self, websocket):
        """Send queued control commands to the server"""
        while True:
            cmd = await self.ws_command_queue.get()
            try:
                await websocket.send(json.dumps(cmd))
                print(f"[WebSocket] Sent command: {cmd}")
            except Exception as e:
                print(f"[WebSocket] Failed to send command {cmd}: {e}")


def main():
    """Entry point"""
    root = tk.Tk()
    app = MultiSymbolDashboard(root, symbols=SYMBOLS)
    root.mainloop()


if __name__ == "__main__":
    main()
