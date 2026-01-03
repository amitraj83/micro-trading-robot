# OHLC Calculation from Tick Data

## Real-World Example: DVLT during 2026-01-02T20:22 (59 ticks)

### The Data Flow

```
59 individual ticks (each second or within second)
    ↓ ↓ ↓ ↓ ↓ ... (59 prices and volumes)
    ↓
EXTRACT 4 KEY PRICES from the 59 ticks
EXTRACT TOTAL VOLUME
CALCULATE WEIGHTED AVERAGE
    ↓
Single OHLC bar representing entire minute
```

---

## Step-by-Step Calculation

### Input Data (59 ticks in the minute)

| Time | Price | Volume | Cumulative |
|------|-------|--------|-----------|
| 20:22:00.465 | 1.0900 | 1,479 | 1,479 |
| 20:22:02.256 | 1.0905 | 11,187 | 12,666 |
| 20:22:03.341 | 1.0950 | 26,992 | 39,658 |
| 20:22:04.449 | 1.0974 | 3,214 | 42,872 |
| 20:22:05.497 | 1.0940 | 8,188 | 51,060 |
| ... | ... | ... | ... |
| 20:22:59.479 | 1.0974 | 1,278 | **599,770** |

**Total ticks: 59**
**Total volume: 599,770 shares**

---

## OHLC Components

### 1. **O (OPEN)** - First Price in Minute

```
Open = first_tick.price
Open = 1.0900
```

**Logic**: The price at which trading started in this minute

---

### 2. **H (HIGH)** - Maximum Price in Minute

```
High = max(all_prices_in_minute)
High = max(1.0900, 1.0905, 1.0950, 1.0974, 1.0940, ..., 1.0974)
High = 1.1000  ← occurred at 20:22:09.348
```

**Logic**: The peak price reached during the minute

---

### 3. **L (LOW)** - Minimum Price in Minute

```
Low = min(all_prices_in_minute)
Low = min(1.0900, 1.0905, 1.0950, 1.0974, 1.0940, ..., 1.0974)
Low = 1.0900  ← occurred multiple times
```

**Logic**: The lowest price reached during the minute

---

### 4. **C (CLOSE)** - Last Price in Minute

```
Close = last_tick.price
Close = 1.0974
```

**Logic**: The price at which the minute ended

---

### 5. **V (VOLUME)** - Total Shares Traded

```
Volume = sum(all_volumes_in_minute)
Volume = 1,479 + 11,187 + 26,992 + 3,214 + 8,188 + ... + 1,278
Volume = 599,770 shares
```

**Logic**: Total quantity of shares traded in this minute

---

### 6. **VWAP (Volume-Weighted Average Price)**

The most important calculation for traders.

```
VWAP = Σ(price × volume) / Σ(volume)

Numerator = (1.0900 × 1,479) + (1.0905 × 11,187) + (1.0950 × 26,992) + ...
          = 1,611.21 + 12,205.57 + 29,610.24 + ... + 1,402.54
          = 656,168.32

Denominator = 599,770

VWAP = 656,168.32 / 599,770
VWAP = 1.0940
```

**Why VWAP matters**:
- Heavily weighted by larger volume trades
- Represents the "true" average price considering market activity
- In this example: 26,992 shares at 1.0950 (large volume) pulls the average up
- Better than simple average which would ignore volume

---

## Output: Single OHLC Bar

All 59 ticks collapse into one bar:

```json
{
  "ev": "A",              // Event: Aggregate bar
  "sym": "DVLT",          // Symbol
  "o": 1.0900,            // Open: 1.0900
  "h": 1.1000,            // High: 1.1000
  "l": 1.0900,            // Low:  1.0900
  "c": 1.0974,            // Close: 1.0974
  "v": 599770,            // Volume: 599,770 shares
  "vw": 1.0940,           // VWAP: 1.0940
  "z": 59,                // Transaction count: 59 ticks
  "s": 1767385320465,     // Start time: milliseconds
  "e": 1767385380464,     // End time: milliseconds
  "n": 1                  // Items in aggregate: 1
}
```

---

## Visual Representation

```
Price Movement During 20:22 Minute for DVLT
─────────────────────────────────────────────────

  1.1000 │                 ╭─ HIGH (peak price)
         │                 │
         │   ╭────────────╮│
  1.0990 │   │            ││
         │   │   ╭─────╮  ││
  1.0980 │   │   │     │  ││
         │   │   │     │  ││  ↑
  1.0970 │ OPEN │   CLOSE  ││  │ Price
         │   1.09 │1.0974  ││  │ Range
  1.0960 │   │   │     │  ││  │
         │   │   │     │  ││  ↓
  1.0950 │   │   ╰─────╯  ││
         │   │            ││
  1.0940 │   │         (HIGH)
         │   │            ││
  1.0930 │   │            ││
         │   │            ││
  1.0900 │───╰────────────╯╰─ LOW (bottom price)
         │
  └─────────────────────────────────────────────
    Time  Open    Trades    Close
```

