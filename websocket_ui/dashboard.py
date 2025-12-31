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

from bot.config import WEBSOCKET_CONFIG, SYMBOL

# Configuration
WEBSOCKET_URI = WEBSOCKET_CONFIG["uri"]
MAX_DATA_POINTS = 100

class TradingDashboard:
    def __init__(self, root):
        self.root = root
        self.symbol = SYMBOL
        self.root.title(f"Trading Dashboard - {self.symbol}")
        self.root.geometry("1200x700")
        
        # Data storage
        self.prices = deque(maxlen=MAX_DATA_POINTS)
        self.bid_prices = deque(maxlen=MAX_DATA_POINTS)
        self.ask_prices = deque(maxlen=MAX_DATA_POINTS)
        self.timestamps = deque(maxlen=MAX_DATA_POINTS)
        self.event_count = 0
        self.connection_status = "Disconnected"
        
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
        title_label = ttk.Label(header_frame, text=f"{self.symbol} Trading Dashboard", 
                               font=("Arial", 16, "bold"))
        title_label.pack(side=tk.LEFT)
        
        # Status
        self.status_label = ttk.Label(header_frame, text="Status: Connecting...", 
                                      font=("Arial", 10))
        self.status_label.pack(side=tk.RIGHT)
        
        # Stats frame
        stats_frame = ttk.LabelFrame(main_frame, text="Statistics", padding=10)
        stats_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Stats grid
        self.current_price_label = ttk.Label(stats_frame, text="Current Price: --", 
                                            font=("Arial", 11, "bold"))
        self.current_price_label.pack(side=tk.LEFT, padx=20)
        
        self.bid_label = ttk.Label(stats_frame, text="Bid: --", font=("Arial", 10))
        self.bid_label.pack(side=tk.LEFT, padx=20)
        
        self.ask_label = ttk.Label(stats_frame, text="Ask: --", font=("Arial", 10))
        self.ask_label.pack(side=tk.LEFT, padx=20)
        
        self.events_label = ttk.Label(stats_frame, text="Events: 0", font=("Arial", 10))
        self.events_label.pack(side=tk.LEFT, padx=20)
        
        self.spread_label = ttk.Label(stats_frame, text="Spread: --", font=("Arial", 10))
        self.spread_label.pack(side=tk.LEFT, padx=20)
        
        # Chart frame
        chart_frame = ttk.LabelFrame(main_frame, text="Price Chart", padding=5)
        chart_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create figure
        self.fig = Figure(figsize=(11, 5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title(f"{self.symbol} Price Movement")
        self.ax.set_xlabel("Time (Events)")
        self.ax.set_ylabel("Price ($)")
        self.ax.grid(True, alpha=0.3)
        
        # Embed matplotlib in tkinter
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Recent events frame
        events_frame = ttk.LabelFrame(main_frame, text="Recent Events", padding=5)
        events_frame.pack(fill=tk.X, pady=(10, 0))
        
        # Scrollable text widget
        scrollbar = ttk.Scrollbar(events_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.events_text = tk.Text(events_frame, height=6, yscrollcommand=scrollbar.set,
                                   font=("Courier", 9))
        self.events_text.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.events_text.yview)
    
    def update_chart(self):
        """Update the price chart"""
        self.ax.clear()
        
        if len(self.prices) > 0:
            x_data = list(range(len(self.prices)))
            self.ax.plot(x_data, list(self.prices), label="Last Price", 
                        color="#2E7D32", linewidth=2, marker='o', markersize=4)
            self.ax.plot(x_data, list(self.bid_prices), label="Bid", 
                        color="#1976D2", linewidth=1, alpha=0.7, linestyle='--')
            self.ax.plot(x_data, list(self.ask_prices), label="Ask", 
                        color="#D32F2F", linewidth=1, alpha=0.7, linestyle='--')
            
            self.ax.legend(loc='upper left')
            self.ax.set_title(f"{self.symbol} Price Movement")
            self.ax.set_xlabel("Time (Events)")
            self.ax.set_ylabel("Price ($)")
            self.ax.grid(True, alpha=0.3)
            
            # Set y-axis limits with some padding
            price_min = min(self.bid_prices) if self.bid_prices else min(self.prices)
            price_max = max(self.ask_prices) if self.ask_prices else max(self.prices)
            padding = (price_max - price_min) * 0.1 if price_max != price_min else 1
            self.ax.set_ylim(price_min - padding, price_max + padding)
        
        self.fig.tight_layout()
        self.canvas.draw()
    
    def update_ui(self, data):
        """Update UI with new data"""
        try:
            results = data.get("results", {})
            price = results.get("P")
            bid = results.get("p")
            ask = price + (price - bid) if bid else price  # Calculate ask from bid-ask spread
            
            if price is not None:
                self.prices.append(price)
                self.bid_prices.append(bid)
                self.ask_prices.append(ask)
                self.timestamps.append(datetime.now().strftime("%H:%M:%S"))
                self.event_count += 1
                
                # Update stats
                spread = ask - bid if bid else 0
                self.current_price_label.config(
                    text=f"Current Price: ${price:.2f}")
                self.bid_label.config(text=f"Bid: ${bid:.2f}")
                self.ask_label.config(text=f"Ask: ${ask:.2f}")
                self.spread_label.config(text=f"Spread: ${spread:.2f}")
                self.events_label.config(text=f"Events: {self.event_count}")
                
                # Update chart
                self.update_chart()
                
                # Update events log
                event_text = f"[{self.timestamps[-1]}] Price: ${price:.2f} | Bid: ${bid:.2f} | Ask: ${ask:.2f} | Spread: ${spread:.2f}"
                self.events_text.insert(tk.END, event_text + "\n")
                self.events_text.see(tk.END)
                
                # Keep only last 50 events in text widget
                line_count = int(self.events_text.index('end-1c').split('.')[0])
                if line_count > 50:
                    self.events_text.delete('1.0', '2.0')
        
        except Exception as e:
            print(f"Error updating UI: {e}")
    
    def start_websocket(self):
        """Connect to WebSocket server and receive data"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.websocket_loop())
    
    async def websocket_loop(self):
        """WebSocket connection loop"""
        while True:
            try:
                uri = "ws://localhost:8765"
                async with websockets.connect(uri) as websocket:
                    self.connection_status = "Connected"
                    self.root.after(0, lambda: self.status_label.config(
                        text=f"Status: Connected | {self.event_count} events"))
                    
                    print(f"Connected to {uri}")
                    
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            if "results" in data:
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
                    text=f"Status: Error - {str(e)[:30]}"))
                print(f"Error: {e}")
                await asyncio.sleep(3)


def main():
    root = tk.Tk()
    dashboard = TradingDashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
