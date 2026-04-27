# WEPO Mainnet Genesis Release Checklist

Date: 2026-04-18
Status: Draft launch gate
Target: July 4, 2026 for the real blockchain, only if every blocker below is green
Purpose: Turn the accelerated wallet-lab progress into a concrete launch gate for permanent mainnet genesis.

## Rule

Do not announce July 4, 2026 publicly unless every `BLOCKER` item below is complete or explicitly waived in writing.

The accelerated `test` wallet lab is valuable evidence, but it is not enough by itself to set a public genesis date.

## Release Decision Order

1. Merge and review the accelerated wallet-lab fixes.
2. Freeze the permanent mainnet scope and parameters.
3. Finish the remaining launch-scope truthfulness and cleanup work.
4. Run one production-like genesis rehearsal on permanent config.
5. Fix every rehearsal failure and re-test.
6. Hold a final go/no-go review.
7. Only then publish the official genesis date.

## Must Pass This Week

### BLOCKER 1 - Review And Merge The Current Branches

- Review and merge `WEPO` branch `wallet-lab-fixes-20260409`.
- Review and merge `WEPO-wallet` branch `wallet-client-lab-fixes-20260409`.
- Confirm the final merged scope is intentional.
- Confirm no accelerated-lab finding remains open without an owner and disposition.

Notes:
- The `WEPO` branch must be reviewed as a platform branch, not as a one-commit skim.
- The wallet-lab work already proved useful chain-backed flows, so the immediate goal is to get that work merged cleanly.

### BLOCKER 2 - Re-Run The Accelerated Wallet Lab In The Intended Test Order

Use the accelerated lab as the main bug-finding surface, not the old bridge-first path.

Launch surface:
- `/home/sparky/WEPO/wepo-blockchain/scripts/run_test_mode_wallet_lab.sh`
- node `127.0.0.1:18212`
- backend `127.0.0.1:18021`

Required test order:
1. wallet creation, import, and unlock on web and desktop
2. send/receive between multiple wallets
3. masternode collateral and registration behavior under reduced test collateral
4. PoS stake flows after activation
5. privacy / ghost transfer paths
6. RWA flows only after wallet and chain behavior are stable

Exit criteria:
- Each flow above is re-run on the current merged code, not just assumed from April 9 notes.
- Every failure gets written down with owner, fix, and re-test evidence.
- No `test` profile shortcut leaks into default `mainnet` behavior.

### BLOCKER 3 - Canonical Smoke And Soak Coverage Around Backend->Node Settlement

- Re-run repeated soak coverage around the canonical fee-settlement path.
- Cover:
  - duplicate trade requests
  - settlement-wallet depletion
  - mempool/block timing behavior
  - Mongo consistency under repeated trade load
- Preserve the rule that blockchain fee settlement is canonical and app-fee settlement is explicit and traceable.

Exit criteria:
- No double-settlement, partial-settlement, or silent-ledger-drift bug remains.
- Repeated load does not corrupt Mongo state or produce inconsistent chain/accounting results.

## Must Pass Before Genesis Rehearsal

### BLOCKER 4 - Mainnet Scope Freeze

- Write and approve the exact v1 launch scope.
- Mark each feature as one of:
  - launch
  - disabled at launch
  - post-launch

Scope list:
- permanent chain/node
- backend/API
- web wallet
- desktop wallet
- masternodes
- staking
- privacy sends
- RWA asset and vault flows
- RWA trading
- governance
- mobile wallets

Rule:
- Any feature still depending on lab-only accounting, compatibility-cache semantics, fake/demo behavior, or incomplete signing/sync logic must either be finished or removed from launch scope.

### BLOCKER 5 - Permanent Mainnet Parameter Freeze

- Finalize permanent genesis block data.
- Finalize chain ID and network magic.
- Finalize address prefixes and network discrimination rules.
- Finalize seed node list and seed ownership.
- Finalize bootstrap distribution plan.
- Finalize PoW and PoS activation heights.
- Finalize masternode collateral rules.
- Finalize staking minimums and reward schedule.
- Finalize fee policy and canonical fee-settlement policy.
- Finalize checkpoints only if they are intentionally part of launch policy.
- Record all final values in one canonical document.

Rule:
- No accelerated `test` profile timings, collateral shortcuts, activation compression, or lab-only defaults may leak into permanent mainnet values.

### BLOCKER 6 - Launch-Scope Truthfulness

