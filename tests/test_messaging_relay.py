#!/usr/bin/env python3
"""
Messaging blind-relay verification tests (server-side security checks).

Messaging uses a device-local messaging key (ML-DSA), independent of the spend/
funds key, so messaging is click-and-use. The relay enforces:
  * key registration: a bundle is accepted only when self-signed by the messaging
    key (sig_pub) it registers — proving the registrant holds that key
  * inbox fetch auth: only the holder of the messaging key currently registered
    for an address, via a fresh signature, can fetch its envelopes; stale or
    wrong-key requests are rejected

This is the click-and-use convenience path: it is claim-based and does NOT prove
spend-key ownership of the address (that is the on-chain anchor's job). The relay
never decrypts content; these checks are all it enforces.

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
    # A wallet address (the device messaging key is independent of the spend key).
    spend = generate_dilithium_keypair()
    address = generate_wepo_address(spend.public_key, address_type="quantum")

    # Device messaging key (this is what the relay authenticates).
    msg = generate_dilithium_keypair()
    sig_pub_hex = msg.public_key.hex()
    kem_pub_hex = ("aa" * 1184)  # opaque to these checks

    # --- key registration (self-signed by the messaging key) ---
    digest = relay.key_registry_digest(address, kem_pub_hex, sig_pub_hex)
    good_sig = sign_with_dilithium(digest, msg.private_key).hex()
    check("valid self-signed messaging bundle is accepted",
          relay.verify_key_registration(address, kem_pub_hex, sig_pub_hex, good_sig) is True)

    # Signature by a different key than the sig_pub being registered → rejected.
    attacker = generate_dilithium_keypair()
    atk_sig = sign_with_dilithium(digest, attacker.private_key).hex()
    check("bundle whose signature doesn't match its sig_pub is rejected",
          relay.verify_key_registration(address, kem_pub_hex, sig_pub_hex, atk_sig) is False)

    # Tampered keys (signature no longer matches the published kem field).
    check("tampered key bundle is rejected",
          relay.verify_key_registration(address, "cc" * 1184, sig_pub_hex, good_sig) is False)

    # --- inbox fetch authorization (against the registered messaging key) ---
    now = int(time.time())
    fetch_sig = sign_with_dilithium(relay.fetch_auth_digest(address, now), msg.private_key).hex()
    check("fresh fetch signed by the registered key is authorized",
          relay.verify_fetch_auth(address, sig_pub_hex, fetch_sig, now, now=now) is True)

    # Stale request (replay window exceeded).
    old_ts = now - (relay.FETCH_AUTH_MAX_SKEW + 60)
    stale_sig = sign_with_dilithium(relay.fetch_auth_digest(address, old_ts), msg.private_key).hex()
    check("stale fetch request is rejected",
          relay.verify_fetch_auth(address, sig_pub_hex, stale_sig, old_ts, now=now) is False)

    # Someone whose key is NOT the one registered for the address cannot fetch.
    other_sig = sign_with_dilithium(relay.fetch_auth_digest(address, now), attacker.private_key).hex()
    check("fetch signed by a non-registered key is rejected",
          relay.verify_fetch_auth(address, sig_pub_hex, other_sig, now, now=now) is False)

    # No key registered for the address → no inbox access.
    check("fetch against an unregistered address is rejected",
          relay.verify_fetch_auth(address, None, fetch_sig, now, now=now) is False)

    # --- first-write-wins + incumbent-authorized key rotation ---
    # `msg` is the incumbent (currently registered) messaging key from above; the
    # attacker holds a different, valid messaging key and tries to take over.
    new_sig_pub = attacker.public_key.hex()
    new_kem = ("bb" * 1184)

    # First registration for an address (no incumbent) → trust-on-first-use accept.
    allowed, why = relay.registration_action(None, None, address, kem_pub_hex, sig_pub_hex)
    check("first registration (no incumbent) is accepted as TOFU", allowed and why == "tofu")

    # Re-publishing the SAME key is idempotent (the common single-device case).
    allowed, why = relay.registration_action(kem_pub_hex, sig_pub_hex, address, kem_pub_hex, sig_pub_hex)
    check("re-publishing the same key is idempotent", allowed and why == "idempotent")

    # A DIFFERENT key with NO rotation signature is rejected (no silent takeover).
    allowed, why = relay.registration_action(kem_pub_hex, sig_pub_hex, address, new_kem, new_sig_pub, "")
    check("a different key without a rotation signature is rejected (conflict)",
          (not allowed) and why == "conflict")

    # A rotation signed by the INCUMBENT key authorizes the change.
    rot_digest = relay.key_rotation_digest(address, sig_pub_hex, new_kem, new_sig_pub)
    rot_sig = sign_with_dilithium(rot_digest, msg.private_key).hex()
    check("rotation signed by the incumbent key verifies",
          relay.verify_key_rotation(address, sig_pub_hex, new_kem, new_sig_pub, rot_sig) is True)
    allowed, why = relay.registration_action(kem_pub_hex, sig_pub_hex, address, new_kem, new_sig_pub, rot_sig)
    check("incumbent-authorized rotation is accepted", allowed and why == "rotation")

    # A rotation signed by a NON-incumbent key (the attacker signing their own) is rejected.
    bad_rot = sign_with_dilithium(rot_digest, attacker.private_key).hex()
    check("rotation signed by a non-incumbent key is rejected",
          relay.verify_key_rotation(address, sig_pub_hex, new_kem, new_sig_pub, bad_rot) is False)

    # A valid rotation signature does not authorize a DIFFERENT new key (bound to the bundle).
    check("rotation signature is bound to the new bundle it authorizes",
          relay.verify_key_rotation(address, sig_pub_hex, "cc" * 1184, new_sig_pub, rot_sig) is False)

    # --- spend-key OWNERSHIP binding (front-run / squat prevention) ---
    # The owner proves control of `address` by signing the bundle with the SPEND
    # key whose public key hashes to `address` (same derivation consensus enforces).
    owner_pub_hex = spend.public_key.hex()
    owner_binding = relay.key_owner_binding_digest(address, kem_pub_hex, sig_pub_hex)
    owner_sig = sign_with_dilithium(owner_binding, spend.private_key).hex()
    check("owner binding by the address's spend key is accepted",
          relay.verify_owner_binding(address, kem_pub_hex, sig_pub_hex, owner_pub_hex, owner_sig) is True)

    # Front-run attempt: attacker signs a binding for the victim's address with
    # THEIR OWN spend key. Their key does not hash to `address` → rejected.
    atk_owner_pub = attacker.public_key.hex()
    atk_owner_sig = sign_with_dilithium(
        relay.key_owner_binding_digest(address, kem_pub_hex, sig_pub_hex), attacker.private_key).hex()
    check("owner binding signed by a non-owner spend key is rejected (no front-run)",
          relay.verify_owner_binding(address, kem_pub_hex, sig_pub_hex, atk_owner_pub, atk_owner_sig) is False)

    # Lying about the spend pubkey (claim the victim's address but present a key
    # that doesn't hash to it) is rejected by the address-binding check.
    check("owner binding whose spend pubkey doesn't hash to the address is rejected",
          relay.verify_owner_binding(address, kem_pub_hex, sig_pub_hex, atk_owner_pub, owner_sig) is False)

    # Owner binding is bound to the exact bundle: tampering the kem field invalidates it.
    check("owner binding is rejected when the kem bundle is tampered",
          relay.verify_owner_binding(address, "cc" * 1184, sig_pub_hex, owner_pub_hex, owner_sig) is False)

    # Missing owner-binding material is rejected (registration must be owner-bound).
    check("owner binding with missing signature is rejected",
          relay.verify_owner_binding(address, kem_pub_hex, sig_pub_hex, owner_pub_hex, "") is False)

    # A malformed (wrong-length) spend pubkey is rejected before any crypto work.
    check("owner binding with a malformed spend pubkey is rejected",
          relay.verify_owner_binding(address, kem_pub_hex, sig_pub_hex, "ab", owner_sig) is False)

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
