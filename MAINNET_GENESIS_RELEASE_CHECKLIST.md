# WEPO Mainnet Genesis Release Checklist

Date: 2026-07-28
Status: Active draft launch gate; no readiness acceptance yet
Target: No release date. Earliest genesis is 30 full days after readiness acceptance.
Purpose: Turn the accelerated wallet-lab progress into a concrete launch gate for permanent mainnet genesis.

## Rule

Follow `MAINNET_READINESS_AND_RELEASE_POLICY.md`. Do not announce a genesis date
until every required gate is green and the protocol, security, wallet, and
operations owners accept the same release commit and parameter manifest. Any
material consensus or cryptographic change resets the 30-day clock.

The accelerated `test` wallet lab is valuable evidence, but it is not enough by itself to set a public genesis date.

## Release Decision Order

1. Merge and review the accelerated wallet-lab fixes.
2. Freeze the permanent mainnet scope and parameters.
3. Finish the remaining launch-scope truthfulness and cleanup work.
4. Run one production-like genesis rehearsal on permanent config.
5. Fix every rehearsal failure and re-test.
6. Hold a final go/no-go review.
7. Only then publish the official genesis date.

## Pre-Freeze Engineering Gates

### BLOCKER 1 - Review And Merge The Current Branches

- Review and merge `WEPO` branch `wallet-lab-fixes-20260409`.
- Review and merge `WEPO-wallet` branch `wallet-client-lab-fixes-20260409`.
- Confirm the final merged scope is intentional.
- Confirm no accelerated-lab finding remains open without an owner and disposition.

Notes:
- The `WEPO` branch must be reviewed as a platform branch, not as a one-commit skim.
- The wallet-lab work already proved useful chain-backed flows, so the immediate goal is to get that work merged cleanly.

### BLOCKER 2 - Release-Candidate Regression Matrix

- Run `python -m pytest -q` from a clean checkout. `pytest.ini` constrains
  discovery to the maintained suite; the current local matrix passes 194 tests,
  including formerly script-only consensus, manifest-bound release decisions,
  read-only freeze-CLI refusal, PoS/reorg, Redis fail-closed, RWA/key-anchor, deterministic restart/replay,
  five repeated live partition/invalid-block recoveries, bounded pending-branch
  storage, and complete Ghost verifier suites.
- Run the Rust release suite and the Python/JavaScript wallet-signing cross-check
  on a clean supported runner; retain logs and hashes. Both now pass locally on
  Windows, including locked all-target Rust tests and Python consensus acceptance
  of the JavaScript-signed transaction. `.github/workflows/release-validation.yml`
  defines clean Ubuntu jobs and a Windows desktop package-boundary job; retain
  the first green run as release evidence.
- Build the production frontend and desktop packages from pinned dependencies.
- Re-run wallet creation, import/recovery, unlock, send/receive, mining, and
  block-explorer flows on the release candidate.

Exit criteria:
- Every shipping core flow passes on the reviewed release commit.
- Every failure has an owner, fix, and retained re-test evidence.
- No accelerated `test` profile shortcut leaks into `mainnet`.

### BLOCKER 3 - Wallet Recovery And Cross-Language Authorization

- Prove the same recovery phrase restores the same spend keys and addresses on
  web and desktop from clean state.
- Prove JavaScript-generated transaction signatures and owner bindings verify
  in Python consensus, including change, timestamp, txid, and replay cases.
- Verify backups are encrypted, documented, and recoverable without server-held
  private keys.

Exit criteria:
- A clean-device recovery and signed send succeed end to end on both clients.
- Published vectors reproduce from the release artifacts.

Current local evidence (2026-07-29):
- New-wallet creation and phrase recovery are local-first and make no backend
  account request. Invalid imported phrases fail instead of silently creating
  different keys.
- The encrypted phrase, wallet descriptor, and device metadata roll back to
  their exact prior values after an injected split-write failure. Complete-vault
  password rotation has the same rollback guarantee and survives offline restart.
- The recovered/rotated ML-DSA key signs a send and verifies successfully. The
  wallet and gateway accept the canonical lowercase `wepo1q` address contract,
  carry amount and fee as exact decimal strings, reject JSON floating-point
  amounts, and forward normalized values to the live node without float
  conversion. Direct gateway and JavaScript/Python consensus tests pass. The
  Electron artifact packages the byte-identical canonical frontend and only its
  constrained main process; both shipped dependency graphs audit with zero
  findings.
  A project-owned transparent PNG and seven-resolution Windows ICO are now
  packaged without Electron's default-icon warning; every raw PE icon frame is
  byte-identical to the corresponding project ICO frame.
