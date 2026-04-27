# WEPO Local Public-Test Handoff

This is the current operator and tester handoff for the managed local public-test stack.

## Operator Start Path

Start the full validated local stack with:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh start
```

Start from a clean genesis-ready lab state with:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh start-clean
```

Reset an already running stack back to clean genesis-ready state with:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh restart-clean
```

Useful companion commands:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh status
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh logs
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh stop
```

Default validated endpoints:

- frontend: `http://127.0.0.1:3100`
- backend: `http://127.0.0.1:18021`
- node: `http://127.0.0.1:18212`

## Validated Browser Flows

These flows were validated against the live local stack:

- create public-test account
- refresh and restore same session
- logout/login
- receive WEPO
- authenticated send with real txid
- Quantum Vault preview loads
- RWA / Exchange path loads
- RWA create-asset screen loads
- BTC DEX preview copy loads
- RWA DEX tab loads
- liquidity tab loads
- Community Mining active-copy spot-check passed
- Settings `Wallet Info` shows `WEPO Public Test`

## Safe Tester Scope

These are the main surfaces to give broader testers:

- wallet create/login/logout
- session restore after refresh
- receive WEPO
- send WEPO
- wallet balance/history refresh
- RWA / Exchange browser pass
- Quantum Vault preview/status
- Community Mining status
- Settings / Wallet Info

## Preview-Only Or Not Yet Finished

Do not describe these as finished product flows in the current broader public-test round:

- BTC custody
- BTC atomic-swap / DEX claims beyond preview validation
- interactive web staking workflow
- recovery phrase import/export
- password rotation in UI
- messaging as a finished secure production feature

Current messaging/staking screens should be treated as:

- `Quantum Messages`: experimental preview
- `Proof of Stake`: status / preview, not a finished web staking workflow

## Next Clean Test Round

The next planned validation round should start from:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-local-public-test-stack.sh restart-clean
```

Run it in this order:

- genesis block and clean boot
- PoW mining and wallet funding
- seamless PoS activation transition
- wallet create/login/send/receive
- masternode collateral and registration

## Tester Guidance

- Treat all balances and flows here as public-test data only.
- Use the managed launcher instead of ad hoc node/backend/frontend commands.
- If the app looks inconsistent after a rebuild, reload the page before triaging.
- If the launcher is up but a browser flow fails, record whether the issue is:
  - wallet/main flow
  - RWA/exchange preview flow
  - preview-only surface

## Current Boundary

This stack is suitable for broader local/public-test rounds around the validated wallet flow.

It is not yet a production release candidate. Remaining work beyond this handoff includes:

- pruning legacy/generated artifacts and duplicate wallet surfaces
- narrowing or hiding any still-unvalidated preview-only screens
- production deployment hardening outside the local test stack
