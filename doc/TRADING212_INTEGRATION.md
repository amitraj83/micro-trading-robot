# Trading212 Integration Documentation

## Overview

The bot now integrates with **Trading212** to automatically execute trades when the bot's strategy generates BUY and SELL signals. This allows real-time trading on the Trading212 platform without manual intervention.

## Architecture

### Components

1. **`bot/trading212_api.py`** - Low-level API client
   - Handles HTTP authentication and requests
   - Implements all Trading212 API endpoints
   - Manages session and error handling
   - Logs all API interactions

2. **`bot/trading212_broker.py`** - Order management and position tracking
   - Tracks bot-generated positions
   - Maps bot trades to Trading212 orders
   - Manages order lifecycle (pending → open → closed)
   - Syncs positions with Trading212 account
   - Handles errors and discrepancies

3. **`websocket_ui/multi_symbol_dashboard.py`** - Event integration
   - Initializes broker on WebSocket connection
   - Calls broker on "OPEN" signals (create BUY order)
   - Calls broker on "CLOSE" signals (create SELL order to close position)
   - Integrates async order execution with Tkinter UI

## Configuration

Add to `.env` file:

```env
# Trading212 API Credentials (DEMO)
TRADING212_DEMO_API_KEY=39265827ZWxTXRWYysJmaaIuPrZiROcOfBAIH
TRADING212_DEMO_API_SECRET=2-Anye9X4yIJj0MVAJnKTRL0g6zoiBj484WAxoPJpao
TRADING212_DEMO_ENVIRONMENT=https://demo.trading212.com/api/v0

# Trading212 API Credentials (LIVE)
TRADING212_API_KEY=36238492ZLpXnCOliQcGMgLfKofQCqmPisddK
TRADING212_API_SECRET=amHA7XXhWzNokzaLf9I3RhaxiGiASZSvT3GESqEc1mc
TRADING212_LIVE_ENVIRONMENT=https://live.trading212.com/api/v0

# Account settings
TRADING212_ACCOUNT_CURRENCY=EUR

# Switch between demo and live (false = demo, true = live)
LIVE=false
```

## Trading Flow

### 1. BUY Signal (Bot Entry)
```
Bot Strategy (OPEN signal)
    ↓
Dashboard receives "OPEN" action
    ↓
Broker.execute_open_trade(symbol, price, quantity)
    ↓
Trading212 Client creates BUY order
    ↓
Position tracked locally: BotPosition(status="PENDING")
    ↓
Order executed on Trading212 platform
```

### 2. SELL Signal (Bot Exit)
```
Bot Strategy (CLOSE signal with exit_reason: TP/SL/TIME/FLAT)
    ↓
Dashboard receives "CLOSE" action
    ↓
Broker.execute_close_trade(symbol, exit_price, exit_reason)
    ↓
Trading212 Client creates SELL order (closes position)
    ↓
Position updated: BotPosition(status="CLOSED", close_reason=exit_reason)
    ↓
Order executed on Trading212 platform
```

## API Reference

### Trading212Client

```python
# Authenticate and create client
async with Trading212Client() as client:
    # Get account info
    account = await client.get_account_info()
    
    # Get open positions
    positions = await client.get_positions()
    
    # Get pending orders
    orders = await client.get_orders()
    
    # Create BUY order
    order = await client.create_buy_order("AAPL", quantity=1.0)
    
    # Create SELL order
    order = await client.create_sell_order("AAPL", quantity=1.0)
    
    # Close position
    order = await client.close_position("AAPL")
    
    # Cancel order
    result = await client.cancel_order(order_id)
```

### Trading212Broker

```python
# Get or create broker
broker = await get_trading212_broker()
await broker.init_client()

# Execute BUY trade
success = await broker.execute_open_trade(
    symbol="AAPL",
    entry_price=150.00,
    quantity=1.0
)

# Execute SELL to close
success = await broker.execute_close_trade(
    symbol="AAPL",
    exit_price=151.50,
    exit_reason="TP"  # or "SL", "TIME", "FLAT"
)

# Get position
position = broker.get_position("AAPL")

# Get all open positions
open_positions = broker.get_open_positions()

# Sync with Trading212
sync_status = await broker.sync_positions()
```

### BotPosition (Data Class)

Tracks each bot-generated position:

```python
@dataclass
class BotPosition:
    symbol: str
    entry_price: float
    entry_time: datetime
    quantity: float
    direction: str = "LONG"
    trading212_order_id: Optional[str] = None
    status: str = "PENDING"  # PENDING, OPEN, CLOSED, ERROR
    error_message: Optional[str] = None
    close_price: Optional[float] = None
    close_time: Optional[datetime] = None
    close_reason: Optional[str] = None
```

## Demo vs Live Mode

### Demo Mode (LIVE=false)
- Uses demo credentials from `.env`
- Connects to `https://demo.trading212.com/api/v0`
- No real money risked
- Trades are on demo account
- Orders execute immediately in demo environment

### Live Mode (LIVE=true)
- Uses live credentials from `.env`
- Connects to `https://live.trading212.com/api/v0`
- **REAL MONEY** - all orders execute with actual funds
- Orders execute on live account

