# Bot v2 Quick Start

## Files Created
- `bot_v2.py` (473 lines) - Main trading bot
- `run_bot_v2.sh` - Launcher script
- `BOT_V2_README.md` - Full documentation

## Quick Run

```bash
# Set symbols in .env first:
# SYMBOLS=AAPL,TSLA,SPY

# Then run:
./run_bot_v2.sh

# Or directly:
POLYGON_API_KEY=your_key SYMBOLS=AAPL python3 bot_v2.py
```

## State Machine Overview

```
IDLE → COMPRESSION (≥3 bars) → IN_TRADE (expansion) → IDLE
                                    ↓
                              (stop/target/timeout)
```

## Strategy Rules (Locked)

### VWAP Bias
```
Bullish:  last 3 closes > VWAP
Bearish:  last 3 closes < VWAP
Neutral:  otherwise (NO TRADES)
```

### Compression Detection
```
Last 10 bars must show:
- max(range) < mean(range) * 1.1
- current_volume < mean(volume)
- Persist for ≥3 consecutive bars
```

### Expansion Entry
```
Current bar must show:
- range ≥ 1.8 × avg_range (last 5)
- volume ≥ 1.5 × avg_volume (last 5)
- Close in top 20% (LONG) or bottom 20% (SHORT)
- Must be in COMPRESSION state
- Bias must match direction
```

### Entry Orders
```
LONG:  Stop = bar_low,  Target = entry + 1.5×range
SHORT: Stop = bar_high, Target = entry - 1.5×range
```

### Exit Conditions
```
1. Stop breached (bar low/high crosses)
2. Target reached (bar low/high crosses)
3. ≥15 seconds AND unprofitable
   - LONG:  close < entry
   - SHORT: close > entry
```

## Configuration

Edit in `bot_v2.py`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MIN_COMPRESSION_BARS` | 3 | Min bars to confirm compression |
| `RANGE_EXPAND_FACTOR` | 1.8 | Range expansion threshold |
| `VOLUME_EXPAND_FACTOR` | 1.5 | Volume expansion threshold |
| `CLOSE_EDGE_PERCENT` | 0.2 | 20% from extreme |
| `TIME_EXIT_SECONDS` | 15 | Time-based exit |
| `TARGET_RR` | 1.5 | Risk-reward ratio |

## Data Contract

WebSocket messages (JSON):
```json
{
  "ev": "A",              // ← Only process this
  "sym": "AAPL",
  "v": 1000,              // Tick volume
  "av": 50M,              // Accumulated volume
  "o": 150.10,            // Bar open
  "c": 150.50,            // Bar close
  "h": 150.75,            // Bar high
  "l": 150.00,            // Bar low
  "a": 150.30,            // Session VWAP (TODAY)
  "vw": 150.25,           // Tick VWAP
  "z": 42,                // Avg trade size
  "s": 1672531200000,     // Start time (ms)
  "e": 1672531201000      // End time (ms)
}
```

## Log Format

```
[HH:MM:SS] SYMBOL | ACTION | Details...
```

Example:
```
[09:35:12] AAPL   | ENTER  | DIR=LONG PRICE=150.5000 STOP=149.9000 TGT=152.0000
[09:35:27] AAPL   | EXIT   | REASON=TARGET PRICE=152.1000 PNL=+1.6000
[09:35:40] AAPL   | EXIT   | REASON=STOP PRICE=149.8000 PNL=-0.7000
```

## Session Hours
- **Trading window**: 09:30 – 16:00 US/Eastern
- Bars outside this window are ignored
- No pre-market, no after-hours trades

## Constraints Met
✅ Async/await only (no blocking)  
✅ Multi-symbol (single process)  
✅ No bid/ask logic  
✅ No tick assumptions  
✅ No external TA libraries  
✅ Event-driven (no polling)  
✅ VWAP from provider (no calculation)  
✅ 09:30-16:00 ET session filter  
✅ Compression persistence (≥3 bars)  
✅ Expansion-after-compression logic  

## Next Steps

1. **Wait for next market day** (market closed Jan 1)
2. **Run the bot**:
   ```bash
   ./run_bot_v2.sh
   ```
3. **Watch logs** for ENTER/EXIT messages
4. **Adjust thresholds** based on market behavior
5. **Integrate with dashboard** (if needed)

## Troubleshooting

**No trades?**
- Check market hours (09:30-16:00 ET)
- Check API key is valid
- Market may not show compression → expansion pattern

**Bot not starting?**
- Verify `POLYGON_API_KEY` is set
- Check `SYMBOLS` env var is correct
- Run: `python3 -c "from bot_v2 import *"`

**WebSocket disconnected?**
- Network issue or rate limit
- Logs will show connection error
- Reconnection logic can be added

## Files Changed
- ✅ Created: `bot_v2.py`
- ✅ Created: `run_bot_v2.sh`
- ✅ Created: `BOT_V2_README.md`
- ✅ Unchanged: `websocket_ui/multi_symbol_dashboard.py` (can integrate later)
- ⚠️ Old bot logic (config.py, rules.py, etc) still present but not used

## Ready?
Yes! Bot is ready to test on next market day.

Run:
```bash
./run_bot_v2.sh
```
