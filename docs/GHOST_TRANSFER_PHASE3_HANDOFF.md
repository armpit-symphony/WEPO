# Ghost Transfers — Phase 3 handoff: the circuit

**Runs on:** the Windows PC (Rust required; the Linux box has no toolchain and
crates.io is 403 there).

**Pull first** — the Linux box landed prep at `9a84e98`:

```
git fetch && git checkout wallet-lab-fixes-20260409 && git pull
python tests\test_shielded_pool.py        # expect ALL CHECKS PASSED
python tests\test_shielded_vectors.py
```

---

## Phase 2 decisions — settled, build against these

| | Decision |
|---|---|
| Hash | **Rescue-Prime `Rp64_256`** |
| Field | **Goldilocks**, cubic extension |
| Security | **43 queries / blowup 8** — 128-bit |
| Python side | **Option 2: tree/anchor maintenance moves into Rust**, batched shell-out as interim |
| Proof size | 35,049 B for depth-32 membership; ~55–60 KB per bundle |
| Block policy | **17–19 shielded tx per 1MB block** |

Two findings from Phase 2 that constrain the build:

- **`Rp64_256::hash()` panics on most real input lengths** — every length > 56
  not a multiple of 7 (124 of 201 probed). `tagged_hash(TAG_NODE, l, r)` is
  ~90 bytes, so a naive port panics on essentially every internal node hash.
  **Use `hash_elements()` / `merge()`.** The canonical bytes→elements encoding is
  now defined in `shielded.encode_bytes_as_field_elements` and pinned by the
  `element_encoding` vectors — implement against those, do not improvise.
- **Winterfell caps trace width at 254 columns** (its two checks disagree —
  `trace_info.rs` accepts 255, `proof/table.rs` rejects it). Keccak's 1600-bit
  state cannot live in columns at all, which is why SHA3-in-an-AIR was never a
  slow option but a different project. Worth keeping in mind as a hard ceiling
  when the circuit grows.

Note that raising blowup does **not** substitute for queries. If anyone later
tunes for proof size, security does not automatically follow.

---

## Step 0 — agree with the vectors before writing any AIR

Have Rust read `tests/vectors/shielded_sha3-256.json` and reproduce the
`element_encoding` section exactly. That section is hash-independent, so it can
be satisfied today.

Then, once Rescue is wired: generate `tests/vectors/shielded_rescue-p64-256.json`
from the Rust side and have Python verify the structure round-trips. A
Rust/Python disagreement here is a **silent chain split** — both sides build
self-consistent trees that do not match — and finding it after the circuit exists
means rewriting the circuit.

`tests/vectors/README.md` is the full contract. The detail most likely to bite:
in the statement digest, the nullifier list and the commitment list are each
**one** length-prefixed field, not one prefix per element.

## Step 1 — the hash swap

This is its own small, atomic, reviewed commit. `shielded.py` is already prepared
for it:

1. Register a `HashAlgorithm("rescue-p64-256", 32, fn)` backed by batched
   shell-out to Rust.
2. Flip `POOL_HASH_ALGORITHM`.
3. Regenerate the golden vectors under the new name.

`_activate_hash_algorithm` rebuilds `EMPTY_ROOTS` for you — that ladder is
hash-derived and a swap that missed it would produce wrong roots while looking
healthy. Do not hand-edit tags or digests; the whole point of the single seam is
that the swap is one registration plus one constant.

Do not ship the pure-Python Rescue path. Phase 2 measured it at 853 µs/hash —
126× slower than shelling out, 28.5 minutes to rebuild a 1M-note tree.

## Step 2 — the circuit, built up

Each step gets tests. Do not big-bang it.

1. **Merkle membership** — depth 32, position and path hidden. *(Already have a
   working AIR from Phase 2; this is the foundation.)*
2. **+ nullifier integrity** — revealed `nf` equals `H(nk, rho)` for the note
   being spent.
3. **+ spend authority** — prover holds the spending key authorising `pk_d`.
4. **+ range** — every output value in `[0, 2^63−1]`. No negatives, no wraparound.
5. **+ balance** — `Σ(spent) + max(vb,0) == Σ(outputs) + max(−vb,0)`.

**Balance must be in-circuit.** Hash commitments are not homomorphic, so summing
commitments the way Zcash sums Pedersen is unavailable. This is why a transaction
carries **one aggregate bundle proof**, not a proof per description.

Public input is `bundle.statement_digest(sighash)`, which already binds anchor,
nullifiers, commitments, `value_balance` and the sighash. Bind the circuit to
exactly that so a proof cannot be lifted onto another transaction.

Report proof size and prove time after each step — the tx/MB figure moves as the
circuit grows, and block policy depends on it. Note the figure is currently
**provisional at 14–16 tx/MB**: the scaling harness uses degree-1 constraints
while the real AIRs carry degree-7, so it under-reads by ~20% (measured ×1.23 at
2.1, ×1.18 at 2.2). Re-measure that ratio each step rather than treating ×1.2 as
settled; it will drift again when 2.4's range gadget changes constraint degree.

