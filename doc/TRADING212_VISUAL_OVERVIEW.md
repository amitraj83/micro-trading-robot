# Trading212 Integration - Visual Overview

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     MICRO-TRADING ROBOT                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Polygon API (Real-Time Price Data)                       │  │
│  │ AXSM, DJT, WULF, HUT every 30 seconds                    │  │
│  └────────────────────────┬─────────────────────────────────┘  │
│                           │                                     │
│                           ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ MicroTradingStrategy                                     │  │
│  │ Entry: Momentum patterns, Volume spike                  │  │
│  │ Exit: TP=1.0%, SL=0.5%, TIME=10s                       │  │
│  └────────────────────────┬─────────────────────────────────┘  │
│                           │                                     │
│              OPEN signal  │  CLOSE signal                       │
│                    │      │      │                              │
│                    ▼      ▼      ▼                              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Dashboard (websocket_ui)                                 │  │
│  │ - Displays chart & signals in real-time                 │  │
│  │ - Receives OPEN/CLOSE events from strategy              │  │
│  └────────────────────────┬─────────────────────────────────┘  │
│                           │                                     │
│                           ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Trading212Broker (ORDER MANAGER) ⭐ NEW                 │  │
│  │ - execute_open_trade(symbol, entry_price, quantity)     │  │
│  │ - execute_close_trade(symbol, exit_price, reason)       │  │
│  │ - Tracks BotPosition with P&L calculation               │  │
│  │ - syncs_positions() to verify account state             │  │
│  └────────────────────────┬─────────────────────────────────┘  │
│                           │                                     │
│                           ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Trading212Client (API CLIENT) ⭐ NEW                     │  │
│  │ - HTTP requests with X-API-KEY/SECRET auth              │  │
│  │ - create_buy_order(symbol, quantity)                    │  │
│  │ - create_sell_order(symbol, quantity)                   │  │
│  │ - close_position(symbol)                                │  │
│  │ - get_account_info(), get_positions()                   │  │
│  └────────────────────────┬─────────────────────────────────┘  │
│                           │                                     │
│                           ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Trading212 REST API                                      │  │
│  │ demo.trading212.com/api/v0 (LIVE=false)                 │  │
│  │ live.trading212.com/api/v0 (LIVE=true)                  │  │
│  └────────────────────────┬─────────────────────────────────┘  │
│                           │                                     │
│                           ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Trading212 Account                                       │  │
│  │ - BUY orders (strategy entry)                            │  │
│  │ - SELL orders (strategy exit)                            │  │
│  │ - Open positions tracked                                 │  │
│  │ - P&L calculated automatically                           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 🔄 Trade Execution Flow

### ENTRY (BUY) Signal Path
```
Strategy detects entry condition
        │
        ├─→ OPEN signal generated
        │
        ├─→ Dashboard receives signal
        │   symbol=AXSM, price=$157.50
        │
        ├─→ asyncio.create_task(
        │     trading212_broker.execute_open_trade(
        │       symbol='AXSM',
        │       entry_price=157.50,
        │       quantity=1.0
        │     )
        │   )
        │
        ├─→ Trading212Broker.execute_open_trade()
        │   • Create BotPosition object
        │   • Call trading212_client.create_buy_order()
        │
        ├─→ Trading212Client creates HTTP request
        │   POST /orders/
        │   {
        │     "ticker": "AXSM",
        │     "quantity": 1.0,
        │     "side": "BUY"
        │   }
        │
        ├─→ Trading212 API executes BUY
        │   Returns: order_abc123
        │
        ├─→ Broker stores position
        │   status: PENDING → OPEN
        │   trading212_order_id: order_abc123
        │
        ├─→ Log: 📈 Creating BUY order: AXSM x 1.0
        └─→ Log: ✅ BUY order created: order_abc123

Dashboard displays: Position OPEN for AXSM at $157.50
```

