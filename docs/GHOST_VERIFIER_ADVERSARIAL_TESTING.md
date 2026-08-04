# Ghost Verifier Adversarial Testing

Status: deterministic local baseline; extended qualification remains open
Recorded: 2026-08-01

## Boundary under test

`tests/test_ghost_verifier_integration.py` invokes the optimized
`zk/target/release/ghost_verifier` executable for every case. It does not mock
the parser, proof verifier, process exit, or stdin framing. One process receives
one bounded request and must communicate only through its exit status.

The same test first generates an honest complete-circuit proof with the release
`ghost_fixture`, verifies it directly, and verifies a proof rebound to an exact
WEPO transaction sighash through Python, the subprocess, Rust, and node
consensus.

## Deterministic adversarial corpus

The maintained integration test requires all invalid cases to exit nonzero and
emit no stdout or stderr:

- 64 evenly sampled single-bit mutations across outer framing, public fields,
  proof metadata, and the Winterfell proof body;
- 14 truncations at protocol field boundaries;
- five hostile outer-envelope lengths, including zero and `u32::MAX`;
- invalid spend and output counts at their first out-of-policy and maximum-byte
  values;
- four signed value-balance boundary violations around the 61-bit policy;
- five hostile raw-proof lengths, including zero and `u32::MAX`;
- 64 deterministic pseudorandom blobs across ten sizes from zero through 4096
  bytes;
- one request larger than the 1 MiB envelope limit; and
- eight concurrent requests carrying an exact 1 MiB invalid envelope.

After the entire corpus, the original honest proof must still verify silently.
This proves the executable is stateless across invocations and that hostile
children do not contaminate later verification.

The separate Python-boundary suite proves invalid digest/proof types and sizes
are rejected before spawn, nonzero/crashing children fail closed, a hanging
child is terminated by the configured wall-clock timeout, shell command strings
are rejected, and the release executable is rehashed before every proof.

## Reproduction

Build and run the real integration boundary:

```bash
cargo build --release --locked --bin ghost_verifier --bin ghost_fixture \
  --manifest-path zk/Cargo.toml
python -m pytest -q tests/test_ghost_verifier_integration.py
```

Run the complete Rust release matrix:

```bash
cargo test --release --locked --all-targets --manifest-path zk/Cargo.toml
```

On the recorded Windows workstation, the Python integration passed in 1.13
seconds and the locked Rust release matrix passed. Timings are diagnostic only;
they are not release-host limits.

## Retained local fuzz evidence

The retained qualification runner
`wepo-blockchain/scripts/wepo_ghost_fuzz_qualification.py` records the pinned
container, dated nightly, cargo-fuzz version, stdout/stderr logs, corpora, and
artifact hashes without overwriting an existing evidence directory.

On 2026-08-01, `release-evidence/local/2026-08-01-ghost-fuzz-qualification-v2`
completed 27,926,832 parser executions in 30 seconds with no finding, then
failed the real verifier target after 10,369 executions on a nested Winterfell
`BatchMerkleProof` allocation path. The production verifier now preflights that
nested metadata before Winterfell vector reservation.

After the fix, `release-evidence/local/2026-08-01-ghost-fuzz-qualification-v3`
completed 318,913 real-verifier executions in 121 seconds with 246 new units,
160 retained corpus files, no crash, hang, OOM, sanitizer finding, or slow unit,
and 464 MiB peak instrumented RSS.

This closes a concrete resource bug and adds retained local bounded evidence. It
does not close Ghost release qualification.

## What this does not prove

This baseline deliberately does not close the readiness checkbox. Release
acceptance still requires:

- longer coverage-guided fuzzing of request/envelope parsing and hostile
  Winterfell proof metadata from the frozen release commit, with retained
  corpus, crash artifacts, tool/version hashes, and repeated clean runs;
- sanitizer or equivalent memory-safety runs on a supported native runner;
- intended-release-host CPU, peak RSS, process-count, timeout, and recovery
  measurements under sustained valid and invalid concurrency;
- an operator-enforced Linux resource policy that prevents verifier children
  from exhausting the node host;
  The source contract now specifies `TasksMax=128`, `CPUQuota=200%`,
  `MemoryHigh=60%`, `MemoryMax=75%`, and a fail-closed two-child default; this
  remaining item requires proof that the intended host actually enforces and
  survives those limits under pressure;
- review of the exact pinned verifier binary and build provenance; and
- independent cryptographic review of the AIR, public-input binding, hash use,
  proof parameters, and all critical/high finding dispositions.

Ghost consensus and client feature gates remain disabled until those items and
the separate wallet/prover and activation requirements are complete.
