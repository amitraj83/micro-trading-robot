# Issue 2: CLOSE Label Not Showing During BUILDING Phase

## The Problem
After a position closes and range enters BUILDING phase, the "Close: $XXX" label disappears instead of persisting until the next trade opens.

## Root Cause Analysis

### Data Flow Scenario

```
Timeline:
T0: Position OPENS
    ├─ OPEN event broadcasted
    └─ Dashboard CLOSE handler: self.close_prices[symbol] = None  ← CLEARS old close!
       
T1-T59: Range BUILDING (60 ticks)
    └─ Tick loop checks: if self.close_prices[symbol] is not None
       └─ FALSE → Label shows "Close: --"
       
T60: Range LOCKED
    └─ Tick loop still checks close_prices[symbol]
       └─ Still None → Label still "Close: --"
    
T100: Position CLOSES
    ├─ CLOSE event broadcasted
    ├─ Dashboard CLOSE handler: self.close_prices[symbol] = price
    └─ Label shows "Close: $XXX"
    
T101-T300: Range BUILDING (for next cycle)
    └─ Tick loop shows "Close: $XXX" (works!)
    
T301: NEW position OPENS
    ├─ OPEN event broadcasted
    ├─ Dashboard OPEN handler: self.close_prices[symbol] = None  ← CLEARS it again!
    └─ Label shows "Close: --"
    
T302+: Range BUILDING
    └─ Tick loop shows "Close: --" (fails again!)
```

### The Core Bug

**File:** `websocket_ui/multi_symbol_dashboard.py` line 796

```python
elif action == "OPEN":
    # ... code ...
    self.open_prices[symbol] = entry_price
    self.close_prices[symbol] = None  # ← BUG: Clears previous close price!
```

**Why this is wrong:**
1. When a NEW position opens, we clear the PREVIOUS close price
2. But the previous close price is what we want to SHOW during the BUILDING phase
3. We should keep showing the last closed trade's exit price
4. Only when a BRAND NEW cycle starts should we clear it

### The Second Issue

**File:** `websocket_ui/multi_symbol_dashboard.py` lines 643-650

The tick loop displays close price only if `self.close_prices[symbol] is not None`:

```python
# Update close price if available (cached from last closed trade)
if self.close_prices[symbol] is not None:
    self.stat_labels[symbol]['close'].config(
        text=f"Close: ${self.close_prices[symbol]:.2f}",
        foreground="red"
    )
    print(f"[_process_symbol_tick] {symbol}: Showing cached Close: ${self.close_prices[symbol]:.2f}")
else:
    self.stat_labels[symbol]['close'].config(text="Close: --")
```

This is correct logic! But it's being undermined by line 796 clearing the value.

## Detailed Trace: What SHOULD Happen vs What HAPPENS

### Scenario: One Complete Trade Cycle

```
DESIRED BEHAVIOR:
━━━━━━━━━━━━━━━━━

Tick 0-60: BUILDING Phase
  Open:  --
  Close: --
  
Tick 61+: LOCKED Phase
  Open:  --
  Close: --
  
Tick 100: NEW TRADE OPENS (OPEN event)
  Open:  $487.01  (from event)
  Close: --        (no previous close yet)
  
Tick 150-180: Position held
  Open:  $487.01  (from strategy.current_positions)
  Close: --
  
Tick 185: TRADE CLOSES (CLOSE event)
  Open:  $487.01  (cached, keep showing)
  Close: $492.30  (from event, NOW SHOW THIS)
  
Tick 186-240: Range REBUILDING
  Open:  $487.01  (persist last trade's entry)  ← USER WANTS THIS
  Close: $492.30  (persist last trade's exit)   ← USER WANTS THIS
  
Tick 241: NEW TRADE OPENS (OPEN event)
  Open:  $491.50  (new entry price from event)
  Close: --        (clear previous, start fresh)  ← Clear here is OK
  
Tick 300+: New position held
  Open:  $491.50
  Close: --
```

### What ACTUALLY Happens NOW

