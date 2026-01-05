"""
Interactive Brokers TWS API Connection Module
Connects to Interactive Brokers via IB Gateway and provides API testing
"""

import socket
import time
import json
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, Tuple, List
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MarketDataAPI:
    """Fetch market data from public APIs (Alpha Vantage, Yahoo Finance, etc.)"""
    
    def __init__(self):
        """Initialize market data API handler"""
        self.base_urls = {
            "alpha_vantage": "https://www.alphavantage.co/query",
            "iex_cloud": "https://cloud.iexapis.com/stable",
        }
        self.timeout = 10
    
    def get_stock_quote_alpha_vantage(self, symbol: str, api_key: str = "demo") -> Dict[str, Any]:
        """
        Get stock quote from Alpha Vantage API
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            api_key: Alpha Vantage API key (default: demo key for testing)
            
        Returns:
            Dictionary with stock data or error info
        """
        try:
            logger.info(f"Fetching stock data for {symbol} from Alpha Vantage...")
            
            params = {
                "function": "GLOBAL_QUOTE",
                "symbol": symbol,
                "apikey": api_key
            }
            
            # Build URL with parameters
            url = f"{self.base_urls['alpha_vantage']}?"
            url += "&".join([f"{k}={v}" for k, v in params.items()])
            
            logger.debug(f"URL: {url}")
            
            # Make request
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            })
            
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            if "Global Quote" in data:
                quote = data["Global Quote"]
                if quote:
                    result = {
                        "symbol": symbol,
                        "price": float(quote.get("05. price", 0)),
                        "change": float(quote.get("09. change", 0)),
                        "change_percent": quote.get("10. change percent", "0%"),
                        "volume": int(quote.get("06. volume", 0)),
                        "bid": float(quote.get("02. bid", 0)),
                        "ask": float(quote.get("03. ask", 0)),
                        "timestamp": time.time(),
                        "source": "Alpha Vantage"
                    }
                    logger.info(f"✅ Got quote for {symbol}: ${result['price']}")
                    return result
                else:
                    return {
                        "error": "No data returned",
                        "symbol": symbol,
                        "source": "Alpha Vantage"
                    }
            
            return data  # Return raw response if not quote format
            
        except urllib.error.HTTPError as e:
            logger.error(f"❌ HTTP Error: {e.code}")
            return {
                "error": f"HTTP Error {e.code}",
                "symbol": symbol,
                "source": "Alpha Vantage"
            }
        except urllib.error.URLError as e:
            logger.error(f"❌ URL Error: {e.reason}")
            return {
                "error": f"URL Error: {e.reason}",
                "symbol": symbol,
                "source": "Alpha Vantage"
            }
        except socket.timeout:
            logger.error(f"❌ Request timeout")
            return {
                "error": "Request timeout",
                "symbol": symbol,
                "source": "Alpha Vantage"
            }
        except Exception as e:
            logger.error(f"❌ Error fetching data: {e}")
            return {
                "error": str(e),
                "symbol": symbol,
                "source": "Alpha Vantage"
            }
    
    def get_intraday_data(self, symbol: str, interval: str = "5min", api_key: str = "demo") -> Dict[str, Any]:
        """
        Get intraday time series data from Alpha Vantage
        
        Args:
            symbol: Stock symbol
            interval: Time interval (1min, 5min, 15min, 30min, 60min)
            api_key: Alpha Vantage API key
            
        Returns:
            Dictionary with intraday data
        """
        try:
            logger.info(f"Fetching {interval} intraday data for {symbol}...")
            
            params = {
                "function": f"TIME_SERIES_INTRADAY",
                "symbol": symbol,
                "interval": interval,
                "apikey": api_key
            }
            
            url = f"{self.base_urls['alpha_vantage']}?"
            url += "&".join([f"{k}={v}" for k, v in params.items()])
            
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            })
            
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            # Extract time series data
            if f"Time Series ({interval})" in data:
                time_series = data[f"Time Series ({interval})"]
                meta_data = data.get("Meta Data", {})
                
                # Convert to list of candles
                candles = []
                for timestamp, ohlc in sorted(time_series.items(), reverse=True)[:20]:
                    candles.append({
                        "timestamp": timestamp,
                        "open": float(ohlc["1. open"]),
                        "high": float(ohlc["2. high"]),
                        "low": float(ohlc["3. low"]),
                        "close": float(ohlc["4. close"]),
                        "volume": int(ohlc["5. volume"])
                    })
                
                result = {
                    "symbol": symbol,
                    "interval": interval,
                    "candles": candles,
                    "meta_data": meta_data,
                    "timestamp": time.time(),
                    "source": "Alpha Vantage"
                }
                
                logger.info(f"✅ Got {len(candles)} candles for {symbol}")
                return result
            
            return {"error": "No time series data", "data": data}
            
        except Exception as e:
            logger.error(f"❌ Error fetching intraday data: {e}")
            return {"error": str(e), "symbol": symbol}
    
    def get_crypto_price(self, symbol: str = "BTC") -> Dict[str, Any]:
        """
        Get cryptocurrency price from CoinGecko API (no API key required)
        
        Args:
            symbol: Crypto symbol (BTC, ETH, etc.)
            
        Returns:
            Dictionary with crypto price data
        """
        try:
            logger.info(f"Fetching {symbol} price from CoinGecko...")
            
            # Map symbol to CoinGecko ID
            crypto_map = {
                "BTC": "bitcoin",
                "ETH": "ethereum",
                "ADA": "cardano",
                "SOL": "solana",
                "XRP": "ripple"
            }
            
            crypto_id = crypto_map.get(symbol.upper(), symbol.lower())
            
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={crypto_id}&vs_currencies=usd&include_market_cap=true&include_24hr_vol=true"
            
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            })
            
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            if crypto_id in data:
                crypto_data = data[crypto_id]
                result = {
                    "symbol": symbol,
                    "price_usd": crypto_data.get("usd", 0),
                    "market_cap_usd": crypto_data.get("usd_market_cap", 0),
                    "volume_24h_usd": crypto_data.get("usd_24h_vol", 0),
                    "timestamp": time.time(),
                    "source": "CoinGecko"
                }
                logger.info(f"✅ Got {symbol} price: ${result['price_usd']}")
                return result
            
            return {"error": "Crypto not found", "symbol": symbol}
            
        except Exception as e:
            logger.error(f"❌ Error fetching crypto price: {e}")
            return {"error": str(e), "symbol": symbol}


