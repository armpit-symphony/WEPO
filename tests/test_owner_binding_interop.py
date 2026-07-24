#!/usr/bin/env python3
"""JS -> Python owner-binding interop check.

Reads a JS-produced (browser wallet) owner-bound messaging registration on stdin and
verifies it with the SAME code the relay runs (backend/messaging_relay.verify_owner_
binding). This proves the spend-key ownership proof is byte-for-byte interoperable:
the address derivation, the canonical binding digest, and the ML-DSA-44 signature all
agree across languages. Also confirms a non-owner (front-run) proof is rejected.

Run: tests/run_owner_binding_interop.sh
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import messaging_relay as relay  # noqa: E402

FAILURES = []


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILURES.append(name)


def main():
    data = json.load(sys.stdin)
    addr = data["address"]
    kem, sig = data["kem_pub"], data["sig_pub"]

    check("JS-produced owner binding verifies in Python (relay accepts)",
          relay.verify_owner_binding(addr, kem, sig, data["owner_sig_pub"], data["owner_sig"]) is True)

    check("JS front-run proof (non-owner spend key) is rejected in Python",
          relay.verify_owner_binding(addr, kem, sig,
                                     data["attacker_owner_sig_pub"], data["attacker_owner_sig"]) is False)

    # Tampering the registered bundle invalidates the JS-produced binding.
    check("tampered bundle invalidates the JS owner binding in Python",
          relay.verify_owner_binding(addr, "cc" * 1184, sig, data["owner_sig_pub"], data["owner_sig"]) is False)

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
