"""Pure-Python Rescue-Prime Rp64_256 — TEST ORACLE ONLY. NEVER ON THE NODE PATH.

Why this exists
---------------
Before the hash swap, Python computed SHA3 with `hashlib` and Rust computed it
with the `sha3` crate. Those are independent implementations, so "both runtimes
agree" was evidence.

After the swap, Python gets Rescue by delegating to the Rust binary. "Both
runtimes agree on a Rescue digest" then becomes tautological — a bug in the
Rescue permutation would be invisible, because both sides share it.

This module restores an independent check. It is a separate implementation of
the permutation, written from the algorithm structure rather than transliterated
from the Rust, and it is pinned to the **upstream Sage reference vector** shipped
in winter-crypto's own test suite (`rp64_256/tests.rs::apply_permutation`, whose
expected values were "obtained by executing sage reference implementation code").

That gives a three-way check:

    Sage (upstream, independent)  <--  this module  -->  Rust (winter-crypto)

Performance
-----------
Measured at ~853 us per permutation, roughly 780x slower than SHA3 in Python.
That is hopeless for a tree — 28.5 minutes to rebuild 1M notes — and completely
fine for the ~50 digests in the vector file. Phase 2 disqualified it for
production; this module is the "disqualified for production is not useless"
case.

DO NOT register this with `register_hash_algorithm` for production use, and do
not import it from `wepo-blockchain/core/`. It lives under `tests/` on purpose.

The round constants are the published Rp64_256 parameters, emitted from
winter-crypto by `zk/src/bin/dump_rescue_constants.rs`. Constants must be
identical across runtimes by definition — different constants are a different
hash — so sharing them costs no independence. The independence is in the
permutation logic, and the Sage vector is what checks it.
"""

import json
import os
from typing import List, Sequence

_HERE = os.path.dirname(os.path.abspath(__file__))
_CONSTANTS_PATH = os.path.join(_HERE, "vectors", "rescue_rp64_256_constants.json")

with open(_CONSTANTS_PATH) as _fh:
    _C = json.load(_fh)

P = int(_C["modulus"])
STATE_WIDTH = _C["state_width"]
NUM_ROUNDS = _C["num_rounds"]
ALPHA = _C["alpha"]
RATE_START, RATE_END = _C["rate_range"]
RATE_WIDTH = RATE_END - RATE_START
CAPACITY_START = _C["capacity_range"][0]
DIGEST_START, DIGEST_END = _C["digest_range"]

MDS = [[int(x) for x in row] for row in _C["mds"]]
ARK1 = [[int(x) for x in row] for row in _C["ark1"]]
ARK2 = [[int(x) for x in row] for row in _C["ark2"]]

# Inverse s-box exponent: the multiplicative inverse of alpha modulo p-1.
# Computed rather than copied, so a wrong constant cannot be inherited.
INV_ALPHA = pow(ALPHA, -1, P - 1)

FELT_BYTES = 7


def _sbox(state: Sequence[int]) -> List[int]:
    return [pow(x, ALPHA, P) for x in state]


def _inv_sbox(state: Sequence[int]) -> List[int]:
    return [pow(x, INV_ALPHA, P) for x in state]


def _mds(state: Sequence[int]) -> List[int]:
    return [
        sum(MDS[i][j] * state[j] for j in range(STATE_WIDTH)) % P
        for i in range(STATE_WIDTH)
    ]


def _add(state: Sequence[int], ark: Sequence[int]) -> List[int]:
    return [(x + k) % P for x, k in zip(state, ark)]


def apply_round(state: Sequence[int], rnd: int) -> List[int]:
    """One Rescue-XLIX round: sbox -> MDS -> ARK1 -> inv_sbox -> MDS -> ARK2."""
    s = _add(_mds(_sbox(state)), ARK1[rnd])
    return _add(_mds(_inv_sbox(s)), ARK2[rnd])


def apply_permutation(state: Sequence[int]) -> List[int]:
    s = list(state)
    for r in range(NUM_ROUNDS):
        s = apply_round(s, r)
    return s


def hash_elements(elements: Sequence[int]) -> List[int]:
    """Sponge over field elements, matching winter-crypto's `hash_elements`.

    The element count goes into the first capacity element, which is what makes
    appending zero elements produce a different digest — so no extra padding is
    applied at the end.
    """
    state = [0] * STATE_WIDTH
    state[CAPACITY_START] = len(elements) % P

    i = 0
    for e in elements:
        state[RATE_START + i] = (state[RATE_START + i] + e) % P
        i += 1
        if i % RATE_WIDTH == 0:
            state = apply_permutation(state)
            i = 0

    if i > 0:
        state = apply_permutation(state)

    return state[DIGEST_START:DIGEST_END]


