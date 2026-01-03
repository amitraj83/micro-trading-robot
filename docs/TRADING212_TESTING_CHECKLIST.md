# Trading212 Integration - Testing & Deployment Checklist

## ✅ Pre-Deployment (Already Complete)

- [x] API credentials added to `.env`
  - [x] TRADING212_DEMO_API_KEY set
  - [x] TRADING212_DEMO_API_SECRET set
  - [x] TRADING212_API_KEY set (for live)
  - [x] TRADING212_API_SECRET set (for live)
  
- [x] Code modules created
  - [x] `bot/trading212_api.py` (270 lines) - REST API client
  - [x] `bot/trading212_broker.py` (320 lines) - Order manager
  - [x] `websocket_ui/multi_symbol_dashboard.py` modified - Signal handlers integrated
  
- [x] Documentation created
  - [x] `TRADING212_QUICKSTART.md` - 5-minute setup
  - [x] `TRADING212_IMPLEMENTATION.md` - Deployment guide
  - [x] `TRADING212_ARCHITECTURE.md` - Technical details
  - [x] `TRADING212_README.md` - Complete reference
  - [x] `test_trading212_integration.py` - Integration tests
  
- [x] Python syntax validated
  - [x] All files parse correctly
  - [x] No import errors
  - [x] No type errors

## 🧪 Phase 1: Initial Testing (You Are Here)

### Step 1: Verify Environment
- [ ] Check `.env` file has LIVE=false
  ```bash
  grep "^LIVE" .env
  # Should show: LIVE=false
  ```

- [ ] Verify credentials exist
  ```bash
  grep "TRADING212_DEMO_API" .env
  # Should show both KEY and SECRET
  ```

- [ ] Verify bot directory has new files
  ```bash
  ls -la bot/trading212*.py
  # Should show 2 files
  ```

### Step 2: Run Integration Tests
- [ ] Execute test script
  ```bash
  python3 test_trading212_integration.py
  # Should show: ✅ for all tests
  ```
  
- [ ] Verify test output shows:
  - [ ] ✅ Account info retrieved
  - [ ] ✅ Positions fetched (may be empty)
  - [ ] ✅ BUY order created
  - [ ] ✅ Position closed
  - [ ] ✅ No API errors

### Step 3: Start Bot in Demo Mode
- [ ] Restart bot with new integration
  ```bash
  bash restart.sh
  # Should show bot starting
  ```

- [ ] Verify bot is running
  ```bash
  ps aux | grep "python.*websocket"
  # Should show process running
  ```

- [ ] Check logs for startup message
  ```bash
  grep "websocket_server started" logs/websocket_server.log
  # Should show recent timestamp
  ```

### Step 4: Monitor for First Signal
- [ ] Watch logs in real-time
  ```bash
  tail -f logs/websocket_server.log | grep -i "trading212\|📈\|✅"
  ```

- [ ] Observe for one of:
  - [ ] 📈 Creating BUY order
  - [ ] 🔒 Closing position
  - [ ] ✅ Order created
  - [ ] ✅ Position closed

### Step 5: Verify on Trading212 Dashboard
- [ ] Log in to https://demo.trading212.com
- [ ] Go to "Orders" tab
- [ ] Look for recent orders from your bot
  - [ ] BUY orders appear ~1 second after bot entry signal
  - [ ] SELL orders appear ~1 second after bot exit signal

- [ ] Check "Positions" tab
  - [ ] Open positions show correct symbol
  - [ ] Entry price matches bot logs
  - [ ] Quantity matches bot trades

## 📊 Phase 2: Full Trade Cycle Testing

### Trade #1: Complete BUY → SELL Cycle
- [ ] Observe next OPEN signal in logs
- [ ] Note: entry price, time, symbol
- [ ] Check Trading212 dashboard - BUY order appears
- [ ] Monitor position in real-time
- [ ] Observe CLOSE signal in logs
- [ ] Note: exit price, time, reason (TP/SL/TIME)
- [ ] Check Trading212 dashboard - SELL order appears
- [ ] Verify P&L calculation in logs
- [ ] Compare P&L with Trading212 dashboard

