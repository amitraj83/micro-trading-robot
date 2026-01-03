# Multi-Dashboard Architecture: Tracking 20 Stocks Across 5 Dashboards

## Overview
Expand your monitoring capability from 4 symbols to 20 symbols by deploying 5 independent dashboard instances, each tracking 4 stocks. This allows simultaneous real-time monitoring of all 20 positions without performance degradation.

---

## Current State vs. Multi-Dashboard

### Current Setup
- **Single Dashboard**: 1 instance of `multi_symbol_dashboard.py`
- **Symbols**: 4 (AXSM, DJT, WULF, UUUU)
- **Visualization**: Matplotlib grid with 4 subplots (1 row per symbol)
- **Port**: 8000
- **Monitoring**: 1 browser window

### Multi-Dashboard Setup
- **5 Independent Dashboards**: 5 separate `multi_symbol_dashboard.py` instances
- **Symbols**: 20 total (4 per dashboard)
- **Visualization**: 5 separate Matplotlib figures
- **Ports**: 8000, 8001, 8002, 8003, 8004
- **Monitoring**: 5 browser windows (can be tiled side-by-side)

---

## Architecture Design

### Symbol Distribution Example
```
Dashboard 1 (Port 8000): AXSM, DJT, WULF, ONDS
Dashboard 2 (Port 8001): NVDA, TSLA, AAPL, MSFT
Dashboard 3 (Port 8002): GOOGL, AMZN, META, NFLX
Dashboard 4 (Port 8003): AMD, INTC, QCOM, MRVL
Dashboard 5 (Port 8004): COIN, HOOD, UPST, SOFI
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    Polygon API (30s interval)               │
│         Fetches all 20 symbols simultaneously               │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  bot.py (Central Instance)                  │
│    • Polygon API client fetches 20 symbols                 │
│    • MicroTradingStrategy processes all symbols            │
│    • WebSocket server broadcasts ALL price updates         │
│    • Trading212Broker executes orders for all symbols      │
└──────────────────────────┬──────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┬───────────────┬──────────────┐
        │                  │                  │               │              │
        ▼                  ▼                  ▼               ▼              ▼
   Dashboard 1        Dashboard 2        Dashboard 3    Dashboard 4    Dashboard 5
   (Port 8000)        (Port 8001)        (Port 8002)    (Port 8003)    (Port 8004)
   
   Symbols 1-4        Symbols 5-8        Symbols 9-12   Symbols 13-16  Symbols 17-20
   
   WebSocket          WebSocket          WebSocket      WebSocket      WebSocket
   Listener           Listener           Listener       Listener       Listener
   (Filters)          (Filters)          (Filters)      (Filters)      (Filters)
   
   Matplotlib         Matplotlib         Matplotlib     Matplotlib     Matplotlib
   Display            Display            Display        Display        Display
```

### Key Points

1. **Single Bot Instance**: One `bot.py` process handles all 20 symbols
   - Fetches all prices from Polygon API
   - Runs strategy logic on all symbols
   - Executes orders via Trading212 for all symbols
   - Broadcasts all updates via WebSocket

2. **Multiple Dashboard Instances**: 5 independent `multi_symbol_dashboard.py` processes
   - Each connects to same WebSocket server
   - Each **filters/subscribes** to only its assigned 4 symbols
   - Each displays its symbols independently
   - Runs on different ports (8000-8004)

3. **No Interference**: Dashboards are completely independent
   - If Dashboard 2 crashes → Dashboards 1, 3, 4, 5 keep running
   - If Dashboard 1 loses connection → Bot still executes trades
   - Each dashboard can be restarted without affecting others

---

## Implementation Options

### Option 1: Separate Dashboard Instances (Recommended)

**Advantages:**
- ✅ Monitor all 20 stocks simultaneously (tile 5 windows side-by-side)
- ✅ Each dashboard is isolated—crashes don't cascade
- ✅ Scales easily (add more dashboards for more symbols)
- ✅ Clean separation of concerns
- ✅ Easy to customize per-dashboard (colors, layouts, etc.)
- ✅ Pairs perfectly with Docker (scale with `docker-compose`)

**Required Changes:**
1. Create `config/dashboard_config.json`:
   ```json
   {
     "dashboards": [
       {
         "id": 1,
         "port": 8000,
         "symbols": ["AXSM", "DJT", "WULF", "ONDS"]
       },
       {
         "id": 2,
         "port": 8001,
         "symbols": ["NVDA", "TSLA", "AAPL", "MSFT"]
       },
       ...
     ]
   }
   ```

2. Modify `multi_symbol_dashboard.py`:
   - Add command-line argument: `--dashboard-id` (or read from env var)
   - Load dashboard config to get assigned symbols + port
   - Filter WebSocket messages to only process assigned symbols
   - Parametrize WebSocket connection (localhost:8000 vs 8001, etc.)

3. Create `launch_dashboards.sh`:
   ```bash
   #!/bin/bash
   # Launch all 5 dashboards
   for i in {1..5}; do
     python3 websocket_ui/multi_symbol_dashboard.py --dashboard-id $i &
   done
   wait
   ```

4. Update `restart.sh` to launch dashboards:
   ```bash
   bash launch_dashboards.sh  # Instead of single dashboard
   ```

**Effort**: ~1-2 hours

---

### Option 2: Single Dashboard with Navigation Tabs (Alternative)

**Advantages:**
- ✅ Single process (simpler deployment)
- ✅ One browser window/tab
- ✅ Less resource usage

