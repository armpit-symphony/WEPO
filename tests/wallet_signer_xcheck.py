#!/usr/bin/env python3
"""
Python half of the wallet-signer cross-check. Verifies the fixture produced by
tests/wallet_signer_xcheck.mjs against the REAL chain:
  * the JS-derived address binds to the JS public key (generate_wepo_address)
  * the JS canonical sighash matches Transaction.get_canonical_sighash
  * the JS ML-DSA-44 signature verifies, and a UTXO owned by the JS address is
    spendable by the signed transaction (validate_transaction == True)

Run via tests/run_wallet_signer_test.sh (which runs the JS half first).
"""
import json
import os
import sys
import shutil
import tempfile

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

from blockchain import WepoBlockchain, Transaction  # noqa: E402
from address_utils import generate_wepo_address  # noqa: E402

FAILURES = []


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILURES.append(name)


def main():
    fx = json.load(open("/tmp/wepo_signer_fixture.json"))
    pub = bytes.fromhex(fx["owner_pubkey"])

    check("JS address binds to JS public key",
          generate_wepo_address(pub, address_type="quantum") == fx["owner_address"])

    tx = Transaction.from_dict(fx["signed_tx"])
    check("JS canonical sighash matches Python",
          tx.get_canonical_sighash().hex() == fx["sighash"])
    check("JS self-verify reported true", fx["js_self_verify"] is True)
    check("JS signature verifies under Python (owner binding)",
          tx.verify_quantum_signature(0, expected_address=fx["owner_address"]) is True)

    tmp = tempfile.mkdtemp(prefix="wepo-signer-xcheck-")
    try:
        bc = WepoBlockchain(data_dir=tmp)
        bc.conn.execute(
            "INSERT INTO utxos (txid, vout, address, amount, script_pubkey, spent) "
            "VALUES (?, ?, ?, ?, ?, FALSE)",
            ("a" * 64, 0, fx["owner_address"], 10 * 100000000, b"output_script"),
        )
        bc.conn.commit()
        check("consensus accepts the JS-signed transaction",
              bc.validate_transaction(tx) is True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
