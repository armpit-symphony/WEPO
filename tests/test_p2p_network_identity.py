"""Live-socket separation of WEPO network framing and handshake identity."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from p2p_network import PROTOCOL_VERSION, WepoP2PNode  # noqa: E402


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def _isolated_seed_environment(monkeypatch) -> None:
    monkeypatch.setenv("WEPO_STATIC_PEERS", "off")
    monkeypatch.setenv("WEPO_DNS_SEEDS", "off")
    monkeypatch.delenv("WEPO_REQUIRE_MAINNET_SEEDS", raising=False)


def test_live_mainnet_and_testnet_nodes_reject_each_other(monkeypatch):
    _isolated_seed_environment(monkeypatch)
    mainnet = None
    testnet = None
    try:
        mainnet_port = _reserve_loopback_port()
        testnet_port = _reserve_loopback_port()
        while testnet_port == mainnet_port:
            testnet_port = _reserve_loopback_port()

        mainnet = WepoP2PNode(
            host="127.0.0.1",
            port=mainnet_port,
            network_profile="mainnet",
        )
        testnet = WepoP2PNode(
            host="127.0.0.1",
            port=testnet_port,
            network_profile="test",
        )
        assert mainnet.network_magic != testnet.network_magic

        mainnet.start_server()
        testnet.start_server()
        assert mainnet.connect_to_peer("127.0.0.1", testnet_port)

        assert _wait_until(
            lambda: mainnet.is_host_banned("127.0.0.1")
            and testnet.is_host_banned("127.0.0.1")
        )
        assert not any(
            peer.handshake_complete for peer in mainnet.peers.values()
        )
        assert not any(
            peer.handshake_complete for peer in testnet.peers.values()
        )
        assert not any(peer.is_connected() for peer in mainnet.peers.values())
        assert not any(peer.is_connected() for peer in testnet.peers.values())
    finally:
        if mainnet is not None:
            mainnet.stop_server()
        if testnet is not None:
            testnet.stop_server()


def test_live_matching_magic_with_wrong_profile_is_rejected(monkeypatch):
    _isolated_seed_environment(monkeypatch)
    node = None
    client = None
    try:
        port = _reserve_loopback_port()
        node = WepoP2PNode(
            host="127.0.0.1",
            port=port,
            network_profile="test",
        )
        node.start_server()

        client = socket.create_connection(("127.0.0.1", port), timeout=3)
        wrong_identity = {
            "version": PROTOCOL_VERSION,
            "services": 1,
            "timestamp": int(time.time()),
            "addr_recv": {"ip": "127.0.0.1", "port": port},
            "addr_from": {"ip": "127.0.0.2", "port": 22567},
            "nonce": 1,
            "user_agent": "/cross-network-test/",
            "start_height": 0,
            "network_profile": "mainnet",
            "relay": True,
        }
        client.sendall(
            node.create_message(
                "version",
                json.dumps(wrong_identity).encode(),
            )
        )

        assert _wait_until(lambda: node.is_host_banned("127.0.0.1"))
        assert not any(peer.handshake_complete for peer in node.peers.values())
        assert not any(peer.is_connected() for peer in node.peers.values())
    finally:
        if client is not None:
            client.close()
        if node is not None:
            node.stop_server()