class IBGatewayConnection:
    """Connect to Interactive Brokers TWS API via IB Gateway"""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 4002, client_id: int = 1):
        """
        Initialize IB Gateway connection parameters
        
        Args:
            host: IB Gateway host (default: localhost)
            port: IB Gateway port (default: 4002 for paper trading)
            client_id: Client ID for the connection
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.server_version = None
        self.connection_time = None
        
    def connect(self) -> bool:
        """
        Establish connection to IB Gateway
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            logger.info(f"Attempting to connect to IB Gateway at {self.host}:{self.port}...")
            
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5)
            self.socket.connect((self.host, self.port))
            
            self.connected = True
            self.connection_time = time.time()
            logger.info(f"✅ Connected to IB Gateway at {self.host}:{self.port}")
            
            return True
            
        except ConnectionRefusedError:
            logger.error(f"❌ Connection refused: IB Gateway not running at {self.host}:{self.port}")
            self.connected = False
            return False
        except socket.timeout:
            logger.error(f"❌ Connection timeout: Could not reach IB Gateway at {self.host}:{self.port}")
            self.connected = False
            return False
        except Exception as e:
            logger.error(f"❌ Connection error: {e}")
            self.connected = False
            return False
    
    def send_request(self, request: str) -> bool:
        """
        Send request to IB Gateway
        
        Args:
            request: Request string to send
            
        Returns:
            True if sent successfully, False otherwise
        """
        if not self.connected or not self.socket:
            logger.error("Not connected to IB Gateway")
            return False
        
        try:
            # IB API uses null-terminated strings
            if not request.endswith('\0'):
                request += '\0'
            
            self.socket.sendall(request.encode('utf-8'))
            logger.debug(f"Sent: {request.strip()}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error sending request: {e}")
            self.connected = False
            return False
    
    def receive_response(self, buffer_size: int = 4096, timeout: float = 2.0) -> Optional[str]:
        """
        Receive response from IB Gateway
        
        Args:
            buffer_size: Size of receive buffer
            timeout: Timeout in seconds
            
        Returns:
            Response string or None if error
        """
        if not self.connected or not self.socket:
            logger.error("Not connected to IB Gateway")
            return None
        
        try:
            self.socket.settimeout(timeout)
            data = self.socket.recv(buffer_size)
            
            if not data:
                logger.warning("No data received from IB Gateway")
                return None
            
            response = data.decode('utf-8')
            logger.debug(f"Received: {response[:100]}...")
            return response
            
        except socket.timeout:
            logger.debug("Receive timeout (expected if no data)")
            return None
        except Exception as e:
            logger.error(f"❌ Error receiving response: {e}")
            self.connected = False
            return None
    
    def test_connection(self) -> Dict[str, Any]:
        """
        Test IB Gateway connection with basic API calls
        
        Returns:
            Dictionary with test results
        """
        results = {
            "connected": False,
            "server_version": None,
            "client_id": self.client_id,
            "host": self.host,
            "port": self.port,
            "timestamp": time.time(),
            "tests": []
        }
        
        if not self.connect():
            results["error"] = "Failed to connect to IB Gateway"
            return results
        
        results["connected"] = True
        
        # Test 1: Send client version and request server version
        logger.info("\n📊 Test 1: Handshake - Send API version")
        try:
            # IB API protocol: Send API version
            handshake = "API\0"
            if self.send_request(handshake):
                logger.info("✅ Sent API handshake")
                results["tests"].append({
                    "name": "Handshake",
                    "status": "success",
                    "message": "API handshake sent"
                })
            else:
                results["tests"].append({
                    "name": "Handshake",
                    "status": "failed",
                    "message": "Failed to send API handshake"
                })
        except Exception as e:
            results["tests"].append({
                "name": "Handshake",
                "status": "failed",
                "message": str(e)
            })
        
        # Test 2: Request contract details for a test symbol (SPY)
        logger.info("\n📊 Test 2: Request Contract Details (SPY)")
        try:
            # IB API request format: reqContractDetails with contract ID 756603 (SPY)
            contract_request = "9|1|756603\0"  # reqContractDetails: Service, Version, ContractId
            if self.send_request(contract_request):
                logger.info("✅ Sent contract details request for SPY")
                response = self.receive_response()
                
                if response:
                    logger.info(f"✅ Received response: {response[:100]}")
                    results["tests"].append({
                        "name": "Contract Details Request",
                        "status": "success",
                        "message": f"Received response ({len(response)} bytes)"
                    })
                else:
                    logger.info("⚠️  No response yet (may still be processing)")
                    results["tests"].append({
                        "name": "Contract Details Request",
                        "status": "partial",
                        "message": "Request sent, no response yet"
                    })
            else:
                results["tests"].append({
                    "name": "Contract Details Request",
                    "status": "failed",
                    "message": "Failed to send contract request"
                })
        except Exception as e:
            results["tests"].append({
                "name": "Contract Details Request",
                "status": "failed",
                "message": str(e)
            })
        
        # Test 3: Request current time
        logger.info("\n📊 Test 3: Request Current Time")
        try:
            time_request = "49\0"  # reqCurrentTime service
            if self.send_request(time_request):
                logger.info("✅ Sent current time request")
                response = self.receive_response()
                
                if response:
                    logger.info(f"✅ Received time response: {response[:50]}")
                    results["tests"].append({
                        "name": "Current Time Request",
                        "status": "success",
                        "message": f"Received time response"
                    })
                else:
                    results["tests"].append({
                        "name": "Current Time Request",
                        "status": "partial",
                        "message": "Request sent, awaiting response"
                    })
            else:
                results["tests"].append({
                    "name": "Current Time Request",
                    "status": "failed",
                    "message": "Failed to send time request"
                })
        except Exception as e:
            results["tests"].append({
                "name": "Current Time Request",
                "status": "failed",
                "message": str(e)
            })
        
        # Test 4: Check connection status
        logger.info("\n📊 Test 4: Connection Status Check")
        try:
            if self.connected and self.socket:
                logger.info("✅ Connection is active")
                results["tests"].append({
                    "name": "Connection Status",
                    "status": "success",
                    "message": "Connection is active"
                })
            else:
                logger.error("❌ Connection lost")
                results["tests"].append({
                    "name": "Connection Status",
                    "status": "failed",
                    "message": "Connection lost"
                })
        except Exception as e:
            results["tests"].append({
                "name": "Connection Status",
                "status": "failed",
                "message": str(e)
            })
        
        return results
    
    def disconnect(self) -> bool:
        """
        Close connection to IB Gateway
        
        Returns:
            True if disconnected successfully
        """
        try:
            if self.socket:
                self.socket.close()
            self.connected = False
            logger.info("✅ Disconnected from IB Gateway")
            return True
        except Exception as e:
            logger.error(f"❌ Error disconnecting: {e}")
            return False
    
    def get_connection_info(self) -> Dict[str, Any]:
        """
        Get current connection information
        
        Returns:
            Dictionary with connection details
        """
        uptime = None
        if self.connected and self.connection_time:
            uptime = time.time() - self.connection_time
        
        return {
            "connected": self.connected,
            "host": self.host,
            "port": self.port,
            "client_id": self.client_id,
            "uptime_seconds": uptime,
            "connection_time": self.connection_time
        }