- A controlled live `test`-profile send through the real gateway/node confirmed
  tx `f1c7d73d5329bf86ea61c012030a9ee488f958ca32feecb73f916c8a0f1ed981`
  and settled exactly `1.23456789 WEPO`. The same transaction and atomic balance
  survived node restart with mining disabled. That rehearsal exposed and closed
  a fixed-difficulty-before-replay bug; sanitized JSON and before/after logs are
  retained under `release-evidence/local/2026-07-29-wallet-live/`.
- A 2026-08-01 package-bound rerun closed a stale-build release-path flaw:
  `dist-win` now rebuilds the canonical frontend before signing/packaging and
  release verification fails if the source or compiled artifact loses the
  wallet intent, local-password, txid, or fixed-KDF controls. Unsigned candidate
  executable
  `ee95c53dfae0fe85c31e7afecffd5f0cd7a48b242423fdf6522472d5a70df867`
  carried byte-identical web/Electron bundles. Intent-bound transaction
  `461ee4ffec2d9bdac251128bebfcd4fcb067e3cf1a182510113e5456abc6e4f6`
  settled exactly 123,456,789 atomic units and survived restart. Evidence is in
  `release-evidence/local/2026-08-01-wallet-artifact-live/`. The candidate is
  NotSigned and browser token error 1344 still prevents a human-visible
  installed-app claim.
- A human-visible clean installed application click-through against a live
  release node is still required; the Windows browser sandbox could not start.
  Windows `dist`/`dist-win` now fail before building unless the approved signer
  thumbprint and private credential are configured, then require timestamped
  Authenticode on the wallet and installer from that exact certificate. The
  current local executable remains correctly classified `NotSigned`; obtaining
  and securing the trusted production certificate remains an owner/operations
  action. The Windows CI job independently builds the unsigned development
  package, verifies canonical hashes and icon frames, and proves `dist-win`
  refuses unsigned output. Local evidence is retained under
  `release-evidence/local/2026-07-29-windows-package/`. The CRA build graph was
  replaced by pinned Vite/Vitest and the complete frontend graph now audits
  with zero findings. The shipped desktop graph also audits clean. Its
  build-only scanner still expands one CVE-2026-14257 metadata finding into 16
  high dependency-path reports, but all six locked `brace-expansion` instances
  contain the four-million-character fix and pass the fail-closed packaging
  verifier. Trusted signing and independent artifact acceptance remain open.

## Must Pass Before Genesis Rehearsal

### BLOCKER 4 - Mainnet Scope Freeze

- Write and approve the exact v1 launch scope.
- Mark each feature as one of:
  - launch
  - disabled at launch
  - post-launch

Scope list:
- permanent chain/node
- backend/API
- web wallet
- desktop wallet
- block explorer
- masternodes
- staking
- Ghost privacy sends / Quantum Vault
- private messaging
- RWA asset creation
- RWA trading
- BTC integration
- governance
- mobile wallets

Rule:
- Any feature still depending on lab-only accounting, compatibility-cache semantics, fake/demo behavior, or incomplete signing/sync logic must either be finished or removed from launch scope.

### BLOCKER 5 - Permanent Mainnet Parameter Freeze

- Finalize permanent genesis block data.
- Finalize chain ID and network magic.
- Finalize address prefixes and network discrimination rules.
- Finalize seed node list and seed ownership.
- Finalize bootstrap distribution plan.
- Finalize PoW and PoS activation heights.
- Finalize masternode collateral rules.
- Finalize staking minimums and reward schedule.
- Resolve the emission-reachability finding in
  `docs/EMISSION_SCHEDULE_AUDIT.md`. The implemented maximum is
  26,006,468.86718600 WEPO, not 69,000,003; approve ceiling-only economics,
  redesign the reward/unpaid-pool tail, or lower the cap truthfully. Re-run the
  independent cross-runtime oracle and all consensus tests after the approved
  change.
- Finalize coinbase-maturity depth; mainnet is fail-closed while it is unset.
- Finalize the node-local minimum relay-fee rate and canonical fee-settlement
  policy; mainnet relay is fail-closed while the rate is unset.
- Finalize checkpoints only if they are intentionally part of launch policy.
- Record all final values in one canonical document.
- Generate the exact `MAINNET_PARAMETER_MANIFEST.json`, freeze its raw SHA-256
  in the same reviewed source commit, and prove
  `mainnet_release_blockers()` returns no entries. A changed genesis flag alone
  is never sufficient to open mainnet.

