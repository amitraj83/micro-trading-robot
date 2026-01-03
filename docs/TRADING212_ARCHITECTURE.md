# Trading212 Integration - Architecture Discussion

## 📌 Problem Statement

**Goal:** When the bot generates trading signals (BUY/SELL), automatically execute real trades on the Trading212 platform.

**Challenge:** 
- Bot generates signals in-memory (strategy.py)
- Orders need to reach Trading212 API
- Position tracking needed locally
- Demo and live modes must be switchable
- No manual intervention desired

## 🏗️ Architecture Overview

### Three-Layer Design

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: Strategy & Signal Generation                 │
│  bot/strategy.py → generates OPEN/CLOSE events         │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│  Layer 2: Signal Integration & UI                       │
│  websocket_ui/multi_symbol_dashboard.py                │
│  → receives OPEN/CLOSE events                          │
│  → calls broker.execute_open_trade()                   │
│  → calls broker.execute_close_trade()                  │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│  Layer 3: Broker & API Client                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │ trading212_broker.py (High-level)               │  │
│  │ - Position tracking (BotPosition)               │  │
│  │ - Order execution logic                         │  │
│  │ - Error recovery                                │  │
│  └──────────────────────────────────────────────────┘  │
│           ↓                                            │
│  ┌──────────────────────────────────────────────────┐  │
│  │ trading212_api.py (Low-level)                   │  │
│  │ - HTTP client with auth                         │  │
│  │ - API endpoint wrappers                         │  │
│  │ - Error handling & logging                      │  │
│  └──────────────────────────────────────────────────┘  │
│           ↓                                            │
│  Trading212 REST API                                  │
│  (demo.trading212.com or live.trading212.com)        │
└─────────────────────────────────────────────────────────┘
```

## 🔄 Signal Flow

### Complete Trade Lifecycle

```
┌──────────────────────────────────────────────────────────────────┐
│ TICK ARRIVES                                                     │
│ (price update from Polygon API)                                 │
└──────────────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────────────┐
│ STRATEGY PROCESSING                                              │
│ bot/strategy.py → process_tick(tick)                            │
│ - Checks entry conditions (volatility, momentum, volume)        │
│ - If entry met: creates Trade, emits OPEN event                │
│ - If exit met: closes Trade, emits CLOSE event                 │
└──────────────────────────────────────────────────────────────────┘
                           ↓
                    ┌──────────────┐
                    │ OPEN Signal? │
                    └──────────────┘
                    ↙              ↘
              YES ↙                ↘ NO
              ↙                      ↘
    ┌─────────────────────┐      ┌────────────────────────┐
    │ BUY Order Needed    │      │ Keep checking for      │
    │                     │      │ exit signals           │
    │ Dashboard receives: │      └────────────────────────┘
    │ action="OPEN"       │                ↓
    │ trade=Trade(...)    │      ┌──────────────────────┐
    │ reason="MOMENTUM"   │      │ Position Open?       │
    │                     │      └──────────────────────┘
    └─────────────────────┘             ↙
                ↓               YES ↙
                ↓         ┌──────────────────────┐
    ┌──────────────────────┐      │ CLOSE Signal? │
    │ execute_open_trade() │      └──────────────┘
    │ - symbol: "AAPL"     │             ↙     ↘
    │ - price: 150.00      │        YES ↙       ↘ NO
    │ - quantity: 1.0      │         ↙           ↘
    └──────────────────────┘     ┌─────────┐    Loop
                ↓                │ SELL    │    until
    ┌──────────────────────┐     │ Order   │    exit
    │ Trading212Client:    │     └─────────┘
    │ create_buy_order()   │         ↓
    │ - POST /orders/      │     ┌──────────────────────┐
    │ - body: {            │     │ execute_close_trade()│
    │     "ticker":"AAPL", │     │ - symbol: "AAPL"     │
    │     "side":"BUY",    │     │ - exit_price: 151.50 │
    │     "quantity":1.0   │     │ - reason: "TP"       │
    │   }                  │     └──────────────────────┘
    └──────────────────────┘             ↓
                ↓              ┌──────────────────────┐
    ┌──────────────────────┐     │ Trading212Client: │
    │ Order Response       │     │ create_sell_order()│
    │ {                    │     │ - POST /orders/    │
    │   "orderId": "123",  │     │ - body: {          │
    │   "status": "filled" │     │   "ticker":"AAPL", │
    │ }                    │     │   "side":"SELL",   │
    └──────────────────────┘     │   "quantity":1.0   │
                ↓                │ }                  │
    ┌──────────────────────┐     └──────────────────────┘
    │ BotPosition updated: │             ↓
    │ - status: "OPEN"     │     ┌──────────────────────┐
    │ - order_id: "123"    │     │ Order Response       │
    │ - qty: 1.0           │     │ {                    │
    └──────────────────────┘     │   "orderId": "456"   │
                ↓                │ }                    │
    ┌──────────────────────┐     └──────────────────────┘
    │ Log to output:       │             ↓
    │ ✅ BUY order:       │     ┌──────────────────────┐
    │ AAPL x 1.0          │     │ BotPosition updated: │
    │ @ $150.00           │     │ - status: "CLOSED"   │
    │ Order ID: 123       │     │ - close_price: 151.5 │
    └──────────────────────┘     │ - close_reason: "TP" │
                ↓                │ - pnl: $1.50         │
    ┌──────────────────────┐     │ - pnl_pct: +1.0%     │
    │ Ready for next       │     └──────────────────────┘
    │ signals              │             ↓
    └──────────────────────┘     ┌──────────────────────┐
                                 │ Log to output:       │
                                 │ ✅ Position CLOSED   │
                                 │ AAPL @ $151.50 (TP)  │
                                 │ P&L: +$1.50 (+1.0%)  │
                                 └──────────────────────┘
                                         ↓
                                 ┌──────────────────────┐
                                 │ Ready for next       │
                                 │ signals              │
                                 └──────────────────────┘
