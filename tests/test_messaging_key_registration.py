#!/usr/bin/env python3
"""
On-chain messaging-key registration tests (trustless key discovery).

Proves messaging public keys can be anchored on-chain, bound to the owner's
address, so peers discover them without trusting the relay registry:

  * a client-signed key_register tx is accepted, mined, and indexed from the chain
  * the registered keys are bound to the owner (signing) address
  * a re-registration replaces the previous one (latest wins)
  * the index is reorg-safe (survives a derived-state rebuild)
  * wrong-size kem/sig pubkeys, owner mismatch, low fee, and non-owner outputs
    are rejected

Run: python3 tests/test_messaging_key_registration.py
"""
import os
import sys
import shutil
import tempfile

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

from blockchain import (  # noqa: E402
    WepoBlockchain, Transaction, TransactionInput, TransactionOutput, COIN,
    TX_TYPE_KEY_REGISTER, MSG_KEY_REGISTER_MIN_FEE,
    ML_KEM768_PUB_HEX_LEN, ML_DSA44_PUB_HEX_LEN,
)
from dilithium import generate_dilithium_keypair  # noqa: E402
from address_utils import generate_wepo_address  # noqa: E402

FAILURES = []
KEM = "a" * ML_KEM768_PUB_HEX_LEN
SIG = "b" * ML_DSA44_PUB_HEX_LEN


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILURES.append(name)


def make_owner():
    kp = generate_dilithium_keypair()
    return kp, generate_wepo_address(kp.public_key, address_type="quantum")


def main():
    tmp = tempfile.mkdtemp(prefix="wepo-msgkey-test-")
    try:
        bc = WepoBlockchain(data_dir=tmp)
        owner_kp, owner_addr = make_owner()
        attacker_kp, attacker_addr = make_owner()
        _, miner_addr = make_owner()

        check("owner funded via mined coinbase", bc.mine_block(owner_addr) is not None)

        # --- happy path: build -> sign -> mine -> indexed on-chain ---
        unsigned = bc.create_key_registration(owner_addr, KEM, SIG, return_unsigned=True)
        check("builder produces a key_register tx", unsigned.tx_type == TX_TYPE_KEY_REGISTER)
        unsigned.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        check("signed key_register accepted into mempool", bc.add_transaction_to_mempool(unsigned) is True)
        mined = bc.mine_block(miner_addr)
        check("block with key_register mined", mined is not None)

        rec = bc.get_messaging_keys(owner_addr)
        check("messaging keys indexed from the chain", rec is not None)
        if rec:
            check("keys bound to the owner address",
                  rec["address"] == owner_addr and rec["kem_pub"] == KEM and rec["sig_pub"] == SIG)
            check("registration records txid + height",
                  bool(rec["register_txid"]) and rec["register_height"] == mined.height)

        # --- re-registration replaces (latest wins) ---
        bc.mine_block(owner_addr)  # fund again
        kem2 = "c" * ML_KEM768_PUB_HEX_LEN
        rereg = bc.create_key_registration(owner_addr, kem2, SIG, return_unsigned=True)
        rereg.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        bc.add_transaction_to_mempool(rereg)
        bc.mine_block(miner_addr)
        check("re-registration replaces prior keys (latest wins)",
              (bc.get_messaging_keys(owner_addr) or {}).get("kem_pub") == kem2)

        # --- reorg safety ---
        bc._rebuild_canonical_state_from_blocks(list(bc.chain))
        check("registration survives a derived-state rebuild (reorg-safe)",
              bc.get_messaging_keys(owner_addr) is not None)

        # Direct-insert a UTXO for rejection cases.
        bc.conn.execute(
            "INSERT INTO utxos (txid, vout, address, amount, script_pubkey, spent) "
            "VALUES (?, ?, ?, ?, ?, FALSE)", ("e" * 64, 0, owner_addr, 1 * COIN, b"output_script"))
        bc.conn.commit()
        utxo = bc.get_utxos_for_address(owner_addr)[0]

        def hand_built(extra, fee=MSG_KEY_REGISTER_MIN_FEE, out_addr=None):
            tx = Transaction(
                version=1,
                inputs=[TransactionInput(prev_txid=utxo["txid"], prev_vout=utxo["vout"],
                                         script_sig=b"signature_placeholder")],
                outputs=[TransactionOutput(value=utxo["amount"] - fee, script_pubkey=b"change_script",
                                           address=out_addr or owner_addr)],
                lock_time=0, fee=fee, tx_type=TX_TYPE_KEY_REGISTER, extra_data=extra)
            tx.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
            return tx

        bad_kem = hand_built({"owner_address": owner_addr, "kem_pub": "ab", "sig_pub": SIG})
        check("wrong-size kem_pub rejected", bc.add_transaction_to_mempool(bad_kem) is False)

        bad_sig = hand_built({"owner_address": owner_addr, "kem_pub": KEM, "sig_pub": "ab"})
        check("wrong-size sig_pub rejected", bc.add_transaction_to_mempool(bad_sig) is False)

        spoof = hand_built({"owner_address": attacker_addr, "kem_pub": KEM, "sig_pub": SIG})
        check("owner_address must match the spending key", bc.add_transaction_to_mempool(spoof) is False)

        low_fee = hand_built({"owner_address": owner_addr, "kem_pub": KEM, "sig_pub": SIG}, fee=1)
        check("fee below anti-spam minimum rejected", bc.add_transaction_to_mempool(low_fee) is False)

        pay_out = hand_built({"owner_address": owner_addr, "kem_pub": KEM, "sig_pub": SIG}, out_addr=attacker_addr)
        check("output to a non-owner rejected", bc.add_transaction_to_mempool(pay_out) is False)

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
