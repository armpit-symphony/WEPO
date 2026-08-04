"""Adversarial P2P connection-slot and parser-dispatch boundaries."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from blockchain import Transaction, TransactionInput, TransactionOutput  # noqa: E402
from p2p_network import (  # noqa: E402
    HANDSHAKE_TIMEOUT_SECONDS,
    PARTIAL_MESSAGE_TIMEOUT_SECONDS,
    WepoP2PNode,
    WepoPeer,
)


ADDRESS = "wepo1q111111111111111111111111111111111111111"


class FakeSocket:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _transaction() -> Transaction:
    return Transaction(
        version=1,
        inputs=[
            TransactionInput(
                prev_txid="a" * 64,
                prev_vout=0,
                script_sig=b"",
                sequence=0xFFFFFFFF,
            )
        ],
        outputs=[
            TransactionOutput(
                value=1,
                address=ADDRESS,
                script_pubkey=b"output",
            )
        ],
        lock_time=0,
        fee=0,
        timestamp=1_800_000_000,
    )


def test_disconnect_stops_pipelined_dispatch():
    network = WepoP2PNode(port=22579, network_profile="test")
    tx = _transaction()
    envelope = {"txid": tx.calculate_txid(), "tx_data": tx.to_dict()}
    callbacks = []

    peer = object.__new__(WepoPeer)
    peer.node = network
    peer.peer_id = "pipelined-violation-peer"
    peer.address = ("203.0.113.12", 40004)
    peer.receive_buffer = (
        network.create_message("ping", json.dumps({"nonce": True}).encode())
        + network.create_transaction_message(envelope)
    )
    peer.partial_message_started_at = 1.0
    peer.connected = True
    peer.handshake_complete = True
    peer.version_received = True
    peer.socket = FakeSocket()
    network.on_new_transaction = lambda payload: callbacks.append(payload)

    peer.process_messages()

    assert not callbacks
    assert peer.receive_buffer == b""
    assert not peer.connected
    assert peer.socket.closed


def test_connection_deadlines_fail_closed():
    network = WepoP2PNode(port=22579, network_profile="test")

    handshake_peer = object.__new__(WepoPeer)
    handshake_peer.node = network
    handshake_peer.peer_id = "handshake-timeout-peer"
    handshake_peer.address = ("203.0.113.13", 40005)
    handshake_peer.receive_buffer = b""
    handshake_peer.partial_message_started_at = None
    handshake_peer.connected_at = 10.0
    handshake_peer.connected = True
    handshake_peer.handshake_complete = False
    handshake_peer.socket = FakeSocket()
    network.peers[handshake_peer.peer_id] = handshake_peer

    assert not handshake_peer.enforce_connection_deadlines(
        10.0 + HANDSHAKE_TIMEOUT_SECONDS + 0.001
    )
    assert not handshake_peer.connected
    assert handshake_peer.socket.closed
    assert handshake_peer.peer_id not in network.peers

    partial_peer = object.__new__(WepoPeer)
    partial_peer.node = network
    partial_peer.peer_id = "partial-frame-timeout-peer"
    partial_peer.address = ("203.0.113.14", 40006)
    partial_peer.receive_buffer = b"W"
    partial_peer.partial_message_started_at = 20.0
    partial_peer.connected_at = 0.0
    partial_peer.connected = True
    partial_peer.handshake_complete = True
    partial_peer.socket = FakeSocket()

    assert not partial_peer.enforce_connection_deadlines(
        20.0 + PARTIAL_MESSAGE_TIMEOUT_SECONDS + 0.001
    )
    assert partial_peer.receive_buffer == b""
    assert not partial_peer.connected
    assert partial_peer.socket.closed


def test_server_stop_wakes_and_joins_service_threads():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = int(probe.getsockname()[1])
    probe.close()

    node = WepoP2PNode(host="127.0.0.1", port=port, network_profile="test")
    node.start_server()
    service_threads = list(node._service_threads)
    assert len(service_threads) == 2
    assert all(thread.is_alive() for thread in service_threads)

    node.stop_server()

    assert node.server_socket is None
    assert node._service_threads == []
    assert all(not thread.is_alive() for thread in service_threads)
