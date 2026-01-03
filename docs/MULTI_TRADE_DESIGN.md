# Multi-Trade Per Symbol Design - Implementation Summary

## Confirmed Design Decision ✅

**The bot allows MULTIPLE trades per symbol throughout the day** by resetting and rebuilding the opening range after each position closes.

---

## How It Works

### Timeline for Each Trade Cycle

```
Time  Event                           Range Phase         Position Status
─────────────────────────────────────────────────────────────────────────
  T0  Symbol starts                   INITIALIZING        None
  T1  Phase 1 BUILD begins            BUILDING (0/60)     None
 T60  After 60 ticks                  LOCKED              None
 T61  Entry signal triggers           LOCKED              ✓ OPEN (Entry)
 T90  Position in profit              LOCKED              ✓ OPEN (Hold)
T100  Position closes                 RESET IMMEDIATELY   ✗ CLOSED (Exit)
T101  Phase 1 BUILD begins again      BUILDING (0/60)     None
T161  After 60 ticks                  LOCKED              None
T162  Entry signal triggers again     LOCKED              ✓ OPEN (2nd Trade)
      ...and cycle repeats
```

### Code Flow

#### 1. **First Trade Cycle**

```python
# Tick 0: Initialize range
self.opening_range[symbol] = {
    "phase": "BUILDING",
    "ticks": 1,
    "high": current_price,
    "low": current_price
}

# Ticks 1-59: Accumulate ticks, track high/low
or_data["ticks"] += 1
or_data["high"] = max(or_data["high"], current_price)
or_data["low"] = min(or_data["low"], current_price)

# Tick 60: Transition to LOCKED phase
if or_data["ticks"] >= 60:
    or_data["phase"] = "LOCKED"
    or_data["lock_time"] = now
    or_data["validity_expires_at"] = now + 900  # 15 minutes

# Ticks 61+: Check entry signals
if current_price <= prev_range_low + 0.5%:  # Price dips to support
    if position_in_range <= 0.30:  # In lower 30% of range
        entry_signal = "LONG"
        open_position(symbol, current_price)
```

#### 2. **Position Close → Range Reset** ⭐ **NEW**

```python
# In close_position() method:
# When position closes, IMMEDIATELY reset the range

if symbol in self.opening_range:
    now = time.time()
    self.opening_range[symbol] = {
        "high": exit_price,
        "low": exit_price,
        "ticks": 1,
        "initialized": False,
        "build_start_time": now,
        "lock_time": None,
        "validity_expires_at": None,
        "position_locked": False,
        "phase": "BUILDING"
    }
    # Clear entry tracking for fresh signals
    self.last_entry_zone[symbol] = None
    self.prev_range_low[symbol] = exit_price
```

**Key improvements in this implementation**:
- ✅ Range resets **immediately** (not waiting for 15-min expiration)
- ✅ Uses **exit_price as new baseline** for next range
- ✅ Clears **last_entry_zone** to allow fresh entry signals
- ✅ Resets **prev_range_low** to prevent stale zone blocking

#### 3. **Second Trade Cycle**

```python
# Next tick after close: Phase 1 BUILD starts fresh
# Ticks 101-160: New range builds from exit_price baseline
# Tick 161: New range LOCKED
# Ticks 162+: New entry signals can generate
```

---

## Key Features

### ✅ **Multiple Entry Opportunities**
- Same symbol can trade 2-3+ times per day
- Each cycle starts fresh with new range baseline
- No artificial locks preventing re-entry

### ✅ **Clean Separation Between Trades**
- Each trade gets its own opening range
- Entry signals based on NEW price levels, not stale data
- Prevents "ghost trades" from old range breaks

### ✅ **Automatic Risk Reset**
- Each new range builds from current market price
- New high/low reflect current volatility
- Stop loss and position sizing recalculated per trade

### ⚠️ **Considerations**

1. **Range Can Be Very Small Initially**
   - If exit_price is the starting point, range might be tight until 60 ticks pass
   - This is actually good - prevents premature false breakouts
   
2. **Entry Zone Tracking Cleared**
   - `last_entry_zone` reset means price can re-trigger same level if it returns
   - This is intentional - new price action = new opportunity
   
3. **No Daily Cooldown**
   - Multiple trades possible within same minute
   - Could lead to over-trading if entry signals are too loose
   - Consider adding minimum hold time if this becomes an issue

