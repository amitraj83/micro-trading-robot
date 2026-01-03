#!/bin/bash

# Simple stop script to halt all trading services.
# Mirrors the stop phase of restart.sh without starting anything.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo -e "${YELLOW}=== Micro Trading Bot - Stop Script ===${NC}"

echo -e "${YELLOW}[1/2] Stopping processes...${NC}"
# Graceful kills for known processes
pkill -f "websocket|dashboard|historical_data" 2>/dev/null
pkill -f "python3 websocket_server/server.py" 2>/dev/null
pkill -f "python3 websocket_ui/trading_dashboard.py" 2>/dev/null
pkill -f "python3 websocket_client/client.py" 2>/dev/null
pkill -f "python3 websocket_server/historical_data_server.py" 2>/dev/null

# Give processes time to exit
sleep 2

# Force kill any stragglers on known ports
lsof -ti:8765 | xargs kill -9 2>/dev/null
lsof -ti:8001 | xargs kill -9 2>/dev/null

echo -e "${GREEN}✓ Services stopped${NC}"

echo -e "${YELLOW}[2/2] Optional cleanup...${NC}"
# Python cache cleanup
find "$SCRIPT_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find "$SCRIPT_DIR" -name "*.pyc" -delete 2>/dev/null

echo -e "${GREEN}✓ Cleanup done${NC}"

echo -e "${GREEN}=== Stop complete ===${NC}"