### Trade #2: Repeat cycle
- [ ] Complete another full trade cycle
- [ ] Verify consistency with Trade #1
- [ ] Check order timing (should be <1 second)
- [ ] Verify P&L calculations

### Trade #3: Repeat cycle
- [ ] Complete third full trade cycle
- [ ] Log all details for analysis

## 🔍 Phase 3: Validation Checks

### API Connectivity
- [ ] All API calls successful (no 4xx errors)
  ```bash
  grep "❌" logs/websocket_server.log
  # Should be empty or minimal
  ```

- [ ] Authentication working (no 401/403)
  ```bash
  grep "401\|403\|Unauthorized" logs/websocket_server.log
  # Should be empty
  ```

- [ ] Timeouts rare or non-existent
  ```bash
  grep "timeout\|Timeout" logs/websocket_server.log
  # Should be empty
  ```

### Position Tracking
- [ ] All opened positions tracked
  ```bash
  grep "BUY order created" logs/websocket_server.log | wc -l
  grep "Position CLOSED" logs/websocket_server.log | wc -l
  # Counts should match (or CLOSED ≥ BUY)
  ```

- [ ] P&L calculations correct
  ```bash
  grep "P&L:" logs/websocket_server.log | tail -5
  # All should show positive or negative values with %
  ```

- [ ] Order IDs tracked
  ```bash
  grep "order_" logs/websocket_server.log | head -5
  # Should show order IDs from Trading212
  ```

### Data Consistency
- [ ] Polygon API fetching (real prices)
  ```bash
  grep "Fetching" logs/websocket_server.log | tail -3
  # Should show recent API calls
  ```

- [ ] Strategy signals generating
  ```bash
  grep "OPEN\|CLOSE" logs/websocket_server.log | tail -10
  # Should show continuous signals
  ```

- [ ] Dashboard receiving signals
  ```bash
  grep "signal\|Signal" logs/trading_dashboard.log | tail -5
  # Should show signal reception
  ```

## 🎯 Phase 4: Error Scenarios (Optional Advanced Testing)

### Insufficient Balance
- [ ] (Demo has unlimited balance, skip for now)

### Invalid Symbol
- [ ] Monitor bot behavior with bad symbol
- [ ] Verify error logged correctly
- [ ] Check position status = 'ERROR'

### Network Interruption
- [ ] Temporarily disable internet
- [ ] Observe timeout handling
- [ ] Verify bot recovers when restored

### API Rate Limit
- [ ] Unlikely in demo, but check logs
- [ ] Verify exponential backoff handling

## 🚀 Phase 5: Going Live (When Confident)

### Pre-Live Checklist
- [ ] ✅ All 3 demo phases passed
- [ ] ✅ No API errors in logs
- [ ] ✅ Position tracking accurate
- [ ] ✅ Orders consistently executing
- [ ] ✅ P&L calculations verified
- [ ] ✅ 5+ successful trade cycles completed

### Switching to Live
- [ ] Review live credentials in .env
  ```bash
  grep "^TRADING212_API_KEY\|^TRADING212_API_SECRET" .env
  # Should match your live account
  ```

- [ ] Update LIVE flag
  ```bash
  sed -i 's/LIVE=false/LIVE=true/' .env
  ```

- [ ] Verify change
  ```bash
  grep "^LIVE" .env
  # Should show: LIVE=true
  ```

- [ ] Restart bot
  ```bash
  bash restart.sh
  ```

- [ ] Monitor logs closely
  ```bash
  tail -f logs/websocket_server.log | grep -i "trading212\|error\|p&l"
  ```

- [ ] Watch Trading212 live account for orders

### Post-Live Validation
- [ ] ✅ First trade completes successfully
- [ ] ✅ P&L shows on live account
- [ ] ✅ Position tracking matches live account
- [ ] ✅ No unexpected errors
- [ ] ✅ Order execution timing normal

## 📋 Ongoing Monitoring

### Daily Checks
- [ ] Review logs for errors
  ```bash
  grep "ERROR\|error\|❌" logs/websocket_server.log
  ```

