"""Phase 2, part 3: the Python-side cost of the hash decision.

Measures what the *node* pays, not what the circuit pays. Three questions:

  1. What does SHA3-256 cost in Python today?  (the baseline we'd give up)
  2. What would Rescue-Prime cost in pure Python?  (option 1)
  3. What does shelling out to Rust cost?  (option 3)

Option 2 -- moving tree/anchor maintenance into Rust -- has no Python cost by
construction, so it needs no measurement here.

IMPORTANT: the Rescue implementation below is NOT a correct Rescue-Prime. It has
the right *operation count and shape* (7 rounds, 12-element state, x^7 s-box,
12x12 MDS, inverse s-box via modular exponentiation) with placeholder constants,
because timing depends on the operation count and not on the constant values.
It exists only to price option 1. It must never be used for real hashing.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "wepo-blockchain" / "core"))

import shielded  # noqa: E402

MERKLE_DEPTH = shielded.MERKLE_DEPTH


def timeit(label, iters, fn):
    fn()  # warm up
    t = time.perf_counter()
    for _ in range(iters):
        fn()
    per = (time.perf_counter() - t) / iters
    print(f"  {label:<46} {per*1e9:>12.0f} ns {1/per:>14,.0f} /s")
    return per


# ---------------------------------------------------------------------------
# 1. SHA3 in Python, as the node uses it today
# ---------------------------------------------------------------------------

print("1. SHA3-256 in Python (current node cost)")
left = b"\x01" * 32
right = b"\x02" * 32
sha3_node = timeit("tagged_hash(NODE, l, r)  [one tree node]", 200_000,
                   lambda: shielded._node_hash(left, right))

path = shielded.MerklePath(position=12345, siblings=[b"\x03" * 32] * MERKLE_DEPTH)
cm = b"\x04" * 32
sha3_path = timeit(f"MerklePath.compute_root  [{MERKLE_DEPTH} nodes]", 5_000,
                   lambda: path.compute_root(cm))

# ---------------------------------------------------------------------------
# 2. Rescue-Prime in pure Python -- operation-count model (option 1)
# ---------------------------------------------------------------------------

P = (1 << 64) - (1 << 32) + 1           # Goldilocks
STATE = 12
ROUNDS = 7
INV_ALPHA = pow(7, -1, P - 1)           # exponent for the inverse s-box

MDS = [[(i * STATE + j + 1) % P for j in range(STATE)] for i in range(STATE)]
ARK1 = [[(r * STATE + j + 7) % P for j in range(STATE)] for r in range(ROUNDS)]
ARK2 = [[(r * STATE + j + 13) % P for j in range(STATE)] for r in range(ROUNDS)]


def _mds(state):
    return [sum(MDS[i][j] * state[j] for j in range(STATE)) % P for i in range(STATE)]


def rescue_permutation(state):
    """Structurally faithful, cryptographically meaningless. Timing only."""
    for r in range(ROUNDS):
        state = [pow(x, 7, P) for x in state]
        state = _mds(state)
        state = [(x + ARK1[r][j]) % P for j, x in enumerate(state)]
        state = [pow(x, INV_ALPHA, P) for x in state]      # the expensive half
        state = _mds(state)
        state = [(x + ARK2[r][j]) % P for j, x in enumerate(state)]
    return state


print("\n2. Rescue-Prime in pure Python (operation-count model, option 1)")
st = list(range(STATE))
rescue_py = timeit("rescue permutation  [one tree node]", 200,
                   lambda: rescue_permutation(st))
print(f"  {'-> per authentication path (x%d)' % MERKLE_DEPTH:<46} "
      f"{rescue_py*MERKLE_DEPTH*1e3:>12.2f} ms")

# ---------------------------------------------------------------------------
# 3. Shelling out to the Rust binary (option 3)
# ---------------------------------------------------------------------------

exe = REPO / "zk" / "target" / "release" / ("hashcli.exe" if os.name == "nt" else "hashcli")

print("\n3. Shell out to Rust hashcli (option 3)")
if not exe.exists():
    print(f"  SKIPPED -- {exe} not built")
else:
    payload = ("01" * 64) + "\n"

    def one_call():
        subprocess.run([str(exe)], input=payload, capture_output=True, text=True)

    spawn = timeit("subprocess per hash  [spawn + 1 hash]", 200, one_call)
    print(f"  {'-> per authentication path (x%d)' % MERKLE_DEPTH:<46} "
          f"{spawn*MERKLE_DEPTH*1e3:>12.2f} ms")

    # batched: one spawn, many hashes -- separates spawn cost from hash cost
    for n in (1_000, 10_000):
        batch = payload * n
        t = time.perf_counter()
        subprocess.run([str(exe)], input=batch, capture_output=True, text=True)
        el = time.perf_counter() - t
        print(f"  batched {n:>6,} hashes in one spawn          "
              f"{el/n*1e9:>12.0f} ns {n/el:>14,.0f} /s")

# ---------------------------------------------------------------------------

print("\n" + "-" * 78)
print("summary (per authentication path, depth %d):" % MERKLE_DEPTH)
print(f"  SHA3 in Python (today)      : {sha3_path*1e3:>10.3f} ms")
print(f"  Rescue in pure Python       : {rescue_py*MERKLE_DEPTH*1e3:>10.3f} ms"
      f"   ({rescue_py*MERKLE_DEPTH/sha3_path:>8,.0f}x slower than today)")
