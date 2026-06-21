#!/usr/bin/env python3
"""
On-chain RWA creation tests.

Proves RWA asset creation is REAL on-chain issuance (not an off-chain DB record):

  * a client-signed rwa_create tx is accepted, mined, and indexed from the chain
    with the owner bound to the signing key and the asset_hash committed on-chain
  * ownership/index is reorg-safe (survives a derived-state rebuild from blocks)
  * a duplicate asset_id is rejected
  * an owner_address that doesn't match the spending key is rejected
  * a malformed asset_hash is rejected
  * a fee below the anti-spam minimum is rejected
  * an output paying someone other than the owner is rejected

Run: python3 tests/test_rwa_creation.py
"""
import os
import sys
import shutil
import hashlib
import tempfile

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

from blockchain import (  # noqa: E402
    WepoBlockchain, Transaction, TransactionInput, TransactionOutput,
    COIN, RWA_CREATION_MIN_FEE, TX_TYPE_RWA_CREATE,
)
from dilithium import generate_dilithium_keypair  # noqa: E402
from address_utils import generate_wepo_address  # noqa: E402

FAILURES = []


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILURES.append(name)


def make_owner():
    kp = generate_dilithium_keypair()
    return kp, generate_wepo_address(kp.public_key, address_type="quantum")


def fund(bc, txid, vout, address, amount):
    bc.conn.execute(
        "INSERT INTO utxos (txid, vout, address, amount, script_pubkey, spent) "
        "VALUES (?, ?, ?, ?, ?, FALSE)",
        (txid, vout, address, amount, b"output_script"),
    )
    bc.conn.commit()


def asset_hash_of(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def main():
    tmp = tempfile.mkdtemp(prefix="wepo-rwa-test-")
    try:
        bc = WepoBlockchain(data_dir=tmp)
        owner_kp, owner_addr = make_owner()
        attacker_kp, attacker_addr = make_owner()
        _, miner_addr = make_owner()

        a_hash = asset_hash_of(b"deed: 123 Main St; title doc v1")

        # Fund the owner from a real mined coinbase (so the UTXO lives in a block
        # and the reorg-rebuild test below is realistic).
        check("owner funded via mined coinbase", bc.mine_block(owner_addr) is not None)

        # --- happy path: build -> sign -> submit -> mine -> indexed on-chain ---
        unsigned = bc.create_rwa_creation(
            owner_address=owner_addr, asset_hash=a_hash,
            name="123 Main St", asset_type="real_estate",
            fee=RWA_CREATION_MIN_FEE, asset_id="asset-001", return_unsigned=True,
        )
        check("builder produces an rwa_create tx", unsigned.tx_type == TX_TYPE_RWA_CREATE)
        unsigned.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        check("signed rwa_create accepted into mempool",
              bc.add_transaction_to_mempool(unsigned) is True)

        mined = bc.mine_block(miner_addr)
        check("block with rwa_create mined", mined is not None)

        asset = bc.get_rwa_asset("asset-001")
        check("asset is indexed from the chain", asset is not None)
        if asset:
            check("on-chain owner is bound to the signing key", asset["owner_address"] == owner_addr)
            check("asset_hash committed on-chain matches", asset["asset_hash"] == a_hash)
            check("asset metadata (name/type) recorded",
                  asset["name"] == "123 Main St" and asset["asset_type"] == "real_estate")
            check("asset records its creation txid + height",
                  bool(asset["create_txid"]) and asset["create_height"] == mined.height)
        check("owner lookup returns the asset",
              any(a["asset_id"] == "asset-001" for a in bc.get_rwa_assets_for_owner(owner_addr)))

        # --- reorg safety: rebuild derived state purely from blocks ---
        bc._rebuild_canonical_state_from_blocks(list(bc.chain))
        check("asset survives a derived-state rebuild (reorg-safe)",
              bc.get_rwa_asset("asset-001") is not None)

        # Direct-insert UTXOs for the rejection cases (these only exercise mempool
        # validation, not a rebuild, so they need not live in a block).
        fund(bc, "e" * 64, 0, owner_addr, 1 * COIN)

        # --- rejection: duplicate asset_id ---
        dup = bc.create_rwa_creation(owner_address=owner_addr, asset_hash=a_hash,
                                     fee=RWA_CREATION_MIN_FEE, asset_id="asset-001",
                                     return_unsigned=True)
        dup.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        check("duplicate asset_id rejected", bc.add_transaction_to_mempool(dup) is False)

        # --- rejection: owner_address does not match the spending key ---
        spoof = bc.create_rwa_creation(owner_address=owner_addr, asset_hash=a_hash,
                                       fee=RWA_CREATION_MIN_FEE, asset_id="asset-spoof",
                                       return_unsigned=True)
        spoof.extra_data["owner_address"] = attacker_addr  # claim someone else owns it
        spoof.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        check("owner_address must match the spending key", bc.add_transaction_to_mempool(spoof) is False)

        # --- rejection: malformed asset_hash ---
        try:
            bc.create_rwa_creation(owner_address=owner_addr, asset_hash="not-a-hash",
                                   fee=RWA_CREATION_MIN_FEE, return_unsigned=True)
            bad_hash_raised = False
        except ValueError:
            bad_hash_raised = True
        check("malformed asset_hash rejected at build", bad_hash_raised)

        # ...and rejected at consensus if forced through a hand-built tx
        forced = bc.create_rwa_creation(owner_address=owner_addr, asset_hash=a_hash,
                                        fee=RWA_CREATION_MIN_FEE, asset_id="asset-badhash",
                                        return_unsigned=True)
        forced.extra_data["asset_hash"] = "xyz"
        forced.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        check("malformed asset_hash rejected at consensus", bc.add_transaction_to_mempool(forced) is False)

        # --- rejection: fee below anti-spam minimum (hand-built) ---
        utxo = bc.get_utxos_for_address(owner_addr)[0]
        low_fee = Transaction(
            version=1,
            inputs=[TransactionInput(prev_txid=utxo["txid"], prev_vout=utxo["vout"],
                                     script_sig=b"signature_placeholder")],
            outputs=[TransactionOutput(value=utxo["amount"] - 1, script_pubkey=b"change_script",
                                       address=owner_addr)],
            lock_time=0, fee=1, tx_type=TX_TYPE_RWA_CREATE,
            extra_data={"asset_id": "asset-lowfee", "owner_address": owner_addr, "asset_hash": a_hash},
        )
        low_fee.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        check("fee below anti-spam minimum rejected", bc.add_transaction_to_mempool(low_fee) is False)

        # --- rejection: output pays a non-owner ---
        pay_out = Transaction(
            version=1,
            inputs=[TransactionInput(prev_txid=utxo["txid"], prev_vout=utxo["vout"],
                                     script_sig=b"signature_placeholder")],
            outputs=[TransactionOutput(value=utxo["amount"] - RWA_CREATION_MIN_FEE,
                                       script_pubkey=b"output_script", address=attacker_addr)],
            lock_time=0, fee=RWA_CREATION_MIN_FEE, tx_type=TX_TYPE_RWA_CREATE,
            extra_data={"asset_id": "asset-pay", "owner_address": owner_addr, "asset_hash": a_hash},
        )
        pay_out.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        check("rwa_create output to a non-owner rejected", bc.add_transaction_to_mempool(pay_out) is False)

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
