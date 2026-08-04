"""
WEPO shielded pool — post-quantum note commitments, Merkle accumulator, nullifiers.

This is the real-crypto replacement for the primitives in `privacy.py`, which are
NOT sound (see `docs/GHOST_TRANSFER_DESIGN.md`): its "Pedersen commitment" is
`SHA256(v||G) XOR SHA256(r||H)` (neither binding nor homomorphic) and each of its
"verifiers" only recomputes a hash over prover-supplied bytes, so a forger with no
secret knowledge can mint arbitrary value. Nothing in this module may import it.

Everything here is hash-based (SHA3-256) and therefore post-quantum: security rests
on collision/preimage resistance, not on discrete log. There is no secp256k1 in the
shielded path.

WHAT THIS MODULE IS
    The sound substrate a shielded pool needs:
      * note commitments        -- binding + hiding
      * incremental Merkle tree -- membership accumulator, anchors
      * nullifier derivation    -- deterministic per note, double-spend prevention
      * nullifier set           -- consensus-side spent-note tracking
      * bundle statement digest -- the exact public input a proof must commit to

WHAT THIS MODULE IS NOT
    The zero-knowledge proof itself. Hiding *amounts* and *linkage* simultaneously
    is irreducibly a ZK statement, and a ZK proving system must not be hand-rolled.
    `ShieldedVerifier` is the seam where a vetted STARK verifier gets wired in;
    until one is registered the default `RejectAllVerifier` refuses every proof, so
    a half-finished pool cannot accept value. See `docs/GHOST_TRANSFER_DESIGN.md`.

NOTE ON VALUE BALANCE
    Zcash checks `sum(inputs) == sum(outputs) + fee` outside its circuit because
    Pedersen value commitments are additively homomorphic. A hash-based (post-
    quantum) commitment is not homomorphic, so WEPO cannot do that: balance has to
    be proven *inside* the circuit. That is why a transaction carries ONE aggregate
    bundle proof over all spends and outputs rather than a proof per description.
"""

import hashlib
import secrets
import struct
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Protocol, Sequence, Set, Tuple

# --- parameters ---------------------------------------------------------------

HASH_LEN = 32
MERKLE_DEPTH = 32                      # 2**32 notes; matches Zcash Sapling depth
# The complete Goldilocks-field bundle circuit proves 61-bit note values. With
# the v1 bundle limits below, either side of the balance equation contains at
# most five terms (four spends plus value_balance), so its integer sum cannot
# wrap the field modulus. These are consensus constants, not deployment knobs.
SHIELDED_VALUE_BITS = 61
MAX_NOTE_VALUE = (1 << SHIELDED_VALUE_BITS) - 1
MAX_SHIELDED_SPENDS = 4
MAX_SHIELDED_OUTPUTS = 2
MAX_SHIELDED_PROOF_BYTES = 1024 * 1024
MAX_ENCRYPTED_NOTE_BYTES = 16 * 1024
COMMITMENT_LEN = HASH_LEN
NULLIFIER_LEN = HASH_LEN
ANCHOR_LEN = HASH_LEN

# Domain separation tags. Every hash in the shielded pool is tagged so a digest
# computed for one purpose can never be reused as a digest for another.
_TAG_LEAF = b"WEPO-Shielded-MerkleLeaf-v1"
_TAG_NODE = b"WEPO-Shielded-MerkleNode-v1"
_TAG_NOTE = b"WEPO-Shielded-NoteCommit-v1"
_TAG_NULLIFIER = b"WEPO-Shielded-Nullifier-v1"
_TAG_NK = b"WEPO-Shielded-NullifierKey-v1"
_TAG_PKD = b"WEPO-Shielded-DiversifiedKey-v1"
_TAG_BUNDLE = b"WEPO-Shielded-BundleStatement-v1"


class ShieldedError(ValueError):
    """Raised when shielded data is malformed or violates a pool invariant."""


# --- hashing ------------------------------------------------------------------
#
# Every digest in the pool goes through `tagged_hash`, and `tagged_hash` goes
# through exactly one swappable algorithm. That single point exists because the
# in-circuit hash is still undecided (see docs/GHOST_TRANSFER_PHASE2_HANDOFF.md):
# SHA3-256 is standard, post-quantum and in the stdlib, which is what let this
# substrate be built and tested before the proving system existed, but Keccak is
# expensive inside an AIR and a ZK-friendly hash may replace it.
#
# Swapping the hash changes EVERY note commitment and EVERY Merkle root, so it
# has to be atomic. Routing everything through one point is what makes it atomic
# instead of a scattered edit where some tags move and some do not.


