"""Operational counters are truthful, bounded, and consensus-independent."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from blockchain import WepoBlockchain  # noqa: E402
from p2p_network import WepoP2PNode  # noqa: E402
from wepo_node import WepoFullNode  # noqa: E402


class FakePeer:
    def __init__(self):
        self.address = ("203.0.113.99", 22567)
        self.disconnected = False

    def disconnect(self):
        self.disconnected = True


def test_consensus_metrics_count_invalid_block_without_affecting_state(tmp_path):
    chain = WepoBlockchain(
        data_dir=str(tmp_path / "chain"),
        network_profile="test",
    )
    try:
        before = chain.get_operational_metrics()
        height = chain.get_block_height()
        tip = chain.get_latest_block().get_block_hash()
        issued = chain.get_issued_supply()

        invalid = copy.deepcopy(chain.get_latest_block())
        invalid.height = height + 1
        invalid.header.prev_hash = "f" * 64
        invalid.header.timestamp += 1
        assert not chain.add_block(invalid)

        after = chain.get_operational_metrics()
        assert after["scope"] == "process"
        assert after["uptime_seconds"] >= 0
        assert after["accepted_blocks_total"] == before["accepted_blocks_total"]
        assert (
            after["block_validation_rejections_total"]
            == before["block_validation_rejections_total"] + 1
        )
        assert after["reorgs_total"] == 0
        assert after["last_reorg"] is None
        assert chain.get_block_height() == height
        assert chain.get_latest_block().get_block_hash() == tip
        assert chain.get_issued_supply() == issued
    finally:
        chain.conn.close()


def test_p2p_metrics_count_policy_events_and_expose_active_state():
    p2p = WepoP2PNode(port=0, network_profile="test")
    peer = FakePeer()

    p2p.penalize_peer(peer, "telemetry-test")
    p2p._record_connection_failure("198.51.100.10:22567")
    metrics = p2p.get_network_info()["operational"]

    assert peer.disconnected
    assert metrics["scope"] == "process"
    assert metrics["uptime_seconds"] >= 0
    assert metrics["misbehavior_events_total"] == 1
    assert metrics["connection_failures_total"] == 1
    assert metrics["banned_hosts_active"] == 1
    assert metrics["outbound_backoffs_active"] == 1


def test_network_status_nests_node_consensus_and_p2p_metrics(tmp_path):
    node = WepoFullNode(
        data_dir=str(tmp_path / "node"),
        p2p_port=0,
        api_port=0,
        enable_mining=False,
        background_mining_enabled=False,
        network_profile="test",
    )
    try:
        status_route = next(
            route
            for route in node.app.routes
            if getattr(route, "path", None) == "/api/network/status"
        )
        status = asyncio.run(status_route.endpoint())
        operational = status["operational"]

        assert operational["scope"] == "process"
        assert operational["p2p_block_rejections_total"] == 0
        assert operational["p2p_transaction_rejections_total"] == 0
        assert operational["consensus"]["reorgs_total"] == 0
        assert operational["consensus"]["block_validation_rejections_total"] == 0
        assert operational["p2p"]["misbehavior_events_total"] == 0

        assert not node.handle_new_transaction({"unexpected": True})
        updated = node.get_operational_metrics()
        assert updated["p2p_transaction_rejections_total"] == 1
        assert status["network_profile"] == "test"
        assert "mempool_size" in status and "mempool_bytes" in status
    finally:
        node.blockchain.conn.close()
