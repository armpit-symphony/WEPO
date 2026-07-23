#!/usr/bin/env python3
"""
Intra-block / mempool double-spend tests (consensus).

validate_transaction only checks a spend against COMMITTED UTXO state (the block
being assembled/validated is not applied yet), so it cannot by itself stop two
transactions that each spend the SAME outpoint from both landing in one block.
Without a cross-transaction check that is an inflation bug: both spends create
outputs, minting coins from nothing and breaking value conservation + the
supply cap.

This suite proves the guards:
  * the mempool refuses a second transaction that conflicts with an outpoint an
    existing mempool transaction already claims (first-seen wins)
  * create_new_block never packs two conflicting spends into the same block
  * validate_block REJECTS a hand-built block containing two transactions that
    spend the same outpoint, even with otherwise-valid PoW
  * a block with distinct, non-conflicting spends is still accepted

Run: python3 tests/test_double_spend.py
"""
import os
import sys
import shutil
import tempfile

os.environ.setdefault("WEPO_NETWORK_PROFILE", "test")

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

from blockchain import (  # noqa: E402
    WepoBlockchain,
    Transaction,
    TransactionInput,
    TransactionOutput,
    Block,
    BlockHeader,
    COIN,
)
from dilithium import generate_dilithium_keypair  # noqa: E402
from address_utils import generate_wepo_address  # noqa: E402

FAILURES = []


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


def make_addr():
    kp = generate_dilithium_keypair()
    return kp, generate_wepo_address(kp.public_key, address_type="quantum")


def insert_utxo(bc, txid, vout, address, amount):
    bc.conn.execute(
        "INSERT INTO utxos (txid, vout, address, amount, script_pubkey, spent) "
        "VALUES (?, ?, ?, ?, ?, FALSE)",
        (txid, vout, address, amount, b"output_script"),
    )
    bc.conn.commit()


def signed_spend(owner_kp, owner_addr, utxo_txid, utxo_vout, in_amount, recipient, fee):
    tx = Transaction(
        version=1,
        inputs=[TransactionInput(prev_txid=utxo_txid, prev_vout=utxo_vout,
                                 script_sig=b"placeholder")],
        outputs=[TransactionOutput(value=in_amount - fee, script_pubkey=b"output_script",
                                   address=recipient)],
        lock_time=0,
        fee=fee,
    )
    tx.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
    return tx


def mine(bc, block, limit=2_000_000):
    for nonce in range(limit):
        block.header.nonce = nonce
        if bc.miner.check_difficulty(bc.miner.calculate_pow_hash(block.header), block.header.bits):
            return True
    return False


def main():
    tmp = tempfile.mkdtemp(prefix="wepo-doublespend-")
    try:
        bc = WepoBlockchain(data_dir=tmp)
        bc.fixed_difficulty = 1  # trivial-but-real PoW so we can mine test blocks fast

        owner_kp, owner_addr = make_addr()
        _, rcpt1 = make_addr()
        _, rcpt2 = make_addr()
        _, miner_addr = make_addr()

        utxo_txid = "a" * 64
        in_amount = 10 * COIN
        fee = 1 * COIN
        insert_utxo(bc, utxo_txid, 0, owner_addr, in_amount)

        # A second, independent UTXO for the "distinct spends are fine" case.
        utxo_txid2 = "b" * 64
        insert_utxo(bc, utxo_txid2, 0, owner_addr, in_amount)

        print("Double-spend guards:")

        # Two DIFFERENT transactions spending the SAME outpoint (both individually valid).
        tx_a = signed_spend(owner_kp, owner_addr, utxo_txid, 0, in_amount, rcpt1, fee)
        tx_b = signed_spend(owner_kp, owner_addr, utxo_txid, 0, in_amount, rcpt2, fee)
        check("both conflicting spends are individually valid (sanity)",
              bc.validate_transaction(tx_a) and bc.validate_transaction(tx_b))

        # --- mempool guard ---
        check("first spend is accepted into the mempool",
              bc.add_transaction_to_mempool(tx_a) is True)
        check("conflicting second spend is rejected by the mempool",
              bc.add_transaction_to_mempool(tx_b) is False)
        check("mempool holds only the first spend", len(bc.mempool) == 1)

        # --- block assembly guard ---
        # Force both conflicting txs into the mempool (bypass the admission guard)
        # to prove create_new_block itself won't pack a conflict.
        bc.mempool[tx_a.calculate_txid()] = tx_a
        bc.mempool[tx_b.calculate_txid()] = tx_b
        assembled = bc.create_new_block(miner_addr)
        assembled_outpoints = [
            (inp.prev_txid, inp.prev_vout)
            for tx in assembled.transactions if not tx.is_coinbase()
            for inp in tx.inputs
        ]
        check("create_new_block does not pack two spends of the same outpoint",
              len(assembled_outpoints) == len(set(assembled_outpoints)))

        # --- validate_block guard (the consensus backstop for P2P-relayed blocks) ---
        height = bc.get_block_height() + 1
        prev_hash = bc.get_latest_block().get_block_hash()
        coinbase = bc.create_coinbase_transaction(height, miner_addr, "pow", [tx_a, tx_b])
        header = BlockHeader(
            version=1, prev_hash=prev_hash, merkle_root="",
            timestamp=bc.get_latest_block().header.timestamp + 360,
            bits=1, nonce=0, consensus_type="pow",
        )
        bad_block = Block(header=header, transactions=[coinbase, tx_a, tx_b], height=height)
        bad_block.header.merkle_root = bad_block.calculate_merkle_root()
        check("valid PoW can be found for the malicious block (isolates the DS check)",
              mine(bc, bad_block))
        check("validate_block REJECTS a block with two spends of the same outpoint",
              bc.validate_block(bad_block) is False)

        # --- non-conflicting block still accepted ---
        tx_c = signed_spend(owner_kp, owner_addr, utxo_txid, 0, in_amount, rcpt1, fee)
        tx_d = signed_spend(owner_kp, owner_addr, utxo_txid2, 0, in_amount, rcpt2, fee)
        coinbase2 = bc.create_coinbase_transaction(height, miner_addr, "pow", [tx_c, tx_d])
        header2 = BlockHeader(
            version=1, prev_hash=prev_hash, merkle_root="",
            timestamp=bc.get_latest_block().header.timestamp + 360,
            bits=1, nonce=0, consensus_type="pow",
        )
        good_block = Block(header=header2, transactions=[coinbase2, tx_c, tx_d], height=height)
        good_block.header.merkle_root = good_block.calculate_merkle_root()
        check("valid PoW can be found for the honest block", mine(bc, good_block))
        check("validate_block ACCEPTS a block with distinct, non-conflicting spends",
              bc.validate_block(good_block) is True)

        print()
        if FAILURES:
            print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
            return 1
        print("RESULT: ALL CHECKS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