@dataclass(frozen=True)
class HashAlgorithm:
    """A pool hash: a name and a one-shot digest function.

    One-shot rather than streaming because a ZK-friendly replacement will most
    likely arrive over an FFI or subprocess boundary, where a streaming API does
    not survive the trip.
    """

    name: str
    digest_size: int
    fn: Callable[[bytes], bytes]


_ALGORITHMS: Dict[str, HashAlgorithm] = {}


def register_hash_algorithm(algorithm: HashAlgorithm) -> None:
    """Make an algorithm available for selection.

    Digest size is fixed at `HASH_LEN`: keys, nullifiers and commitments are all
    sized to it, so an algorithm with a different width would silently break the
    field-length checks rather than fail loudly here.
    """
    if not isinstance(algorithm, HashAlgorithm):
        raise ShieldedError("expected a HashAlgorithm")
    if algorithm.digest_size != HASH_LEN:
        raise ShieldedError(
            f"pool hash must produce {HASH_LEN} bytes, "
            f"'{algorithm.name}' produces {algorithm.digest_size}"
        )
    probe = algorithm.fn(b"")
    if not isinstance(probe, (bytes, bytearray)) or len(probe) != HASH_LEN:
        raise ShieldedError(f"'{algorithm.name}' did not return {HASH_LEN} bytes")
    _ALGORITHMS[algorithm.name] = algorithm


def available_hash_algorithms() -> List[str]:
    return sorted(_ALGORITHMS)


register_hash_algorithm(
    HashAlgorithm("sha3-256", 32, lambda data: hashlib.sha3_256(data).digest())
)

# Rescue-Prime Rp64_256 over the Goldilocks field, selected in Phase 2
# (docs/GHOST_TRANSFER_PHASE2_RESULTS.md). Chosen because the spend circuit
# proves Merkle membership, which is MERKLE_DEPTH hash invocations *inside the
# AIR*: Rescue costs 256 trace rows there, SHA3-256 cannot even fit its 1600-bit
# state into Winterfell's 254-column trace.
#
# Python does not compute Rescue itself. It delegates to the Rust binary over a
# persistent pipe (see rescue_backend). Pure Python was measured at 853 us per
# hash -- 28.5 minutes to rebuild a 1M-note tree -- which is disqualifying.
#
# There is deliberately NO fallback to SHA3 when the binary is unavailable. A
# node that quietly fell back would compute different commitments from every
# other node and split the chain *silently*, which is the precise failure the
# whole cross-runtime vector apparatus exists to prevent. A missing or wrong
# binary is a hard startup error, and rescue_backend runs a known-answer test
# before it will use one.
try:  # flat module by default; tolerate being imported as part of a package
    from . import rescue_backend  # type: ignore[import-not-found]
except ImportError:
    import rescue_backend  # type: ignore[no-redef]

register_hash_algorithm(
    HashAlgorithm("rescue-rp64-256", 32, rescue_backend.rescue_pool_hash)
)

# Consensus constant, deliberately NOT environment-configurable: two nodes
# running different pool hashes would compute different commitments and split the
# chain. Changing it is a reviewed code change, not a deployment knob.
POOL_HASH_ALGORITHM = "rescue-rp64-256"

_active_hash: HashAlgorithm = _ALGORITHMS[POOL_HASH_ALGORITHM]


def active_hash_algorithm() -> HashAlgorithm:
    return _active_hash


def _activate_hash_algorithm(name: str) -> None:
    """Switch the pool hash and rebuild everything derived from it."""
    global _active_hash, EMPTY_ROOTS
    if name not in _ALGORITHMS:
        raise ShieldedError(
            f"unknown pool hash '{name}'; available: {available_hash_algorithms()}"
        )
    _active_hash = _ALGORITHMS[name]
    # The empty-subtree ladder is hash-derived, so it is stale the moment the
    # algorithm changes. Forgetting this is how a half-swapped tree still
    # "works" while producing wrong roots.
    EMPTY_ROOTS = _empty_roots(MERKLE_DEPTH)


@contextmanager
def using_hash_algorithm(name: str):
    """Temporarily switch the pool hash.

    For generating candidate-hash test vectors and benchmarking only. Never use
    this on a live node: commitments made under one hash are meaningless under
    another.
    """
    previous = _active_hash.name
    _activate_hash_algorithm(name)
    try:
        yield _active_hash
    finally:
        _activate_hash_algorithm(previous)


# Goldilocks field, p = 2**64 - 2**32 + 1. Phase 2 selected Rescue-Prime
# Rp64_256 over this field, which hashes FIELD ELEMENTS, not bytes -- so the
# swap needs an explicit, canonical bytes->elements encoding that both runtimes
# agree on. Defined here now (additive; it changes no digest) so the encoding is
# pinned by test vectors before the hash swap itself lands.
GOLDILOCKS_MODULUS = (1 << 64) - (1 << 32) + 1
FELT_BYTES = 7  # 7 bytes = 56 bits < p, so every chunk is canonical and injective


