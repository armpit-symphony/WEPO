#!/usr/bin/env python3
"""
Consensus value-invariant regression tests for the 2026-07 audit fixes.

Run: python3 tests/test_consensus_value_invariants.py
"""
import os
import sys
import shutil
import tempfile
import time

os.environ.setdefault("WEPO_NETWORK_PROFILE", "test")

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

from blockchain import (  # noqa: E402
    Block,
    BlockHeader,
    COIN,
    Transaction,
    TransactionInput,
    TransactionOutput,
    WepoBlockchain,
)
from dilithium import generate_dilithium_keypair  # noqa: E402
from address_utils import generate_wepo_address  # noqa: E402

FAILURES = []


def check(name, condition):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}")
    if not condition:
        FAILURES.append(name)


def make_owner():
    keypair = generate_dilithium_keypair()
    address = generate_wepo_address(keypair.public_key, address_type="quantum")
    return keypair, address


def insert_utxo(blockchain, txid, vout, address, amount):
    blockchain.conn.execute(
        "INSERT INTO utxos (txid, vout, address, amount, script_pubkey, spent) "
        "VALUES (?, ?, ?, ?, ?, FALSE)",
        (txid, vout, address, amount, b"test_utxo"),
    )
    blockchain.conn.commit()


def mine_header(blockchain, header):
    while not blockchain.miner.check_difficulty(
        blockchain.miner.calculate_pow_hash(header),
        header.bits,
    ):
        header.nonce += 1


def make_next_block(blockchain, transactions):
    latest = blockchain.get_latest_block()
    height = blockchain.get_block_height() + 1
    header = BlockHeader(
        version=1,
        prev_hash=latest.get_block_hash(),
        merkle_root="",
        timestamp=min(int(time.time()), latest.header.timestamp + 360),
        bits=1,
        nonce=0,
        consensus_type="pow",
    )
    block = Block(header=header, transactions=transactions, height=height)
    block.header.merkle_root = block.calculate_merkle_root()
    mine_header(blockchain, block.header)
    return block


def build_spend(owner_addr, recipient_addr, utxo_txid, utxo_vout, in_amount, send_amount, fee):
    outputs = [
        TransactionOutput(
            value=send_amount,
            script_pubkey=b"pay",
            address=recipient_addr,
        )
    ]
    change = in_amount - send_amount - fee
    if change > 0:
        outputs.append(
            TransactionOutput(value=change, script_pubkey=b"change", address=owner_addr)
        )
    return Transaction(
        version=1,
        inputs=[TransactionInput(prev_txid=utxo_txid, prev_vout=utxo_vout)],
        outputs=outputs,
        lock_time=0,
        fee=fee,
    )


def new_chain():
    tmp = tempfile.mkdtemp(prefix="wepo-consensus-invariants-")
    bc = WepoBlockchain(data_dir=tmp)
    bc.fixed_difficulty = 1
    bc.current_difficulty = 1
    return bc, tmp


def main():
    bc, tmp = new_chain()
    try:
        owner_kp, owner_addr = make_owner()
        _, recipient_addr = make_owner()
        _, attacker_addr = make_owner()

        input_amount = 10 * COIN
        fee = 10_000

        print("Consensus value invariants:")

        insert_utxo(bc, "a" * 64, 0, owner_addr, input_amount)
        tx_ok = build_spend(owner_addr, recipient_addr, "a" * 64, 0, input_amount, 3 * COIN, fee)
        tx_ok.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        check("ordinary owner-signed transparent spend is accepted", bc.validate_transaction(tx_ok) is True)

        try:
            TransactionOutput(value=-1, script_pubkey=b"neg", address=attacker_addr)
            negative_constructor_rejected = False
        except ValueError:
            negative_constructor_rejected = True
        check("negative output construction is rejected", negative_constructor_rejected)

        insert_utxo(bc, "b" * 64, 0, owner_addr, input_amount)
        tx_negative = build_spend(owner_addr, recipient_addr, "b" * 64, 0, input_amount, 1 * COIN, fee)
        tx_negative.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        tx_negative.outputs[1].value = -fee
        check("mutated negative output is rejected by consensus", bc.validate_transaction(tx_negative) is False)

        insert_utxo(bc, "c" * 64, 0, owner_addr, input_amount)
        tx_privacy = build_spend(owner_addr, recipient_addr, "c" * 64, 0, input_amount, 2 * COIN, fee)
        tx_privacy.privacy_proof = b"placeholder-proof"
        tx_privacy.ring_signature = b"placeholder-ring"
        tx_privacy.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        check("privacy metadata is rejected while consensus privacy is disabled", bc.validate_transaction(tx_privacy) is False)

        insert_utxo(bc, "d" * 64, 0, owner_addr, input_amount)
        tx_duplicate = build_spend(owner_addr, recipient_addr, "d" * 64, 0, input_amount, 1 * COIN, fee)
        tx_duplicate.inputs.append(TransactionInput(prev_txid="d" * 64, prev_vout=0))
        tx_duplicate.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        tx_duplicate.sign_input(1, owner_kp.private_key, owner_kp.public_key)
        check("duplicate input outpoints are rejected", bc.validate_transaction(tx_duplicate) is False)

        height = bc.get_block_height() + 1
        honest_coinbase = bc.create_coinbase_transaction(height, owner_addr, "pow", [])
        extra_coinbase = Transaction(
            version=1,
            inputs=[TransactionInput(prev_txid="0" * 64, prev_vout=0xffffffff)],
            outputs=[TransactionOutput(value=1 * COIN, script_pubkey=b"extra", address=attacker_addr)],
            lock_time=0,
            fee=0,
        )
        check(
            "block with additional coinbase is rejected",
            bc.validate_block(make_next_block(bc, [honest_coinbase, extra_coinbase])) is False,
        )

        allowed = bc.clamped_base_reward(height, "pow")
        negative_coinbase = bc.create_coinbase_transaction(height, owner_addr, "pow", [])
        negative_coinbase.outputs = [
            TransactionOutput(value=allowed + fee, script_pubkey=b"cb_pos", address=attacker_addr),
            TransactionOutput(value=fee, script_pubkey=b"cb_tmp", address=recipient_addr),
        ]
        negative_coinbase.outputs[1].value = -fee
        check(
            "coinbase negative-output offset is rejected",
            bc.validate_block(make_next_block(bc, [negative_coinbase])) is False,
        )

        insert_utxo(bc, "e" * 64, 0, owner_addr, input_amount)
        actual_fee = 10_000
        fake_fee = 1 * COIN
        tx_fake_fee = build_spend(
            owner_addr,
            recipient_addr,
            "e" * 64,
            0,
            input_amount,
            input_amount - actual_fee,
            actual_fee,
        )
        tx_fake_fee.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        tx_fake_fee.fee = fake_fee
        inflated_coinbase = bc.create_coinbase_transaction(height, owner_addr, "pow", [])
        inflated_coinbase.outputs[0].value = allowed + fake_fee
        check(
            "coinbase cannot claim unvalidated transaction fee fields",
            bc.validate_block(make_next_block(bc, [inflated_coinbase, tx_fake_fee])) is False,
        )

        print()
        if FAILURES:
            print(f"RESULT: FAILED ({len(FAILURES)} failing): {FAILURES}")
            return 1
        print("RESULT: ALL CHECKS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
