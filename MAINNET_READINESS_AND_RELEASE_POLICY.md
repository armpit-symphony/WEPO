# WEPO Mainnet Readiness and Release Policy

Status: active
Adopted: 2026-07-27
Release date: not set

## Decision

WEPO will not target September 2 or any other calendar date before technical
readiness is accepted. The earliest mainnet genesis is 30 full days after the
readiness decision.

“Perfect” cannot mean a guarantee that no defect will ever exist. For WEPO it
means a release candidate has defined consensus rules, no known critical or
high-severity defects, independent security review, reproducible evidence, and
successful operation across independent infrastructure.

The 30-day clock starts only when every blocking item below is green. A change
to consensus, transaction authorization, cryptographic verification, genesis
parameters, emission, fork choice, or P2P network identity resets the clock.

## Current release state

**NO-GO — readiness has not been accepted.**

The code intentionally keeps `MAINNET_GENESIS_FINALIZED=False`. The full node
refuses to start a mainnet profile in this state. The current timestamp and
quantum address are deterministic rehearsal placeholders, not public launch
parameters.
Owner scope decision (2026-08-02): Ghost privacy transfers and PoS with
validator signing are mandatory at launch. Neither feature may be marked
`deferred` in the frozen mainnet manifest. Their readiness bits remain false
until every implementation, intended-host, operational, and independent-audit
gate below is evidenced.


Known blocking decisions:

1. Decide where the 400 WEPO genesis bootstrap reward goes. The decision must
   specify burn, controlled distribution, or another auditable policy. No
   developer-controlled placeholder address may silently receive it.
2. Complete PoS production readiness. Canonical validator-key ML-DSA
   authorization, fail-closed external signing, slot pacing, and branch-aware
   reorg validation are implemented and tested. The production signer executable
   now validates the complete canonical payload and persists fail-closed
   anti-equivocation and stake-authorization state instead of signing opaque
   digests. A retained local three-node test-profile rehearsal activates stake
   without exporting the validator private key and covers live signing,
   partition, stronger-PoW reorg, retained anti-equivocation state, and
   post-reorg continuation. A pinned Debian 13 rehearsal proves the immutable
   policy/runtime and distinct locked node/signer users. Intended-release-image
   deployment, extended multi-host rehearsal, and independent audit remain
   required. Mainnet PoS currently fails closed.
3. Complete mandatory Ghost-transfer readiness. The verifier process
   boundary, complete Rust CLI, real proof integration, 61-bit value bound, and
   4-spend/2-output layout are implemented. Resource/fuzz testing, consensus and
   production wallet wiring/recovery, activation freeze, intended-host drills,
   and external audit remain blockers.
4. Select and independently review the mainnet coinbase-maturity depth. UTXO
   origin is persisted and replayed, and consensus, mempool admission, and wallet
   spendable-balance selection enforce maturity. Mainnet remains explicitly
   unset and therefore rejects spending block-issued value. Reproducible
   decision evidence carries 100 blocks as a non-approved conservative candidate:
   600 minutes in the six-minute phase and 300-900 minutes under hybrid pacing.
   Multi-host reorg and pool/wallet evidence remain required before selection.
5. Select and publish the minimum relay-fee rate. Canonical-byte fee-rate
   admission is implemented strictly as node-local mempool policy, so it cannot
   invalidate an otherwise valid block. Mainnet remains unset and refuses relay
   admission. Stake and masternode lifecycle builders can pay fees without
   eroding locked principal or collateral. The committed 8,160-byte ML-DSA
   wallet vector proves that its 10,000-atomic default fee supports at most
   1,225 atomic/kB; 1,000 atomic/kB is a non-approved compatibility candidate.
   The shipping transparent wallet now obtains a node quote from the exact
   fixed-size ML-DSA shape, independently reproduces its canonical size and fee
   floor, displays the exact fee/rate/total, and rechecks live policy before
   decrypting the spend key after explicit approval. Any other transaction shape
   enabled for mainnet must adopt the same boundary or remain deferred before a
   positive rate can be frozen.
   The mainnet profile now rejects stake, masternode, RWA, and messaging-key
   transaction types at the shared consensus-shape boundary whenever their
   readiness flag is false; every affected local builder fails before state or
   balance lookup. RWA and messaging are explicitly manifest-bound as
   `deferred`. PoS lifecycle and Ghost are mandatory and remain fail-closed
   until their release gates pass. See `docs/MAINNET_TRANSACTION_SHAPE_DISPOSITIONS.md`.
