import json
import os
from datetime import datetime

# Support both module and package import contexts
try:
    from models import Tick
except ImportError:  # Fallback when imported as part of the bot package
    from bot.models import Tick

class TickLogger:
    """Log all ticks and trades for retrospective analysis"""
    
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        # Ensure the logs directory exists
        os.makedirs(self.log_dir, exist_ok=True)
        self.tick_log_file = os.path.join(log_dir, "trading_ticks.jsonl")
        self.trade_log_file = os.path.join(log_dir, "trading_trades.jsonl")
        self.analysis_file = os.path.join(log_dir, "trading_analysis.txt")
        
        # Clear old logs
        self._clear_logs()
    
    def _clear_logs(self):
        """Clear old log files"""
        for f in [self.tick_log_file, self.trade_log_file, self.analysis_file]:
            if os.path.exists(f):
                os.remove(f)
    
    def log_tick(self, tick: Tick, event: dict):
        """
        Log each tick with strategy decision
        
        Args:
            tick: Tick data
            event: Strategy event output
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "tick_count": event["metrics"]["total_ticks"],
            "price": tick.price,
            "volume": tick.volume,
            "symbol": tick.symbol,
            "action": event["action"],
            "reason": event["reason"],
            "no_trade_reason": event.get("no_trade_reason"),
            "position_state": "OPEN" if event["metrics"]["open_positions"] > 0 else "CLOSED",
            "metrics": {
                "total_trades": event["metrics"]["total_trades"],
                "daily_pnl": event["metrics"]["daily_pnl"],
                "total_pnl": event["metrics"]["total_pnl"],
                "win_rate": event["metrics"]["win_rate"],
            }
        }

        calc = event.get("calc")
        if calc:
            entry["calc"] = calc
        
        with open(self.tick_log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    
    def log_trade(self, trade):
        """Log completed trade"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "direction": trade.direction,
            "entry_price": trade.entry_price,
            "entry_time": trade.entry_time.isoformat(),
            "exit_price": trade.exit_price,
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
            "exit_reason": trade.exit_reason,
            "pnl": trade.pnl,
            "pnl_pct": trade.pnl_pct,
            "duration_seconds": (trade.exit_time - trade.entry_time).total_seconds() if trade.exit_time else None,
        }
        
        with open(self.trade_log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    
    def generate_analysis_report(self, strategy):
        """Generate analysis report of all ticks and trades"""
        with open(self.analysis_file, "w") as f:
            f.write("=" * 80 + "\n")
            f.write("MICRO TRADING BOT - ANALYSIS REPORT\n")
            f.write("=" * 80 + "\n\n")
            
            # Summary
            f.write("SUMMARY\n")
            f.write("-" * 80 + "\n")
            f.write(f"Total Ticks: {strategy.metrics.total_ticks}\n")
            f.write(f"Total Trades: {strategy.metrics.total_trades}\n")
            f.write(f"Winning Trades: {strategy.metrics.winning_trades}\n")
            f.write(f"Losing Trades: {strategy.metrics.losing_trades}\n")
            f.write(f"Win Rate: {strategy.metrics.win_rate*100:.2f}%\n")
            f.write(f"Total P/L: ${strategy.metrics.total_pnl:.2f}\n")
            f.write(f"Daily P/L: ${strategy.metrics.daily_pnl:.2f}\n")
            f.write(f"Max Drawdown: ${strategy.metrics.max_drawdown:.2f}\n")
            f.write(f"Avg Win: ${strategy.metrics.avg_win:.3f}\n")
            f.write(f"Avg Loss: ${strategy.metrics.avg_loss:.3f}\n")
            f.write(f"Consecutive Losses: {strategy.metrics.consecutive_losses}\n\n")
            
            # Trades
            f.write("TRADES HISTORY\n")
            f.write("-" * 80 + "\n")
            for i, trade in enumerate(strategy.closed_trades, 1):
                f.write(f"\n[Trade #{i}]\n")
                f.write(f"  Direction: {trade.direction}\n")
                f.write(f"  Entry: ${trade.entry_price:.2f} @ {trade.entry_time.strftime('%H:%M:%S')}\n")
                f.write(f"  Exit: ${trade.exit_price:.2f} @ {trade.exit_time.strftime('%H:%M:%S')} ({trade.exit_reason})\n")
                f.write(f"  Duration: {(trade.exit_time - trade.entry_time).total_seconds():.1f}s\n")
                f.write(f"  P/L: ${trade.pnl:.3f} ({trade.pnl_pct*100:+.2f}%)\n")
            
            f.write("\n" + "=" * 80 + "\n")
    
    def read_recent_ticks(self, n: int = 50) -> list:
        """Read last N tick entries"""
        if not os.path.exists(self.tick_log_file):
            return []
        
        with open(self.tick_log_file, "r") as f:
            lines = f.readlines()
        
        return [json.loads(line) for line in lines[-n:]]
    
    def read_recent_trades(self, n: int = 20) -> list:
        """Read last N trade entries"""
        if not os.path.exists(self.trade_log_file):
            return []
        
        with open(self.trade_log_file, "r") as f:
            lines = f.readlines()
        
        return [json.loads(line) for line in lines[-n:]]
    
    def find_price_drop(self, start_price: float, end_price: float, threshold_pct: float = 0.01):
        """
        Find ticks in the range where price dropped and why SHORT wasn't triggered
        
        Args:
            start_price: Starting price (e.g., 170)
            end_price: Ending price (e.g., 156)
            threshold_pct: Price drop threshold (1%)
        
        Returns:
            Analysis of what happened during the drop
        """
        if not os.path.exists(self.tick_log_file):
            return None
        
        drop_pct = abs(end_price - start_price) / start_price
        
        analysis = {
            "start_price": start_price,
            "end_price": end_price,
            "drop_pct": drop_pct,
            "expected_short_trigger": drop_pct >= threshold_pct,
            "ticks_in_range": [],
            "potential_issues": [],
        }
        
        with open(self.tick_log_file, "r") as f:
            for line in f:
                tick = json.loads(line)
                price = tick["price"]
                
                # Check if tick is in the price range
                if (min(start_price, end_price) <= price <= max(start_price, end_price)):
                    analysis["ticks_in_range"].append(tick)
        
        # Analyze why SHORT wasn't triggered
        if analysis["ticks_in_range"]:
            first_tick = analysis["ticks_in_range"][0]
            
            # Check if position was already open
            if first_tick["position_state"] == "OPEN":
                analysis["potential_issues"].append(
                    "Position was already OPEN when price started dropping - can't open new SHORT"
                )
            
            # Check if action was taken
            actions = [t["action"] for t in analysis["ticks_in_range"] if t["action"]]
            if not actions:
                analysis["potential_issues"].append(
                    "No SHORT signal triggered during the drop - momentum/volume conditions not met"
                )
            
            # Check volume
            volumes = [t["volume"] for t in analysis["ticks_in_range"]]
            if volumes:
                avg_vol = sum(volumes) / len(volumes)
                analysis["potential_issues"].append(
                    f"Average volume during drop: {avg_vol:.0f} (need volume spike)"
                )
        
        return analysis
