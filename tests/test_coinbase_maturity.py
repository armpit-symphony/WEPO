"""Consensus coverage for block-reward maturity and UTXO provenance."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from address_utils import generate_wepo_address  # noqa: E402
from blockchain import (  # noqa: E402
    Block,
    BlockHeader,
    Transaction,
    TransactionInput,
    TransactionOutput,
    WepoBlockchain,
)
from dilithium import generate_dilithium_keypair  # noqa: E402
from network_profile import get_network_profile  # noqa: E402


def _identity():
    keypair = generate_dilithium_keypair()
    address = generate_wepo_address(
        keypair.public_key, address_type="quantum"
    )
    return keypair, address


def _candidate_block(chain, miner_address, transactions):
    height = chain.get_block_height() + 1
    coinbase = chain.create_coinbase_transaction(
        height, miner_address, "pow", transactions
    )
    latest = chain.get_latest_block()
    header = BlockHeader(
        version=1,
        prev_hash=latest.get_block_hash(),
        merkle_root="",
        timestamp=max(int(time.time()), latest.header.timestamp + 1),
        bits=chain.calculate_expected_difficulty(),
        nonce=0,
        consensus_type="pow",
    )
    block = Block(
        header=header,
        transactions=[coinbase, *transactions],
        height=height,
    )
    block.header.merkle_root = block.calculate_merkle_root()
    while not chain.miner.check_difficulty(
        chain.miner.calculate_pow_hash(block.header), block.header.bits
    ):
        block.header.nonce += 1
    return block


def test_coinbase_maturity_is_enforced_and_replayed():
    data_dir = tempfile.mkdtemp(prefix="wepo-coinbase-maturity-")
    chain = None
    reopened = None
    try:
        assert get_network_profile("mainnet").coinbase_maturity is None
        with patch.dict(
            os.environ, {"WEPO_TEST_COINBASE_MATURITY": "2"}
        ):
            chain = WepoBlockchain(
                data_dir=data_dir, network_profile="test"
            )
            chain.fixed_difficulty = 1
            owner_keypair, owner_address = _identity()
            _, recipient_address = _identity()
            _, miner_address = _identity()

            reward_block = chain.mine_block(owner_address)
            assert reward_block is not None
            reward_row = chain.conn.execute(
                "SELECT txid, vout, amount, created_height, is_coinbase "
                "FROM utxos WHERE address = ? AND created_height = 1 "
                "AND is_coinbase = TRUE ORDER BY vout LIMIT 1",
                (owner_address,),
            ).fetchone()
            assert reward_row is not None
            reward_txid, reward_vout, reward_amount, created_height, is_coinbase = reward_row
            assert created_height == 1
            assert bool(is_coinbase)

            fee = 10_000
            spend = Transaction(
                version=1,
                inputs=[
                    TransactionInput(
                        prev_txid=reward_txid,
                        prev_vout=reward_vout,
                        script_sig=b"",
                        sequence=0xFFFFFFFF,
                    )
                ],
                outputs=[
                    TransactionOutput(
                        value=reward_amount - fee,
                        script_pubkey=b"maturity-test",
                        address=recipient_address,
                    )
                ],
                lock_time=0,
                fee=fee,
            )
            assert spend.sign_all_inputs(
                owner_keypair.private_key, owner_keypair.public_key
            )

            assert chain.get_balance(owner_address) == 0
            assert chain.get_immature_balance(owner_address) == reward_amount
            assert (
                chain.get_total_unlocked_balance(owner_address)
                == reward_amount
            )
            assert chain.get_utxos_for_address(owner_address) == []
            assert chain.get_network_info()["coinbase_maturity"] == 2
            assert not chain.add_transaction_to_mempool(spend)
            assert not chain.validate_block(
                _candidate_block(chain, miner_address, [spend])
            )

            assert chain.mine_block(miner_address) is not None
            assert chain.get_balance(owner_address) == reward_amount
            assert chain.get_immature_balance(owner_address) == 0
            assert (
                chain.get_total_unlocked_balance(owner_address)
                == reward_amount
            )
            assert chain.add_transaction_to_mempool(spend)
            assert chain.mine_block(miner_address) is not None
            assert chain.conn.execute(
                "SELECT spent, spent_height, created_height, is_coinbase "
                "FROM utxos WHERE txid = ? AND vout = ?",
                (reward_txid, reward_vout),
            ).fetchone() == (1, 3, 1, 1)

            chain.conn.close()
            chain = None
            reopened = WepoBlockchain(
                data_dir=data_dir, network_profile="test"
            )
            assert reopened.conn.execute(
                "SELECT spent, spent_height, created_height, is_coinbase "
                "FROM utxos WHERE txid = ? AND vout = ?",
                (reward_txid, reward_vout),
            ).fetchone() == (1, 3, 1, 1)
    finally:
        if chain is not None:
            chain.conn.close()
        if reopened is not None:
            reopened.conn.close()
        shutil.rmtree(data_dir, ignore_errors=True)
