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
MAX_NOTE_VALUE = (1 << 63) - 1         # fits a signed 64-bit accumulator
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
    return tagged_hash(_TAG_NK, _require_len("spending_key", spending_key, HASH_LEN))


def derive_diversified_key(spending_key: bytes, diversifier: bytes) -> bytes:
    """Derive the payment key `pk_d` a note is sent to.

    The diversifier lets one wallet hand out many unlinkable payment keys from a
    single spending key.
    """
    return tagged_hash(
        _TAG_PKD,
        _require_len("spending_key", spending_key, HASH_LEN),
        _require_len("diversifier", diversifier, 11),
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

    def commitment(self) -> bytes:
        """`cm = H(value, pk_d, rho, rcm)`.

        Binding by collision resistance; hiding because `rcm` is uniform and secret.
        """
        return tagged_hash(
            _TAG_NOTE,
            struct.pack("<Q", self.value),
            self.pk_d,
            self.rho,
            self.rcm,
        )

    def nullifier(self, nk: bytes) -> bytes:
        """`nf = H(nk, rho)` — revealed when the note is spent."""
        return tagged_hash(_TAG_NULLIFIER, _require_len("nk", nk, HASH_LEN), self.rho)


def random_note(value: int, pk_d: bytes) -> Note:
    """Create a note with fresh randomness for `rho` and `rcm`."""
    return Note(value=value, pk_d=pk_d, rho=secrets.token_bytes(HASH_LEN),
                rcm=secrets.token_bytes(HASH_LEN))


# --- merkle accumulator -------------------------------------------------------

def _leaf_hash(cm: bytes) -> bytes:
    return tagged_hash(_TAG_LEAF, _require_len("commitment", cm, COMMITMENT_LEN))


def _node_hash(left: bytes, right: bytes) -> bytes:
    return tagged_hash(_TAG_NODE, left, right)


def _empty_roots(depth: int) -> List[bytes]:
    """Precompute the hash of an all-empty subtree at each level."""
    roots = [tagged_hash(_TAG_LEAF, b"")]
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
        node = _leaf_hash(commitment)
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
        self._layers: List[List[bytes]] = [[]]

    @property
    def size(self) -> int:
        return len(self._leaves)

    def append(self, commitment: bytes) -> int:
        """Append a commitment; returns its position."""
        _require_len("commitment", commitment, COMMITMENT_LEN)
        if self.size >= (1 << self.depth):
            raise ShieldedError("note commitment tree is full")
        position = len(self._leaves)
        self._leaves.append(commitment)
        self._rebuild()
        return position

    def _rebuild(self) -> None:
        # Recomputes the layers over the occupied prefix. The tree is small during
        # tests and early chain life; a production node keeps incremental frontier
        # state instead of rebuilding (see design doc, "frontier" section).
        layer = [_leaf_hash(cm) for cm in self._leaves]
        self._layers = [layer]
        for level in range(self.depth):
            empty = EMPTY_ROOTS[level]
            nxt = []
            for i in range(0, max(len(layer), 1), 2):
                left = layer[i] if i < len(layer) else empty
                right = layer[i + 1] if i + 1 < len(layer) else empty
                nxt.append(_node_hash(left, right))
            layer = nxt
            self._layers.append(layer)

    def root(self) -> bytes:
        """Current anchor."""
        if not self._leaves:
            return EMPTY_ROOTS[self.depth]
        return self._layers[self.depth][0]

    def path(self, position: int) -> MerklePath:
        """Authentication path for the note at `position`."""
        if not 0 <= position < self.size:
            raise ShieldedError(f"no note at position {position}")
        siblings: List[bytes] = []
        index = position
        for level in range(self.depth):
            layer = self._layers[level]
            empty = EMPTY_ROOTS[level]
            sibling_index = index ^ 1
            siblings.append(
                layer[sibling_index] if sibling_index < len(layer) else empty
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
        if type(self.value_balance) is not int or isinstance(self.value_balance, bool):
            raise ShieldedError("value_balance must be an int")
        if abs(self.value_balance) > MAX_NOTE_VALUE:
            raise ShieldedError("value_balance out of range")

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
      4. every output note's value is in `[0, MAX_NOTE_VALUE]` (no negatives, no
         wraparound);
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


def register_verifier(verifier: ShieldedVerifier) -> None:
    """Install the proof verifier used by consensus.

    Call this only with an implementation backed by a vetted proving system.
    Never register something that accepts unconditionally.
    """
    if not hasattr(verifier, "verify"):
        raise ShieldedError("verifier must expose verify(statement_digest, proof)")
    global _VERIFIER
    _VERIFIER = verifier


def active_verifier() -> ShieldedVerifier:
    return _VERIFIER


def verifier_is_audited() -> bool:
    """False while the reject-all default is installed."""
    return not isinstance(_VERIFIER, RejectAllVerifier)


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

    if not active_verifier().verify(digest, bundle.proof):
        return False, "invalid shielded proof"

    return True, "ok"