def encode_bytes_as_field_elements(data: bytes) -> List[int]:
    """Canonical bytes -> Goldilocks field elements.

    Leading element is the byte length, then little-endian 7-byte chunks with the
    final chunk zero-padded. The length element is what keeps this injective:
    without it, trailing zero bytes and zero padding are indistinguishable.

    7 bytes per element (rather than 8) because a 64-bit chunk can exceed p and
    would need reduction, which is not injective. This also matches Winterfell's
    own 7-bytes-per-element convention, so the encoding agrees with `hash()` on
    the inputs where `hash()` happens to work.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise ShieldedError("data must be bytes")
    elements = [len(data)]
    for offset in range(0, len(data), FELT_BYTES):
        elements.append(int.from_bytes(data[offset:offset + FELT_BYTES], "little"))
    return elements


# --- field-native hashing (everything the circuit proves) ---------------------
#
# Rescue hashes field elements. Converting bytes to elements is free outside a
# circuit and expensive inside one: a digest is 4 elements of 8 bytes each, the
# byte encoding chunks at 7 bytes, and those boundaries never align, so proving
# the conversion needs byte decomposition of every digest at every tree level.
# Measured, that costs ~3.5x the proof size -- and it compounds, because it is
# needed wherever a digest feeds another hash, which is every circuit step.
#
# So every hash the circuit proves operates on field elements directly, and a
# 32-byte pool value IS 4 canonical Goldilocks elements, little-endian each.
# Nothing is ever re-chunked, so the decomposition gadget disappears entirely.
#
# The bundle statement digest keeps the byte-oriented `tagged_hash`: it is the
# public input, computed by the verifier outside the circuit, so it costs
# nothing in-circuit and keeps its self-describing ASCII tag.
#
# Domain separation moves from a byte tag into capacity[1]. `hash_elements`
# puts the element count in capacity[0] and leaves capacity[1..4] at zero, and
# those elements are already inside the 12-wide state the AIR pays for -- so a
# domain costs no extra permutation and no extra trace column. Prepending a
# domain element to the input instead would push a node hash to 9 elements,
# spilling the 8-element rate into a second permutation and doubling the cost
# of the most repeated operation in the circuit.

DOMAIN_LEAF = 1
DOMAIN_NODE = 2
DOMAIN_NOTE = 3
DOMAIN_NULLIFIER = 4
DOMAIN_NULLIFIER_KEY = 5
DOMAIN_DIVERSIFIED_KEY = 6

FELT_LIMB_BYTES = 8  # a pool value is 4 canonical limbs of 8 bytes


def bytes_to_field_elements(data: bytes, name: str = "value") -> List[int]:
    """A 32-byte pool value -> 4 canonical Goldilocks elements, LE per limb.

    Rejects non-canonical limbs rather than reducing them. Reduction is not
    injective, so two different byte strings would hash identically -- and one
    of them would be a value nobody could have committed to honestly.
    """
    if len(data) % FELT_LIMB_BYTES != 0:
        raise ShieldedError(
            f"{name} must be a multiple of {FELT_LIMB_BYTES} bytes, got {len(data)}"
        )
    out: List[int] = []
    for off in range(0, len(data), FELT_LIMB_BYTES):
        limb = int.from_bytes(data[off:off + FELT_LIMB_BYTES], "little")
        if limb >= GOLDILOCKS_MODULUS:
            raise ShieldedError(
                f"{name} limb at offset {off} is not canonical "
                f"({limb} >= p); pool values must be valid field elements"
            )
        out.append(limb)
    return out


def field_elements_to_bytes(elements: Sequence[int]) -> bytes:
    return b"".join(int(e).to_bytes(FELT_LIMB_BYTES, "little") for e in elements)


def field_hash(domain: int, elements: Sequence[int]) -> bytes:
    """`H_dom(domain, elements)` — the in-circuit pool hash.

    Pinned to Rescue-Prime. Unlike `tagged_hash`, this is deliberately not
    routed through the swappable `HashAlgorithm` seam: the circuit is built
    against this permutation, so a node running a different one would not merely
    disagree, it would be unable to verify any proof at all.
    """
    return rescue_backend.field_hash(domain, field_elements_to_bytes(elements))


def _field(data: bytes) -> bytes:
    """Length-prefix a field so concatenation is unambiguous.

    Without this, H(a||b) collides across different splits of the same bytes
    (e.g. a=b"01", b=b"2" and a=b"0", b=b"12"), which lets an attacker reinterpret
    one committed value as another.
    """
    return struct.pack("<I", len(data)) + data


def tagged_hash(tag: bytes, *parts: bytes) -> bytes:
    """Pool hash over a domain tag and length-prefixed fields."""
    buf = bytearray(_field(tag))
    for part in parts:
        buf += _field(part)
    return _active_hash.fn(bytes(buf))


def _require_len(name: str, value: bytes, expected: int) -> bytes:
    if not isinstance(value, (bytes, bytearray)):
        raise ShieldedError(f"{name} must be bytes, got {type(value).__name__}")
    if len(value) != expected:
        raise ShieldedError(f"{name} must be {expected} bytes, got {len(value)}")
    return bytes(value)


# --- keys ---------------------------------------------------------------------

def derive_nullifier_key(spending_key: bytes) -> bytes:
    """Derive the nullifier key `nk` from the shielded spending key.

    `nk` is what makes a nullifier unforgeable-but-deterministic: only the note's
    owner can compute it, and it is the same every time, so a second spend of the
    same note produces the same nullifier and is caught.
    """
    sk = _require_len("spending_key", spending_key, HASH_LEN)
    return field_hash(DOMAIN_NULLIFIER_KEY, bytes_to_field_elements(sk, "spending_key"))


def derive_diversified_key(spending_key: bytes, diversifier: bytes) -> bytes:
    """Derive the payment key `pk_d` a note is sent to.

    The diversifier lets one wallet hand out many unlinkable payment keys from a
    single spending key.
    """
    sk = _require_len("spending_key", spending_key, HASH_LEN)
    div = _require_len("diversifier", diversifier, 11)
    # The diversifier is 11 bytes, so it is not a whole number of limbs. It is a
    # pure witness input -- never a hash output feeding another hash -- so the
    # 7-byte chunk encoding is used for it and costs the circuit nothing.
    return field_hash(
        DOMAIN_DIVERSIFIED_KEY,
        bytes_to_field_elements(sk, "spending_key")
        + encode_bytes_as_field_elements(div),
    )


# --- notes --------------------------------------------------------------------

@dataclass(frozen=True)
class Note:
    """A shielded note: `value` WEPO payable to `pk_d`.

    `rho` is the note's unique serial (it makes the nullifier unique per note) and
    `rcm` is the commitment randomness (it makes the commitment hiding).
    """

    value: int
    pk_d: bytes
    rho: bytes
    rcm: bytes

    def __post_init__(self) -> None:
        if type(self.value) is not int or isinstance(self.value, bool):
            raise ShieldedError("note value must be an int")
        if not 0 <= self.value <= MAX_NOTE_VALUE:
            raise ShieldedError(f"note value out of range: {self.value}")
        _require_len("pk_d", self.pk_d, HASH_LEN)
        _require_len("rho", self.rho, HASH_LEN)
        _require_len("rcm", self.rcm, HASH_LEN)
        # Reject non-canonical limbs at construction rather than at hash time,
        # so a bad note cannot be built and then silently collide with another.
        bytes_to_field_elements(self.pk_d, "pk_d")
        bytes_to_field_elements(self.rho, "rho")
        bytes_to_field_elements(self.rcm, "rcm")

    def commitment(self) -> bytes:
        """`cm = H(value, pk_d, rho, rcm)`.

        Binding by collision resistance; hiding because `rcm` is uniform and secret.
        """
        # value fits one element: MAX_NOTE_VALUE is 2**63-1, well under p.
        return field_hash(
            DOMAIN_NOTE,
            [self.value]
            + bytes_to_field_elements(self.pk_d, "pk_d")
            + bytes_to_field_elements(self.rho, "rho")
            + bytes_to_field_elements(self.rcm, "rcm"),
        )

    def nullifier(self, nk: bytes) -> bytes:
        """`nf = H(nk, rho)` — revealed when the note is spent."""
        nk = _require_len("nk", nk, HASH_LEN)
        return field_hash(
            DOMAIN_NULLIFIER,
            bytes_to_field_elements(nk, "nk")
            + bytes_to_field_elements(self.rho, "rho"),
        )


def random_field_value() -> bytes:
    """32 bytes of randomness that is guaranteed to be 4 canonical elements.

    `secrets.token_bytes(32)` is not safe here: a uniform 8-byte limb lands at
    or above p with probability about 2**-32, and such a value has no canonical
    byte representation, so it would be rejected on the way back in.
    """
    return field_elements_to_bytes(
        [secrets.randbelow(GOLDILOCKS_MODULUS) for _ in range(HASH_LEN // FELT_LIMB_BYTES)]
    )


def random_note(value: int, pk_d: bytes) -> Note:
    """Create a note with fresh randomness for `rho` and `rcm`."""
    return Note(value=value, pk_d=pk_d, rho=random_field_value(),
                rcm=random_field_value())


# --- merkle accumulator -------------------------------------------------------

# THE TREE'S LEAVES ARE THE NOTE COMMITMENTS. There is deliberately no leaf hash.
#
# This is the change most likely to be mistaken for a careless optimisation, so
# the argument is recorded here rather than left implicit. A leaf hash exists to
# prevent *leaf/node confusion*: an attacker presenting an internal node's digest
# as though it were a leaf, so that a shorter path is accepted and a note that
# was never committed appears to be in the tree. Four independent properties
# block that here, and any one of them alone would be sufficient:
#
# 1. FIXED DEPTH. The attack needs a path shorter than the real one. MERKLE_DEPTH
#    is exactly 32, MerklePath rejects any path that is not exactly 32 siblings,
#    and the circuit's trace has exactly 32 node-hash cycles. A short path is not
#    representable, let alone acceptable -- there is no "up to 32" anywhere.
#
# 2. DOMAIN SEPARATION ALREADY EXISTS. A commitment is H_dom(DOMAIN_NOTE, ..) and
#    an internal node is H_dom(DOMAIN_NODE, ..). The domain sits in capacity[1]
#    and the element count in capacity[0], both absorbed before the permutation.
#    Passing a node digest off as a commitment means finding a value that is
#    simultaneously a valid output of two different domains -- a cross-domain
#    collision, no easier than a collision in Rescue itself. Re-hashing the leaf
#    under DOMAIN_LEAF added a third label to a value that was already labelled.
#
# 3. THE CIRCUIT OPENS THE COMMITMENT. From step 2.2 on, the spend circuit does
#    not treat the leaf as opaque bytes the prover chose: it proves
#    cm == H_dom(DOMAIN_NOTE, [value] || limbs(pk_d) || limbs(rho) || limbs(rcm))
#    for a note the prover can spend. An internal node's digest has no such
#    opening; producing one is a preimage break. So the leaf is constrained to be
#    a well-formed commitment by the proof itself, not merely by its shape.
#
# 4. PRIOR ART. Zcash Sapling does exactly this -- its note commitment tree takes
#    note commitments directly as leaves, at fixed depth 32, with no separate
#    leaf hash. This is the standard construction for a shielded pool, not a
#    shortcut taken to save a permutation.
#
# The saving is real but secondary: depth-32 membership needs 32 node hashes, and
# a leaf hash made it 33 -- 264 trace rows, which Winterfell rounds up to a
# power of two, so 512 with half the trace inert. Measured 49,017 B with the leaf
# hash against 35,049 B without. One redundant hash cost 40% of the proof.
#
# DOMAIN_LEAF survives as EMPTY_LEAF, the empty-slot sentinel -- see below.

def _node_hash(left: bytes, right: bytes) -> bytes:
    # Exactly 8 elements -- the full rate -- so a node costs one permutation.
    return field_hash(
        DOMAIN_NODE,
        bytes_to_field_elements(left, "left") + bytes_to_field_elements(right, "right"),
    )


# The value occupying every slot past the last appended note.
#
#   EMPTY_LEAF = H_dom(DOMAIN_LEAF, [])
#              = b88b1711c776ab193129f9ac08bf6492b257745225cd8c29a33c5b5b041f5a40
#
# It must be impossible for this to be a real commitment, or a spender could
# claim an unoccupied slot as their note and produce a membership proof for a
# note that was never appended. It cannot be, for two reasons that compound:
#
#   - DOMAIN.  capacity[1] is DOMAIN_LEAF (1) here and DOMAIN_NOTE (3) for any
#              commitment.
#   - LENGTH.  capacity[0] is the absorbed element count: 0 here, 13 for a
#              commitment ([value] + 4 + 4 + 4 limbs).
#
# Both are absorbed into the state before the permutation runs, so producing a
# note whose commitment equals EMPTY_LEAF requires a preimage of this specific
# 256-bit value under a different domain and a different length -- a preimage
# break, not a coincidence. Note also that the empty ladder is unchanged by
# dropping the leaf hash: it always started from this sentinel, never from a
# hashed commitment, so the empty-tree anchor is byte-identical across the
# change while the populated root moves.
EMPTY_LEAF = field_hash(DOMAIN_LEAF, [])


def _empty_roots(depth: int) -> List[bytes]:
    """Precompute the hash of an all-empty subtree at each level."""
    # The empty slot is H_dom(DOMAIN_LEAF, []) -- an empty element list. H_dom
    # still permutes in that case, so this is a real digest rather than the
    # untouched zero state. It is domain-separated from any real commitment.
    roots = [EMPTY_LEAF]
    for _ in range(depth):
        roots.append(_node_hash(roots[-1], roots[-1]))
    return roots


EMPTY_ROOTS = _empty_roots(MERKLE_DEPTH)


@dataclass
class MerklePath:
    """An authentication path proving `commitment` sits at `position`."""

    position: int
    siblings: List[bytes]

    def __post_init__(self) -> None:
        if len(self.siblings) != MERKLE_DEPTH:
            raise ShieldedError(
                f"path must have {MERKLE_DEPTH} siblings, got {len(self.siblings)}"
            )
        if not 0 <= self.position < (1 << MERKLE_DEPTH):
            raise ShieldedError(f"position out of range: {self.position}")

    def compute_root(self, commitment: bytes) -> bytes:
        # the commitment IS the leaf; it is already a domain-separated digest
        node = _require_len("commitment", commitment, COMMITMENT_LEN)
        bytes_to_field_elements(node, "commitment")
        index = self.position
        for sibling in self.siblings:
            _require_len("sibling", sibling, HASH_LEN)
            if index & 1:
                node = _node_hash(sibling, node)
            else:
                node = _node_hash(node, sibling)
            index >>= 1
        return node


class NoteCommitmentTree:
    """Append-only Merkle accumulator over note commitments.

    Notes are only ever added, never removed — spending is tracked by the
    nullifier set instead. That is what keeps a spend unlinkable: the tree does
    not change shape when a note is spent.
    """

    def __init__(self, depth: int = MERKLE_DEPTH):
        if depth != MERKLE_DEPTH:
            raise ShieldedError("only the consensus depth is supported")
        self.depth = depth
        self._leaves: List[bytes] = []
        # Sparse occupied-prefix nodes by level. Appending touches one node per
        # level instead of rebuilding every historical layer.
        self._nodes: List[Dict[int, bytes]] = [dict() for _ in range(depth + 1)]

    @property
    def size(self) -> int:
        return len(self._leaves)

    def append(self, commitment: bytes) -> int:
        """Append a commitment; returns its position."""
        _require_len("commitment", commitment, COMMITMENT_LEN)
        if self.size >= (1 << self.depth):
            raise ShieldedError("note commitment tree is full")
        position = len(self._leaves)
        value = bytes(commitment)
        self._leaves.append(value)
        self._nodes[0][position] = value

        index = position
        for level in range(self.depth):
            parent = index >> 1
            left_index = parent << 1
            left = self._nodes[level].get(left_index, EMPTY_ROOTS[level])
            right = self._nodes[level].get(left_index + 1, EMPTY_ROOTS[level])
            self._nodes[level + 1][parent] = _node_hash(left, right)
            index = parent
        return position


    def root(self) -> bytes:
        """Current anchor."""
        if not self._leaves:
            return EMPTY_ROOTS[self.depth]
        return self._nodes[self.depth][0]

    def path(self, position: int) -> MerklePath:
        """Authentication path for the note at `position`."""
        if not 0 <= position < self.size:
            raise ShieldedError(f"no note at position {position}")
        siblings: List[bytes] = []
        index = position
        for level in range(self.depth):
            empty = EMPTY_ROOTS[level]
            sibling_index = index ^ 1
            siblings.append(
                self._nodes[level].get(sibling_index, empty)
            )
            index >>= 1
        return MerklePath(position=position, siblings=siblings)


# --- nullifier set ------------------------------------------------------------

class NullifierSet:
    """Consensus-side record of spent notes.

    A nullifier reveals nothing about *which* note was spent, but repeating one
    is exactly a double-spend, so the set is the pool's only spend guard.
    """

    def __init__(self) -> None:
        self._spent: Dict[bytes, int] = {}

    def __contains__(self, nullifier: bytes) -> bool:
        return bytes(nullifier) in self._spent

    def __len__(self) -> int:
        return len(self._spent)

    def height_of(self, nullifier: bytes) -> Optional[int]:
        return self._spent.get(bytes(nullifier))

    def add(self, nullifier: bytes, height: int) -> None:
        nf = _require_len("nullifier", nullifier, NULLIFIER_LEN)
        if nf in self._spent:
            raise ShieldedError(f"double spend: nullifier already spent at height "
                                f"{self._spent[nf]}")
        self._spent[nf] = height

    def add_bundle(self, nullifiers: Sequence[bytes], height: int) -> None:
        """Add every nullifier in a bundle, or none of them.

        Applied atomically so a bundle that double-spends against itself cannot
        leave half its nullifiers recorded.
        """
        staged: Set[bytes] = set()
        for nf in nullifiers:
            value = _require_len("nullifier", nf, NULLIFIER_LEN)
            if value in self._spent or value in staged:
                raise ShieldedError("double spend: duplicate nullifier in bundle")
            staged.add(value)
        for nf in staged:
            self._spent[nf] = height

    def rollback(self, nullifiers: Sequence[bytes]) -> None:
        """Undo a bundle's nullifiers when its block is disconnected."""
        for nf in nullifiers:
            self._spent.pop(bytes(nf), None)


