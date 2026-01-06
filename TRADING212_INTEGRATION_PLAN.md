# Trading212 Integration Plan: Open & Close Position Signals

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ RUNNER (runner.py)                                              │
│ ├─ Receives market ticks from WebSocket                         │
│ └─ Calls: strategy.process_tick(tick)                           │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 │ event = {
                 │   "action": "OPEN" or "CLOSE" or None,
                 │   "trade": Trade object,
                 │   "reason": exit reason,
                 │   ...
                 │ }
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ STRATEGY (strategy.py)                                          │
│ ├─ process_tick() generates OPEN/CLOSE signals                  │
│ └─ Returns event dict with action                               │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 │ NEW: Check event["action"]
                 │
    ┌────────────┴────────────┐
    │                         │
    ▼                         ▼
 "OPEN"                   "CLOSE"
    │                         │
    ▼                         ▼
┌──────────────────┐   ┌──────────────────┐
│ BROKER.          │   │ BROKER.          │
│ execute_open()   │   │ execute_close()  │
│                  │   │                  │
│ ✓ Create BUY     │   │ ✓ Sell position  │
│ ✓ Track order    │   │ ✓ Update state   │
│ ✓ Confirm filled │   │ ✓ Record PnL     │
└────────┬─────────┘   └────────┬─────────┘
         │                      │
         ▼                      ▼
    ┌──────────────────────────────────┐
    │ TRADING212 API                   │
    │ (trading212_api.py)              │
    │                                  │
    │ POST /equity/orders              │
    │ DELETE /equity/positions/{id}    │
    └──────────────────────────────────┘
         │                      │
         ▼                      ▼
    REAL TRADING212            REAL TRADING212
    BUY ORDER EXECUTED         POSITION CLOSED
```

---

## Step-by-Step Integration Flow

### **1. Generate Signal in `process_tick()` (Already Happening)**

**File:** `bot/strategy.py`, line ~1420

```python
def process_tick(self, tick: Tick) -> dict:
    event = {
        "action": None,          # ← We'll set to "OPEN" or "CLOSE"
        "trade": None,           # ← Trade object
        "reason": None,          # ← Why we're opening/closing
        ...
    }
    
    # EXIT: Check for close signals
    if tick.symbol in self.current_positions:
        exit_reason = self.check_exit_signals(tick.symbol, tick.price)
        if exit_reason:
            self._close_position(tick.symbol, tick.price, exit_reason)
            event["action"] = "CLOSE"      # ← Signal generated here
            event["trade"] = trade_to_close
            event["reason"] = exit_reason
    
    # ENTRY: Check for open signals  
    else:
        entry_signal = self.check_entry_signals(tick.symbol, buf)
        if entry_signal:
            quantity = self._compute_position_size(entry_price=tick.price)
            self._open_position(tick.symbol, tick.price, quantity, entry_signal)
            event["action"] = "OPEN"       # ← Signal generated here
            event["trade"] = new_trade
            event["reason"] = entry_signal
    
    return event
```

---

### **2. Intercept Signal in Runner and Execute**

**File:** `bot/runner.py`, line ~180

Currently, the runner just logs the event. **We'll add Trading212 execution:**

```python
# In the tick processing loop:
event = _bot_client.strategy.process_tick(tick)

# NEW: Execute on Trading212 if signal generated
if event.get("action"):
    action = event["action"]
    trade = event.get("trade")
    symbol = tick.symbol
    
    if action == "OPEN":
        # Execute OPEN trade on Trading212
        success = await _bot_client.broker.execute_open_trade(
            symbol=symbol,
            entry_price=tick.price,
            quantity=trade.quantity,
            order_type="MARKET"  # Market order for fastest execution
        )
        if success:
            logger.info(f"✅ OPEN: {symbol} {trade.quantity} shares @ ${tick.price:.2f}")
        else:
            logger.error(f"❌ OPEN FAILED: {symbol}")
    
    elif action == "CLOSE":
        # Execute CLOSE trade on Trading212
        success = await _bot_client.broker.execute_close_trade(
            symbol=symbol,
            exit_price=tick.price,
            close_reason=event.get("reason")
        )
        if success:
            logger.info(f"✅ CLOSE: {symbol} @ ${tick.price:.2f} | PnL: {trade.pnl:+.2f}%")
        else:
            logger.error(f"❌ CLOSE FAILED: {symbol}")
