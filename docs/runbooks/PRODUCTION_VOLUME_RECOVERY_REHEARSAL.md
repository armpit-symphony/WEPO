# Production-Volume Recovery Rehearsal

Status: local engineering baseline proven; release-candidate qualification pending

## Purpose

Exercise the real WEPO consensus, ML-DSA signing, SQLite/WAL crash boundary,
startup replay, canonical backup tool, restore, and second replay at a defined
chain volume. The tool publishes machine-readable evidence only after every
state and integrity comparison passes.

This rehearsal never enables mainnet and is not a substitute for off-host,
independent-operator, release-hardware, or trusted-peer catch-up acceptance.

## Local engineering baseline

The baseline is derived from the fastest currently configured mainnet cadence:

```text
30 days * 24 hours * 60 minutes * 60 seconds / 360 seconds = 7,200 blocks
```

The chain must contain:

- 7,200 post-genesis blocks;
- at least one real FIPS 204 ML-DSA signed transfer in every block after the
  actor-funding block;
- canonical coinbase, transaction, UTXO, wallet-activity, issued-supply, block
  index, and main-chain state; and
- an empty mempool after recovery, because mempool contents are intentionally
  volatile.

If the frozen block cadence changes, this baseline must be recalculated and
rerun. It is a minimum history/recovery baseline, not a maximum-throughput or
full-block claim.

## Run

Use a new, empty work directory and a new evidence path. The tool refuses to
reuse the work directory or overwrite evidence.

```powershell
python wepo-blockchain\scripts\wepo_recovery_rehearsal.py `
  --work-directory C:\tmp\wepo-recovery-baseline `
  --output release-evidence\local\production-volume-recovery\evidence.json `
  --blocks 7200 `
  --actors 1 `
  --progress-every 100 `
  --timeout-seconds 3600
```

The writer uses the real fixed-difficulty test consensus profile and real
ML-DSA signatures. It accelerates block timestamps monotonically from the
deterministic test genesis; persisted blocks still pass normal consensus replay.

After the requested chain is committed, the tool:

1. submits and signs one more transfer;
2. pauses only after SQLite reports an active uncommitted block transaction;
3. forcibly terminates the writer process;
4. reopens the exact database and compares every recorded state measure;
5. creates and verifies a backup with `wepo_db_backup.py`;
6. restores into an empty directory; and
7. reopens and compares the restored state again.

## Fail-closed acceptance

The evidence is valid only when all of these are true:

- `format` is `wepo-recovery-rehearsal-v1` and `status` is `pass`;
- `release_qualification` is `false` for local runs;
- the forced-kill boundary is an active uncommitted SQLite transaction;
- committed-block recovery-point loss is zero;
- height, tip, supply, block rows, transaction rows, UTXO rows, and wallet
  activity match before crash, after source recovery, and after restore;
- `quick_check` passes and `foreign_key_check` is empty;
- chain, block-index, and main-chain hash counts equal height plus genesis;
- the backup filename, size, SHA-256, height, tip, page metadata, and integrity
  match its canonical manifest; and
- the evidence script and retained backup/manifest hashes reproduce.

Any timeout, child exit before the armed boundary, state mismatch, integrity
failure, missing file, or evidence-path collision is a failed rehearsal.

## Current local result

The 2026-07-31 workstation run passed with:

- 7,200 post-genesis blocks;
- 7,199 real signed transfers and 14,400 persisted transactions total;
- 21,599 UTXO rows and 14,483 wallet-activity rows;
- a 157,712,384-byte verified backup;
- zero committed-block recovery-point loss;
- 69.485 seconds for crash recovery/replay;
- 0.888 seconds for backup plus verification;
- 0.509 seconds for restore copy; and
- 71.348 seconds for restored replay.

These are observations from this PC, not production RPO/RTO promises.

## Remaining release qualification

Before readiness acceptance, rerun on the frozen node image, hardware class,
filesystem, and database configuration. Also retain evidence for:

- a transaction-volume target derived from public testnet telemetry with
  documented headroom;
- encrypted off-host transfer and independent verification;
- restore plus trusted-peer catch-up;
- sustained hostile traffic and disk-growth behavior during the run;
- an operator other than the author following the runbook; and
- approved recovery-point and recovery-time objectives.