# --- anchors ------------------------------------------------------------------

class AnchorSet:
    """Recent tree roots a spend is allowed to reference.

    A spend proves membership against an anchor rather than the current root, so
    a wallet's witness stays valid for a few blocks. The window is bounded so an
    attacker cannot resurrect an ancient root.
    """

    def __init__(self, window: int = 100):
        if window < 1:
            raise ShieldedError("anchor window must be positive")
        self.window = window
        self._anchors: Dict[bytes, int] = {}

    def add(self, anchor: bytes, height: int) -> None:
        self._anchors[_require_len("anchor", anchor, ANCHOR_LEN)] = height
        self._prune(height)

    def _prune(self, height: int) -> None:
        cutoff = height - self.window
        for anchor, at in list(self._anchors.items()):
            if at < cutoff:
                del self._anchors[anchor]

    def is_valid(self, anchor: bytes) -> bool:
        return bytes(anchor) in self._anchors

    def __len__(self) -> int:
        return len(self._anchors)


# --- bundles ------------------------------------------------------------------

@dataclass(frozen=True)
class SpendDescription:
    """Public half of a spend: the anchor it proves against and its nullifier."""

    anchor: bytes
    nullifier: bytes

    def __post_init__(self) -> None:
        _require_len("anchor", self.anchor, ANCHOR_LEN)
        _require_len("nullifier", self.nullifier, NULLIFIER_LEN)