```

---

### **3. Implement Trading212 Execution Methods**

**File:** `bot/trading212_broker.py`

#### **A. Execute Open Trade**

```python
async def execute_open_trade(
    self, 
    symbol: str, 
    entry_price: float, 
    quantity: float,
    order_type: str = "MARKET"
) -> bool:
    """
    Create a BUY order on Trading212.
    
    Process:
    1. Create market BUY order for (quantity) shares
    2. Wait for order confirmation (1-5 seconds typical)
    3. If filled: Store order_id and position_id
    4. If rejected: Log error and return False
    5. Track position in self.positions dict
    """
    
    if not self.enabled:
        logger.warning(f"⚠️  Trading212 broker disabled")
        return False
    
    # Ensure API client initialized
    await self.init_client()
    
    # Check: Don't open if already have position for this symbol
    if symbol in self.positions:
        logger.warning(f"⚠️  Position already exists for {symbol}")
        return False
    
    try:
        # Call Trading212 API to create BUY order
        order_response = await self.client.create_buy_order(
            symbol=symbol,
            quantity=quantity,
            order_type=order_type  # MARKET for immediate execution
        )
        
        # Check for errors
        if order_response.get("error"):
            error_msg = order_response.get("error")
            logger.error(f"❌ BUY order failed for {symbol}: {error_msg}")
            
            # Track failed position for debugging
            self.positions[symbol] = BotPosition(
                symbol=symbol,
                entry_price=entry_price,
                entry_time=datetime.now(),
                quantity=quantity,
                status="ERROR",
                error_message=error_msg
            )
            return False
        
        # Extract order details from response
        order_id = order_response.get("orderId")
        position_id = order_response.get("positionId")
        filled_qty = order_response.get("filledQuantity", quantity)
        filled_price = order_response.get("filledPrice", entry_price)
        
        # Create position tracking record
        self.positions[symbol] = BotPosition(
            symbol=symbol,
            entry_price=filled_price,
            entry_time=datetime.now(),
            quantity=filled_qty,
            direction="LONG",
            trading212_order_id=order_id,
            trading212_position_id=position_id,
            status="OPEN"  # ← Position is now OPEN on Trading212
        )
        
        logger.info(f"✅ BUY order created: {symbol} {filled_qty} @ ${filled_price:.2f} (Order: {order_id})")
        return True
        
    except Exception as e:
        logger.error(f"❌ Exception opening trade {symbol}: {e}")
        return False
```

#### **B. Execute Close Trade**

```python
async def execute_close_trade(
    self,
    symbol: str,
    exit_price: float,
    close_reason: str = "Signal"
) -> bool:
    """
    Close an open position on Trading212 by selling all shares.
    
    Process:
    1. Find position record for symbol
    2. Create SELL order for entire quantity
    3. Wait for fill confirmation
    4. Update position status to CLOSED
    5. Calculate and record P&L
    """
    
    if not self.enabled:
        logger.warning(f"⚠️  Trading212 broker disabled")
        return False
    
    # Check: Position must exist
    if symbol not in self.positions:
        logger.warning(f"⚠️  No position found for {symbol}")
        return False
    
    position = self.positions[symbol]
    
    # Skip if already closed
    if position.status == "CLOSED":
        logger.warning(f"⚠️  Position already closed for {symbol}")
        return False
    
    try:
        # Call Trading212 API to create SELL order
        close_response = await self.client.create_sell_order(
            symbol=symbol,
            quantity=position.quantity,
            order_type="MARKET"
        )
        
        # Check for errors
        if close_response.get("error"):
            error_msg = close_response.get("error")
            logger.error(f"❌ SELL order failed for {symbol}: {error_msg}")
            position.status = "ERROR"
            position.error_message = error_msg
            return False
        
        # Extract close details
        close_order_id = close_response.get("orderId")
        filled_qty = close_response.get("filledQuantity", position.quantity)
        filled_price = close_response.get("filledPrice", exit_price)
        
        # Update position with close info
        position.close_price = filled_price
        position.close_time = datetime.now()
        position.close_reason = close_reason
        position.status = "CLOSED"
        
        # Calculate P&L
        pnl_dollars = (filled_price - position.entry_price) * position.quantity
        pnl_percent = ((filled_price - position.entry_price) / position.entry_price) * 100
        
        logger.info(
            f"✅ SELL order executed: {symbol} {filled_qty} @ ${filled_price:.2f} "
            f"(Order: {close_order_id}) | PnL: ${pnl_dollars:+.2f} ({pnl_percent:+.2f}%)"
        )
        return True
        
    except Exception as e:
        logger.error(f"❌ Exception closing trade {symbol}: {e}")
        position.status = "ERROR"
        position.error_message = str(e)
        return False