def test_ib_gateway() -> None:
    """
    Main test function for IB Gateway connection
    """
    logger.info("=" * 70)
    logger.info("Interactive Brokers TWS API Connection Test")
    logger.info("=" * 70)
    
    # Create connection object
    ib_connection = IBGatewayConnection(
        host="127.0.0.1",
        port=4001,  # Live trading port
        client_id=1
    )
    
    # Run tests
    test_results = ib_connection.test_connection()
    
    # Print results
    logger.info("\n" + "=" * 70)
    logger.info("TEST RESULTS")
    logger.info("=" * 70)
    
    logger.info(f"✅ Connected: {test_results['connected']}")
    logger.info(f"Host: {test_results['host']}:{test_results['port']}")
    logger.info(f"Client ID: {test_results['client_id']}")
    
    if 'error' in test_results:
        logger.error(f"❌ Error: {test_results['error']}")
    
    logger.info("\nIndividual Tests:")
    for i, test in enumerate(test_results.get('tests', []), 1):
        status_icon = "✅" if test['status'] == 'success' else "⚠️" if test['status'] == 'partial' else "❌"
        logger.info(f"  {i}. {status_icon} {test['name']}: {test['message']}")
    
    # Get connection info
    conn_info = ib_connection.get_connection_info()
    logger.info(f"\nConnection Info:")
    logger.info(f"  Status: {'Active' if conn_info['connected'] else 'Inactive'}")
    if conn_info['uptime_seconds']:
        logger.info(f"  Uptime: {conn_info['uptime_seconds']:.2f}s")
    
    # Disconnect
    ib_connection.disconnect()
    
    logger.info("\n" + "=" * 70)
    logger.info("Test Complete")
    logger.info("=" * 70)


