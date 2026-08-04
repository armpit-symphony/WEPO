"""Protocol record identities cannot be replaced within a block or mempool."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
import time


os.environ.setdefault("WEPO_NETWORK_PROFILE", "test")
ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from address_utils import generate_wepo_address  # noqa: E402
from blockchain import (  # noqa: E402
    Block,
    BlockHeader,
    COIN,
    TX_TYPE_MASTERNODE_CREATE,
    Transaction,
    TransactionInput,
    TransactionOutput,
    WepoBlockchain,
)
from dilithium import generate_dilithium_keypair  # noqa: E402


def _owner():
    keypair = generate_dilithium_keypair()
    return keypair, generate_wepo_address(
        keypair.public_key, address_type="quantum"
    )


def _insert_utxo(chain, txid, address, amount):
    chain.conn.execute(
        "INSERT INTO utxos "
        "(txid, vout, address, amount, script_pubkey, spent) "
        "VALUES (?, 0, ?, ?, ?, FALSE)",
        (txid, address, amount, b"protocol-claim-test"),
    )
    chain.conn.commit()


def _registration(chain, keypair, address, txid, masternode_id):
    required = chain.get_masternode_collateral_for_height(
        chain.get_block_height() + 1
    )
    _insert_utxo(chain, txid, address, required)
    transaction = Transaction(
        version=1,
        inputs=[
            TransactionInput(
                prev_txid=txid,
                prev_vout=0,
                sequence=0xFFFFFFFF,
            )
        ],
        outputs=[
            TransactionOutput(
                value=required,
                script_pubkey=f"masternode_lock:{masternode_id}".encode(),
                address=address,
            )
        ],
        lock_time=0,
        fee=0,
        tx_type=TX_TYPE_MASTERNODE_CREATE,
        extra_data={
            "masternode_id": masternode_id,
            "operator_address": address,
            "ip_address": "127.0.0.1",
            "port": 22567,
        },
    )
    assert transaction.sign_all_inputs(
        keypair.private_key, keypair.public_key
    )
    return transaction


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


def test_masternode_state_claims_are_unique_and_immutable():
    data_dir = tempfile.mkdtemp(prefix="wepo-protocol-claims-")
    chain = None
    try:
        chain = WepoBlockchain(data_dir=data_dir, network_profile="test")
        chain.fixed_difficulty = 1
        first_keypair, first_address = _owner()
        second_keypair, second_address = _owner()
        shared_id = "mn-consensus-identity"
        first = _registration(
            chain, first_keypair, first_address, "a" * 64, shared_id
        )
        second = _registration(
            chain, second_keypair, second_address, "b" * 64, shared_id
        )

        assert chain.validate_transaction(first)
        assert chain.validate_transaction(second)
        assert chain.add_transaction_to_mempool(first)
        assert not chain.add_transaction_to_mempool(second)
        assert not chain.validate_block(
            _candidate_block(chain, first_address, [first, second])
        )

        assert chain.add_block(
            _candidate_block(chain, first_address, [first])
        )
        replacement = _registration(
            chain, second_keypair, second_address, "c" * 64, shared_id
        )
        assert not chain.validate_transaction(replacement)

        # An active masternode receives the canonical fee share. Preserving the
        # total coinbase value while redirecting that output must still fail.
        input_amount = COIN
        fee = 10_000
        _insert_utxo(chain, "d" * 64, second_address, input_amount)
        fee_transaction = Transaction(
            version=1,
            inputs=[TransactionInput(prev_txid="d" * 64, prev_vout=0)],
            outputs=[
                TransactionOutput(
                    value=input_amount - fee,
                    script_pubkey=b"fee-test",
                    address=second_address,
                )
            ],
            lock_time=0,
            fee=fee,
        )
        assert fee_transaction.sign_all_inputs(
            second_keypair.private_key, second_keypair.public_key
        )
        redirected = _candidate_block(
            chain, first_address, [fee_transaction]
        )
        assert len(redirected.transactions[0].outputs) == 2
        fee_output = redirected.transactions[0].outputs[1]
        assert fee_output.script_pubkey.startswith(b"masternode_fee_output:")
        fee_output.address = second_address
        redirected.header.merkle_root = redirected.calculate_merkle_root()
        redirected.header.nonce = 0
        while not chain.miner.check_difficulty(
            chain.miner.calculate_pow_hash(redirected.header),
            redirected.header.bits,
        ):
            redirected.header.nonce += 1
        assert not chain.validate_block(redirected)
    finally:
        if chain is not None:
            chain.conn.close()
        shutil.rmtree(data_dir, ignore_errors=True)
