#!/usr/bin/env python3
"""
Block-explorer privacy-projection tests.

The explorer must never reveal more than the chain already makes public:
  * transparent transfers pass through in full (auditable base layer),
  * shielded (Ghost) transactions expose only shape — never amounts/addresses,
  * coinbase / RWA / key-anchor transactions are labelled from safe fields only.

Run: python3 tests/test_explorer_privacy.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import explorer_privacy as ep  # noqa: E402

FAILURES = []


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILURES.append(name)


def main():
    # --- transparent transfer passes through in full ---
    transparent = {
        "txid": "a" * 64,
        "tx_type": "transfer",
        "fee": 0.0001,
        "timestamp": 1788372000,
        "block_height": 10,
        "confirmations": 3,
        "inputs": [{"prev_txid": "b" * 64, "prev_vout": 0}],
        "outputs": [{"value": 5.0, "address": "wepo1qrecipient0000000000000000000000"}],
        "privacy_proof": False,
        "ring_signature": False,
    }
    v = ep.sanitize_tx(transparent)
    check("transparent tx keeps its output amount", v["outputs"][0].get("value") == 5.0)
    check("transparent tx keeps its recipient address",
          v["outputs"][0].get("address") == "wepo1qrecipient0000000000000000000000")
    check("transparent tx not flagged shielded", v["shielded"] is False)

    # --- shielded via privacy_proof: amounts + addresses must be gone ---
    shielded_pp = dict(transparent, txid="c" * 64, privacy_proof=True)
    v = ep.sanitize_tx(shielded_pp)
    check("shielded (privacy_proof) is flagged", v["shielded"] is True)
    check("shielded output carries NO value", "value" not in v["outputs"][0])
    check("shielded output carries NO address", "address" not in v["outputs"][0])
    check("shielded input carries NO prev_txid", "prev_txid" not in v["inputs"][0])
    check("shielded output count is preserved", len(v["outputs"]) == 1)
    check("shielded tx carries the explanatory note", v.get("note") == ep.SHIELDED_NOTE)
    # Belt-and-suspenders: no plaintext amount/address string leaks anywhere.
    blob = repr(v)
    check("no recipient address leaks in shielded projection", "wepo1qrecipient" not in blob)
    check("no cleartext amount value leaks in shielded projection", "5.0" not in blob)

    # --- shielded via ring_signature marker ---
    shielded_rs = dict(transparent, txid="d" * 64, ring_signature=True)
    check("shielded (ring_signature) is flagged", ep.sanitize_tx(shielded_rs)["shielded"] is True)

    # --- coinbase detection (all-zero prev_txid) ---
    coinbase = dict(transparent, txid="e" * 64,
                    inputs=[{"prev_txid": "0" * 64, "prev_vout": 0xffffffff}])
    check("coinbase is detected", ep.sanitize_tx(coinbase)["coinbase"] is True)
    check("normal tx is not coinbase", ep.sanitize_tx(transparent)["coinbase"] is False)

    # --- RWA creation exposes only safe commitment fields ---
    rwa = dict(transparent, txid="f" * 64, tx_type="rwa_create",
               extra_data={"asset_id": "asset-123", "name": "Deed #7",
                           "asset_type": "property", "asset_hash": "9" * 64,
                           "secret_note": "should-not-appear"})
    v = ep.sanitize_tx(rwa)
    check("rwa surfaces asset_id", v["asset"]["asset_id"] == "asset-123")
    check("rwa surfaces asset_hash", v["asset"]["asset_hash"] == "9" * 64)
    check("rwa does NOT surface unrelated extra_data", "should-not-appear" not in repr(v))

    # --- key-register anchor surfaces owner + note, not raw key material ---
    keyreg = dict(transparent, txid="1" * 64, tx_type="key_register",
                  extra_data={"owner_address": "wepo1qowner", "kem_pub": "aa" * 1184,
                              "sig_pub": "bb" * 1312})
    v = ep.sanitize_tx(keyreg)
    check("key_register surfaces owner", v["messaging_key_anchor"]["owner_address"] == "wepo1qowner")

    # --- defensive: non-dict input ---
    check("non-dict input yields empty projection", ep.sanitize_tx(None) == {})

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
