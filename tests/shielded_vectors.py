#!/usr/bin/env python3
"""
Deterministic cross-runtime test vectors for the shielded pool.

The Rust circuit and the Python node must compute byte-identical note
commitments and Merkle roots. If they disagree the chain splits, and it splits
silently -- both sides keep producing self-consistent trees that simply do not
match. That failure mode has no natural detection point, so it gets a dedicated
harness.

This module emits every distinct hash usage in the pool as JSON. Python is
checked against a committed golden file by `tests/test_shielded_vectors.py`;
the Rust side consumes the same file and must reproduce every digest. See
`tests/vectors/README.md` for the contract.

Regenerate (only when the encoding is intentionally changed):
    python3 tests/shielded_vectors.py > tests/vectors/shielded_sha3-256.json

Generate for a candidate hash (Phase 2 benchmarking):
    python3 tests/shielded_vectors.py blake2b-256
"""
import json
import os
import sys

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

import _backend_shim  # noqa: F401,E402  (must precede `import shielded`)
import shielded as S  # noqa: E402

# Fixed inputs -- no randomness anywhere, or the vectors are not vectors.
SPENDING_KEYS = [bytes([i]) * S.HASH_LEN for i in (1, 2)]
DIVERSIFIERS = [bytes([i]) * 11 for i in (0, 7)]
SIGHASH = bytes(range(32))


def _pattern(seed: int) -> bytes:
    """A fixed 32-byte pattern that varies with `seed` but never randomly."""
    return bytes((seed * 37 + i * 11) & 0xFF for i in range(S.HASH_LEN))


def _sample_notes():
    notes = []
    for i, sk in enumerate(SPENDING_KEYS):
        pk_d = S.derive_diversified_key(sk, DIVERSIFIERS[i])
        for j, value in enumerate((0, 1, 21_000_000_00000000)):
            notes.append(
                S.Note(
                    value=value,
                    pk_d=pk_d,
                    rho=_pattern(i * 10 + j),
                    rcm=_pattern(i * 10 + j + 100),
                )
            )
    return notes


