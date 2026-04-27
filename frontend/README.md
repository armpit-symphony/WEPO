# WEPO Web Wallet Frontend

This frontend is the current web wallet/client surface used for local public-test validation.

It is still transitional code that lives in the platform repo, but the main wallet flow has been validated locally against the accelerated test lab:

- create account
- refresh and restore the same session
- login/logout
- receive WEPO
- authenticated send through the live backend

## Current Public-Test Scope

Supported for the current public-test build:

- backend account create/login/logout
- live WEPO balance and transaction reads
- authenticated WEPO send
- receive address display
- PoS / masternode / privacy / RWA surfaces backed by the accelerated test lab

Explicitly not live self-custody in this build:

- recovery phrase import/export
- password-change flow
- BTC custody

BTC UI is preview-only and should not be described as live custody.

## Runtime Modes

### Development UI

Use CRACO dev mode when iterating on the React app:

```bash
npm install
npm start
```

That starts the development server.

### Built Secure Frontend

For the validated local public-test flow, the preferred operator path is:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh start
```

For the next clean-chain validation round from genesis, use:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh restart-clean
```

That launcher:

- starts the accelerated wallet lab in tmux
- builds the frontend bundle by default
- serves the built app with `secure-server.js`
- exposes `start | start-clean | restart-clean | stop | status | logs`

If you only want the frontend locally while another backend/node is already running, the lower-level path is still:

```bash
npm install
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
WDS_SOCKET_PORT=443
```

## Recommended Local Flow

1. Start the local public-test stack:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh start
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
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh stop
```

## Security Notes

- The frontend CSP defaults now allow the validated local wallet-lab backend and node ports.
- The backend must allow the frontend origin through `WEPO_ALLOWED_ORIGINS`.
- The frontend assumes a backend-issued auth session token for send authorization.

## Scripts

- `npm start`: CRACO development server
- `npm run build`: production build for the secure server path
- `npm test`: CRACO test runner

## Related Docs

- `/home/sparky/WEPO/README.md`
- `/home/sparky/WEPO/wepo-production-deployment/PUBLIC_RELEASE_CHECKLIST.md`
- `/home/sparky/WEPO/wepo-production-deployment/LOCAL_PUBLIC_TEST_CHECKLIST.md`
- `/home/sparky/WEPO/wepo-production-deployment/PUBLIC_TEST_HANDOFF.md`