### EXIT (SELL) Signal Path
```
Strategy detects exit condition (TP/SL/TIME)
        │
        ├─→ CLOSE signal generated
        │   reason='TP' (take profit)
        │   exit_price=$159.50
        │
        ├─→ Dashboard receives signal
        │
        ├─→ asyncio.create_task(
        │     trading212_broker.execute_close_trade(
        │       symbol='AXSM',
        │       exit_price=159.50,
        │       exit_reason='TP'
        │     )
        │   )
        │
        ├─→ Trading212Broker.execute_close_trade()
        │   • Find open position for AXSM
        │   • Calculate P&L: (159.50 - 157.50) × 1.0 = $2.00
        │   • Call trading212_client.create_sell_order()
        │
        ├─→ Trading212Client creates HTTP request
        │   POST /orders/
        │   {
        │     "ticker": "AXSM",
        │     "quantity": 1.0,
        │     "side": "SELL"
        │   }
        │
        ├─→ Trading212 API executes SELL
        │   Returns: order_def456
        │
        ├─→ Broker updates position
        │   status: OPEN → CLOSED
        │   close_price: 159.50
        │   close_time: timestamp
        │   pnl: +$2.00 (+1.27%)
        │
        ├─→ Log: 🔒 Closing position: AXSM
        └─→ Log: ✅ Position CLOSED: P&L: +$2.00 (+1.27%)

Dashboard displays: Position CLOSED, ready for next trade
```

## 📊 File Structure

```
/Users/ara/micro-trading-robot/
├── bot/
│   ├── strategy.py                    (MicroTradingStrategy)
│   ├── config.py                      (Configuration: TP=1.0%, SL=0.5%)
│   ├── trading212_api.py              ⭐ NEW (270 lines)
│   └── trading212_broker.py           ⭐ NEW (320 lines)
│
├── websocket_ui/
│   └── multi_symbol_dashboard.py      ✏️ MODIFIED (signal handlers)
│
├── TRADING212_COMPLETE.md             ⭐ NEW (This overview)
├── TRADING212_QUICKSTART.md           ⭐ NEW (5-min setup)
├── TRADING212_README.md               ⭐ NEW (Complete reference)
├── TRADING212_IMPLEMENTATION.md       ⭐ NEW (Deployment guide)
├── TRADING212_ARCHITECTURE.md         ⭐ NEW (Technical details)
├── TRADING212_TESTING_CHECKLIST.md    ⭐ NEW (Testing guide)
│
├── doc/
│   └── TRADING212_INTEGRATION.md      ⭐ NEW (Extended docs)
│
├── test_trading212_integration.py     ⭐ NEW (Integration tests)
│
├── .env                               ✏️ MODIFIED (credentials)
├── restart.sh                         (Bot restart script)
├── logs/
│   └── websocket_server.log          (Order execution logs)
│
└── README.md                          (Original docs)
```

## 🎬 Example Trading Session Timeline

```
14:37:27.282  📊 Polygon API fetches prices
              AXSM=$157.50, DJT=$11.20, WULF=$10.50, HUT=$45.80
              
14:37:27.300  🔍 Strategy analyzes patterns
              Found momentum entry in AXSM
              
14:37:27.310  ⏬ OPEN signal generated
              symbol='AXSM', entry_price=$157.50
              
14:37:27.320  📈 Dashboard receives OPEN
              Creates asyncio.create_task() for execute_open_trade()
              
14:37:27.330  🔄 Broker creates BUY order
              POST /orders/ with AXSM, 1.0 shares, BUY side
              
14:37:27.350  ✅ Trading212 API returns order_123
              Position status: OPEN
              Entry logged with timestamp

--- POSITION OPEN FOR 3 SECONDS ---

14:37:28.400  📈 Prices update
              AXSM moved to $159.50 (+1.27%)
              P&L: +$2.00 (+1.27%)
              
14:37:30.500  🎯 Strategy detects TP target
              Entry price: $157.50
              Current price: $159.50 (TP reached)
              
14:37:30.510  ⏬ CLOSE signal generated
              symbol='AXSM', exit_price=$159.50, reason='TP'
              
14:37:30.520  🔄 Dashboard receives CLOSE
              Creates asyncio.create_task() for execute_close_trade()
              
14:37:30.530  🔒 Broker creates SELL order
              POST /orders/ with AXSM, 1.0 shares, SELL side
              Calculates P&L: (159.50 - 157.50) × 1.0 = $2.00
              
14:37:30.550  ✅ Trading212 API returns order_456
              Position status: CLOSED
              P&L: +$2.00 (+1.27%)
              Exit logged with timestamp

--- POSITION CLOSED, READY FOR NEXT ---

14:37:30.560  📊 Dashboard updates
              AXSM position removed
              Ready for next signal
              
14:37:31.000  Trade complete
              Duration: ~3.7 seconds
              Result: +$2.00 profit
              Log entries: 4 (entry, BUY confirmed, exit, CLOSED confirmed)
```