**Disadvantages:**
- ❌ Can't see all 5 dashboards simultaneously
- ❌ Must navigate between pages (tabs/buttons)
- ❌ Not ideal for monitoring 20 stocks in real-time
- ❌ Harder to catch signals across all portfolios at once

**Not Recommended** for your use case (you want to monitor all 20 stocks together).

---

## Deployment Scenarios

### Scenario A: Multiple Instances (No Docker)

```bash
# Terminal 1: Start bot (serves all 20 symbols via WebSocket)
python3 bot.py

# Terminal 2: Start all 5 dashboards
bash launch_dashboards.sh

# Result: 5 browser windows open (ports 8000-8004)
```

**Pros**: Simple, straightforward
**Cons**: Managing 5+ terminal windows, manual restarts

---

### Scenario B: Docker Compose (Recommended)

```yaml
# docker-compose.yml
version: '3.8'
services:
  bot:
    build: .
    environment:
      - LIVE=${LIVE:-false}
      - POLYGON_API_KEY=${POLYGON_API_KEY}
      - TRADING212_API_KEY=${TRADING212_API_KEY}
    volumes:
      - ./bot:/app/bot
      - ./logs:/app/logs

  dashboard-1:
    build: .
    environment:
      - DASHBOARD_ID=1
    ports:
      - "8000:8000"
    volumes:
      - ./websocket_ui:/app/websocket_ui
      - ./config:/app/config

  dashboard-2:
    build: .
    environment:
      - DASHBOARD_ID=2
    ports:
      - "8001:8001"
    volumes:
      - ./websocket_ui:/app/websocket_ui
      - ./config:/app/config

  # ... repeat for dashboards 3, 4, 5
```

**Command:**
```bash
docker-compose up -d  # Starts bot + 5 dashboards
```

**Pros**: 
- One command to start everything
- Automatic scaling: `docker-compose up -d --scale dashboard=5`
- Reproducible across machines
- Easy to manage logs, volumes, restarts

**Cons**: Docker overhead (small learning curve)

---

## Why This Works

1. **WebSocket Broadcasting**: Your bot already sends all symbol updates via WebSocket. Each dashboard just needs to filter for its assigned symbols.

2. **Independent Execution**: Trading happens independently of dashboard display. If Dashboard 2 crashes, orders still execute.

3. **No Coordination Needed**: Dashboards don't talk to each other. They all listen to the same WebSocket and filter independently.

4. **Scalability**: Want to track 30 symbols instead of 20? Just add 2 more dashboards. No code changes needed.

5. **Resource Efficient**: Each dashboard is lightweight (Matplotlib listening to WebSocket). Modern CPUs handle 5+ instances easily.

---

## Real-Time Monitoring Experience

### With Multi-Dashboard
```
┌─────────────────────┬─────────────────────┬─────────────────────┐
│   Dashboard 1       │   Dashboard 2       │   Dashboard 3       │
│  AXSM, DJT,         │  NVDA, TSLA,        │  GOOGL, AMZN,       │
│  WULF, ONDS         │  AAPL, MSFT         │  META, NFLX         │
│  [Live Charts]      │  [Live Charts]      │  [Live Charts]      │
└─────────────────────┴─────────────────────┴─────────────────────┘
┌─────────────────────┬─────────────────────┐
│   Dashboard 4       │   Dashboard 5       │
│  AMD, INTC,         │  COIN, HOOD,        │
│  QCOM, MRVL         │  UPST, SOFI         │
│  [Live Charts]      │  [Live Charts]      │
└─────────────────────┴─────────────────────┘
```

**You can see all 20 stocks simultaneously while bot executes trades in background.**

---

## Configuration Management

### Per-Dasboard Customization
Each dashboard could have its own theme:
```json
{
  "id": 1,
  "port": 8000,
  "symbols": ["AXSM", "DJT", "WULF", "ONDS"],
  "theme": "dark",
  "update_interval_ms": 500,
  "chart_height": 4,
  "colors": ["#FF6B6B", "#4ECDC4", "#45B7D1", "#FFA07A"]
}
```

---

## Migration Path

### Phase 1 (Now): Single Instance
- Keep current setup (1 bot, 1 dashboard)
- Increase symbols in `SYMBOLS` env var as needed

### Phase 2 (Optional): Add 2nd Dashboard
- Implement dashboard config + filtering
- Test with 2 dashboards (8 symbols total)
- Verify WebSocket filtering works correctly

### Phase 3: Full 5-Dashboard Setup
- Add remaining 3 dashboards
- Test scaling and isolation
- Optimize performance if needed

### Phase 4 (Future): Docker
- Containerize everything
- Replace `restart.sh` with docker-compose
- Deploy to cloud if desired

---

## Summary

**Yes, you can absolutely monitor 20 stocks across 5 dashboards.** 

The architecture is clean because:
1. **One bot** fetches all prices and executes all trades
2. **Five dashboards** connect to the same WebSocket and filter for their symbols
3. **No synchronization needed**—each dashboard is independent
4. **Scales easily**—add dashboards without changing bot code

**Recommendation**: Implement **Option 1 (Separate Dashboard Instances)** with docker-compose later. This gives you:
- Real-time visibility of all 20 stocks
- Isolated instances (no cascading failures)
- Horizontal scaling (add more dashboards as needed)
- Cloud-deployment ready

**Effort**: 1-2 hours to implement, 30 min with Docker.
