# Quick Reference: Monitoring Multi-Trade Sequences

## Real-Time Monitoring Commands

### 1. Watch Bot Trade Events
```bash
tail -f logs/bot_runner.log | grep -E "BUILDING|LOCKED|✅ ENTRY|CLOSE|RESET"
```

Expected output:
```
[Symbol] Phase 1 BUILDING started at 10:15:30
[Symbol] Phase 2 LOCKED after 60 ticks: $100.00-$101.50
✅ ENTRY LONG @ $100.25 | PnL: +0.00%
CLOSE LONG @ $101.00 | PnL: +0.75%
[Symbol] Position closed @ $101.00. Range RESET to Phase 1 (BUILD) for next opportunity
```

### 2. Watch Dashboard Label Updates
```bash
tail -f logs/trading_dashboard.log | grep -E "update_open_label|update_close_label"
```

Expected output:
```
[update_open_label] Setting text to: Open: $100.25 for QQQ
✅ Updated Open label for QQQ to: Open: $100.25
[update_close_label] Setting text to: Close: $101.00 for QQQ
✅ Updated Close label for QQQ to: Close: $101.00
```

### 3. Watch Entry/Exit Summary
```bash
tail -f logs/bot_runner.log | grep -E "^✅ ENTRY|^CLOSE"
```

### 4. Count Trades per Symbol (Cumulative)
```bash
grep "✅ ENTRY\|^CLOSE" logs/bot_runner.log | grep -c "QQQ"  # Total QQQ entries + closes
```

### 5. Monitor Range Resets
```bash
tail -f logs/bot_runner.log | grep "RESET to Phase 1"
```

---

## Key Metrics to Watch

### Per-Symbol Performance
- **Trades**: Number of completed trade cycles
- **Winning Rate**: % of trades with positive PnL
- **Average PnL**: Mean profit/loss per trade
- **Consecutive Losses**: Triggers cooldown (PROFESSIONAL_RULES)

### Range Metrics
- **Range Size**: High - Low (wider = more volatility)
- **Build Time**: Should be exactly 60 ticks (since OPENING_RANGE_MINUTES=1)
- **Lock Duration**: Up to 15 minutes (unless position closes)

### Dashboard Verification
- **Open Label**: Shows current or last entry price
- **Close Label**: Shows last exit price
- **Price Label**: Shows current price
- **P/L Label**: Shows unrealized (open) or realized (closed) P&L

---

## Troubleshooting

### Issue: No trades triggering
**Check**:
```bash
tail -f logs/bot_runner.log | grep "Skip.*Entry"
```
Look for reasons why entries are being blocked (not in lower 30%, already in zone, etc.)

### Issue: Open label shows wrong value
**Check dashboard logs**:
```bash
grep "Entry Price:" logs/trading_dashboard.log | tail -5
```
Should show numeric values like `Entry Price: 100.25`

### Issue: Range not resetting after close
**Check bot logs**:
```bash
grep "RESET to Phase 1" logs/bot_runner.log
```
Should see message immediately after CLOSE event

### Issue: Multiple positions open simultaneously
**Check current positions**:
```bash
grep "current_positions\[" logs/bot_runner.log | tail -10
```
Should show one position per symbol at a time

---

## Test Sequence (with FAKE_TICKS)

1. Start system: `bash restart.sh`
2. Wait ~2 minutes for Range to BUILD and LOCK
3. Monitor for first trade
4. After first trade closes, watch for:
   - Range reset message
   - New range building
   - New entry signal
5. Verify Open/Close labels update correctly

---

## Configuration Tuning

### To allow more frequent re-entries:
```env
OPENING_RANGE_MINUTES=1           # Keep short (1 min = 60 ticks)
RANGE_ENTRY_ZONE_PCT=0.50         # Increase to 0.50 (upper 50% can enter)
```

### To be more selective with entries:
```env
OPENING_RANGE_MINUTES=5           # Longer build = more data
RANGE_ENTRY_ZONE_PCT=0.20         # Decrease to 0.20 (only very low prices)
```

### To add cooldown between trades:
Check `bot/rules.py` for PROFESSIONAL_RULES:
```python
"rule_4_4_cooldown_after_losses": {
    "cooldown_seconds": 300  # 5 minutes after 3+ losses
}
```

---

## Performance Baseline

With current configuration (OPENING_RANGE_MINUTES=1, RANGE_ENTRY_ZONE_PCT=0.30):

**Expected daily (8-hour session)**:
- 3-5 trades per symbol (5 symbols = 15-25 total trades)
- 60-70% win rate (depends on volatility)
- Average win: +0.50% to +1.50% per trade
- Average loss: -0.30% to -0.80% per trade

**This will vary** based on:
- Market volatility (historical data)
- Entry condition strictness
- Position sizing
- Stop loss settings

---

## Key Files to Monitor

| File | Purpose | Key Lines |
|------|---------|-----------|
| logs/bot_runner.log | Bot entry/exit events | Search: "✅ ENTRY", "CLOSE" |
| logs/trading_dashboard.log | UI label updates | Search: "update_open_label", "update_close_label" |
| logs/websocket_server.log | Event routing | Search: "TRADE_EVENT" |
| logs/historical_data_server.log | Tick streaming | Search: "Client connected" |

---