@dataclass(frozen=True)
class OutputDescription:
    """Public half of an output: the new note commitment.

    `enc_note` is the note ciphertext for the recipient (ML-KEM-768 + AES-256-GCM,
    same construction as WEPO messaging). Consensus treats it as opaque.
    """

    commitment: bytes
    enc_note: bytes

    def __post_init__(self) -> None:
        _require_len("commitment", self.commitment, COMMITMENT_LEN)
        if not isinstance(self.enc_note, (bytes, bytearray)):
            raise ShieldedError("enc_note must be bytes")
        if len(self.enc_note) > MAX_ENCRYPTED_NOTE_BYTES:
            raise ShieldedError(
                f"enc_note exceeds {MAX_ENCRYPTED_NOTE_BYTES} bytes"
            )


@dataclass
class ShieldedBundle:
    """All shielded activity in one transaction, under one aggregate proof.

    `value_balance` is the net value moving between the transparent and shielded
    pools: positive shields funds in, negative unshields out. A fully-shielded
    transfer has `value_balance == 0`. The amounts *inside* the pool stay hidden;
    only this net figure is public, and the proof is what ties it to the notes.
    """

    spends: List[SpendDescription] = field(default_factory=list)
    outputs: List[OutputDescription] = field(default_factory=list)
    value_balance: int = 0
    proof: bytes = b""

    def nullifiers(self) -> List[bytes]:
        return [s.nullifier for s in self.spends]

    def commitments(self) -> List[bytes]:
        return [o.commitment for o in self.outputs]

    def check_shape(self) -> None:
        """Structural checks that hold regardless of the proof system."""
        if not self.spends and not self.outputs:
            raise ShieldedError("bundle must contain at least one spend or output")
        if len(self.spends) > MAX_SHIELDED_SPENDS:
            raise ShieldedError(
                f"bundle has too many spends: {len(self.spends)} > "
                f"{MAX_SHIELDED_SPENDS}"
            )
        if len(self.outputs) > MAX_SHIELDED_OUTPUTS:
            raise ShieldedError(
                f"bundle has too many outputs: {len(self.outputs)} > "
                f"{MAX_SHIELDED_OUTPUTS}"
            )
        if type(self.value_balance) is not int or isinstance(self.value_balance, bool):
            raise ShieldedError("value_balance must be an int")
        if abs(self.value_balance) > MAX_NOTE_VALUE:
            raise ShieldedError("value_balance out of range")
        if not isinstance(self.proof, (bytes, bytearray)):
            raise ShieldedError("proof must be bytes")
        if len(self.proof) > MAX_SHIELDED_PROOF_BYTES:
            raise ShieldedError("shielded proof exceeds consensus size limit")

        seen: Set[bytes] = set()
        for nf in self.nullifiers():
            if nf in seen:
                raise ShieldedError("duplicate nullifier within bundle")
            seen.add(nf)

        anchors = {s.anchor for s in self.spends}
        if len(anchors) > 1:
            raise ShieldedError("all spends in a bundle must share one anchor")

    def anchor(self) -> Optional[bytes]:
        return self.spends[0].anchor if self.spends else None

    def statement_digest(self, sighash: bytes) -> bytes:
        """The public input the aggregate proof must commit to.

        Binding every public element — anchor, nullifiers, commitments, value
        balance, and the transaction sighash — is what stops a valid proof from
        being lifted onto a different transaction or replayed with a swapped
        output. `sighash` is the transaction's signature hash, so the proof is
        non-transferable across transactions.
        """
        _require_len("sighash", sighash, HASH_LEN)
        self.check_shape()
        anchor = self.anchor() or EMPTY_ROOTS[MERKLE_DEPTH]
        return tagged_hash(
            _TAG_BUNDLE,
            anchor,
            struct.pack("<I", len(self.spends)),
            b"".join(self.nullifiers()),
            struct.pack("<I", len(self.outputs)),
            b"".join(self.commitments()),
            struct.pack("<q", self.value_balance),
            sighash,
        )


