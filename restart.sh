#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Micro Trading Bot - Restart Script ===${NC}"
echo ""

# Step 1: Stop all processes
echo -e "${YELLOW}[1/3] Stopping all processes...${NC}"
pkill -f "python3 websocket_server/server.py" 2>/dev/null
pkill -f "python3 websocket_ui/trading_dashboard.py" 2>/dev/null
pkill -f "python3 websocket_client/client.py" 2>/dev/null

# Give processes time to shutdown gracefully
sleep 2

# Force kill any remaining Python processes on port 8765
lsof -ti:8765 | xargs kill -9 2>/dev/null

echo -e "${GREEN}✓ All processes stopped${NC}"
echo ""

# Step 2: Wait before restarting
echo -e "${YELLOW}[2/3] Waiting 2 seconds before restart...${NC}"
sleep 2

# Step 3: Start server
echo -e "${YELLOW}[3/3] Starting services...${NC}"
echo ""

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# Start WebSocket server in background
echo -e "${GREEN}Starting WebSocket Server...${NC}"
cd "$SCRIPT_DIR"
python3 websocket_server/server.py > "$LOG_DIR/websocket_server.log" 2>&1 &
SERVER_PID=$!
echo -e "${GREEN}✓ Server started (PID: $SERVER_PID)${NC}"

# Wait for server to start
sleep 2

# Start trading dashboard
echo -e "${GREEN}Starting Trading Dashboard...${NC}"
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
python3 websocket_ui/trading_dashboard.py > "$LOG_DIR/trading_dashboard.log" 2>&1 &
DASHBOARD_PID=$!
echo -e "${GREEN}✓ Dashboard started (PID: $DASHBOARD_PID)${NC}"

echo ""
echo -e "${GREEN}=== All services started successfully ===${NC}"
echo ""
echo -e "${YELLOW}Running services:${NC}"
echo "  • WebSocket Server (PID: $SERVER_PID) - ws://localhost:8765"
echo "  • Trading Dashboard (PID: $DASHBOARD_PID) - Watch your terminal"
echo ""
echo -e "${YELLOW}Logs available at:${NC}"
echo "  • Server: $LOG_DIR/websocket_server.log"
echo "  • Dashboard: $LOG_DIR/trading_dashboard.log"
echo ""
echo -e "${YELLOW}To stop all services:${NC}"
echo "  • Press Ctrl+C in any terminal"
echo "  • Or run: pkill -f 'python3 websocket'"
echo ""
