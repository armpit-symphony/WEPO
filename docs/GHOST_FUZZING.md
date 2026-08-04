# Ghost Coverage-Guided Fuzzing

Status: maintained parser baseline and retained verifier qualification baseline;
extended release qualification still open
Recorded: 2026-08-01

## Reproducible toolchain

The first bounded run used the immutable container:

`rustlang/rust@sha256:512278c783d00322db4554dba748671cc269162b1b43fd577715118f5f64a033`

Inside that image:

- `rustc 1.99.0-nightly (ad3d0bc14 2026-07-31)`;
- `cargo 1.99.0-nightly (7c83d4cc0 2026-07-29)`; and
- `cargo-fuzz 0.13.2`, installed with `--locked`.

Both `zk/Cargo.lock` and `zk/fuzz/Cargo.lock` are source-controlled. The fuzz
package owns `libfuzzer-sys`; the production ZK manifest and lockfile do not.

## Targets

`wepo-blockchain/scripts/wepo_ghost_fuzz_qualification.py` runs the pinned Linux
container, records the exact toolchain, captures stdout/stderr, preserves the
final corpora, hashes every retained artifact, and refuses to overwrite an
existing evidence directory. It copies a filtered source tree into the container
so generated targets, previous fuzz corpora, node modules, release evidence, and
Git history are not treated as fuzz inputs.

Retained local evidence:

- `release-evidence/local/2026-08-01-ghost-fuzz-qualification-v1`: failed
  runner-debug attempt; retained to preserve the failed invocation record.
- `release-evidence/local/2026-08-01-ghost-fuzz-qualification-v2`: parser
  passed; verifier failed on a nested Winterfell proof allocation path.
- `release-evidence/local/2026-08-01-ghost-fuzz-qualification-v3`: verifier-only
  rerun after nested proof preflight hardening; passed.

`zk/fuzz/fuzz_targets/ghost_protocol.rs` independently exercises arbitrary
bytes through `parse_request()` and `parse_envelope()`. When both layers parse,
it also recomputes the public statement digest. A panic, overflow, sanitizer
finding, or unsafe allocation terminates the run as a failure.

`zk/fuzz/fuzz_targets/ghost_verifier_request.rs` calls the same shared
`verify_request()` core used by the production `ghost_verifier` subprocess. Its
runtime corpus is seeded by `ghost_fixture`, so mutations reach real Winterfell
proof metadata, public inputs, statement binding, and both WEPO framing layers.
The harness resets libFuzzer's panic hook because production treats contained
Winterfell parser panics as invalid proofs; process aborts, OOM, hangs, and
escaping panics still fail the fuzz run.

## Recorded bounded parser baseline

A 31-second Linux libFuzzer session completed:

- 28,114,270 executed units;
- 906,911 average executions/second;
- 118 coverage points and 139 features;
- 39 minimized in-memory corpus entries totaling 4,742 bytes;
- 157 new units added;
- zero crashes, hangs, sanitizer findings, or slow units; and
- 552 MiB peak RSS for the instrumented fuzz process.

The RSS figure includes sanitizer/libFuzzer instrumentation and is not a node
memory requirement.

## Recorded verifier proof-metadata smoke

The first real-verifier target exposed an unsafe allocation path: hostile
Winterfell proof metadata could request about 15 GB of vector capacity before
deserialization discovered the input was truncated. Production verification now
parses top-level proof bytes through a bounded reader that rejects oversized
collection counts before reservation while preserving the honest fixture.

After that fix and the panic-hook alignment, the immutable Linux container first
completed a verifier smoke seeded by a 69,506-byte honest request:

- 1,000 executed units;
- 2,394 coverage points and 3,187 features;
- 35 new units added;
- 27 in-memory corpus entries totaling 1,718 KiB;
- zero crashes, hangs, OOMs, sanitizer findings, or slow units; and
- 185 MiB peak RSS for the instrumented fuzz process.

That smoke is a regression tripwire for proof-metadata parsing and allocation.

The retained qualification runner then completed a 30-second parser run in
`2026-08-01-ghost-fuzz-qualification-v2`:

- 27,926,832 executed units;
- 900,865 average executions/second;
- 32 new units added;
- 73 retained corpus files totaling 10,016 bytes;
- zero parser crashes, hangs, sanitizer findings, or slow units; and
- 488 MiB peak RSS for the instrumented parser fuzz process.

The same retained v2 run found a second, deeper resource bug after 10,369
verifier executions: nested Winterfell `BatchMerkleProof` bytes could drive an
AddressSanitizer `allocation-size-too-big` failure before the final parse
rejected the malformed proof. Production verification now preflights the nested
FRI query and Merkle-proof byte buffers before Winterfell can reserve vectors.

After nested proof preflight hardening, retained verifier-only run
`2026-08-01-ghost-fuzz-qualification-v3` completed:

- 318,913 executed units in 121 seconds;
- 2,635 average executions/second;
- 246 new units added;
- 160 retained corpus files totaling 10,495,805 bytes;
- zero crashes, hangs, OOMs, sanitizer findings, or slow units; and
- 464 MiB peak RSS for the instrumented verifier fuzz process.

This is retained local bounded evidence, not final Ghost activation
qualification.

## Reproduction

From `/work/zk` inside the immutable container after installing cargo-fuzz:

```bash
cargo fuzz run ghost_protocol fuzz/seeds/ghost_protocol -- \
  -dict=fuzz/dictionaries/ghost_protocol.dict \
  -max_total_time=30 -jobs=1 -workers=1 -print_final_stats=1

mkdir -p /tmp/wepo-ghost-verifier-corpus
cargo run --release --locked --bin ghost_fixture -- \
  /tmp/wepo-ghost-verifier-corpus/honest_request
cargo fuzz run ghost_verifier_request /tmp/wepo-ghost-verifier-corpus -- \
  -runs=1000 -max_len=131072 -timeout=5 \
  -jobs=1 -workers=1 -print_final_stats=1
```

Every release-validation CI run also uses the dated nightly toolchain and pinned
cargo-fuzz version for an exact one-million-execution parser smoke with a
4096-byte maximum input and a 1,000-run real-verifier smoke with a 131,072-byte
maximum input. These are regression tripwires, not substitutes for the longer
retained qualification sessions.

The initial minimized corpus is source-controlled under
`fuzz/seeds/ghost_protocol`; it was generated only from public protocol magic,
scanned for secret markers, and is bounded by a source contract.

Generated `corpus`, `artifacts`, `coverage`, and fuzz `target` directories are
ignored. A crash or coverage seed is promoted only after review, minimization,
secret inspection, and an accompanying regression test.

## Gate still open

This bounded local evidence does not constitute extended fuzz qualification.
Remaining evidence includes multi-hour parser and verifier runs, retained
minimized corpora and logs from the frozen release commit, repeated frozen-commit
runs, intended-host CPU/RSS/process pressure, sustained concurrency soaks,
review of the exact retained verifier binary/build provenance, and independent
cryptographic review. Ghost consensus and client activation remain disabled.