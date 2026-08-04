# Deploy and Rollback Runbook

## Boundary

Deployment and rollback are privileged production changes. Require an approved
change record, named operator and observer, immutable release hash, maintenance
window, rollback decision time, and retained evidence. This runbook never
authorizes mainnet genesis or a consensus downgrade.

## Pre-deploy

1. Confirm the target commit, signed manifest, dependency locks, test evidence,
   scope manifest, and parameter manifest all identify the same candidate.
2. Confirm three seed failure domains, Redis/MongoDB health, TLS expiry,
   monitoring, disk headroom, and encrypted off-host backup status.
3. Create and verify an online chain backup with `CHAIN_BACKUP_RESTORE.md`.
4. Record node height/tip/supply, peer list, mempool counts, database quick check,
   service unit hashes, environment-file hashes, and current release symlink.
5. Fence validator signing if the change touches signer code, consensus, node
   state, or the node-to-signer command.

## Deploy

1. Copy the candidate to a new root-owned versioned directory. Never overwrite
   the running release directory.
2. Verify `SHA256SUMS` and the release-manifest signature before changing the
   `current` symlink.
3. Stop only the affected service through the approved change.
4. Atomically select the new release, start the service, and run
   `verify-production-host.sh`.
5. Compare height, tip, supply, peer connectivity, and database integrity with
   trusted independent nodes. Re-enable a fenced signer only after this check.
6. Observe through the declared rollback window and attach logs/metrics to the
   change record.

## Rollback rules

Rollback is permitted only when the previous binary is database-compatible and
consensus-compatible with every block the node may have accepted. Never run an
older consensus binary merely because a deployment is unhealthy.

If no new canonical block or schema mutation occurred:

1. fence signer and public API traffic;
2. stop the affected service;
3. restore the prior immutable release selection;
4. start, verify, and compare with trusted peers;
5. retain both release hashes and the reason.

If canonical state or schema may have changed, stop. Follow the fork/stall and
backup/restore runbooks. Require protocol and data-owner review before selecting
a binary or restoring a database. Never edit block, UTXO, stake, supply, or
shielded tables manually.

## Abort conditions

Abort or roll forward under review if any of these occur:

- manifest/signature mismatch;
- unexpected database migration;
- node reports the wrong network or genesis;
- supply/tip differs from trusted peers without an explained fork;
- Redis fail-closed behavior, TLS, or loopback binding fails;
- signer key/state ownership or anti-equivocation integrity changes;
- unexplained reorg, rejected-block spike, or peer isolation.

## Evidence

Retain the approval, timestamps, operator/observer, before/after release hashes,
unit/env hashes, backup manifest, node state, verifier output, alerts, rollback
decision, and sanitized logs. Never retain secrets, private keys, mnemonics,
cookies, complete environment files, or customer IP addresses.
