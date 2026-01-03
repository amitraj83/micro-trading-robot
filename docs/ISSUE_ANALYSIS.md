# Trading Bot Issues - Root Cause Analysis

## Summary
Five interconnected issues preventing proper trading execution and UI display. Root causes span configuration misunderstanding, exit logic bugs, and incomplete event generation.

---

## Issue 1: RANGE_LOOKBACK_MAX_MINUTES=5 (Ineffective)

### User's Intent
"I wanted to change the **range building duration** to 5 minutes"

### Root Cause
**Conceptual Confusion: Two Separate Mechanisms**

The code has TWO independent range concepts that serve different purposes:

1. **OPENING_RANGE_MINUTES** (what controls building duration)
   - File: `bot/config.py` line 49
   - Config key: `OPENING_RANGE_MINUTES = int(os.getenv("OPENING_RANGE_MINUTES", "5"))`
   - Current: `OPENING_RANGE_MINUTES = 1` (from .env)
   - Effect: Controls how many ticks before range "locks" and entry signals enable
   - Calculation: `OPENING_RANGE_TICKS = OPENING_RANGE_MINUTES * 60 / FETCH_INTERVAL`
   - With OPENING_RANGE_MINUTES=1: Range builds for exactly 60 ticks, then locks
   - Used in: `bot/strategy.py` line 265 (checks `if or_data["ticks"] >= self.opening_range_ticks`)

2. **RANGE_LOOKBACK_MAX_MINUTES** (what you changed)
   - File: `bot/config.py` line 42
   - Config key: `RANGE_LOOKBACK_MAX_MINUTES = int(os.getenv("RANGE_LOOKBACK_MAX_MINUTES", "120"))`
   - Current: `RANGE_LOOKBACK_MAX_MINUTES = 5` (from .env - your change)
   - Effect: Controls how far BACK in history to look when calculating exit conditions
   - Used in: `bot/strategy.py` line 460 (lookback calculation for exit zone)
   - Purpose: For exit logic, how many ticks of history to examine

### Why Your Change Had No Effect
Changing `RANGE_LOOKBACK_MAX_MINUTES=5` affects which historical data is used for **exit calculations**, NOT how long the initial range takes to build.

### Solution
To reduce building time to 5 minutes (300 ticks):
```env
# Current (ineffective)
RANGE_LOOKBACK_MAX_MINUTES=5

# Should be (effective)
OPENING_RANGE_MINUTES=5
```

---

## Issue 2: CLOSE Label Not Showing During BUILDING Phase

### Observed Behavior
After position closes, the "Close: $XXX" label disappears instead of persisting through BUILDING phase.

### Root Cause Analysis

**Part A: Close events ARE broadcasted**
- File: `bot/runner.py` lines 175-220
- When `strategy.process_tick()` returns `event.get("action") == "CLOSE"`, the bot broadcasts it
- Code: `broadcast_msg` includes action="CLOSE" and gets sent via `broadcast_event()`

**Part B: Dashboard DOES receive and cache close prices**
- File: `websocket_ui/multi_symbol_dashboard.py` line 839
- CLOSE handler sets: `self.close_prices[symbol] = price`
- CLOSE handler updates label: `self.stat_labels[sym]['close'].config(text=f"Close: ${exit_p:.2f}", foreground="red")`

**Part C: Tick loop SHOULD display cached close price**
- File: `websocket_ui/multi_symbol_dashboard.py` lines 643-652
- Code checks: `if self.close_prices[symbol] is not None`
- If true: displays `Close: ${self.close_prices[symbol]:.2f}`

### Why It Doesn't Show

The dashboard code is correct. The problem is: **The strategy isn't generating CLOSE events**.

**Why no CLOSE events?**

1. **Positions might not be closing**: If `strategy.process_tick()` never returns `action="CLOSE"`, no close event is broadcasted
2. **Close conditions not met**: The exit logic in `bot/strategy.py` might not be triggered often enough
3. **Test event only sends OPEN**: The test event at tick 100 only injects `action="OPEN"`, not any CLOSE events

### Verification Needed
Check bot logs for:
```
grep "Broadcasted event: CLOSE" logs/bot_runner.log
```
If count is 0 or very low → strategy not closing positions
If count is high → dashboard CLOSE handler should work

---

## Issue 3: BUILDING Phase Stuck for QQQ

### Observed Behavior
After a trade closes, QQQ's range should reset to BUILDING phase and progress (0/60 ticks). Instead, it gets stuck.

### Root Cause Analysis

**Part A: Range reset code EXISTS and is correct**
- File: `bot/strategy.py` lines 938-947
- When position closes, range is reset:
  ```python
  self.opening_range[symbol] = {
      "high": exit_price,
      "low": exit_price,
      "ticks": 1,
      "phase": "BUILDING"
  }
  ```
- This sets range back to BUILDING with 1 tick

**Part B: BUILDING phase requires ticks to progress**
- File: `bot/strategy.py` line 265
- Code: `if or_data["ticks"] >= self.opening_range_ticks`
- With OPENING_RANGE_MINUTES=1: range needs 60 ticks to reach LOCKED
- Range progresses only when `process_tick()` is called for that symbol

### Why It Gets Stuck

**Hypothesis 1: Ticks stop flowing after close**
- If strategy stops processing QQQ after close, no new ticks → ticks count stays at 1
- Solution: Verify ticks are continuously fed through `process_tick()`