def test_market_data_api() -> None:
    """
    Test function for Market Data API
    """
    logger.info("\n" + "=" * 70)
    logger.info("Market Data API Test")
    logger.info("=" * 70)
    
    market_data = MarketDataAPI()
    
    # Test 1: Get stock quote (may fail with demo key, that's ok)
    logger.info("\n📊 Test 1: Stock Quote (AAPL)")
    aapl_quote = market_data.get_stock_quote_alpha_vantage("AAPL", api_key="demo")
    if "error" not in aapl_quote and "price" in aapl_quote:
        logger.info(f"✅ AAPL Quote: ${aapl_quote['price']} | Change: {aapl_quote['change_percent']}")
        logger.info(f"   Volume: {aapl_quote['volume']} | Bid: ${aapl_quote['bid']} | Ask: ${aapl_quote['ask']}")
    else:
        logger.warning(f"⚠️  Demo API Key Limitation: {aapl_quote.get('error', 'No data returned')}")
        logger.info("   (Use your own Alpha Vantage API key for full access)")
    
    # Test 2: Get intraday data (may fail with demo key)
    logger.info("\n📊 Test 2: Intraday Data (MSFT, 5-min)")
    msft_intraday = market_data.get_intraday_data("MSFT", interval="5min", api_key="demo")
    if "error" not in msft_intraday and "candles" in msft_intraday:
        candles = msft_intraday['candles']
        logger.info(f"✅ Got {len(candles)} candles for MSFT")
        if candles:
            latest = candles[0]
            logger.info(f"   Latest: O:{latest['open']} H:{latest['high']} L:{latest['low']} C:{latest['close']} | Vol:{latest['volume']}")
    else:
        logger.warning(f"⚠️  Demo API Key Limitation: {msft_intraday.get('error', 'Unknown error')}")
        logger.info("   (Use your own Alpha Vantage API key for full access)")
    
    # Test 3: Get crypto price (no API key needed - this will work!)
    logger.info("\n📊 Test 3: Cryptocurrency Prices (CoinGecko) - FREE API")
    logger.info("   ✅ No API key required, working with CoinGecko...")
    
    for crypto in ["BTC", "ETH"]:
        crypto_price = market_data.get_crypto_price(crypto)
        if "error" not in crypto_price and "price_usd" in crypto_price:
            logger.info(f"✅ {crypto}: ${crypto_price['price_usd']:,.2f}")
            logger.info(f"   Market Cap: ${crypto_price['market_cap_usd']:,.0f} | 24h Vol: ${crypto_price['volume_24h_usd']:,.0f}")
        else:
            logger.warning(f"⚠️  {crypto} Error: {crypto_price.get('error', 'Unknown error')}")
    
    logger.info("\n" + "=" * 70)
    logger.info("Market Data Test Complete")
    logger.info("=" * 70)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "market":
        test_market_data_api()
    else:
        test_ib_gateway()