### Key Observations:
- Started at 1.0900 (Open)
- Peak reached 1.1000 (High)
- Floor stayed at 1.0900 (Low)
- Ended at 1.0974 (Close)
- 599,770 shares changed hands (Volume)
- **Most trades were between 1.0900-1.0950** (weighted heavily in VWAP)

---

## Practical Example: Why VWAP Matters

Same minute, different volume distribution:

**Scenario A: Our actual data**
- 26,992 shares at 1.0950 (40% of volume)
- 62,402 shares at 1.0900 (10% of volume)
- VWAP = 1.0940 (pulled up by high-volume 1.0950 trades)

**Scenario B: Different distribution**
- 26,992 shares at 1.0900
- 62,402 shares at 1.1000
- VWAP would be pulled toward 1.1000

**Why the bot uses VWAP**:
- Simple average: (1.0900 + 1.1000) / 2 = 1.0950
- But this ignores that MORE shares traded at 1.0900
- VWAP correctly weights: more activity at 1.0900 = lower average
- Better for entry/exit price decisions

---

## Complete Transformation Pipeline

```
TICK DATA                         OHLC BAR
─────────────────                ──────────

Tick 1:                          Single Minute Bar:
  timestamp: 20:22:00.465          Symbol: DVLT
  price: 1.0900         ───┐        Open:   1.0900
  volume: 1,479         ───┤        High:   1.1000
                            │        Low:    1.0900
Tick 2:                      ├─ AGGREGATE ─→ Close:  1.0974
  timestamp: 20:22:02.256    │        Volume: 599,770
  price: 1.0905         ───┤        VWAP:   1.0940
  volume: 11,187        ───┤
                            │
Tick 3:                      │
  ... (continues) ...   ─────┤
                            │
Tick 59:                      │
  timestamp: 20:22:59.478    │
  price: 1.0974         ───┤
  volume: 1,278         ───┤
                        ───┘

Result: 10,308 ticks → 292 OHLC bars (across 4 symbols, ~72 minutes)
```

---

## Code Implementation (from transformer)

```python
def aggregate_ticks_to_bars(ticks):
    """
    Group ticks by symbol-minute, then calculate OHLC
    """
    bars_by_symbol_minute = defaultdict(list)
    
    # Group ticks by (symbol, minute)
    for tick in ticks:
        symbol = tick['symbol']
        timestamp = tick['timestamp']
        minute_key = timestamp[:16]  # "2026-01-02T20:22"
        key = (symbol, minute_key)
        bars_by_symbol_minute[key].append(tick)
    
    # Calculate OHLC for each group
    bars = []
    for (symbol, minute_key), ticks_in_minute in bars_by_symbol_minute.items():
        prices = [t['price'] for t in ticks_in_minute]
        volumes = [t['volume'] for t in ticks_in_minute]
        
        # The 4 key prices
        open_price = prices[0]           # OPEN
        close_price = prices[-1]         # CLOSE
        high_price = max(prices)         # HIGH
        low_price = min(prices)          # LOW
        
        # Totals
        total_volume = sum(volumes)      # VOLUME
        
        # Weighted calculation
        vwap = sum(p*v for p,v in zip(prices, volumes)) / total_volume  # VWAP
        
        # Create bar
        bar = {
            'sym': symbol,
            'o': open_price,
            'h': high_price,
            'l': low_price,
            'c': close_price,
            'v': total_volume,
            'vw': vwap,
            'z': len(ticks_in_minute),  # tick count
            # ... timestamps ...
        }
        bars.append(bar)
    
    return bars
```

---

## Summary

| Component | Formula | Example | Meaning |
|-----------|---------|---------|---------|
| **Open** | `prices[0]` | 1.0900 | First trade price |
| **High** | `max(prices)` | 1.1000 | Peak price |
| **Low** | `min(prices)` | 1.0900 | Bottom price |
| **Close** | `prices[-1]` | 1.0974 | Last trade price |
| **Volume** | `Σ volumes` | 599,770 | Total shares |
| **VWAP** | `Σ(p×v) / Σv` | 1.0940 | Weighted avg |

**Result**: 59 ticks → 1 clean OHLC bar ready for bot processing ✅
