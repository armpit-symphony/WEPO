# Chain Database Backup and Restore Runbook

Status: release-candidate procedure; production rehearsal required

## Purpose

Create, verify, retain, and restore a consistent WEPO SQLite chain database.
This procedure covers chain data only. Wallet keys, validator keys, Redis,
backend databases, configuration, and secrets require separate protected
backup procedures.

Never copy a live `blockchain.db` file directly. WEPO uses SQLite WAL mode, so
a raw copy can omit committed data held in the WAL. Use the online backup tool.

## Preconditions

- Run commands from the repository root using the same Python environment as
  the node.
- Confirm the source and destination paths are on storage with sufficient free
  space.
- Restrict backup and manifest access to authorized operators.
- Record the node, network profile, operator, ticket/change identifier, and UTC
  time in the operational evidence log.
- For production restore, obtain the required change approval and stop all
  processes that can open the target database.

## Create an online backup

The node may remain running while this command creates a consistent SQLite
snapshot:

```powershell
python wepo-blockchain\scripts\wepo_db_backup.py create `
  --database C:\path\to\data\blockchain.db `
  --output-directory C:\path\to\staging\backups
```

The command prints the paths of:

- a timestamped `.sqlite3` backup; and
- its adjacent `.sqlite3.json` manifest.

The manifest binds the filename, byte size, SHA-256 digest, UTC creation time,
SQLite integrity result, database page metadata, chain height, and tip hash.
Keep the backup and its manifest together.

## Verify before transfer

```powershell
python wepo-blockchain\scripts\wepo_db_backup.py verify `
  --backup C:\path\to\staging\backups\wepo-chain-TIMESTAMP.sqlite3
```

A nonzero exit or any integrity, size, hash, filename, or chain-tip mismatch is
a failed backup. Do not retain it as a recovery point.

## Retain off host

After local verification:

1. Transfer both files to access-controlled, encrypted off-host storage.
2. Verify the transferred copy with the same command.
3. Record its object/version identifier, manifest SHA-256, height, tip hash,
   retention class, and verification time.
4. Keep at least one recovery point outside the node's provider failure domain.
5. Apply an approved retention policy and test that expired-object cleanup
   cannot remove the last known-good recovery point.

Do not place wallet seeds, private keys, signer credentials, API secrets, or
database passwords in the manifest or evidence log.

## Restore rehearsal

Perform rehearsals on an isolated host or data directory. Never point a
rehearsal at a live node database.

1. Verify the backup and manifest.
2. Confirm the target database path does not exist.
3. Restore into the empty target path:

```powershell
python wepo-blockchain\scripts\wepo_db_backup.py restore `
  --backup C:\path\to\backups\wepo-chain-TIMESTAMP.sqlite3 `
  --target C:\path\to\empty-data\blockchain.db
```

4. Start a node using the isolated data directory and the matching network
   profile.
5. Confirm startup integrity checks pass.
6. Confirm the restored height and tip hash match the manifest.
7. Allow the node to reconnect and catch up; record the final height, tip,
   duration, and any reorg.
8. Retain logs and the signed/operator-approved rehearsal record.

The restore command verifies the backup before copying it and refuses to
overwrite an existing target. This is intentional. Operators must preserve and
move aside an existing database, its `-wal`, and its `-shm` files through the
approved incident/change process before a production restore.

## Production recovery

1. Declare the incident and obtain the required approval.
2. Stop the node and confirm no process has the database open.
3. Capture the current database, WAL, SHM, logs, configuration fingerprint,
   height, and tip for forensics when safe to do so.
4. Select the newest independently verified recovery point that predates the
   corruption or loss.
5. Restore into an empty target path using the command above.
6. Start one node in isolation first and compare height/tip with the manifest.
7. Reconnect it to trusted peers, observe catch-up, reorgs, rejected blocks,
   disk use, memory, and peer behavior.
8. Return it to service only after the incident owner accepts the evidence.

If the restored node diverges from trusted peers, repeatedly fails integrity
checks, or cannot reproduce the manifest tip, stop and escalate as a possible
consensus, storage, or backup-integrity incident.

## Release evidence

Use `PRODUCTION_VOLUME_RECOVERY_REHEARSAL.md` for the repeatable forced-kill,
backup, restore, and replay measurement. Its local baseline does not satisfy
the off-host, independent-operator, or release-hardware requirements below.

Before readiness acceptance, retain evidence of:

- automated live-backup, tamper, overwrite, and restore/reopen tests;
- an encrypted off-host transfer and post-transfer verification;
- a production-sized isolated restore and catch-up;
- measured backup, restore, and recovery times;
- recovery-point and recovery-time objectives;
- access-control and retention review; and
- one operator other than the author successfully following this runbook.
