# RANGE_LOOKBACK_MAX_MINUTES - Complete Usage Analysis

## Configuration Chain

```
.env
  RANGE_LOOKBACK_MAX_MINUTES=5
        ↓
config.py (line 42)
  RANGE_LOOKBACK_MAX_MINUTES = int(os.getenv("RANGE_LOOKBACK_MAX_MINUTES", "120"))
        ↓
config.py (line 53)
  RANGE_LOOKBACK_MAX_TICKS = int(RANGE_LOOKBACK_MAX_MINUTES * 60 / FETCH_INTERVAL_SECONDS)
  → 5 * 60 / 1 = 300 ticks
        ↓
config.py (line 67)
  "range_lookback_max_ticks": RANGE_LOOKBACK_MAX_TICKS
        ↓
config.py (line 84)
  "window_size": RANGE_LOOKBACK_MAX_TICKS
```

## Where It's Used

### 1. **Tick Buffer Window Size** (CRITICAL)
**File:** `bot/strategy.py` line 61
```python
self.tick_buffers: dict = {}  # {symbol: TickBuffer}
```

**File:** `bot/strategy.py` line 65-66
```python
buf = TickBuffer(symbol, window_size=STRATEGY_CONFIG["window_size"])
# window_size = RANGE_LOOKBACK_MAX_TICKS = 300 ticks
```

**Effect:**
- Tick buffer holds maximum 300 price ticks (5 minutes of data with 1-second intervals)
- Older ticks are automatically dropped (deque with maxlen)
- This is the **maximum history available** for any calculation

**Current with RANGE_LOOKBACK_MAX_MINUTES=5:**
- Buffer holds 300 ticks = 5 minutes of price history
- Any calculation looking back can only see 5 minutes max

---

### 2. **Exit Range Calculation** (PRIMARY USE)
**File:** `bot/strategy.py` lines 456-475

```python
# Check exit conditions
buf = self.tick_buffers.get(symbol)
if buf:
    prices = buf.get_prices()  # Gets up to 300 prices (300 ticks)
    min_lookback = STRATEGY_CONFIG.get("range_lookback_min_ticks", 5)       # 5 ticks = 5 seconds
    max_lookback = STRATEGY_CONFIG.get("range_lookback_max_ticks", 60)      # ← Uses this!
    
    if len(prices) >= min_lookback:
        lookback_ticks = min(len(prices), max_lookback)  # Take min of available and max
        # ↑ With RANGE_LOOKBACK_MAX_MINUTES=5: max_lookback = 300 ticks
        
        lookback_prices = prices[-lookback_ticks:]  # Get last N prices
        range_high = max(lookback_prices)
        range_low = min(lookback_prices)
        range_size = range_high - range_low
        
        position_in_range = (current_price - range_low) / range_size
        
        # EXIT if price near range high
        if position_in_range >= exit_zone and current_price >= trade.entry_price:
            # exit
```

**Effect with RANGE_LOOKBACK_MAX_MINUTES=5 (300 ticks):**
- Exit calculation looks at: last 300 ticks of price data
- range_high = highest price in last 5 minutes
- range_low = lowest price in last 5 minutes
- Exit triggers when current price is in top 10% of that range

**Example:**
- Last 5 minutes: low=184, high=198
- range_size = 14
- position_in_range threshold = 0.90
- Exit trigger = price >= 184 + (14 * 0.90) = 198.6

---

### 3. **Entry Zone Logging** (INFORMATIONAL)
**File:** `bot/strategy.py` lines 202-204

```python
"trigger_zone_low": STRATEGY_CONFIG.get("range_entry_zone_pct", 0.10),
"min_lookback": STRATEGY_CONFIG.get("range_lookback_min_ticks", 5),
"max_lookback": STRATEGY_CONFIG.get("range_lookback_max_ticks", 60),
```

This is just logging/display info, not a functional limit.

---

## Current Configuration Analysis

**Your settings:**
```env
RANGE_LOOKBACK_MAX_MINUTES=5          # 300 ticks max lookback
RANGE_LOOKBACK_MIN_MINUTES=1          # 60 ticks min lookback
RANGE_EXIT_ZONE_PCT=0.80              # Exit at 80% from bottom (not 90%)
OPENING_RANGE_MINUTES=1               # 60 ticks to build opening range
FETCH_INTERVAL=1                      # 1 second per tick
```

