"""
Tests for GQ_ZMQ_Bridge EA connection.
Requires the EA to be running in MT5 on ports 32768 (REP) and 32769 (PUB).
Run with: pytest tests/test_EA.py -v
"""
import json
import pytest
import zmq

EA_HOST        = "localhost"
CMD_PORT       = 32768
DATA_PORT      = 32769
RECV_TIMEOUT   = 3000   # ms — fail fast if EA not responding


@pytest.fixture(scope="function")
def cmd_socket():
    """REQ socket connected to EA's REP command port."""
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, RECV_TIMEOUT)
    sock.setsockopt(zmq.SNDTIMEO, RECV_TIMEOUT)
    sock.connect(f"tcp://{EA_HOST}:{CMD_PORT}")
    yield sock
    sock.close()
    ctx.term()


@pytest.fixture(scope="function")
def sub_socket():
    """SUB socket connected to EA's PUB data port."""
    ctx = zmq.Context()
    sock = ctx.socket(zmq.SUB)
    sock.setsockopt(zmq.RCVTIMEO, RECV_TIMEOUT)
    sock.setsockopt_string(zmq.SUBSCRIBE, "")
    sock.connect(f"tcp://{EA_HOST}:{DATA_PORT}")
    yield sock
    sock.close()
    ctx.term()


def send_command(sock, payload: dict) -> dict:
    sock.send_json(payload)
    raw = sock.recv_json()
    return raw if isinstance(raw, dict) else json.loads(raw)


# ---------------------------------------------------------------------------
# Command socket tests
# ---------------------------------------------------------------------------

def test_ping(cmd_socket):
    """EA must respond to PING with PONG."""
    resp = send_command(cmd_socket, {"action": "PING"})
    assert resp["status"] == "OK", f"Bad status: {resp}"
    assert resp["action"] == "PONG", f"Expected PONG, got: {resp}"
    assert "timestamp" in resp


def test_get_account(cmd_socket):
    """EA must return valid account info."""
    resp = send_command(cmd_socket, {"action": "GET_ACCOUNT"})
    assert resp["status"] == "OK", f"Bad status: {resp}"
    for key in ("login", "balance", "equity", "currency", "leverage"):
        assert key in resp, f"Missing key '{key}' in account response"
    assert resp["balance"] >= 0
    assert resp["leverage"] > 0


def test_get_price_valid_symbol(cmd_socket):
    """EA must return bid/ask for a known symbol."""
    resp = send_command(cmd_socket, {"action": "GET_PRICE", "symbol": "EURUSD"})
    assert resp["status"] == "OK", f"Bad status: {resp}"
    assert resp["bid"] > 0
    assert resp["ask"] > 0
    assert resp["ask"] >= resp["bid"]


def test_get_price_invalid_symbol(cmd_socket):
    """EA must return ERROR for a non-existent symbol."""
    resp = send_command(cmd_socket, {"action": "GET_PRICE", "symbol": "FAKEPAIR"})
    assert resp["status"] == "ERROR"


def test_get_history(cmd_socket):
    """EA must return OHLCV bars for a valid symbol."""
    resp = send_command(cmd_socket, {
        "action":    "GET_HISTORY",
        "symbol":    "EURUSD",
        "timeframe": "H1",
        "bars":      "10",
    })
    assert resp["status"] == "OK", f"Bad status: {resp}"
    assert "data" in resp
    bars = resp["data"]
    assert len(bars) > 0, "Expected at least one bar"
    bar = bars[0]
    for key in ("time", "open", "high", "low", "close", "volume"):
        assert key in bar, f"Missing key '{key}' in bar"
    assert bar["high"] >= bar["low"]


def test_get_positions(cmd_socket):
    """EA must return a positions list (may be empty)."""
    resp = send_command(cmd_socket, {"action": "GET_POSITIONS"})
    assert resp["status"] == "OK", f"Bad status: {resp}"
    assert "positions" in resp
    assert isinstance(resp["positions"], list)


def test_unknown_action(cmd_socket):
    """EA must return ERROR for an unknown action."""
    resp = send_command(cmd_socket, {"action": "INVALID_ACTION_XYZ"})
    assert resp["status"] == "ERROR"


# ---------------------------------------------------------------------------
# PUB socket test
# ---------------------------------------------------------------------------

def test_pub_receives_message(sub_socket):
    """EA must publish at least one message (tick or heartbeat) within timeout."""
    try:
        raw = sub_socket.recv_string()
        msg = json.loads(raw)
        assert "type" in msg, f"Published message missing 'type': {msg}"
        assert msg["type"] in ("TICK", "HEARTBEAT", "POSITION_UPDATE"), \
            f"Unexpected message type: {msg['type']}"
    except zmq.Again:
        pytest.fail(
            f"No message received on PUB port {DATA_PORT} within {RECV_TIMEOUT}ms. "
            "Check InpStreamTicks and InpHeartbeatSec EA settings."
        )