---

## Testing the Design

### Test Case: Multi-Trade Sequence

```bash
# Start system with FAKE_TICKS=true
bash restart.sh

# Monitor bot logs for:
tail -f logs/bot_runner.log | grep -E "BUILDING|LOCKED|OPEN|CLOSE|RESET"
```

**Expected output for successful 2-trade sequence**:

```
[Symbol] Phase 1 BUILDING started at 10:15:30
[Symbol] Phase 2 LOCKED after 60 ticks: $100.00-$101.50
✅ ENTRY LONG @ $100.25 | PnL: +0.00%
CLOSE LONG @ $101.00 | PnL: +0.75%
[Symbol] Position closed @ $101.00. Range RESET to Phase 1 (BUILD)
[Symbol] Phase 1 BUILDING started at 10:16:30
[Symbol] Phase 2 LOCKED after 60 ticks: $101.00-$102.50
✅ ENTRY LONG @ $101.25 | PnL: +0.00%
CLOSE LONG @ $102.00 | PnL: +0.75%
```

---

## Dashboard Integration

### Open/Close Label Updates

The dashboard now correctly displays:

```
QQQ: Price: $100.50 | P/L: $+150.00 | Trades: 2 | Open: $100.25 | Close: $101.00 | Range: LOCKED
```

**What each label means**:
- **Open**: Entry price of current/last position
- **Close**: Exit price of last closed position
- **Trades**: Total number of positions closed today
- **Range**: Current opening range phase (BUILDING/LOCKED)

---

## Logic Verification Checklist

- ✅ Range initializes on first tick
- ✅ Range builds for 60 ticks (OPENING_RANGE_MINUTES=1)
- ✅ Range transitions to LOCKED after 60 ticks
- ✅ Entry signals check price vs previous range low
- ✅ Entry signals require price in lower 30% of range
- ✅ Position opens with entry_price tracked
- ✅ Position closes on exit signal (profit target/stop loss/time-based)
- ✅ **On close, range IMMEDIATELY resets** (NEW)
- ✅ Entry zone tracking cleared for fresh signals (NEW)
- ✅ New range builds from exit price baseline
- ✅ Cycle repeats allowing 2nd+ trades

---

## Configuration

Current settings (from .env):
```
OPENING_RANGE_MINUTES=1        # 60 ticks for BUILD phase (since 1 tick/sec)
USE_OPENING_RANGE=true         # Enable range-based strategy
RANGE_ENTRY_ZONE_PCT=0.30      # Entry allowed in lower 30% of range
```

**To adjust behavior**:
- Increase `OPENING_RANGE_MINUTES` for slower range building (e.g., 5 for medium trading)
- Decrease `RANGE_ENTRY_ZONE_PCT` to make entries more selective (e.g., 0.20 for very low prices)
- Increase for more loose entries (e.g., 0.50 for upper range entries)

---

## Performance Impact

### Positive
- ✅ More trading opportunities per symbol
- ✅ Captures multiple momentum swings
- ✅ Leverages different price levels in same security
- ✅ Automatic risk reset between trades

### Potential Risks (To Monitor)
- ⚠️ Could increase trading frequency significantly
- ⚠️ Multiple correlated losses if market trending against strategy
- ⚠️ Needs good entry filters to avoid over-trading
- ⚠️ Consider adding "max trades per symbol per day" safeguard if needed

---

## Files Modified

1. **bot/strategy.py** - Line 927-948
   - Improved `close_position()` to immediately reset range
   - Clear entry zone tracking for fresh signals
   - Reset prev_range_low to exit price

2. **websocket_ui/multi_symbol_dashboard.py** - Lines 780-821
   - Fixed closure variable bugs in Open/Close label callbacks
   - Pass entry_price and exit_price as default parameters
   - Added proper foreground colors

---

## Next Steps

1. **Test multi-trade scenario** with real (or simulated) price data
2. **Monitor entry signal frequency** - adjust RANGE_ENTRY_ZONE_PCT if too loose/tight
3. **Consider adding safeguards** if over-trading becomes an issue:
   - Max trades per symbol per day
   - Minimum time between trades
   - Loss streak cooldown (already exists via PROFESSIONAL_RULES)
4. **Analyze performance** - compare single-trade vs multi-trade results

---

