# Public Release Checklist

Use this checklist before calling WEPO or WEPO Wallet public-ready.

This is the handoff point between platform hardening and multi-wallet validation.

For the validated local pre-public-test stack and browser wallet flow, see:

- `/home/sparky/WEPO/wepo-production-deployment/LOCAL_PUBLIC_TEST_CHECKLIST.md`
- `/home/sparky/WEPO/wepo-production-deployment/PUBLIC_TEST_HANDOFF.md`

## 1. Canonical Platform Gate

Require all of the following on staging:

- `wepo-node` active
- `wepo-backend` active
- nginx config valid
- `/etc/wepo/backend.env` populated with non-placeholder values
- canonical release gate passing

Preferred command:

```bash
sudo /opt/wepo/wepo-production-deployment/verify-canonical-staging-host.sh
```

Do not continue to wallet testing until this passes.

## 2. Required Platform Passes

The canonical release gate must show:

- `happy_path`: pass
- `idempotent_replay`: pass
- `concurrent_idempotency`: pass
- `soak`: pass

Optional but recommended:

- `EXPECT_SETTLEMENT_DEPLETION=true` failure-mode exercise documented separately

## 3. Wallet-Test Entry Criteria

Before multi-wallet testing starts, confirm:

- staging backend URL is fixed and known
- staging API domain/TLS is working
- canonical settlement wallet is funded
- backend CORS allowlist includes the intended wallet origins
- no wallet flow depends on `wepo-fast-test-bridge.py`
- the wallet repo is pinned to the canonical backend path for this round of testing

## 4. Multi-Wallet Scope For This Round

Minimum wallet surfaces:

- web wallet from `WEPO-wallet`
- desktop wallet from `WEPO-wallet`

If mobile wallets are not actively maintained for this round, do not block release claims on them. Mark them unsupported or out of scope instead.

## 5. Required Wallet Scenarios

Run the matrix in:

- `/home/sparky/WEPO/wepo-production-deployment/MULTI_WALLET_TEST_MATRIX.md`

Do not collapse this to “wallet opens and login works.” The goal is cross-client behavior against the same canonical backend.

## 6. Release Claims Audit

Before anything goes public on `sparkpitlabs.com`, confirm:

- README status language is still accurate
- download pages do not promise unsupported platforms
- security claims match the actual key-storage model
- site copy does not describe bridge-era or preview-era infrastructure as live
- support/contact and recovery guidance exist

## 7. Public-Go Boundary

Public release should require all of:

- canonical staging host verifier passes
- multi-wallet matrix completed with recorded outcomes
- unresolved failures triaged as either fixed or explicitly out of scope
- Sparkpit Labs public pages updated with current scope
- rollback and support owner identified

If any of the above is missing, call the release candidate internal-only, not public-ready.
