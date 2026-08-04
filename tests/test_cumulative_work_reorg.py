"""Adversarial cumulative-work fork-choice and replay regression."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from address_utils import generate_wepo_address  # noqa: E402
import blockchain as consensus  # noqa: E402
from blockchain import WepoBlockchain  # noqa: E402
from dilithium import generate_dilithium_keypair  # noqa: E402


def _miner_address() -> str:
    keypair = generate_dilithium_keypair()
    return generate_wepo_address(keypair.public_key, address_type="quantum")


def _mine_at(chain: WepoBlockchain, timestamp: int):
    with patch.object(consensus.time, "time", return_value=timestamp):
        block = chain.mine_block(_miner_address())
    assert block is not None
    return block


def _copy_block(
    source: WepoBlockchain,
    target: WepoBlockchain,
    block,
):
    return target.deserialize_block(json.loads(source.serialize_block(block)))


def test_shorter_higher_work_branch_is_adopted_and_replays_exactly(tmp_path):
    main = WepoBlockchain(
        data_dir=str(tmp_path / "main"),
        network_profile="test",
    )
    side = WepoBlockchain(
        data_dir=str(tmp_path / "side"),
        network_profile="test",
    )
    reopened = None
    try:
        assert main.chain[0].get_block_hash() == side.chain[0].get_block_hash()
        genesis_time = main.chain[0].header.timestamp
        target_spacing = consensus.BLOCK_TIME_INITIAL_18_MONTHS

        for height in range(1, 16):
            _mine_at(main, genesis_time + height * target_spacing)

        side_blocks = [
            _mine_at(side, genesis_time + height)
            for height in range(1, 11)
        ]

        assert main.get_block_height() == 15
        assert side.get_block_height() == 10
        assert [block.header.bits for block in side_blocks] == [1] * 9 + [2]
        assert len(side.chain) < len(main.chain)

        main_score_before = main._chain_score(main.chain)
        side_score = side._chain_score(side.chain)
        assert side_score[0] > main_score_before[0]

        old_tip = main.get_latest_block().get_block_hash()
        adoption_results = [
            main.add_block_with_priority(_copy_block(side, main, block))
            for block in side_blocks
        ]

        assert adoption_results[:-1] == [False] * 9
        assert adoption_results[-1] is True
        assert main.get_block_height() == 10
        assert (
            main.get_latest_block().get_block_hash()
            == side.get_latest_block().get_block_hash()
        )
        assert old_tip in main.block_index
        assert old_tip not in main.main_chain_hashes
        assert main.get_issued_supply() == side.get_issued_supply()
        metrics = main.get_operational_metrics()
        assert metrics["reorgs_total"] == 1
        assert metrics["reorg_failures_total"] == 0
        assert metrics["last_reorg"]["ancestor_height"] == 0
        assert metrics["last_reorg"]["disconnected_depth"] == 15
        assert metrics["last_reorg"]["old_tip"] == old_tip
        assert metrics["last_reorg"]["new_tip"] == side.get_latest_block().get_block_hash()

        assert main.conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert main.conn.execute("PRAGMA foreign_key_check").fetchall() == []

        expected = {
            "height": main.get_block_height(),
            "tip": main.get_latest_block().get_block_hash(),
            "issued_supply": main.get_issued_supply(),
        }
        main.conn.close()
        main = None

        reopened = WepoBlockchain(
            data_dir=str(tmp_path / "main"),
            network_profile="test",
        )
        actual = {
            "height": reopened.get_block_height(),
            "tip": reopened.get_latest_block().get_block_hash(),
            "issued_supply": reopened.get_issued_supply(),
        }
        assert actual == expected
        assert reopened.conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert reopened.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        if main is not None:
            main.conn.close()
        side.conn.close()
        if reopened is not None:
            reopened.conn.close()
