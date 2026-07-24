# Ghost Transfers — real-crypto design

Status: **substrate built and tested; ZK proof system outstanding.**
The shielded pool is closed at consensus and stays closed until the proof
verifier below is implemented and audited.

Canonical code: `wepo-blockchain/core/shielded.py`
Tests: `tests/test_shielded_pool.py`, `tests/test_legacy_privacy_unsound.py`

---

## 1. Why this is a rebuild and not a fix

`wepo-blockchain/core/privacy.py` cannot be repaired. Its failures are structural,
not bugs:

| Component | Claimed | Actually |
|---|---|---|
| `_pedersen_commit` | Pedersen commitment `vG + rH` | `SHA256(v‖G) XOR SHA256(r‖H)` — XOR is not a group operation, so commitments are **not additive** and value balance cannot be checked at all |
| `_verify_bulletproof` | Range proof | Recomputes `SHA256(data[:-32]) == data[-32:]` over **prover-supplied bytes** — a checksum, not a proof |
| `verify_stark_proof` | zk-STARK verification | Reconstructs a Merkle root from evaluations the **prover chose**; no low-degree test, no FRI query phase |
| `verify_ring_signature` | Ring signature | Same shape — self-consistency over prover data |
| Curve | Post-quantum | **secp256k1** (`SigningKey`, `SECP256k1`) — broken by Shor's algorithm, contradicting WEPO's entire thesis |

`tests/test_legacy_privacy_unsound.py` demonstrates the break concretely: it
forges a range proof **from `os.urandom` with no secret knowledge**, declares an
arbitrary range, and the legacy verifier returns `True`. On a live chain that is
unlimited counterfeiting.

The legacy module must be **deleted**, not patched, once the new path lands.
Nothing in `shielded.py` imports it.

## 2. What is built and sound today

All of it is hash-based (SHA3-256), so its security rests on collision and
preimage resistance — post-quantum by construction. No elliptic curves anywhere
in the shielded path.

- **Domain-separated hashing.** Every digest is tagged and every field is
  length-prefixed, so `H("01","2") != H("0","12")`. Without the prefix an
  attacker can re-split a committed byte string and reinterpret one value as
  another.
- **Note commitments.** `cm = H(value, pk_d, rho, rcm)`. Binding by collision
  resistance; hiding because `rcm` is fresh and secret. Two notes of the same
  value to the same key are unlinkable — the legacy commitment was deterministic
  in `(v, r)` and therefore confirmable by guessing the amount.
- **Note commitment tree.** Append-only Merkle accumulator, depth 32, with leaf
  and internal-node hashes separately tagged (otherwise an internal node can be
  passed off as a leaf). Notes are never removed, so the tree does not change
  shape when a note is spent — that is what keeps a spend unlinkable.
- **Nullifiers.** `nf = H(nk, rho)`, where `nk` derives from the shielded
  spending key. Deterministic per note (so a double-spend repeats) and
  underivable from public data (so nobody else can mark a note spent).
- **Nullifier set.** Consensus double-spend guard. Bundle insertion is atomic and
  reversible, so a self-conflicting bundle leaves no partial state and a
  disconnected block rolls back cleanly.
- **Anchor window.** Spends prove membership against a recent root rather than
  the tip, so a wallet's witness survives a few blocks. Bounded so an ancient
  root cannot be resurrected.
- **Bundle statement digest.** Binds anchor, all nullifiers, all output
  commitments, `value_balance`, **and the transaction sighash** — so a valid
  proof cannot be lifted onto another transaction or replayed with a swapped
  output.

## 3. The one thing that is not built: the proof

Hiding amounts and linkage at the same time is irreducibly a zero-knowledge
statement. There is no sound way around it: revealing a Merkle path reveals which
note is being spent, and without a proof of membership a spender can invent a
nullifier and mint value from nothing.

