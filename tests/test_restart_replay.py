"""Deterministic restart and canonical-state replay coverage."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import shutil
import sys
import tempfile


CORE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
)
sys.path.insert(0, CORE)

from address_utils import generate_wepo_address  # noqa: E402
from blockchain import RWA_CREATION_MIN_FEE, WepoBlockchain  # noqa: E402
from dilithium import generate_dilithium_keypair  # noqa: E402


def _new_identity():
    keypair = generate_dilithium_keypair()
    address = generate_wepo_address(keypair.public_key, address_type="quantum")
    return keypair, address

def _transaction_rows(chain: WepoBlockchain):
    rows = chain.conn.execute(
        "SELECT txid, block_height, block_hash, fee, tx_data "
        "FROM transactions ORDER BY txid"
    ).fetchall()
    return tuple(
        (
            txid,
            block_height,
            block_hash,
            fee,
            json.dumps(
                json.loads(tx_data),
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        for txid, block_height, block_hash, fee, tx_data in rows
    )



def _rows(chain: WepoBlockchain, query: str):
    return tuple(chain.conn.execute(query).fetchall())


def _state_snapshot(chain: WepoBlockchain):
    return {
        "height": chain.get_block_height(),
        "tip": chain.chain[-1].get_block_hash(),
        "hashes": tuple(block.get_block_hash() for block in chain.chain),
        "issued_supply": chain.get_issued_supply(),
        "utxos": _rows(
            chain,
            "SELECT txid, vout, address, amount, hex(script_pubkey), spent, "
            "spent_txid, spent_height FROM utxos ORDER BY txid, vout",
        ),
        "transactions": _transaction_rows(chain),
        "rwa_assets": _rows(
            chain,
            "SELECT asset_id, owner_address, asset_hash, name, asset_type, "
            "create_txid, create_height FROM rwa_assets ORDER BY asset_id",
        ),
        "stakes": _rows(
            chain,
            "SELECT stake_id, staker_address, amount, start_height, status "
            "FROM stakes ORDER BY stake_id",
        ),
        "masternodes": _rows(
            chain,
            "SELECT masternode_id, operator_address, collateral_txid, "
            "collateral_vout, start_height, status "
            "FROM masternodes ORDER BY masternode_id",
        ),
    }


def test_restart_and_replay_reconstruct_identical_consensus_state():
    data_dir = tempfile.mkdtemp(prefix="wepo-restart-replay-")
    first = None
    reopened = None
    try:
        first = WepoBlockchain(data_dir=data_dir, network_profile="test")
        owner_keypair, owner_address = _new_identity()
        assert first.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert first.conn.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert first.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert (
            first.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        )
        assert (
            first.conn.execute("PRAGMA journal_size_limit").fetchone()[0]
            == 67108864
        )
        assert first.conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        reward_indexes = {
            row[1]
            for row in first.conn.execute(
                "PRAGMA index_list(staking_rewards)"
            ).fetchall()
        }
        assert "idx_staking_rewards_height_id" in reward_indexes
        _, miner_address = _new_identity()

        assert first.mine_block(owner_address) is not None
        asset_hash = hashlib.sha256(b"restart replay asset").hexdigest()
        asset_tx = first.create_rwa_creation(
            owner_address=owner_address,
            asset_hash=asset_hash,
            name="Replay asset",
            asset_type="test",
            fee=RWA_CREATION_MIN_FEE,
            asset_id="restart-replay-asset",
            return_unsigned=True,
        )
        asset_tx.sign_all_inputs(
            owner_keypair.private_key,
            owner_keypair.public_key,
        )
        assert first.add_transaction_to_mempool(asset_tx)
        assert first.mine_block(miner_address) is not None
        assert first.get_rwa_asset("restart-replay-asset") is not None

        expected = _state_snapshot(first)
        expected_supply_cache = dict(first.issued_supply_by_height)
        first.conn.close()
        # A tip read is served from the prefix cache without touching SQLite.
        assert first.get_issued_supply() == expected["issued_supply"]
        first = None

        # Structurally valid but semantically altered derived state is rebuilt
        # from canonical blocks at startup.
        tamper = sqlite3.connect(os.path.join(data_dir, "blockchain.db"))
        tamper.execute(
            "UPDATE utxos SET amount = amount + 1 "
            "WHERE rowid = (SELECT rowid FROM utxos LIMIT 1)"
        )
        tamper.commit()
        tamper.close()

        reopened = WepoBlockchain(data_dir=data_dir, network_profile="test")
        assert _state_snapshot(reopened) == expected
        assert reopened.issued_supply_by_height == expected_supply_cache
        assert not reopened.mempool
        assert set(reopened.block_index) == set(expected["hashes"])
        assert reopened.main_chain_hashes == set(expected["hashes"])

        canonical_blocks = list(reopened.chain)
        reopened._rebuild_canonical_state_from_blocks(canonical_blocks)
        assert _state_snapshot(reopened) == expected
        assert reopened.issued_supply_by_height == expected_supply_cache
    finally:
        if first is not None:
            first.conn.close()
        if reopened is not None:
            reopened.conn.close()
        shutil.rmtree(data_dir, ignore_errors=True)




def test_fixed_test_difficulty_is_applied_before_restart_replay():
    data_dir = tempfile.mkdtemp(prefix="wepo-fixed-difficulty-restart-")
    first = None
    reopened = None
    try:
        first = WepoBlockchain(
            data_dir=data_dir,
            network_profile="test",
            fixed_difficulty=1,
        )
        _, miner_address = _new_identity()
        for _ in range(12):
            assert first.mine_block(miner_address) is not None

        expected_height = first.get_block_height()
        expected_tip = first.get_latest_block().get_block_hash()
        assert expected_height >= 12
        assert all(
            block.header.bits == 1
            for block in first.chain
            if block.header.consensus_type == "pow"
        )
        first.conn.close()
        first = None

        reopened = WepoBlockchain(
            data_dir=data_dir,
            network_profile="test",
            fixed_difficulty=1,
        )
        assert reopened.get_block_height() == expected_height
        assert reopened.get_latest_block().get_block_hash() == expected_tip
        assert reopened.fixed_difficulty == 1
        assert reopened.calculate_expected_difficulty() == 1
    finally:
        if first is not None:
            first.conn.close()
        if reopened is not None:
            reopened.conn.close()
        shutil.rmtree(data_dir, ignore_errors=True)
def test_alternate_valid_pow_genesis_is_rejected():
    data_dir = tempfile.mkdtemp(prefix="wepo-alternate-genesis-")
    chain = None
    try:
        chain = WepoBlockchain(data_dir=data_dir, network_profile="test")
        canonical = chain.chain[0]
        alternate = chain.deserialize_block(
            json.loads(chain.serialize_block(canonical))
        )
        alternate.transactions[0].timestamp += 1
        alternate.header.merkle_root = alternate.calculate_merkle_root()
        alternate.header.nonce = 0
        while not chain.miner.check_difficulty(
            chain.miner.calculate_pow_hash(alternate.header),
            alternate.header.bits,
        ):
            alternate.header.nonce += 1
        alternate.size = alternate.calculate_size()

        assert chain.miner.check_difficulty(
            chain.miner.calculate_pow_hash(alternate.header),
            alternate.header.bits,
        )
        assert alternate.get_block_hash() != canonical.get_block_hash()
        assert not chain._validate_configured_genesis(alternate)
    finally:
        if chain is not None:
            chain.conn.close()
        shutil.rmtree(data_dir, ignore_errors=True)


def test_block_row_metadata_drift_fails_closed():
    data_dir = tempfile.mkdtemp(prefix="wepo-block-row-drift-")
    chain = None
    try:
        chain = WepoBlockchain(data_dir=data_dir, network_profile="test")
        database_path = chain.db_path
        chain.conn.close()
        chain = None

        tamper = sqlite3.connect(database_path)
        tamper.execute(
            "UPDATE blocks SET hash = ? WHERE height = 0",
            ("0" * 64,),
        )
        tamper.commit()
        tamper.close()

        try:
            WepoBlockchain(data_dir=data_dir, network_profile="test")
        except RuntimeError:
            rejected = True
        else:
            rejected = False
        assert rejected
    finally:
        if chain is not None:
            chain.conn.close()
        shutil.rmtree(data_dir, ignore_errors=True)


def test_corrupt_database_fails_closed_instead_of_creating_a_new_chain():
    data_dir = tempfile.mkdtemp(prefix="wepo-corrupt-db-")
    chain = None
    try:
        chain = WepoBlockchain(data_dir=data_dir, network_profile="test")
        database_path = chain.db_path
        chain.conn.close()
        chain = None

        with open(database_path, "r+b") as database_file:
            database_file.seek(0)
            database_file.write(b"not-a-sqlite-database")
            database_file.flush()
            os.fsync(database_file.fileno())

        try:
            WepoBlockchain(data_dir=data_dir, network_profile="test")
        except (RuntimeError, sqlite3.DatabaseError):
            rejected = True
        else:
            rejected = False
        assert rejected
    finally:
        if chain is not None:
            chain.conn.close()
        shutil.rmtree(data_dir, ignore_errors=True)
