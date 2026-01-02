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
            ax = self.chart_frames[new_symbol]['ax']
            ax.set_title(f"{new_symbol} Price Chart")
            self.chart_frames[new_symbol]['canvas'].draw()

        if old_symbol in self.stat_labels:
            self.stat_labels[new_symbol] = self.stat_labels.pop(old_symbol)
            self.stat_labels[new_symbol]['price'].config(text="Price: --")
            self.stat_labels[new_symbol]['pnl'].config(text="P/L: --")
            self.stat_labels[new_symbol]['trades'].config(text="Trades: 0")

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
        
        # Header frame
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Title
        title_label = ttk.Label(header_frame, text=f"🤖 Multi-Symbol Trading Bot ({len(self.symbols)} tickers) - 10x2 Grid", 
                               font=("Arial", 14, "bold"))
        title_label.pack(side=tk.LEFT)
        
        # Status
        self.status_label = ttk.Label(header_frame, text="Status: Connecting...", 
                                      font=("Arial", 10))
        self.status_label.pack(side=tk.RIGHT)

        # Replace ticker controls (hot-swap)
        replace_frame = ttk.Frame(main_frame)
        replace_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(replace_frame, text="Replace Symbol:").pack(side=tk.LEFT, padx=(0, 5))
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
        
        # Global stats frame
        global_stats_frame = ttk.LabelFrame(main_frame, text="Portfolio Stats", padding=10)
        global_stats_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.global_pnl_label = ttk.Label(global_stats_frame, text="Total P/L: --", 
                                         font=("Arial", 11, "bold"))
        self.global_pnl_label.pack(side=tk.LEFT, padx=20)
        
        self.global_trades_label = ttk.Label(global_stats_frame, text="Trades: 0", 
                                            font=("Arial", 10))
        self.global_trades_label.pack(side=tk.LEFT, padx=20)
        
        self.open_positions_label = ttk.Label(global_stats_frame, text=f"Open Positions: 0/{len(self.symbols)}", 
                                             font=("Arial", 10))
        self.open_positions_label.pack(side=tk.LEFT, padx=20)
        
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
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
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
                
                # Calculate metrics
                strategy = self.strategy_manager.get_strategy(symbol)
                if strategy:
                    metrics = strategy.metrics
                    total_pnl += metrics.total_pnl
                    total_trades += metrics.total_trades
                    # Check if symbol has open position
                    if symbol in strategy.current_positions:
                        open_positions += 1
            
            # Update global stats
            pnl_color = "green" if total_pnl >= 0 else "red"
            self.global_pnl_label.config(text=f"Total P/L: ${total_pnl:+.2f}")
            self.global_trades_label.config(text=f"Trades: {total_trades}")
            self.open_positions_label.config(text=f"Open Positions: {open_positions}/{len(self.symbols)}")
            
            print(f"[update_ui] DONE - Total P/L: ${total_pnl:+.2f}, Trades: {total_trades}\n")
        
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
                if trade:
                    self.trade_counters[symbol] += 1
                    print(f"[_process_symbol_tick] {symbol}: OPEN signal - trade #{self.trade_counters[symbol]}")
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
                if trade:
                    print(f"[_process_symbol_tick] {symbol}: CLOSE signal - P/L: ${trade.pnl:.3f}")
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
                            print(f"[WebSocket] Received message with keys: {list(data.keys())}")
                            
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
                                print(f"[WebSocket] Trade event: {symbol} {action} @ ${price} ({reason})")
                                self.root.after(0, lambda d=data: self.handle_trade_event(d))
                            
                            else:
                                print(f"[WebSocket] Message does not have 'symbols' or 'type' key: {list(data.keys())}")
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
            
            # Get current tick count
            current_tick_idx = len(self.prices[symbol]) - 1
            
            if action == "OPEN":
                # Log the open trade signal
                direction = trade_data.get("direction", "UNKNOWN")
                entry_price = trade_data.get("entry_price", price)
                print(f"  → Opening {direction} position at ${entry_price:.2f}")
                
                # Add to appropriate signals list (buy/sell based on direction)
                if direction == "LONG":
                    self.buy_signals[symbol].append((current_tick_idx, price))
                    print(f"  → Added to buy signals at tick {current_tick_idx}")
                elif direction == "SHORT":
                    self.sell_signals[symbol].append((current_tick_idx, price))
                    print(f"  → Added to sell signals at tick {current_tick_idx}")
            
            elif action == "CLOSE":
                # Log the close trade signal
                entry_price = trade_data.get("entry_price", 0)
                pnl = trade_data.get("pnl", 0)
                print(f"  → Closing position | Entry: ${entry_price:.2f} Exit: ${price:.2f} PnL: {pnl:+.2f}%")
                
                # Determine if this was a long or short close based on reason
                # Could also check trade_data["direction"]
                direction = trade_data.get("direction", "UNKNOWN")
                
                # Add to appropriate close signals list
                if direction == "LONG":
                    self.buy_close_signals[symbol].append((current_tick_idx, price, 0))
                    print(f"  → Added to buy close signals at tick {current_tick_idx}")
                elif direction == "SHORT":
                    self.sell_close_signals[symbol].append((current_tick_idx, price, 0))
                    print(f"  → Added to sell close signals at tick {current_tick_idx}")
            
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