### Watch the column budget, not the rows

Columns went 13 (2.1) → 25 (2.2) → 50 (2.3), all at 256 rows. Rows are cheap —
they grow by powers of two and there is headroom. **Columns are hard-capped at
254**, so they are now the binding constraint.

The architecture commits to *one aggregate proof per transaction* covering all
spends and outputs with balance in-circuit. At ~50 columns per spend that ceiling
arrives fast, so project it at 2.4, before the layout is committed at 2.5:

- what a realistic bundle costs — 2 spends + 2 outputs, with range and balance;
- the spend count at which a bundle hits 254.

If a common bundle does not fit, the parallel layout has to partially invert for
multi-spend — trading rows back for columns, the same tradeoff measured at 2.2.
That is a cheap decision at 2.4 and an expensive one at 2.5.

### Test witnesses must not be structurally degenerate

Steps 2.1 and 2.2 were originally witnessed with `paths[0]`. Position 0 makes
every direction bit zero, so the bit column became the zero polynomial, the
placement constraint collapsed from degree 2 to 1, and **the right-child branch
of the Merkle path was never exercised**. Both steps passed anyway.

The general form: convenient test data is often degenerate, and a degenerate
witness silently collapses the constraint that depends on it. A zero diversifier
would have hidden the `encode()` element-count bug; `value = 0` would zero the
value column at 2.4. Choose witnesses that are structurally generic — non-zero,
mixed bits, nothing aligned — and prefer covering both branches of any binary
choice in every step.

## Step 3 — the verifier boundary

Subprocess CLI, decided and not open (the "verifier panics" guardrail). Reads
`(statement_digest, proof)`, exits 0/1. Fails **closed** on any error, non-zero
exit, timeout, crash, missing binary or malformed output. Wall-clock timeout and
bounded stdin, so a hostile proof cannot hang or balloon a validating node.

Then implement `shielded.ShieldedVerifier` and install it with
`register_verifier()`. Tests: real proof accepted, tampered proof rejected, proof
rejected under a different sighash, `verifier_is_audited()` reporting correctly,
and `test_shielded_pool.py` still passing unchanged including the reject-all
default.

---

## Guardrails

Carried from `docs/GHOST_TRANSFER_WINDOWS_HANDOFF.md`, plus one this phase
added. Numbering below is local to this document — other docs cite that one by
its own numbering, so cross-reference guardrails **by name**, not by number.

1. **Never register a verifier that can return `True` without checking a proof.**
   Not temporarily, not to unblock testing.
2. **Never register a verifier for a PARTIAL circuit.** Steps 2.1–2.4 are each
   individually unsound; only the complete five-condition circuit is sound.
   Guardrail 1 does not catch this, because a partial verifier *does* check a
   proof — the proof simply proves too little.

   Concretely, at step 2.2 a prover can show that some `cm` is in the tree and
   that `nf` is a well-formed hash of *some* `nk` and `rho`, with nothing tying
   either to the note being spent. Commitments are public, so anyone could pick
   any note in the tree, invent an `nk`, and drain it. Without 2.4 and 2.5 the
   values are unconstrained on top of that, so it mints as well as steals.

   Wire the subprocess boundary only once step 2.5 lands. Until then the
   intermediate circuits are benchmarks and correctness fixtures, exercised by
   their own tests — never through `register_verifier()`, not even "to test the
   integration".
3. **Verifier panics must never reach the node process.** Phase 2 made this
   concrete twice over.
4. **Do not hand-roll the proving system.** Implementing a published permutation
   or encoding against its spec and vectors is fine; that is not what this bans.
5. **`WEPO_FEATURE_PRIVACY` stays `0`** regardless of how well the circuit goes.
   A working verifier is not an audited one.
6. Keep `backend/.env` and `frontend/.env` unstaged.

## Out of scope

Consensus wiring (replacing `privacy_proof`/`ring_signature` in `blockchain.py`,
persisting the nullifier set and tree frontier, reorg handling), wallet note
scanning and witness maintenance, and making `NoteCommitmentTree._rebuild()`
incremental. `PRIVACY_CONSENSUS_ENABLED` stays `False`.

The Option 2 refactor — moving tree/anchor maintenance into Rust — is a real
project of its own. Batched shell-out is explicitly blessed as the interim so the
swap can land before genesis without a consensus refactor.

## Done when

A registered `ShieldedVerifier` backed by Winterfell accepts honestly-generated
bundle proofs and rejects tampered ones, with tests, with Rust and Python
agreeing on every vector, and with the gate still off.

Keep fuzzing the edges. Phase 1's verifier panic and Phase 2's `hash()` panic
were both found by poking rather than planning, and both changed a decision.
