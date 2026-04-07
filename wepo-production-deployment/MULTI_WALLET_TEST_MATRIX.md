# Multi-Wallet Test Matrix

This matrix is the next step after the canonical staging host verifier passes.

Primary goal:

- verify multiple wallet clients behave correctly against the same canonical WEPO backend/node stack

Primary environment:

- staging backend/API
- staging node
- canonical fee settlement enabled

## Test Inputs

Prepare:

- at least 3 disposable test identities
- at least 2 distinct wallet client types
- one seeded funding wallet for cross-wallet send/receive
- one staging observer account for reading backend and node state during failures

Suggested client set:

- Wallet A: web wallet
- Wallet B: desktop wallet
- Wallet C: second desktop instance or second browser profile

## Entry Command

The platform side must already pass:

```bash
sudo /opt/wepo/wepo-production-deployment/verify-canonical-staging-host.sh
```

Record the resulting release-gate `summary.json` path with the wallet test notes.

## Core Matrix

### A. Create / Import / Unlock

- Create a fresh wallet in Wallet A
- Create a fresh wallet in Wallet B
- Unlock both after restart/reload
- If import is supported, import the same wallet into Wallet C and confirm deterministic address recovery

Pass criteria:

- same secret recovers the same address
- encrypted local vault survives restart
- no plaintext secrets are exposed in obvious storage paths

### B. Receive / Observe

- Send funds from the staging funding wallet to Wallet A
- Confirm Wallet A reflects the received balance
- Confirm backend and node state agree on the resulting balance

Pass criteria:

- receive flow is visible in wallet UI
- balance updates without manual database intervention
- backend/node do not disagree materially on the resulting state

### C. Cross-Wallet Send

- Send from Wallet A to Wallet B
- Send from Wallet B to Wallet A
- Send from Wallet A to Wallet C when Wallet C is the same recovered identity

Pass criteria:

- sends succeed with correct destination behavior
- duplicate-submit protection does not double-apply effects
- client-side retries do not create inconsistent balances

### D. Restart / Resume

- Restart Wallet A and Wallet B after successful sends
- Reconnect them to the staging backend
- Confirm balances and recent activity still reconcile

Pass criteria:

- session recovery works
- wallet vault unlock works after restart
- no stale bridge-era endpoints reappear after restart

### E. Concurrent Behavior

- Attempt overlapping user actions from Wallet A and Wallet B
- Exercise repeated submit behavior from one wallet while the other performs a valid send

Pass criteria:

- one user action cannot silently duplicate another
- backend returns clear error states
- clients do not get stuck in unrecoverable pending state

### F. Fee-Settlement Awareness

- Execute a flow that triggers backend-originated fee settlement if the wallet surfaces it indirectly
- Confirm the backend/operator side records the canonical settlement result

Pass criteria:

- wallet action succeeds without bridge-era assumptions
- operator can correlate the action with release-gate style backend/node evidence

## Failure Recording

For each failure, capture:

- wallet client type and version
- staging backend URL
- approximate timestamp in UTC
- user action being performed
- wallet-visible error
- backend/node evidence if available
- whether the failure is reproducible

## Exit Criteria

Call the matrix complete only when:

- all core scenarios have been exercised on at least web and desktop
- all critical failures are fixed or explicitly scoped out
- any unsupported surface is labeled unsupported in public-facing copy

If mobile wallets are not included in this round, record that explicitly instead of implying support.
