#!/usr/bin/env python3
"""
Shielded pool substrate tests (wepo-blockchain/core/shielded.py).

Covers the parts of Ghost transfers that are sound today: note commitments, the
Merkle accumulator, nullifier derivation and the double-spend set, anchors, and
bundle statement binding. Also pins the safety default -- an unregistered proof
verifier must reject everything, so an unfinished pool cannot accept value.

Run: python3 tests/test_shielded_pool.py
"""
import os
import secrets
import sys

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

import shielded as S  # noqa: E402

FAILURES = []


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


def raises(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except S.ShieldedError:
        return True
    except Exception:
        return False
    return False


def make_note(value=1000, sk=None):
    sk = sk or secrets.token_bytes(32)
    pk_d = S.derive_diversified_key(sk, b"\x00" * 11)
    return sk, S.random_note(value, pk_d)


def test_hashing():
    print("Domain separation and unambiguous encoding:")
    check("tagged_hash differs by tag",
          S.tagged_hash(b"A", b"x") != S.tagged_hash(b"B", b"x"))
    # Without length prefixes H("01","2") == H("0","12"). This is the classic
    # concatenation ambiguity that lets one committed value be reread as another.
    check("field splits do not collide",
          S.tagged_hash(b"T", b"01", b"2") != S.tagged_hash(b"T", b"0", b"12"))
    cm = secrets.token_bytes(32)
    check("leaf and node hashes are separated",
          S._leaf_hash(cm) != S._node_hash(cm, cm))


def test_hash_agnostic():
    print("\nSwappable pool hash:")
    import hashlib

    check("default algorithm is the consensus constant",
          S.active_hash_algorithm().name == S.POOL_HASH_ALGORITHM
          == "rescue-rp64-256")

    # Pin the wire encoding: tag and parts are length-prefixed, then hashed once.
    # Stated against the *active* algorithm so this tests the encoding rather
    # than the hash -- it is unchanged by the SHA3 -> Rescue swap, which is the
    # point. The encoding is consensus-critical independently of which hash runs.
    buf = S._field(b"tag") + S._field(b"a") + S._field(b"bb")
    check("tagged_hash is one digest over length-prefixed tag and parts",
          S.tagged_hash(b"tag", b"a", b"bb") == S.active_hash_algorithm().fn(buf))

    # Pin the concrete bytes under SHA3 as well, where hashlib is an independent
    # implementation. Also exercises the swap context in both directions.
    with S.using_hash_algorithm("sha3-256"):
        check("tagged_hash encoding is pinned to length-prefixed SHA3-256",
              S.tagged_hash(b"tag", b"a", b"bb") == hashlib.sha3_256(buf).digest())

    check("wrong digest size rejected at registration",
          raises(S.register_hash_algorithm,
                 S.HashAlgorithm("too-short", 16, lambda d: b"\x00" * 16)))
    check("non-HashAlgorithm rejected", raises(S.register_hash_algorithm, object()))
    check("algorithm whose fn lies about its width rejected",
          raises(S.register_hash_algorithm,
                 S.HashAlgorithm("liar", 32, lambda d: b"\x00" * 8)))
    check("unknown algorithm rejected", raises(S._activate_hash_algorithm, "nope"))

    # Stand-in for a future ZK-friendly hash: proves the seam works end to end
    # without waiting on the Rust side.
    S.register_hash_algorithm(
        S.HashAlgorithm("blake2b-256", 32,
                        lambda d: hashlib.blake2b(d, digest_size=32).digest()))
    check("registered algorithm is listed",
          "blake2b-256" in S.available_hash_algorithms())

    sk, note = make_note(1234)
    baseline_cm = note.commitment()
    baseline_empty = S.EMPTY_ROOTS[S.MERKLE_DEPTH]

    tree = S.NoteCommitmentTree()
    for i in range(3):
        tree.append(S.Note(value=i, pk_d=note.pk_d, rho=bytes([i]) * 32,
                           rcm=bytes([i + 1]) * 32).commitment())
    baseline_root = tree.root()

    with S.using_hash_algorithm("blake2b-256"):
        check("commitment changes under a different hash",
              note.commitment() != baseline_cm)
        # The empty-subtree ladder is hash-derived; a swap that forgot to rebuild
        # it would leave a tree that looks fine but computes wrong roots.
        check("EMPTY_ROOTS rebuilt on swap",
              S.EMPTY_ROOTS[S.MERKLE_DEPTH] != baseline_empty)

        alt_tree = S.NoteCommitmentTree()
        alt_commitments = []
        for i in range(3):
            cm = S.Note(value=i, pk_d=note.pk_d, rho=bytes([i]) * 32,
                        rcm=bytes([i + 1]) * 32).commitment()
            alt_commitments.append(cm)
            alt_tree.append(cm)
        check("tree root differs under a different hash",
              alt_tree.root() != baseline_root)
        check("paths still verify under the swapped hash",
              all(alt_tree.path(i).compute_root(alt_commitments[i]) == alt_tree.root()
                  for i in range(3)))

    check("algorithm restored after the context exits",
          S.active_hash_algorithm().name == S.POOL_HASH_ALGORITHM)
    check("commitment restored after the context exits",
          note.commitment() == baseline_cm)
    check("EMPTY_ROOTS restored after the context exits",
          S.EMPTY_ROOTS[S.MERKLE_DEPTH] == baseline_empty)


def test_field_element_encoding():
    print("\nCanonical bytes -> Goldilocks field elements:")
    enc = S.encode_bytes_as_field_elements

    check("empty input encodes to just the length", enc(b"") == [0])
    check("length leads the encoding", enc(b"abc")[0] == 3)
    check("7 bytes is one chunk", len(enc(b"a" * 7)) == 2)
    check("8 bytes spills to two chunks", len(enc(b"a" * 8)) == 3)
    check("chunks are little-endian",
          enc(b"\x01\x02")[1] == 0x0201)

    # 7 bytes rather than 8: a full 64-bit chunk can exceed p and would need
    # reduction, which is not injective.
    check("every element is a canonical field element",
          all(0 <= e < S.GOLDILOCKS_MODULUS
              for e in enc(bytes(range(256)))))
    check("max chunk stays below the modulus",
          enc(b"\xff" * 7)[1] == (1 << 56) - 1 < S.GOLDILOCKS_MODULUS)

    # The length element is what makes padding unambiguous -- without it,
    # trailing zero bytes and zero padding are indistinguishable.
    check("trailing zeros are distinguishable from padding",
          enc(b"\x01") != enc(b"\x01\x00"))
    check("distinct inputs encode distinctly",
          len({tuple(enc(bytes([i]) * n)) for i in (0, 1) for n in (0, 1, 7, 8, 15)}) == 9)

    check("non-bytes rejected", raises(enc, "not bytes"))

    # A realistic node hash: tagged_hash(TAG_NODE, left, right) is ~90 bytes,
    # which is exactly where Winterfell's Rp64_256::hash() panics. The encoding
    # must handle it, since every internal Merkle node goes through this path.
    node_input = S._field(S._TAG_NODE) + S._field(b"\x11" * 32) + S._field(b"\x22" * 32)
    check("realistic node-hash input encodes cleanly",
          len(node_input) > 56 and len(node_input) % 7 != 0
          and all(0 <= e < S.GOLDILOCKS_MODULUS
                  for e in enc(node_input)))


def test_note_commitment():
    print("\nNote commitments (binding + hiding):")
    sk, note = make_note(1000)

    check("commitment is deterministic", note.commitment() == note.commitment())

    # Binding: changing any committed field changes the commitment.
    other_value = S.Note(value=1001, pk_d=note.pk_d, rho=note.rho, rcm=note.rcm)
    check("different value -> different commitment",
          other_value.commitment() != note.commitment())

    other_pk = S.Note(value=note.value, pk_d=secrets.token_bytes(32),
                      rho=note.rho, rcm=note.rcm)
    check("different pk_d -> different commitment",
          other_pk.commitment() != note.commitment())

    # Hiding: same value, fresh randomness -> unlinkable commitment. This is what
    # the legacy XOR commitment failed at, since it was deterministic in (v, r).
    twin = S.random_note(1000, note.pk_d)
    check("same value, fresh rcm -> different commitment",
          twin.commitment() != note.commitment())

    check("negative value rejected", raises(S.Note, -1, note.pk_d, note.rho, note.rcm))
    check("oversized value rejected",
          raises(S.Note, S.MAX_NOTE_VALUE + 1, note.pk_d, note.rho, note.rcm))
    check("bool value rejected", raises(S.Note, True, note.pk_d, note.rho, note.rcm))
    check("short pk_d rejected", raises(S.Note, 1, b"\x00" * 31, note.rho, note.rcm))


def test_nullifier():
    print("\nNullifier derivation:")
    sk, note = make_note()
    nk = S.derive_nullifier_key(sk)

    check("nullifier is deterministic", note.nullifier(nk) == note.nullifier(nk))
    check("nullifier needs the right nk",
          note.nullifier(nk) != note.nullifier(S.derive_nullifier_key(secrets.token_bytes(32))))

    # Two notes of identical value to the same key must still nullify differently,
    # otherwise spending one would falsely mark the other spent.
    twin = S.random_note(note.value, note.pk_d)
    check("distinct notes -> distinct nullifiers", twin.nullifier(nk) != note.nullifier(nk))

    check("nk derivation is domain separated from pk_d",
          S.derive_nullifier_key(sk) != S.derive_diversified_key(sk, b"\x00" * 11))


def test_merkle():
    print("\nNote commitment tree:")
    tree = S.NoteCommitmentTree()
    empty_root = tree.root()

    commitments = []
    for i in range(8):
        _, note = make_note(100 + i)
        cm = note.commitment()
        commitments.append(cm)
        position = tree.append(cm)
        check(f"append returns position {i}", position == i)

    check("root changes once notes are added", tree.root() != empty_root)

    root = tree.root()
    ok = all(tree.path(i).compute_root(commitments[i]) == root for i in range(8))
    check("every authentication path recomputes the root", ok)

    # Wrong note at a valid position must not authenticate.
    check("path does not authenticate a different commitment",
          tree.path(3).compute_root(commitments[4]) != root)

    # Tampered sibling must not authenticate.
    path = tree.path(2)
    tampered = S.MerklePath(position=2, siblings=list(path.siblings))
    tampered.siblings[0] = secrets.token_bytes(32)
    check("tampered sibling breaks the path",
          tampered.compute_root(commitments[2]) != root)

    # Same siblings, wrong claimed position -> different traversal, different root.
    moved = S.MerklePath(position=3, siblings=list(path.siblings))
    check("wrong claimed position breaks the path",
          moved.compute_root(commitments[2]) != root)

    check("path for an unoccupied position rejected", raises(tree.path, 99))
    check("short commitment rejected", raises(tree.append, b"\x00" * 31))
    check("malformed path length rejected",
          raises(S.MerklePath, 0, [secrets.token_bytes(32)] * 3))

    # Appending must not invalidate the root of a *previously anchored* state --
    # old roots stay valid via AnchorSet, which is what keeps witnesses usable.
    before = tree.root()
    _, extra = make_note(999)
    tree.append(extra.commitment())
    check("appending changes the current root", tree.root() != before)


def test_nullifier_set():
    print("\nNullifier set (double-spend guard):")
    nfset = S.NullifierSet()
    nf1, nf2 = secrets.token_bytes(32), secrets.token_bytes(32)

    nfset.add(nf1, 10)
    check("nullifier recorded", nf1 in nfset)
    check("height recorded", nfset.height_of(nf1) == 10)
    check("unspent nullifier absent", nf2 not in nfset)
    check("re-spending the same nullifier rejected", raises(nfset.add, nf1, 11))

    # A bundle that double-spends against itself must leave no partial state.
    fresh = S.NullifierSet()
    dup = secrets.token_bytes(32)
    check("bundle with an internal duplicate rejected",
          raises(fresh.add_bundle, [nf2, dup, dup], 12))
    check("failed bundle recorded nothing", len(fresh) == 0)

    fresh.add_bundle([nf1, nf2], 12)
    check("valid bundle recorded atomically", len(fresh) == 2)
    check("bundle conflicting with history rejected",
          raises(fresh.add_bundle, [secrets.token_bytes(32), nf1], 13))

    fresh.rollback([nf1, nf2])
    check("rollback clears a disconnected block", len(fresh) == 0)
    check("malformed nullifier rejected", raises(nfset.add, b"\x00" * 16, 1))


def test_anchors():
    print("\nAnchor window:")
    anchors = S.AnchorSet(window=5)
    old = secrets.token_bytes(32)
    anchors.add(old, 1)
    check("fresh anchor accepted", anchors.is_valid(old))

    recent = secrets.token_bytes(32)
    anchors.add(recent, 4)
    check("anchor still valid inside the window", anchors.is_valid(old))

    anchors.add(secrets.token_bytes(32), 20)
    check("anchor expires outside the window", not anchors.is_valid(old))
    check("unknown anchor rejected", not anchors.is_valid(secrets.token_bytes(32)))
    check("zero window rejected", raises(S.AnchorSet, 0))


def make_bundle(anchor, n_spends=1, n_outputs=2, value_balance=0, proof=b"proof"):
    spends = [S.SpendDescription(anchor=anchor, nullifier=secrets.token_bytes(32))
              for _ in range(n_spends)]
    outputs = [S.OutputDescription(commitment=secrets.token_bytes(32), enc_note=b"ct")
               for _ in range(n_outputs)]
    return S.ShieldedBundle(spends=spends, outputs=outputs,
                            value_balance=value_balance, proof=proof)


def test_bundle_statement():
    print("\nBundle statement binding:")
    anchor = secrets.token_bytes(32)
    sighash = secrets.token_bytes(32)
    bundle = make_bundle(anchor)
    digest = bundle.statement_digest(sighash)

    check("statement digest is deterministic",
          bundle.statement_digest(sighash) == digest)

    # A proof must not be liftable onto a different transaction.
    check("digest binds the sighash",
          bundle.statement_digest(secrets.token_bytes(32)) != digest)

    swapped = S.ShieldedBundle(
        spends=list(bundle.spends),
        outputs=[S.OutputDescription(commitment=secrets.token_bytes(32), enc_note=b"ct")]
                + list(bundle.outputs[1:]),
        value_balance=bundle.value_balance,
        proof=bundle.proof,
    )
    check("digest binds output commitments", swapped.statement_digest(sighash) != digest)

    rebalanced = S.ShieldedBundle(spends=list(bundle.spends), outputs=list(bundle.outputs),
                                 value_balance=5000, proof=bundle.proof)
    check("digest binds value_balance", rebalanced.statement_digest(sighash) != digest)

    reanchored = S.ShieldedBundle(
        spends=[S.SpendDescription(anchor=secrets.token_bytes(32),
                                   nullifier=bundle.spends[0].nullifier)],
        outputs=list(bundle.outputs), value_balance=0, proof=bundle.proof)
    check("digest binds the anchor", reanchored.statement_digest(sighash) != digest)

    print("\nBundle shape rules:")
    check("empty bundle rejected", raises(S.ShieldedBundle().check_shape))

    nf = secrets.token_bytes(32)
    dup = S.ShieldedBundle(
        spends=[S.SpendDescription(anchor=anchor, nullifier=nf),
                S.SpendDescription(anchor=anchor, nullifier=nf)],
        outputs=list(bundle.outputs), proof=b"p")
    check("duplicate nullifier in bundle rejected", raises(dup.check_shape))

    mixed = S.ShieldedBundle(
        spends=[S.SpendDescription(anchor=anchor, nullifier=secrets.token_bytes(32)),
                S.SpendDescription(anchor=secrets.token_bytes(32),
                                   nullifier=secrets.token_bytes(32))],
        outputs=list(bundle.outputs), proof=b"p")
    check("mixed anchors in one bundle rejected", raises(mixed.check_shape))

    check("non-int value_balance rejected",
          raises(S.ShieldedBundle(spends=list(bundle.spends), outputs=list(bundle.outputs),
                                  value_balance=True, proof=b"p").check_shape))


def test_consensus_verification():
    print("\nConsensus bundle verification (default = closed pool):")
    anchor = secrets.token_bytes(32)
    sighash = secrets.token_bytes(32)
    anchors = S.AnchorSet()
    anchors.add(anchor, 100)
    nfset = S.NullifierSet()

    bundle = make_bundle(anchor)

    # THE safety property: with no audited verifier registered, a structurally
    # perfect bundle is still refused. An accept-by-default stub here is exactly
    # the legacy privacy.py bug.
    ok, reason = S.verify_bundle(bundle, sighash, anchors, nfset)
    check("well-formed bundle rejected while no verifier is registered", not ok)
    check("rejection reason is the proof, not the shape", reason == "invalid shielded proof")
    check("verifier_is_audited() reports False", S.verifier_is_audited() is False)

    ok, reason = S.verify_bundle(make_bundle(secrets.token_bytes(32)), sighash, anchors, nfset)
    check("unknown anchor rejected before proof work", not ok and "anchor" in reason)

    spent = make_bundle(anchor)
    nfset.add(spent.spends[0].nullifier, 99)
    ok, reason = S.verify_bundle(spent, sighash, anchors, nfset)
    check("already-spent nullifier rejected", not ok and "double spend" in reason)

    empty_proof = make_bundle(anchor, proof=b"")
    ok, reason = S.verify_bundle(empty_proof, sighash, anchors, nfset)
    check("missing proof rejected", not ok and "no proof" in reason)

    # A registered verifier is honoured -- proving the seam works -- but only an
    # audited implementation may ever be installed in production.
    class AcceptOnlyThisStatement:
        def __init__(self, digest):
            self.digest = digest

        def verify(self, statement_digest, proof):
            return statement_digest == self.digest and proof == b"proof"

    good = make_bundle(anchor)
    try:
        S.register_verifier(AcceptOnlyThisStatement(good.statement_digest(sighash)))
        ok, reason = S.verify_bundle(good, sighash, anchors, nfset)
        check("registered verifier can accept a matching bundle", ok)
        check("verifier_is_audited() reports True once registered",
              S.verifier_is_audited() is True)

        ok, _ = S.verify_bundle(good, secrets.token_bytes(32), anchors, nfset)
        check("same proof rejected against a different sighash", not ok)

        check("verifier without verify() rejected", raises(S.register_verifier, object()))
    finally:
        S.register_verifier(S.RejectAllVerifier())

    check("default restored to reject-all", S.verifier_is_audited() is False)


def test_end_to_end_flow():
    print("\nEnd-to-end note lifecycle (everything except the ZK proof):")
    tree = S.NoteCommitmentTree()
    nfset = S.NullifierSet()
    anchors = S.AnchorSet()

    alice_sk = secrets.token_bytes(32)
    alice_nk = S.derive_nullifier_key(alice_sk)
    alice_pk = S.derive_diversified_key(alice_sk, b"\x01" * 11)

    note = S.random_note(50_000, alice_pk)
    position = tree.append(note.commitment())
    anchor = tree.root()
    anchors.add(anchor, 1)

    # Alice can prove membership of her note.
    path = tree.path(position)
    check("Alice's note authenticates against the anchor",
          path.compute_root(note.commitment()) == anchor)

    # Decoy traffic must not disturb her witness's anchor.
    for i in range(4):
        _, decoy = make_note(1 + i)
        tree.append(decoy.commitment())
    anchors.add(tree.root(), 2)
    check("earlier anchor remains valid after other notes land",
          anchors.is_valid(anchor))
    check("witness still verifies against the anchor it was taken at",
          path.compute_root(note.commitment()) == anchor)

    # Spending reveals only the nullifier.
    nf = note.nullifier(alice_nk)
    nfset.add_bundle([nf], 3)
    check("spend recorded by nullifier alone", nf in nfset)
    check("second spend of the same note rejected",
          raises(nfset.add_bundle, [nf], 4))

    # An attacker who copies the public commitment cannot produce the nullifier.
    attacker_nk = S.derive_nullifier_key(secrets.token_bytes(32))
    check("attacker cannot derive the nullifier from public data",
          note.nullifier(attacker_nk) != nf)


def main():
    test_hashing()
    test_hash_agnostic()
    test_field_element_encoding()
    test_note_commitment()
    test_nullifier()
    test_merkle()
    test_nullifier_set()
    test_anchors()
    test_bundle_statement()
    test_consensus_verification()
    test_end_to_end_flow()

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
