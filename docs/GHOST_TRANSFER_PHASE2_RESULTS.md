# Ghost Transfers — Phase 2 results: the in-circuit hash decision

**Run on:** Windows PC, `x86_64-pc-windows-gnu`, rustc 1.97.1, single-threaded
release builds, Python 3.12.10. Branch `wallet-lab-fixes-20260409` at `205dc79`.

**Recommendation: Rescue-Prime `Rp64_256` over the 64-bit Goldilocks field, with
a cubic extension. Move note-tree and anchor maintenance into Rust (option 2),
using batched subprocess hashing as the migration path.**

`shielded.py` was not modified, per guardrail 1.

Reproduce with:

```
cd zk
cargo run --release --bin phase2_native      # native hash throughput
cargo run --release --bin phase2_merkle      # in-circuit Merkle, depth 32
cargo run --release --bin phase2_scaling     # cost vs trace geometry
cargo run --release --bin rescue_len_probe   # upstream panic characterisation
python bench_python.py                       # node-side cost, all three options
```

---

## 1. The headline comparison

In-circuit Merkle membership, depth 32, one spend. Everything except the hash
held fixed.

| | trace | proof (128-bit) | prove | verify |
|---|---|---|---|---|
| **Rescue-Prime Rp64_256** | 256 rows × 13 cols | **35,049 B** | **5.7 ms** | **0.309 ms** |
| SHA3-256 (lower bound) | 250 cols × 8,192 rows | ≥166,351 B | ≥642 ms | ≥2.5 ms |

Rescue wins by **≥4.7× on proof size and ≥113× on prove time**, and those are
the *most favourable possible* SHA3 numbers. See §4 for why the real figure is
far worse.

The Rescue row is a real, working AIR — its trace root is checked against a
native `Rp64_256` recomputation, and a wrong anchor is rejected. It is not a
model.

Rescue at both security levels, same circuit:

| config | proof bytes | prove ms | verify ms | ≥128-bit |
|---|---|---|---|---|
| 32 queries, blowup 8, cubic | 27,964 | 6.3 | 0.249 | no |
| **43 queries, blowup 8, cubic** | **35,049** | **5.7** | **0.309** | **yes** |
| 32 queries, blowup 16, cubic | 32,069 | 9.4 | 0.269 | no |
| 28 queries, blowup 8, grind 16 | 26,424 | 7.6 | 0.209 | no |

Only `43q / blowup 8 / cubic` actually clears 128-bit conjectured security.
Raising the blowup factor does *not* substitute for queries here — worth knowing
before someone tunes for proof size and assumes the security followed.

## 2. Settling 128-bit (the tokenomics input)

**128-bit costs +25.3% proof size on the identical circuit** (27,964 → 35,049 B).
That is the honest marginal cost of the security upgrade.

Projected `ShieldedBundle` sizes at 128-bit, from measured trace geometry:

| bundle | trace | proof | prove | **tx per 1 MB block** |
|---|---|---|---|---|
| 1 spend, 2 outputs | 32 × 1024 | 54,914 B | 13.8 ms | **19.1** |
| 2 spends, 2 outputs | 32 × 2048 | 60,398 B | 27.1 ms | **17.4** |

Sizing assumption, stated so it can be argued with: per spend ≈ 256 rows Merkle
+ ~32 rows nullifier/commitment/spend-auth + ~64 rows 64-bit range ≈ 512; per
output ≈ 128 rows; width ≈ 32 (12 Rescue state + 1 path bit + range bits +
balance accumulator).

**The ~20 shielded tx/MB working figure survives.** The revised number is
**17–19 tx/MB at 128-bit** — a 5–13% reduction, not a material worsening. Fee
and block-size policy can be designed on this without waiting for the circuit.

## 3. The cost nobody had priced: the Python side

This is the part that changes the shape of the project, and the answer is not
the obvious one.

Per Merkle node hash:

| approach | per node | per 32-node path | vs SHA3-in-Python |
|---|---|---|---|
| SHA3-256 in Python (today) | 897 ns | 0.035 ms | 1× |
| **Rescue, native Rust (option 2)** | **3,921 ns** | **0.125 ms** | 4.4× slower |
| Rescue, batched subprocess (option 3) | 6,771 ns | 0.217 ms | 7.5× slower |
| Rescue, subprocess per hash (option 3 naive) | 4,509,837 ns | 144 ms | 5,027× slower |
| Rescue, pure Python (option 1) | 853,570 ns | 27.3 ms | **780× slower** |

**Option 1 — implement Rescue-Prime in Python — is disqualified, and not
narrowly.** It is *126× slower than simply shelling out to Rust in batches*. The
option that avoids the native dependency is comprehensively beaten by the option
that embraces it. Concretely, rebuilding the tree over 1M notes:

- SHA3 in Python today: **1.8 s**
- Rescue via batched subprocess: **13.5 s**
- Rescue in pure Python: **28.5 minutes**

That last figure is per rebuild, and `NoteCommitmentTree._rebuild()` currently
runs on every `append()`. Option 1 does not merely slow the node down; it makes
block validation impossible. It also carries the silent-chain-split risk, so it
was the highest-risk option *and* the slowest.

