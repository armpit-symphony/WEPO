# Canonical Staging Deployment

This is the current staging shape for WEPO platform validation.

It is intentionally separate from the older bridge-era deploy scripts in this directory.

## Target Topology

Use a single staging host or a tightly controlled private network with:

- WEPO node bound locally on `127.0.0.1:8122`
- WEPO backend bound locally on `127.0.0.1:8011`
- nginx terminating TLS and proxying public traffic to the backend
- Mongo reachable privately by the backend
- Redis optional for rate limiting, with in-memory fallback if Redis is absent
- node mining RPC enabled, but background mining disabled for deterministic gate runs

Recommended public DNS split:

- backend/API: `staging-api.sparkpitlabs.com`
- web product/docs: `staging.sparkpitlabs.com`

## Canonical Assets

Use these files as the starting point:

- `/home/sparky/WEPO/wepo-production-deployment/backend.env.example`
- `/home/sparky/WEPO/wepo-production-deployment/bootstrap-canonical-staging.sh`
- `/home/sparky/WEPO/wepo-production-deployment/verify-canonical-staging-host.sh`
- `/home/sparky/WEPO/wepo-production-deployment/wepo-backend.service.example`
- `/home/sparky/WEPO/wepo-production-deployment/wepo-node.service.example`
- `/home/sparky/WEPO/wepo-production-deployment/nginx-wepo-api.conf.example`
- `/home/sparky/WEPO/wepo-production-deployment/run-canonical-release-gate.sh`

If you want the templates installed into `/etc`, `/var`, and nginx in one pass, use:

```bash
sudo /home/sparky/WEPO/wepo-production-deployment/bootstrap-canonical-staging.sh
```

## Backend Environment

Copy the example env file and edit it:

```bash
sudo mkdir -p /etc/wepo
sudo cp /home/sparky/WEPO/wepo-production-deployment/backend.env.example /etc/wepo/backend.env
sudo chmod 600 /etc/wepo/backend.env
```

Minimum values to set correctly:

- `MONGO_URL`
- `DB_NAME`
- `WEPO_NODE_API_URL`
- `WEPO_CANONICAL_APPLICATION_FEES_ENABLED=true`
- `WEPO_APP_FEE_SETTLEMENT_ADDRESS`
- `WEPO_ALLOWED_ORIGINS`

The settlement address must be a funded staging address if canonical app-fee settlement is enabled.

## Service Layout

Copy the systemd examples and edit the placeholder paths or addresses:

```bash
sudo cp /home/sparky/WEPO/wepo-production-deployment/wepo-node.service.example /etc/systemd/system/wepo-node.service
sudo cp /home/sparky/WEPO/wepo-production-deployment/wepo-backend.service.example /etc/systemd/system/wepo-backend.service
```

Then adjust:

- Python virtualenv path under `/opt/wepo/.venv`
- repo checkout path under `/opt/wepo`
- node miner address placeholder in `wepo-node.service`
- any user/group names if the service user is not `wepo`

The staging node template intentionally uses:

- `--difficulty-override 1`
- `--no-background-mining`

That is a deterministic staging/test profile so the canonical release gate can confirm transactions quickly and repeatably. It is not the intended long-term public production mining profile.

The bootstrap script can pre-install these files for you, but it intentionally does not start the services.

## Nginx Layout

Install the example config and edit the server names:

```bash
sudo cp /home/sparky/WEPO/wepo-production-deployment/nginx-wepo-api.conf.example /etc/nginx/sites-available/wepo-api
sudo ln -sf /etc/nginx/sites-available/wepo-api /etc/nginx/sites-enabled/wepo-api
sudo nginx -t
sudo systemctl reload nginx
```

The example assumes:

- TLS termination at nginx
- proxy to `127.0.0.1:8011`
- no wildcard CORS in nginx
- CORS allowlist handled in the backend through `WEPO_ALLOWED_ORIGINS`

## Deployment Order

1. Provision `/opt/wepo` and a Python virtualenv.
2. Install backend dependencies from `backend/requirements.txt`.
3. Copy `/etc/wepo/backend.env`.
4. Install `wepo-node.service` and `wepo-backend.service`.
5. Start the node, then start the backend.
6. Install nginx config and TLS.
7. Run the canonical release gate on the staging host.

## Canonical Staging Gate

Run this on the staging host after the services are up:

```bash
GATE_MODE=assume-running \
BACKEND_BASE_URL=http://127.0.0.1:8011 \
NODE_BASE_URL=http://127.0.0.1:8122 \
BACKEND_ENV_PATH=/etc/wepo/backend.env \
SOAK_ITERATIONS=5 \
/home/sparky/WEPO/wepo-production-deployment/run-canonical-release-gate.sh
```

For a single operator command that checks systemd, nginx, env values, local health, and then runs the gate, use:

```bash
sudo /home/sparky/WEPO/wepo-production-deployment/verify-canonical-staging-host.sh
```

Once that passes, move immediately to:

- `/home/sparky/WEPO/wepo-production-deployment/PUBLIC_RELEASE_CHECKLIST.md`
- `/home/sparky/WEPO/wepo-production-deployment/MULTI_WALLET_TEST_MATRIX.md`

Required pass matrix before calling staging valid:

- `happy_path`
- `idempotent_replay`
- `concurrent_idempotency`
- `soak`

Use `EXPECT_SETTLEMENT_DEPLETION=true` only as an explicit failure-mode exercise.

## Not Yet Covered

This staging shape still needs real production decisions for:

- secrets distribution and rotation
- backups and restore drills
- metrics and alerting
- multi-node topology
- wallet download and public support surfaces on `sparkpitlabs.com`

Do not treat staging as public-ready until those are addressed.
