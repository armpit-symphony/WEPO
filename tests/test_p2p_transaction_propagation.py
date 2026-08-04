#!/usr/bin/env python3
"""Full-transaction P2P inventory/getdata/acceptance propagation regressions."""

import hashlib
import json
import os
import struct
import sys

CORE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
)
sys.path.insert(0, CORE)

from blockchain import Transaction, TransactionInput, TransactionOutput  # noqa: E402
from p2p_network import (  # noqa: E402
    MAX_MESSAGE_SIZE,
    InventoryType,
    WepoP2PNode,
    WepoPeer,
)
from wepo_node import WepoFullNode  # noqa: E402


FAILURES = []
ADDRESS = "wepo1q111111111111111111111111111111111111111"


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


class FakePeer:
    def __init__(self, peer_id="source"):
        self.peer_id = peer_id
        self.sent = []

    def is_connected(self):
        return True

    def send_raw(self, message):
        self.sent.append(message)


class FakeSocket:
    def __init__(self):
        self.closed = False
        self.sent = []

    def close(self):
        self.closed = True

    def sendall(self, data):
        self.sent.append(data)


class FakeChain:
    def __init__(self, accept=True):
        self.accept = accept
        self.received = []
        self.payloads = {}

    def add_transaction_to_mempool(self, transaction):
        self.received.append(transaction)
        return self.accept

    def get_transaction_payload(self, txid):
        return self.payloads.get(txid)


def transaction():
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


