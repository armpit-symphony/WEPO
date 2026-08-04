# Ghost Transfers — Phase 2 handoff: decide the in-circuit hash

**Runs on:** the Windows PC. Re-verified on the Linux box 2026-07-25 —
no `cargo`/`rustc`/`rustup`, and both `crates.io` and `static.crates.io` return
HTTP 403, so the Winterfell dependency tree cannot be fetched there at all.

**Branch:** `wallet-lab-fixes-20260409`, now pushed and at `4a03f4a`.

```
git fetch
git checkout wallet-lab-fixes-20260409
git pull
git log --oneline -1     # must show 4a03f4a or newer
```

Then relocate the spike from `C:\Users\limap\tmp_zk_spike` into `zk/` in the repo
and commit it — Phase 1's benchmark harness is the starting point for Phase 2 and
should be under version control before it grows.

Context: `docs/GHOST_TRANSFER_DESIGN.md` (spec),
`docs/GHOST_TRANSFER_WINDOWS_HANDOFF.md` (guardrails + Phase 1 results).

---

## The decision

Which hash do the note commitments and the Merkle tree use?

Today `shielded.py` uses **SHA3-256**. It was chosen because it is standard,
post-quantum, and available in the Python stdlib — deliberately, so the substrate
could be built and tested before the proving system existed. It was never claimed
to be the right in-circuit choice.

The circuit proves Merkle membership, which means **`MERKLE_DEPTH = 32` hash
invocations per spend, inside the AIR**. Keccak is brutal in an arithmetic
circuit; Rescue-Prime (`Rp64_256`, ships with Winterfell) is designed for exactly
this. The expectation is that Rescue-Prime wins decisively, but measure it — a
documented trade beats an assumed one.

**This is now-or-never.** Changing the hash changes the tag constants in
`shielded.py` and therefore **every note commitment and every Merkle root**. Free
before activation, impossible once mainnet notes exist. No genesis date is set.

---

## Cost nobody has priced yet — read before benchmarking

If Rescue-Prime wins, **the Python node also needs Rescue-Prime**, not just the
circuit. The node builds the note commitment tree, computes anchors, and
validates them. Rust and Python must produce **byte-identical** digests or the
chain splits. There is no vetted Rescue-Prime implementation in Python.

That is a real cost and it belongs in the comparison, not discovered afterwards.
Three ways out, and Phase 2 should recommend one:

| Option | Trade-off |
|---|---|
| **Implement Rescue-Prime in Python** | A permutation is a spec to follow, not a protocol to invent, so this is not the "hand-rolled soundness crypto" we banned — but a subtle mismatch is a silent chain split. Requires exhaustive cross-runtime vectors. |
| **Move tree/anchor maintenance into Rust** | One implementation, no divergence risk. Bigger refactor; the node takes a native dependency. Probably the right long-term answer. |
| **Python shells out to the Rust binary to hash** | Correct by construction, but hashing happens constantly during block validation, so process spawn per hash is almost certainly too slow. Measure before dismissing. |

**Also check the field.** Phase 1 ran `f128`. `Rp64_256` is a 64-bit-field hash,
so adopting it likely means moving to the 64-bit field — which changes query
counts, security margin, and proof size. Hash choice and field choice are
coupled; decide them together, not sequentially.

---

## Benchmarks to run

Keep everything except the hash fixed, or the comparison is meaningless.

1. **In-circuit Merkle membership**, depth 32, one spend — SHA3-256 vs
   Rescue-Prime. Report trace length, proof size, prove time, verify time.
2. **Native hash throughput** for both, since the node hashes constantly outside
   the circuit too.
3. **Projected bundle cost** — extrapolate 1-spend/2-output and 2-spend/2-output
   bundles. Ballpark is fine; the shape matters more than the digits.

## Settle 128-bit security in the same session

Phase 1's numbers were ~96-bit conjectured, no field extension. Report proof size
at a **128-bit** configuration for the winning hash. That number is what
block-size and shielded-fee policy actually get designed around — the current
working figure of ~20 shielded tx per 1MB block came from the 96-bit run and is
an optimistic ceiling. If 128-bit materially worsens it, that is a tokenomics
input and I want it before it is baked in, not after.

---

## Guardrails

All of `docs/GHOST_TRANSFER_WINDOWS_HANDOFF.md` still applies. The ones that bite
here:

1. **Do not edit `shielded.py` in this phase.** Phase 2 produces a recommendation
   and evidence; the swap lands as its own reviewed change once we agree. A
   partial swap — some tags moved, some not — silently corrupts every commitment.
2. **Do not hand-roll the proving system.** Implementing a *published hash
   permutation* against its spec and test vectors is fine and is not what that
   rule is about.
3. **Verifier panics must never reach the node process** (guardrail 5). Subprocess
   CLI is decided, not open.
4. **`WEPO_FEATURE_PRIVACY` stays `0`.**
5. Keep `backend/.env` and `frontend/.env` unstaged.
6. Commit trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

## Prep landed on the Linux box (commit `d774a05`) — pull before starting

Two things exist now that did not when Phase 1 finished:

1. **The pool hash is swappable.** Every digest routes through one registered
   `HashAlgorithm` in `shielded.py`. SHA3-256 is still the default and no digest
   changed. When Phase 2 picks a winner the swap is one registration plus one
   constant, not a scattered edit — and `_activate_hash_algorithm` rebuilds
   `EMPTY_ROOTS`, which is hash-derived and would otherwise go stale and produce
   wrong roots while still looking healthy.

   `using_hash_algorithm(name)` is a context manager for **benchmarking and
   vector generation only**. `POOL_HASH_ALGORITHM` is a consensus constant and
   deliberately not environment-configurable.

2. **Cross-runtime vectors exist.** `tests/vectors/shielded_sha3-256.json` pins
   every distinct hash usage; `tests/vectors/README.md` states the exact encoding
   a Rust port must match. Verified to have teeth: a one-character tag change
   trips 44 mismatches, dropping the length prefix trips 287.

   **Use these from day one of circuit work.** Have the Rust side read that JSON
   and reproduce every digest *before* writing any AIR. A Rust/Python hash
   disagreement is a silent chain split, and finding it after the circuit is
   built means rewriting the circuit.

   To generate vectors for a candidate hash:
   `python3 tests/shielded_vectors.py <algorithm> > tests/vectors/shielded_<algorithm>.json`
   (add the algorithm to the registry first — `blake2b-256` is wired up as a
   worked example of a non-default hash).

## Report back

- The benchmark table, SHA3-256 vs Rescue-Prime, held apples-to-apples.
- Recommended hash **and field**, with the reasoning.
- Recommended answer to the Python-side problem (implement / move to Rust / shell
  out), with the throughput number behind it.
- Proof size at 128-bit for the winner, and the revised shielded-tx-per-MB figure.
- Anything that surprised you. Phase 1's verifier panic was the most valuable
  thing that came back; it was found by fuzzing rather than by planning, so keep
  poking at the edges.

**Done when** we can make the hash decision on evidence — not when the swap is
implemented. The swap is the next change after that, and it should be small,
atomic, and covered by cross-runtime vectors proving Rust and Python agree
byte-for-byte.