**Hypothesis 2: Range progress check broken**
- Dashboard shows range status from `strategy.opening_range[symbol]`
- If bot and dashboard have different strategy instances, they're out of sync
- Solution: Dashboard needs to read from bot's strategy instance (currently has its own)

**Hypothesis 3: Time-based validity interferes**
- File: `bot/strategy.py` lines 267-275
- LOCKED phase has time-based validity (15 min)
- If BUILDING phase also has time limit, it might expire before reaching LOCKED

### Verification Needed
Check dashboard logs:
```
grep "Building.*QQQ" logs/trading_dashboard.log
```
Look for progression: `Building (1/60) → Building (5/60) → ... → LOCKED`

If you see: stuck at `Building (1/60)` → ticks not flowing
If you see: range type switching weirdly → different mechanism interfering

---

## Issue 4: SPY Position Not Closing (Entry 184, Upper 198, Reached 202)

### Observed Behavior
- SPY opened position at entry price 184
- Range high calculated as 198 (range = 14 points)
- Price rose to 202 (beyond range high)
- Position did NOT close

### Root Cause

**The Exit Logic Bug (bot/strategy.py lines 469-490)**

```python
position_in_range = (current_price - range_low) / range_size

# Example: SPY at 202
# position_in_range = (202 - 184) / 14 = 1.29 (goes beyond 1.0!)

if position_in_range >= exit_zone and current_price >= trade.entry_price:
    # exit_zone = 0.90
    # 1.29 >= 0.90 = TRUE ✓
    
    if trade.direction == "LONG" and current_price >= prev_price:
        # HOLDS if price still rising (prev_price = 201, current = 202)
        # 202 >= 201 = TRUE → HOLD (don't exit)
    else:
        # Exits only if price is falling (dipping)
```

### The Problem

The exit logic assumes price stays within range boundaries. When price **breaks above the upper range**, the calculation becomes invalid:

- `position_in_range = 1.29` (should be clamped to 1.0)
- Entry condition satisfied: `1.29 >= 0.90` ✓
- BUT then: price must be **falling** to trigger exit
- If price is still rising even slightly → HOLDs indefinitely

### Why SPY Never Closed

Price at 202 > 198 (upper range), so it's beyond range. It should exit. But:
1. Price is still rising (202 > 201) → HOLD triggered
2. Need price to dip below 202 to exit
3. But if price keeps rising above 202, it never dips → Never exits

**This is a critical bug**: When price breaks range, the bot holds hoping for a dip instead of exiting immediately.

### The Fix (Needed)

Add logic: **If price breaks above upper range → always exit**

```python
# Proposed addition to exit logic
if current_price > range_high:  # Price broke above range
    logger.info(f"EXIT: Price ${current_price:.2f} exceeds range high ${range_high:.2f}")
    return "RANGE_BREAKOUT"

# Clamp position_in_range
position_in_range = min(1.0, (current_price - range_low) / range_size)
```

---

## Issue 5: No Time-Based Profit Taking

### Current Behavior
- Position opens at entry price
- Bot waits for price to fall, then bounce back to upper range
- If price just keeps dropping slowly, position held indefinitely waiting for upper range
- By time upper range is reached, losses are significant

### The Problem

The only exit mechanisms are:
1. Price reaches upper range AND starts falling (RANGE_HIGH)
2. Stop loss triggered (hard floor on losses)
3. Trailing stop (requires significant gain first)

**Missing**: Exit for small profit if price bounces any amount after a wait period

### Proposed Solution

Add **time-based exit** that attempts profit-taking:

**Mechanism:**
1. After position opens, start timer
2. If after T seconds, price has bounced up by even 0.2%, close for profit
3. If price falls below entry for T seconds, close to stop further losses

**Configuration (add to .env):**
```env
# Time after entry to start looking for profit-taking opportunity
TIME_AFTER_ENTRY_SECONDS=60

# Minimum profit % to trigger exit after time threshold
SMALL_PROFIT_TARGET_PCT=0.002  # 0.2% profit

# Maximum loss % to trigger exit if no upside after time threshold  
SMALL_LOSS_STOP_PCT=0.005  # 0.5% loss
```

**Implementation Location:**
File: `bot/strategy.py` → `check_exit_conditions()` method
- Add check after range/stop-loss checks
- If time elapsed > threshold and profit/loss target met → return exit reason
- Example exit reasons: "TIME_PROFIT", "TIME_LOSS"

**Benefits:**
- Prevents holding losing positions indefinitely
- Takes profits on small bounces
- Makes position holding time bounded

---

## Summary Table

| Issue | Root Cause | Impact | Fix Complexity |
|-------|-----------|--------|-----------------|
| 1. Env Not Working | Used wrong config variable | Can't adjust build time | Low - Change OPENING_RANGE_MINUTES |
| 2. Close Label Missing | No close events generated | Can't see closed trade values | High - Need real trades closing |
| 3. Building Stuck | Ticks not flowing OR bot/dashboard desync | Range never locks | Medium - Debug tick flow |
| 4. SPY No Exit | Exit logic breaks at range boundaries | Positions never close | Medium - Add breakout exit logic |
| 5. No Profit Taking | No time-based exit mechanism | Holds losing trades too long | Medium - Add time + profit threshold exit |

---

## Recommended Fix Order

1. **Issue 1** (Env) - Easiest, immediate impact
2. **Issue 4** (SPY Exit) - Critical bug, prevents positions closing
3. **Issue 5** (Time Profit) - Improves robustness
4. **Issue 3** (Building Stuck) - Investigate why ticks stop
5. **Issue 2** (Close Label) - Depends on Issue 4 (need real closes first)