- [ ] Check P&L summary
  ```bash
  grep "P&L:" logs/websocket_server.log | tail -20
  ```

- [ ] Verify API is fetching (real data)
  ```bash
  grep "Fetching" logs/websocket_server.log | tail -1
  ```

### Weekly Analysis
- [ ] [ ] Export P&L data for analysis
- [ ] [ ] Review position entry/exit prices
- [ ] [ ] Check for API timeout patterns
- [ ] [ ] Verify no memory leaks
- [ ] [ ] Confirm account balances match

### Monthly Review
- [ ] [ ] Archive old logs
- [ ] [ ] Review strategy performance
- [ ] [ ] Check credentials still valid
- [ ] [ ] Plan any optimizations

## 🆘 Troubleshooting During Testing

### No Orders Appearing
```bash
# Check if signals are being generated
grep "OPEN\|CLOSE" logs/websocket_server.log | head -5

# Check if broker is initialized
grep "Trading212Broker\|initialized" logs/websocket_server.log

# Check for API errors
grep "❌\|error\|Error" logs/websocket_server.log | tail -10
```

### Orders Appear but No P&L
```bash
# Check closing signal logic
grep "Closing position\|Position CLOSED" logs/websocket_server.log

# Verify exit prices captured
grep "exit_price\|close_price" logs/websocket_server.log
```

### P&L Looks Wrong
```bash
# Verify entry/exit prices
grep "entry_price\|exit_price" logs/websocket_server.log | tail -5

# Check P&L formula: (exit - entry) * quantity
python3 -c "print((159.50 - 157.50) * 1.0)"  # Example
```

### Connection Timeouts
```bash
# Check network
ping -c 1 api.trading212.com

# Check Trading212 status page
# (Visit: status.trading212.com)

# Restart bot if needed
bash restart.sh
```

## 📊 Success Criteria

### Phase 1 Success
✅ Tests pass without errors  
✅ Bot restarts cleanly  
✅ Logs show no critical errors  
✅ At least one trade completes  

### Phase 2 Success
✅ 3+ complete trade cycles  
✅ All orders appear on Trading212  
✅ P&L calculates correctly  
✅ Consistent order timing (<1s)  

### Phase 3 Success
✅ No API errors in logs  
✅ Position tracking accurate  
✅ All trades closed properly  
✅ Ready for live trading  

### Phase 4 Success
✅ Error scenarios handled gracefully  
✅ Bot recovers from failures  
✅ Logs informative and detailed  

### Overall Success
✅ Bot autonomously executes trades on Trading212  
✅ Positions tracked and P&L calculated  
✅ Demo mode fully tested and validated  
✅ Live mode ready to activate  

## 🎓 Quick Reference

### Essential Commands
```bash
# Restart bot with new integration
bash restart.sh

# Watch trading events
tail -f logs/websocket_server.log | grep -i "trading212\|📈\|✅"

# Run tests
python3 test_trading212_integration.py

# Check environment
grep "LIVE\|TRADING212" .env

# Switch to live (dangerous!)
sed -i 's/LIVE=false/LIVE=true/' .env
```

### Key Files
- Configuration: `.env`
- API Client: `bot/trading212_api.py`
- Order Manager: `bot/trading212_broker.py`
- Tests: `test_trading212_integration.py`
- Logs: `logs/websocket_server.log`
- Dashboard: `websocket_ui/multi_symbol_dashboard.py`

### Log Filtering
```bash
# Trading212 operations
grep "Trading212\|📈" logs/websocket_server.log

# All successful actions
grep "✅" logs/websocket_server.log

# All errors
grep "❌\|error\|Error" logs/websocket_server.log

# P&L summary
grep "P&L:" logs/websocket_server.log
```

## ✨ You're All Set!

Your Trading212 integration is complete and ready for testing. Follow the phases above in order and you'll have full automated trading in no time.

**Start with:** `bash restart.sh` then `tail -f logs/websocket_server.log | grep -i "trading212"`

Good luck! 🚀
