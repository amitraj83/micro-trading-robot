#!/bin/bash

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${YELLOW}║   Micro Trading Bot - Restart & Deploy                      ║${NC}"
echo -e "${YELLOW}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Step 1: Kill all processes
echo -e "${YELLOW}[1/4] Stopping all processes...${NC}"
pkill -9 -f "websocket_server\|websocket_ui\|websocket_client" 2>/dev/null
lsof -ti:8765 | xargs kill -9 2>/dev/null
sleep 2
echo -e "${GREEN}✓ All processes stopped${NC}"
echo ""

# Step 2: Clear old logs
echo -e "${YELLOW}[2/4] Clearing old logs...${NC}"
rm -f /tmp/trading_*.jsonl /tmp/trading_*.txt /tmp/server.log /tmp/dashboard.log
echo -e "${GREEN}✓ Logs cleared${NC}"
echo ""

# Step 3: Start server
echo -e "${YELLOW}[3/4] Starting WebSocket Server on ws://localhost:8765...${NC}"
cd /Users/ara/micro-trading-robot
python3 websocket_server/server.py > /tmp/server.log 2>&1 &
SERVER_PID=$!
sleep 3
echo -e "${GREEN}✓ Server started (PID: $SERVER_PID)${NC}"
echo ""

# Step 4: Start dashboard
echo -e "${YELLOW}[4/4] Starting Trading Dashboard with improved strategy...${NC}"
export PYTHONPATH="/Users/ara/micro-trading-robot:$PYTHONPATH"
python3 websocket_ui/trading_dashboard.py > /tmp/dashboard.log 2>&1 &
DASHBOARD_PID=$!
sleep 2
echo -e "${GREEN}✓ Dashboard started (PID: $DASHBOARD_PID)${NC}"
echo ""

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ✓ BOT READY - PROFITABILITY ENHANCED                      ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}📊 IMPROVEMENTS:${NC}"
echo "  • Stricter entry conditions (0.08% momentum + 2.0x volume spike)"
echo "  • Direction confirmation (4+ consecutive moves)"
echo "  • Higher profit targets (0.25% target, 0.08% stop)"
echo "  • Graph now shows: BUY OPEN, BUY CLOSE, SELL OPEN, SELL CLOSE with IDs"
echo ""
echo -e "${YELLOW}📈 ANALYSIS:${NC}"
echo "  • View logs: python3 analyze_logs.py"
echo "  • Quick status: ./quick_logs.sh"
echo "  • Price drop analysis: python3 analyze_logs.py drop <start> <end>"
echo ""
