# Ghost Transfers — handoff to the Windows PC

**Why you:** the Linux box has no Rust toolchain (`cargo`/`rustc` absent) and
crates.io returns HTTP 403. Every credible post-quantum proving system is Rust.
That is the *only* thing blocking Ghost transfers, so the work moves to a machine
that can reach crates.io.

**Branch:** `wallet-lab-fixes-20260409`
**Start from commit:** `1290d54` — "Ghost transfers: build the real post-quantum
shielded-pool substrate"

```
git fetch
git checkout wallet-lab-fixes-20260409
git pull
git log --oneline -1     # must show 1290d54 or newer
```

Confirm you have the new files before doing anything else:
`wepo-blockchain/core/shielded.py`, `docs/GHOST_TRANSFER_DESIGN.md`,
`tests/test_shielded_pool.py`, `tests/test_legacy_privacy_unsound.py`.

**Read `docs/GHOST_TRANSFER_DESIGN.md` first.** It is the spec. This document is
only the execution plan.

---

## Where things stand

The sound half of the shielded pool is **built and tested**: note commitments,
depth-32 Merkle accumulator, nullifiers, double-spend set, anchor window, and the
bundle statement digest. All SHA3-256, no elliptic curves, post-quantum by
construction.

The missing piece is **the zero-knowledge proof**, and only that. Hiding amounts
and linkage at the same time is irreducibly a ZK statement.

The pool is closed by construction until you finish: `shielded.RejectAllVerifier`
refuses every proof, so `verify_bundle()` rejects even a structurally perfect
bundle. That default is load-bearing — see the guardrails.

---

## Guardrails — read before writing code

1. **Do not hand-roll the proving system.** Use a real library. The legacy
   `privacy.py` was hand-rolled and `tests/test_legacy_privacy_unsound.py` forges
   a valid-looking range proof from `os.urandom` with zero secret knowledge. That
   is the failure mode we are climbing out of; do not recreate it.
2. **Never register a verifier that can return `True` without checking a proof.**
   Not "temporarily", not "to unblock testing". If you need a test double, scope
   it inside the test the way `test_shielded_pool.py` does (accepts exactly one
   known statement digest, restores `RejectAllVerifier` in a `finally`).
3. **Do not flip `WEPO_FEATURE_PRIVACY`.** It stays `0` through the 2026-09-02
   genesis regardless of how well the circuit goes. It lifts after external audit.
4. **Do not touch the messaging crypto** (`@noble/post-quantum`, `wepoMessaging.js`,
   `messaging_relay.py`). It is vetted, live, and unrelated.
5. **Do not delete `privacy.py` yet.** `test_legacy_privacy_unsound.py` imports it
   as a standing guard. It gets deleted when the replacement path lands.
6. **Keep `backend/.env` and `frontend/.env` unstaged.** Always.
7. Commit messages end with:
   `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

## Phase 0 — prove the toolchain works

Do not design anything until this passes.

1. Install Rust via rustup (`https://rustup.rs`), then verify:
   `cargo --version`, `rustc --version`.
2. Verify crates.io is actually reachable from this machine — that is the whole
   reason for the move. `cargo search winterfell` should return results.
3. Confirm the existing Python tests still run here. On Windows the interpreter is
   usually `python`, not `python3`:
   ```
   python tests\test_shielded_pool.py
   ```
   Expect `RESULT: ALL CHECKS PASSED`.
   `tests\test_legacy_privacy_unsound.py` additionally needs `ecdsa` and
   `pycryptodome`; if they are not installed it is fine to skip it here — it is
   evidence, not a dependency of the new work.

**Report back:** cargo/rustc versions, whether crates.io resolves, and the
shielded-pool test result. Stop and report if any of the three fails.

## Phase 1 — library spike (do this before the real circuit)

Create a new crate at `zk/` in the repo. Pick a library:

| Option | Trade-off |
|---|---|
| **Winterfell** (preferred) | Production STARK, hash-based/PQ, circuit written as an AIR. Most direct fit for what we need. |
| **Plonky2** | FRI-based, very fast prover. Good fallback. |
| **RISC Zero** | zkVM — circuit is a Rust guest program instead of a hand-written AIR. Much easier authoring, but larger proofs and a heavier verifier. Take this if AIR authoring stalls. |