# --- proof verification seam --------------------------------------------------

class ShieldedVerifier(Protocol):
    """Verifies an aggregate bundle proof against its public statement.

    An implementation must establish, in zero knowledge, that for the given
    statement digest the prover knows notes and keys such that:

      1. every spent note's commitment is in the tree under the bundle's anchor;
      2. every nullifier is `H(nk, rho)` for the note it spends;
      3. the prover holds the spending key authorising each `pk_d`;
      4. every spent and output note's value is in `[0, MAX_NOTE_VALUE]` (no
         negatives, no wraparound);
      5. `sum(spent values) + max(value_balance, 0)`
           `== sum(output values) + max(-value_balance, 0)`.

    Item 5 must be in-circuit: WEPO's commitments are hash-based for post-quantum
    security and therefore not homomorphic, so balance cannot be checked by
    summing commitments the way Zcash does.
    """

    def verify(self, statement_digest: bytes, proof: bytes) -> bool:
        ...


class RejectAllVerifier:
    """Default verifier: refuses every proof.

    The shielded pool stays closed until a real, audited verifier is registered.
    This is deliberate — an always-accept stub in this position is precisely the
    bug that makes the legacy `privacy.py` unshippable, and defaulting to "open"
    would let an unfinished pool mint value.
    """

    reason = "no audited shielded verifier is registered"

    def verify(self, statement_digest: bytes, proof: bytes) -> bool:
        return False