6. Resolve the emission-reachability defect. The independent oracle proves the
   present reward curve can issue at most 26,006,468.86718600 WEPO, leaving
   42,993,534.13281400 WEPO of the advertised 69,000,003 cap unreachable.
   Approve whether the cap is only a ceiling, redesign the tail and unpaid-pool
   rules to target it, or lower the cap with truthful path-dependent supply
   language. See `docs/EMISSION_SCHEDULE_AUDIT.md`. No replacement economics
   are authorized yet. The source-hash-bound combined evidence and exact-target
   invariants are retained in `docs/MAINNET_PARAMETER_DECISION_EVIDENCE.md` and
   `tests/vectors/mainnet_parameter_decision_evidence_v1.json`.

Partial activation now fails closed as one contract rather than a collection of
assumptions. Full-node startup enumerates every unresolved genesis, bootstrap,
emission, maturity, relay-fee, PoS, Ghost, and manifest blocker. A future release
must include the exact machine-generated `MAINNET_PARAMETER_MANIFEST.json` and
freeze its raw SHA-256 in source. Missing, byte-modified, rehashed-semantic, or
internally inconsistent manifests are rejected before a mainnet data directory,
P2P listener, or API is created. The read-only production-host verifier runs the
same gate for mainnet while allowing pre-freeze `test`-profile qualification.


Current local evidence (2026-08-02): `python -m pytest -q` is constrained by
`pytest.ini` to the maintained suite and passes 260 tests. The frozen release
qualification minimum remains 243. Coverage includes mandatory-feature consensus gates, verifier concurrency saturation, fuzz dependency/corpus/CI contracts, formerly
script-only consensus, spend authorization, manifest-bound release decisions,
PoS/reorg, Redis fail-closed, RWA/key-anchor, deterministic restart/replay,
five repeated live partition/invalid-block recovery cases, bounded pending-branch
storage, and complete Ghost verifier integration suites. The Vite frontend
production build and 35 Vitest tests pass; the complete frontend graph and
shipped desktop graph both audit with zero findings. The exact release Rust checks now pass
locally: formatting, locked release all-target tests, and the four verifier
evidence binaries. The JavaScript-produced ML-DSA transaction passes Python
address, sighash, signature, and consensus validation, including ten serialized
passes split across test and default-mainnet profiles. GitHub Actions defines
the same Ubuntu jobs plus a Windows desktop package-boundary job; its first
retained green run remains pending evidence.

The controlled live-wallet acceptance now also proves a client-side ML-DSA send
through the real gateway/node, exact `1.23456789 WEPO` recipient settlement, and
confirmation persistence after reopening the same chain with mining disabled.
That restart exposed and closed an accelerated-lab bug where a fixed difficulty
was installed after canonical replay. Sanitized evidence and before/after logs
are retained under `release-evidence/local/2026-07-29-wallet-live/`. Interactive
installed-app acceptance remains open because the Windows browser sandbox could
not start on this runner. Local Windows package evidence is retained under
`release-evidence/local/2026-07-29-windows-package/`: clean lockfile installs,
zero shipped dependency findings, byte-identical canonical frontend files, all
seven PE icon frames, and unsigned-release refusal pass. The desktop build-only
scanner report is isolated to CVE-2026-14257 metadata; every locked
`brace-expansion` maintenance release contains the four-million-character bound
and passes a fail-closed runtime probe before packaging. A trusted signing
certificate, timestamped artifacts, installed-app acceptance, and independent
artifact acceptance remain open.


## Readiness gates

### 1. Consensus and monetary invariants

- [ ] Canonical genesis timestamp, reward address/policy, block hash, and Merkle
  root are reviewed and published.
- [ ] Supply cap and every emission phase are independently recomputed from
  code and match the published schedule exactly.
  The independent JavaScript oracle now covers genesis, all five PoW ranges,
  every PoS integer-halving cohort through the zero-reward tail, paid and paused
  pools, all-PoW and post-activation-all-PoS paths, exact phase boundaries, and
  one-unit/one-height tampering. It exposed and tests the correction of
  float-derived Phase 2B/2C rewards. It also proves the current maximum schedule
  stops at 26,006,468.86718600 WEPO and therefore never exercises the
  69,000,003-WEPO clamp. This gate remains open until replacement economics or
  truthful ceiling-only policy is approved, implemented, re-vectorized, and
  independently reviewed. See `docs/EMISSION_SCHEDULE_AUDIT.md`.
- [x] Fork choice uses cumulative work and is covered by reorg tests.
  An adversarial full-path regression proves that a 10-block branch with a
  difficulty-2 tip replaces a 15-block difficulty-1 branch because its
  cumulative PoW is greater. The losing tip remains indexed as noncanonical
  history; canonical height, tip, issued supply, SQLite integrity, and
  post-restart replay all match the winning branch. PoS progress can break only
  an equal-PoW tie and cannot manufacture work.
