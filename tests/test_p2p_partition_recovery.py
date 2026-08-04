"""Live P2P recovery after two nodes mine competing partitioned branches."""

from __future__ import annotations

import copy
import json
import os
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from address_utils import generate_wepo_address  # noqa: E402
import blockchain as consensus  # noqa: E402
from blockchain import WepoBlockchain  # noqa: E402
from dilithium import generate_dilithium_keypair  # noqa: E402
from p2p_network import WepoP2PNode  # noqa: E402


def _reserve_loopback_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def _miner_address() -> str:
    keypair = generate_dilithium_keypair()
    return generate_wepo_address(keypair.public_key, address_type="quantum")


def _wire_chain(
    node: WepoP2PNode, chain: WepoBlockchain, received: list[str] | None = None
) -> None:
    def accept_block(payload: dict) -> None:
        block = chain.deserialize_block(payload)
        if received is not None:
            received.append(block.get_block_hash())
        chain.add_block_with_priority(block)

    node.on_new_block = accept_block
    node.get_block_callback = chain.get_block_payload
    node.get_headers_callback = chain.get_headers_after_locator
    node.get_block_hashes_callback = chain.get_block_hashes_after_locator
    node.get_height_callback = chain.get_block_height
    node.get_locator_callback = chain.get_block_locator_hashes


@pytest.mark.parametrize("_iteration", range(5))
def test_partitioned_nodes_converge_on_the_higher_work_branch(_iteration):
    old_static = os.environ.get("WEPO_STATIC_PEERS")
    old_dns = os.environ.get("WEPO_DNS_SEEDS")
    old_required = os.environ.get("WEPO_REQUIRE_MAINNET_SEEDS")
    os.environ["WEPO_STATIC_PEERS"] = "off"
    old_test_timestamp = os.environ.get("WEPO_TEST_GENESIS_TIMESTAMP")
    old_test_address = os.environ.get("WEPO_TEST_GENESIS_ADDRESS")
    os.environ["WEPO_DNS_SEEDS"] = "off"
    os.environ.pop("WEPO_REQUIRE_MAINNET_SEEDS", None)

    os.environ.pop("WEPO_TEST_GENESIS_TIMESTAMP", None)
    os.environ.pop("WEPO_TEST_GENESIS_ADDRESS", None)
    data_a = tempfile.mkdtemp(prefix="wepo-partition-a-")
    data_b = tempfile.mkdtemp(prefix="wepo-partition-b-")
    chain_a = None
    chain_b = None
    node_a = None
    node_b = None
    try:
        chain_a = WepoBlockchain(data_dir=data_a, network_profile="test")
        chain_b = WepoBlockchain(data_dir=data_b, network_profile="test")
        assert chain_a.chain[0].get_block_hash() == chain_b.chain[0].get_block_hash()

        assert chain_a.mine_block(_miner_address()) is not None
        assert chain_a.mine_block(_miner_address()) is not None
        assert chain_b.mine_block(_miner_address()) is not None
        partition_tip_b = chain_b.chain[-1].get_block_hash()
        winning_tip = chain_a.chain[-1].get_block_hash()
        assert partition_tip_b != winning_tip
        assert chain_a.get_block_height() == 2
        assert chain_b.get_block_height() == 1

        port_a = _reserve_loopback_port()
        port_b = _reserve_loopback_port()
        while port_b == port_a:
            port_b = _reserve_loopback_port()
        node_a = WepoP2PNode("127.0.0.1", port_a, network_profile="test")
        node_b = WepoP2PNode("127.0.0.1", port_b, network_profile="test")
        received_by_b = []
        _wire_chain(node_a, chain_a)
        _wire_chain(node_b, chain_b, received_by_b)
        node_a.start_server()
        node_b.start_server()

        assert node_a.connect_to_peer("127.0.0.1", port_b)
        assert _wait_until(
            lambda: chain_b.get_block_height() == 2
            and chain_b.chain[-1].get_block_hash() == winning_tip
        )
        assert chain_a.chain[-1].get_block_hash() == winning_tip
        assert partition_tip_b in chain_a.block_index
        assert partition_tip_b in chain_b.block_index
        assert chain_a.get_issued_supply() == chain_b.get_issued_supply()

        outbound_peer = next(
            peer for peer in node_a.peers.values() if peer.is_connected()
        )
        stable_tip = chain_b.chain[-1].get_block_hash()
        invalid_block = chain_a.create_new_block(_miner_address())
        invalid_block.header.merkle_root = "0" * 64
        invalid_hash = invalid_block.get_block_hash()
        outbound_peer.send_raw(
            node_a.create_block_message(
                json.loads(chain_a.serialize_block(invalid_block))
            )
        )
        assert _wait_until(lambda: invalid_hash in received_by_b)
        assert chain_b.chain[-1].get_block_hash() == stable_tip
        assert invalid_hash not in chain_b.block_index
        assert chain_b.get_block_payload(invalid_hash) is None

        valid_extension = chain_a.mine_block(_miner_address())
        assert valid_extension is not None
        outbound_peer.send_raw(
            node_a.create_block_message(
                chain_a.get_block_payload(valid_extension.get_block_hash())
            )
        )
        assert _wait_until(
            lambda: chain_b.chain[-1].get_block_hash()
            == valid_extension.get_block_hash()
        )

        # Take B offline, advance A, then recreate B's transport around the
        # same stale chain state. Its locator must trigger catch-up on reconnect.
        node_b.stop_server()
        node_b = None
        stale_tip = chain_b.chain[-1].get_block_hash()
        offline_extension = chain_a.mine_block(_miner_address())
        assert offline_extension is not None
        assert chain_a.chain[-1].get_block_hash() != stale_tip
        assert chain_b.chain[-1].get_block_hash() == stale_tip

        reconnect_port = _reserve_loopback_port()
        while reconnect_port == port_a:
            reconnect_port = _reserve_loopback_port()
        node_b = WepoP2PNode(
            "127.0.0.1", reconnect_port, network_profile="test"
        )
        _wire_chain(node_b, chain_b, received_by_b)
        node_b.start_server()
        assert node_b.connect_to_peer("127.0.0.1", port_a)
        assert _wait_until(
            lambda: chain_b.chain[-1].get_block_hash()
            == offline_extension.get_block_hash()
        )
        assert chain_b.get_issued_supply() == chain_a.get_issued_supply()
    finally:
        if node_a is not None:
            node_a.stop_server()
        if node_b is not None:
            node_b.stop_server()
        if chain_a is not None:
            chain_a.conn.close()
        if chain_b is not None:
            chain_b.conn.close()
        shutil.rmtree(data_a, ignore_errors=True)
        shutil.rmtree(data_b, ignore_errors=True)
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
        if old_test_timestamp is None:
            os.environ.pop("WEPO_TEST_GENESIS_TIMESTAMP", None)
        else:
            os.environ["WEPO_TEST_GENESIS_TIMESTAMP"] = old_test_timestamp
        if old_test_address is None:
            os.environ.pop("WEPO_TEST_GENESIS_ADDRESS", None)
        else:
            os.environ["WEPO_TEST_GENESIS_ADDRESS"] = old_test_address


