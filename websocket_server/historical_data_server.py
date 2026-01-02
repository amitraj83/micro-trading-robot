"""
Historical Data WebSocket Server
Streams real Yahoo Finance historical data to bot clients
Loads pre-downloaded data from data/historical_data.json file
Replaces fake_polygon_server.py with real market data
"""

import asyncio
import json
import logging
from datetime import datetime
import websockets
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
HOST = "localhost"
PORT = 8001
SYMBOLS = ["QQQ", "SPY", "NVDA", "AAPL", "MSFT"]  # Real, liquid symbols
DAYS_BACK = 7
INTERVAL = "1m"  # 1-minute bars

# Global state
connected_clients: set = set()
playback_speed = 1.0  # 1.0 = real-time (1 bar per second), higher = faster

class HistoricalDataServer:
    """Serves historical data to WebSocket clients"""
    
    def __init__(self, symbols: list, days_back: int = 7, data_file: str = "data/historical_data.json"):
        self.symbols = symbols
        self.data_file = Path(data_file)
        self.bars = []
        self.bar_iterator = None
        self.connected_clients = set()
        self.subscriptions = {}  # Track symbol subscriptions per client
        self.playback_task = None
        self.is_running = False
        
    async def initialize(self) -> bool:
        """Load pre-downloaded data from JSON file"""
        logger.info("Initializing historical data server...")
        
        if not self.data_file.exists():
            logger.error(f"Data file not found: {self.data_file}")
            logger.error("Please run: python download_historical_data.py")
            return False
        
        try:
            with open(self.data_file, 'r') as f:
                data = json.load(f)
            
            self.bars = data.get('bars', [])
            metadata = data.get('metadata', {})
            
            if not self.bars:
                logger.error("No bars found in data file")
                return False
            
            logger.info(f"📊 Data loaded from {self.data_file}:")
            logger.info(f"   Downloaded at: {metadata.get('downloaded_at', 'unknown')}")
            logger.info(f"   Total bars: {metadata.get('total_bars', len(self.bars))}")
            logger.info(f"   Date range: {metadata.get('date_range', {})}")
            bars_per_sym = metadata.get('bars_per_symbol', {})
            for sym, count in bars_per_sym.items():
                logger.info(f"   {sym}: {count} bars")
            
            # Reset iterator to start of bars
            self.bar_iterator = iter(self.bars)
            
            return True
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in data file: {e}")
            return False
        except Exception as e:
            logger.error(f"Error loading data file: {e}", exc_info=True)
            return False
    
    async def broadcast_bar(self, bar: dict):
        """Send bar to all subscribed clients"""
        if not self.connected_clients:
            return
        
        symbol = bar['sym']
        
        # Send to all clients subscribed to this symbol
        for client, subscriptions in self.subscriptions.items():
            if symbol in subscriptions and client in self.connected_clients:
                try:
                    await client.send(json.dumps(bar))
                except websockets.exceptions.ConnectionClosed:
                    pass
                except Exception as e:
                    logger.error(f"Error sending to client: {e}")
    
    async def playback_loop(self):
        """Stream bars to connected clients"""
        logger.info("🎬 Starting historical data playback...")
        self.is_running = True
        
        # Reset iterator to start of bars
        self.bar_iterator = iter(self.bars)
        bar_count = 0
        last_symbol = None
        
        while self.is_running:
            try:
                bar = next(self.bar_iterator)
            except StopIteration:
                logger.info(f"✅ Playback complete: {bar_count} bars sent")
                self.is_running = False
                # Notify clients
                for client in self.connected_clients:
                    try:
                        await client.send(json.dumps({"type": "END"}))
                    except:
                        pass
                break
            
            await self.broadcast_bar(bar)
            bar_count += 1
            
            # Log progress every 100 bars
            if bar_count % 100 == 0 or bar['sym'] != last_symbol:
                logger.info(f"  Bar {bar_count}: {bar['sym']} @ ${bar['c']:.2f} (vol: {bar['v']:,})")
                last_symbol = bar['sym']
            
            # Wait 1 second between bars (simulate real-time)
            await asyncio.sleep(1.0 / playback_speed)
    
    async def handle_client(self, websocket):
        """Handle new WebSocket client"""
        client_id = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"✅ Client connected: {client_id}")
        
        self.connected_clients.add(websocket)
        self.subscriptions[websocket] = set()
        
        try:
            async for message in websocket:
                try:
                    msg = json.loads(message)
                    action = msg.get('action', '').lower()
                    
                    if action == 'subscribe':
                        params = msg.get('params', '')
                        # Extract symbol from params like "A.QQQ"
                        if params.startswith('A.'):
                            symbol = params[2:]
                            self.subscriptions[websocket].add(symbol)
                            logger.info(f"  {client_id} subscribed to {symbol}")
                        
                    elif action == 'unsubscribe':
                        params = msg.get('params', '')
                        if params.startswith('A.'):
                            symbol = params[2:]
                            self.subscriptions[websocket].discard(symbol)
                            logger.info(f"  {client_id} unsubscribed from {symbol}")
                    
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from {client_id}: {message}")
        
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            logger.error(f"Error handling client {client_id}: {e}")
        finally:
            self.connected_clients.discard(websocket)
            self.subscriptions.pop(websocket, None)
            logger.info(f"❌ Client disconnected: {client_id}")

async def start_server():
    """Start historical data WebSocket server"""
    global data_loader
    
    logger.info("=" * 80)
    logger.info("🚀 HISTORICAL DATA WEBSOCKET SERVER (Yahoo Finance)")
    logger.info("=" * 80)
    
    # Initialize server
    server = HistoricalDataServer(SYMBOLS, days_back=DAYS_BACK)
    
    if not await server.initialize():
        logger.error("Failed to initialize server")
        return
    
    # Start WebSocket server
    async with websockets.serve(server.handle_client, HOST, PORT):
        logger.info(f"📡 Server listening on ws://{HOST}:{PORT}")
        
        # Wait a moment for client to connect, then start playback
        await asyncio.sleep(2)
        
        # Start playback if clients connected
        if server.connected_clients:
            await server.playback_loop()
        else:
            logger.warning("⚠️  No clients connected, waiting...")
            # Keep running and start playback when client connects
            playback_task = None
            
            while True:
                if server.connected_clients and not playback_task:
                    playback_task = asyncio.create_task(server.playback_loop())
                
                if playback_task and playback_task.done():
                    logger.info("Playback finished")
                    break
                
                await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        import traceback
        traceback.print_exc()
