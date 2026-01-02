# Trading212 Integration - Quick Start Guide

## 🚀 5-Minute Setup

### Step 1: Verify Credentials (Already in .env)
```bash
cd /Users/ara/micro-trading-robot
grep "TRADING212" .env | head -5
```

You should see:
```
TRADING212_DEMO_API_KEY=39265827ZWxTXRWYysJmaaIuPrZiROcOfBAIH
TRADING212_DEMO_API_SECRET=2-Anye9X4yIJj0MVAJnKTRL0g6zoiBj484WAxoPJpao
LIVE=false
```

### Step 2: Start in Demo Mode
```bash
# Ensure LIVE=false in .env
grep "^LIVE" .env

# Restart bot
bash restart.sh
```

### Step 3: Monitor Trading212 Orders
```bash
# Watch for Trading212 operations
tail -f logs/websocket_server.log | grep -i "trading212\|📈\|✅"
```

You should see:
```
📈 Creating BUY order: AXSM x 1.0 shares (DEMO)
✅ BUY order created: order_12345
🔒 Closing position: AXSM x 1.0 shares
✅ Position CLOSED: P&L: +$10.50
```

### Step 4: Verify on Trading212 Dashboard
- Log in to https://demo.trading212.com
- Check "Orders" tab
- You should see your bot's BUY/SELL orders appearing in real-time

### Step 5: Test with Demo Data
```bash
# Check dashboard logs
tail -f logs/trading_dashboard.log | grep "Trading212\|OPEN\|CLOSE"
```

## ✅ Testing Checklist

- [ ] Credentials verified in .env
- [ ] LIVE=false confirmed
- [ ] Bot restarted with bash restart.sh
- [ ] Logs show Trading212 API calls
- [ ] Demo account showing new orders
- [ ] BUY orders appearing after bot entry
- [ ] SELL orders appearing after bot exit
- [ ] P&L calculations visible in logs
- [ ] Position tracking working

## 🧪 Run Integration Tests

```bash
# Full test suite
python3 test_trading212_integration.py

# Expected output:
# ✅ Account fetched
# ✅ Fetched N positions
# ✅ BUY order created: order_...
# ✅ Position CLOSED
```

## 🚨 Troubleshooting

### "Credentials missing"
```bash
# Fix: Add credentials to .env
TRADING212_DEMO_API_KEY=your_key_here
TRADING212_DEMO_API_SECRET=your_secret_here
```

### "No orders appearing"
```bash
# Check if broker is enabled
grep "Trading212Broker" logs/websocket_server.log

# Check API responses
grep "❌\|error" logs/websocket_server.log

# Verify LIVE=false
grep LIVE .env
```

### "Position mismatch"
```bash
# Check sync results
grep "discrepancies\|sync" logs/websocket_server.log

# Verify on Trading212 dashboard
# Check that positions match bot tracking
```

## 📊 What's Being Automated

When bot generates signals, these happen automatically:

| Event | Action | Result |
|-------|--------|--------|
| Entry signal (LONG) | BUY order created | Shares purchased |
| Exit signal (TP) | SELL order created | Position closed with profit |
| Exit signal (SL) | SELL order created | Position closed with loss |
| Exit signal (TIME) | SELL order created | Position closed on timeout |

## 🔄 Example Trading Session

```
14:30 - Bot detects momentum in AAPL
        → BUY order created automatically
        → Log: ✅ BUY order created: order_123
        → Trading212: Shows order in dashboard

14:30:15 - Price moves up
           → P&L improves
           
14:30:30 - Bot detects take-profit target
           → SELL order created automatically
           → Log: ✅ Position CLOSED: P&L: +$10.50 (+1.0%)
           → Trading212: Shows filled SELL order

14:31 - Position fully closed
        → Ready for next entry
```

## 📈 Switching to Live

**When you're confident with demo results:**

```bash
# 1. Update .env
sed -i 's/LIVE=false/LIVE=true/' .env

# 2. Restart bot
bash restart.sh

# 3. Monitor closely
tail -f logs/websocket_server.log | grep "Trading212"

# 4. Verify account balance
# (Check actual Trading212 live account)
```

⚠️ **Warning:** Once LIVE=true, orders use REAL MONEY. Start small.

## 🆘 Quick Help

| Problem | Solution |
|---------|----------|
| Orders not executing | Verify account has balance, check API logs |
| P&L looks wrong | Check position entry/exit prices in logs |
| Can't find orders | Check Trading212 dashboard → Orders tab |
| Sync showing errors | Run sync_positions() to reconcile |
| API timeout | Check internet connection, Trading212 status |

## 📞 Getting More Help

1. **Check logs:**
   ```bash
   grep -A5 "error\|Error\|ERROR" logs/websocket_server.log
   ```

2. **View architecture:**
   ```bash
   cat TRADING212_ARCHITECTURE.md
   ```

3. **Full documentation:**
   ```bash
   cat doc/TRADING212_INTEGRATION.md
   ```

4. **Test everything:**
   ```bash
   python3 test_trading212_integration.py
   ```

## 💡 Pro Tips

1. **Start small** - Use quantity=0.1 initially
2. **Monitor logs** - Always watch logs during testing
3. **Use demo first** - Never go straight to live
4. **Check balance** - Ensure account has funds
5. **Log analysis** - Save logs for post-trade analysis
6. **Sync regularly** - Verify position tracking accuracy

## 🎯 Success Criteria

Your integration is working when:

✅ Bot generates entry signal
✅ BUY order appears on Trading212 within 1 second  
✅ Order fills immediately (demo environment)
✅ Position tracked locally with correct price
✅ Bot generates exit signal
✅ SELL order appears on Trading212 within 1 second
✅ P&L calculated and logged
✅ Position shows as CLOSED in logs

## 📊 Example Success Log

```
2025-12-31 14:37:27,282 [INFO] 🔄 Fetch cycle #1
2025-12-31 14:37:27,300 [INFO] 📈 Creating BUY order: AXSM x 1.0 shares (DEMO)
2025-12-31 14:37:27,350 [INFO] ✅ BUY order created: order_abc123
2025-12-31 14:37:28,400 [INFO] 🔒 Closing position: AXSM x 1.0 shares (DEMO)
2025-12-31 14:37:28,450 [INFO] ✅ Position CLOSED for AXSM: P&L: $10.50 (+6.70%)
```

---

**Ready?** Start with: `bash restart.sh` then `tail -f logs/websocket_server.log | grep Trading212`