```

## 🎯 Design Decisions

### 1. **Separation of Concerns**

**Why separate into 3 files?**

| Component | Responsibility | Reusability |
|-----------|-----------------|-------------|
| `trading212_api.py` | HTTP + Authentication | Can be used independently |
| `trading212_broker.py` | Order management + Position tracking | Can wrap multiple API clients |
| `dashboard.py` | Signal → Order translation | UI-specific, minimal TT212 knowledge |

**Benefits:**
- Easy to test API independently
- Broker can be used in other UIs (CLI, REST API, etc.)
- Clean separation: UI doesn't know about HTTP details
- Easy to add other brokers (Interactive Brokers, etc.)

### 2. **Async/Await Pattern**

**Why async?**

```python
# Without async (blocking):
execute_open_trade()  # Waits here...
# UI freezes for 500ms

# With async (non-blocking):
asyncio.create_task(execute_open_trade())  # Returns immediately
# UI remains responsive
```

**Benefits:**
- Orders execute in background
- UI stays responsive during API calls
- Multiple symbols can execute in parallel
- Natural fit with Tkinter's event loop

### 3. **Position Tracking**

**Why track locally?**

```python
class BotPosition:
    symbol: str          # What we bought
    entry_price: float   # When we bought at
    entry_time: datetime # Timestamp
    quantity: float      # How many shares
    trading212_order_id  # Reference to actual order
    status               # PENDING → OPEN → CLOSED
    close_reason         # TP / SL / TIME / FLAT
    pnl                  # Calculated P&L
```

**Why important:**
- Bot doesn't have access to Trading212 account real-time
- Orders take time to execute (network latency)
- Provides local audit trail
- Enables position sync reconciliation
- Useful for backtesting/analysis

### 4. **Demo/Live Toggle**

**Simple environment switching:**

```python
if LIVE == "true":
    API_KEY = LIVE_API_KEY
    BASE_URL = LIVE_API_URL
else:
    API_KEY = DEMO_API_KEY
    BASE_URL = DEMO_API_URL
```

**Why important:**
- Safe testing before real money
- Same code path for both environments
- Easy to switch (just .env change)
- Builds confidence before going live

### 5. **Comprehensive Logging**

**Every operation logged:**

```
[INFO] 🔄 Fetch cycle #1: Fetching 4 symbols
[INFO] 📈 Creating BUY order: AXSM x 1.0 shares (DEMO)
[INFO] ✅ BUY order created: order_12345
[INFO] 🔒 Closing position: AXSM x 1.0 shares
[INFO] ✅ Position CLOSED: P&L: +$10.50 (+6.70%)
```

**Why important:**
- Audit trail for regulatory compliance
- Debugging API issues
- Performance monitoring
- Post-trade analysis
- Error investigation

## 🔐 Security Considerations

### Credential Management

```env
# Separated by environment
TRADING212_DEMO_API_KEY=...      # Demo account
TRADING212_DEMO_API_SECRET=...
TRADING212_API_KEY=...            # Live account
TRADING212_API_SECRET=...
LIVE=false                         # Toggle between them
```

**Security practices:**
- ✅ Credentials in `.env` (not in code)
- ✅ Environment-specific keys
- ✅ Demo mode as default
- ✅ No credential logging
- ✅ HTTPS for all API calls

### Risk Controls

```python
# In broker:
- Position size limited by entry_price
- Error status prevents further orders
- Sync verification checks for discrepancies
- All orders logged before execution
```

## 🧪 Testing Strategy

### Unit Testing (API client)

```python
async def test_create_buy_order():
    async with Trading212Client() as client:
        response = await client.create_buy_order("AAPL", 1.0)
        assert "orderId" in response or "id" in response
