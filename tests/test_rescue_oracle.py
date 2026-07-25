"""Independent check of the Rescue permutation itself.

The gap this closes
-------------------
Before the swap, Python hashed with `hashlib` and Rust with the `sha3` crate --
two independent implementations, so cross-runtime agreement was evidence.

After the swap, Python gets Rescue by delegating to the Rust binary. "Python and
Rust agree on a Rescue digest" is then tautological: they are the same code. A
bug in the permutation would be invisible to every cross-runtime test we have.

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


def oracle_tagged_hash(tag: bytes, *parts: bytes) -> bytes:
    """tagged_hash rebuilt on top of the independent permutation."""
    buf = field(tag)
    for p in parts:
        buf += field(p)
    return R.pool_hash(buf)


def main():
    print("Rescue permutation, independent oracle:")

    # 1. the oracle itself must match the upstream Sage reference vector
    try:
        R.self_check()
        check("pure-Python Rescue matches the upstream Sage reference vector", True)
    except AssertionError as exc:
        check(f"pure-Python Rescue matches Sage reference vector -- {exc}", False)
        return 1

    check("consensus hash is Rescue", S.POOL_HASH_ALGORITHM == "rescue-rp64-256")
    check("active hash is Rescue", S.active_hash_algorithm().name == "rescue-rp64-256")

    # 2. the node's raw hash must equal the oracle's
    print("\nNode digests recomputed independently:")
    for label, data in [
        ("empty", b""),
        ("abc", b"abc"),
        ("32 zero bytes", bytes(32)),
        ("103-byte node input", field(S._TAG_NODE) + field(bytes(32)) + field(bytes(32))),
    ]:
        check(
            f"pool hash agrees: {label}",
            S.active_hash_algorithm().fn(data) == R.pool_hash(data),
        )

    # 3. tagged_hash, the function every pool digest goes through
    for label, args in [
        ("leaf tag, empty", (S._TAG_LEAF, b"")),
        ("node tag, two children", (S._TAG_NODE, bytes(32), b"\x01" * 32)),
        ("note tag, four parts", (S._TAG_NOTE, (7).to_bytes(8, "little"),
                                  b"\x02" * 32, b"\x03" * 32, b"\x04" * 32)),
    ]:
        check(
            f"tagged_hash agrees: {label}",
            S.tagged_hash(*args) == oracle_tagged_hash(*args),
        )

    # 4. the empty-subtree ladder -- 33 chained digests, so an error at any
    #    level propagates and is caught
    print("\nEmpty-subtree ladder (33 levels) recomputed independently:")
    empty = [oracle_tagged_hash(S._TAG_LEAF, b"")]
    for _ in range(S.MERKLE_DEPTH):
        empty.append(oracle_tagged_hash(S._TAG_NODE, empty[-1], empty[-1]))
    check("every empty root agrees", empty == list(S.EMPTY_ROOTS))
    check("anchor of the empty tree agrees", empty[S.MERKLE_DEPTH] == S.EMPTY_ROOTS[S.MERKLE_DEPTH])

    # 5. a real note commitment and nullifier
    print("\nNote derivation recomputed independently:")
    sk = bytes.fromhex("01" * 32)
    div = bytes(11)
    nk = oracle_tagged_hash(S._TAG_NK, sk)
    pk_d = oracle_tagged_hash(S._TAG_PKD, sk, div)
    check("nullifier key agrees", nk == S.tagged_hash(S._TAG_NK, sk))
    check("diversified key agrees", pk_d == S.tagged_hash(S._TAG_PKD, sk, div))

    rho = bytes.fromhex("0b" * 32)
    rcm = bytes.fromhex("0c" * 32)
    note = S.Note(value=42, pk_d=pk_d, rho=rho, rcm=rcm)
    cm = oracle_tagged_hash(S._TAG_NOTE, (42).to_bytes(8, "little"), pk_d, rho, rcm)
    check("note commitment agrees", cm == note.commitment())
    nf = oracle_tagged_hash(S._TAG_NULLIFIER, nk, rho)
    check("nullifier agrees", nf == note.nullifier(nk))

    # 6. negative control -- the oracle must be capable of disagreeing
    print("\nNegative control:")
    check(
        "oracle rejects a tampered digest",
        R.pool_hash(b"abc") != R.pool_hash(b"abd"),
    )
    check(
        "domain separation holds (leaf tag != node tag on same input)",
        oracle_tagged_hash(S._TAG_LEAF, bytes(32))
        != oracle_tagged_hash(S._TAG_NODE, bytes(32)),
    )

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
