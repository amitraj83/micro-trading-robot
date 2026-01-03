# Trading Dashboard Issues & Design Discussion

## Issues Identified

### 1. **Open/Close Labels Not Displaying Correctly**

**Problem**: 
- For QQQ: Open label showed a value, but it was the "invested amount" (notional value) not the entry price
- For other symbols: No value showing in Open/Close labels even though positions were opened

**Root Causes Identified**:

1. **Closure Variable Bug**: The `entry_price` variable was being used inside a closure that executed asynchronously via `root.after()`. If the variable was reused before the callback executed, it would show the wrong value.

   **Example**:
   ```python
   # WRONG (variable captured by reference)
   def update_label():
       label.config(text=f"Open: ${entry_price:.2f}")
   root.after(0, update_label)  # entry_price might change before callback runs
   
   # FIXED (variable passed as default parameter)
   def update_label(ep=entry_price):
       label.config(text=f"Open: ${ep:.2f}")
   root.after(0, update_label)
   ```

2. **Missing Foreground Color on Close Label**: The Close label wasn't configured with `foreground="red"`, so it might not be visible.

**Fix Applied**:
- ✅ Pass `entry_price` and `price` as default parameters to callbacks to avoid closure issues
- ✅ Added `foreground="red"` to Close label config
- ✅ Added symbol parameter to all callbacks for clarity

---

### 2. **Re-opening After Position Close (Design Question)**

**Current Behavior**:
When a position closes, the opening range is reset to Phase 1 (BUILD), allowing the bot to:
- Rebuild a new opening range
- Generate new entry signals
- Open another position on the same symbol

**Code Implementation**:
```python
# In strategy.py, close_position() method
if symbol in self.opening_range:
    self.opening_range[symbol]["position_locked"] = False
    # Range resets to Phase 1 (BUILD) on next tick
```

**Design Questions for Discussion**:

1. **Should one symbol trade MULTIPLE times per day, or only ONCE per "session"?**
   - Current: Multiple positions allowed (resets range after close)
   - Alternative: Lock symbol until next daily reset

2. **What triggers a new "session"?**
   - Opening Range expiration (current: 15 minutes of validity)
   - Daily market open/close
   - Manual reset

3. **Should there be a minimum time between closes and reopens?**
   - Current: Can reopen immediately
   - Alternative: Wait N minutes before allowing new entry

---

## Verification Steps

### To verify Open/Close labels now display correctly:

1. **Start the system**:
   ```bash
   cd /Users/ara/micro-trading-robot
   bash restart.sh
   ```

2. **Wait for tick 100** (≈2 minutes)
   - Bot will inject test OPEN event automatically

3. **Check Dashboard Logs**:
   ```bash
   tail -f logs/trading_dashboard.log | grep "update_open_label\|update_close_label"
   ```
   
   Expected output:
   ```
   [update_open_label] Setting text to: Open: $487.01 for QQQ
   ✅ Updated Open label for QQQ to: Open: $487.01
   ```

4. **Check Dashboard UI**:
   - Verify Open label shows "Open: $XXX.XX" with green text
   - Verify Close label shows "Close: --" initially
   - When position closes, verify Close shows "Close: $YYY.YY" with red text

---

## Code Changes Made

### File: `websocket_ui/multi_symbol_dashboard.py`

**Lines 780-795**: Fixed OPEN label update
```python
# BEFORE: Closure variable bug
def update_open_label():
    label.config(text=f"Open: ${entry_price:.2f}")
root.after(0, update_open_label)

# AFTER: Pass variables as default parameters
def update_open_label(ep=entry_price, sym=symbol):
    label.config(text=f"Open: ${ep:.2f}")
root.after(0, update_open_label)
```

**Lines 813-821**: Fixed CLOSE label update
```python
# BEFORE: Missing color, closure variable bug
def update_close_labels():
    label.config(text=f"Close: ${price:.2f}")
root.after(0, update_close_labels)

# AFTER: Pass variables, add color
def update_close_labels(exit_p=price, sym=symbol):
    label.config(text=f"Close: ${exit_p:.2f}", foreground="red")
root.after(0, update_close_labels)
```

---

## Recommendations

### Issue 1: Multi-Trade per Symbol (Design Decision Needed)

**Option A: Allow Multiple Trades (Current)**
- Pros: Maximize trading opportunities, leverage multiple breakouts in same symbol
- Cons: Could lead to high position overlap, inconsistent behavior
- Use case: Scalping/momentum trading

**Option B: One Trade per Opening Range Session**
- Pros: Clearer trading intent, prevents over-trading single symbol
- Cons: Might miss recovery opportunities after early exit
- Use case: Range-based breakout trading

**Option C: One Trade per Day with Reset at Market Close**
- Pros: Clean daily sessions, matches traditional trading
- Cons: Bot stops trading mid-day after one close
- Use case: Daily traders

**Recommendation**: Implement **Option B** (one trade per range session) to prevent conflicting signals and maintain trading clarity.

---

## Architecture Notes

### Event Flow

```
Bot (runner.py)
  → Detects entry signal (check_entry_signals)
  → Creates Trade object with entry_price
  → Broadcasts TRADE_EVENT via WebSocket to port 8765
  
WebSocket Server (server.py)
  → Receives TRADE_EVENT from bot
  → Forwards to all connected dashboard clients
  
Dashboard (multi_symbol_dashboard.py)
  → Receives TRADE_EVENT via WebSocket
  → Extracts entry_price from trade_data
  → Updates Open label via root.after() callback
```

### Thread Safety

- ✅ All UI updates use `root.after(0, callback)` for thread-safe Tkinter operations
- ✅ WebSocket runs in separate async thread
- ✅ Callback parameters passed as defaults to avoid closure issues

---

## Testing

### Test Case 1: Verify Open Label Displays Entry Price
```
1. Start system
2. Wait for tick 100 (test event injected)
3. Check: Dashboard shows "Open: $XXX.XX"
4. Check: Entry price ≈ current price ± small adjustment
```

### Test Case 2: Verify Close Label Displays Exit Price
```
1. Inject CLOSE event with exit_price=100.50
2. Check: Dashboard shows "Close: $100.50"
3. Check: Open label resets to "Open: --"
```

### Test Case 3: Multiple Trades on Same Symbol
```
1. Position opens on QQQ
2. Position closes
3. Check: Can bot open another position on QQQ?
   - Current: YES (range resets)
   - Desired: Depends on design choice above
```

---

## Questions for User

1. **Should a symbol trade ONCE or MULTIPLE times per session?**
   - If ONCE: Add `trades_in_range` counter to prevent reopens
   - If MULTIPLE: Current behavior is correct

2. **What constitutes a "new session"?**
   - Opening range expiration (current)
   - Daily reset at market close
   - Other criteria?

3. **For the invested amount appearing on QQQ**: 
   - Did it show `position_size` (quantity)? 
   - Did it show `notional` (entry_price × position_size)?
   - This would help debug what value was being sent vs. displayed

4. **Do other symbols now display correctly?**
   - Check the logs: `grep "update_open_label" logs/trading_dashboard.log`
   - Do all symbols show the entry_price in the callback logs?

---