**Option 3 deserved the measurement the handoff asked for, and it changed the
verdict.** Per-hash spawning is indeed hopeless — 4.5 ms of process spawn on
Windows, 144 ms per authentication path. But batched, one spawn amortised over
10,000 hashes, it reaches 147,688 hashes/sec and lands within **1.7×** of native
Rust. Tree rebuilds and block validation are naturally batchable.

**Recommendation: option 2, with option 3 as the migration path.** Move
tree/anchor maintenance into Rust for the single-implementation, no-divergence
property that matters most here. But option 3 batched is a legitimate interim —
it needs no consensus refactor, and 1.7× off native is a price worth paying to
get the hash swap landed before genesis. Either way, cross-runtime test vectors
are mandatory.

## 4. Why SHA3-256 in-circuit is not merely expensive

Winterfell **hard-caps trace width at 255 columns**
(`winter-air/src/air/trace_info.rs:111`). Keccak-f\[1600] has a 1600-bit state,
and an AIR cannot XOR or rotate — bits must live in separate cells. **The state
does not fit in the trace at all.**

It must therefore be spread across rows: ≥7 rows just to *hold* 1600 bits at 250
columns, × 24 rounds × 32 tree levels ≈ 5,376 rows before any constraint logic.
The ≥166,351 B / ≥642 ms figure in §1 measures exactly that geometry — with
degree-1 constraints and zero helper columns.

The real cost is far higher: every one of the 1600 bits needs a `b² − b = 0`
booleanity constraint, θ needs parity helper columns, and χ is degree 2. Four to
ten times more rows is a conservative multiplier, putting a realistic SHA3
circuit at **~190–400 KB and 3–15 s per proof** — against Rescue's 35 KB and
5.7 ms.

This reframes the decision. It was posed as a trade to be measured; it is closer
to a feasibility boundary. Keccak in an AIR is not a slow option, it is a
different project.

## 5. Hash and field are coupled — decide together

`Rp64_256` is a 64-bit-field hash, so adopting it moves the circuit from Phase
1's `f128` to **Goldilocks f64**. That is not a cost, it is a benefit:

- Phase 1, f128, no extension, 96-bit: 42,964 B for a *toy* Fibonacci circuit.
- Phase 2, f64 + cubic, **128-bit**: 35,049 B for a *real* depth-32 Merkle circuit.

More security and vastly more useful computation, in a smaller proof. A 64-bit
field needs the cubic extension to reach 128-bit security, which is included in
every number above.

## 6. Things that surprised me

Per the handoff's instruction to keep poking at the edges — the two most
valuable findings again came from fuzzing, not planning.

**`Rp64_256::hash()` panics on most real-world input lengths.** It decides
whether it is on the final chunk by comparing `i` to `num_elements - 1`, but `i`
is a rate position reset to 0 every 8 absorptions
(`winter-crypto/src/hash/rescue/rp64_256/mod.rs:144-166`). Once input needs more
than 8 seven-byte chunks, that check stops identifying the last chunk and a
short final chunk hits a fixed-width `copy_from_slice`.

Probed exhaustively over lengths 0–200: **it panics for every length > 56 that
is not a multiple of 7** — 124 of 201 lengths, matching the predicted rule
exactly. This is directly load-bearing for us: `tagged_hash(_TAG_NODE, l, r)`
feeds ~90 bytes, squarely in the panicking range. **A naive port of
`shielded.py`'s byte-oriented hashing to `Rp64_256::hash()` would panic on
essentially every node hash.**

Mitigation, already applied in `zk/src/bin/hashcli.rs`: use the field-element
API (`hash_elements` / `merge`), which is unaffected. The swap must adopt an
explicit canonical byte↔field encoding rather than hashing serialised bytes.

**Winterfell's column-count checks disagree with each other.** `trace_info.rs`
accepts 255 columns; `proof/table.rs:55` rejects 255 with the message "number of
columns cannot exceed 255, but was 255". Off-by-one in the check or the message.
Practical cap is 254.

**Rescue is 19× slower than SHA3 natively** (3,921 ns vs 208 ns per node hash in
optimised Rust). The hash decision does not remove cost, it *relocates* it from
the circuit to the node — which is precisely why §3 is the real decision and not
a footnote.

**The `Air::new` panic path from Phase 1 recurs here.** `MerkleAir::new` still
can only `assert!`, because the trait returns `Self` and not `Result`. Guardrail
3 (subprocess boundary) is load-bearing, not ceremonial.

## 7. What Phase 2 did not do

- `shielded.py` untouched. The tag swap is the next change, and it must be
  atomic and covered by cross-runtime vectors.
- No Keccak AIR was written; §4 is a measured lower bound plus a stated
  multiplier, not a measurement of Keccak itself.
- Bundle sizes in §2 are projections from measured geometry. The Merkle row in
  §1 is real; the bundle rows are not yet.
- The Merkle AIR leaves the leaf unconstrained — it measures Merkle cost. The
  real circuit must bind the leaf to the note commitment.

## 8. Decisions requested

1. Adopt **Rescue-Prime `Rp64_256` + Goldilocks f64 + cubic extension**.
2. Adopt **43 queries / blowup 8** as the 128-bit production configuration.
3. Approve **option 2** (tree/anchor maintenance into Rust), with batched
   subprocess as the interim.
4. Accept **17–19 shielded tx/MB** as the planning figure for fee and block-size
   policy.
5. Note the upstream `Rp64_256::hash()` panic in the design doc so the swap does
   not reintroduce it.