```

---

### **4. Create Trading212 API Endpoint Calls**

**File:** `bot/trading212_api.py` (already exists)

Need these two methods:

```python
class Trading212Client:
    
    async def create_buy_order(
        self, 
        symbol: str, 
        quantity: float,
        order_type: str = "MARKET"
    ) -> dict:
        """
        POST /equity/orders
        {
            "type": "BUY",
            "instrumentCode": symbol,
            "quantity": quantity,
            "timeInForce": "Day",  # or GTC (Good Till Cancel)
            "assetType": "Equity"
        }
        """
        endpoint = "/equity/orders"
        payload = {
            "type": "BUY",
            "instrumentCode": symbol,
            "quantity": quantity,
            "timeInForce": "Day",
            "assetType": "Equity"
        }
        
        response = await self._request("POST", endpoint, json=payload)
        return response
    
    async def create_sell_order(
        self,
        symbol: str,
        quantity: float,
        order_type: str = "MARKET"
    ) -> dict:
        """
        POST /equity/orders
        {
            "type": "SELL",
            "instrumentCode": symbol,
            "quantity": quantity,
            "timeInForce": "Day"
        }
        """
        endpoint = "/equity/orders"
        payload = {
            "type": "SELL",
            "instrumentCode": symbol,
            "quantity": quantity,
            "timeInForce": "Day",
            "assetType": "Equity"
        }
        
        response = await self._request("POST", endpoint, json=payload)
        return response
    
    async def get_open_positions(self) -> dict:
        """
        GET /equity/positions
        Returns all open positions for verification
        """
        endpoint = "/equity/positions"
        response = await self._request("GET", endpoint)
        return response
```

---

## Data Flow Diagram

### When Bot Generates "OPEN" Signal:

```
1. Strategy detects entry condition (EMA cross, price at support, etc.)
   └─> process_tick() returns: event["action"] = "OPEN"

2. Runner sees action == "OPEN"
   └─> Calls: broker.execute_open_trade(symbol, price, qty)

3. Broker prepares order:
   └─> quantity = bot's position size (e.g., 5 shares)
   └─> order_type = "MARKET" (fastest execution)

4. Trading212 API receives BUY order
   └─> API creates order on Trading212 server
   └─> Order matched with seller (market liquidity)
   └─> Order fills at market price

5. API response returned to broker:
   └─> Contains: orderId, positionId, filledQty, filledPrice

6. Broker stores position tracking:
   └─> self.positions[symbol] = BotPosition(...)
   └─> status = "OPEN"

7. Runner logs success:
   └─> "✅ OPEN: BTC 5 shares @ $45,230.50 (Order: 12345)"

8. Next tick: Runner monitors exit signals
   └─> When exit condition met → action = "CLOSE"
```

### When Bot Generates "CLOSE" Signal:

```
1. Strategy detects exit condition (trailing stop, time decay, reverse signal)
   └─> process_tick() returns: event["action"] = "CLOSE"

2. Runner sees action == "CLOSE"
   └─> Calls: broker.execute_close_trade(symbol, exit_price)

3. Broker looks up open position:
   └─> position = self.positions[symbol]
   └─> quantity = position.quantity (5 shares)

4. Broker creates SELL order:
   └─> Same quantity as OPEN trade
   └─> Market order for immediate execution

5. Trading212 API executes SELL:
   └─> Matches with buyer
   └─> Fills at market price
   └─> Position closed

6. Response includes:
   └─> filledPrice (e.g., $45,340.50)
   └─> Implies P&L = (45,340.50 - 45,230.50) × 5 = $550

7. Broker updates position:
   └─> status = "CLOSED"
   └─> close_price = 45,340.50
   └─> close_time = now
   └─> close_reason = "Time decay exit"