- [x] Timestamp, difficulty, coinbase, fee, maturity, duplicate-input,
  signature-owner binding, and replay invariants have regression tests.
  Local tests prove transaction validation is identity-preserving: the signed,
  declared fee must exactly equal transparent/shielded value conservation and
  validation never rewrites a Merkle-committed transaction. Version 1 has no
  finalized absolute/relative lock semantics, so nonzero `lock_time` and
  nonfinal input sequence fail closed. The unused transparent `script_sig` must
  be empty and output scripts must use canonical bytes, preventing unsigned
  legacy fields from malleating a valid ML-DSA transaction ID. Coinbase maturity
  origin is persisted in the UTXO set, rebuilt from canonical blocks on restart,
  and enforced at both mempool and block validation; wallet balance/selection
  exposes only next-block-spendable rewards while reporting immature rewards
  separately. The mainnet depth remains an
  explicit owner parameter decision and is fail-closed while unset.
  Coinbase validation reconstructs the complete canonical payout list rather
  than checking only its total. Fee shares use deterministic integer arithmetic
  and stable stake/masternode ordering, and redirection of a required protocol
  fee output is rejected.
  Derived PoS and fee-reward records use the canonical block timestamp rather
  than local wall-clock time, making replay evidence stable across nodes.
  Difficulty retarget thresholds use exact integer-ratio comparisons and the
  target phase of the candidate height, including the initial-to-long-term
  boundary; consensus no longer depends on floating-point rounding.
  Wallet, gateway, and lifecycle API amounts use exact decimal-to-atomic parsing,
  are forwarded as canonical decimal strings, reject JSON floating-point values,
  sub-atomic precision, non-finite values, booleans, and values above the supply
  cap, and never round currency through binary floating point before signing.
  Hybrid retargeting considers only the last ten PoW headers, so interleaved PoS
  headers with zero difficulty and faster timestamps cannot collapse or distort
  the next PoW target.
  Issued-supply accounting counts only actually persisted PoS pool rewards.
  When no eligible recipient exists the pool pauses without consuming cap
  headroom, while redistributed transaction fees remain excluded from issuance.
  A per-height issuance prefix is rebuilt deterministically on startup/reorg and
  extended atomically per block, eliminating the prior full-chain rescan from
  steady-state validation while preserving rollback and restart equivalence.
  Canonical block addition and branch replay are now serialized across P2P
  receive threads by one re-entrant state lock. This closes an intermittent
  race where concurrent adoption could clear another replay's supply prefix;
  60 consecutive live partition/reorg cases pass after the fix.
- [x] Mainnet and testnet have distinct message framing and handshake identity.
  Live-socket regressions prove that real mainnet and testnet nodes reject and
  temporarily ban each other before handshake completion because their wire
  magic differs. A second adversarial case uses valid testnet framing but claims
  a mainnet handshake profile and is also disconnected and banned, proving both
  separation layers independently.
