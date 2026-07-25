"""Node-side cost of the SHA3 -> Rescue swap, measured through the real node.

Everything here goes through `shielded.py` as the node actually runs it, so the
Rescue numbers include the full round trip: hex encode, pipe write, Rust hash,
pipe read, hex decode. SHA3 numbers are `hashlib` in-process, for comparison.

Run after: cargo build --release --bin poolhash
"""

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "wepo-blockchain" / "core"))

import shielded as S  # noqa: E402

MERKLE_DEPTH = S.MERKLE_DEPTH


def timeit(label, iters, fn):
    fn()
    t = time.perf_counter()
    for _ in range(iters):
        fn()
    per = (time.perf_counter() - t) / iters
    print(f"  {label:<44} {per*1e9:>11,.0f} ns {1/per:>13,.0f} /s")
    return per


def measure(algorithm):
    print(f"\n=== {algorithm} ===")
    with S.using_hash_algorithm(algorithm):
        left, right = b"\x01" * 32, b"\x02" * 32
        node = timeit("tagged_hash(NODE, l, r)  [one tree node]", 2000,
                      lambda: S._node_hash(left, right))

        path = S.MerklePath(position=12345,
                            siblings=[b"\x03" * 32] * MERKLE_DEPTH)
        cm = b"\x04" * 32
        pth = timeit(f"MerklePath.compute_root  [{MERKLE_DEPTH} nodes]", 200,
                     lambda: path.compute_root(cm))

        # Real tree growth. NoteCommitmentTree._rebuild() recomputes every layer
        # on every append (documented: a production node keeps frontier state),
        # so this is quadratic and is measured, not extrapolated.
        sizes = (25, 50, 100)
        rebuild = {}
        for n in sizes:
            tree = S.NoteCommitmentTree()
            commitments = [
                S.Note(value=i, pk_d=b"\x05" * 32,
                       rho=i.to_bytes(32, "big"), rcm=b"\x06" * 32).commitment()
                for i in range(n)
            ]
            t = time.perf_counter()
            for c in commitments:
                tree.append(c)
            el = time.perf_counter() - t
            rebuild[n] = el
            print(f"  {'grow tree to %d notes (append x%d)' % (n, n):<44} "
                  f"{el*1e3:>11,.1f} ms")

        return {"node": node, "path": pth, "rebuild": rebuild}


def main():
    print("Node-side cost of the pool hash swap")
    print(f"consensus algorithm: {S.POOL_HASH_ALGORITHM}")
    print(f"backend binary     : {__import__('rescue_backend').binary_path()}")

    sha3 = measure("sha3-256")
    rescue = measure("rescue-rp64-256")

    print("\n" + "-" * 74)
    print("Rescue / SHA3 ratio:")
    print(f"  one tree node        : {rescue['node']/sha3['node']:>8.1f}x")
    print(f"  authentication path  : {rescue['path']/sha3['path']:>8.1f}x")
    for n, el in rescue["rebuild"].items():
        print(f"  grow to {n:>3} notes     : {el/sha3['rebuild'][n]:>8.1f}x")

    # Project the figure Phase 2 quoted, from the measured per-node cost.
    # A full rebuild over N leaves costs ~2N node hashes.
    print("\nprojected full tree rebuild (~2N node hashes):")
    print(f"  {'notes':>10} {'SHA3':>12} {'Rescue':>14}")
    for n in (1_000, 100_000, 1_000_000):
        s_t = sha3["node"] * 2 * n
        r_t = rescue["node"] * 2 * n
        print(f"  {n:>10,} {s_t:>10.2f} s {r_t:>12.2f} s")

    print("\nper-block anchor validation (100 shielded tx, 32 nodes each):")
    for label, d in (("SHA3", sha3), ("Rescue", rescue)):
        print(f"  {label:<8} {d['path']*100*1e3:>8.1f} ms")


if __name__ == "__main__":
    main()
