import asyncio
import json
import websockets
from datetime import datetime


async def connect_to_server():
    """Connect to the WebSocket server and consume events"""
    uri = "ws://localhost:8765"
    
    try:
        async with websockets.connect(uri) as websocket:
            print("=" * 60)
            print("WebSocket Trading Client Connected")
            print("=" * 60)
            print(f"Connected to {uri}")
            print("=" * 60)
            
            # Receive messages from the server
            async for message in websocket:
                try:
                    data = json.loads(message)

                    # Connection status handshake
                    if "status" in data and data["status"] == "connected" and "ticker" not in data:
                        print(f"\n[Server Message] {data.get('message', 'Connected')}")
                        continue

                    # Raw Polygon snapshot payload
                    if "ticker" in data:
                        ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                        ticker = data.get("ticker", {})
                        day = ticker.get("day", {})
                        minute = ticker.get("min", {})
                        prev = ticker.get("prevDay", {})
                        print(f"\n[Snapshot @ {ts}]")
                        print(f"  Symbol: {ticker.get('ticker', 'N/A')}")
                        print(f"  Change: {ticker.get('todaysChange', 'N/A')} ({ticker.get('todaysChangePerc', 'N/A')})")
                        print(f"  Last price (day close): {day.get('c', 'N/A')}")
                        print(f"  Day O/H/L/C: {day.get('o','N/A')} / {day.get('h','N/A')} / {day.get('l','N/A')} / {day.get('c','N/A')}")
                        print(f"  Day VWAP/Vol: {day.get('vw','N/A')} / {day.get('v','N/A')}")
                        print(f"  Min O/H/L/C: {minute.get('o','N/A')} / {minute.get('h','N/A')} / {minute.get('l','N/A')} / {minute.get('c','N/A')} (vol {minute.get('v','N/A')}, trades {minute.get('n','N/A')})")
                        print(f"  Prev Day Close: {prev.get('c','N/A')} (O/H/L: {prev.get('o','N/A')} / {prev.get('h','N/A')} / {prev.get('l','N/A')})")
                        continue

                    # Echo responses
                    if "echo" in data:
                        print(f"\n[Echo Response] {data['echo']}")

                except json.JSONDecodeError:
                    print(f"[!] Failed to parse message: {message}")
                except Exception as e:
                    print(f"[!] Error processing message: {e}")
    
    except ConnectionRefusedError:
        print("=" * 60)
        print("[✗] Connection Failed")
        print("=" * 60)
        print(f"Could not connect to {uri}")
        print("Make sure the server is running on localhost:8765")
        print("\nTo start the server, run:")
        print("  python websocket_server/server.py")
        print("=" * 60)
    
    except KeyboardInterrupt:
        print("\n\n[✓] Client disconnected by user")
    
    except Exception as e:
        print(f"[!] Unexpected error: {e}")


async def main():
    """Main entry point for the client"""
    while True:
        try:
            await connect_to_server()
            break
        except Exception as e:
            print(f"[!] Connection error: {e}")
            print("Attempting to reconnect in 5 seconds...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
