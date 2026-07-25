"""Independent check of the Rescue permutation and the field-native construction.

The gap this closes
-------------------
Before the hash swap, Python hashed with `hashlib` and Rust with the `sha3`
crate -- two independent implementations, so cross-runtime agreement was
evidence.

After the swap, Python gets Rescue by delegating to the Rust binary. "Python and
Rust agree on a Rescue digest" is then tautological: they are the same code. A
bug in the permutation, or in the domain-separated sponge built on it, would be
invisible to every cross-runtime test we have.

This restores independence by recomputing the node's digests with a separate
pure-Python implementation (tests/rescue_reference.py), which is itself pinned to
the **upstream Sage reference vector** from winter-crypto's test suite.

    Sage (upstream, independent)  <--  rescue_reference  -->  Rust (the node path)

Pure Python is ~853 us per permutation, so this is deliberately scoped to a few
dozen digests rather than a tree. That is exactly the trade Phase 2 identified:
disqualified for production, entirely fine as an oracle.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "wepo-blockchain", "core"))

import rescue_reference as R  # noqa: E402
import shielded as S  # noqa: E402

FAILURES = []


def check(label, ok):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILURES.append(label)


def field(x: bytes) -> bytes:
    return len(x).to_bytes(4, "little") + x


def main():
    print("Rescue permutation, independent oracle:")

    try:
        R.self_check()
        check("pure-Python Rescue matches the upstream Sage reference vector", True)
    except AssertionError as exc:
        check(f"pure-Python Rescue matches Sage reference vector -- {exc}", False)
        return 1

    check("consensus hash is Rescue", S.POOL_HASH_ALGORITHM == "rescue-rp64-256")

    # -- the byte-oriented hash, still used for the bundle statement digest ---
    print("\nByte-oriented pool hash (bundle statement digest path):")
    for label, data in [
        ("empty", b""),
        ("abc", b"abc"),
        ("103-byte tagged buffer", field(b"tag") + field(bytes(32)) + field(bytes(32))),
    ]:
        check(
            f"pool hash agrees: {label}",
            S.active_hash_algorithm().fn(data) == R.pool_hash(data),
        )

    # -- the field-native hash, which is what the circuit proves --------------
    print("\nField-native H_dom (the in-circuit construction):")
    for label, dom, els in [
        ("empty element list", S.DOMAIN_LEAF, []),
        ("single element", S.DOMAIN_LEAF, [1]),
        ("4 elements (leaf)", S.DOMAIN_LEAF, [1, 2, 3, 4]),
        ("8 elements (node, full rate)", S.DOMAIN_NODE, list(range(8))),
        ("9 elements (spills the rate)", S.DOMAIN_NOTE, list(range(9))),
        ("13 elements (note commitment)", S.DOMAIN_NOTE, list(range(13))),
    ]:
        check(
            f"H_dom agrees: {label}",
            S.field_hash(dom, els) == R.field_hash(dom, els),
        )

    # domain separation must actually separate
    check(
        "different domains give different digests",
        S.field_hash(S.DOMAIN_LEAF, [1, 2, 3, 4])
        != S.field_hash(S.DOMAIN_NODE, [1, 2, 3, 4]),
    )
    check(
        "empty leaf digest is not the zero state",
        S.field_hash(S.DOMAIN_LEAF, []) != bytes(32),
    )

    # -- the empty-subtree ladder: 33 chained digests -------------------------
    print("\nEmpty-subtree ladder (33 levels) recomputed independently:")
    empty = [R.field_hash(S.DOMAIN_LEAF, [])]
    for _ in range(S.MERKLE_DEPTH):
        prev = R.bytes_to_field_elements(empty[-1])
        empty.append(R.field_hash(S.DOMAIN_NODE, prev + prev))
    check("every empty root agrees", empty == list(S.EMPTY_ROOTS))

    # -- note derivation ------------------------------------------------------
    print("\nNote derivation recomputed independently:")
    sk = bytes.fromhex("01" * 32)
    div = bytes(11)
    sk_els = R.bytes_to_field_elements(sk)

    nk = R.field_hash(S.DOMAIN_NULLIFIER_KEY, sk_els)
    check("nullifier key agrees", nk == S.derive_nullifier_key(sk))

    pk_d = R.field_hash(
        S.DOMAIN_DIVERSIFIED_KEY, sk_els + R.encode_bytes_as_field_elements(div)
    )
    check("diversified key agrees", pk_d == S.derive_diversified_key(sk, div))

    rho = S.field_elements_to_bytes([11, 12, 13, 14])
    rcm = S.field_elements_to_bytes([21, 22, 23, 24])
    note = S.Note(value=42, pk_d=pk_d, rho=rho, rcm=rcm)

    cm = R.field_hash(
        S.DOMAIN_NOTE,
        [42]
        + R.bytes_to_field_elements(pk_d)
        + R.bytes_to_field_elements(rho)
        + R.bytes_to_field_elements(rcm),
    )
    check("note commitment agrees", cm == note.commitment())

    nf = R.field_hash(
        S.DOMAIN_NULLIFIER,
        R.bytes_to_field_elements(nk) + R.bytes_to_field_elements(rho),
    )
    check("nullifier agrees", nf == note.nullifier(nk))

    # -- tree operations ------------------------------------------------------
    print("\nTree operations recomputed independently:")
    leaf = R.field_hash(S.DOMAIN_LEAF, R.bytes_to_field_elements(cm))
    check("leaf hash agrees", leaf == S._leaf_hash(cm))
    node = R.field_hash(
        S.DOMAIN_NODE,
        R.bytes_to_field_elements(leaf) + R.bytes_to_field_elements(empty[0]),
    )
    check("node hash agrees", node == S._node_hash(leaf, empty[0]))

    # -- negative controls ----------------------------------------------------
    print("\nNegative controls:")
    check(
        "oracle rejects a tampered input",
        R.field_hash(S.DOMAIN_LEAF, [1, 2, 3, 4])
        != R.field_hash(S.DOMAIN_LEAF, [1, 2, 3, 5]),
    )
    check(
        "element count is bound (trailing zero changes the digest)",
        R.field_hash(S.DOMAIN_LEAF, [1, 2, 3, 4])
        != R.field_hash(S.DOMAIN_LEAF, [1, 2, 3, 4, 0]),
    )
    try:
        S.bytes_to_field_elements(b"\xff" * 8, "probe")
        check("non-canonical limb rejected", False)
    except S.ShieldedError:
        check("non-canonical limb rejected", True)

    print()
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} CHECK(S) FAILED")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
