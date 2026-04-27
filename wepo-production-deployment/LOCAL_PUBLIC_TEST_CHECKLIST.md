# Local Public-Test Checklist

Use this checklist for the local pre-public-test stack that was validated on:

- frontend: `http://127.0.0.1:3100`
- backend: `http://127.0.0.1:18021`
- node: `http://127.0.0.1:18212`

This is the practical handoff between engineering validation and a broader outside tester round.

See also:

- `/home/sparky/WEPO/wepo-production-deployment/PUBLIC_TEST_HANDOFF.md`

## 1. Start The Local Public-Test Stack

Run:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh start
```

For a fresh genesis-to-PoS rehearsal from empty test-lab state, run:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh restart-clean
```

Confirm:

- node responds on `127.0.0.1:18212`
- backend responds on `127.0.0.1:18021`
- frontend responds on `127.0.0.1:3100`
- node reports `network_profile=test`
- backend is pointed at the test node
- tmux sessions `wepo-public-test-lab` and `wepo-public-test-frontend` are running

Useful operator commands:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh status
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh logs
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh stop
```

Clean-reset operator actions:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh start-clean
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh restart-clean
```

Optional:

- set `AUTO_BUILD_FRONTEND=false` if you intentionally want to reuse the existing built bundle without rebuilding before startup

## 2. Confirm Frontend Runtime

Confirm:

- `http://127.0.0.1:3100` loads
- frontend CSP allows `18021` and `18212`
- backend CORS allows `127.0.0.1:3100`

## 3. Required Main Wallet Flow

All of the following should pass on the local public-test stack:

1. Create a public-test account
2. Confirm backend auth token is issued
3. Refresh the page
4. Confirm the same wallet session restores
5. Confirm funded balance reloads on the dashboard
6. Confirm dashboard shows `Network: PoW active`
7. Open receive and confirm the displayed address matches the active wallet
8. Logout
9. Login with the same account
10. Send WEPO through the frontend
11. Confirm the success banner includes a real txid
12. Confirm recipient balance changes on-chain
13. Logout and confirm the UI returns to the login screen

## 4. Product-Claim Audit For Public Testing

Before outside testers touch the build, confirm:

- recovery phrase copy does not imply live self-custody
- password-change flow does not claim to work when it is disabled
- BTC UI is clearly marked preview-only
- exchange / RWA copy does not claim unsupported custody behavior
- no product-facing page still carries Emergent branding or telemetry residue

## 5. Runtime / Operator Checks

Confirm:

- `frontend/.env` points at the intended backend
- `backend/.env` or runtime env points at the intended node
- `WEPO_ALLOWED_ORIGINS` includes the served frontend origin
- `WEPO_FRONTEND_CONNECT_SRC` is set if overriding CSP defaults
- live node and backend processes stay up across reload/login/send testing

## 6. Non-Primary Surface Pass

After the main wallet flow is green, do a targeted browser pass on:

- privacy helper flow
- RWA create / trade / vault flow
- BTC preview-only screens to confirm they do not overclaim live custody

## 7. Exit Criteria For Broader Testing

Do not call the build ready for broader outside testing unless all of the following are true:

- main wallet browser flow is green end-to-end
- accelerated wallet lab can be started repeatably
- frontend build succeeds
- runtime env examples are current
- public-test docs exist and match the actual stack
- known unsupported features are labeled honestly
