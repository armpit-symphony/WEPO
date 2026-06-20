#!/usr/bin/env python3
"""
Consensus spend-authorization tests (BLOCKER #1).

Proves that validate_transaction / add_transaction_to_mempool now enforce
cryptographic ownership of spent UTXOs:

  * a correctly Dilithium-signed spend by the UTXO owner is ACCEPTED
  * a spend signed with someone else's key (valid signature, wrong owner) is REJECTED
  * an unsigned/placeholder spend is REJECTED
  * a spend whose outputs were tampered after signing is REJECTED
  * a forged "coinbase" cannot be injected into the mempool to mint coins

Run: python3 tests/test_spend_authorization.py
"""
import os
import sys
import shutil
import tempfile

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

from blockchain import (  # noqa: E402
    WepoBlockchain,
    Transaction,
    TransactionInput,
    TransactionOutput,
    COIN,
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
    kp = generate_dilithium_keypair()
    addr = generate_wepo_address(kp.public_key, address_type="quantum")
    return kp, addr


def insert_utxo(bc, txid, vout, address, amount):
    bc.conn.execute(
        "INSERT INTO utxos (txid, vout, address, amount, script_pubkey, spent) "
        "VALUES (?, ?, ?, ?, ?, FALSE)",
        (txid, vout, address, amount, b"output_script"),
    )
    bc.conn.commit()


def build_spend(owner_addr, recipient_addr, utxo_txid, utxo_vout, in_amount, send_amount, fee):
    inputs = [TransactionInput(prev_txid=utxo_txid, prev_vout=utxo_vout,
                               script_sig=b"signature_placeholder")]
    outputs = [TransactionOutput(value=send_amount, script_pubkey=b"output_script",
                                 address=recipient_addr)]
    change = in_amount - send_amount - fee
    if change > 0:
        outputs.append(TransactionOutput(value=change, script_pubkey=b"change_script",
                                         address=owner_addr))
    return Transaction(version=1, inputs=inputs, outputs=outputs, lock_time=0, fee=fee)


def main():
    tmp = tempfile.mkdtemp(prefix="wepo-auth-test-")
    try:
        bc = WepoBlockchain(data_dir=tmp)

        owner_kp, owner_addr = make_owner()
        attacker_kp, attacker_addr = make_owner()
        _, recipient_addr = make_owner()

        utxo_txid = "a" * 64
        in_amount = 10 * COIN
        insert_utxo(bc, utxo_txid, 0, owner_addr, in_amount)

        send_amount = 3 * COIN
        fee = 10000

        print("Spend authorization enforcement:")

        # 1. Correctly signed by the owner -> ACCEPTED
        tx_ok = build_spend(owner_addr, recipient_addr, utxo_txid, 0, in_amount, send_amount, fee)
        tx_ok.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        check("owner-signed spend is accepted", bc.validate_transaction(tx_ok) is True)

        # 2. Valid signature but WRONG owner key (binding must fail) -> REJECTED
        tx_attacker = build_spend(owner_addr, recipient_addr, utxo_txid, 0, in_amount, send_amount, fee)
        tx_attacker.sign_all_inputs(attacker_kp.private_key, attacker_kp.public_key)
        check("spend signed by non-owner is rejected (owner binding)",
              bc.validate_transaction(tx_attacker) is False)

        # 3. Unsigned / placeholder (default signature_type) -> REJECTED
        tx_unsigned = build_spend(owner_addr, recipient_addr, utxo_txid, 0, in_amount, send_amount, fee)
        check("unsigned placeholder spend is rejected",
              bc.validate_transaction(tx_unsigned) is False)

        # 4. Tamper an output value AFTER signing -> sighash changes -> REJECTED
        tx_tampered = build_spend(owner_addr, recipient_addr, utxo_txid, 0, in_amount, send_amount, fee)
        tx_tampered.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        tx_tampered.outputs[0].value = in_amount - fee  # steal the change
        check("tampered-after-signing spend is rejected",
              bc.validate_transaction(tx_tampered) is False)

        # 5. Re-pointed recipient AFTER signing -> REJECTED
        tx_redirect = build_spend(owner_addr, recipient_addr, utxo_txid, 0, in_amount, send_amount, fee)
        tx_redirect.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        tx_redirect.outputs[0].address = attacker_addr
        check("redirected-output spend is rejected",
              bc.validate_transaction(tx_redirect) is False)

        # 6. Valid signed spend enters mempool; double structures consistent
        tx_mempool = build_spend(owner_addr, recipient_addr, utxo_txid, 0, in_amount, send_amount, fee)
        tx_mempool.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        check("owner-signed spend is admitted to mempool",
              bc.add_transaction_to_mempool(tx_mempool) is True)

        # 7. Forged coinbase cannot be injected into the mempool
        forged_cb = Transaction(
            version=1,
            inputs=[TransactionInput(prev_txid="0" * 64, prev_vout=0xffffffff,
                                     script_sig=b"forged")],
            outputs=[TransactionOutput(value=1_000_000 * COIN, script_pubkey=b"x",
                                       address=attacker_addr)],
            lock_time=0,
            fee=0,
        )
        check("forged coinbase is rejected by mempool",
              bc.add_transaction_to_mempool(forged_cb) is False)

        # 8. Sanity: sighash is stable across signing (digest excludes signature fields)
        tx_stable = build_spend(owner_addr, recipient_addr, utxo_txid, 0, in_amount, send_amount, fee)
        pre = tx_stable.get_canonical_sighash()
        tx_stable.sign_all_inputs(owner_kp.private_key, owner_kp.public_key)
        post = tx_stable.get_canonical_sighash()
        check("canonical sighash is stable before/after signing", pre == post)

        # ---- Protocol-tx flows: masternode register (unsigned -> sign -> submit) ----
        print()
        print("Protocol-tx client-signing (masternode):")
        mn_kp, mn_addr = make_owner()
        height = bc.get_block_height()
        required = bc.get_masternode_collateral_for_height(height)
        col_txid = "c" * 64
        insert_utxo(bc, col_txid, 0, mn_addr, required)

        mn_unsigned = bc.create_masternode(mn_addr, col_txid, 0, ip_address="127.0.0.1",
                                           port=22567, return_unsigned=True)
        # Wire path: serialize -> deserialize before signing
        mn_unsigned = Transaction.from_dict(mn_unsigned.to_dict())
        check("masternode build returns an unsigned tx (rejected before signing)",
              bc.validate_transaction(mn_unsigned) is False)
        mn_unsigned.sign_all_inputs(mn_kp.private_key, mn_kp.public_key)
        mn_signed = Transaction.from_dict(mn_unsigned.to_dict())
        check("operator-signed masternode registration is accepted",
              bc.validate_transaction(mn_signed) is True)

        # Negative: someone else signs the operator's collateral spend -> rejected
        insert_utxo(bc, "c2" + "c" * 62, 0, mn_addr, required)
        mn_attack = bc.create_masternode(mn_addr, "c2" + "c" * 62, 0, ip_address="127.0.0.1",
                                         port=22567, return_unsigned=True)
        mn_attack.sign_all_inputs(attacker_kp.private_key, attacker_kp.public_key)
        check("non-operator-signed masternode registration is rejected",
              bc.validate_transaction(mn_attack) is False)

        # ---- Protocol-tx flows: stake create (unsigned -> sign -> submit) ----
        print()
        print("Protocol-tx client-signing (stake):")
        from blockchain import POS_ACTIVATION_HEIGHT, MIN_STAKE_AMOUNT
        # Staking is gated on activation height; simulate an active chain.
        bc.get_block_height = lambda: POS_ACTIVATION_HEIGHT + 1
        stk_kp, stk_addr = make_owner()
        stake_amount = MIN_STAKE_AMOUNT
        insert_utxo(bc, "d" * 64, 0, stk_addr, stake_amount + 5000)

        stk_unsigned = bc.create_stake(stk_addr, stake_amount, return_unsigned=True)
        stk_unsigned = Transaction.from_dict(stk_unsigned.to_dict())
        check("stake build returns an unsigned tx (rejected before signing)",
              bc.validate_transaction(stk_unsigned) is False)
        stk_unsigned.sign_all_inputs(stk_kp.private_key, stk_kp.public_key)
        stk_signed = Transaction.from_dict(stk_unsigned.to_dict())
        check("staker-signed stake create is accepted",
              bc.validate_transaction(stk_signed) is True)

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
