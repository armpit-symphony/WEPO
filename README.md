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

This repository is not production ready yet.

The current local public-test status is stronger than the production status:

- the accelerated wallet lab is validated on `127.0.0.1:18212` and `127.0.0.1:18021`
- the built web wallet flow is validated on `127.0.0.1:3100`
- create, refresh/session-restore, login/logout, receive, and authenticated send all passed on the live local stack

Known gaps include:

- backend, chain, and deployment code need production hardening
- deployment assets still include demo/test-oriented paths
- docs and product claims have been ahead of actual implementation
- repo cleanup is still required for generated artifacts and backup files

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
5. Clean generated artifacts, release bundles, and backup files from versioned source.

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
- older ad hoc root-level API/stress harnesses now quarantined under `legacy/root-test-harnesses/`
- historical launch-readiness/security notes under `ops-and-audit/` may reference quarantined preview-era scripts

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
