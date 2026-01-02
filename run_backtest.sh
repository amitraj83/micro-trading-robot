#!/bin/bash

# Historical Backtest Runner
# Usage: ./run_backtest.sh [SYMBOLS...]
# Example: ./run_backtest.sh QQQ SPY NVDA
# Or: ./run_backtest.sh (uses default QQQ)

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "═══════════════════════════════════════════════════════════════════════════════"
echo "  HISTORICAL BACKTEST RUNNER"
echo "═══════════════════════════════════════════════════════════════════════════════"

# Get symbols from command line or use defaults
SYMBOLS="${@:-QQQ}"

echo ""
echo "📊 Backtest Configuration:"
echo "   Symbols: $SYMBOLS"
echo "   Data source: Yahoo Finance (1-minute bars)"
echo "   Period: Last 7 days of real market data"
echo ""
echo "🤖 Bot Configuration:"
echo "   Strategy: Compression → Expansion with VWAP bias"
echo "   Entry gate: COMPRESSION state required"
echo "   Exits: Stop-loss, Target, Time exit only"
echo "   Cooldown: 30-60s per symbol after exit"
echo ""

# Clear old logs
echo "🧹 Clearing old logs..."
rm -f logs/trading_ticks.jsonl
rm -f logs/*.log 2>/dev/null || true

echo ""
echo "═══════════════════════════════════════════════════════════════════════════════"
echo "🚀 STARTING BACKTEST"
echo "═══════════════════════════════════════════════════════════════════════════════"
echo ""

# Run backtest
python3 -m bot.historical_backtest $SYMBOLS

echo ""
echo "═══════════════════════════════════════════════════════════════════════════════"
echo "📊 BACKTEST RESULTS"
echo "═══════════════════════════════════════════════════════════════════════════════"
echo ""

# Show trade summary if log exists
if [ -f "logs/trading_ticks.jsonl" ]; then
    TOTAL_LINES=$(wc -l < logs/trading_ticks.jsonl)
    OPEN_TRADES=$(grep -c '"action": "OPEN"' logs/trading_ticks.jsonl || true)
    CLOSE_TRADES=$(grep -c '"action": "CLOSE"' logs/trading_ticks.jsonl || true)
    WIN_TRADES=$(grep -c '"daily_pnl": .*[1-9]' logs/trading_ticks.jsonl | head -1 || echo "?")
    
    echo "📈 Trade Statistics:"
    echo "   Total log entries: $TOTAL_LINES"
    echo "   OPEN actions: $((OPEN_TRADES / 11))  (÷11 symbols)"
    echo "   CLOSE actions: $((CLOSE_TRADES / 11))"
    echo ""
    echo "📊 Last 5 trades:"
    echo ""
    grep '"action": "OPEN"\|"action": "CLOSE"' logs/trading_ticks.jsonl | tail -10 | python3 -m json.tool 2>/dev/null | head -50 || true
    echo ""
    echo "💾 Full log saved to: logs/trading_ticks.jsonl"
else
    echo "⚠️  No trades executed (logs/trading_ticks.jsonl not found)"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════════════════"