Rule:
- No accelerated `test` profile timings, collateral shortcuts, activation compression, or lab-only defaults may leak into permanent mainnet values.

### BLOCKER 6 - Launch-Scope Truthfulness

- Remove or disable old bridge-era endpoint assumptions.
- Remove or disable fake/demo wallet flows.
- Ensure dashboards and status endpoints show live network values, not stale placeholders.
- Ensure wallet clients only expose features actually supported by the shipping backend and chain.
- Ensure unsupported ghost-transfer or privacy-adjacent routes are not shown as live if they are not truly launch-ready.

Known items that must be resolved or explicitly excluded:
- RWA trading is deferred and must remain unreachable in the release profile.
- Legacy auth/cache wallet compatibility paths must not be exposed by shipping clients.
- BTC integration and private messaging are disabled by default pending separate acceptance.
- Ghost remains rejected by consensus and hidden in clients until audit and activation review.

### BLOCKER 7 - Production Infrastructure Readiness

- Stand up production node hosts.
- Use the isolated three-host test-profile rehearsal pack in
  `wepo-production-deployment/THREE_HOST_SEED_REHEARSAL.md` before attempting
  a production seed rollout. It does not authorize mainnet, DNS publication, or
  a public release date.
- Stand up production backend hosts.
- Stand up production Redis and verify `WEPO_REQUIRE_REDIS_RATE_LIMIT=1` at
  startup and during a runtime outage.
- Stand up and back up only the databases required by the frozen release scope.
- Harden RPC exposure and firewall rules.
- Configure TLS, domains, and reverse proxies.
- Configure secrets management.
- Configure monitoring, alerting, evidence capture, and log retention.
- Validate backup and restore for chain data and backend data.
- Create restart, rollback, and incident runbooks.
- Define launch-day owner and on-call coverage.

## Must Pass In Genesis Rehearsal

### BLOCKER 8 - Full Production-Like Genesis Rehearsal

Run one full rehearsal from zero state on the permanent mainnet configuration.

Required checks:
- bootstrap node from empty data dir
- secondary node sync from zero
- backend attaches cleanly to the permanent config
- wallet create/import/unlock works
- wallet send/receive works
- masternode registration works if accepted in the frozen release scope
- PoS/staking works with the production signer if accepted; otherwise mainnet
  rejects it fail-closed
- every disabled optional surface remains hidden and rejected, including Ghost,
  RWA trading, BTC, and private messaging
- canonical transaction fee conservation works
- restart and crash recovery work
- fresh wallet can recover from seed after restart

Exit criteria:
- No blocker-severity failure remains unresolved.
- All failures are logged with owner, fix, and re-test evidence.
- The rehearsal result is treated as launch evidence, not a one-off demo.

## Must Pass Before Public Date Announcement

### BLOCKER 9 - Security And Operational Signoff

- Run a final security review on the merged launch scope.
- Review key management and wallet storage assumptions.
- Review node hardening and backend exposure.
- Review rate limiting, abuse paths, and denial-of-service posture.
- Review signing and release artifact integrity.
- Review dependency and secret handling.
- Record explicit signoff from engineering, ops, and security owners.

### BLOCKER 10 - Launch Artifacts And Public Readiness

- Build and verify release binaries/packages.
- Publish wallet installation instructions.
- Publish mainnet connection and verification instructions.
- Publish seed-node and bootstrap guidance.
- Publish operator instructions for masternodes and validators.
- Publish support path and status page.
- Publish exact genesis date, time, and UTC reference only after every blocker is green.

## Go/No-Go Meeting

Participants:
- protocol/chain owner
- backend owner
- wallet owner
- ops/deployment owner
- security reviewer

Agenda:
- review blocker status
- review accelerated-lab evidence
- review genesis rehearsal evidence
- review outstanding risks
- assign launch-day owner list
- approve or reject public genesis date

## Minimum Evidence Required Before Setting Any Public Date

- reviewed release commit and parameter manifest
- clean Python, Rust, JavaScript, web, and desktop build/test evidence
- independently reviewed genesis, emission, consensus, wallet, and cryptographic vectors
- three reachable seed nodes on independent failure domains
- production Redis, TLS, monitoring, backups, restore, and incident runbooks
- full multi-host genesis rehearsal and continuous seven-day release-candidate run
- final wallet recovery and user-facing truthfulness pass
- explicit protocol, wallet, security, and operations signoff

## Current Read On 2026-07-28

