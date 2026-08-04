"""Live-socket integration coverage for the WEPO P2P transport."""

from __future__ import annotations

import os
import socket
import struct
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from p2p_network import MAX_MESSAGE_SIZE, WepoP2PNode  # noqa: E402


def _reserve_loopback_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


@pytest.mark.parametrize("_iteration", range(5))
def test_two_node_handshake_transaction_and_hostile_frame(_iteration):
    old_static = os.environ.get("WEPO_STATIC_PEERS")
    old_dns = os.environ.get("WEPO_DNS_SEEDS")
    old_required = os.environ.get("WEPO_REQUIRE_MAINNET_SEEDS")
    os.environ["WEPO_STATIC_PEERS"] = "off"
    os.environ["WEPO_DNS_SEEDS"] = "off"
    os.environ.pop("WEPO_REQUIRE_MAINNET_SEEDS", None)

    node_a = None
    node_b = None
    try:
        port_a = _reserve_loopback_port()
        port_b = _reserve_loopback_port()
        while port_b == port_a:
            port_b = _reserve_loopback_port()

        node_a = WepoP2PNode(
            host="127.0.0.1",
            port=port_a,
            network_profile="test",
        )
        node_b = WepoP2PNode(
            host="127.0.0.1",
            port=port_b,
            network_profile="test",
        )
        node_a.start_server()
        node_b.start_server()

        assert node_a.running and node_b.running
        assert node_a.connect_to_peer("127.0.0.1", port_b)
        assert _wait_until(
            lambda: any(peer.is_connected() for peer in node_a.peers.values())
            and any(peer.is_connected() for peer in node_b.peers.values())
        )

        received = []
        relayed = []
        node_b.on_new_transaction = (
            lambda payload: received.append(payload) is None
        )
        node_b.fluff_transaction = (
            lambda payload, exclude_peer_id=None: relayed.append(
                (payload, exclude_peer_id)
            )
        )

        envelope = {"txid": "11" * 32, "tx_data": {}}
        outbound_peer = next(
            peer for peer in node_a.peers.values() if peer.is_connected()
        )
        outbound_peer.send_raw(node_a.create_transaction_message(envelope))

        assert _wait_until(lambda: received == [envelope])
        assert len(relayed) == 1
        assert relayed[0][0] == envelope

        hostile_header = struct.pack(
            "<4s12sI4s",
            node_a.network_magic,
            b"tx".ljust(12, b"\x00"),
            MAX_MESSAGE_SIZE + 1,
            b"\x00" * 4,
        )
        outbound_peer.send_raw(hostile_header)

        assert _wait_until(lambda: node_b.is_host_banned("127.0.0.1"))
        assert _wait_until(
            lambda: not any(
                peer.is_connected() for peer in node_b.peers.values()
            )
        )
    finally:
        if node_a is not None:
            node_a.stop_server()
        if node_b is not None:
            node_b.stop_server()
        if old_static is None:
            os.environ.pop("WEPO_STATIC_PEERS", None)
        else:
            os.environ["WEPO_STATIC_PEERS"] = old_static
        if old_dns is None:
            os.environ.pop("WEPO_DNS_SEEDS", None)
        else:
            os.environ["WEPO_DNS_SEEDS"] = old_dns
        if old_required is None:
            os.environ.pop("WEPO_REQUIRE_MAINNET_SEEDS", None)
        else:
            os.environ["WEPO_REQUIRE_MAINNET_SEEDS"] = old_required
