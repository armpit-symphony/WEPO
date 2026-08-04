# Ghost Transfers — real-crypto design

Status: **verifier and consensus substrate implemented; launch qualification incomplete.**
The shielded pool remains fail-closed until the production wallet, independent
cryptographic audit, pinned verifier artifact, activation freeze, and
release-host qualification are complete.

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

The legacy node API is permanently retired with HTTP 410 and no longer imports
this module. The module remains only for explicit unsoundness regression tests.
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

## 3. Proof and verifier status

Hiding amounts and linkage at the same time is irreducibly a zero-knowledge
statement. There is no sound way around it: revealing a Merkle path reveals which
note is being spent, and without a proof of membership a spender can invent a
nullifier and mint value from nothing.

The complete five-condition Winterfell AIR and production Rust verifier CLI are
implemented. The raw STARK public inputs include the bundle fields and an
injective five-element encoding of the 32-byte transaction sighash. The outer
versioned envelope independently commits to those same public fields. Rewriting
the envelope sighash and recomputing its digest while reusing the raw proof is
therefore rejected.

`shielded.ShieldedVerifier` remains the node seam. The default
`RejectAllVerifier` refuses every proof, verifier registration does not imply
audit approval, and `verify_bundle()` remains closed until an independently
audited verifier is explicitly approved. **This default is deliberate**: an
accept-by-default stub in exactly this position is the legacy bug.

### The statement a verifier must establish

Given `statement_digest`, the prover knows notes and keys such that:

1. **Membership** — every spent note's commitment is in the tree under the
   bundle's anchor.
2. **Nullifier integrity** — every revealed nullifier is `H(nk, rho)` for the
   note it spends.
3. **Spend authority** — the prover holds the spending key authorising each
   note's `pk_d`.
4. **Range** — every spent and output note's value is in `[0, 2^61−1]`; no
   negatives and no Goldilocks-field wraparound.
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

1. **Independent cryptographic audit.** Review the complete AIR, Rescue
   implementation, 61-bit/no-wrap argument, transcript/public-input binding,
   Rust parser, and Python subprocess boundary. Close every critical/high
   finding before audit approval can be set.
2. **Extended adversarial/resource testing.** Fuzz the envelope and Winterfell
   proof parser, rehearse verifier timeouts/crashes, measure worst-case CPU and
   memory, and freeze operational limits.
3. **Wallet prover integration.** Implement note scanning, trial decryption,
   witness maintenance, proof generation for the transaction's exact canonical
   sighash, backup/restore, and reorg recovery.
4. **Activation specification.** Freeze a reviewed activation height and
   deployment procedure. The owner-selected value is height 1 (the first
   post-genesis block) and `MAINNET_GHOST_ACTIVATION_HEIGHT` is manifest-bound;
   formal review is still required and `PRIVACY_CONSENSUS_ENABLED` remains
   `False` until the complete gate passes.
5. **Legacy privacy quarantine.** The node's `/api/privacy/*` demo routes now
   return HTTP 410 and the node no longer imports their unsound implementation.

Consensus plumbing is now implemented but inactive: `ShieldedBundle` has
deterministic transaction/block serialization; transparent/shielded conservation
enforces `inputs - outputs = fee + value_balance`; nullifiers, commitments, and
anchors persist atomically in SQLite; same-block and mempool nullifier conflicts
are rejected; canonical disconnect/replay and restart recovery are tested; and
the note commitment tree appends incrementally rather than rebuilding its
occupied prefix.

## 5. Launch position

Ghost transfers and Quantum Vault are **mandatory launch gates** and stay
**🔒 fail-closed** until their
independent audit, wallet path, activation specification, and release-candidate
rehearsal are complete. No calendar launch date is currently committed.
The whitepaper framing is already correct and should not change:

> *"Ghost transfers & Vault — post-quantum private transactions, launching after
> independent audit."*

A mainnet release without qualified Ghost transfers is prohibited by policy and code.