def test_pending_branch_cache_is_bounded_and_evicts_oldest_entries():
    data_dir = tempfile.mkdtemp(prefix="wepo-pending-bounds-")
    chain = None
    try:
        chain = WepoBlockchain(data_dir=data_dir, network_profile="test")
        template = chain.create_new_block(_miner_address())
        inserted_hashes = []

        invalid_orphan = copy.deepcopy(template)
        invalid_orphan.header.prev_hash = "e" * 64
        invalid_orphan.header.merkle_root = "0" * 64
        invalid_orphan_hash = invalid_orphan.get_block_hash()
        assert not chain.add_block_with_priority(invalid_orphan)
        assert invalid_orphan_hash not in chain.block_index
        assert invalid_orphan_hash not in chain.pending_block_order

        with (
            patch.object(consensus, "MAX_PENDING_BLOCKS", 3),
            patch.object(consensus, "MAX_PENDING_CHILDREN_PER_PARENT", 2),
        ):
            for index in range(5):
                orphan = copy.deepcopy(template)
                orphan.header.prev_hash = f"{index + 1:064x}"
                orphan.header.nonce = index
                orphan_hash = orphan.get_block_hash()
                inserted_hashes.append(orphan_hash)
                assert chain._remember_noncanonical_block(orphan)

            assert len(chain.pending_block_order) == 3
            assert sum(
                len(children)
                for children in chain.pending_blocks_by_prev_hash.values()
            ) == 3
            assert all(
                block_hash not in chain.block_index for block_hash in inserted_hashes[:2]
            )
            assert all(
                block_hash in chain.block_index
                for block_hash in inserted_hashes[-3:]
            )

            shared_parent = "f" * 64
            shared_hashes = []
            for nonce in range(3):
                orphan = copy.deepcopy(template)
                orphan.header.prev_hash = shared_parent
                orphan.header.nonce = 100 + nonce
                shared_hashes.append(orphan.get_block_hash())
                remembered = chain._remember_noncanonical_block(orphan)
                if nonce < 2:
                    assert remembered
                else:
                    assert not remembered

            assert len(chain.pending_blocks_by_prev_hash[shared_parent]) == 2
            assert shared_hashes[2] not in chain.block_index
            assert len(chain.pending_block_order) == 3
    finally:
        if chain is not None:
            chain.conn.close()
        shutil.rmtree(data_dir, ignore_errors=True)
