#!/usr/bin/env python3
"""
Dandelion++ transaction-origin privacy tests (PRIVACY_DESIGN.md Layer 1).

Verifies the propagation-control logic that decouples the broadcasting node from
the originating node — the metadata-privacy layer that defeats "first node to
announce == sender" de-anonymization. Also covers the SOCKS5/Tor outbound
handshake against a local fake proxy. No sockets are opened for the routing tests.

Run: python3 tests/test_dandelion_privacy.py
"""
import os
import sys
import socket
import struct
import threading
import random

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

from p2p_network import WepoP2PNode, CONNECTION_TIMEOUT  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        FAILURES.append(name)


class FakePeer:
    """Minimal peer stand-in that records raw sends."""
    def __init__(self, peer_id):
        self.peer_id = peer_id
        self.sent = []

    def is_connected(self):
        return True

    def send_raw(self, data):
        self.sent.append(data)


def make_node():
    # Dandelion on, no proxy; do not start the server.
    os.environ["WEPO_DANDELION"] = "1"
    os.environ.pop("WEPO_SOCKS5_PROXY", None)
    return WepoP2PNode(host="127.0.0.1", port=22600 + random.randint(0, 200))


def test_stem_peer_selection():
    node = make_node()
    peers = ["a:1", "b:2", "c:3", "d:4"]

    # Stable within an epoch, and always one of the peers.
    e = 5
    s1 = node.select_stem_peer(e, peers)
    s2 = node.select_stem_peer(e, list(reversed(peers)))
    check("stem peer is stable within an epoch (order-independent)", s1 == s2)
    check("stem peer is one of the connected peers", s1 in peers)
    check("no peers -> no stem peer", node.select_stem_peer(e, []) is None)

    # Rotates across epochs (over a span of epochs we should see >1 distinct relay).
    seen = {node.select_stem_peer(i, peers) for i in range(50)}
    check("stem route rotates across epochs", len(seen) > 1)


def test_decision_fluff_and_stem():
    node = make_node()
    peers = ["a:1", "b:2", "c:3"]

    # No peers -> always fluff.
    check("no peers -> fluff", node.dandelion_decision([], now=0)[0] == "fluff")

    # rng below fluff prob -> fluff; at/above -> stem.
    low = random.Random(); low.random = lambda: 0.0
    high = random.Random(); high.random = lambda: 0.99
    check("low roll -> fluff", node.dandelion_decision(peers, now=0, rng=low)[0] == "fluff")
    act, peer = node.dandelion_decision(peers, now=0, rng=high)
    check("high roll -> stem to a single peer", act == "stem" and peer in peers)

    # Disabled -> always fluff.
    node.dandelion_enabled = False
    check("dandelion disabled -> fluff", node.dandelion_decision(peers, now=0, rng=high)[0] == "fluff")


def test_relay_stem_then_fluff_and_embargo():
    node = make_node()
    node._dandelion_rng = type("R", (), {"random": staticmethod(lambda: 0.99)})()  # force stem
    node.dandelion_embargo_seconds = 30
    p_stem = FakePeer("a:1")
    p_other = FakePeer("b:2")
    node.peers = {"a:1": p_stem, "b:2": p_other}

    tx = {"txid": "deadbeef", "amount": 1}
    action, stem_peer = node.dandelion_relay_transaction(tx, from_peer_id=None)
    check("originated tx goes to a single stem peer (not flooded)", action == "stem")
    # Exactly one peer received a stem send; the other got nothing yet.
    sent_counts = (len(p_stem.sent), len(p_other.sent))
    check("only the stem peer received the tx", sorted(sent_counts) == [0, 1])
    check("stem send carries the stem phase marker",
          any(b"_dandelion_phase" in s and b"stem" in s for s in p_stem.sent + p_other.sent))
    check("embargo recorded for the stem tx", "deadbeef" in node._stem_pool)

    # Embargo not yet expired -> nothing fluffed.
    check("embargo not expired yet -> no fluff", node.expired_embargoes(now=0) == [])
    # After the embargo deadline, the failsafe releases it for fluffing.
    expired = node.expired_embargoes(now=10**12)
    check("embargo expires -> tx released to fluff", len(expired) == 1 and expired[0][0] == "deadbeef")
    check("embargo cleared after release", "deadbeef" not in node._stem_pool)


def test_relay_fluff_floods_all_peers():
    node = make_node()
    node._dandelion_rng = type("R", (), {"random": staticmethod(lambda: 0.0)})()  # force fluff
    p1, p2, p3 = FakePeer("a:1"), FakePeer("b:2"), FakePeer("c:3")
    node.peers = {"a:1": p1, "b:2": p2, "c:3": p3}

    action, _ = node.dandelion_relay_transaction({"txid": "cafe"}, from_peer_id=None)
    check("fluff path announces to ALL peers", action == "fluff"
          and all(len(p.sent) == 1 for p in (p1, p2, p3)))
    check("fluff announces via inventory (no stem marker)",
          all(b"_dandelion_phase" not in p.sent[0] for p in (p1, p2, p3)))


def test_socks5_connect_handshake():
    """Drive _socks5_connect against a tiny in-process SOCKS5 server."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    proxy_host, proxy_port = listener.getsockname()
    captured = {}

    def fake_proxy():
        conn, _ = listener.accept()
        try:
            greeting = conn.recv(3)               # 05 01 00
            captured["greeting"] = greeting
            conn.sendall(b"\x05\x00")             # no-auth accepted
            head = conn.recv(4)                   # 05 01 00 03
            ln = conn.recv(1)[0]
            host = conn.recv(ln)
            port = struct.unpack(">H", conn.recv(2))[0]
            captured["dest"] = (host.decode(), port)
            # success reply with a dummy bound IPv4:port
            conn.sendall(b"\x05\x00\x00\x01" + b"\x00\x00\x00\x00" + struct.pack(">H", 0))
            conn.recv(16)  # let the client proceed/close
        except Exception:
            pass
        finally:
            conn.close()

    t = threading.Thread(target=fake_proxy, daemon=True)
    t.start()

    node = make_node()
    try:
        sock = node._socks5_connect((proxy_host, proxy_port), "example.onion", 22567)
        sock.close()
        ok = True
    except Exception as e:
        ok = False
        print("    socks5 error:", e)
    t.join(timeout=2)
    listener.close()

    check("SOCKS5 greeting is no-auth (05 01 00)", captured.get("greeting") == b"\x05\x01\x00")
    check("SOCKS5 sends destination as a domain name (no DNS leak)",
          captured.get("dest") == ("example.onion", 22567))
    check("SOCKS5 CONNECT completes and returns a socket", ok)


def main():
    test_stem_peer_selection()
    test_decision_fluff_and_stem()
    test_relay_stem_then_fluff_and_embargo()
    test_relay_fluff_floods_all_peers()
    test_socks5_connect_handshake()

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
