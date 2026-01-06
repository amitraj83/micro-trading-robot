"""
Trading212 Broker Manager
Manages order execution, position tracking, and synchronization between bot trades and Trading212.
"""

import logging
import asyncio
from typing import Dict, Optional, List
from datetime import datetime
from dataclasses import dataclass, field

# Support both module and package import contexts
try:
    from trading212_api import Trading212Client
except ImportError:  # Fallback when imported as part of the bot package
    from bot.trading212_api import Trading212Client

logger = logging.getLogger(__name__)


@dataclass
class BotPosition:
    """Represents a position created by the bot."""
    symbol: str
    entry_price: float
    entry_time: datetime
    quantity: float
    direction: str = "LONG"  # LONG or SHORT
    bot_trade_id: Optional[str] = None
    trading212_order_id: Optional[str] = None
    trading212_position_id: Optional[str] = None
    status: str = "PENDING"  # PENDING, OPEN, CLOSED, ERROR
    error_message: Optional[str] = None
    close_price: Optional[float] = None
    close_time: Optional[datetime] = None
    close_reason: Optional[str] = None


class Trading212Broker:
    """
    Manages orders and positions on Trading212.
    Bridges bot trading signals to actual Trading212 API calls.
    """
    
    def __init__(self):
        self.positions: Dict[str, BotPosition] = {}  # symbol -> position
        self.client: Optional[Trading212Client] = None
        self.enabled = True
        self.sync_interval = 60  # seconds - periodically sync with Trading212
        
        logger.info("✅ Trading212Broker initialized (auto-execute on/off based on config)")
    
    async def init_client(self):
        """Initialize Trading212 API client."""
        if self.client is None:
            self.client = Trading212Client()
            if not self.client.api_key or not self.client.api_secret:
                logger.error("❌ Trading212 credentials missing - broker disabled")
                self.enabled = False
            else:
                logger.info(f"✅ Trading212 client initialized ({self.client.mode} mode)")
    
    async def execute_open_trade(self, symbol: str, entry_price: float, quantity: float = 1.0) -> bool:
        """
        Execute a BUY trade on Trading212 when bot generates OPEN signal.
        
        Args:
            symbol: Ticker symbol
            entry_price: Entry price from bot signal
            quantity: Number of shares to buy
            
        Returns:
            True if order created successfully, False otherwise
        """
        if not self.enabled:
            logger.warning(f"⚠️  Trading212Broker disabled - skipping BUY for {symbol}")
            return False
        
        await self.init_client()
        
        # Check if position already exists
        if symbol in self.positions:
            logger.warning(f"⚠️  Position already exists for {symbol} - not opening new trade")
            return False
        
        try:
            # Create BUY order on Trading212
            async with Trading212Client() as client:
                response = await client.create_buy_order(symbol, quantity)
            
            if "error" in response:
                logger.error(f"❌ Failed to create BUY order for {symbol}: {response['error']}")
                # Create position record with error status
                self.positions[symbol] = BotPosition(
                    symbol=symbol,
                    entry_price=entry_price,
                    entry_time=datetime.now(),
                    quantity=quantity,
                    status="ERROR",
                    error_message=response.get("error")
                )
                return False
            
            # Extract order ID from response
            order_id = response.get("orderId") or response.get("id")
            
            # Create position tracking record
            self.positions[symbol] = BotPosition(
                symbol=symbol,
                entry_price=entry_price,
                entry_time=datetime.now(),
                quantity=quantity,
                trading212_order_id=order_id,
                status="PENDING"
            )
            
            logger.info(f"✅ BUY order created for {symbol}: {quantity} shares @ ${entry_price} | Order ID: {order_id}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Exception creating BUY order for {symbol}: {e}")
            self.positions[symbol] = BotPosition(
                symbol=symbol,
                entry_price=entry_price,
                entry_time=datetime.now(),
                quantity=quantity,
                status="ERROR",
                error_message=str(e)
            )
            return False
    
    async def execute_close_trade(self, symbol: str, exit_price: float, exit_reason: str) -> bool:
        """
        Execute a SELL trade on Trading212 when bot generates CLOSE signal.
        
        Args:
            symbol: Ticker symbol
            exit_price: Exit price from bot signal
            exit_reason: Reason for exit (TP, SL, TIME, FLAT)
            
        Returns:
            True if close order created successfully, False otherwise
        """
        if not self.enabled:
            logger.warning(f"⚠️  Trading212Broker disabled - skipping CLOSE for {symbol}")
            return False
        
        await self.init_client()
        
        # Check if position exists
        if symbol not in self.positions:
            logger.warning(f"⚠️  No position found for {symbol} - cannot close")
            return False
        
        position = self.positions[symbol]
        
        try:
            # Create SELL order on Trading212
            async with Trading212Client() as client:
                response = await client.close_position(symbol, position.quantity)
            
            if "error" in response:
                logger.error(f"❌ Failed to close position for {symbol}: {response['error']}")
                position.status = "ERROR"
                position.error_message = response.get("error")
                return False
            
            # Update position record
            position.close_price = exit_price
            position.close_time = datetime.now()
            position.close_reason = exit_reason
            position.status = "CLOSED"
            
            # Calculate P&L
            pnl = (exit_price - position.entry_price) * position.quantity
            pnl_pct = (exit_price - position.entry_price) / position.entry_price * 100
            
            logger.info(
                f"✅ Position CLOSED for {symbol}: {position.quantity} shares @ ${exit_price} ({exit_reason}) | "
                f"P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)"
            )
            return True
        
        except Exception as e:
            logger.error(f"❌ Exception closing position for {symbol}: {e}")
            position.status = "ERROR"
            position.error_message = str(e)
            return False
    
    async def sync_positions(self) -> Dict[str, Dict]:
        """
        Periodically sync bot positions with Trading212 account.
        Verifies that all bot positions are reflected in Trading212.
        
        Returns:
            Dict with sync status and any discrepancies found
        """
        if not self.enabled:
            return {"status": "disabled"}
        
        await self.init_client()
        
        try:
            async with Trading212Client() as client:
                trading212_positions = await client.get_positions()
            
            if isinstance(trading212_positions, dict) and "error" in trading212_positions:
                logger.warning(f"⚠️  Could not fetch Trading212 positions: {trading212_positions['error']}")
                return {"status": "error", "message": trading212_positions['error']}
            
            # Compare bot positions with Trading212 positions
            discrepancies = []
            
            for symbol, bot_pos in self.positions.items():
                if bot_pos.status in ["CLOSED", "ERROR"]:
                    continue  # Only check open positions
                
                # Find matching position in Trading212
                found = False
                if isinstance(trading212_positions, list):
                    for t212_pos in trading212_positions:
                        if t212_pos.get("ticker") == symbol or t212_pos.get("instrumentCode") == symbol:
                            found = True
                            quantity = t212_pos.get("quantity")
                            if quantity != bot_pos.quantity:
                                discrepancies.append({
                                    "symbol": symbol,
                                    "issue": "quantity_mismatch",
                                    "bot_qty": bot_pos.quantity,
                                    "t212_qty": quantity
                                })
                            break
                
                if not found and bot_pos.status == "OPEN":
                    discrepancies.append({
                        "symbol": symbol,
                        "issue": "position_not_found_in_trading212",
                        "bot_qty": bot_pos.quantity
                    })
            
            sync_status = {
                "status": "success",
                "bot_positions": len([p for p in self.positions.values() if p.status == "OPEN"]),
                "discrepancies": discrepancies
            }
            
            if discrepancies:
                logger.warning(f"⚠️  Found {len(discrepancies)} position discrepancies: {discrepancies}")
            else:
                logger.info("✅ Position sync verified - no discrepancies")
            
            return sync_status
        
        except Exception as e:
            logger.error(f"❌ Exception during position sync: {e}")
            return {"status": "error", "message": str(e)}
    
    def get_position(self, symbol: str) -> Optional[BotPosition]:
        """Get position record for a symbol."""
        return self.positions.get(symbol)
    
    def get_open_positions(self) -> List[BotPosition]:
        """Get all open positions."""
        return [p for p in self.positions.values() if p.status == "OPEN"]
    
    def get_all_positions(self) -> Dict[str, BotPosition]:
        """Get all position records (including closed/error)."""
        return self.positions.copy()


# Global broker instance
_broker_instance: Optional[Trading212Broker] = None


async def get_trading212_broker() -> Trading212Broker:
    """Get or create Trading212 broker instance."""
    global _broker_instance
    if _broker_instance is None:
        _broker_instance = Trading212Broker()
    return _broker_instance