Locally strong:
- Mainnet is deliberately unavailable while genesis is unfinalized.
- Consensus spend authorization, supply clamping, fork/reorg boundaries,
  canonical wire limits, exact signed-fee identity and deterministic coinbase
  distribution, fail-closed v1 lock-time, Redis fail-closed behavior, and
  feature gates have regression coverage.
- Mainnet ignores test/staging feature opt-ins in both API layers and the
  frontend build; focused Python boundaries, 35 Vitest tests, and the
  optimized production frontend build pass.
- The Python matrix passes 194 tests, including live-loopback P2P, deterministic
  restart/replay, repeated live partition/invalid-block recoveries, bounded
  pending-branch/mempool bounds, concurrent admission accounting, fail-closed
  protocol-state identity conflicts, SQLite integrity and replay, verified
  online database backup/restore with tamper and overwrite rejection, and
  complete Ghost verifier integration. A committed cross-runtime v3 wallet vector now
  pins network-bound sighash/txid payloads and preimages, deterministic FIPS 204 signatures,
  normalized signed transaction bytes, and PoW/PoS header/signing bytes and IDs.
  JavaScript generation and Python verification match every byte, regenerate
  identically, and include tamper boundaries; this closed a real client txid
  mismatch caused by an omitted canonical null field. P2P regressions also
  enforce absolute handshake/partial-frame deadlines, immediate peer-slot
  release, and no dispatch of frames pipelined behind a disconnecting protocol
  violation. Three forced mid-transaction process-kill runs recover exactly to
  the last committed height with valid SQLite and canonical indexes. A separate
  7,200-block local volume rehearsal passes with 7,199 real signed transfers,
  exact crash replay, verified backup/restore, and exact restored replay;
  release-hardware, telemetry-derived load, off-host, and trusted-peer
  acceptance remain open.
  A retained local three-node hybrid PoW/PoS test-profile rehearsal also uses
  the real signer subprocess, replaces a signed height-6 block with a stronger
  PoW branch, retains signer anti-equivocation rows at heights 5/6/8, and
  converges all nodes to the same height-8 tip and semantic state. Evidence is
  under `release-evidence/local/2026-08-01-pos-multinode-v2/`; this run activated stake without exporting the validator private key. Release-image Linux
  deployment, independent hosts, extended duration, and review remain open.
  A separate pinned Debian 13 disposable Linux rehearsal proves distinct locked
  node/signer users, immutable root-owned signer and stake-policy code, exact sudo delegation, negative
  permission paths, restart/idempotence/conflict behavior, corrupt-state refusal,
  complete key-plus-state restore, and continued signing at heights 17/18.
  Sanitized evidence is retained under
  `release-evidence/local/2026-08-01-validator-signer-linux-v4/`. Intended-host
  systemd operation, fencing, encrypted off-host backup, and failover remain open.
  Transparent transaction signatures now bind the explicit network through
  `WEPO_SIGHASH_V3`; the node, browser wallet, API builders, signer policy, and
  cross-runtime vectors reject wrong-network replay. Mainnet remains locked, and
  the intended release artifact plus independent review are still required
  before this local evidence can satisfy the release gate.
  Canonical block/reorg mutations are serialized across P2P receive threads;
  60 consecutive live partition/reorg cases pass without the formerly
  intermittent issued-supply prefix race.
  A full branch-adoption regression also proves that a shorter difficulty-2
  branch replaces a longer difficulty-1 branch by cumulative work, preserves
  the losing history, and reopens with exact winning height/tip/supply.

  Live cross-network regressions additionally prove that mainnet/testnet wire
  magic cannot interoperate and that a matching-magic peer claiming the wrong
  handshake profile is disconnected and temporarily banned.

  The Node.js state oracle independently replays both the four-block
  signed-transfer chain and a real variable-difficulty fork. The fast branch
  retargets to difficulty 2 at height 10 and accumulates work 416, so it beats
  the height-15 difficulty-1 branch with work 256. The oracle recomputes the
  common ancestor, every Argon2id hash and live target, both branch scores, the
  shorter winning tip, and its exact UTXO/supply/state commitment; the Python
  node adopts that same branch only when its final block arrives and preserves
  the losing tip as noncanonical. Difficulty, score, winner, signature, and
  state tampering fail closed. A PoS candidate scenario independently derives
  its active 100-WEPO stake from the signed stake-lock transaction, recomputes
  weighted validator selection and the slot, reconstructs the exact SHA3-256
  signing digest, verifies the deterministic 2,420-byte ML-DSA signature and
  signed block ID, and proves the PoS tie-breaker creates no PoW. Stake, slot,
  digest, and signature tampering fail closed.
  The same scenario is committed through height 20: the active stake earns the
  full 12.5-WEPO pool at heights 15-17; a real signed masternode registration
  at height 17 preserves its complete 500-WEPO test-profile collateral and is
  first reward-eligible in the next block. Height 18 splits the pool exactly
  60/40. Signed stake and masternode deactivations spend both locks at height
  19, excluding both from same-block rewards, and height 20 confirms continued
  ineligibility. Node matches Python's lifecycle indexes, per-role reward
  totals/history, synthetic reward UTXOs, transaction identities, supply, tip,
  and state commitment. Registration-state, status, reward, and eligibility
  tampering fail closed.
  The continuation reaches height 23 with one owner-signed RWA creation and two
  owner-signed messaging-key registrations. Node independently matches the RWA
  index, exact key shapes and owner binding, registration history, and the
  height-23 latest-wins key. All 30,000 atomic units of metadata fees are
  present in canonical coinbase outputs, with zero issued-supply/UTXO delta.
  RWA, messaging, fee-redistribution, and supply tampering fail closed.
  A separate cumulative-work fork gives both branches different RWA assets and
  messaging keys. Python rebuilds both indexes from the height-15 losing branch
  to the height-10 winner at work 416 versus 256; Node derives both histories,
  chooses the same winner, proves 20,000 atomic units of fee redistribution per
  branch, and rejects forged canonical-index or rebuild evidence.
  A two-block shielded scenario confirms a signed 5-WEPO deposit and anchored
  spend. JavaScript reproduces transaction IDs, canonical sighashes, commitment
  and nullifier indexes, supply reconciliation, and disconnect/reconnect
  evidence. The Sage-pinned Rescue reference independently reproduces both
  roots and proof statement digests. Tampering fails closed across both oracles.
  This completes public consensus-state replay for the frozen v1 scope. It does
  not satisfy the separate external security audit required before Ghost can be
  enabled; the real prover, verifier, circuit, artifact pinning, and subprocess
  boundary remain in that gate.
  The PoW audit also corrected the preimage timestamp from 32-bit to the
  canonical 64-bit header width. Mainnet is unfinalized; evidence generated
  before this consensus change is diagnostic and must not qualify a candidate.
  A five-minute local real-socket hostile-traffic baseline passes 7,500 delivered
  attacks with one continuously healthy control peer, all seven slow-handshake
  deadlines, the 4,096-host ban cap, exact zero chain/database mutation, passing
  SQLite integrity, bounded measured resources, and clean peer/thread shutdown.
  This remains workstation evidence; independent-host internet paths with trusted
  propagation and the seven-day candidate rehearsal remain open.
  A separate abrupt-restart companion kills the target at height 10, advances
  the source to 15 during the outage, restarts from the same database, and
  converges to identical tip/supply with passing SQLite integrity while hostile
  connections continue. All 16 recovery acceptance checks pass. This remains
  workstation evidence; independent-host restart fault injection,
  release-hardware volume/disk telemetry, and the seven-day candidate rehearsal
  remain open.


