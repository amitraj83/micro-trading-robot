# Trading212 Integration - Complete Reference

## 📋 Overview

Your micro-trading robot now automatically executes trades on Trading212 when the strategy generates buy/sell signals. This document serves as your complete reference.

## 🎯 What's New

Three new modules handle automated trading:

1. **`bot/trading212_api.py`** - Low-level REST API client (270 lines)
2. **`bot/trading212_broker.py`** - Order manager & position tracker (320 lines)  
3. **`websocket_ui/multi_symbol_dashboard.py`** - Modified to execute orders (615 lines)

Plus comprehensive documentation:
- `TRADING212_QUICKSTART.md` - 5-minute setup guide ⭐ **START HERE**
- `TRADING212_IMPLEMENTATION.md` - Deployment & configuration
- `TRADING212_ARCHITECTURE.md` - Technical deep-dive
- `test_trading212_integration.py` - Integration tests

## 🚀 Quick Start (2 minutes)

```bash
# 1. Verify credentials (already in .env)
grep "LIVE=" .env

# 2. Ensure demo mode (LIVE=false)
cat .env | grep "^LIVE"

# 3. Restart bot
bash restart.sh

# 4. Watch for Trading212 orders
tail -f logs/websocket_server.log | grep "Trading212\|📈\|✅"
```

That's it! When bot signals appear, orders execute automatically.

## 📊 How It Works

```
Strategy generates signal
    ↓
Dashboard receives OPEN or CLOSE event
    ↓
Calls Trading212Broker.execute_open_trade() or execute_close_trade()
    ↓
Broker creates HTTP request (BUY or SELL)
    ↓
Trading212 API executes order
    ↓
Broker tracks position locally with P&L
    ↓
Logs appear: "✅ BUY order created" or "✅ Position CLOSED: P&L: +$10.50"
```

## 🔧 Configuration

All configuration is in `.env`:

```bash
# API Credentials (DEMO)
TRADING212_DEMO_API_KEY=39265827ZWxTXRWYysJmaaIuPrZiROcOfBAIH
TRADING212_DEMO_API_SECRET=2-Anye9X4yIJj0MVAJnKTRL0g6zoiBj484WAxoPJpao

# API Credentials (LIVE)
TRADING212_API_KEY=36238492ZLpXnCOliQcGMgLfKofQCqmPisddK
TRADING212_API_SECRET=amHA7XXhWzNokzaLf9I3RhaxiGiASZSvT3GESqEc1mc

# Environment Toggle
LIVE=false          # ← Change to 'true' for REAL MONEY trading

# Account Setting
TRADING212_ACCOUNT_CURRENCY=EUR  # Use EUR for Trading212 accounts
```

## ✅ What's Automated

| Signal | Action | API Call | Result |
|--------|--------|----------|--------|
| **OPEN** (entry) | Create BUY order | `POST /orders/` | Buys shares |
| **CLOSE** (TP) | Create SELL order | `POST /orders/` | Sells at profit |
| **CLOSE** (SL) | Create SELL order | `POST /orders/` | Sells at loss |
| **CLOSE** (TIME) | Create SELL order | `POST /orders/` | Sells on timeout |

## 📝 Log Output Examples

When bot executes a trade, you'll see:

```
2025-12-31 14:37:27,282 [INFO] 📈 Creating BUY order: AXSM x 1.0 shares (DEMO)
2025-12-31 14:37:27,350 [INFO] ✅ BUY order created: order_abc123
2025-12-31 14:37:28,400 [INFO] 🔒 Closing position: AXSM (exit_price=$159.50, reason=TP)
2025-12-31 14:37:28,450 [INFO] ✅ Position CLOSED: P&L: +$10.50 (+6.67%)
```

## 🧪 Test Everything

```bash
# Run integration tests
python3 test_trading212_integration.py

# Expected output:
# ✅ Account info fetched
# ✅ Positions retrieved
# ✅ BUY order created
# ✅ Position closed with P&L
```

## 📊 Position Tracking

Each trade is tracked with:

```python
BotPosition(
    symbol='AXSM',
    entry_price=157.50,
    entry_time='2025-12-31 14:37:27',
    quantity=1.0,
    direction='BUY',
    trading212_order_id='order_abc123',
    status='CLOSED',  # PENDING → OPEN → CLOSED
    close_price=159.50,
    close_time='2025-12-31 14:37:28',
    close_reason='TP',  # TP | SL | TIME | ERROR
    error_message=None
)
```

P&L calculated as: `(exit_price - entry_price) × quantity`

## 🔄 Demo vs Live Mode

### Demo Mode (LIVE=false)
```
Environment: demo.trading212.com/api/v0
Credentials: TRADING212_DEMO_API_KEY/SECRET
Account: Training account (fake money)
Risk: ZERO - Perfect for testing
```

### Live Mode (LIVE=true)
```
Environment: live.trading212.com/api/v0
Credentials: TRADING212_API_KEY/SECRET
Account: Real money account
Risk: REAL - Only after confident with demo results
```

**⚠️ IMPORTANT:** Always test thoroughly in demo (LIVE=false) before switching to live.

## 🚨 Troubleshooting

### Orders not appearing

```bash
# Check logs for errors
grep "❌\|error" logs/websocket_server.log

# Verify credentials are correct
grep "TRADING212" .env | head -3

# Check API response
grep "Failed\|Error" logs/websocket_server.log | tail -20
```