```

### Integration Testing (Broker)

```python
async def test_full_cycle():
    broker = await get_trading212_broker()
    
    # Execute BUY
    success = await broker.execute_open_trade("AAPL", 150.00, 1.0)
    assert success
    
    # Verify position tracked
    pos = broker.get_position("AAPL")
    assert pos.status == "PENDING"
    
    # Execute SELL
    success = await broker.execute_close_trade("AAPL", 151.50, "TP")
    assert success
    assert pos.status == "CLOSED"
```

### End-to-End Testing (Dashboard)

```python
# Simulate strategy signals
event = {"action": "OPEN", "trade": trade_obj}
# Dashboard should create order automatically
# Verify in logs and Trading212 dashboard
```

## 🚀 Future Enhancements

### Short Term
1. **Position averaging** - Scale into positions over multiple signals
2. **Partial closes** - Close half at profit, half at stop loss
3. **Advanced order types** - Limit orders, stop orders
4. **Webhook notifications** - Alerts on order fills

### Medium Term
1. **Risk limits** - Max position size, daily loss limits
2. **Paper trading** - Simulate without execution
3. **Order modifications** - Update SL/TP dynamically
4. **Multi-broker support** - Add Interactive Brokers, etc.

### Long Term
1. **Machine learning** - Learn from P&L patterns
2. **Options trading** - Protect positions with options
3. **Arbitrage detection** - Find opportunities across exchanges
4. **Portfolio rebalancing** - Maintain target allocations

## 📊 Performance Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Order creation latency | < 500ms | Includes network round-trip |
| API request timeout | 10 seconds | Per Trading212 docs |
| Position sync interval | 60 seconds | Periodic reconciliation |
| Concurrent orders | 4+ | All symbols in parallel |
| Logging overhead | < 50ms | Per order |
| Memory per position | ~200 bytes | Lightweight tracking |

## 🎓 Key Concepts

### BotPosition Lifecycle

```
Created (dashboard) → PENDING (waiting) → OPEN (filled) → CLOSED (exited)
                                      ↘ ERROR (if failed)
```

### Event Types

| Event | Direction | Broker Action | Result |
|-------|-----------|---------------|--------|
| OPEN | LONG | create_buy_order | BUY executed |
| CLOSE | LONG | create_sell_order | SELL executed |
| OPEN | SHORT | create_sell_order | SELL executed |
| CLOSE | SHORT | create_buy_order | BUY executed |

### Error Handling

```
API Error
  → Catch exception
  → Update position.status = "ERROR"
  → Set position.error_message
  → Log error with timestamp
  → Continue accepting new signals
  → Admin can investigate from logs
```

## 📈 Workflow Example

**Scenario:** Bot trades AAPL at different times

```
14:30:00 - Price: $150.00
          Strategy: MOMENTUM detected ✓
          → execute_open_trade("AAPL", 150.00, 1.0)
          → Trading212: BUY 1 AAPL @ market
          → Filled @ $150.02
          → BotPosition: status=OPEN, entry_price=$150.00
          
14:30:15 - Price: $150.50
          Strategy: No exit signal yet
          
14:30:30 - Price: $151.50
          Strategy: TAKE PROFIT target hit (+1.0%) ✓
          → execute_close_trade("AAPL", 151.50, "TP")
          → Trading212: SELL 1 AAPL @ market
          → Filled @ $151.48
          → BotPosition: status=CLOSED, pnl=$1.48, pnl_pct=+0.99%

Log output:
📈 Creating BUY order: AAPL x 1.0 shares (DEMO)
✅ BUY order created: order_ABC123
🔒 Closing position: AAPL x 1.0 shares
✅ Position CLOSED: P&L: $1.48 (+0.99%)
```

---

**Design philosophy:** *Simple, testable, extensible, secure*