## 🔐 Credential & Environment Management

```
.env file structure:
├── Polygon API (data fetching)
│   ├── POLYGON_API_KEY=TEwsmbCFGd8dDANW3EY3...
│   ├── POLYGON_BASE_URL=https://api.massive.com
│   ├── POLYGON_SNAPSHOT_PATH=/v2/snapshot/...
│   ├── SYMBOLS=AXSM,DJT,WULF,HUT
│   └── FAKE_TICKS=false (real data)
│
├── Trading212 DEMO Credentials
│   ├── TRADING212_DEMO_API_KEY=39265827ZWxTXRWYysJmaaIuPrZiROcOfBAIH
│   ├── TRADING212_DEMO_API_SECRET=2-Anye9X4yIJj0MVAJnKTRL0g6zoiBj484WAxoPJpao
│   └── TRADING212_DEMO_ENVIRONMENT=https://demo.trading212.com/api/v0
│
├── Trading212 LIVE Credentials
│   ├── TRADING212_API_KEY=36238492ZLpXnCOliQcGMgLfKofQCqmPisddK
│   ├── TRADING212_API_SECRET=amHA7XXhWzNokzaLf9I3RhaxiGiASZSvT3GESqEc1mc
│   └── TRADING212_LIVE_ENVIRONMENT=https://live.trading212.com/api/v0
│
└── Environment Toggle
    ├── LIVE=false           (← Uses DEMO credentials)
    └── LIVE=true            (← Uses LIVE credentials with REAL MONEY)
```

## 📈 Data Flow with Objects

```
┌─────────────────────────────────────────┐
│ OPEN Signal from Strategy               │
│ ├─ symbol: 'AXSM'                       │
│ ├─ entry_price: 157.50                  │
│ └─ timestamp: 2025-12-31 14:37:27.310   │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ BotPosition Object Created              │
│ ├─ symbol: 'AXSM'                       │
│ ├─ entry_price: 157.50                  │
│ ├─ entry_time: 2025-12-31 14:37:27      │
│ ├─ quantity: 1.0                        │
│ ├─ direction: 'BUY'                     │
│ ├─ status: 'PENDING'                    │
│ └─ trading212_order_id: None            │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ HTTP POST /orders/                      │
│ ├─ ticker: 'AXSM'                       │
│ ├─ quantity: 1.0                        │
│ ├─ side: 'BUY'                          │
│ └─ headers: X-API-KEY, X-API-SECRET     │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ Trading212 API Response                 │
│ ├─ order_id: 'order_abc123'             │
│ ├─ status: 'PENDING'                    │
│ └─ created_at: 2025-12-31 14:37:27      │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ BotPosition Updated                     │
│ ├─ trading212_order_id: 'order_abc123'  │
│ ├─ status: 'OPEN'                       │
│ └─ logged: "✅ BUY order created"       │
└─────────────────────────────────────────┘
                    │
           (Position held for ~3 seconds)
                    │
                    ▼
┌─────────────────────────────────────────┐
│ CLOSE Signal from Strategy              │
│ ├─ symbol: 'AXSM'                       │
│ ├─ exit_price: 159.50                   │
│ ├─ reason: 'TP'                         │
│ └─ timestamp: 2025-12-31 14:37:30       │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ BotPosition Updated                     │
│ ├─ close_price: 159.50                  │
│ ├─ close_time: 2025-12-31 14:37:30      │
│ ├─ close_reason: 'TP'                   │
│ ├─ pnl: 2.00                            │
│ ├─ pnl_pct: 1.27                        │
│ └─ status: 'PENDING_CLOSE'              │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ HTTP POST /orders/                      │
│ ├─ ticker: 'AXSM'                       │
│ ├─ quantity: 1.0                        │
│ ├─ side: 'SELL'                         │
│ └─ headers: X-API-KEY, X-API-SECRET     │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ Trading212 API Response                 │
│ ├─ order_id: 'order_def456'             │
│ └─ status: 'PENDING'                    │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ BotPosition Final State                 │
│ ├─ status: 'CLOSED'                     │
│ ├─ pnl: 2.00 (entry profit)             │
│ ├─ pnl_pct: 1.27%                       │
│ └─ logged: "✅ Position CLOSED: +$2.00" │
└─────────────────────────────────────────┘
```