- [x] State replay from genesis produces the same UTXO and consensus state on
  at least two independent implementations or one implementation plus an
  independent state-transition oracle.
  The independent Node.js oracle replays a deterministic four-block
  signed-transfer chain from genesis and derives the exact Python UTXO set,
  issued supply, tip, and state commitment. It also replays two full
  variable-difficulty branches: a height-15 difficulty-1 branch with work 256
  and a fast branch that retargets to difficulty 2 at height 10 with work 416.
  From the common genesis ancestor, it independently selects the shorter
  higher-work branch and reproduces the state adopted by the real Python node.
  Header IDs, Argon2id-v19 hashes and targets, seven boundary vectors, live
  retargets, cumulative work, txids, Merkle roots, owner-bound ML-DSA spends,
  coinbase maturity, fees, transparent UTXOs, and state commitments are checked.
  Regeneration is byte-identical; PoW, difficulty, score, winner, signature,
  maturity, and state tampering fail closed.
  A PoS candidate scenario now derives a 100-WEPO active stake from its real
  signed stake-lock transaction, recomputes deterministic SHA3-256 weighted
  validator selection and slot pacing, reconstructs the exact domain-separated
  signing digest, verifies the deterministic 2,420-byte ML-DSA signature and
  signed block ID, and proves that the PoS tie-breaker adds no PoW. Stake,
  slot, digest, and signature tampering fail closed independently of Python
  validation.
  The scenario now continues through height 20. The stake receives the full
  12.5-WEPO pool at heights 15-17; a real signed masternode registration at
  height 17 preserves its complete 500-WEPO test-profile collateral and is not
  rewarded in its own block. Height 18 splits the pool exactly 60/40, then
  signed stake and masternode deactivations spend both locks at height 19, with
  neither eligible in that block or at height 20. Node independently validates
  registration metadata, collateral and fee-input preservation, both lifecycle
  indexes, exact per-role rewards, reward history, synthetic UTXOs, deactivation
  identities, issued supply, tip, and state commitment. Masternode state,
  registration outpoint, reward, and eligibility tampering fail closed.
  The continuation now reaches height 23 with an owner-signed RWA creation and
  two owner-signed messaging-key registrations. Node independently enforces RWA
  ID uniqueness, owner/hash binding and exact metadata rows; exact ML-KEM/ML-DSA
  key sizes, owner binding and latest-confirmed-registration-wins behavior; and
  all three metadata fee settlements. Exactly 30,000 atomic units are charged
  and 30,000 are redistributed through canonical coinbase outputs, leaving zero
  issued-supply/UTXO delta. Forged RWA state, messaging latest/history, fee, and
  supply evidence fail closed.
  A separate cumulative-work fork commits different RWA assets and messaging
  keys to both branches. Python initially indexes the height-15 losing state,
  then rebuilds both tables to the shorter height-10 branch when its work reaches
  416 versus 256. Node independently derives both histories, selects the same
  winner, verifies 20,000 atomic units of fee redistribution per branch, and
  rejects forged canonical-index or rebuild evidence.
  A two-block shielded scenario confirms a signed 5-WEPO deposit and anchored
  spend. JavaScript independently enforces shielded value conservation,
  reproduces transaction IDs and canonical sighashes, and derives commitment
  and nullifier rows plus supply reconciliation. The Sage-pinned pure-Python
  Rescue reference independently reproduces both block-boundary roots and both
  proof statement digests. Python disconnects to the exact one-commitment,
  no-nullifier prefix and reconnects to identical final state. Commitment,
  sighash, reconnect, root, and statement-digest tampering fail closed.
  The PoW audit corrected its timestamp preimage from unsigned 32-bit to the
  canonical unsigned 64-bit header width. Mainnet is unfinalized, so all
  pre-change evidence is diagnostic rather than candidate qualification.
  This closes the independent public-state replay gate for the frozen v1
  scope. It does not close the separate Ghost security gate: the fixture's
  state-machine test double is not proof evidence, and external audit approval
  of the real prover, verifier, circuit, artifact pinning, and subprocess
  boundary remains required. See `docs/STATE_TRANSITION_ORACLE.md`.

- [x] Consensus serialization and signed payloads have stable published test
  vectors.
  The committed v2 cross-runtime fixture pins exact canonical UTF-8 payloads,
  little-endian length-prefixed sighash and txid preimages, deterministic FIPS
  204 signing, normalized signed-transaction bytes, txid, PoW/PoS canonical
  header and validator-signing bytes, and block IDs. JavaScript generates and
  verifies the fixture; Python reconstructs and verifies every byte and digest,
  including tamper boundaries. Regeneration is byte-identical with SHA-256
  `65f45db0adf3e5e38f0683192d4e93626210c02f39a5196da06512239c3ba9ae`.
  This work exposed and closed a missing-null-field client txid mismatch.

### 2. Cryptography and transaction safety

- [x] Production startup requires the real FIPS 204 ML-DSA implementation; no
  simulation or permissive fallback is reachable.
  The RSA formatter/signer/verifier implementation and its cryptography imports
  have been removed from the consensus module. If `dilithium-py` is absent,
  every public constructor, keygen, sign, verify, metadata, verifier-wrapper,
  and compatibility entry point raises before cryptographic work. A `python -S`
  subprocess proves all eleven direct and compatibility surfaces fail closed.
  Mainnet full-node construction and backend lifespan startup both require real
  ML-DSA before chain or database initialization. Real keygen/sign/verify,
  tampered-message rejection, source-absence, and startup-order tests pass in
  both focused and full maintained matrices.
