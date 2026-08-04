"""P2P keepalive liveness and authenticated pong deadlines."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from p2p_network import (  # noqa: E402
    CONNECTION_TIMEOUT,
    WepoP2PNode,
    WepoPeer,
)


class FakeSocket:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _peer(network: WepoP2PNode) -> WepoPeer:
    peer = object.__new__(WepoPeer)
    peer.node = network
    peer.peer_id = "keepalive-peer"
    peer.address = ("203.0.113.15", 40007)
    peer.receive_buffer = b""
    peer.partial_message_started_at = None
    peer.connected_at = 0.0
    peer.connected = True
    peer.handshake_complete = True
    peer.pending_ping_nonce = None
    peer.pending_ping_sent_at = None
    peer.last_pong = 0.0
    peer.socket = FakeSocket()
    return peer


def test_ping_deadline_requires_an_outstanding_ping():
    network = WepoP2PNode(port=22579, network_profile="test")
    peer = _peer(network)

    assert peer.enforce_connection_deadlines(10_000.0)
    assert peer.connected

    peer.pending_ping_nonce = 123
    peer.pending_ping_sent_at = 30.0
    assert peer.enforce_connection_deadlines(30.0 + CONNECTION_TIMEOUT)
    assert peer.enforce_connection_deadlines(
        30.0 + CONNECTION_TIMEOUT - 0.001
    )
    assert not peer.enforce_connection_deadlines(
        30.0 + CONNECTION_TIMEOUT + 0.001
    )
    assert not peer.connected
    assert peer.socket.closed


def test_pong_only_clears_matching_outstanding_ping():
    network = WepoP2PNode(port=22579, network_profile="test")
    peer = _peer(network)
    peer.pending_ping_nonce = 456
    peer.pending_ping_sent_at = 40.0

    network.handle_pong(peer, json.dumps({"nonce": 455}).encode())
    assert peer.pending_ping_nonce == 456
    assert peer.pending_ping_sent_at == 40.0
    assert peer.last_pong == 0.0

    network.handle_pong(peer, json.dumps({"nonce": 456}).encode())
    assert peer.pending_ping_nonce is None
    assert peer.pending_ping_sent_at is None
    assert peer.last_pong > 0.0
