#!/usr/bin/env python3
"""P2P release-boundary regressions.

Run: python3 tests/test_p2p_release_boundaries.py
"""

import json
import os
import socket
import sys

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

from p2p_network import DEFAULT_PORT, WepoP2PNode  # noqa: E402

FAILURES = []


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


class FakePeer:
    peer_id = "fake-peer"

    def __init__(self, host=None):
        if host is not None:
            self.address = (host, DEFAULT_PORT)
            self.peer_id = f"{host}:{DEFAULT_PORT}"
        self.disconnected = False
        self.verack_sent = False
        self.handshake_complete = False
        self.version_received = False
        self.sent = []
        self.pongs = []
        self.last_pong = 0

    def disconnect(self):
        self.disconnected = True

    def send_verack(self):
        self.verack_sent = True

    def is_connected(self):
        return not self.disconnected

    def send_raw(self, message):
        self.sent.append(message)

    def send_pong(self, nonce):
        self.pongs.append(nonce)


def main():
    old_static = os.environ.get("WEPO_STATIC_PEERS")
    old_dns = os.environ.get("WEPO_DNS_SEEDS")
    old_required = os.environ.get("WEPO_REQUIRE_MAINNET_SEEDS")
    os.environ["WEPO_STATIC_PEERS"] = "off"
    os.environ["WEPO_DNS_SEEDS"] = "off"
    os.environ.pop("WEPO_REQUIRE_MAINNET_SEEDS", None)

    try:
        mainnet = WepoP2PNode(port=22567, network_profile="mainnet")
        testnet = WepoP2PNode(port=22568, network_profile="test")

        print("P2P release boundaries:")
        mainnet_ping = mainnet.create_message("ping", b"payload")
        check(
            "testnet rejects mainnet message framing",
            testnet.parse_message(mainnet_ping) is None,
        )

        peer = FakePeer("198.51.100.20")
        wrong_profile = json.dumps(
            {
                "version": 70001,
                "services": 1,
                "user_agent": "/test/",
                "start_height": 0,
                "network_profile": "test",
            }
        ).encode()
        mainnet.handle_version(peer, wrong_profile)
        check("profile-mismatched peer is disconnected", peer.disconnected)
        check("profile-mismatched peer is not acknowledged", not peer.verack_sent)

        check(
            "profile-mismatched peer host is temporarily banned",
            mainnet.is_host_banned("198.51.100.20"),
        )
        premature = FakePeer()
        mainnet.handle_verack(premature, b"")
        check("verack before version is disconnected", premature.disconnected)
        check("premature verack does not complete handshake", not premature.handshake_complete)

        old_protocol = FakePeer()
        old_version = json.dumps(
            {
                "version": 70000,
                "services": 1,
                "user_agent": "/old/",
                "start_height": 0,
                "network_profile": "mainnet",
            }
        ).encode()
        mainnet.handle_version(old_protocol, old_version)
        check("unsupported protocol version is disconnected", old_protocol.disconnected)

        valid_peer = FakePeer()
        valid_version = json.dumps(
            {
                "version": 70001,
                "services": 1,
                "timestamp": 1,
                "addr_recv": {"ip": "127.0.0.1", "port": DEFAULT_PORT},
                "addr_from": {"ip": "198.51.100.30", "port": DEFAULT_PORT},
                "nonce": 1,
                "user_agent": "/valid/",
                "start_height": 0,
                "network_profile": "mainnet",
                "relay": True,
            }
        ).encode()
        mainnet.handle_version(valid_peer, valid_version)
        check("valid version is recorded", valid_peer.version_received)
        check("valid version is acknowledged", valid_peer.verack_sent)
        mainnet.handle_verack(valid_peer, b"")
        check("version then verack completes handshake", valid_peer.handshake_complete)

        duplicate = FakePeer()
        mainnet.handle_version(duplicate, valid_version)
        duplicate.disconnected = False
        mainnet.handle_version(duplicate, valid_version)
        check("duplicate version message is disconnected", duplicate.disconnected)

        malformed_addr_peer = FakePeer("198.51.100.21")
        mainnet.handle_addr(
            malformed_addr_peer,
            json.dumps({"addresses": [{"ip": "node.example", "port": 70000}]}).encode(),
        )
        check("malformed address message disconnects its peer", malformed_addr_peer.disconnected)
        check(
            "malformed address message bans its source host",
            mainnet.is_host_banned("198.51.100.21"),
        )

        canonical_addr_message = mainnet.parse_message(
            mainnet.create_addr_message([("seed.example", DEFAULT_PORT)])
        )
        canonical_addr_data = (
            json.loads(canonical_addr_message.payload.decode())
            if canonical_addr_message
            else {}
        )
        addr_receiver = FakePeer("198.51.100.23")
        testnet.handle_addr(addr_receiver, json.dumps(canonical_addr_data).encode())
        check(
            "node-generated address payload matches the receiving wire schema",
            canonical_addr_data
            == {"addresses": [{"ip": "seed.example", "port": DEFAULT_PORT}]}
            and ("seed.example", DEFAULT_PORT) in testnet.known_addresses
            and not addr_receiver.disconnected,
        )

        valid_ping_peer = FakePeer("198.51.100.24")
        mainnet.handle_ping(valid_ping_peer, json.dumps({"nonce": 7}).encode())
        check(
            "canonical ping nonce is echoed",
            valid_ping_peer.pongs == [7] and not valid_ping_peer.disconnected,
        )
        invalid_ping_peer = FakePeer("198.51.100.25")
        mainnet.handle_ping(invalid_ping_peer, json.dumps({"nonce": True}).encode())
        check("boolean ping nonce is rejected", invalid_ping_peer.disconnected)

        getaddr_peer = FakePeer("198.51.100.26")
        mainnet.handle_getaddr(getaddr_peer, b"unexpected")
        check(
            "malformed getaddr is rejected before addresses are disclosed",
            getaddr_peer.disconnected and not getaddr_peer.sent,
        )

        invalid_inventory_peer = FakePeer("198.51.100.27")
        mainnet.handle_inv(
            invalid_inventory_peer,
            json.dumps(
                {"inventory": [{"type": 1, "hash": "z" * 64}]}
            ).encode(),
        )
        check(
            "non-hex inventory hashes are rejected",
            invalid_inventory_peer.disconnected,
        )

        invalid_getdata_peer = FakePeer("198.51.100.28")
        mainnet.handle_getdata(
            invalid_getdata_peer,
            json.dumps(
                {
                    "inventory": [
                        {"type": 1, "hash": "00" * 32, "future_field": 1}
                    ]
                }
            ).encode(),
        )
        check(
            "unknown getdata item fields are rejected",
            invalid_getdata_peer.disconnected,
        )

        invalid_sync_peer = FakePeer("198.51.100.29")
        mainnet.handle_getheaders(
            invalid_sync_peer,
            json.dumps(
                {"locator_hashes": [], "stop_hash": None, "limit": 2001}
            ).encode(),
        )
        check(
            "getheaders response limits are enforced before callbacks",
            invalid_sync_peer.disconnected,
        )

        invalid_block_peer = FakePeer("198.51.100.31")
        mainnet.on_new_block = lambda _payload: False
        mainnet.handle_block(
            invalid_block_peer,
            json.dumps({"hash": "00" * 32}).encode(),
        )
        check(
            "consensus-rejected block disconnects and bans its source",
            invalid_block_peer.disconnected
            and mainnet.is_host_banned("198.51.100.31"),
        )

        class FailingSocket:
            def __init__(self):
                self.closed = False

            def settimeout(self, _timeout):
                return None

            def connect(self, _address):
                raise OSError("intentional connection failure")

            def close(self):
                self.closed = True

        backoff_peer_id = "198.51.100.22:22567"
        failing_socket = FailingSocket()
        original_socket = socket.socket
        socket.socket = lambda *_args, **_kwargs: failing_socket
        try:
            connected_result = mainnet.connect_to_peer("198.51.100.22", DEFAULT_PORT)
        finally:
            socket.socket = original_socket

        check("failed outbound connection is rejected", not connected_result)
        check("failed outbound socket is closed", failing_socket.closed)
        check(
            "failed outbound connection enters exponential backoff",
            mainnet._outbound_backoff_active(backoff_peer_id),
        )
        first_attempts, first_retry_at = mainnet.connection_backoff[backoff_peer_id]
        mainnet._record_connection_failure(backoff_peer_id)
        second_attempts, second_retry_at = mainnet.connection_backoff[backoff_peer_id]
        check(
            "repeated outbound failures escalate backoff",
            second_attempts == first_attempts + 1 and second_retry_at > first_retry_at,
        )
        mainnet._prune_peer_policy(now=second_retry_at + 1)
        check(
            "expired retry delay retains escalation history",
            mainnet.connection_backoff[backoff_peer_id][0] == second_attempts,
        )
        mainnet._record_connection_success(backoff_peer_id)
        check(
            "successful handshake clears outbound backoff",
            not mainnet._outbound_backoff_active(backoff_peer_id),
        )

        os.environ["WEPO_DNS_SEEDS"] = "seed.example.invalid"
        dns_node = WepoP2PNode(port=22569, network_profile="mainnet")
        connected = []
        original_getaddrinfo = socket.getaddrinfo

        def fake_getaddrinfo(host, port, family, socktype):
            check("configured DNS seed is resolved", host == "seed.example.invalid")
            return [
                (family, socktype, 6, "", ("198.51.100.10", port)),
                (family, socktype, 6, "", ("198.51.100.10", port)),
            ]

        socket.getaddrinfo = fake_getaddrinfo
        dns_node.connect_to_peer = lambda host, port: connected.append((host, port)) or True
        try:
            dns_node.discover_peers()
        finally:
            socket.getaddrinfo = original_getaddrinfo

        check(
            "resolved DNS peers are deduplicated and connected",
            connected == [("198.51.100.10", DEFAULT_PORT)],
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
        if old_required is None:
            os.environ.pop("WEPO_REQUIRE_MAINNET_SEEDS", None)
        else:
            os.environ["WEPO_REQUIRE_MAINNET_SEEDS"] = old_required

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


def test_regression_suite():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
