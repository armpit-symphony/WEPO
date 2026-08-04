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
| Proof size | 69,409 B (1-in/2-out), 89,309 B (2-in/2-out), 127,480 B (4-in/2-out); proof-only |
| Block policy | **Design fees/block size around ~11–12 proof-only tx/MiB for realistic 2-in/2-out bundles; lower after envelope/transaction overhead** |

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
4. **+ range** — every spent and output value in `[0, 2^61−1]`. No negatives or field wraparound.
5. **+ balance** — `Σ(spent) + max(vb,0) == Σ(outputs) + max(−vb,0)`.

**Balance must be in-circuit.** Hash commitments are not homomorphic, so summing
commitments the way Zcash sums Pedersen is unavailable. This is why a transaction
carries **one aggregate bundle proof**, not a proof per description.

The node supplies `bundle.statement_digest(sighash)`. The versioned proof
envelope carries the corresponding public anchor, nullifiers, commitments,
`value_balance`, and sighash; the Rust verifier recomputes the digest and passes
the bundle fields plus an injective five-element encoding of the 32-byte sighash
as Winterfell public inputs. A proof therefore cannot be lifted onto another
transaction. The release-mode regression rewrites the envelope sighash,
recomputes its digest, reuses the raw proof, and requires rejection.

Report proof size and prove time after each step — the tx/MB figure moves as the
circuit grows, and block policy depends on it. Earlier scaling-harness
projections of 14–16 tx/MB are superseded by the complete-circuit measurements
below. Treat the 2-in/2-out 11.7 proof-only number as the current planning upper
bound, then subtract envelope and transaction overhead for fee policy.

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

### Complete-circuit release measurements (2026-07-28)

Per spend 52 columns (measured), per output ~20 (commitment only — no path, no
nullifier), balance ~4.

| bundle | columns | raw proof | proof-only upper bound per MiB |
|---|---|---|---|
| 1 spend + 2 outputs | 96 | 69,409 B | 15.1 |
| 2 spends + 2 outputs | 148 | 89,309 B | 11.7 |
| 4 spends + 2 outputs | 252 | 127,480 B | 8.2 |

**4 spends is the hard ceiling with 2 outputs** — 252 against the 254 cap. Past
that the parallel layout exceeds Winterfell's cap and is rejected by v1.

Two consequences that are protocol decisions, not implementation details:

- **A 4-input cap is a real UX limit.** A wallet holding many small notes cannot
  consolidate more than four in one transaction. Dust consolidation becomes
  multi-transaction, which costs fees and leaks timing.
- **Splitting into multiple proofs is not free.** One aggregate proof per
  transaction exists *because* hash commitments are not homomorphic, so balance
  must be proven in-circuit across all spends and outputs at once. Two proofs
  means two balance statements, and nothing binds them together without a
  second-level construction.

Decision frozen 2026-07-28: v1 uses one parallel aggregate proof with at most
four spends and two outputs. Sequential and two-level layouts are deferred
until they have their own circuit, vectors, resource measurements, and review.
Wallets must consolidate additional notes across multiple transactions; this
limit is enforced by both the node and verifier.

### The tx/MB figure keeps falling — track it deliberately

20 → 17–19 → 14–16 → **11.7 proof-only for a complete 2-in/2-out bundle**.
Actual block capacity is lower after the envelope and transaction overhead. Each drop came
from the circuit getting more complete or the measurement getting more honest,
not from anything going wrong. Block-size and shielded-fee policy must use the
complete-circuit measurements plus conservative serialization overhead.

### Declared constraint degree: derive it, do not measure it

Winterfell's debug degree assertion cannot arbitrate its own question here.
Declaring 510/765 for the range constraints reports actual 0; declaring 255
reports 510/765 — same trace, same expressions.

The reason is that the assertion interpolates `C(x)/D(x)` **on one satisfying
trace**. On a valid trace the constraint evaluates to zero everywhere, so the
numerator vanishes on the whole domain and the quotient's degree reflects that
particular trace, not the constraint's bound. The bound has to hold for *all*
traces, including invalid ones — which is exactly the case the measurement never
sees.

So: derive the declared degree from the algebra (a degree-1/2 trace expression
times a length-256 periodic column), and treat the debug assertion as a smoke
detector rather than an oracle. **When in doubt, over-declare** — that costs a
larger composition polynomial and nothing else, while under-declaring is
unsound. Behaviour is the real check: out-of-range rejected, legal values
accepted.

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

**Mixedness is not enough — aperiodicity matters too, and less obviously.** The
first fix for the position-0 bug was `0xA5A5A5A5`, which alternates from level 0
and looks maximally generic. But `A5` repeated gives the direction bits a period
of 8 levels = 64 rows, an exact divisor of the 256-row trace, so the bit column
interpolates to a polynomial in `x**4` of degree 252 rather than 255. Every
constraint multiplying by it lands 3–6 below its declared degree, disabling the
debug degree assertion — the check that had caught two real bugs. A degeneracy
aimed straight at the Rescue cycle.

The vector now uses `0x9E3779B9` and asserts the property, not the constant: no
period dividing 32, and both directions present in every 8-level window. For
range values, the same rule says the headline witness must not be `0`,
`2^61−1`, or a power of two.

## Step 3 — verifier boundaries and honest proof integration done 2026-07-28

The fail-closed Python boundary is implemented in
`wepo-blockchain/core/shielded_verifier.py` and covered by
`tests/test_shielded_verifier_boundary.py`. Registration and explicit external
audit approval are now separate states.

Subprocess CLI, decided and not open (the "verifier panics" guardrail). Reads
`(statement_digest, proof)`, exits 0/1. Fails **closed** on any error, non-zero
exit, timeout, crash, missing binary or malformed output. Wall-clock timeout and
bounded stdin, so a hostile proof cannot hang or balloon a validating node.

The complete Rust Winterfell CLI, versioned statement-bound proof envelope, and
deterministic honest proof generator are implemented. Cross-runtime integration
accepts the honest complete-circuit proof and rejects proof tampering, statement
tampering, truncation, trailing bytes, crashes, timeouts, missing binaries,
oversized input, and malformed command configuration. The reject-all default
and separate audit gate remain in force.

Remaining work is extended resource/fuzz testing, wallet wiring, independent
audit, and a reviewed activation specification. Consensus transaction/state
wiring is implemented and remains inactive.

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

## Deferred beyond this handoff

Wallet note scanning, witness maintenance, backup/restore, and shipping
activation remain deferred. Consensus persistence/reorg handling and
incremental tree appends are now implemented, but
`SHIELDED_ACTIVATION_HEIGHT` stays `None` and
`PRIVACY_CONSENSUS_ENABLED` stays `False`.

The Option 2 refactor — moving tree/anchor maintenance into Rust — is a real
project of its own. Batched shell-out is explicitly blessed as the interim so the
swap can land before genesis without a consensus refactor.

## Done when

A registered `ShieldedVerifier` backed by Winterfell accepts honestly-generated
bundle proofs and rejects tampered ones, with tests, with Rust and Python
agreeing on every vector, and with the gate still off.

Keep fuzzing the edges. Phase 1's verifier panic and Phase 2's `hash()` panic
were both found by poking rather than planning, and both changed a decision.
