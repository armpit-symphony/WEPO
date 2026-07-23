#!/usr/bin/env python3
"""
Launch configuration regression checks.

Run: python3 tests/test_launch_config.py
"""
import os
import sys

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

FAILURES = []


def check(name, condition):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}")
    if not condition:
        FAILURES.append(name)


def main():
    for k in ("WEPO_STATIC_PEERS", "WEPO_DNS_SEEDS", "WEPO_REQUIRE_MAINNET_SEEDS"):
        os.environ.pop(k, None)

    import network_profile
    import blockchain
    from p2p_network import WepoP2PNode

    print("Launch configuration:")
    check(
        "mainnet genesis timestamp is 2026-09-02 18:00:00 UTC",
        network_profile.MAINNET_GENESIS_TIMESTAMP == 1788372000
        and blockchain.MAINNET_GENESIS_TIMESTAMP == 1788372000,
    )
    check("core consensus module is in production mode", blockchain.PRODUCTION_MODE is True)

    mainnet_node = WepoP2PNode(port=0, network_profile="mainnet")
    check("mainnet has no fake localhost static peers by default", mainnet_node.static_seed_addresses == [])
    check("mainnet has no fake DNS seeds by default", mainnet_node.dns_seeds == [])

    test_node = WepoP2PNode(port=0, network_profile="test")
    check(
        "test profile keeps localhost static peers for smoke tests",
        ("127.0.0.1", 22567) in test_node.static_seed_addresses,
    )

    os.environ["WEPO_STATIC_PEERS"] = "node-a.example:22567,node-b.example:22568"
    configured_node = WepoP2PNode(port=0, network_profile="mainnet")
    check(
        "configured static peers are parsed explicitly",
        configured_node.static_seed_addresses == [("node-a.example", 22567), ("node-b.example", 22568)],
    )
    os.environ.pop("WEPO_STATIC_PEERS", None)

    os.environ["WEPO_REQUIRE_MAINNET_SEEDS"] = "1"
    try:
        WepoP2PNode(port=0, network_profile="mainnet")
        requires_seeds = False
    except RuntimeError:
        requires_seeds = True
    os.environ.pop("WEPO_REQUIRE_MAINNET_SEEDS", None)
    check("production mainnet can require configured seeds", requires_seeds)

    service = open("wepo-production-deployment/wepo-node.service.example", encoding="utf-8").read()
    check("node service binds API to localhost", "--api-host 127.0.0.1" in service)
    check("node service does not use testing difficulty override", "--difficulty-override" not in service)
    check("node service requires mainnet seed configuration", "WEPO_REQUIRE_MAINNET_SEEDS=1" in service)

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)} failing): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
