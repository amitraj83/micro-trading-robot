"""
Trading212 API Integration
Handles authentication, order creation, position management, and account data retrieval.
"""

import os
import aiohttp
import asyncio
import logging
from typing import Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# Configuration from environment
TRADING212_LIVE = os.getenv("LIVE", "false").lower() == "true"

# Select credentials based on LIVE flag
if TRADING212_LIVE:
    API_KEY = os.getenv("TRADING212_API_KEY", "")
    API_SECRET = os.getenv("TRADING212_API_SECRET", "")
    BASE_URL = os.getenv("TRADING212_LIVE_ENVIRONMENT", "https://live.trading212.com/api/v0")
    logger.info("🔴 Trading212 LIVE MODE - Using production environment")
else:
    API_KEY = os.getenv("TRADING212_DEMO_API_KEY", "")
    API_SECRET = os.getenv("TRADING212_DEMO_API_SECRET", "")
    BASE_URL = os.getenv("TRADING212_DEMO_ENVIRONMENT", "https://demo.trading212.com/api/v0")
    logger.info("🟢 Trading212 DEMO MODE - Using demo environment")

ACCOUNT_CURRENCY = os.getenv("TRADING212_ACCOUNT_CURRENCY", "EUR")


class Trading212Client:
    """Async HTTP client for Trading212 API with authentication and error handling."""
    
    def __init__(self):
        self.base_url = BASE_URL
        self.api_key = API_KEY
        self.api_secret = API_SECRET
        self.session: Optional[aiohttp.ClientSession] = None
        self.mode = "LIVE" if TRADING212_LIVE else "DEMO"
        
        if not self.api_key or not self.api_secret:
            logger.error(f"❌ Trading212 credentials missing! KEY: {bool(self.api_key)}, SECRET: {bool(self.api_secret)}")
    
    async def __aenter__(self):
        """Context manager entry."""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self.session:
            await self.session.close()
    
    def _get_headers(self) -> Dict[str, str]:
        """Build request headers with authentication."""
        return {
            "X-API-KEY": self.api_key,
            "X-API-SECRET": self.api_secret,
            "Content-Type": "application/json"
        }
    
    async def _request(self, method: str, endpoint: str, json_data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Make authenticated API request to Trading212.
        
        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            endpoint: API endpoint (e.g., "/accounts/")
            json_data: Request body (for POST/PUT)
            
        Returns:
            Response JSON dict
        """
        if not self.session:
            logger.error("❌ Session not initialized. Use 'async with Trading212Client() as client:'")
            return {}
        
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()
        
        try:
            logger.info(f"📤 Trading212 API Request: {method} {url}")
            if json_data:
                logger.info(f"   Payload: {json_data}")
            
            async with self.session.request(method, url, json=json_data, headers=headers, timeout=10) as resp:
                response_text = await resp.text()
                
                logger.info(f"📥 Trading212 API Response: {resp.status}")
                logger.info(f"   Body: {response_text[:500]}")  # First 500 chars
                
                if resp.status >= 400:
                    logger.error(f"❌ Trading212 API {resp.status}: {response_text}")
                    return {"error": response_text, "status": resp.status}
                
                try:
                    return await resp.json() if response_text else {}
                except:
                    return {"raw_response": response_text}
        
        except asyncio.TimeoutError:
            logger.error(f"❌ Trading212 API timeout: {endpoint}")
            return {"error": "timeout"}
        except Exception as e:
            logger.error(f"❌ Trading212 API exception: {e}")
            return {"error": str(e)}
    
    async def get_account_info(self) -> Dict[str, Any]:
        """
        Get account information.
        
        Returns:
            Account dict with balance, cash, etc.
        """
        logger.info(f"📊 Fetching {self.mode} account info...")
        response = await self._request("GET", "/api/v0/equity/account/summary")
        
        if "error" not in response:
            logger.info(f"✅ Account fetched: {response.get('id')}")
        
        return response
    
    async def get_positions(self) -> Dict[str, Any]:
        """
        Get all open positions.
        
        Returns:
            List of position dicts
        """
        logger.info(f"📋 Fetching {self.mode} positions...")
        response = await self._request("GET", "/api/v0/equity/positions")
        
        if isinstance(response, list):
            logger.info(f"✅ Fetched {len(response)} positions")
        
        return response
    
    async def get_orders(self) -> Dict[str, Any]:
        """
        Get all pending orders.
        
        Returns:
            List of order dicts
        """
        logger.info(f"📋 Fetching {self.mode} orders...")
        response = await self._request("GET", "/api/v0/equity/orders")
        
        if isinstance(response, list):
            logger.info(f"✅ Fetched {len(response)} orders")
        
        return response
    
    async def create_buy_order(self, symbol: str, quantity: float) -> Dict[str, Any]:
        """
        Create a BUY market order.
        
        Args:
            symbol: Ticker symbol (e.g., "AAPL")
            quantity: Number of shares to buy
            
        Returns:
            Order response dict with order_id
        """
        # Ensure ticker has the _US_EQ suffix
        ticker = symbol if "_" in symbol else f"{symbol}_US_EQ"
        
        payload = {
            "ticker": ticker,
            "quantity": quantity  # Positive for BUY
        }
        
        logger.info(f"📈 Creating BUY order: {ticker} x {quantity} shares ({self.mode})")
        response = await self._request("POST", "/api/v0/equity/orders/market", payload)
        
        if "id" in response:
            order_id = response.get("id")
            logger.info(f"✅ BUY order created: {order_id}")
        elif "error" not in response:
            logger.info(f"✅ Order response: {response}")
        
        return response
    
    async def create_sell_order(self, symbol: str, quantity: float) -> Dict[str, Any]:
        """
        Create a SELL market order.
        
        Args:
            symbol: Ticker symbol
            quantity: Number of shares to sell
            
        Returns:
            Order response dict with order_id
        """
        # Ensure ticker has the _US_EQ suffix
        ticker = symbol if "_" in symbol else f"{symbol}_US_EQ"
        
        payload = {
            "ticker": ticker,
            "quantity": -quantity  # Negative for SELL
        }
        
        logger.info(f"📉 Creating SELL order: {ticker} x {quantity} shares ({self.mode})")
        response = await self._request("POST", "/api/v0/equity/orders/market", payload)
        
        if "id" in response:
            order_id = response.get("id")
            logger.info(f"✅ SELL order created: {order_id}")
        elif "error" not in response:
            logger.info(f"✅ Order response: {response}")
        
        return response
    
    async def close_position(self, symbol: str, quantity: float = None) -> Dict[str, Any]:
        """
        Close a position by selling all shares.
        
        Args:
            symbol: Ticker symbol
            quantity: Optional - specific quantity to sell. If None, closes entire position.
            
        Returns:
            Order response dict
        """
        # Get current positions to find the symbol
        positions = await self.get_positions()
        
        position_qty = None
        if isinstance(positions, list):
            for pos in positions:
                if pos.get("ticker") == symbol or pos.get("instrumentCode") == symbol:
                    position_qty = pos.get("quantity")
                    break
        
        if quantity is None:
            quantity = position_qty
        
        if quantity is None or quantity <= 0:
            logger.warning(f"⚠️  No position found for {symbol} to close")
            return {"error": "no_position"}
        
        logger.info(f"🔒 Closing position: {symbol} x {quantity} shares ({self.mode})")
        return await self.create_sell_order(symbol, quantity)
    
    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """
        Cancel a pending order.
        
        Args:
            order_id: ID of order to cancel
            
        Returns:
            Response dict
        """
        logger.info(f"❌ Cancelling order: {order_id} ({self.mode})")
        return await self._request("DELETE", f"/orders/{order_id}")


# Singleton instance for convenient usage
_client_instance: Optional[Trading212Client] = None


async def get_trading212_client() -> Trading212Client:
    """Get or create Trading212 client instance."""
    global _client_instance
    if _client_instance is None:
        _client_instance = Trading212Client()
    return _client_instance