def build_vectors(algorithm: str = S.POOL_HASH_ALGORITHM) -> dict:
    with S.using_hash_algorithm(algorithm):
        notes = _sample_notes()

        # Tags are part of the wire format: Rust must use these exact bytes.
        tags = {
            "leaf": S._TAG_LEAF.hex(),
            "node": S._TAG_NODE.hex(),
            "note": S._TAG_NOTE.hex(),
            "nullifier": S._TAG_NULLIFIER.hex(),
            "nullifier_key": S._TAG_NK.hex(),
            "diversified_key": S._TAG_PKD.hex(),
            "bundle": S._TAG_BUNDLE.hex(),
        }

        # Raw tagged_hash cases, including the pair that collides without
        # length prefixing -- the encoding rule, not just the hash, must match.
        tagged = []
        for tag, parts in [
            (b"WEPO-Test", []),
            (b"WEPO-Test", [b""]),
            (b"WEPO-Test", [b"a", b"bb", b"ccc"]),
            (b"WEPO-Test", [b"01", b"2"]),
            (b"WEPO-Test", [b"0", b"12"]),
            (b"", [b""]),
            (b"WEPO-Test", [bytes(range(256))]),
        ]:
            tagged.append({
                "tag": tag.hex(),
                "parts": [p.hex() for p in parts],
                "digest": S.tagged_hash(tag, *parts).hex(),
            })

        keys = []
        for i, sk in enumerate(SPENDING_KEYS):
            keys.append({
                "spending_key": sk.hex(),
                "nullifier_key": S.derive_nullifier_key(sk).hex(),
                "diversifier": DIVERSIFIERS[i].hex(),
                "diversified_key": S.derive_diversified_key(sk, DIVERSIFIERS[i]).hex(),
            })

        note_vectors = []
        for idx, note in enumerate(notes):
            nk = S.derive_nullifier_key(SPENDING_KEYS[idx // 3])
            note_vectors.append({
                "value": note.value,
                "pk_d": note.pk_d.hex(),
                "rho": note.rho.hex(),
                "rcm": note.rcm.hex(),
                "commitment": note.commitment().hex(),
                "nullifier_key": nk.hex(),
                "nullifier": note.nullifier(nk).hex(),
            })

        # A populated tree with every authentication path, so a Rust
        # implementation is pinned on ordering and on the empty-node ladder,
        # not just on the root.
        tree = S.NoteCommitmentTree()
        commitments = []
        for note in notes:
            cm = note.commitment()
            commitments.append(cm)
            tree.append(cm)

        paths = []
        for position in range(tree.size):
            path = tree.path(position)
            paths.append({
                "position": position,
                "commitment": commitments[position].hex(),
                "siblings": [s.hex() for s in path.siblings],
                "root": path.compute_root(commitments[position]).hex(),
            })

        # A synthetic path at a deep, bit-alternating position.
        #
        # The populated tree only holds six notes, so every position in it has
        # zero bits above level 2 and the right-child branch goes unexercised
        # from there up. Steps 2.1 and 2.2 were originally witnessed at position
        # 0, where EVERY direction bit is zero: the bit column became the zero
        # polynomial, the placement constraint collapsed from degree 2 to 1, and
        # the right-child branch was never exercised at all -- while both steps
        # passed.
        #
        # The position must be APERIODIC, which the first attempt here was not.
        # 0xA5A5A5A5 is A5 repeated, giving the direction bits a period of 8
        # levels = 64 rows -- an exact divisor of the 256-row trace. The bit
        # column then interpolates to a polynomial in x**4 of degree 252 rather
        # than 255, every constraint multiplying by it lands 3-6 below its
        # declared degree, and Winterfell's debug degree assertion is disabled.
        # It fixed the all-zeros degeneracy and introduced a subtler one aimed
        # straight at the Rescue cycle.
        #
        # 0x9E3779B9 (the golden-ratio constant) has no period dividing 32 and
        # both directions occur in every 8-level window. This is not a path in
        # the populated tree; siblings are taken from the empty ladder. It exists
        # purely to pin traversal in both directions at every level, in both
        # runtimes, without perturbing constraint degrees.
        deep_position = 0x9E3779B9
        deep_siblings = [S.EMPTY_ROOTS[level] for level in range(S.MERKLE_DEPTH)]
        deep_path = S.MerklePath(position=deep_position, siblings=deep_siblings)
        deep_commitment = commitments[0]

        merkle = {
            "empty_root_leaf_level": S.EMPTY_ROOTS[0].hex(),
            "synthetic_deep_path": {
                "note": "not a path in the tree above; siblings are empty roots. "
                        "Pins left/right traversal at all 32 levels -- a witness "
                        "with zero direction bits collapses the placement "
                        "constraint and silently skips the right-child branch.",
                "position": deep_position,
                "position_bits": format(deep_position, "032b"),
                "commitment": deep_commitment.hex(),
                "siblings": [s.hex() for s in deep_siblings],
                "root": deep_path.compute_root(deep_commitment).hex(),
            },
            "empty_roots": [r.hex() for r in S.EMPTY_ROOTS],
            # There is no leaf hash: the tree's leaves ARE the commitments,
            # which are already domain-separated digests. The empty-slot
            # sentinel keeps DOMAIN_LEAF alive.
            "empty_leaf_sentinel": S.EMPTY_LEAF.hex(),
            "node_hash_of_first_two_leaves": S._node_hash(
                commitments[0], commitments[1]
            ).hex(),
            "empty_tree_root": S.NoteCommitmentTree().root().hex(),
            "size": tree.size,
            "root": tree.root().hex(),
            "paths": paths,
        }

        # Bundle statement digest -- the circuit's public input. If Rust and
        # Python disagree here, every proof is rejected.
        anchor = tree.root()
        nk0 = S.derive_nullifier_key(SPENDING_KEYS[0])
        bundle = S.ShieldedBundle(
            spends=[
                S.SpendDescription(anchor=anchor, nullifier=notes[0].nullifier(nk0)),
                S.SpendDescription(anchor=anchor, nullifier=notes[1].nullifier(nk0)),
            ],
            outputs=[
                S.OutputDescription(commitment=commitments[3], enc_note=b"\x01\x02"),
                S.OutputDescription(commitment=commitments[4], enc_note=b""),
            ],
            value_balance=-12345,
            proof=b"",
        )

        bundle_vectors = {
            "anchor": anchor.hex(),
            "nullifiers": [nf.hex() for nf in bundle.nullifiers()],
            "commitments": [cm.hex() for cm in bundle.commitments()],
            "value_balance": bundle.value_balance,
            "sighash": SIGHASH.hex(),
            "statement_digest": bundle.statement_digest(SIGHASH).hex(),
        }

        # A shielding bundle: outputs only, positive value_balance, no anchor.
        shield = S.ShieldedBundle(
            spends=[],
            outputs=[S.OutputDescription(commitment=commitments[0], enc_note=b"")],
            value_balance=500_000,
            proof=b"",
        )
        shield_vectors = {
            "note": "outputs only; no anchor, so the empty-tree root is used",
            "commitments": [cm.hex() for cm in shield.commitments()],
            "value_balance": shield.value_balance,
            "sighash": SIGHASH.hex(),
            "statement_digest": shield.statement_digest(SIGHASH).hex(),
        }

        # Bytes -> Goldilocks field elements. Rescue-Prime hashes field
        # elements, not bytes, so this encoding is its own cross-runtime
        # agreement surface -- and it is testable now, before any Rescue
        # implementation exists on either side.
        element_cases = []
        for label, data in [
            ("empty", b""),
            ("abc", b"abc"),
            ("seven_bytes", b"a" * 7),
            ("eight_bytes", b"a" * 8),
            ("trailing_zero", b"\x01\x00"),
            ("max_chunk", b"\xff" * 7),
            ("node_hash_input",
             S._field(S._TAG_NODE) + S._field(b"\x11" * 32) + S._field(b"\x22" * 32)),
            ("long", bytes(range(256))),
        ]:
            element_cases.append({
                "label": label,
                "bytes": data.hex(),
                "byte_len": len(data),
                "elements": [str(e) for e in S.encode_bytes_as_field_elements(data)],
            })

        return {
            "algorithm": algorithm,
            "field": {
                "name": "goldilocks",
                "modulus": str(S.GOLDILOCKS_MODULUS),
                "bytes_per_element": S.FELT_BYTES,
                "note": "leading element is the byte length, then little-endian "
                        "7-byte chunks, final chunk zero-padded; elements are "
                        "decimal strings to survive JSON integer limits",
            },
            "element_encoding": element_cases,
            "hash_len": S.HASH_LEN,
            "merkle_depth": S.MERKLE_DEPTH,
            "max_note_value": S.MAX_NOTE_VALUE,
            "max_shielded_spends": S.MAX_SHIELDED_SPENDS,
            "max_shielded_outputs": S.MAX_SHIELDED_OUTPUTS,
            "shielded_value_bits": S.SHIELDED_VALUE_BITS,
            "field_encoding": {
                "note": "little-endian uint32 length prefix, then the bytes",
                "empty": S._field(b"").hex(),
                "abc": S._field(b"abc").hex(),
            },
            "value_encoding": "note value: little-endian uint64; "
                              "value_balance: little-endian int64",
            "tags": tags,
            "tagged_hash": tagged,
            "key_derivation": keys,
            "notes": note_vectors,
            "merkle": merkle,
            "bundle": bundle_vectors,
            "shielding_bundle": shield_vectors,
        }


def main() -> int:
    algorithm = sys.argv[1] if len(sys.argv) > 1 else S.POOL_HASH_ALGORITHM
    if algorithm not in S.available_hash_algorithms():
        # blake2b-256 exists only as a registered stand-in inside the test suite;
        # register it here too so candidate-hash vectors can be generated.
        import hashlib
        if algorithm == "blake2b-256":
            S.register_hash_algorithm(S.HashAlgorithm(
                "blake2b-256", 32,
                lambda d: hashlib.blake2b(d, digest_size=32).digest()))
        else:
            print(f"unknown algorithm '{algorithm}'; "
                  f"available: {S.available_hash_algorithms()}", file=sys.stderr)
            return 2
    json.dump(build_vectors(algorithm), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
