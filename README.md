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
- `/home/sparky/WEPO/wepo-blockchain/scripts/wepo_accelerated_simulation.py`

For repeated local backend/node verification under load, use:

```bash
/home/sparky/WEPO/wepo-blockchain/scripts/run_canonical_fee_soak.sh
```

Useful env overrides:

- `SOAK_ITERATIONS`
- `SOAK_PAUSE_SECONDS`
- `MAX_FAILURES`
- `SOAK_LOG_DIR`

The active backend/frontend runtime files no longer carry a built-in preview-host
default. Set explicit allowlists through env when needed:

- `WEPO_ALLOWED_ORIGINS` for backend/bridge CORS origins
- `WEPO_FRONTEND_CONNECT_SRC` for frontend CSP `connect-src`

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
3. real deployment and secrets handling
4. observability, backup, and rollback procedures
5. accurate public documentation

## Related Repositories

- Platform repo: `https://github.com/armpit-symphony/WEPO`
- Wallet repo: `https://github.com/armpit-symphony/WEPO-wallet`

## Sparkpit Labs Positioning

WEPO and WEPO Wallet are being prepared for future Sparkpit Labs product integration. Public product pages and download surfaces will live under `sparkpitlabs.com`, but this repository remains the engineering source for the platform/network side.
