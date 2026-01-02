# Bot v2: Momentum Trading After Compression

## Overview

New async Python trading bot using second-level aggregates from Polygon WebSocket.

**Strategy**: Detect compression, trade expansion breakouts with VWAP bias.

## Architecture

### State Machine
```
IDLE
  ↓ (compression ≥3 bars)
COMPRESSION
  ↓ (expansion + bias match)
IN_TRADE
  ↓ (stop/target/timeout)
IDLE
```

### Key Features
- **Async/await** throughout (no blocking)
- **Multi-symbol** support (single process)
- **Rolling buffers**: 5, 10, 30 bars per symbol
- **VWAP bias** from provider field `a` (no calculation)
- **Session filter**: 09:30-16:00 ET only
- **Compression persistence**: ≥3 consecutive bars
- **Expansion trigger**: Only after compression state
- **Event-driven**: Message handling, no polling

## Configuration

### Environment Variables

```bash
POLYGON_API_KEY=<your-key>          # Required
SYMBOLS=AAPL,TSLA,SPY               # Comma-separated (no spaces)
```

### Strategy Parameters (in `bot_v2.py`)

| Parameter | Value | Description |
|-----------|-------|-------------|
| `MIN_COMPRESSION_BARS` | 3 | Minimum consecutive compression bars |
| `RANGE_EXPAND_FACTOR` | 1.8 | Range must be ≥1.8x average |
| `VOLUME_EXPAND_FACTOR` | 1.5 | Volume must be ≥1.5x average |
| `CLOSE_EDGE_PERCENT` | 0.2 | 20% from candle extreme |
| `TIME_EXIT_SECONDS` | 15 | Exit timeout (if unprofitable) |
| `TARGET_RR` | 1.5 | Risk-reward multiplier |

## Running

### Single Symbol
```bash
POLYGON_API_KEY=your_key SYMBOLS=AAPL python3 bot_v2.py
```

### Multiple Symbols
```bash
POLYGON_API_KEY=your_key SYMBOLS=AAPL,TSLA,SPY python3 bot_v2.py
```

### Using Launcher
```bash
./run_bot_v2.sh
```
(reads `SYMBOLS` from `.env`)

## Data Contract

Each WebSocket message (aggregate bar) has:

```json
{
  "ev": "A",                    // Event type (A = aggregate)
  "sym": "AAPL",               // Ticker symbol
  "v": 1000,                   // Tick volume
  "av": 50000000,              // Accumulated volume today
  "op": 150.00,                // Today's official open
  "vw": 150.25,                // Tick volume-weighted avg
  "o": 150.10,                 // Bar open
  "c": 150.50,                 // Bar close
  "h": 150.75,                 // Bar high
  "l": 150.00,                 // Bar low
  "a": 150.30,                 // Session VWAP (TODAY)
  "z": 42,                     // Avg trade size
  "s": 1672531200000,          // Start time (ms)
  "e": 1672531201000           // End time (ms)
}
```

**Important**: Only `ev == "A"` messages are processed.

## Trading Logic

### VWAP Bias
- **Bullish**: Last 3 closes > session VWAP (`a`)
- **Bearish**: Last 3 closes < session VWAP (`a`)
- **Neutral**: Otherwise (no trades)

### Compression
```
max(range) < mean(range) * 1.1  AND  current_volume < mean(volume)
```
Must persist for ≥3 consecutive bars.

### Expansion (Entry Trigger)
```
current_range ≥ 1.8 × avg_range(last 5)  AND
current_volume ≥ 1.5 × avg_volume(last 5)
```

### Close Position
- **LONG entry**: Close in top 20% of candle
  - `close >= high - 0.2 * (high - low)`
- **SHORT entry**: Close in bottom 20% of candle
  - `close <= low + 0.2 * (high - low)`

### Entry Rules
All must be true:
1. Bias is not neutral
2. Currently in COMPRESSION state
3. Bar shows expansion
4. Close position matches bias

### Order Setup
- **LONG**: Stop = bar low, Target = entry + 1.5×range
- **SHORT**: Stop = bar high, Target = entry - 1.5×range

### Exit Rules
Exit immediately if:
1. Stop breached (bar high/low crosses)
2. Target reached (bar high/low crosses)
3. 15 seconds elapsed **AND** trade unprofitable
   - LONG: exit if close < entry
   - SHORT: exit if close > entry

## Logging

Format:
```
[HH:MM:SS] SYMBOL | LEVEL  | Message...
```

Examples:
```
[09:35:12] AAPL   | ENTER  | DIR=LONG PRICE=150.5000 STOP=149.9000 TGT=152.0000
[09:35:27] AAPL   | EXIT   | REASON=TARGET PRICE=152.1000 PNL=+1.6000
[09:35:35] AAPL   | EXIT   | REASON=TIME_EXIT PRICE=150.6000 PNL=+0.1000
[09:35:40] AAPL   | EXIT   | REASON=STOP PRICE=149.8000 PNL=-0.7000
```

## Development Notes

### No External TA Libraries
Strategy uses only Python stdlib:
- `collections.deque` (rolling buffers)
- `statistics.mean` (averages)
- `datetime`, `pytz` (timestamps)

### Single File Design
All logic in `bot_v2.py` for easy deployment.

### Extensibility
Later enhancements:
- Real execution (replace logging with broker API)
- Multiple feeds (combine Polygon + Massive)
- Risk management (position sizing, max drawdown)
- Dashboard integration (WebSocket to UI)

## Constraints Respected

✅ No bid/ask logic  
✅ No tick assumptions  
✅ No indicators (RSI/MACD/etc)  
✅ No synchronous blocking  
✅ No global sleeps  
✅ Event-driven only  
✅ 09:30-16:00 ET session filter  

## Testing

### Syntax Check
```bash
python3 -m py_compile bot_v2.py
```

### Import Test
```bash
python3 -c "from bot_v2 import *; print('OK')"
```

### Live Test (next market day)
```bash
POLYGON_API_KEY=your_key SYMBOLS=AAPL python3 bot_v2.py
```
Watch for ENTER/EXIT logs.

## Troubleshooting

**No messages received?**
- Market is closed (holidays, weekends, pre/post-market)
- Check API key is valid
- Check subscription format (should be `A.SYMBOL`)

**WebSocket disconnects?**
- Network issue or API rate limiting
- Add reconnection logic if needed

**Trades not triggering?**
- Market may not be showing compression+expansion pattern
- Check logs for state transitions (IDLE → COMPRESSION → IN_TRADE)
- Adjust thresholds in config

## License

Internal use only.
