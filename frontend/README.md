# WEPO Web Wallet Frontend

This is the canonical WEPO self-custodial web wallet and the frontend embedded
in the desktop package. Mainnet remains deliberately unavailable while release
readiness is incomplete.

The wallet flow has been validated locally against the accelerated test lab:

- create account
- refresh and restore the same session
- login/logout
- receive WEPO
- authenticated send through the live backend
- local ML-DSA key generation and transaction signing
- recovery-phrase restore and atomic local-vault password rotation

## Current Public-Test Scope

Supported for the current public-test build:

- backend account create/login/logout
- live WEPO balance and transaction reads
- authenticated WEPO send
- receive address display
- PoS / masternode / privacy / RWA surfaces backed by the accelerated test lab

Ghost privacy, RWA trading, browser mining, and production BTC custody are
release-gated or preview-only and must not be described as live mainnet
features.

## Runtime Modes

### Development UI

Use the loopback-only Vite development server when iterating on the React app:

```bash
npm ci
npm start
```

That starts the development server.

### Built Secure Frontend

For the validated local public-test flow, the preferred operator path is:

```bash
./wepo-production-deployment/run-local-public-test-stack.sh start
```

For the next clean-chain validation round from genesis, use:

```bash
./wepo-production-deployment/run-local-public-test-stack.sh restart-clean
```

That launcher:

- starts the accelerated wallet lab in tmux
- builds the frontend bundle by default
- serves the built app with `secure-server.js`
- exposes `start | start-clean | restart-clean | stop | status | logs`

If you only want the frontend locally while another backend/node is already running, the lower-level path is still:

```bash
npm ci
npm run build
PORT=3100 node secure-server.js
```

## Local Public-Test Stack

The currently validated local stack is:

- frontend: `http://127.0.0.1:3100`
- backend: `http://127.0.0.1:18021`
- node: `http://127.0.0.1:18212`

The frontend reads its backend target from `.env` / `REACT_APP_BACKEND_URL`.

Example:

```env
REACT_APP_BACKEND_URL=http://127.0.0.1:18021
```

## Recommended Local Flow

1. Start the local public-test stack:

```bash
./wepo-production-deployment/run-local-public-test-stack.sh start
```

Use `restart-clean` instead when you need the lab reset to genesis before the next end-to-end round.

2. Open `http://127.0.0.1:3100`

3. Run the main public-test path:

- create account
- refresh
- logout/login
- fund/send/receive WEPO
- confirm send success banner and live balance updates

4. When finished:

```bash
./wepo-production-deployment/run-local-public-test-stack.sh stop
```

## Security Notes

- The frontend CSP defaults now allow the validated local wallet-lab backend and node ports.
- The backend must allow the frontend origin through `WEPO_ALLOWED_ORIGINS`.
- Account APIs use a backend-issued session, but each spend is authorized by a
  client-side ML-DSA signature and enforced by consensus; the server never
  receives the recovery phrase or spend secret.

## Scripts

- `npm start`: loopback-only Vite development server
- `npm run build`: optimized Vite build in `build/`
- `npm test`: one-shot Vitest suite
- `npm run test:watch`: interactive Vitest watch mode

## Related Docs

- `../README.md`
- `../wepo-production-deployment/PUBLIC_RELEASE_CHECKLIST.md`
- `../wepo-production-deployment/LOCAL_PUBLIC_TEST_CHECKLIST.md`
- `../wepo-production-deployment/PUBLIC_TEST_HANDOFF.md`
