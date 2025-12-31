import asyncio
import json
import websockets
import logging
from datetime import datetime
from bot.models import Tick
from bot.strategy import MicroTradingStrategy
from bot.config import WEBSOCKET_CONFIG, LOG_CONFIG, SYMBOL

# Setup logging
logging.basicConfig(
    level=LOG_CONFIG["level"],
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename=LOG_CONFIG["log_file"]  # Redirect logs to the specified file
)
logger = logging.getLogger(__name__)


class TradingBotClient:
    """WebSocket client integrated with trading strategy"""
    
    def __init__(self):
        self.strategy = MicroTradingStrategy()
        self.tick_count = 0
        self.trade_callbacks = []  # Callbacks when trades happen
        self.tick_callbacks = []   # Callbacks for each tick
    
    def register_trade_callback(self, callback):
        """Register a callback for trade events"""
        self.trade_callbacks.append(callback)
    
    def register_tick_callback(self, callback):
        """Register a callback for tick events"""
        self.tick_callbacks.append(callback)
    
    def on_tick(self, data: dict):
        """Process incoming tick data"""
        try:
            results = data.get("results", {})
            
            # Parse tick
            tick = Tick(
                price=results.get("P"),
                volume=results.get("S"),
                timestamp_ns=results.get("t"),
                symbol=results.get("T", SYMBOL),
            )
            
            self.tick_count += 1
            
            # Process through strategy
            event = self.strategy.process_tick(tick)
            
            # Call tick callbacks
            for cb in self.tick_callbacks:
                cb(event)
            
            # Handle trade events
            if event["action"]:
                logger.info(f"Trade event: {event['action']} - {event['reason']}")
                
                for cb in self.trade_callbacks:
                    cb(event)
        
        except Exception as e:
            logger.error(f"Error processing tick: {e}", exc_info=True)
    
    async def connect_and_run(self):
        """Connect to WebSocket and run trading bot"""
        uri = WEBSOCKET_CONFIG["uri"]
        
        while True:
            try:
                async with websockets.connect(uri) as websocket:
                    logger.info(f"Connected to {uri}")
                    
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            
                            # Only process trade events
                            if "results" in data:
                                self.on_tick(data)
                        
                        except json.JSONDecodeError:
                            pass
                        except Exception as e:
                            logger.error(f"Error processing message: {e}")
            
            except ConnectionRefusedError:
                logger.warning(f"Connection refused. Retrying in {WEBSOCKET_CONFIG['reconnect_delay']}s...")
                await asyncio.sleep(WEBSOCKET_CONFIG["reconnect_delay"])
            
            except Exception as e:
                logger.error(f"Connection error: {e}")
                await asyncio.sleep(WEBSOCKET_CONFIG["reconnect_delay"])


def run_bot():
    """Entry point for the bot"""
    bot = TradingBotClient()
    
    # Run async loop
    asyncio.run(bot.connect_and_run())


if __name__ == "__main__":
    run_bot()