8. Runner logs:
   └─> "✅ CLOSE: BTC 5 @ $45,340.50 | PnL: +$550.00 (+0.24%)"

9. Position removed from active tracking
   └─> Next tick can open new position for same symbol
```

---

## Error Handling

### Case 1: Order Rejected (Insufficient Cash)
```
Trading212 returns: {"error": "Insufficient cash in account"}
→ Broker logs error and returns False
→ Position marked with status="ERROR"
→ Strategy continues (doesn't crash)
→ Next tick can retry
```

### Case 2: API Timeout
```
API call exceeds 10 second timeout
→ Exception caught in try/except
→ Position marked with status="ERROR"
→ Error logged: "Exception opening trade BTC: Connection timeout"
→ Retry on next signal
```

### Case 3: Symbol Already Has Open Position
```
Runner tries to open BTC when already has open BTC position
→ Broker checks: if symbol in self.positions
→ Returns False, logs warning
→ Prevents double-opening same symbol
```

### Case 4: Try to Close Non-Existent Position
```
Close signal for XYZ but XYZ not in self.positions
→ Broker logs warning and returns False
→ No Trading212 API call made
→ Strategy continues
```

---

## Configuration

### Risk Parameters (In `.env` or `config.py`)

```python
# Trading212 Integration
ENABLE_TRADING212_EXECUTION=true      # Master switch
TRADING212_ORDER_TYPE=MARKET          # MARKET for speed, LIMIT for control
TRADING212_ORDER_TIME_IN_FORCE=Day    # Day or GTC
TRADING212_CLOSE_ON_MARKET_HOURS=true # Auto-close at market close?
TRADING212_ALLOW_SHORTS=false         # Allow short selling?
```

---

## Testing Strategy

### Phase 1: Dry Run (No Real Trades)
```
1. Run bot with ENABLE_TRADING212_EXECUTION=false
2. Verify signals generate correctly
3. Log shows: "[DRY] Would open BTC 5 @ $45,230.50"
4. Confirm signal logic is correct
```

### Phase 2: Paper Trading (Demo Account)
```
1. Set LIVE=false in .env (uses demo.trading212.com)
2. Run bot normally
3. Verify orders actually execute on Trading212 demo account
4. Check positions appear in Trading212 dashboard
5. Run for 1-2 hours, capture several open/close cycles
```

### Phase 3: Live Trading (Real Account)
```
1. Set LIVE=true in .env (uses live.trading212.com)
2. Start with small position sizes
3. Monitor first 5-10 trades carefully
4. Check P&L matches between bot tracking and Trading212 dashboard
5. Gradually increase position sizes as confidence grows
```

---

## Implementation Checklist

- [ ] Add `execute_open_trade()` method to Trading212Broker
- [ ] Add `execute_close_trade()` method to Trading212Broker
- [ ] Add `create_buy_order()` to Trading212Client API wrapper
- [ ] Add `create_sell_order()` to Trading212Client API wrapper
- [ ] Update runner.py to call broker methods when action="OPEN"/"CLOSE"
- [ ] Add error handling and logging
- [ ] Add configuration flags
- [ ] Test with demo account
- [ ] Verify P&L calculation accuracy
- [ ] Add position sync with Trading212 to prevent stale state
- [ ] Test with live account on small sizes

---

## Benefits of This Approach

✅ **Clean separation of concerns**: Strategy logic separate from execution  
✅ **Position tracking**: Maintain state in BotPosition for reconciliation  
✅ **Error resilient**: Failed orders don't crash bot, retry next signal  
✅ **Configurable**: Easy to disable/enable Trading212 execution  
✅ **Testable**: Can dry-run signals before executing  
✅ **Auditable**: All orders logged with timestamps and prices  
✅ **Async-ready**: Non-blocking API calls for performance  

---

## Files to Modify

1. **bot/trading212_broker.py** - Add execute_open_trade() and execute_close_trade()
2. **bot/trading212_api.py** - Add create_buy_order() and create_sell_order()
3. **bot/runner.py** - Intercept signals and call broker execution
4. **bot/config.py** - Add TRADING212_EXECUTION flags
5. **.env** - Add ENABLE_TRADING212_EXECUTION flag