## Logging

All Trading212 operations are logged to:
- **Console**: Real-time INFO level logs
- **File**: `logs/websocket_server.log` (with timestamps)

Log format:
```
2025-12-31 14:37:27,282 [INFO] 📈 Creating BUY order: AAPL x 1.0 shares (DEMO)
2025-12-31 14:37:27,290 [INFO] ✅ BUY order created: order_12345
2025-12-31 14:37:28,300 [INFO] 🔒 Closing position: AAPL x 1.0 shares (DEMO)
2025-12-31 14:37:28,350 [INFO] ✅ Position CLOSED for AAPL: 1.0 shares @ $151.50 (TP) | P&L: $1.50 (+1.00%)
```

## Error Handling

### Common Errors

**"No position found for SYMBOL to close"**
- Bot tried to close a position that wasn't opened
- Possible cause: Market closed, order didn't execute yet

**API 401 Unauthorized**
- Credentials are invalid or expired
- Check `TRADING212_API_KEY` and `TRADING212_API_SECRET` in `.env`

**Quantity mismatch discrepancy**
- Position sync found different quantities on bot vs Trading212
- Possible cause: Manual trading on Trading212, position updated elsewhere

### Error Recovery

1. **Automatic retries**: Each API call has built-in timeout handling
2. **Position tracking**: All trades recorded locally in `BotPosition`
3. **Manual sync**: Call `broker.sync_positions()` to reconcile

## Testing

Run the integration test:

```bash
python3 test_trading212_integration.py
```

This will:
1. Test API authentication
2. Fetch account info, positions, and orders
3. Create a test BUY order
4. Sync positions
5. Create a test SELL order

## Workflow

### Step-by-Step Setup

1. **Configure credentials** in `.env`:
   ```env
   TRADING212_DEMO_API_KEY=...
   TRADING212_DEMO_API_SECRET=...
   LIVE=false  # Start with demo
   ```

2. **Restart the bot**:
   ```bash
   bash restart.sh
   ```

3. **Monitor logs** for Trading212 order execution:
   ```bash
   tail -f logs/websocket_server.log | grep "Trading212"
   ```

4. **Verify on Trading212 dashboard**:
   - Orders should appear in real-time
   - Positions should match broker tracking

5. **When confident, switch to LIVE**:
   - Update `.env`: `LIVE=true`
   - Restart bot
   - Monitor closely during first trades

## Safety Considerations

⚠️ **Before going LIVE:**

1. **Test thoroughly in DEMO mode** - create at least 5 complete trade cycles
2. **Verify position tracking** - check that bot positions match Trading212
3. **Check order timing** - ensure orders execute within expected time
4. **Monitor slippage** - verify actual execution prices vs bot signals
5. **Start with small quantities** - use `quantity: 0.1` or similar

🛑 **Risk Management:**

- Set `ALLOW_SELL_POSITIONS=false` to prevent SHORT sales
- Cap position size to acceptable risk per trade
- Always have daily loss limits enabled in strategy
- Monitor account balance regularly
- Have manual kill switch ready

## Integration Points

### In `multi_symbol_dashboard.py`

**Initialization** (line ~550):
```python
async def websocket_loop(self):
    # Initialize Trading212 broker
    self.trading212_broker = await get_trading212_broker()
    await self.trading212_broker.init_client()
```

**On OPEN signal** (line ~470):
```python
if self.trading212_broker:
    asyncio.create_task(self.trading212_broker.execute_open_trade(
        symbol=symbol,
        entry_price=price,
        quantity=1.0
    ))
```

**On CLOSE signal** (line ~490):
```python
if self.trading212_broker:
    asyncio.create_task(self.trading212_broker.execute_close_trade(
        symbol=symbol,
        exit_price=trade.exit_price,
        exit_reason=trade.exit_reason
    ))
```

## Performance

- **Order creation latency**: < 500ms
- **API request timeout**: 10 seconds
- **Position sync interval**: 60 seconds
- **Concurrent orders**: All symbols execute in parallel (asyncio)

## Future Enhancements

1. **Order modifications**: Update stop loss / take profit dynamically
2. **Partial closes**: Close position at specific price levels
3. **Advanced order types**: Limit orders, stop orders, trailing stops
4. **Webhook notifications**: Get alerts on order fills
5. **Position averaging**: Scale into positions over multiple signals
6. **Risk limits**: Enforce max position size, max daily loss
7. **Paper trading**: Simulate trades without execution

## Support & Troubleshooting

### Check Integration Status

```bash
# Verify credentials in .env
grep TRADING212 .env

# Check logs for Trading212 errors
grep -i "trading212" logs/websocket_server.log

# Test API connectivity
python3 test_trading212_integration.py
```

### Common Issues

| Issue | Solution |
|-------|----------|
| "Credentials missing" | Check `.env` file has all Trading212 keys |
| Orders not executing | Check Trading212 account has sufficient balance |
| Position mismatch | Run `broker.sync_positions()` and check logs |
| Timeout errors | Check internet connection, Trading212 API status |

---

**Last Updated**: 2025-12-31
**Version**: 1.0
**Status**: Production Ready (Demo), Testing (Live)
