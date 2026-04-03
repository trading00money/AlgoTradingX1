"""
MT5 ZMQ Bridge — connection diagnostic.
Run with: python tests/check_mt5_connection.py
"""
import json
import sys
import zmq

EA_HOST    = "localhost"
CMD_PORT   = 32768
DATA_PORT  = 32769
TIMEOUT_MS = 3000


def section(title):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print('='*50)


def ok(msg):  print(f"  [OK]   {msg}")
def fail(msg): print(f"  [FAIL] {msg}")
def info(msg): print(f"  [INFO] {msg}")


def main():
    section("1. ZMQ library")
    try:
        import zmq
        ok(f"pyzmq {zmq.__version__} installed")
    except ImportError:
        fail("pyzmq not installed — run: pip install pyzmq")
        sys.exit(1)

    section("2. REP socket reachable (port 32768)")
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, TIMEOUT_MS)
    sock.setsockopt(zmq.SNDTIMEO, TIMEOUT_MS)
    sock.setsockopt(zmq.LINGER, 0)
    sock.connect(f"tcp://{EA_HOST}:{CMD_PORT}")

    try:
        sock.send_json({"action": "PING"})
        resp = sock.recv_json()
        if resp.get("action") == "PONG":
            ok(f"PING → PONG  (timestamp={resp.get('timestamp')})")
        else:
            fail(f"Unexpected response: {resp}")
            sys.exit(1)
    except zmq.Again:
        fail(f"No response on port {CMD_PORT} after {TIMEOUT_MS}ms")
        print("\n  Checklist:")
        print("  - Is MT5 open?")
        print("  - Is GQ_ZMQ_Bridge EA attached to a chart and running?")
        print("  - Is 'Allow DLL imports' enabled in MT5 Tools → Options → Expert Advisors?")
        print("  - Is libzmq.dll in MQL5\\Libraries\\?")
        sys.exit(1)

    section("3. Account info")
    try:
        sock.send_json({"action": "GET_ACCOUNT"})
        resp = sock.recv_json()
        if resp.get("status") == "OK":
            ok(f"Login:    {resp.get('login')}")
            ok(f"Server:   {resp.get('server')}")
            ok(f"Balance:  {resp.get('balance')} {resp.get('currency')}")
            ok(f"Equity:   {resp.get('equity')}")
            ok(f"Leverage: 1:{resp.get('leverage')}")
        else:
            fail(f"GET_ACCOUNT failed: {resp}")
    except zmq.Again:
        fail("Timeout on GET_ACCOUNT")

    section("4. Price feed — GOLD")
    try:
        sock.send_json({"action": "GET_PRICE", "symbol": "GOLD"})
        resp = sock.recv_json()
        if resp.get("status") == "OK":
            ok(f"Bid: {resp.get('bid')}  Ask: {resp.get('ask')}  Time: {resp.get('time')}")
        else:
            fail(f"GET_PRICE failed: {resp.get('message')}")
            info("GOLD may not be in Market Watch — right-click → Show Symbol")
    except zmq.Again:
        fail("Timeout on GET_PRICE")

    section("5. History — GOLD H1 x10 bars")
    try:
        sock.send_json({"action": "GET_HISTORY", "symbol": "GOLD", "timeframe": "H1", "bars": "10"})
        resp = sock.recv_json()
        if resp.get("status") == "OK":
            bars = resp.get("data", [])
            ok(f"Received {len(bars)} bars")
            if bars:
                b = bars[-1]
                ok(f"Latest bar → time={b['time']}  O={b['open']}  H={b['high']}  L={b['low']}  C={b['close']}")
        else:
            fail(f"GET_HISTORY failed: {resp.get('message')}")
            info("Check that GOLD history is loaded in MT5 (open a chart first)")
    except zmq.Again:
        fail("Timeout on GET_HISTORY")

    section("6. PUB socket — listening for 1 message (port 32769)")
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.RCVTIMEO, 6000)   # heartbeat is every 5s by default
    sub.setsockopt(zmq.LINGER, 0)
    sub.setsockopt_string(zmq.SUBSCRIBE, "")
    sub.connect(f"tcp://{EA_HOST}:{DATA_PORT}")
    try:
        raw = sub.recv_string()
        msg = json.loads(raw)
        ok(f"Received '{msg.get('type')}' message: {raw[:120]}")
    except zmq.Again:
        fail(f"No message on port {DATA_PORT} within 6s")
        info("Check InpStreamTicks and InpHeartbeatSec EA inputs")
    finally:
        sub.close()

    sock.close()
    ctx.term()

    section("Result")
    ok("MT5 ZMQ bridge is connected and working.")
    print()


if __name__ == "__main__":
    main()
