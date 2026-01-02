# Yahoo Finance Screener Types

## Overview
The bot can now fetch symbols from different Yahoo Finance screeners. Change the `YAHOO_SCREENER_TYPE` in `.env` to quickly switch between different market selections.

## Available Screener Types

### 1. **day_gainers** (Default)
Top percentage gainers for the day
```env
YAHOO_SCREENER_TYPE=day_gainers
```
**Best for:** Momentum trading, following the day's strongest movers
**Risk:** May be overhyped, reversals common after big gains

### 2. **most_active**
Highest trading volume stocks
```env
YAHOO_SCREENER_TYPE=most_active
```
**Best for:** Scalping, high liquidity, tight spreads
**Risk:** Volume ≠ direction, may be random oscillation

### 3. **most_trending** (Currently Used)
Most socially trending / highest momentum
```env
YAHOO_SCREENER_TYPE=most_trending
```
**Best for:** Riding social/news momentum, early breakouts
**Risk:** News-driven volatility, false breakouts common

### 4. **day_losers**
Top percentage losers for the day
```env
YAHOO_SCREENER_TYPE=day_losers
```
**Best for:** Contrarian trades, bounce trading oversold stocks
**Risk:** Stocks may continue falling, catching falling knives

## How to Switch

### Quick Switch (No Code Changes)
1. Edit `.env` and change the line:
   ```env
   YAHOO_SCREENER_TYPE=most_trending  # Change this
   ```

2. Restart the bot:
   ```bash
   cd /Users/ara/micro-trading-robot
   bash restart.sh
   ```

### Example Sequences
**Try trending first, fall back to gainers if bad:**
```bash
# Session 1: Try trending
echo "YAHOO_SCREENER_TYPE=most_trending" >> .env
bash restart.sh
# ... trade for 30 mins ...

# Session 2: Switch to gainers if trending isn't working
sed -i '' 's/most_trending/day_gainers/' .env
bash restart.sh
```

**A/B Test Different Screeners:**
```bash
# Morning: Gainers
sed -i '' 's/YAHOO_SCREENER_TYPE=.*/YAHOO_SCREENER_TYPE=day_gainers/' .env

# Midday: Most Active (liquidity)
sed -i '' 's/YAHOO_SCREENER_TYPE=.*/YAHOO_SCREENER_TYPE=most_active/' .env

# Afternoon: Trending (momentum)
sed -i '' 's/YAHOO_SCREENER_TYPE=.*/YAHOO_SCREENER_TYPE=most_trending/' .env
```

## Current Configuration

**Platform:** YAHOO  
**Screener Type:** most_trending  
**Auto-Update:** true  
**Validation:** Polygon API (confirms ticker existence)  
**Symbol Limit:** 4 (for 2x2 dashboard)

## Implementation Details

### Files Modified
- `.env` - Added `YAHOO_SCREENER_TYPE` parameter
- `find_matching_tickers.py` - Updated `fetch_gainers_yahoo()` to accept screener type
- `update_symbols_from_gainers.py` - Passes screener type to finder

### Code Flexibility
The parameter flows through:
```
.env YAHOO_SCREENER_TYPE
  ↓
update_symbols_from_gainers.py
  ↓
find_matching_tickers.py
  ↓
fetch_gainers() / fetch_gainers_yahoo()
  ↓
Yahoo API: scrIds={screener_type}
```

### Fallback Behavior
If the screener API returns 404 or fails:
1. Falls back to manual ticker checking
2. Validates each ticker individually with yfinance
3. Still returns sorted list by change %
4. Still filters by instruments and Polygon validation

## Performance Notes

- **most_trending** may have higher false breakout rate
- **day_gainers** tends to have reverse momentum later in day
- **most_active** has best liquidity for scalping
- Screener API sometimes returns 404 (Yahoo rate limiting) → fallback kicks in

## Future Enhancements

Could add:
- `SCREENER_MIN_CHANGE_PCT` - Filter screener results by min % change
- `SCREENER_MAX_PRICE` - Only trade <$X (penny stock strategy)
- `SCREENER_MIN_VOLUME` - Require minimum daily volume
- Multiple screeners at once (4 stocks from gainers + 2 from trending)

## Troubleshooting

**Symbols not updating?**
- Check `AUTO_UPDATE_SYMBOLS_FROM_GAINERS=true`
- Check restart.sh output for validation errors
- Try switching to `day_gainers` (most reliable)

**404 errors in logs?**
- Yahoo rate limiting on screener API
- Fallback to manual ticker check still works
- Add random delay in update_symbols_from_gainers.py if frequent

**Same symbols every restart?**
- Set `AUTO_UPDATE_SYMBOLS_FROM_GAINERS=true`
- Or edit SYMBOLS manually in .env