Then prove the pipeline end to end on something trivial — Winterfell ships a
Fibonacci AIR example; use it. Generate a proof, verify it, and deliberately
corrupt a byte to confirm verification **fails**.

**Report back:** library chosen and why, proof size in bytes, prove time, verify
time. Those numbers decide whether raw on-chain STARK verification is viable, and
we do **not** wrap in Groth16 — that reintroduces a trusted setup and elliptic
curves, destroying the post-quantum property. If proofs come out unusably large,
say so rather than reaching for a SNARK wrap.

## Phase 2 — decide the in-circuit hash

SHA3-256 is expensive inside an AIR. Benchmark it against a ZK-friendly
post-quantum hash (Winterfell ships Rescue-Prime, `Rp64_256`).

If we switch, `shielded.py`'s tag constants and hash function change, and **every
commitment changes with them**. That is fine right now and impossible later — so
this decision must land **before any mainnet notes exist**.

**Report back:** constraint-count / prove-time comparison and a recommendation.
Do not change `shielded.py` until we agree on the choice.

## Phase 3 — the circuit

Build up, don't big-bang it. Each step gets its own tests.

1. **Merkle membership only** — prove a commitment sits at some position under a
   given anchor, without revealing the position or the path.
2. **+ nullifier integrity** — prove the revealed `nf` equals `H(nk, rho)` for the
   note being spent.
3. **+ spend authority** — prove the prover holds the spending key authorising the
   note's `pk_d`.
4. **+ range** — every output value in `[0, 2^63−1]`. No negatives, no wraparound.
5. **+ balance** — `Σ(spent) + max(vb, 0) == Σ(outputs) + max(−vb, 0)`.

**Balance must be in-circuit.** Our commitments are hash-based and therefore not
homomorphic, so we cannot sum commitments the way Zcash does with Pedersen. This
is exactly why a transaction carries **one aggregate bundle proof** rather than a
proof per spend/output. `ShieldedBundle` is already shaped for that.

The public input is `bundle.statement_digest(sighash)` — it already binds anchor,
all nullifiers, all output commitments, `value_balance`, and the transaction
sighash. Bind the circuit to exactly that digest so a proof cannot be lifted onto
another transaction.

## Phase 4 — wire it to Python

Implement `shielded.ShieldedVerifier` and install it with `register_verifier()`.

Two boundary options — **start with the subprocess CLI**, it is far easier to get
right and the perf work can come later:

- **Subprocess CLI:** the Rust binary takes `(statement_digest, proof)` on stdin
  and exits 0/1. Simple, no build complexity, easy to sandbox.
- **PyO3 native module:** faster, but adds a build step to every node install on
  every platform. Only worth it once the circuit is settled.

Whichever you pick, the verifier must fail **closed**: any error, timeout, missing
binary, or malformed output means `verify()` returns `False`. Never `True` on an
exception path.

## Phase 5 — tests

- Rust: proof verifies; corrupted proof fails; proof for statement A rejected
  against statement B.
- Python: a new `tests/test_shielded_verifier.py` — real proof accepted, tampered
  proof rejected, proof rejected under a different sighash, and
  `verifier_is_audited()` reporting correctly.
- Re-run `tests/test_shielded_pool.py` — it must still pass unchanged, including
  the reject-all default when no verifier is registered.

---

## What is explicitly NOT in scope for this session

Consensus wiring (replacing `privacy_proof`/`ring_signature` in `blockchain.py`),
wallet-side note scanning and witness maintenance, and making
`NoteCommitmentTree._rebuild()` incremental. Those come after a working verifier.
`PRIVACY_CONSENSUS_ENABLED` stays `False` (`blockchain.py:148`).

## Definition of done for this handoff

A registered `ShieldedVerifier` backed by a real proving system that accepts
honestly-generated bundle proofs and rejects tampered ones, with tests, and
**`WEPO_FEATURE_PRIVACY` still `0`**. Enabling it needs an external audit of the
circuit and verifier — that is a separate, funded track.
