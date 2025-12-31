# Micro Trading Robot

A Python-based trading robot with WebSocket client/server for real-time market data consumption.

## Project Structure

```
├── websocket_server/      # Mock WebSocket server for trading events
│   └── server.py          # WebSocket server that broadcasts trading events
├── websocket_client/      # WebSocket client for consuming events
│   └── client.py          # Client that connects and receives trading data
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## Features

### WebSocket Server
- Runs on `ws://localhost:8765`
- Generates realistic mock trading events every 2 seconds
- Broadcasts events to all connected clients
- Includes multiple stock symbols (AAPL, GOOGL, MSFT, AMZN, TSLA, META, NVDA, AMD)
- Pushes events in the format:
  ```json
  {
    "request_id": "b84e24636301f19f88e0dfbf9a45ed5c",
    "results": {
      "P": 127.98,      // Last trade price
      "S": 7,           // Bid size
      "T": "AAPL",      // Symbol
      "X": 19,          // Exchange code
      "p": 127.96,      // Bid price
      "q": 83480742,    // Last quote timestamp
      "s": 1,           // Ask size
      "t": 1617827221349730300,  // Last trade timestamp
      "x": 11,          // Exchange code for trade
      "y": 1617827221349366000,  // Quote timestamp
      "z": 3            // Tape
    },
    "status": "OK"
  }
  ```

### WebSocket Client
- Connects to the WebSocket server
- Receives and processes trading events in real-time
- Displays formatted event data with timestamps
- Automatic reconnection on connection loss
- Handles graceful disconnection

## Installation

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Running the Server

Start the WebSocket server in one terminal:
```bash
python websocket_server/server.py
```

You should see output like:
```
============================================================
WebSocket Trading Server Started
============================================================
Server running on ws://localhost:8765
Waiting for clients to connect...
============================================================
```

### Running the Client

In another terminal, start the WebSocket client:
```bash
python websocket_client/client.py
```

The client will connect and start receiving trading events:
```
============================================================
WebSocket Trading Client Connected
============================================================
Connected to ws://localhost:8765
============================================================

[Trading Event Received at 14:23:45.123]
  Request ID: b84e24636301f19f8...
  Status: OK
  Symbol: AAPL
  Last Price: $145.67
  Bid Price: $145.65
  ...
```

## Development Notes

- The server generates new trading events every 2 seconds
- All timestamps are in nanoseconds for precision
- The client automatically reconnects if the connection drops
- Press `Ctrl+C` to stop the client or server gracefully

## Future Integration

Once the real WebSocket server is available and cost is no longer a concern, you can:
1. Update the `uri` in `websocket_client/client.py` to point to the production server
2. Adjust event processing logic as needed for the real API response format
3. Add authentication/API key handling as required by the production server
