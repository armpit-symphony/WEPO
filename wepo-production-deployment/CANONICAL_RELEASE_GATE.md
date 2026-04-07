# Canonical Release Gate

This is the current authoritative pre-release gate for WEPO platform changes.

Use it before calling any environment staging-ready or public-ready.

Primary command:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-canonical-release-gate.sh
```

## What It Verifies

By default the gate runs:

- happy-path canonical fee settlement smoke
- idempotent replay verification
- concurrent duplicate-request verification
- short repeated soak

Optional:

- settlement-wallet depletion verification

Artifacts are written under `RELEASE_GATE_LOG_DIR`:

- `summary.log`
- `summary.json`
- one log per case
- a soak subdirectory when the soak case runs

## Modes

### `GATE_MODE=local-managed`

Use this for local operator verification. The gate delegates to the existing local launchers:

- `/home/sparky/WEPO/wepo-blockchain/scripts/run_canonical_fee_smoke.sh`
- `/home/sparky/WEPO/wepo-blockchain/scripts/run_canonical_fee_soak.sh`

Example:

```bash
GATE_MODE=local-managed \
SOAK_ITERATIONS=3 \
SOAK_PAUSE_SECONDS=1 \
/home/sparky/WEPO/wepo-production-deployment/run-canonical-release-gate.sh
```

### `GATE_MODE=assume-running`

Use this for staging or pre-production environments where the canonical backend and node are already running.

This mode does not start or stop services. Run it on a host that can reach:

- the target backend URL
- the target node URL
- the target Mongo database used by the backend

You can provide Mongo access either by:

- pointing `BACKEND_ENV_PATH` at the backend `.env` for that environment
- or overriding `MONGO_URL` and `DB_NAME`

Example:

```bash
GATE_MODE=assume-running \
BACKEND_BASE_URL=http://127.0.0.1:8011 \
NODE_BASE_URL=http://127.0.0.1:8122 \
BACKEND_ENV_PATH=/opt/wepo/backend/.env \
SOAK_ITERATIONS=5 \
/home/sparky/WEPO/wepo-production-deployment/run-canonical-release-gate.sh
```

## Recommended Minimum Pass Matrix

Before calling an environment release-candidate or public-ready, require:

- `happy_path`: pass
- `idempotent_replay`: pass
- `concurrent_idempotency`: pass
- `soak`: pass

Use `EXPECT_SETTLEMENT_DEPLETION=true` as an explicit failure-mode exercise, not as a default staging gate.

## Current Deployment Reality

The older deployment scripts in this directory are still bridge-era:

- `/home/sparky/WEPO/wepo-production-deployment/deploy-server.sh`
- `/home/sparky/WEPO/wepo-production-deployment/upload-and-deploy.sh`

They remain historical reference only until they are rewritten around the canonical backend/node stack.
