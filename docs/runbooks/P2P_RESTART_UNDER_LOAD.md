# P2P Abrupt Restart Under Hostile Load

Status: local engineering baseline proven; release-candidate qualification pending

## Purpose

Prove that a real WEPO node can be killed without a graceful shutdown, reopen the
same database, reconnect to a peer that advanced while it was offline, and
converge to the exact canonical state while malformed TCP traffic continues.

The harness uses the test network profile, fixed difficulty 1, loopback APIs,
and two real node subprocesses. It never enables mainnet and explicitly records
`release_qualification: false`.

## Local baseline

One local engineering run must satisfy all of these conditions:

- the target reaches height 10 while hostile traffic is active;
- at least 100 malformed connections are delivered before the kill with no
  online connect/send errors;
- the target process is killed abruptly and returns a nonzero exit code;
- the source mines at least five additional blocks while the target is offline;
- attempted hostile connections fail during the planned outage;
- the target restarts from its original data directory and reconnects;
- source and target API height and best-block hash converge exactly;
- at least 50 more malformed connections are delivered after recovery with no
  connect/send errors;
- independent post-shutdown replay produces identical height, tip, and issued
  supply for both databases;
- both databases pass SQLite `quick_check` and `foreign_key_check`; and
- the hostile-load thread terminates cleanly and configured peer/ban bounds
  remain unchanged.

## Run

Use fresh work and evidence paths. The harness refuses to reuse the work
directory or overwrite its evidence file.

```powershell
python wepo-blockchain\scripts\wepo_p2p_restart_under_load.py `
  --work-directory C:\tmp\wepo-p2p-restart-under-load `
  --output release-evidence\local\p2p-restart-under-load\evidence.json `
  --initial-height 10 `
  --offline-blocks 5 `
  --attack-rate 25 `
  --minimum-online-attacks 100 `
  --minimum-post-restart-attacks 50
```

## Evidence acceptance

Accept a local result only when:

- `format` is `wepo-p2p-restart-under-load-v1`;
- `status` is `pass` and `release_qualification` is `false`;
- every value in `acceptance` is `true`;
- `local_baseline.met` is `true`;
- `actual.abrupt_exit_code` is nonzero;
- online and post-restart attack errors are zero, while outage errors are
  greater than zero;
- `actual.source_replay` exactly equals `actual.target_replay`; and
- every recorded script, dependency, node, P2P, and blockchain SHA-256 matches
  the file that was exercised.

A smaller bounded profile is a regression smoke only. It must report
`local_baseline.met: false` even when all functional acceptance checks pass.

## Current local result

The final 2026-08-01 workstation result is retained at
`release-evidence/local/2026-08-01-p2p-restart-under-load-r2/evidence.json` and
passed all 16 acceptance checks:

- target height 10 before the abrupt kill and exit code 1;
- source and recovered target height 15;
- 100 delivered online attacks and 52 delivered post-restart attacks, with zero
  errors in both online phases;
- seven connection failures during the intentional outage;
- identical replay tip
  `6cf77c15721a8f650933637c15aaa03dca20588c430d6f6722cf962143f87344`;
- identical issued supply `112964698624`;
- passing SQLite integrity and zero foreign-key violations; and
- matching recorded hashes for every exercised code file.

The earlier non-`r2` result used the superseded in-flight phase-attribution
logic and is retained only as diagnostic history.


This result is loopback workstation evidence. It does not qualify release
hardware, public internet paths, independent failure domains, monitoring, or
sustained production-volume disk pressure.

## Remaining release qualification

Before readiness acceptance, repeat from the frozen clean candidate with:

- independent source and target hosts over real internet paths;
- release-hardware resource, disk, and monitoring telemetry;
- production-volume chain state and approved alert thresholds;
- an independent operator following this runbook;
- network partition and process restart fault injection during trusted traffic;
  and
- the continuous seven-day release-candidate network rehearsal.