- [ ] Wallet key generation, backup, restore, signing, owner binding, change,
  fee selection, and transaction submission pass cross-language vectors.
  Local technical evidence is green: 35 frontend tests and seven Python
  wallet/gateway vector tests pass. The wallet rejects self-consistent malicious
  builder output that changes the recipient, amount, fee, change owner,
  transaction shape, metadata, shielded fields, input outpoints, or integer
  bounds before signing. It verifies every local ML-DSA signature, requires the
  returned node txid to match the locally computed signed-transaction ID, never
  sends a vault password to a login endpoint, and rejects malformed or
  attacker-costed encrypted-vault envelopes before PBKDF2.
  A fresh package-bound `test`-profile rehearsal verified executable SHA-256
  `ee95c53dfae0fe85c31e7afecffd5f0cd7a48b242423fdf6522472d5a70df867`,
  byte-identical web/Electron bundles, embedded wallet security markers, exact
  pre-sign intent binding, local ML-DSA verification, and equal local/node txid.
  Transaction
  `461ee4ffec2d9bdac251128bebfcd4fcb067e3cf1a182510113e5456abc6e4f6`
  settled exactly 123,456,789 atomic units and survived database restart at the
  same height with mining disabled. Evidence is retained under
  `release-evidence/local/2026-08-01-wallet-artifact-live/`.
  The candidate is explicitly NotSigned, and the browser runner again failed
  with Windows token error 1344. This gate remains open until clean-device
  recovery and signed-send UI acceptance pass on final signed installed
  web/desktop release artifacts and an independent wallet review is complete.
- [x] PoS canonical external signing, deterministic selection, slot pacing, and
  branch-aware state/reorg validation have adversarial regression coverage.
- [x] The production signer executable validates the full canonical PoS payload,
  recomputes the digest, binds network/height/parent/address/public key, rejects
  arbitrary opaque digests, retains idempotent signatures, and refuses a
  conflicting block at a previously signed height. The node-to-real-signer
  subprocess path produces a fully valid PoS block in regression tests. Public
  protocol-v3 request/response vector
  `tests/vectors/validator_signer_protocol_v3.json` regenerates byte-for-byte
  from the independent state-transition fixture and has SHA-256
  `e6f2ba31d07f25ad71701b0a78dd7cb5e2d58d3c9471e712f7f17386a45cc868`.
  Protocol v3 also makes validator activation and withdrawal cold-key
  operations: exact signer-only operator authorization, network-bound
  `WEPO_SIGHASH_V3`, owner-only value flow, a fee ceiling, and persistent
  outpoint fencing are required before the bounded node subprocess may sign.
  The validator private key is never exported to the node or controller.
- [x] A local three-node `test`-profile rehearsal used real node and signer
  subprocesses to create signed stake, produce PoS, partition, build a stronger
  PoW branch, rejoin, replace the signed height-6 block with PoW, retain signer
  authorizations at heights 5/6/8, and converge to equal semantic state at
  height 8. Sanitized evidence and verified hashes are retained under
  `release-evidence/local/2026-08-01-pos-multinode-v2/` (cold-key activation,
  SHA-256 `1b26f02a9f7e88c29e82a78331903e42774277bcbe56a7486dd5389a02ba0879`).
- [x] A pinned Debian 13 disposable Linux rehearsal created distinct locked
  `wepo-node`/`wepo-signer` users, a root-owned immutable runtime, private key
  and state paths, an immutable stake-policy module, and exact `NOEXEC` sudo
  delegation. It proved allowed signing
  plus forbidden command/argument paths, heights 17/18 across process restarts,
  idempotence, conflict refusal, corrupt-state fail-closed behavior, complete
  key-plus-state restore, and SQLite integrity. Sanitized evidence is retained
  under `release-evidence/local/2026-08-01-validator-signer-linux-v4/` (SHA-256
  `afd8b045ad496a9d9844dcd366233c380fb37832929b9df19affc249c080ff8a`).
- [ ] Separate-user signer deployment on the release image, extended multi-host
  rehearsal, and independent audit are complete, or PoS is removed from frozen
  launch consensus. See `docs/VALIDATOR_SIGNER_SECURITY.md`.
- [x] Ghost has a bounded, fail-closed Python subprocess boundary. Enabled
  startup requires source-controlled audit approval, a direct executable with
  an exact SHA-256 pin, and a valid activation height; the executable is
  rehashed before every proof.
- [x] The complete Rust Ghost verifier CLI, versioned statement-bound proof
  envelope, honest proof integration, 61-bit value bound, and v1
  4-spend/2-output bundle-layout policy are implemented and cross-tested.
- [x] Ghost raw proofs bind the canonical transaction sighash as Winterfell
  public input; outer-envelope rebinding with the same raw proof is rejected.
- [x] Inactive Ghost consensus plumbing persists commitments, anchors, and
  nullifiers atomically and passes mempool/same-block conflict, disconnect,
  replay, restart, and corrupted-state fail-closed tests.
- [x] Versioned canonical transaction signatures bind timestamp, every
  unsigned field, and the explicit network without delimiter ambiguity; the
  versioned txid commits
  to the complete serialized transaction. Python regression cases and repeated
  v3 JavaScript/Python consensus cross-checks and wrong-network rejection pass.
