#!/usr/bin/env python3
"""
Pins the shielded pool's wire encoding against committed golden vectors.

Two jobs:
  1. Catch an accidental encoding change in Python. Any drift in a tag, a length
     prefix, an integer width or a hash input reorders or changes digests, and
     every previously-created note becomes unspendable.
  2. Give the Rust circuit something concrete to agree with. Rust reads the same
     JSON and must reproduce every digest -- see tests/vectors/README.md.

If this fails after a *deliberate* encoding change, regenerate the golden file:
    python3 tests/shielded_vectors.py > tests/vectors/shielded_sha3-256.json
and treat it as a consensus change, because it is one.

Run: python3 tests/test_shielded_vectors.py
"""
import json
import os
import sys

HERE = os.path.dirname(__file__)
CORE = os.path.join(HERE, "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))
sys.path.insert(0, os.path.abspath(HERE))

import _backend_shim  # noqa: F401,E402  (must precede `import shielded`)
import shielded as S          # noqa: E402
import shielded_vectors as V  # noqa: E402

GOLDEN = os.path.join(HERE, "vectors", f"shielded_{S.POOL_HASH_ALGORITHM}.json")

FAILURES = []


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


def diff(expected, actual, path=""):
    """Yield human-readable paths where two JSON structures differ."""
    if type(expected) is not type(actual):
        yield f"{path or '<root>'}: type {type(expected).__name__} != {type(actual).__name__}"
        return
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected:
                yield f"{path}.{key}: unexpected"
            elif key not in actual:
                yield f"{path}.{key}: missing"
            else:
                yield from diff(expected[key], actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            yield f"{path}: length {len(expected)} != {len(actual)}"
            return
        for i, (e, a) in enumerate(zip(expected, actual)):
            yield from diff(e, a, f"{path}[{i}]")
    elif expected != actual:
        yield f"{path}: {expected!r} != {actual!r}"


# The empty-slot sentinel and the empty-tree anchor, pinned as literals.
#
# These survived the leaf-hash removal byte-for-byte while the populated root
# moved, because the ladder always started from the sentinel and never from a
# hashed commitment. That makes them a free tripwire: a change that is supposed
# to affect only occupied leaves must leave both of these alone, and a change
# that moves them touched the sponge, the domain constants or the ladder.
#
# Pinned as literals rather than recomputed, so the check cannot agree with a
# regenerated golden that is itself wrong. If either moves, that is a consensus
# change: confirm it was intended, then update these and say so in the commit.
PINNED_EMPTY_LEAF = "b88b1711c776ab193129f9ac08bf6492b257745225cd8c29a33c5b5b041f5a40"
PINNED_EMPTY_ANCHOR = "cb736bf4b5c245412b4bc1fa3739df7ea5a8da187633a8491a0b5303df3f5faf"


def check_pinned_empty_ladder(golden):
    print("\nEmpty ladder is pinned (tripwire for unintended consensus change):")
    check("EMPTY_LEAF matches its pinned literal",
          S.EMPTY_LEAF.hex() == PINNED_EMPTY_LEAF)
    check("empty-tree anchor matches its pinned literal",
          S.EMPTY_ROOTS[S.MERKLE_DEPTH].hex() == PINNED_EMPTY_ANCHOR)
    check("golden agrees with the pinned sentinel",
          golden["merkle"]["empty_leaf_sentinel"] == PINNED_EMPTY_LEAF)
    check("golden agrees with the pinned anchor",
          golden["merkle"]["empty_tree_root"] == PINNED_EMPTY_ANCHOR)
    # The ladder starts at the sentinel: level 0 IS the empty leaf, and every
    # level above is a node hash of the level below.
    check("ladder starts at the sentinel",
          golden["merkle"]["empty_roots"][0] == PINNED_EMPTY_LEAF)
    check("the sentinel is not itself a note commitment",
          PINNED_EMPTY_LEAF not in {n["commitment"] for n in golden["notes"]})


# Sections that do not depend on the pool hash. They must be byte-identical in
# every golden file, whatever hash it was generated under.
HASH_INDEPENDENT = (
    "hash_len",
    "merkle_depth",
    "max_note_value",
    "value_encoding",
    "field_encoding",
    "element_encoding",
    "field",
    "tags",
)


def check_hash_independent_sections(golden):
    """Cross-check every golden file agrees on the hash-independent parts.

    Once the pool hash swaps, Python computes Rescue by delegating to Rust, so
    "Python and Rust agree on a Rescue digest" becomes tautological. What stays
    meaningful is that the swap disturbed nothing structural -- the encoding,
    the tags and the parameters are the same under both hashes. Diffing the
    golden files gives that for free.

    Inert while only one golden file exists; it arms itself when the second
    one lands.
    """
    import glob

    print("\nHash-independent sections agree across golden files:")
    for name in HASH_INDEPENDENT:
        check(f"golden declares '{name}'", name in golden)

    others = sorted(
        p for p in glob.glob(os.path.join(HERE, "vectors", "shielded_*.json"))
        if os.path.basename(p) != os.path.basename(GOLDEN)
    )
    if not others:
        print("  [ .. ] only one golden file; cross-hash check arms when a "
              "second lands")
        return

    for path in others:
        label = os.path.basename(path)
        with open(path) as fh:
            other = json.load(fh)
        check(f"{label} was generated under a different hash",
              other.get("algorithm") != golden.get("algorithm"))
        for name in HASH_INDEPENDENT:
            mismatches = list(diff(golden.get(name), other.get(name), name))
            check(f"{label}: '{name}' identical across hashes", not mismatches)
            for line in mismatches[:3]:
                print(f"         {line}")
        # The hash-dependent parts must actually differ, or the "swap" did not
        # take effect and one of the files was generated under the wrong hash.
        check(f"{label}: merkle root differs under a different hash",
              other.get("merkle", {}).get("root")
              != golden.get("merkle", {}).get("root"))


def main():
    global FAILURES
    FAILURES = []
    print(f"Golden vectors ({os.path.basename(GOLDEN)}):")

    if not os.path.exists(GOLDEN):
        print(f"  [FAIL] golden file missing: {GOLDEN}")
        return 1

    with open(GOLDEN) as fh:
        golden = json.load(fh)

    check("golden matches the consensus hash algorithm",
          golden.get("algorithm") == S.POOL_HASH_ALGORITHM)
    check("golden matches consensus parameters",
          golden.get("hash_len") == S.HASH_LEN
          and golden.get("merkle_depth") == S.MERKLE_DEPTH
          and golden.get("max_note_value") == S.MAX_NOTE_VALUE)

    rebuilt = V.build_vectors(S.POOL_HASH_ALGORITHM)
    mismatches = list(diff(golden, json.loads(json.dumps(rebuilt))))
    if mismatches:
        print(f"  [FAIL] {len(mismatches)} mismatch(es) vs golden:")
        for line in mismatches[:15]:
            print(f"         {line}")
        if len(mismatches) > 15:
            print(f"         ... and {len(mismatches) - 15} more")
        FAILURES.append("golden vectors")
    else:
        check("every digest reproduces the golden file", True)

    check("generation is deterministic",
          V.build_vectors(S.POOL_HASH_ALGORITHM) == rebuilt)

    print("\nGolden vectors are internally consistent:")
    # Guards against a golden file regenerated while the code was broken --
    # matching a wrong golden proves nothing on its own.
    merkle = golden["merkle"]
    check("every authentication path recomputes the stated root",
          all(p["root"] == merkle["root"] for p in merkle["paths"]))

    paths_ok = True
    for entry in merkle["paths"]:
        path = S.MerklePath(position=entry["position"],
                            siblings=[bytes.fromhex(s) for s in entry["siblings"]])
        computed = path.compute_root(bytes.fromhex(entry["commitment"]))
        if computed.hex() != merkle["root"]:
            paths_ok = False
    check("paths recompute the root when replayed through shielded.py", paths_ok)

    notes_ok = True
    for entry in golden["notes"]:
        note = S.Note(value=entry["value"], pk_d=bytes.fromhex(entry["pk_d"]),
                      rho=bytes.fromhex(entry["rho"]), rcm=bytes.fromhex(entry["rcm"]))
        if note.commitment().hex() != entry["commitment"]:
            notes_ok = False
        if note.nullifier(bytes.fromhex(entry["nullifier_key"])).hex() != entry["nullifier"]:
            notes_ok = False
    check("note commitments and nullifiers replay correctly", notes_ok)

    check("distinct notes have distinct commitments",
          len({n["commitment"] for n in golden["notes"]}) == len(golden["notes"]))
    check("distinct notes have distinct nullifiers",
          len({n["nullifier"] for n in golden["notes"]}) == len(golden["notes"]))
    check("empty-tree root is the top empty root",
          merkle["empty_tree_root"] == merkle["empty_roots"][S.MERKLE_DEPTH])
    check("populated root differs from the empty root",
          merkle["root"] != merkle["empty_tree_root"])

    # The length-prefix rule is the whole reason these two differ; if a port
    # drops it they collide and one committed value can be reread as another.
    split_a = next(t for t in golden["tagged_hash"]
                   if t["parts"] == ["3031", "32"])
    split_b = next(t for t in golden["tagged_hash"]
                   if t["parts"] == ["30", "3132"])
    check("length-prefixed field splits do not collide",
          split_a["digest"] != split_b["digest"])

    check("bundle statement digest binds a different sighash to a different value",
          golden["bundle"]["statement_digest"]
          != golden["shielding_bundle"]["statement_digest"])

    print("\nSynthetic deep path exercises both branches at every level:")
    deep = golden["merkle"]["synthetic_deep_path"]
    bits = deep["position_bits"]
    check("deep position sets bits at all 32 levels", len(bits) == 32)
    check("deep position exercises the right-child branch", "1" in bits)
    check("deep position exercises the left-child branch", "0" in bits)
    # The degeneracy that hid the bug: a position whose bits are all zero makes
    # the direction column the zero polynomial, so the placement constraint
    # collapses and the right-child branch is never taken.
    check("deep position is not degenerate (bits are mixed, not all-zero)",
          set(bits) == {"0", "1"})
    check("bits alternate, so no run of levels shares a direction",
          "0000" not in bits and "1111" not in bits)
    deep_path = S.MerklePath(position=deep["position"],
                             siblings=[bytes.fromhex(s) for s in deep["siblings"]])
    check("deep path replays through shielded.py to the stated root",
          deep_path.compute_root(bytes.fromhex(deep["commitment"])).hex()
          == deep["root"])
    check("deep root differs from the populated root",
          deep["root"] != golden["merkle"]["root"])

    check_pinned_empty_ladder(golden)
    check_hash_independent_sections(golden)

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


# --- pytest entry point -------------------------------------------------------
#
# These suites are scripts: `check()` records a failure and returns, so the run
# can report every problem at once instead of stopping at the first. That design
# is invisible to pytest, which sees plain functions that never raise and marks
# them passed. Collected directly, `pytest tests/` reported "28 passed" with the
# vector suite contributing zero tests and the rest passing vacuously -- absence
# of failure looking like success, the same shape as the stale-binary problem.
#
# This is the one collectable test, and it fails when the suite fails.


def test_suite():
    assert main() == 0, "suite reported failures; run the script directly for detail"


if __name__ == "__main__":
    sys.exit(main())