### P&L looks wrong

```bash
# Verify entry/exit prices in logs
grep "BUY order\|Position CLOSED" logs/websocket_server.log

# Check position tracking
python3 -c "from bot.trading212_broker import trading212_broker; \
print('Open positions:', trading212_broker.get_open_positions())"
```

### Position mismatch

```bash
# Sync with Trading212 account
python3 -c "import asyncio; from bot.trading212_broker import get_trading212_broker; \
asyncio.run(get_trading212_broker().sync_positions())"
```

### API timeout

```bash
# Check internet and Trading212 status
curl -s https://api.trading212.com/api/v0/account/info \
  -H "Authorization: Bearer YOUR_TOKEN" | jq .

# Or wait a moment and restart
bash restart.sh
```

## 🆘 Getting Help

### Check Current Status
```bash
# Show last 20 Trading212 operations
grep "Trading212\|📈\|✅\|❌" logs/websocket_server.log | tail -20

# Show all errors
grep "error\|Error\|ERROR" logs/websocket_server.log | tail -10

# Show P&L summary
grep "P&L" logs/websocket_server.log
```

### Read Documentation
- **Quick setup:** `TRADING212_QUICKSTART.md`
- **Detailed guide:** `TRADING212_IMPLEMENTATION.md`
- **Architecture:** `TRADING212_ARCHITECTURE.md`

### Run Tests
```bash
python3 test_trading212_integration.py -v
```

## 📈 API Reference

### Trading212Broker Methods

```python
from bot.trading212_broker import get_trading212_broker

broker = await get_trading212_broker()
await broker.init_client()

# Create BUY order
success = await broker.execute_open_trade('AAPL', 150.25, 1.0)

# Create SELL order
success = await broker.execute_close_trade('AAPL', 152.50, 'TP')

# Get position
position = broker.get_position('AAPL')

# Get all open positions
open = broker.get_open_positions()

# Sync with Trading212
await broker.sync_positions()
```

### Trading212Client Methods (Low-level)

```python
from bot.trading212_api import Trading212Client

client = Trading212Client(demo_mode=True)

# Get account info
account = await client.get_account_info()

# Get positions
positions = await client.get_positions()

# Get orders
orders = await client.get_orders()

# Create order
order = await client.create_buy_order('AAPL', 1.0)

# Close position
result = await client.close_position('AAPL', 1.0)
```

## 💡 Pro Tips

1. **Start small** - Use quantity 0.1 or 1.0 initially
2. **Watch logs** - Always monitor logs during trading: `tail -f logs/websocket_server.log`
3. **Test demo first** - LIVE=false always before going to LIVE=true
4. **Check balance** - Ensure account has funds before trading
5. **Save logs** - Keep logs for post-trade analysis and debugging
6. **Verify orders** - Check Trading212 dashboard to confirm orders executed
7. **Monitor P&L** - Watch P&L calculations in logs

## 🎯 Next Steps

1. ✅ Verify credentials in `.env` - Already done!
2. ✅ Run `bash restart.sh` - Restart with new integration
3. ⏳ Watch for next signal - Monitor logs in real-time
4. ⏳ Verify order on Trading212 - Check dashboard
5. ⏳ Monitor 5-10 trades - Ensure everything works
6. ⏳ Switch to LIVE (optional) - After full confidence

## 📊 Sample Trading Session

```
14:30:00 - Bot detects AXSM momentum
         → 📈 Creating BUY order: AXSM x 1.0 shares
         → ✅ BUY order created: order_123

14:30:15 - Price rises 1.2%
         → P&L: +$1.89

14:30:30 - TP target hit (1.0%)
         → 🔒 Closing position: AXSM
         → ✅ Position CLOSED: P&L: +$10.50 (+6.67%)
         → 📊 Trade completed in 30 seconds

14:31:00 - Ready for next signal
         → Position fully closed
         → Cash available for next trade
```

## 🔐 Security Notes

- **API Keys:** Stored in `.env` (git-ignored for safety)
- **Async Execution:** Orders execute non-blocking (UI stays responsive)
- **Position Tracking:** Local cache matches Trading212 account
- **Demo by Default:** LIVE=false prevents accidental real money trades
- **Error Logging:** All failures logged for investigation

## 📞 Support Resources

| Resource | File |
|----------|------|
| Quick Start (5 min) | `TRADING212_QUICKSTART.md` |
| Implementation Guide | `TRADING212_IMPLEMENTATION.md` |
| Architecture Details | `TRADING212_ARCHITECTURE.md` |
| Integration Tests | `test_trading212_integration.py` |
| API Client | `bot/trading212_api.py` |
| Order Manager | `bot/trading212_broker.py` |

## ✨ Summary

Your bot is now **fully integrated with Trading212**:

✅ Automatic BUY orders on strategy entry  
✅ Automatic SELL orders on strategy exit  
✅ Real-time position tracking with P&L  
✅ Demo mode for safe testing (LIVE=false)  
✅ Live mode ready when you're confident (LIVE=true)  
✅ Comprehensive logging and error handling  
✅ Non-blocking async execution  

**Ready to trade?** Start with: `bash restart.sh && tail -f logs/websocket_server.log`

---

*Last updated: 2025-12-31 | Integration complete and tested*