- [ ] Extended resource/fuzz testing and independent Ghost audit are complete.
  A deterministic real-release-executable adversarial baseline now rejects 96
  parser-boundary, hostile-field, and seeded-random requests; 64 sampled
  single-bit mutations across an honest request; an over-limit request; and
  eight concurrent maximum-sized invalid requests. Every rejection is silent
  and nonzero, and the honest proof still verifies afterward. The Python
  boundary separately proves crash and timeout failure and now admits only two
  verifier children by default, rejecting saturation without a second spawn.
  The production node cgroup carries finite task, CPU, memory-high, and
  memory-max ceilings, and the read-only host verifier inspects their effective
  runtime values. Source-controlled libFuzzer targets now exercise request and
  envelope parsing, statement-digest recomputation, and the shared production
  verifier core with an honest Winterfell proof seed under a dated nightly
  toolchain, pinned cargo-fuzz, separate lockfile, dictionary, reviewed seed
  corpus, and a retained qualification runner. The parser run completed
  28,114,270 units in 31 seconds with no crash, hang, or finding; the exact
  one-million-run CI command also passes. The first real-verifier target found
  and drove a fix for a hostile top-level proof metadata path that could request
  about 15 GB of allocation before rejection. A retained verifier run then found
  a nested Winterfell `BatchMerkleProof` allocation path after 10,369 executions;
  nested FRI query and Merkle-proof byte buffers are now preflighted before
  Winterfell vector reservation. After that hardening, retained local verifier
  run `release-evidence/local/2026-08-01-ghost-fuzz-qualification-v3`
  completed 318,913 executions in 121 seconds, retained 160 corpus files, added
  246 new units, and reported no crash, hang, OOM, sanitizer finding, or slow
  unit, peaking at 464 MiB instrumented RSS. These are bounded local baselines,
  not multi-hour frozen-commit qualification, intended-host CPU/RSS/pressure
  qualification, a sustained concurrency soak, or an independent cryptographic
  audit, so the gate remains open. See
  `docs/GHOST_VERIFIER_ADVERSARIAL_TESTING.md`.
  See also `docs/GHOST_FUZZING.md`.
- [ ] Any enabled Ghost/shielded path verifies proofs out of process,
  fail-closed, with resource limits and adversarial malformed-proof tests.
- [ ] Enabled cryptographic code has an independent review with all critical
  and high findings closed.

### 3. Node and P2P reliability

- [ ] DNS seeds are resolved and static peers work when DNS is unavailable.
  The operator has supplied the owned registrable domain `wepocoin.org`; the
  registrar owner, MFA/recovery controls, DNS provider, API/seed FQDNs,
  operational DNS control, and live records remain required ops evidence. Do
  not ship the historical `wepo.network` placeholder or any DNS name until
  operational control and the records are independently verified.
- [ ] At least three publicly reachable seed nodes run on independent failure
  domains. AWS and DigitalOcean can provide two; the third should not depend on
  the same provider or a home NAT connection.
- [ ] Port 22567 reachability is verified externally for every seed.
  A source-controlled isolated three-host test-profile rehearsal pack now exists
  under `wepo-production-deployment/THREE_HOST_SEED_REHEARSAL.md`, with static
  peers, loopback-only API, and a local host verifier. It deliberately keeps DNS
  and mainnet off; no external host, firewall, or independent TCP-reachability
  evidence exists yet, so these gates remain open.
- [ ] Full transaction inventory/getdata propagation, claimed-txid binding,
  validation-before-relay, complete socket writes, handshake gating, and
  hostile-frame message limits pass a real two-node integration test. A live
  loopback TCP test now passes the bidirectional handshake, full transaction
  envelope, validation-before-relay boundary, complete socket send, and
  oversized-frame ban. Unit regressions also prove node-generated address
  envelopes round-trip through the receiving schema; failed outbound sockets
  close and enter escalating backoff; and malformed control, address,
  inventory, getdata, transaction, locator, header, oversized-frame, and
  pre-handshake messages are rejected with temporary in-process peer bans.
  Deterministic resource-boundary regressions additionally prove absolute
  handshake and partial-frame deadlines, immediate timed-out slot release, and
  that frames pipelined behind a disconnecting violation are never dispatched.
  This gate remains open until the same matrix passes across independent hosts.
- [x] Transaction and block decoders enforce exact canonical wire schemas,
  pre-construction count limits, per-transaction byte/script/metadata limits,
  declared block-size equality, and strict transaction-envelope fields.
