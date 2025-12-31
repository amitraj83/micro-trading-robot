#!/bin/bash

# Kill any existing processes
pkill -f "python3.*websocket_server" 2>/dev/null
pkill -f "python3.*trading_dashboard" 2>/dev/null
sleep 2

# Release port
lsof -ti:8765 | xargs kill -9 2>/dev/null
sleep 1

# Clear old logs
rm -f /tmp/trading_*.jsonl /tmp/server.log /tmp/dashboard.log

cd /Users/ara/micro-trading-robot

# Set Python path
export PYTHONPATH=/Users/ara/micro-trading-robot:$PYTHONPATH

echo "Starting WebSocket Server..."
python3 websocket_server/server.py > /tmp/server.log 2>&1 &
SERVER_PID=$!
echo "Server PID: $SERVER_PID"
sleep 3

echo "Starting Trading Dashboard..."
python3 websocket_ui/trading_dashboard.py > /tmp/dashboard.log 2>&1 &
DASHBOARD_PID=$!
echo "Dashboard PID: $DASHBOARD_PID"
sleep 3

echo ""
echo "✅ ALL SERVICES STARTED"
echo "Server PID: $SERVER_PID"
echo "Dashboard PID: $DASHBOARD_PID"
echo ""
echo "Monitor bot:"
echo "  tail -f /tmp/dashboard.log"
echo "  tail -f /tmp/trading_ticks.jsonl"