def h_dom(domain: int, elements: Sequence[int]) -> List[int]:
    """Domain-separated sponge: `hash_elements` with capacity[1] = domain.

    The only delta from the stock construction is that one assignment, plus
    permuting for an entirely empty input (stock would return the untouched
    state, i.e. an all-zero digest, and the empty-subtree ladder starts there).
    """
    state = [0] * STATE_WIDTH
    state[CAPACITY_START] = len(elements) % P
    state[CAPACITY_START + 1] = domain % P

    i = 0
    permuted = False
    for e in elements:
        state[RATE_START + i] = (state[RATE_START + i] + e) % P
        i += 1
        if i % RATE_WIDTH == 0:
            state = apply_permutation(state)
            permuted = True
            i = 0

    if i > 0 or not permuted:
        state = apply_permutation(state)

    return state[DIGEST_START:DIGEST_END]


def field_hash(domain: int, elements: Sequence[int]) -> bytes:
    """The in-circuit pool hash, computed independently."""
    return digest_to_bytes(h_dom(domain, elements))


def bytes_to_field_elements(data: bytes) -> List[int]:
    """32-byte pool value -> 4 canonical limbs, little-endian each."""
    if len(data) % 8 != 0:
        raise ValueError(f"expected a multiple of 8 bytes, got {len(data)}")
    out = []
    for off in range(0, len(data), 8):
        limb = int.from_bytes(data[off:off + 8], "little")
        if limb >= P:
            raise ValueError(f"non-canonical limb at offset {off}")
        out.append(limb)
    return out


def encode_bytes_as_field_elements(data: bytes) -> List[int]:
    """Canonical bytes -> Goldilocks elements: [len] then LE 7-byte chunks.

    Mirrors `shielded.encode_bytes_as_field_elements`. Duplicated here on
    purpose: an oracle that imports the thing it checks is not an oracle.
    """
    out = [len(data)]
    for off in range(0, len(data), FELT_BYTES):
        chunk = data[off:off + FELT_BYTES]
        out.append(int.from_bytes(chunk.ljust(8, b"\x00"), "little"))
    return out


def digest_to_bytes(digest_elements: Sequence[int]) -> bytes:
    """4 field elements -> 32 bytes, little-endian each (winter-crypto layout)."""
    return b"".join(int(e).to_bytes(8, "little") for e in digest_elements)


def pool_hash(data: bytes) -> bytes:
    """The full WEPO pool hash under Rescue, computed independently."""
    return digest_to_bytes(hash_elements(encode_bytes_as_field_elements(data)))


# ---------------------------------------------------------------------------
# Upstream Sage reference vector
# ---------------------------------------------------------------------------
#
# From winter-crypto 0.13.1, src/hash/rescue/rp64_256/tests.rs::apply_permutation.
# The comment there reads: "expected values are obtained by executing sage
# reference implementation code". Permuting [0, 1, ..., 11] must give exactly:

SAGE_REFERENCE_INPUT = list(range(12))

SAGE_REFERENCE_OUTPUT = [
    11084501481526603421,
    6291559951628160880,
    13626645864671311919,
    18397438323058963117,
    7443014167353970324,
    17930833023906771425,
    4275355080008025761,
    7676681476902901785,
    3460534574143792217,
    11912731278641497187,
    8104899243369883110,
    674509706691634438,
]


def self_check() -> None:
    """Raise unless this implementation reproduces the Sage reference vector."""
    got = apply_permutation(SAGE_REFERENCE_INPUT)
    if got != SAGE_REFERENCE_OUTPUT:
        raise AssertionError(
            "pure-Python Rescue does NOT match the upstream Sage reference vector\n"
            f"  got  {got}\n"
            f"  want {SAGE_REFERENCE_OUTPUT}"
        )
    if INV_ALPHA != 10540996611094048183:
        raise AssertionError(f"unexpected INV_ALPHA: {INV_ALPHA}")


if __name__ == "__main__":
    self_check()
    print("pure-Python Rescue matches the upstream Sage reference vector")
    print(f"  INV_ALPHA = {INV_ALPHA}")
    print(f"  pool_hash(b'') = {pool_hash(b'').hex()}")
    print(f"  pool_hash(b'abc') = {pool_hash(b'abc').hex()}")