- [ ] Nodes recover from restart, temporary partition, stale peers, invalid
  blocks, competing branches, and database replay without manual state edits.
  Local automated evidence now covers restart/replay, 60 repeated live
  two-node temporary-partition/competing-branch recoveries, stale-peer
  transport restart and locator catch-up, rejection without index contamination,
  and source-peer disconnect/temporary ban attribution.
  A separate two-process local baseline now proves an abrupt target kill at
  height 10, source advance to height 15 during the outage, same-directory
  restart, peer reconnect, exact tip/supply replay, and passing SQLite integrity
  while malformed TCP traffic continues before and after recovery. All 16
  acceptance checks passed; this remains loopback workstation evidence, so
  independent-host fault injection and the seven-day rehearsal keep this gate
  open.
- [ ] Resource limits, peer bans/backoff, message-size enforcement, and disk
  growth behavior are tested under hostile traffic.
  The pending side-branch/orphan cache now has global, per-parent, and
  height-ahead bounds with FIFO eviction coverage. Context-free header, merkle,
  PoW/PoS shape, timestamp, coinbase, and transaction checks precede admission.
  The mempool now enforces atomic 10,000-transaction and 64 MiB ceilings,
  maintains exact confirmation-time byte accounting, snapshots safely for block
  assembly, and exposes capacity telemetry. A mempool-specific sustained soak
  remains open.
  P2P unit coverage now closes slow-handshake, trickled partial-frame, delayed
  slot-release, post-violation pipelining, keepalive nonce/deadline, and clean
  service-thread shutdown cases. A five-minute local real-socket baseline also
  delivered 7,500 hostile attempts with zero connect/send failures while one
  valid peer survived every sample, all seven slow handshakes expired, the
  4,096-host ban cap was exercised, chain tip and 387,096 database bytes stayed
  exact, SQLite integrity passed, and post-shutdown peer/thread state was empty.
  Peak workstation growth was 7,933,952 RSS bytes, 3,106,867 Python heap bytes,
  four handles, and zero threads. This is local engineering evidence, not release
  qualification; independent-host internet-path traffic with trusted propagation
  and combined disk-growth rehearsal remain open, so this gate stays
  unchecked.
  Mempool and block validation enforce first-seen uniqueness for stake,
  masternode, and RWA state identifiers; masternode identifiers are immutable
  once confirmed, and endpoint metadata is bounded before persistence.
  SQLite now starts fail-closed with WAL, full synchronous durability, foreign
  keys, busy timeout, bounded journal retention, and structural integrity checks;
  restart/replay, deliberately corrupted-database tests, and three repeated
  forced kills during an active uncommitted block transaction all recover
  exactly to the last committed height. A local 7,200-block rehearsal now also
  passes after 7,199 real ML-DSA transfers, a forced uncommitted-write kill,
  exact source replay, verified backup, restore, and exact restored replay.
  This is a workstation engineering baseline, not release qualification.
  Startup cross-checks each denormalized block row against its canonical payload,
  requires the unique deterministic genesis for the selected network, and
  reconstructs derived consensus state from the validated block sequence.
  Structurally valid UTXO tampering is repaired by replay, while block-row drift,
  alternate valid-PoW genesis data, and structurally corrupt databases fail
  closed. The local 157,712,384-byte recovery point replays in 69.485 seconds
  and its restored copy replays in 71.348 seconds. Release-hardware measurement,
  telemetry-derived transaction volume, and approved RPO/RTO remain open.
  A source-controlled operator tool now creates consistent online SQLite
  backups, records SHA-256 and chain-tip evidence, verifies integrity before
  restore, and refuses destructive overwrite. Automated coverage proves live
  backup, restore/reopen equivalence, overwrite rejection, and tamper rejection.
  The local production-volume restore path passes. Off-host encrypted retention,
  independent verification, and trusted-peer catch-up remain open.
- [ ] A release-candidate network completes a continuous seven-day rehearsal
  with no unexplained consensus divergence.

### 4. API, deployment, and operations

- [ ] Production Redis is deployed and
  `WEPO_REQUIRE_REDIS_RATE_LIMIT=1` is verified both at startup and during a
  runtime Redis outage. The retained evidence must pass
  `wepo-production-deployment/verify-redis-outage-evidence.py` and must not
  disclose Redis URLs, credentials, cookies, wallet material, or client IPs.
- [ ] Public APIs are behind TLS and a trusted reverse proxy with explicit
  origins, proxy-header trust, request limits, and secrets outside source.
  A source-controlled inert production contract now requires HTTPS-only origins,
  TLS 1.2/1.3, HSTS, body/header/time/connection/request limits, forwarding-header
  overwrite, loopback-only backend/node APIs, private env files, distinct locked
  node/API identities, signed release-manifest verification, and a read-only host
  gate. Contract tests pass. Intended-host TLS, certificate, firewall, and
  external observation evidence do not exist yet, so this gate remains open.