_VERIFIER: ShieldedVerifier = RejectAllVerifier()
_VERIFIER_AUDIT_APPROVED = False


def register_verifier(
    verifier: ShieldedVerifier, *, audit_approved: bool = False
) -> None:
    """Install the proof verifier used by consensus.

    Call this only with an implementation backed by a vetted proving system.
    Never register something that accepts unconditionally.
    """
    if not hasattr(verifier, "verify"):
        raise ShieldedError("verifier must expose verify(statement_digest, proof)")
    if type(audit_approved) is not bool:
        raise ShieldedError("audit_approved must be a boolean")
    global _VERIFIER, _VERIFIER_AUDIT_APPROVED
    _VERIFIER = verifier
    _VERIFIER_AUDIT_APPROVED = (
        audit_approved and not isinstance(verifier, RejectAllVerifier)
    )


def active_verifier() -> ShieldedVerifier:
    return _VERIFIER


def verifier_is_audited() -> bool:
    """Return the explicit external-audit approval state.

    Registering executable code alone never implies that it was audited.
    """
    return _VERIFIER_AUDIT_APPROVED


# --- consensus entry point ----------------------------------------------------

def verify_bundle(
    bundle: ShieldedBundle,
    sighash: bytes,
    anchors: AnchorSet,
    nullifiers: NullifierSet,
) -> Tuple[bool, str]:
    """Full consensus check for a shielded bundle.

    Returns `(ok, reason)`. The cheap structural checks run first so a malformed
    bundle is rejected before any proof work.
    """
    try:
        bundle.check_shape()
    except ShieldedError as exc:
        return False, str(exc)

    anchor = bundle.anchor()
    if anchor is not None and not anchors.is_valid(anchor):
        return False, "unknown or expired anchor"

    for nf in bundle.nullifiers():
        if nf in nullifiers:
            return False, "double spend: nullifier already spent"

    if not bundle.proof:
        return False, "bundle carries no proof"

    try:
        digest = bundle.statement_digest(sighash)
    except ShieldedError as exc:
        return False, str(exc)

    if not verifier_is_audited():
        return False, "invalid shielded proof"

    if not active_verifier().verify(digest, bundle.proof):
        return False, "invalid shielded proof"

    return True, "ok"
