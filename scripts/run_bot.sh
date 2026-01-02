#!/bin/bash
# Launcher for bot (new momentum bot with VWAP bias and WebSocket integration)

set -e

cd "$(dirname "$0")/.."

# Load environment
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

echo "=================================================="
echo "Starting Trading Bot (Polygon WebSocket)"
echo "=================================================="
echo "Symbols: $SYMBOLS"
echo "API Key: ${POLYGON_API_KEY:0:20}..."
echo ""

# Run bot from bot package
python3 -m bot.bot