- [ ] Builds and dependencies are pinned, scanned, reproducible, and signed.
  Both shipped npm graphs currently audit with zero findings, and the Windows
  release command fails before artifact creation without the approved signer.
  The current development executable is intentionally `NotSigned`; a trusted
  certificate/timestamped release, retained clean-runner evidence, and closure
  of build-only advisories remain required.
- [ ] Monitoring covers chain height, peer count, reorgs, rejected blocks,
  Redis, disk, memory, certificate expiry, and backup/restore.
  Node status now exposes process-scoped structured consensus reorg/rejection and
  P2P rejection/ban/backoff counters alongside height, tip, supply, peers, and
  mempool capacity. External retention, host/resource/datastore exporters, alert
  delivery, and threshold qualification remain open.
- [x] Runbooks cover deploy, rollback, key compromise, seed loss, chain stall,
  fork investigation, data restore, and security disclosure.

  Source-controlled runbooks also cover monitoring/alerts, hostile traffic,
  abrupt restart, production-volume recovery, and verified chain backup/restore.
  Intended-host exercises remain separate evidence.
- [ ] A clean machine can deploy from the release artifacts and reproduce the
  published genesis and test results.

### 5. Product truthfulness

- [ ] Every client-visible feature is either demonstrably working end to end or
  clearly absent. Backend gates now reject complete optional feature surfaces,
  matching frontend build gates hide them by default, and the production
  frontend build passes. Final release-profile acceptance remains required.
  Mainnet now ignores all test/staging opt-in flags at the backend, node API,
  and frontend build layers; focused Python tests, 35 Vitest tests, and
  an optimized production frontend build pass.
- [ ] No privacy, RWA, BTC, staking, or governance claim exceeds what consensus
  and the shipping clients enforce.
- [ ] Mobile and dApp surfaces are excluded unless they independently meet the
  same release standard.
- [x] The v1 scope document matches the code and has no stale blocker claims.

## Readiness decision package

The go/no-go review must receive a filled
`wepo-production-deployment/readiness-decision-package.template.json` artifact
that passes `verify-readiness-decision-package.py` and records:

- the exact release commit, signed source/archive hashes, and approved release signing-key fingerprint;
- full automated test and seven-day rehearsal evidence;
- the frozen parameter manifest and genesis construction transcript;
- external audit reports and finding dispositions;
- seed-node, Redis, monitoring, backup, and recovery evidence;
- an explicit list of disabled features and their enforcement points; and
- named approval from protocol, security, wallet, and operations owners, with
  every approval binding the same commit, parameter manifest, and signing key.

The read-only release gate independently validates and hash-binds the filled
seed inventory, Redis outage, monitoring, backup/restore, continuous seven-day
rehearsal, retained external-audit bundle, and release qualification evidence to
this package. Every file must name the same release commit. Monitoring,
backup/restore, rehearsal, audit, and qualification evidence must name the same
release artifact; rehearsal, audit, and qualification evidence must also name
the frozen parameter manifest. The operator invocation must supply all eight
artifacts:

```bash
python3 wepo-blockchain/scripts/wepo_mainnet_release_gate.py status \
  --seed-inventory /path/to/seed-node-inventory.json \
  --redis-outage-evidence /path/to/redis-outage-evidence.json \
  --monitoring-evidence /path/to/monitoring-evidence.json \
  --backup-restore-evidence /path/to/backup-restore-evidence.json \
  --seven-day-rehearsal-evidence /path/to/seven-day-rehearsal-evidence.json \
  --external-audit-package /path/to/external-audit-package.json \
  --release-qualification-evidence /path/to/release-qualification-evidence.json \
  --readiness-package /path/to/readiness-decision-package.json
```

Readiness is accepted only when all required approvers record GO against the
same commit and parameter manifest.

## Thirty-day release clock

At readiness acceptance (`T0`):

1. Set the proposed genesis time to no earlier than `T0 + 30 days`.
2. Publish the release commit, parameter manifest, genesis inputs, binaries,
   hashes, audit evidence, and seed endpoints.
3. Keep the candidate network and monitoring running through the full period.
4. Permit documentation and non-consensus operational fixes. Any material
   protocol or cryptographic change creates a new candidate and a new `T0`.
5. Perform a final go/no-go review at least 24 hours before genesis.

The date is an output of readiness, not a substitute for it.
