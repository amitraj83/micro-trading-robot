# Bot package - v2 architecture (async momentum trading)
from bot.bot import (
    SymbolState,
    states,
    handle_bar,
    websocket_loop,
    log_trade,
)

__version__ = "2.0.0"
__all__ = [
    "SymbolState",
    "states",
    "handle_bar",
    "websocket_loop",
    "log_trade",
]
