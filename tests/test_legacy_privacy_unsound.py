#!/usr/bin/env python3
"""
Evidence that `wepo-blockchain/core/privacy.py` is cryptographically unsound.

This is not a regression test for a bug to fix in place — it is the justification
for the ground-up rebuild in `wepo-blockchain/core/shielded.py`, and a standing
guard against anyone re-enabling the legacy privacy path. It constructs forgeries
that the legacy verifiers ACCEPT, using no secret knowledge whatsoever.

If any check here starts failing because the legacy verifier got stricter, that
still does not make it sound; the module must be deleted, not patched.

Run: python3 tests/test_legacy_privacy_unsound.py
"""
import hashlib
import os
import struct
import sys

HERE = os.path.dirname(__file__)
CORE = os.path.join(HERE, "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))
sys.path.insert(0, os.path.abspath(HERE))

import _backend_shim  # noqa: F401,E402  (must precede `import shielded`)

FAILURES = []


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


def main():
    import privacy

    ct = privacy.ConfidentialTransactions()
    size = privacy.CONFIDENTIAL_PROOF_SIZE

    print("Legacy Pedersen commitment is not binding or homomorphic:")

    # C = SHA256(v||G) XOR SHA256(r||H). XOR of two hashes is not a group
    # operation, so commitments do not add: C(a) XOR C(b) != C(a+b). Without
    # homomorphism a verifier cannot check that inputs equal outputs at all.
    c1 = ct.commit_amount(10, b"\x01" * 32)
    c2 = ct.commit_amount(20, b"\x02" * 32)
    c3 = ct.commit_amount(30, b"\x03" * 32)
    combined = bytes(x ^ y for x, y in zip(c1, c2))
    check("C(10) XOR C(20) != C(30) -- commitments are not additive", combined != c3)

    # The blinding factor cancels: two different values committed with the same
    # blinding differ only by the value hash, so a verifier holding a candidate
    # value can confirm it by recomputation. The commitment is not hiding against
    # anyone who can guess the amount -- and payment amounts are highly guessable.
    same_blind = b"\x07" * 32
    a = ct.commit_amount(1_000, same_blind)
    b = ct.commit_amount(1_000, same_blind)
    check("commitment is deterministic -- amount is confirmable by guessing", a == b)

    print("\nLegacy range proof is forgeable with zero knowledge:")

    # A forger picks an arbitrary 32-byte "commitment", never knowing any value or
    # blinding factor, and assembles bytes that satisfy every check the verifier
    # makes. The verifier only recomputes hashes over data the prover supplied.
    fake_commitment = os.urandom(32)
    filler = os.urandom(320)
    body = fake_commitment + filler
    forged_bulletproof = body + hashlib.sha256(body).digest()
    actual_size = len(forged_bulletproof)

    proof_data = bytearray(forged_bulletproof)
    proof_data.extend(b"\x00" * (size - len(proof_data)))
    proof_data = bytes(proof_data[:size])

    min_value, max_value = 0, 2 ** 32
    verification_key = hashlib.sha256(
        fake_commitment + proof_data + struct.pack("<QQ", min_value, max_value)
    ).digest()

    forged = privacy.PrivacyProof(
        proof_type="confidential",
        proof_data=proof_data,
        public_parameters={
            "commitment": fake_commitment.hex(),
            "min_value": min_value,
            "max_value": max_value,
            "proof_size": len(proof_data),
            "actual_bulletproof_size": actual_size,
            "blinding_factor_commitment": os.urandom(32).hex(),
        },
        verification_key=verification_key,
    )

    accepted = ct.verify_range_proof(forged)
    check("legacy verifier ACCEPTS a range proof forged from random bytes", accepted)

    # The same forgery works for an absurd declared range, so "range proof" does
    # not constrain the amount at all: this is how value gets minted from nothing.
    huge_min, huge_max = 0, 2 ** 63 - 1
    forged.public_parameters["min_value"] = huge_min
    forged.public_parameters["max_value"] = huge_max
    forged.verification_key = hashlib.sha256(
        fake_commitment + proof_data + struct.pack("<QQ", huge_min, huge_max)
    ).digest()
    check(
        "legacy verifier ACCEPTS the same forgery for an arbitrary declared range",
        ct.verify_range_proof(forged),
    )

    print("\nLegacy shielded path uses quantum-breakable secp256k1:")
    check("ConfidentialTransactions is bound to SECP256k1",
          getattr(ct, "curve", None) is privacy.SECP256k1)

    print("\nReplacement refuses proofs by default:")
    import shielded
    check("shielded.verifier_is_audited() is False before registration",
          shielded.verifier_is_audited() is False)
    check("RejectAllVerifier rejects the analogous forged bytes",
          shielded.active_verifier().verify(os.urandom(32), proof_data) is False)

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED -- legacy privacy.py is confirmed unsound")
    return 0


if __name__ == "__main__":
    sys.exit(main())
