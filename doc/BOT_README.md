# Micro Trading Bot

A high-frequency micro-trading bot for AAPL using momentum-burst strategy with WebSocket real-time data.

## 🎯 Strategy Overview

**Momentum Burst + Time Stop Strategy**

### Entry Conditions
- Price change ≥ 0.05% in last 15 seconds
- Volume spike (current vol > 1.5x rolling avg)
- Price volatility guard: ±0.1% move required
- No existing open positions

### Exit Conditions
1. **Profit Target**: +0.15% (maximize profits)
2. **Stop Loss**: -0.05% (tight stops)
3. **Time Stop**: 8 seconds max hold
4. **Flat Market**: Exit if 2 consecutive flat candles

### Risk Management
- **Max 1 open position** per symbol
- **Daily loss limit**: -5% stops all trading
- **Cooldown**: Skip 2 trades after a loss
- **Volatility filter**: Requires movement to trade

## 📊 Architecture

```
WebSocket Server (Port 8765)
       ↓ (Push ticks)
   Tick Buffer (15-sec rolling window)
       ↓
  Strategy Engine (Entry/Exit logic)
       ↓
  Risk Manager (Position validation)
       ↓
  Trade Executor (Simulate trades)
       ↓
  Metrics & Logging
       ↓
  UI Dashboard (Real-time visualization)
```

## 🚀 Setup

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Start the Server (Terminal 1)
```bash
python3 websocket_server/server.py
```

You should see:
```
============================================================
WebSocket Trading Server Started
============================================================
Server running on ws://localhost:8765
Waiting for clients to connect...
============================================================
```

### Start the Trading Dashboard (Terminal 2)
```bash
python3 websocket_ui/trading_dashboard.py
```

A graphical window will open showing:
- Real-time price chart with buy/sell signals
- Trading statistics (win rate, P/L, max drawdown)
- Recent trades history with colors (green=profit, red=loss)
- Live tick event log

## 📈 Dashboard Features

### Statistics Panel
- **Current Price**: Last AAPL price
- **Position**: Current open position (LONG/SHORT/None)
- **Trades**: Total number of completed trades
- **Win Rate**: Percentage of winning trades
- **Daily P/L**: Profit/Loss for current day
- **Total P/L**: Total profits since startup
- **Max Drawdown**: Largest peak-to-trough loss

### Price Chart
- Green line: Last trade price
- Green triangle (^): Buy signals
- Red triangle (v): Sell signals
- Auto-scaling Y-axis for visibility

### Recent Trades
- Shows last trades with entry/exit prices
- Color-coded: Green (profit), Red (loss)
- Exit reason: TP (target), SL (stop), TIME, FLAT

### Tick Events Log
- Real-time price, bid, ask data
- Last 50 events kept for reference

## ⚙️ Configuration

All settings in `bot/config.py`:

```python
STRATEGY_CONFIG = {
    "window_size": 15,              # Seconds of history
    "entry_threshold": 0.0005,      # 0.05% move required
    "volume_spike_multiplier": 1.5, # Volume > avg * 1.5
    "volatility_guard_threshold": 0.001,  # 0.1% move required
    "profit_target": 0.0015,        # 0.15% target
    "stop_loss": 0.0005,            # 0.05% stop
    "time_stop_seconds": 8,         # Max 8 sec hold
    "flat_seconds": 2,              # Flat market detection
}

RISK_CONFIG = {
    "max_open_positions": 1,
    "daily_loss_limit": -0.05,      # 5% daily loss limit
    "cooldown_trades_after_loss": 2,
    "position_size": 1.0,
}
```

## 📊 Metrics Tracked

- **Total ticks processed**
- **Total trades executed**
- **Winning/losing trades count**
- **Win rate percentage**
- **Daily and total P/L**
- **Max drawdown**
- **Current drawdown**
- **Consecutive losses**

## 🔧 File Structure

```
bot/
├── __init__.py           # Package init
├── config.py             # All strategy parameters
├── models.py             # Data classes (Tick, Trade, Metrics)
├── tick_buffer.py        # Rolling window data + momentum calc
├── strategy.py           # Core strategy logic
└── trading_bot.py        # WebSocket client integration

websocket_server/
└── server.py             # Mock WS server pushing ticks

websocket_ui/
└── trading_dashboard.py  # Real-time UI with strategy integration

requirements.txt          # Dependencies
```

## 📝 Logs

All trades logged to console with timestamps:
```
[timestamp] - bot.strategy - INFO - OPEN LONG @ $150.25
[timestamp] - bot.strategy - INFO - CLOSE LONG @ $150.48 (TP) | PnL: $0.23 (0.15%)
```

## 🎮 Controls

- **Run**: Launch server, then dashboard
- **Exit**: Close dashboard window (gracefully stops)
- **Monitor**: Watch real-time statistics update

## 📈 Performance Expectations

With realistic market conditions:
- **Win rate**: 45-55% (aim for positive risk/reward)
- **Avg win**: +0.12 to +0.15%
- **Avg loss**: -0.04 to -0.05%
- **Expectancy**: Avg win * win% - avg loss * loss%

Example:
```
Win% = 50%, Avg Win = +0.14%, Avg Loss = -0.05%
Expectancy = 0.14 * 0.5 - 0.05 * 0.5 = 0.045% per trade
```

## 🚨 Safety Features

1. **Daily loss kill switch** - Stops at -5%
2. **Max 1 open trade** - No over-leveraging
3. **Cooldown after losses** - Avoids revenge trading
4. **Volatility guard** - No trading in flat markets
5. **Time stops** - Forces exit to prevent overnight holds

## 🔄 Extending the Bot

To add new features:

1. **New entry signals**: Add to `check_entry_signals()` in `bot/strategy.py`
2. **New exit signals**: Add to `check_exit_signals()` in `bot/strategy.py`
3. **Custom metrics**: Extend `StrategyMetrics` in `bot/models.py`
4. **UI updates**: Modify `bot/trading_dashboard.py`

## 🐛 Debugging

Enable detailed logging:
```python
# In bot/config.py
LOG_CONFIG = {
    "level": "DEBUG",  # Changed from INFO
}
```

Check logs for all decisions:
```
[timestamp] - bot.strategy - DEBUG - Entry signal check...
[timestamp] - bot.strategy - DEBUG - Momentum: 0.0006 (threshold: 0.0005)
[timestamp] - bot.strategy - DEBUG - Volume spike: 2.1x avg
```

## ⚠️ Disclaimer

This is a **simulation/paper trading bot**. It does NOT execute real trades. To use with real money:

1. Integrate with broker API (Alpaca, Interactive Brokers, etc.)
2. Add proper order management
3. Implement slippage modeling
4. Test thoroughly with small position sizes
5. Monitor live trading closely

---

**Last Updated**: 2025-12-30
**Status**: Simulation Ready ✅
