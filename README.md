# WEPO

WEPO is the platform repository for the WEPO network.

As of April 5, 2026, this repo should be treated as the source of truth for:

- blockchain and node code
- backend and API services
- genesis and network configuration
- staking, masternode, governance, and protocol logic
- deployment and operations assets

This repo should not be the long-term home for wallet clients. Web, desktop, iOS, and Android wallet ownership is being split toward `WEPO-wallet`.

## Status

> **Current decision (2026-07-27): WEPO is not production ready and has no
> mainnet release date.** Readiness is evaluated first; the earliest genesis is
> 30 full days after every gate in `MAINNET_READINESS_AND_RELEASE_POLICY.md` is
> accepted. This policy supersedes older date and blocker language below.

The full node deliberately refuses to start mainnet while
`MAINNET_GENESIS_FINALIZED=False`. Current genesis values are deterministic
rehearsal placeholders. The remaining critical path is:

1. decide and audit the 400 WEPO genesis-bootstrap distribution;
2. ship the production validator-signer executable/deployment, publish PoS
   vectors, and complete independent review (canonical ML-DSA authorization
   and branch-aware reorg tests now exist; mainnet PoS remains fail-closed);
3. finish Ghost resource/fuzz testing and independent cryptographic review
   (the complete Rust verifier, honest proof integration, 61-bit value bound,
   4-spend/2-output v1 bundle layout, transaction-sighash STARK binding, and
   inactive persistent/reorg-safe shielded consensus state are now implemented;
   wallet note/prover integration and activation specification remain);
4. independently reconcile the emission schedule and supply cap;
5. provision three independent public seeds, production Redis, monitoring,
   backups, and recovery runbooks; and
6. complete an independent audit and production-like multi-node rehearsal.

This repository is not production ready yet. Several core consensus and backend
findings from the 2026-06 audit are closed, but independent audit, hostile
rehearsal, wallet recovery, and production operations remain. Mainnet depends on
launch decisions and production infrastructure (see the launch documents below).

Release-blocker progress (June 2026):