`shielded.ShieldedVerifier` is the seam. The default `RejectAllVerifier` refuses
every proof, and `verify_bundle()` returns `invalid shielded proof` for even a
structurally perfect bundle. **This default is deliberate**: an accept-by-default
stub in exactly this position is the legacy bug, and defaulting to open would let
an unfinished pool accept value.

### The statement a verifier must establish

Given `statement_digest`, the prover knows notes and keys such that:

1. **Membership** — every spent note's commitment is in the tree under the
   bundle's anchor.
2. **Nullifier integrity** — every revealed nullifier is `H(nk, rho)` for the
   note it spends.
3. **Spend authority** — the prover holds the spending key authorising each
   note's `pk_d`.
4. **Range** — every output note's value is in `[0, 2^63−1]`; no negatives, no
   wraparound.
5. **Balance** — `Σ(spent values) + max(value_balance, 0) == Σ(output values) + max(−value_balance, 0)`.

### Why balance must be *in-circuit* (a real design consequence)

Zcash checks balance **outside** its circuit by summing Pedersen value
commitments, which are additively homomorphic. WEPO's commitments are hash-based
for post-quantum security and therefore **not** homomorphic, so that trick is
unavailable. Balance has to be proven inside the circuit.

That is why a WEPO transaction carries **one aggregate bundle proof** over all
spends and outputs, rather than a proof per spend/output description. This is
already reflected in the `ShieldedBundle` type and its statement digest.

## 4. Remaining work, in order

### Blocker: proving-system toolchain
This machine has **no Rust toolchain** (`cargo`/`rustc` absent) and crates.io is
unreachable (HTTP 403). Every credible post-quantum proving system is Rust. Until
that is resolved the circuit cannot be built at all.

Options, in order of preference:

| System | Fit | Notes |
|---|---|---|
| **Winterfell** | Good | Production STARK library, hash-based/PQ, circuit written as an AIR. Most direct fit. |
| **Plonky2** | Good | FRI-based, very fast prover, well exercised. |
| **RISC Zero** | Easiest authoring | zkVM — circuit is a Rust guest program rather than a hand-written AIR. Larger proofs, heavier verifier. |

Do **not** substitute a hand-written prover. Writing the proof system is the one
part of this that must not be hand-rolled, and it is precisely how the legacy
module ended up unsound.

### Then
1. **Pick the hash for in-circuit use.** SHA3-256 is expensive inside an AIR. A
   ZK-friendly PQ hash (Rescue-Prime / Poseidon over the STARK field) should
   replace it for the tree and commitments. This changes the tag constants in
   `shielded.py` — do it **before** any mainnet notes exist, since it changes
   every commitment.
2. **Write the AIR/circuit** for the five conditions above.
3. **FFI + `ShieldedVerifier` implementation**, registered via
   `register_verifier()`.
4. **Wallet prover integration** (note scanning, witness maintenance, proof
   generation) — trial-decrypt outputs with ML-KEM-768, same construction as
   messaging.
5. **Consensus wiring** — replace the `privacy_proof` / `ring_signature` fields in
   `blockchain.py` (currently hard-rejected by `PRIVACY_CONSENSUS_ENABLED = False`)
   with `ShieldedBundle`, persist the nullifier set and tree frontier, and handle
   reorgs via `NullifierSet.rollback()`.
6. **Performance** — `NoteCommitmentTree._rebuild()` recomputes layers over the
   occupied prefix, which is fine for tests and early chain life but must become
   incremental frontier state before mainnet volume.
7. **External audit** of the circuit and verifier. Only then does
   `WEPO_FEATURE_PRIVACY` get to be `1`.
8. **Delete `privacy.py`** and `production_zk_stark.py`.

## 5. Launch position

Ghost transfers and Quantum Vault stay **🔒 gated** for the 2026-09-02 genesis.
The whitepaper framing is already correct and should not change:

> *"Ghost transfers & Vault — post-quantum private transactions, launching after
> independent audit."*

Live privacy at launch is real but narrower: Dandelion++ transaction-origin
privacy, optional Tor routing, and end-to-end post-quantum private messaging.