**Computed values:**
- `RANGE_LOOKBACK_MAX_TICKS = 5 * 60 / 1 = 300 ticks`
- `RANGE_LOOKBACK_MIN_TICKS = 1 * 60 / 1 = 60 ticks`
- `OPENING_RANGE_TICKS = 1 * 60 / 1 = 60 ticks`

---

## What RANGE_LOOKBACK_MAX_MINUTES Actually Controls

### ✅ Controls
1. **Tick buffer window size** - how much historical price data is retained
2. **Exit range calculation** - how far back to look for high/low when checking exit conditions
3. **Memory usage** - larger value = more ticks held in memory

### ❌ Does NOT Control
1. **Opening range build duration** - controlled by `OPENING_RANGE_MINUTES`
2. **Entry signals** - uses opening range, not lookback range
3. **Position hold time** - controlled by exit conditions, not lookback period
4. **Lock time validity** - controlled by hard-coded 15 minutes in strategy.py

---

## Impact Analysis: What Changed When You Set It to 5?

**Before (default 120 minutes):**
- Tick buffer held 7200 ticks (120 minutes of data)
- Exit calculation looked back up to 120 minutes
- Position in range = (price - low_of_last_2_hours) / range_of_last_2_hours
- Exits triggered when price near 2-hour high

**After (now 5 minutes):**
- Tick buffer holds 300 ticks (5 minutes of data)
- Exit calculation looks back up to 5 minutes
- Position in range = (price - low_of_last_5_minutes) / range_of_last_5_minutes
- Exits trigger when price near 5-minute high

**The Effect:**
- **Smaller lookback = tighter range = more frequent exits**
- Exit trigger happens sooner because 5-min range is narrower than 2-hour range
- SPY example: In 2-hour range might be 190-200. In 5-min range might be 194-198 (much tighter)
- **Likely HELPS with the SPY exit problem** (202 never closed) because the range resets more frequently

---

## Critical Findings

### Finding 1: Buffer Size Constraint
**Current:** `window_size = 300 ticks`

If you set `RANGE_LOOKBACK_MAX_MINUTES=120`, the buffer would be 7200 ticks.
**Memory impact:** Each symbol keeps 7200 price points. With 5 symbols = 36,000 floats ≈ 144KB
**Not a problem** for desktop, could matter on embedded systems.

### Finding 2: Current Setting is GOOD
**Your change to RANGE_LOOKBACK_MAX_MINUTES=5 is actually beneficial** because:
1. Smaller lookback window = exits trigger faster
2. Prevents holding positions through long losing streaks
3. More responsive to recent price action
4. Helps with SPY exit issue (202 beyond range)

### Finding 3: There's a Logic Gap
**The exit logic issue remains:** Even with 5-minute range, if price breaks ABOVE the high, it still doesn't close properly. The lookback window doesn't solve Issue 4 (SPY position not closing).

---

## Recommendations for RANGE_LOOKBACK_MAX_MINUTES

### For Testing (Current)
```env
RANGE_LOOKBACK_MAX_MINUTES=5        # ✅ Good for quick exits
RANGE_LOOKBACK_MIN_MINUTES=1        # ✅ Good for responsive range
```

### For Production (Recommended)
```env
RANGE_LOOKBACK_MAX_MINUTES=60       # Look back 1 hour for exits
RANGE_LOOKBACK_MIN_MINUTES=5        # Minimum 5 minutes for stability
```

### If You Want Aggressive Trading
```env
RANGE_LOOKBACK_MAX_MINUTES=3        # Only look at last 3 minutes
RANGE_LOOKBACK_MIN_MINUTES=1        # Quick responses
```

---

## Summary: Is RANGE_LOOKBACK_MAX_MINUTES Working?

**YES** ✅ 
- It IS loaded from .env correctly
- It IS converted to ticks correctly
- It IS used to size the tick buffer
- It IS used in exit range calculations
- Your change to 5 minutes WAS effective

**The effect you may not have seen is:**
- Exits happen sooner (range tighter)
- But if price goes BEYOND range, exits still break (Issue 4)
- So you don't see the improvement because positions aren't closing anyway

**Conclusion:** The variable works, but Issue 4 (position not closing when price breaks range) masks its effectiveness.
