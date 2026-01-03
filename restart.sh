#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Resolve script directory early so cleanup paths work
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo -e "${YELLOW}=== Micro Trading Bot - Restart Script ===${NC}"
echo ""

# Clear Python cache FIRST before running any Python scripts
echo -e "${YELLOW}[PREP] Clearing Python cache...${NC}"
find "$SCRIPT_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find "$SCRIPT_DIR" -name "*.pyc" -delete 2>/dev/null
echo -e "${GREEN}✓ Cache cleared${NC}"
echo ""

# Step 0: Update symbols from gainers (if enabled)
echo -e "${YELLOW}[0/4] Checking for symbol updates from gainers...${NC}"
python3 update_symbols_from_gainers.py
UPDATE_STATUS=$?
if [ $UPDATE_STATUS -eq 0 ]; then
    echo -e "${GREEN}✓ Symbols updated (or skipped if disabled)${NC}"
else
    echo -e "${YELLOW}⚠ Symbol update had issues, continuing with existing symbols${NC}"
fi
echo ""

# Step 1: Stop all processes and clean Python cache
echo -e "${YELLOW}[1/4] Stopping all processes and cleaning cache...${NC}"
pkill -f "websocket|dashboard|historical_data" 2>/dev/null
pkill -f "python3 websocket_server/server.py" 2>/dev/null
pkill -f "python3 websocket_ui/trading_dashboard.py" 2>/dev/null
pkill -f "python3 websocket_client/client.py" 2>/dev/null
pkill -f "python3 websocket_server/historical_data_server.py" 2>/dev/null

# Give processes time to shutdown gracefully
sleep 2

# Force kill any remaining Python processes on port 8765
lsof -ti:8765 | xargs kill -9 2>/dev/null

# Force kill any remaining Python processes on port 8001 (historical data)
lsof -ti:8001 | xargs kill -9 2>/dev/null

# Clear Python cache files
echo -e "${GREEN}  Clearing Python cache...${NC}"
find "$SCRIPT_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find "$SCRIPT_DIR" -name "*.pyc" -delete 2>/dev/null

# Clear old trading logs for fresh start
echo -e "${GREEN}  Clearing old trading logs...${NC}"
rm -f "$SCRIPT_DIR/logs/trading_ticks.jsonl" 2>/dev/null
rm -f "$SCRIPT_DIR/logs/trading_trades.jsonl" 2>/dev/null
rm -f "$SCRIPT_DIR/logs/bot_runner.log" 2>/dev/null
rm -f "$SCRIPT_DIR/logs/websocket_server.log" 2>/dev/null
rm -f "$SCRIPT_DIR/logs/trading_dashboard.log" 2>/dev/null

echo -e "${GREEN}✓ All processes stopped and cache cleaned${NC}"
echo ""

# Step 2: Wait before restarting
echo -e "${YELLOW}[2/4] Waiting 2 seconds before restart...${NC}"
sleep 2

# Step 3: Start server
echo -e "${YELLOW}[3/4] Starting services...${NC}"
echo ""

# Get the directory where the script is located (already resolved above)
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# Load environment variables to check FAKE_TICKS
set -a
source "$SCRIPT_DIR/.env"
set +a

# Ensure local packages (e.g., bot) are importable
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# Step 4: Start services based on FAKE_TICKS
echo -e "${YELLOW}[4/4] Launching server, bot, and dashboard...${NC}"

cd "$SCRIPT_DIR"

if [ "$FAKE_TICKS" = "true" ]; then
        echo -e "${YELLOW}FAKE_TICKS=true → starting historical playback server (ws://localhost:8001)...${NC}"
        python3 websocket_server/historical_data_server.py > "$LOG_DIR/historical_data_server.log" 2>&1 &
        HISTORICAL_DATA_PID=$!
        echo -e "${GREEN}✓ Historical Data server started (PID: $HISTORICAL_DATA_PID)${NC}"
        sleep 1
fi

echo -e "${GREEN}Starting WebSocket Server...${NC}"
python3 websocket_server/server.py > "$LOG_DIR/websocket_server.log" 2>&1 &
SERVER_PID=$!
echo -e "${GREEN}✓ Server started (PID: $SERVER_PID)${NC}"

sleep 2

echo -e "${GREEN}Starting Trading Bot...${NC}"
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
python3 bot/runner.py > "$LOG_DIR/bot_runner.log" 2>&1 &
BOT_PID=$!
echo -e "${GREEN}✓ Trading Bot started (PID: $BOT_PID)${NC}"

sleep 2

echo -e "${GREEN}Starting Multi-Symbol Trading Dashboard...${NC}"
python3 websocket_ui/multi_symbol_dashboard.py > "$LOG_DIR/trading_dashboard.log" 2>&1 &
DASHBOARD_PID=$!
echo -e "${GREEN}✓ Dashboard started (PID: $DASHBOARD_PID)${NC}"

echo ""
echo -e "${GREEN}=== All services started successfully ===${NC}"
echo ""
echo -e "${YELLOW}Running services:${NC}"
echo "  • WebSocket Server (PID: $SERVER_PID) - ws://localhost:8765"
echo "  • Trading Dashboard (PID: $DASHBOARD_PID) - Watch your terminal"
echo "  • Trading Bot (PID: $BOT_PID)"
if [ "$FAKE_TICKS" = "true" ]; then
    echo "  • Historical Data Server (PID: $HISTORICAL_DATA_PID) - ws://localhost:8001"
fi
echo ""
echo -e "${YELLOW}Logs available at:${NC}"
echo "  • Server: $LOG_DIR/websocket_server.log"
echo "  • Bot: $LOG_DIR/bot_runner.log"
echo "  • Dashboard: $LOG_DIR/trading_dashboard.log"
if [ "$FAKE_TICKS" = "true" ]; then
    echo "  • Historical: $LOG_DIR/historical_data_server.log"
fi
echo ""
echo -e "${YELLOW}To stop all services:${NC}"
echo "  • Press Ctrl+C in any terminal"
echo "  • Or run: pkill -f 'python3 websocket'"
echo ""