Not ready for readiness acceptance:
- Genesis reward disposition and PoS launch/defer disposition remain owner decisions.
- Clean-runner Ubuntu/Windows workflow logs and artifact hashes are not retained yet.
- Independent consensus, wallet, and cryptographic reviews are not complete.
- Production seeds, Redis, TLS, monitoring, off-host backup retention,
  release-hardware volume/restore qualification, and multi-host rehearsal do
  not yet exist.

## Immediate Next Actions

1. Review and commit the current readiness branch as an auditable release-candidate change set.
2. Decide the 400 WEPO bootstrap disposition and whether PoS is shipped or deferred.
3. Recompute and independently review genesis, emission, signed payload, and owner-binding vectors.
4. Obtain clean Rust and JavaScript cross-check evidence on a supported runner.
5. Deploy the source-controlled anti-equivocation validator signer under a
   separate OS identity on the intended release image, then complete extended
   multi-host rehearsal and independent review,
   or keep PoS disabled in frozen consensus.
6. Complete independent consensus/wallet/Ghost security reviews and close critical/high findings.
7. Provision three independent seeds plus production Redis/TLS/monitoring only for the frozen scope.
8. Run multi-host genesis/restart/partition/recovery tests and a seven-day release-candidate rehearsal.
9. Start the 30-day public-release clock only after every readiness gate and signoff is green.
