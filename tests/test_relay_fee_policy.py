"""Relay-fee policy and fee-bearing lifecycle transaction coverage."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import pytest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from address_utils import generate_wepo_address  # noqa: E402
from blockchain import (  # noqa: E402
    Block,
    BlockHeader,
    COIN,
    MIN_STAKE_AMOUNT,
    POS_ACTIVATION_HEIGHT,
    Transaction,
    TransactionInput,
    TransactionOutput,
    WepoBlockchain,
)
from dilithium import generate_dilithium_keypair  # noqa: E402


def _identity():
    keypair = generate_dilithium_keypair()
    address = generate_wepo_address(
        keypair.public_key, address_type="quantum"
    )
    return keypair, address


def _insert_utxo(chain, txid, address, amount, script=b"test-output"):
    chain.conn.execute(
        "INSERT INTO utxos "
        "(txid, vout, address, amount, script_pubkey, spent) "
        "VALUES (?, 0, ?, ?, ?, FALSE)",
        (txid, address, amount, script),
    )
    chain.conn.commit()


def _spend(keypair, owner, recipient, txid, amount, fee, network):
    transaction = Transaction(
        version=1,
        inputs=[
            TransactionInput(
                prev_txid=txid,
                prev_vout=0,
                script_sig=b"",
                sequence=0xFFFFFFFF,
            )
        ],
        outputs=[
            TransactionOutput(
                value=amount - fee,
                script_pubkey=b"relay-test",
                address=recipient,
            )
        ],
        lock_time=0,
        fee=fee,
    )
    assert transaction.sign_all_inputs(
        keypair.private_key, keypair.public_key, network
    )
    return transaction


def _candidate_block(chain, miner_address, transactions):
    height = chain.get_block_height() + 1
    coinbase = chain.create_coinbase_transaction(
        height, miner_address, "pow", transactions
    )
    latest = chain.get_latest_block()
    block = Block(
        header=BlockHeader(
            version=1,
            prev_hash=latest.get_block_hash(),
            merkle_root="",
            timestamp=max(int(time.time()), latest.header.timestamp + 1),
            bits=chain.calculate_expected_difficulty(),
            nonce=0,
            consensus_type="pow",
        ),
        transactions=[coinbase, *transactions],
        height=height,
    )
    block.header.merkle_root = block.calculate_merkle_root()
    while not chain.miner.check_difficulty(
        chain.miner.calculate_pow_hash(block.header), block.header.bits
    ):
        block.header.nonce += 1
    return block


def test_relay_fee_rate_is_local_policy_not_block_consensus():
    data_dir = tempfile.mkdtemp(prefix="wepo-relay-fee-")
    mainnet_dir = tempfile.mkdtemp(prefix="wepo-relay-mainnet-")
    chain = None
    mainnet = None
    try:
        with patch.dict(
            os.environ, {"WEPO_TEST_MIN_RELAY_FEE_PER_KB": "100000"}
        ):
            chain = WepoBlockchain(
                data_dir=data_dir, network_profile="test"
            )
        chain.fixed_difficulty = 1
        owner_keypair, owner_address = _identity()
        _, recipient_address = _identity()
        _, miner_address = _identity()
        amount = 10 * COIN

        _insert_utxo(chain, "a" * 64, owner_address, amount)
        zero_fee = _spend(
            owner_keypair, owner_address, recipient_address,
            "a" * 64, amount, 0, "test",
        )
        assert chain.validate_transaction(zero_fee)
        assert not chain.add_transaction_to_mempool(zero_fee)
        # Relay policy must never turn an otherwise valid transaction/block
        # into a consensus-invalid block.
        assert chain.validate_block(
            _candidate_block(chain, miner_address, [zero_fee])
        )

        _insert_utxo(chain, "b" * 64, owner_address, amount)
        high_fee = _spend(
            owner_keypair, owner_address, recipient_address,
            "b" * 64, amount, COIN, "test",
        )
        size = high_fee.canonical_wire_size()
        assert chain.required_relay_fee(size) == (
            100000 * size + 999
        ) // 1000
        assert high_fee.fee >= chain.required_relay_fee(size)
        assert chain.add_transaction_to_mempool(high_fee)
        assert (
            chain.get_network_info()["minimum_relay_fee_per_kb"]
            == 100000
        )

        mainnet = WepoBlockchain(
            data_dir=mainnet_dir, network_profile="mainnet"
        )
        mainnet.fixed_difficulty = 1
        _insert_utxo(mainnet, "c" * 64, owner_address, amount)
        mainnet_tx = _spend(
            owner_keypair, owner_address, recipient_address,
            "c" * 64, amount, COIN, "mainnet",
        )
        assert mainnet.validate_transaction(mainnet_tx)
        assert mainnet.required_relay_fee(
            mainnet_tx.canonical_wire_size()
        ) is None
        assert not mainnet.add_transaction_to_mempool(mainnet_tx)
    finally:
        if chain is not None:
            chain.conn.close()
        if mainnet is not None:
            mainnet.conn.close()
        shutil.rmtree(data_dir, ignore_errors=True)
        shutil.rmtree(mainnet_dir, ignore_errors=True)


def test_wallet_fee_quote_matches_exact_signed_shape_and_converges():
    data_dir = tempfile.mkdtemp(prefix="wepo-relay-quote-")
    chain = None
    try:
        with patch.dict(
            os.environ, {"WEPO_TEST_MIN_RELAY_FEE_PER_KB": "1226"}
        ):
            chain = WepoBlockchain(data_dir=data_dir, network_profile="test")
        _, owner_address = _identity()
        _, recipient_address = _identity()
        _insert_utxo(chain, "c" * 64, owner_address, 2 * COIN)

        quoted, signed_size = chain.create_relay_fee_transaction(
            owner_address, recipient_address, COIN
        )
        assert quoted.fee >= 10_000
        assert quoted.fee >= chain.required_relay_fee(signed_size)
        assert signed_size == chain.estimated_signed_wire_size(quoted)

        signed_shape = Transaction.from_dict(quoted.to_dict())
        for tx_input in signed_shape.inputs:
            tx_input.script_sig = b""
            tx_input.signature_type = "dilithium"
            tx_input.quantum_public_key = b"p" * 1312
            tx_input.quantum_signature = b"s" * 2420
        assert signed_shape.canonical_wire_size() == signed_size
    finally:
        if chain is not None:
            chain.conn.close()
        shutil.rmtree(data_dir, ignore_errors=True)


def test_wallet_fee_quote_fails_closed_when_policy_is_unset():
    data_dir = tempfile.mkdtemp(prefix="wepo-relay-quote-mainnet-")
    chain = None
    try:
        chain = WepoBlockchain(data_dir=data_dir, network_profile="mainnet")
        _, owner_address = _identity()
        _, recipient_address = _identity()
        _insert_utxo(chain, "d" * 64, owner_address, 2 * COIN)
        with pytest.raises(ValueError, match="not finalized"):
            chain.create_relay_fee_transaction(owner_address, recipient_address, COIN)
    finally:
        if chain is not None:
            chain.conn.close()
        shutil.rmtree(data_dir, ignore_errors=True)


def test_lifecycle_builders_pay_fees_without_eroding_locked_value():
    data_dir = tempfile.mkdtemp(prefix="wepo-lifecycle-fees-")
    chain = None
    try:
        chain = WepoBlockchain(
            data_dir=data_dir, network_profile="test"
        )
        owner_keypair, owner_address = _identity()
        _, other_address = _identity()
        fee = 10_000

        # Exercise the post-activation stake builder without mining through the
        # accelerated schedule; all UTXOs are explicit non-issuance fixtures.
        chain.get_block_height = lambda: POS_ACTIVATION_HEIGHT + 1
        stake_funding = MIN_STAKE_AMOUNT + fee + 123
        _insert_utxo(
            chain, "d" * 64, owner_address, stake_funding
        )
        stake_tx = chain.create_stake(
            owner_address,
            MIN_STAKE_AMOUNT,
            return_unsigned=True,
            fee=fee,
        )
        assert [output.value for output in stake_tx.outputs] == [
            MIN_STAKE_AMOUNT, 123
        ]
        assert stake_tx.fee == fee
        assert stake_tx.sign_all_inputs(
            owner_keypair.private_key, owner_keypair.public_key
        )
        assert chain.validate_transaction(stake_tx)

        redirected_change = Transaction.from_dict(stake_tx.to_dict())
        redirected_change.outputs[1].address = other_address
        assert redirected_change.sign_all_inputs(
            owner_keypair.private_key, owner_keypair.public_key
        )
        assert not chain.validate_transaction(redirected_change)
        chain.conn.execute("UPDATE utxos SET spent = TRUE WHERE txid = ?", ("d" * 64,))
        chain.conn.commit()


        # Registration preserves the complete designated collateral outpoint;
        # a separate owner outpoint pays the fee and receives exact change.
        chain.get_block_height = lambda: 0
        required = chain.get_masternode_collateral_for_height(1)
        _insert_utxo(
            chain, "e" * 64, owner_address, required
        )
        _insert_utxo(
            chain, "f" * 64, owner_address, fee + 77
        )
        masternode_tx = chain.create_masternode(
            owner_address,
            "e" * 64,
            0,
            ip_address="127.0.0.1",
            port=22567,
            return_unsigned=True,
            fee=fee,
        )
        assert len(masternode_tx.inputs) == 2
        assert masternode_tx.inputs[0].prev_txid == "e" * 64
        assert [output.value for output in masternode_tx.outputs] == [
            required, 77
        ]
        assert masternode_tx.sign_all_inputs(
            owner_keypair.private_key, owner_keypair.public_key
        )
        assert chain.validate_transaction(masternode_tx)

        # An active canonical collateral output can pay its deactivation fee
        # while returning every other atomic unit to the owner.
        locked_txid = "1" * 64
        masternode_id = "mn_fee_deactivation"
        _insert_utxo(
            chain,
            locked_txid,
            owner_address,
            required,
            f"masternode_lock:{masternode_id}".encode(),
        )
        chain.conn.execute(
            "INSERT INTO transactions ("
            "txid, block_height, block_hash, version, lock_time, fee, tx_data"
            ") VALUES (?, 0, ?, 1, 0, 0, ?)",
            (
                locked_txid,
                chain.chain[0].get_block_hash(),
                "{}",
            ),
        )
        chain.conn.execute(
            "INSERT INTO masternodes ("
            "masternode_id, operator_address, collateral_txid, "
            "collateral_vout, ip_address, port, start_height, start_time, "
            "last_ping, status, total_rewards"
            ") VALUES (?, ?, ?, 0, ?, ?, 0, 1, 0, 'active', 0)",
            (
                masternode_id,
                owner_address,
                locked_txid,
                "127.0.0.1",
                22567,
            ),
        )
        chain.conn.commit()
        deactivate_tx = chain.deactivate_masternode(
            masternode_id,
            owner_address,
            return_unsigned=True,
            fee=fee,
        )
        assert deactivate_tx.outputs[0].value == required - fee
        assert deactivate_tx.sign_all_inputs(
            owner_keypair.private_key, owner_keypair.public_key
        )
        assert chain.validate_transaction(deactivate_tx)
    finally:
        if chain is not None:
            chain.conn.close()
        shutil.rmtree(data_dir, ignore_errors=True)