```
ACTUAL BEHAVIOR:
━━━━━━━━━━━━━━━━

Tick 0-60: BUILDING Phase
  Open:  --
  Close: --
  
Tick 61+: LOCKED Phase
  Open:  --
  Close: --
  
Tick 100: NEW TRADE OPENS (OPEN event)
  Open:  $487.01   ✓ Correct
  Close: None      ← Line 796 sets to None
  
Tick 150-180: Position held
  Open:  $487.01   ✓ From strategy.current_positions
  Close: --        ✓ Shows "Close: --" (None value)
  
Tick 185: TRADE CLOSES (CLOSE event)
  Open:  $487.01   ✓ Cached
  Close: $492.30   ✓ Line 841 sets value
  
Tick 186-240: Range REBUILDING
  Open:  $487.01   ✓ Persists (cached)
  Close: $492.30   ✓ Persists (cached) - WORKS!
  
Tick 241: NEW TRADE OPENS (OPEN event)
  Open:  $491.50   ✓ New entry
  Close: None      ← Line 796 clears it IMMEDIATELY
  
Tick 242-300: Range REBUILDING
  Open:  $491.50   ✓
  Close: --        ✗ DISAPPEARS! (User wanted to see $492.30 still)
```

## Why Line 796 Exists (Intent vs Reality)

**Original Intent:**
```python
# When new position opens, clear the old close price to prepare for next cycle
self.close_prices[symbol] = None
```

**The Problem:**
- This clears it TOO EARLY
- It should only be cleared when we're truly starting a fresh range cycle
- But the next position opens BEFORE the BUILDING phase completes
- So we lose the previous close price info during the very BUILDING phase we want to show it in

## When Should We Clear close_prices?

**Current (Wrong):** When OPEN event arrives
**Correct timing:** 
- Option A: Only when clicking "replace symbol" or manually resetting
- Option B: When the range completes LOCKED phase (but this is complex)
- Option C: Never auto-clear; let user manually reset if needed
- Option D: Clear only when BUILDING phase completes AND no new trade opened

## The Fix Options

### Option 1: Don't Clear on OPEN (SIMPLEST)
```python
# Remove line 796 entirely
# self.close_prices[symbol] = None  ← DELETE THIS
```

**Consequence:** 
- Previous close price persists through multiple cycles
- Until manually cleared or symbol replaced
- Pro: Preserves history during BUILDING
- Con: Old data lingers if trading same symbol all day

### Option 2: Clear on New Range Reset (BETTER)
```python
# In strategy.py close_position() method
# When range resets to BUILDING, signal dashboard to clear close_prices

# Add to broadcast event:
broadcast_msg["clear_close_price"] = True

# In dashboard handle_trade_event():
if event.get("clear_close_price"):
    self.close_prices[symbol] = None
```

**Consequence:**
- Clear close price EXACTLY when range resets
- Prevents stale data from previous cycles
- Pro: Precise timing
- Con: Adds broadcast coordination

### Option 3: Track Range Cycle ID (COMPLEX)
```python
# Each time range resets, increment a cycle_id
# Only clear close_prices when new cycle_id arrives and position closes

self.range_cycle_id[symbol] = 0
# ... on range reset: increment
# ... on OPEN: only clear if new cycle
```

**Consequence:**
- Clean separation of cycles
- Pro: Prevents any data leakage between cycles
- Con: More complex state tracking

## Impact Assessment

### Current Impact
- **Severity:** Medium-Low
- **User Experience:** Close values disappear during rebuilding phase
- **Workaround:** None (values are genuinely lost)
- **Data Loss:** No, just display issue

### If We Use Option 1 (Simplest)
- **Benefit:** Close label persists through BUILDING as intended
- **Risk:** Stale close prices if trading same symbol repeatedly
- **Example:** Day 1: close at $500 → Day 2: still shows $500 from yesterday

### If We Use Option 2 (Better)
- **Benefit:** Clean cycle separation + persistent display in BUILDING
- **Risk:** Requires bot/dashboard coordination
- **Example:** Exact timing of clears matches range resets

## Recommendation

**Use Option 1 for now** (simplest, fixes the issue immediately):
- Remove line 796: `self.close_prices[symbol] = None`
- Add manual reset when symbol is replaced (already handled)
- If stale data becomes problem, migrate to Option 2

**Why Option 1 is good enough:**
1. User is trading same symbol all day anyway
2. Previous close is from recent trade, not stale
3. Can manually refresh by replacing symbol
4. No coordination overhead

**When to move to Option 2:**
- If user complains about stale values persisting
- If trading same symbol over multiple days
- When need production-grade state management
