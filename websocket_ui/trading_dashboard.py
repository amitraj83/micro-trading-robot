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
from bot.strategy import MicroTradingStrategy
from bot.tick_logger import TickLogger
from bot.config import WEBSOCKET_CONFIG, SYMBOL

# Configuration
MAX_DATA_POINTS = 100


def _shift_and_prune_signals(signal_deque, shift=-1, has_cost=False):
    """Shift signal x-coordinates and drop any that fall off the chart window"""
    if shift == 0:
        return
    updated = deque()
    for item in signal_deque:
        if has_cost:
            x, p, tid, cost = item
            nx = x + shift
            if nx >= 0:
                updated.append((nx, p, tid, cost))
        else:
            x, p, tid = item
            nx = x + shift
            if nx >= 0:
                updated.append((nx, p, tid))
    signal_deque.clear()
    signal_deque.extend(updated)

class TradingDashboardBot:
    def __init__(self, root):
        self.root = root
        self.symbol = SYMBOL
        self.root.title(f"Micro Trading Bot - {self.symbol}")
        self.root.geometry("1400x900")
        
        # Data storage
        self.prices = deque(maxlen=MAX_DATA_POINTS)
        self.bid_prices = deque(maxlen=MAX_DATA_POINTS)
        self.ask_prices = deque(maxlen=MAX_DATA_POINTS)
        self.timestamps = deque(maxlen=MAX_DATA_POINTS)
        self.buy_signals = deque()  # Buy entry points: (x, price, trade_id, cost)
        self.sell_signals = deque()  # Sell entry points: (x, price, trade_id, cost)
        self.buy_close_signals = deque()  # Buy close points: (x, price, trade_id)
        self.sell_close_signals = deque()  # Sell close points: (x, price, trade_id)
        self.trades_history = []
        self.trade_counter = 0  # Unique trade ID
        
        self.strategy = MicroTradingStrategy()
        self.tick_count = 0
        self.connection_status = "Disconnected"
        self.logger = TickLogger()
        
        # Setup UI
        self.setup_ui()
        
        # Start WebSocket connection in background thread
        self.ws_thread = threading.Thread(target=self.start_websocket, daemon=True)
        self.ws_thread.start()
    
    def setup_ui(self):
        """Setup the UI components"""
        # Main container
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Header frame
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Title
        title_label = ttk.Label(header_frame, text=f"🤖 Micro Trading Bot - {self.symbol}", 
                               font=("Arial", 16, "bold"))
        title_label.pack(side=tk.LEFT)
        
        # Status
        self.status_label = ttk.Label(header_frame, text="Status: Connecting...", 
                                      font=("Arial", 10))
        self.status_label.pack(side=tk.RIGHT)
        
        # Stats frame (horizontal layout)
        stats_frame = ttk.LabelFrame(main_frame, text="Trading Statistics", padding=10)
        stats_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Create grid for stats
        stat_items = [
            ("Current Price", "current_price_label"),
            ("Position", "position_label"),
            ("Trades", "trades_label"),
            ("Win Rate", "win_rate_label"),
            ("Daily P/L", "daily_pnl_label"),
            ("Total P/L", "total_pnl_label"),
            ("Max Drawdown", "max_drawdown_label"),
        ]
        
        for i, (label_text, attr_name) in enumerate(stat_items):
            col = i % 4
            row = i // 4
            
            frame = ttk.Frame(stats_frame)
            frame.grid(row=row, column=col, padx=15, pady=5, sticky="w")
            
            label = ttk.Label(frame, text=label_text + ":", font=("Arial", 9))
            label.pack(side=tk.LEFT)
            
            value_label = ttk.Label(frame, text="--", font=("Arial", 10, "bold"))
            value_label.pack(side=tk.LEFT, padx=(5, 0))
            
            setattr(self, attr_name, value_label)
        
        # Charts frame (left chart + right info)
        charts_container = ttk.Frame(main_frame)
        charts_container.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Left: Price chart
        chart_frame = ttk.LabelFrame(charts_container, text="Price Chart & Signals", padding=5)
        chart_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # Create figure
        self.fig = Figure(figsize=(8, 5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title(f"{self.symbol} Price with Buy/Sell Signals")
        self.ax.set_xlabel("Time (Events)")
        self.ax.set_ylabel("Price ($)")
        self.ax.grid(True, alpha=0.3)
        
        # Embed matplotlib
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Right: Recent trades
        trades_frame = ttk.LabelFrame(charts_container, text="Recent Trades", padding=5)
        trades_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(10, 0))
        
        scrollbar = ttk.Scrollbar(trades_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.trades_text = tk.Text(trades_frame, width=35, height=20, 
                                   yscrollcommand=scrollbar.set,
                                   font=("Courier", 8))
        self.trades_text.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.trades_text.yview)
        
        # Bottom: Events log
        events_frame = ttk.LabelFrame(main_frame, text="Tick Events Log", padding=5)
        events_frame.pack(fill=tk.X)
        
        scrollbar = ttk.Scrollbar(events_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.events_text = tk.Text(events_frame, height=4, yscrollcommand=scrollbar.set,
                                   font=("Courier", 8))
        self.events_text.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.events_text.yview)
    
    def update_chart(self):
        """Update the price chart with all trade signals - symbols stay aligned"""
        self.ax.clear()
        
        if len(self.prices) > 0:
            x_data = list(range(len(self.prices)))
            
            # Plot price line
            self.ax.plot(x_data, list(self.prices), label="Price", 
                        color="#2E7D32", linewidth=2, marker='o', markersize=3, alpha=0.8)
            
            # Build a mapping of price index to trade signals for accurate alignment
            buy_open_map = {x: (p, tid, cost) for x, p, tid, cost in self.buy_signals}
            sell_open_map = {x: (p, tid, cost) for x, p, tid, cost in self.sell_signals}
            buy_close_map = {x: (p, tid) for x, p, tid in self.buy_close_signals}
            sell_close_map = {x: (p, tid) for x, p, tid in self.sell_close_signals}
            
            # Plot BUY OPEN signals (green upward triangle)
            if buy_open_map:
                buy_x = list(buy_open_map.keys())
                buy_y = [buy_open_map[x][0] for x in buy_x]
                self.ax.scatter(buy_x, buy_y, marker='^', color='#00D084', s=300, 
                              label="BUY OPEN", zorder=5, edgecolors='darkgreen', linewidths=2)
                
                # Add trade IDs and cost to buy signals
                for x in buy_x:
                    p, tid, cost = buy_open_map[x]
                    self.ax.text(x, p + 0.3, f"B{tid}\n${cost:.0f}", fontsize=8, ha='center', 
                               color='darkgreen', weight='bold')
            
            # Plot SELL OPEN signals (red downward triangle)
            if sell_open_map:
                sell_x = list(sell_open_map.keys())
                sell_y = [sell_open_map[x][0] for x in sell_x]
                self.ax.scatter(sell_x, sell_y, marker='v', color='#FF6B6B', s=300, 
                              label="SELL OPEN", zorder=5, edgecolors='darkred', linewidths=2)
                
                # Add trade IDs and cost to sell signals
                for x in sell_x:
                    p, tid, cost = sell_open_map[x]
                    self.ax.text(x, p - 0.5, f"S{tid}\n${cost:.0f}", fontsize=8, ha='center', 
                               color='darkred', weight='bold')
            
            # Plot BUY CLOSE signals (green X)
            if buy_close_map:
                buy_close_x = list(buy_close_map.keys())
                buy_close_y = [buy_close_map[x][0] for x in buy_close_x]
                self.ax.scatter(buy_close_x, buy_close_y, marker='X', color='#00AA55', s=250, 
                              label="BUY CLOSE", zorder=4, edgecolors='darkgreen', linewidths=1, alpha=0.7)
                
                # Add trade IDs to buy close
                for x in buy_close_x:
                    p, tid = buy_close_map[x]
                    self.ax.text(x, p + 0.5, f"B{tid}✓", fontsize=7, ha='center', 
                               color='darkgreen', weight='bold', alpha=0.8)
            
            # Plot SELL CLOSE signals (red X)
            if sell_close_map:
                sell_close_x = list(sell_close_map.keys())
                sell_close_y = [sell_close_map[x][0] for x in sell_close_x]
                self.ax.scatter(sell_close_x, sell_close_y, marker='X', color='#CC4444', s=250, 
                              label="SELL CLOSE", zorder=4, edgecolors='darkred', linewidths=1, alpha=0.7)
                
                # Add trade IDs to sell close
                for x in sell_close_x:
                    p, tid = sell_close_map[x]
                    self.ax.text(x, p - 0.5, f"S{tid}✓", fontsize=7, ha='center', 
                               color='darkred', weight='bold', alpha=0.8)
            
            self.ax.legend(loc='upper left', fontsize=9)
            self.ax.set_title(f"{self.symbol} Price with Trade Signals (Unique IDs)")
            self.ax.set_xlabel("Time (Ticks)")
            self.ax.set_ylabel("Price ($)")
            self.ax.grid(True, alpha=0.3)
            
            # Set y-axis limits
            if self.prices:
                price_min = min(self.prices)
                price_max = max(self.prices)
                padding = (price_max - price_min) * 0.1 if price_max != price_min else 1
                self.ax.set_ylim(price_min - padding, price_max + padding)
            
            # Show the full window of retained ticks to avoid shrinking after 60+ ticks
            if len(self.prices) > 1:
                self.ax.set_xlim(0, len(self.prices) - 1)
            else:
                self.ax.set_xlim(0, 1)
        
        self.fig.tight_layout()
        self.canvas.draw()
    
    def update_ui(self, data):
        """Update UI with new data (expects raw snapshot)."""
        try:
            if "ticker" not in data:
                return

            ticker = data.get("ticker", {})
            day = ticker.get("day", {})
            minute = ticker.get("min", {})

            price = minute.get("c") or day.get("c")
            if price is None:
                return

            volume = minute.get("v") or day.get("v") or 0
            bid = round(price - 0.01, 2)
            ask = round(price + 0.01, 2)
            updated_ns = ticker.get("updated") or int(time.time() * 1e9)

            # Synthetic results dict for downstream processing
            results = {
                "P": price,
                "p": bid,
                "S": volume,
                "s": volume,
                "T": ticker.get("ticker", self.symbol),
                "t": updated_ns,
                "q": updated_ns,
                "X": 11,
                "x": 11,
                "y": updated_ns,
                "z": 1,
            }
            
            if price is not None:
                # Update prices; when window slides, shift stored signal indices
                window_full = len(self.prices) == self.prices.maxlen
                self.prices.append(price)
                self.bid_prices.append(bid)
                self.ask_prices.append(ask)
                self.tick_count += 1

                # If we just dropped the oldest point, shift trade signal positions left
                if window_full:
                    _shift_and_prune_signals(self.buy_signals, shift=-1, has_cost=True)
                    _shift_and_prune_signals(self.sell_signals, shift=-1, has_cost=True)
                    _shift_and_prune_signals(self.buy_close_signals, shift=-1, has_cost=False)
                    _shift_and_prune_signals(self.sell_close_signals, shift=-1, has_cost=False)
                
                # Process through strategy
                tick = Tick(price=price, volume=results.get("S"), 
                          timestamp_ns=results.get("t"), symbol=self.symbol)
                
                event = self.strategy.process_tick(tick)
                
                # Log the tick and event
                self.logger.log_tick(tick, event)
                
                # Handle trade signals with unique IDs
                if event["action"] == "OPEN":
                    trade = event["trade"]
                    self.trade_counter += 1
                    if trade and trade.direction == "LONG":
                        cost = trade.entry_price * trade.position_size
                        self.buy_signals.append((len(self.prices)-1, price, self.trade_counter, cost))
                    elif trade and trade.direction == "SHORT":
                        cost = trade.entry_price * trade.position_size
                        self.sell_signals.append((len(self.prices)-1, price, self.trade_counter, cost))
                
                if event["action"] == "CLOSE":
                    trade = event["trade"]
                    if trade:
                        self.trades_history.append(trade)
                        self.logger.log_trade(trade)
                        
                        # Track close point with same trade ID
                        # Find the trade ID from open signals
                        trade_id = self.trade_counter
                        
                        if trade.direction == "LONG":
                            self.buy_close_signals.append((len(self.prices)-1, trade.exit_price, trade_id))
                        elif trade.direction == "SHORT":
                            self.sell_close_signals.append((len(self.prices)-1, trade.exit_price, trade_id))
                        
                        # Update trades display
                        trade_str = (f"[{trade.exit_time.strftime('%H:%M:%S')}] "
                                   f"{trade.direction} @ ${trade.entry_price:.2f} → "
                                   f"${trade.exit_price:.2f} ({trade.exit_reason}) | "
                                   f"P/L: ${trade.pnl:.3f} ({trade.pnl_pct*100:+.2f}%)\n")
                        
                        # Color by profit/loss
                        self.trades_text.insert(tk.END, trade_str)
                        if trade.pnl > 0:
                            line_num = int(self.trades_text.index(tk.END).split('.')[0]) - 1
                            self.trades_text.tag_add("profit", f"{line_num}.0", f"{line_num}.end")
                            self.trades_text.tag_config("profit", foreground="#00D084")
                        elif trade.pnl < 0:
                            line_num = int(self.trades_text.index(tk.END).split('.')[0]) - 1
                            self.trades_text.tag_add("loss", f"{line_num}.0", f"{line_num}.end")
                            self.trades_text.tag_config("loss", foreground="#FF6B6B")
                        
                        self.trades_text.see(tk.END)
                
                # Update stats
                metrics = event["metrics"]
                self.current_price_label.config(text=f"${price:.2f}")
                
                position_text = "LONG" if self.strategy.current_position and self.strategy.current_position.direction == "LONG" else \
                               "SHORT" if self.strategy.current_position and self.strategy.current_position.direction == "SHORT" else \
                               "None"
                self.position_label.config(text=position_text)
                
                self.trades_label.config(text=f"{metrics['total_trades']}")
                self.win_rate_label.config(text=f"{metrics['win_rate']*100:.1f}%")
                
                daily_pnl_str = f"${metrics['daily_pnl']:.2f}"
                daily_pnl_color = "green" if metrics['daily_pnl'] >= 0 else "red"
                self.daily_pnl_label.config(text=daily_pnl_str)
                
                total_pnl_str = f"${metrics['total_pnl']:.2f}"
                total_pnl_color = "green" if metrics['total_pnl'] >= 0 else "red"
                self.total_pnl_label.config(text=total_pnl_str)
                
                self.max_drawdown_label.config(text=f"${metrics['max_drawdown']:.2f}")
                
                # Update events log
                event_text = f"[{datetime.now().strftime('%H:%M:%S')}] Price: ${price:.2f} | Bid: ${bid:.2f} | Ask: ${ask:.2f}"
                self.events_text.insert(tk.END, event_text + "\n")
                self.events_text.see(tk.END)
                
                # Keep only last 50 lines
                line_count = int(self.events_text.index('end-1c').split('.')[0])
                if line_count > 50:
                    self.events_text.delete('1.0', '2.0')
                
                # Update chart
                self.update_chart()
        
        except Exception as e:
            print(f"Error updating UI: {e}")
            import traceback
            traceback.print_exc()
    
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
                        text=f"Status: Connected | {self.tick_count} ticks"))
                    
                    print(f"Connected to {uri}")
                    
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            if "ticker" in data:
                                self.root.after(0, self.update_ui, data)
                        except json.JSONDecodeError:
                            pass
                        except Exception as e:
                            print(f"Error processing message: {e}")
            
            except ConnectionRefusedError:
                self.connection_status = "Disconnected"
                self.root.after(0, lambda: self.status_label.config(
                    text="Status: Connection Failed - Retrying..."))
                print("Connection failed. Retrying in 3 seconds...")
                await asyncio.sleep(3)
            
            except Exception as e:
                self.connection_status = "Error"
                self.root.after(0, lambda: self.status_label.config(
                    text=f"Status: Error"))
                print(f"Error: {e}")
                await asyncio.sleep(3)


def main():
    root = tk.Tk()
    dashboard = TradingDashboardBot(root)
    root.mainloop()


if __name__ == "__main__":
    main()