- **Consensus spend authorization (BLOCKER #1) — fixed.** Every non-coinbase
  input must carry a Dilithium signature bound to the UTXO owner; unsigned spends
  and forged coinbase are rejected. This is a hard fork to client-side signing
  with quantum addresses (`wepo1q` + H(pubkey)); legacy `wepo1` sha256(seed)
  addresses are invalid on mainnet. See `tests/test_spend_authorization.py`.
- **Rate-limit identity bypass — fixed.** Rate limiting now keys on the real
  socket peer unless `WEPO_TRUST_PROXY_HEADERS=1` (set behind nginx). See
  `tests/test_rate_limit_identity.py`.
- **Launch-scope feature gating (BLOCKER #6) — done.** Features not launch-ready
  (zk-STARK privacy/Quantum Vault, RWA trading/vault, BTC relay/swaps, staging
  toggles) are disabled by default and return HTTP 503. See
  `backend/feature_flags.py` and `tests/test_launch_feature_gate.py`.
- **Scope & parameter freeze (BLOCKERS 4/5) — drafted, decisions recorded.** See
  `MAINNET_V1_LAUNCH_SCOPE.md` and `MAINNET_PARAMETER_FREEZE.md`.

Remaining gaps:

- Web-wallet client-side ML-DSA key generation/signing and Python vectors pass.
  Local-first creation/recovery, exact encrypted-vault rollback, complete-vault
  password rotation, offline restart, recovered-key signing, and canonical
  Electron packaging now pass automated acceptance tests. The wallet/gateway
  boundary now enforces canonical lowercase `wepo1q` addresses and carries
  amount/fee as exact normalized decimal strings without binary-float
  conversion. A controlled shipping-signer send through the real gateway/node
  confirmed and survived node restart, with byte-identical web/Electron bundle
  hashes and sanitized evidence retained under
  `release-evidence/local/2026-07-29-wallet-live/`. An interactive clean
  installed-app click-through, trusted release certificate, build-tool audit
  closure, and independent acceptance evidence remain. Both shipped npm graphs
  now audit with zero findings; the remaining frontend/desktop advisories are
  confined to build-only dependency graphs and are still tracked as release
  debt.
- The fixed 69,000,003 cap is enforced by consensus clamping regardless of the
  variable PoW/PoS mix; the schedule and cap still require independent
  reconciliation before parameter freeze.
- Genesis timestamp + `PRODUCTION_MODE` are set-at-launch; seed nodes/bootstrap
  not yet provisioned.
- Production infrastructure, genesis rehearsal, and final signoff still pending.
- `MAINNET_READINESS_AND_RELEASE_POLICY.md` - authoritative readiness gates and
  30-day release-clock policy.

## Launch documents

- `MAINNET_GENESIS_RELEASE_CHECKLIST.md` — the 10 launch blockers.
- `MAINNET_V1_LAUNCH_SCOPE.md` — current per-feature readiness / disabled / deferred scope.
- `MAINNET_PARAMETER_FREEZE.md` — canonical mainnet parameters + recorded decisions.

## Intended Repo Boundary

### This repo owns

- `backend/`
- `wepo-blockchain/`
- `wepo-production-deployment/`
- `data/genesis/`
- `genesis.json`
- `wepo-network-genesis.sh`
- `wepo-blockchain-bridge.py`
- `wepo-fast-test-bridge.py`

### This repo should not own long term

- `frontend/`
- `wepo-desktop-wallet/`
- `wepo-ios-wallet/`
- `wepo-android-wallet/`

Those wallet surfaces currently remain in-tree while the split is being planned, but they should be treated as migration candidates rather than stable ownership.

## Repository Layout

### Platform surfaces

- `backend/`: FastAPI service layer and backend security utilities
- `wepo-blockchain/`: blockchain, mining, node, wallet-daemon, and protocol code
- `wepo-production-deployment/`: deployment scripts and ops docs
- `data/genesis/`: genesis-related data

### Transitional / duplicate surfaces

- `frontend/`: current web wallet/client surface, planned for wallet repo ownership
- `wepo-desktop-wallet/`: current Electron wallet surface, planned for wallet repo ownership
- `wepo-ios-wallet/`: current iOS wallet surface, planned for wallet repo ownership
- `wepo-android-wallet/`: current Android wallet surface, planned for wallet repo ownership

## Current Priorities

1. Finalize repo ownership and remove duplication with `WEPO-wallet`.
2. Replace test/demo deployment paths with a real staging and production model.
3. Harden backend and chain behavior for public production.
4. Remove stale under-launch-review messaging and align docs with reality.
5. Clean generated artifacts, release bundles, and backup files from versioned
   source. (In progress: core `.bak`/`.new` backups removed, ~42 ad-hoc
   root-level test harnesses quarantined to `legacy/root-test-harnesses/`, and
   the large historical `test_result.md` moved to `legacy/`. The canonical
   smoke/soak/gate scripts remain in place.)

## Canonical Local Verification

The current authoritative local verification path for backend-originated canonical fee settlement is:

```bash
/home/sparky/WEPO/wepo-blockchain/scripts/run_canonical_fee_smoke.sh
```

That launcher:

1. starts a dedicated local node on `127.0.0.1:8122`
2. starts a dedicated local backend on `127.0.0.1:8011`
3. runs the canonical smoke at `/home/sparky/WEPO/canonical_fee_settlement_smoke.py`
4. verifies on-chain settlement plus Mongo state
5. tears the temporary processes down

For manual or deeper local work, the authoritative scripts are:

- `/home/sparky/WEPO/canonical_fee_settlement_smoke.py`
- `/home/sparky/WEPO/wepo-blockchain/scripts/run_canonical_fee_smoke.sh`
- `/home/sparky/WEPO/wepo-blockchain/scripts/run_canonical_fee_soak.sh`
- `/home/sparky/WEPO/wepo-production-deployment/run-canonical-release-gate.sh`
- `/home/sparky/WEPO/wepo-blockchain/scripts/run_test_mode_wallet_lab.sh`
- `/home/sparky/WEPO/wepo-blockchain/scripts/wepo_accelerated_simulation.py`

For repeated local backend/node verification under load, use:

```bash
/home/sparky/WEPO/wepo-blockchain/scripts/run_canonical_fee_soak.sh
```

That soak launcher now emits both:

- `summary.log`
- `summary.json`

under `SOAK_LOG_DIR`, including per-iteration duration, extracted trade metadata,
failure classification, and restart events.

Useful env overrides:

- `SOAK_ITERATIONS`
- `SOAK_PAUSE_SECONDS`
- `MAX_FAILURES`
- `SOAK_LOG_DIR`
- `VERIFY_IDEMPOTENT_REPLAY=true`
- `VERIFY_CONCURRENT_IDEMPOTENCY=true`
- `EXPECT_SETTLEMENT_DEPLETION=true`
- `BACKEND_RESTART_ITERATION=<n>`
- `NODE_RESTART_ITERATION=<n>`
- `RESTART_SETTLE_SECONDS=<n>`

## Accelerated Test Chain

For wallet, masternode, staking, privacy, and RWA feature testing on an accelerated chain profile, use:

```bash
/home/sparky/WEPO/wepo-blockchain/scripts/run_test_mode_wallet_lab.sh
```

That launcher starts a local node and backend on a `test` network profile with:

- compressed PoS activation height
- reduced collateral requirements
- low-difficulty mining for rapid funding and progression
- isolated node data under `/tmp/wepo-test-wallet-lab`
- isolated Mongo database defaulting to `wepo_test_wallet_lab`

The node and backend both report `network_profile=test` when that mode is active.
The default `mainnet` profile remains unchanged; stopping the lab and running the normal
node/backend without `WEPO_NETWORK_PROFILE=test` returns the system to its intended chain behavior.

The active backend/frontend runtime files no longer carry a built-in preview-host
default. Set explicit allowlists through env when needed:

- `WEPO_ALLOWED_ORIGINS` for backend/bridge CORS origins
- `WEPO_FRONTEND_CONNECT_SRC` for frontend CSP `connect-src`

For the full validated local public-test stack, including the built frontend on `127.0.0.1:3100`, use:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh start
```

For a fresh-chain test round from empty lab state, use:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh restart-clean
```

That operator launcher starts the accelerated wallet lab in tmux, builds the frontend by default, serves the secure frontend, and supports:

- `start`
- `start-clean`
- `restart-clean`
- `stop`
- `status`
- `logs`

## Legacy Paths

The following files still exist in-tree but should not be treated as the canonical production path:

- `wepo-fast-test-bridge.py`
- `wepo-blockchain-bridge.py`
- preview-era smoke/security scripts now quarantined under `legacy/preview-tests/`
- unreferenced backend backup files now quarantined under `legacy/backend-backups/`
- historical step2 result artifacts now stored under `legacy/step2-results/`
- ad hoc root-level API/stress/security harnesses quarantined under `legacy/root-test-harnesses/` (the 2026-06 cleanup moved ~42 more here)
- the large historical `test_result.md` moved to `legacy/test_result.md`
- historical launch-readiness/security notes under `ops-and-audit/` may reference quarantined preview-era scripts

Current authoritative tests live under `tests/`:

- `tests/test_spend_authorization.py` — consensus spend authorization
- `tests/test_rate_limit_identity.py` — rate-limit client identity
- `tests/test_launch_feature_gate.py` — launch-scope feature gating

Use them only as historical reference until they are either removed or rewritten around the canonical backend/node stack.

## Production Track

The production path for this repo is:

1. stable protocol and chain rules
2. stable backend and API behavior
3. canonical release-gate passes in local and staging environments
4. real deployment and secrets handling
5. observability, backup, and rollback procedures
6. accurate public documentation

The current pre-release operator gate lives at:

- `wepo-production-deployment/run-canonical-release-gate.sh`

See also:

- `wepo-production-deployment/CANONICAL_RELEASE_GATE.md`
- `wepo-production-deployment/CANONICAL_STAGING_DEPLOYMENT.md`
- `wepo-production-deployment/bootstrap-canonical-staging.sh`
- `wepo-production-deployment/verify-canonical-staging-host.sh`
- `wepo-production-deployment/LOCAL_PUBLIC_TEST_CHECKLIST.md`
- `wepo-production-deployment/PUBLIC_TEST_HANDOFF.md`
- `wepo-production-deployment/PUBLIC_RELEASE_CHECKLIST.md`
- `wepo-production-deployment/MULTI_WALLET_TEST_MATRIX.md`

## Related Repositories

- Platform repo: `https://github.com/armpit-symphony/WEPO`
- Wallet repo: `https://github.com/armpit-symphony/WEPO-wallet`

## Sparkpit Labs Positioning

WEPO and WEPO Wallet are being prepared for future Sparkpit Labs product integration. Public product pages and download surfaces will live under `sparkpitlabs.com`, but this repository remains the engineering source for the platform/network side.