- Remove or disable old bridge-era endpoint assumptions.
- Remove or disable fake/demo wallet flows.
- Ensure dashboards and status endpoints show live network values, not stale placeholders.
- Ensure wallet clients only expose features actually supported by the shipping backend and chain.
- Ensure unsupported ghost-transfer or privacy-adjacent routes are not shown as live if they are not truly launch-ready.

Known items that must be resolved or explicitly excluded:
- RWA trade WEPO leg is still lab-mode accounting layered on top of live node balance, not true on-chain user settlement.
- Legacy auth-oriented wallet routes still exist as compatibility paths with cache semantics.
- Bitcoin integration in the active wallet context is still simplified and not yet a production-grade signing/sync path.
- Some legacy helper files and stale docs still reflect removed or non-production assumptions.

### BLOCKER 7 - Production Infrastructure Readiness

- Stand up production node hosts.
- Stand up production backend hosts.
- Stand up production Mongo and backup plan.
- Harden RPC exposure and firewall rules.
- Configure TLS, domains, and reverse proxies.
- Configure secrets management.
- Configure monitoring, alerting, and log retention.
- Validate backup and restore for chain data and backend data.
- Create restart, rollback, and incident runbooks.
- Define launch-day owner and on-call coverage.

## Must Pass In Genesis Rehearsal

### BLOCKER 8 - Full Production-Like Genesis Rehearsal

Run one full rehearsal from zero state on the permanent mainnet configuration.

Required checks:
- bootstrap node from empty data dir
- secondary node sync from zero
- backend attaches cleanly to the permanent config
- wallet create/import/unlock works
- wallet send/receive works
- masternode registration works
- staking activates at the configured height and works
- privacy send works
- canonical backend fee settlement works
- restart and crash recovery work
- fresh wallet can recover from seed after restart

Exit criteria:
- No blocker-severity failure remains unresolved.
- All failures are logged with owner, fix, and re-test evidence.
- The rehearsal result is treated as launch evidence, not a one-off demo.

## Must Pass Before Public Date Announcement

### BLOCKER 9 - Security And Operational Signoff

- Run a final security review on the merged launch scope.
- Review key management and wallet storage assumptions.
- Review node hardening and backend exposure.
- Review rate limiting, abuse paths, and denial-of-service posture.
- Review signing and release artifact integrity.
- Review dependency and secret handling.
- Record explicit signoff from engineering, ops, and security owners.

### BLOCKER 10 - Launch Artifacts And Public Readiness

- Build and verify release binaries/packages.
- Publish wallet installation instructions.
- Publish mainnet connection and verification instructions.
- Publish seed-node and bootstrap guidance.
- Publish operator instructions for masternodes and validators.
- Publish support path and status page.
- Publish exact genesis date, time, and UTC reference only after every blocker is green.

## Go/No-Go Meeting

Participants:
- protocol/chain owner
- backend owner
- wallet owner
- ops/deployment owner
- security reviewer

Agenda:
- review blocker status
- review accelerated-lab evidence
- review genesis rehearsal evidence
- review outstanding risks
- assign launch-day owner list
- approve or reject public genesis date

## Minimum Evidence Required Before Setting July 4 Publicly

- merged wallet-lab fixes in both repos
- accelerated wallet-lab flows re-run cleanly on merged code
- canonical fee-settlement soak coverage passed
- permanent parameter document approved
- production infrastructure checklist green
- full genesis rehearsal passed
- final user-facing wallet pass completed
- final security and ops signoff recorded

## Current Read On 2026-04-18

Already in strong shape:
- isolated accelerated `test` wallet lab exists and is useful
- chain-backed send/receive, staking, masternodes, privacy sends, and RWA vault flows were re-verified there
- the accelerated lab has already exposed and driven fixes in consensus, wallet balance, masternode, unstake, and fee-settlement behavior

Not yet sufficient to publish July 4 publicly:
- merged review state is incomplete
- permanent mainnet parameter freeze is not yet recorded in one canonical document
- launch-scope truthfulness is not fully settled
- production-like genesis rehearsal on permanent config has not yet been logged
- final security and operational signoff have not yet been recorded

## Immediate Next Actions

1. Open and review the two pushed GitHub PRs.
2. Re-run the accelerated wallet lab in the recorded test order and log every failure.
3. Re-run fee-settlement soak coverage and record results.
4. Freeze permanent mainnet parameters in one canonical document.
5. Lock the v1 launch scope, especially around RWA trade settlement and any compatibility routes.
6. Build and run the full production-like genesis rehearsal.
7. Fix every rehearsal finding before deciding whether July 4 is real or needs to slip.
