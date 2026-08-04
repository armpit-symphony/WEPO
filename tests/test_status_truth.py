#!/usr/bin/env python3
"""Truthfulness boundaries for public network/mining status payloads."""

import os
import sys


BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, os.path.abspath(BACKEND))

from status_truth import build_mining_status, build_network_status  # noqa: E402


NODE_STATUS = {
    "height": 7,
    "best_block_hash": "ab" * 32,
    "difficulty": 42,
    "total_supply": 123_456_789,
    "supply_cap": 6_900_000_300_000_000,
    "network": "WEPO Test Network",
    "network_profile": "test",
    "consensus_type": "pow",
    "peers": 3,
    "connections": ["node-a", "node-b", "node-c"],
    "minimum_relay_fee_per_kb": 1000,
}


def test_network_status_uses_canonical_atomic_values_without_fake_hashrate():
    status = build_network_status(
        NODE_STATUS,
        staking_status={"total_staked": 12.5},
        masternodes=[{"id": "a"}, {"id": "b"}],
        observed_at=1234,
    )

    assert status["source"] == "live_node"
    assert status["block_height"] == 7
    assert status["total_supply_atomic"] == 123_456_789
    assert status["total_supply"] == 1.23456789
    assert status["supply_cap_atomic"] == 6_900_000_300_000_000
    assert status["supply_cap"] == 69_000_003
    assert status["minimum_relay_fee_per_kb_atomic"] == 1000
    assert status["active_masternodes"] == 2
    assert status["total_staked"] == 12.5
    assert status["network_hashrate"] is None
    assert status["network_hashrate_available"] is False


def test_missing_optional_status_is_unavailable_not_zero():
    status = build_network_status(NODE_STATUS, observed_at=1234)

    assert status["active_masternodes"] is None
    assert status["total_staked"] is None
    assert status["network_hashrate"] is None


def test_mining_status_labels_browser_telemetry_and_uses_live_tip():
    status = build_mining_status(
        NODE_STATUS,
        {
            "network": "WEPO Test Network",
            "network_profile": "test",
            "difficulty": 42,
            "mining_enabled": True,
            "background_mining_enabled": False,
        },
        connected_browser_sessions=4,
        reported_browser_hashrate=987.5,
        observed_at=1234,
    )

    assert status["source"] == "live_node"
    assert status["node_reachable"] is True
    assert status["genesis_status"] == "found"
    assert status["genesis_launch_time"] is None
    assert status["block_height"] == 7
    assert status["network_hashrate"] is None
    assert status["connected_browser_sessions"] == 4
    assert status["reported_browser_hashrate"] == 987.5


def test_status_rejects_negative_consensus_values():
    invalid = dict(NODE_STATUS, height=-1)

    try:
        build_network_status(invalid, observed_at=1234)
    except ValueError as exc:
        assert "height" in str(exc)
    else:
        raise AssertionError("negative height must be rejected")

def test_status_rejects_missing_canonical_supply_fields():
    invalid = dict(NODE_STATUS)
    invalid.pop("supply_cap")

    try:
        build_network_status(invalid, observed_at=1234)
    except ValueError as exc:
        assert "supply_cap" in str(exc)
    else:
        raise AssertionError("missing supply cap must be rejected")