def main():
    old_static = os.environ.get("WEPO_STATIC_PEERS")
    old_dns = os.environ.get("WEPO_DNS_SEEDS")
    os.environ["WEPO_STATIC_PEERS"] = "off"
    os.environ["WEPO_DNS_SEEDS"] = "off"
    try:
        network = WepoP2PNode(port=22579, network_profile="test")
        peer = FakePeer()
        tx = transaction()
        envelope = {"txid": tx.calculate_txid(), "tx_data": tx.to_dict()}

        print("P2P framing limits:")
        outbound_peer = object.__new__(WepoPeer)
        outbound_peer.node = network
        outbound_peer.peer_id = "outbound-peer"
        outbound_peer.connected = True
        outbound_peer.socket = FakeSocket()
        outbound_peer.send_raw(b"complete-frame")
        check(
            "peer writes use sendall so frames cannot be silently truncated",
            outbound_peer.socket.sent == [b"complete-frame"],
        )

        try:
            network.create_message("tx", b"x" * (MAX_MESSAGE_SIZE + 1))
            oversized_send_rejected = False
        except ValueError:
            oversized_send_rejected = True
        check("outbound oversized payload is rejected", oversized_send_rejected)

        oversized_header = struct.pack(
            "<4s12sI4s",
            network.network_magic,
            b"tx".ljust(12, b"\x00"),
            MAX_MESSAGE_SIZE + 1,
            hashlib.sha256(hashlib.sha256(b"").digest()).digest()[:4],
        )
        check(
            "parser rejects an oversized declared payload from its header",
            network.parse_message(oversized_header) is None,
        )

        hostile_peer = object.__new__(WepoPeer)
        hostile_peer.node = network
        hostile_peer.peer_id = "oversized-peer"
        hostile_peer.address = ("203.0.113.9", 40001)
        hostile_peer.receive_buffer = oversized_header
        hostile_peer.connected = True
        hostile_peer.socket = FakeSocket()
        hostile_peer.process_messages()
        check("oversized frame disconnects its peer immediately", not hostile_peer.connected)
        check("oversized frame buffer is discarded", hostile_peer.receive_buffer == b"")
        check("oversized peer socket is closed", hostile_peer.socket.closed)
        check(
            "oversized frame source is temporarily banned",
            network.is_host_banned("203.0.113.9"),
        )

        prehandshake_peer = object.__new__(WepoPeer)
        prehandshake_peer.node = network
        prehandshake_peer.peer_id = "prehandshake-peer"
        prehandshake_peer.address = ("203.0.113.10", 40002)
        prehandshake_peer.receive_buffer = network.create_message("ping", b"{}")
        prehandshake_peer.connected = True
        prehandshake_peer.handshake_complete = False
        prehandshake_peer.version_received = False
        prehandshake_peer.socket = FakeSocket()
        prehandshake_peer.process_messages()
        check(
            "application message before handshake disconnects its peer",
            not prehandshake_peer.connected,
        )
        check(
            "pre-handshake application sender is temporarily banned",
            network.is_host_banned("203.0.113.10"),
        )

        unknown_peer = object.__new__(WepoPeer)
        unknown_peer.node = network
        unknown_peer.peer_id = "unknown-command-peer"
        unknown_peer.address = ("203.0.113.11", 40003)
        unknown_peer.receive_buffer = network.create_message("futurecmd", b"")
        unknown_peer.connected = True
        unknown_peer.handshake_complete = True
        unknown_peer.version_received = True
        unknown_peer.socket = FakeSocket()
        unknown_peer.process_messages()
        check(
            "unknown protocol command disconnects its peer",
            not unknown_peer.connected,
        )
        check(
            "unknown protocol command source is temporarily banned",
            network.is_host_banned("203.0.113.11"),
        )


        print("\nP2P inventory/getdata:")
        network.has_transaction_callback = lambda txid: txid == envelope["txid"]
        known_inv = json.dumps(
            {
                "inventory": [
                    {"type": int(InventoryType.MSG_TX), "hash": envelope["txid"]}
                ]
            }
        ).encode()
        network.handle_inv(peer, known_inv)
        check("known transaction inventory is not requested", not peer.sent)

        network.has_transaction_callback = lambda _txid: False
        network.handle_inv(peer, known_inv)
        check("unknown transaction inventory triggers getdata", len(peer.sent) == 1)
        requested = network.parse_message(peer.sent.pop())
        requested_data = json.loads(requested.payload.decode()) if requested else {}
        check(
            "getdata requests the announced transaction",
            requested is not None
            and requested.command == "getdata"
            and requested_data.get("inventory", [{}])[0].get("hash")
            == envelope["txid"],
        )

        network.get_transaction_callback = (
            lambda txid: envelope if txid == envelope["txid"] else None
        )
        network.handle_getdata(peer, known_inv)
        full_message = network.parse_message(peer.sent.pop()) if peer.sent else None
        full_payload = json.loads(full_message.payload.decode()) if full_message else {}
        check(
            "getdata response carries the complete canonical transaction",
            full_message is not None
            and full_message.command == "tx"
            and full_payload == envelope,
        )

        print("\nP2P validation-before-relay:")
        accepted_payloads = []
        relayed = []
        network.on_new_transaction = (
            lambda payload: accepted_payloads.append(payload) is None
        )
        network.fluff_transaction = (
            lambda payload, exclude_peer_id=None: relayed.append(
                (payload, exclude_peer_id)
            )
        )
        network.handle_tx(peer, json.dumps(envelope).encode())
        check("full transaction reaches the consensus callback", accepted_payloads == [envelope])
        check(
            "accepted transaction is announced onward excluding its source",
            relayed == [(envelope, peer.peer_id)],
        )

        accepted_payloads.clear()
        relayed.clear()
        network.on_new_transaction = lambda payload: False
        network.handle_tx(peer, json.dumps(envelope).encode())
        check("rejected transaction is not relayed", not relayed)
        accepted_payloads.clear()
        network.on_new_transaction = (
            lambda payload: accepted_payloads.append(payload) is None
        )
        unknown_envelope = dict(envelope)
        unknown_envelope["future_field"] = 1
        network.handle_tx(peer, json.dumps(unknown_envelope).encode())
        check(
            "unknown transaction envelope fields are rejected before callback",
            not accepted_payloads,
        )
        invalid_phase = dict(envelope)
        invalid_phase["_dandelion_phase"] = "future-phase"
        network.handle_tx(peer, json.dumps(invalid_phase).encode())
        check(
            "unknown Dandelion phase is rejected before callback",
            not accepted_payloads,
        )


        print("\nFull-node envelope validation:")
        full_node = object.__new__(WepoFullNode)
        full_node.blockchain = FakeChain(accept=True)
        check(
            "matching txid and full payload enter the mempool",
            full_node.handle_new_transaction(envelope),
        )
        check(
            "full-node handler reconstructed the transaction",
            len(full_node.blockchain.received) == 1
            and full_node.blockchain.received[0].calculate_txid() == envelope["txid"],
        )

        tampered = {"txid": "0" * 64, "tx_data": tx.to_dict()}
        before = len(full_node.blockchain.received)
        check(
            "claimed txid mismatch is rejected",
            not full_node.handle_new_transaction(tampered),
        )
        check(
            "txid mismatch never reaches the mempool",
            len(full_node.blockchain.received) == before,
        )

        malformed = {"txid": envelope["txid"], "tx_data": "transaction_data"}
        check(
            "legacy placeholder payload is rejected",
            not full_node.handle_new_transaction(malformed),
        )
        unknown_full_node_envelope = dict(envelope)
        unknown_full_node_envelope["future_field"] = 1
        check(
            "full-node handler rejects unknown envelope fields",
            not full_node.handle_new_transaction(unknown_full_node_envelope),
        )

    finally:
        if old_static is None:
            os.environ.pop("WEPO_STATIC_PEERS", None)
        else:
            os.environ["WEPO_STATIC_PEERS"] = old_static
        if old_dns is None:
            os.environ.pop("WEPO_DNS_SEEDS", None)
        else:
            os.environ["WEPO_DNS_SEEDS"] = old_dns

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        raise SystemExit(1)
    print("RESULT: ALL CHECKS PASSED")


def test_regression_suite():
    main()


if __name__ == "__main__":
    main()
