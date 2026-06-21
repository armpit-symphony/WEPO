#!/usr/bin/env python3
"""
Messaging blind-relay verification tests (server-side security checks).

Proves the relay's two trust anchors:
  * key registry binding: a messaging key bundle is accepted only when signed by
    the account's spend key AND the address equals H(spend pubkey) — so the relay
    cannot substitute keys (no MITM)
  * inbox fetch auth: only the address owner, via a fresh spend-key signature, can
    fetch their envelopes; stale or wrong-key requests are rejected

The relay never decrypts content; these checks are all it enforces.

Run: python3 tests/test_messaging_relay.py
"""
import os
import sys
import time

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from dilithium import generate_dilithium_keypair, sign_with_dilithium  # noqa: E402
from address_utils import generate_wepo_address  # noqa: E402
import messaging_relay as relay  # noqa: E402

FAILURES = []


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILURES.append(name)


def main():
    # Owner spend key + address (self-custody identity).
    spend = generate_dilithium_keypair()
    spend_pub_hex = spend.public_key.hex()
    address = generate_wepo_address(spend.public_key, address_type="quantum")

    # Published messaging public keys (values are opaque to these checks).
    kem_pub_hex = ("aa" * 1184)
    sig_pub_hex = ("bb" * 1312)

    # --- key registry binding ---
    digest = relay.key_registry_digest(address, kem_pub_hex, sig_pub_hex)
    good_sig = sign_with_dilithium(digest, spend.private_key).hex()
    check("valid spend-signed, address-bound bundle is accepted",
          relay.verify_key_binding(address, kem_pub_hex, sig_pub_hex, spend_pub_hex, good_sig) is True)

    # Attacker tries to publish keys for someone else's address.
    attacker = generate_dilithium_keypair()
    atk_digest = relay.key_registry_digest(address, kem_pub_hex, sig_pub_hex)
    atk_sig = sign_with_dilithium(atk_digest, attacker.private_key).hex()
    check("bundle signed by a non-owner key is rejected (no key hijack)",
          relay.verify_key_binding(address, kem_pub_hex, sig_pub_hex,
                                   attacker.public_key.hex(), atk_sig) is False)

    # Tampered keys (signature no longer matches the published kem/sig pubkeys).
    check("tampered key bundle is rejected",
          relay.verify_key_binding(address, "cc" * 1184, sig_pub_hex, spend_pub_hex, good_sig) is False)

    # Address that doesn't match the spend key.
    check("address not equal to H(spend pubkey) is rejected",
          relay.verify_key_binding("wepo1qbogusaddress", kem_pub_hex, sig_pub_hex, spend_pub_hex, good_sig) is False)

    # --- inbox fetch authorization ---
    now = int(time.time())
    fetch_sig = sign_with_dilithium(relay.fetch_auth_digest(address, now), spend.private_key).hex()
    check("fresh owner-signed fetch is authorized",
          relay.verify_fetch_auth(address, spend_pub_hex, fetch_sig, now, now=now) is True)

    # Stale request (replay window exceeded).
    old_ts = now - (relay.FETCH_AUTH_MAX_SKEW + 60)
    stale_sig = sign_with_dilithium(relay.fetch_auth_digest(address, old_ts), spend.private_key).hex()
    check("stale fetch request is rejected",
          relay.verify_fetch_auth(address, spend_pub_hex, stale_sig, old_ts, now=now) is False)

    # Someone else trying to fetch this address's inbox.
    other_sig = sign_with_dilithium(relay.fetch_auth_digest(address, now), attacker.private_key).hex()
    check("fetch signed by a non-owner is rejected",
          relay.verify_fetch_auth(address, attacker.public_key.hex(), other_sig, now, now=now) is False)

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