## 🧪 Testing Integration Points

```
Unit Level Testing:
  ├─ Trading212Client API methods
  │   ├─ create_buy_order() → returns order_id
  │   ├─ create_sell_order() → returns order_id
  │   ├─ get_positions() → returns list
  │   └─ get_account_info() → returns account data
  │
  └─ Trading212Broker methods
      ├─ execute_open_trade() → creates BotPosition
      ├─ execute_close_trade() → updates BotPosition
      ├─ get_position() → returns position or None
      └─ sync_positions() → verifies consistency

Integration Level Testing:
  ├─ Dashboard → Broker connection
  │   ├─ OPEN signal → execute_open_trade() call
  │   └─ CLOSE signal → execute_close_trade() call
  │
  ├─ Broker → Trading212Client connection
  │   ├─ HTTP requests sent correctly
  │   ├─ Authentication headers valid
  │   └─ Responses parsed correctly
  │
  └─ Trading212Client → Trading212 API connection
      ├─ Orders appear in dashboard
      ├─ Positions match account
      └─ P&L calculated accurately

End-to-End Testing:
  ├─ Strategy signal → Trading212 order
  ├─ P&L calculation matches actual
  ├─ Position sync accurate
  └─ Error recovery working
```

## 🎯 Key Metrics & Performance

```
Order Execution Latency:
  Signal generated: 0ms
  → Dashboard receives: +0-5ms
  → Broker creates order: +5-10ms
  → API request sent: +10-20ms
  → Trading212 response: +20-100ms (network dependent)
  → Position logged: +100-200ms
  Total: ~100-200ms per trade

Trade Lifecycle Duration:
  Entry signal → Open position: ~100-200ms
  Open position hold: 1-30 seconds (strategy dependent)
  Exit signal → Closed position: ~100-200ms
  Total trade time: 1-30 seconds

Position Tracking:
  BotPosition objects: In-memory dict
  Updates per trade: 4 (create, open, close signal, closed)
  Sync interval: Manual or on-demand
  Consistency: Verified with Trading212 account

Data Throughput:
  Price updates: 4 symbols × 1 per 30 seconds = ~0.13 Hz
  Strategy analysis: Real-time per price update
  Order requests: 2 per trade (BUY + SELL)
  Log entries: 4 per trade
```

## 📋 Setup Verification Checklist

```
✅ Credentials in .env
   ├─ TRADING212_DEMO_API_KEY
   ├─ TRADING212_DEMO_API_SECRET
   ├─ TRADING212_API_KEY
   ├─ TRADING212_API_SECRET
   └─ LIVE=false

✅ Files created
   ├─ bot/trading212_api.py (270 lines)
   ├─ bot/trading212_broker.py (320 lines)
   ├─ test_trading212_integration.py (100 lines)
   └─ Documentation (1500+ lines)

✅ Dashboard integrated
   ├─ Trading212Broker imported
   ├─ OPEN signal handler added
   ├─ CLOSE signal handler added
   └─ Non-blocking execution confirmed

✅ Tests passing
   ├─ test_api_client() ✓
   ├─ test_broker() ✓
   └─ No import errors

Ready to trade! 🚀
```

---

**Next Step:** `bash restart.sh && tail -f logs/websocket_server.log | grep -i "trading212"`
