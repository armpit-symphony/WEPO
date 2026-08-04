# P2P Hostile-Traffic Soak

Status: local engineering baseline proven; release-candidate qualification pending

## Purpose

Exercise a real WEPO TCP listener under connection churn, malformed frames, slow
handshakes, and ban-registry pressure while a valid control peer remains
connected. The harness measures peer/buffer bounds, chain and SQLite stability,
memory, handles, threads, and shutdown cleanup. It writes evidence exclusively
and never enables mainnet.

This procedure is not a substitute for independent hosts, public internet
paths, release hardware, production monitoring, or the seven-day candidate
rehearsal.

## Local baseline

The local engineering baseline requires all of the following in one run:

- at least 300 seconds and 6,000 scheduled attacks;
- seven slow clients plus one valid control peer, never exceeding eight peers;
- rotating invalid magic, oversized declaration, bad checksum,
  pre-handshake ping, malformed version, partial-header, and churn traffic;
- zero connect/send failures and zero valid-peer failure samples;
- the 4,096-host ban registry limit reached but never exceeded;
- handshake deadlines observed and receive buffers bounded;
- identical chain height/tip and exactly zero hostile-traffic database growth;
- passing SQLite `quick_check` and empty `foreign_key_check`;
- bounded RSS, Python heap, handle, and thread growth; and
- an empty peer registry with all P2P service threads joined after shutdown.

## Run

Use new work and evidence paths. The harness refuses to reuse the work directory
or overwrite evidence.

```powershell
python wepo-blockchain\scripts\wepo_p2p_hostile_soak.py `
  --work-directory C:\tmp\wepo-p2p-hostile-soak `
  --output release-evidence\local\p2p-hostile-soak\evidence.json `
  --duration-seconds 300 `
  --attack-rate 25 `
  --slow-clients 7 `
  --sample-interval-seconds 1 `
  --progress-every-seconds 10
```

The default resource ceilings are 128 MiB RSS growth, 64 MiB Python heap,
128 additional process handles/file descriptors, and two additional threads.
Release thresholds must be approved from release-hardware and monitoring data;
do not silently raise a failed limit.

## Evidence acceptance

Accept the JSON only when:

- `format` is `wepo-p2p-hostile-soak-v1` and `status` is `pass`;
- `release_qualification` is `false` for a local run;
- every value in `acceptance` is `true`;
- `local_baseline.met` is `true`;
- the recorded script, P2P, and blockchain SHA-256 values match the files that
  were exercised; and
- the retained output path is unique and immutable.

Socket reset after a successfully delivered malformed frame is normal rejection
behavior and is not a connect/send failure. A failure before or during
`sendall`, any healthy-peer loss, state/disk mutation, missing resource metric,
or leaked thread/peer is a failed run.

## Current local result

The final 2026-07-31 workstation run is retained at
`release-evidence/local/2026-07-31-p2p-hostile-soak-r3/evidence.json` and passed:

- 300.0 seconds and 7,500 delivered attacks with zero connect/send failures;
- zero valid-peer failure samples across repeated keepalive intervals;
- peak eight peer entries and 4,096 banned hosts;
- all seven slow handshake deadlines observed;
- unchanged height/tip and 387,096 database bytes before and after traffic;
- passing SQLite integrity checks;
- 7,933,952 bytes peak RSS growth, 3,106,867 bytes peak Python heap,
  four additional handles, and zero thread growth; and
- zero peers and no retained P2P service threads after shutdown.


## Trusted propagation companion

Run `wepo_p2p_trusted_under_load.py` after the resource baseline to prove that
valid consensus work remains available during attack load. The companion local
baseline requires at least 120 seconds, 40 real signed transaction/block pairs,
2,400 delivered hostile connections, repeated keepalive intervals, identical
tips and issued supply, an empty confirmed mempool, and clean shutdown.

The 2026-07-31 companion result is retained at
`release-evidence/local/2026-07-31-p2p-trusted-under-load/evidence.json` and
passed 60 real FIPS 204 transaction/block propagations during 2,990 delivered
malformed connections with zero connect/send or healthy-peer failures. Both
chains finished at height 61 with tip
`b6b1a2c666440b14cb9a86c7b898d4bb97e786d09d955837244c5828407c8638`
and issued supply `208314698593`. Maximum measured latency was 0.093 seconds
for transaction admission and 0.125 seconds for block convergence. This is
loopback workstation evidence, not independent-host qualification.

## Abrupt restart companion

Run `wepo_p2p_restart_under_load.py` to prove non-graceful same-database
restart and exact peer catch-up while hostile traffic continues. The procedure,
acceptance contract, current evidence, and remaining gates are in
`docs/runbooks/P2P_RESTART_UNDER_LOAD.md`.


The original run retained under `2026-07-31-p2p-hostile-soak/` exposed and
failed on a keepalive race at about 61 seconds. The `r2` run proved the node fix
but used superseded reset/RSS evidence semantics. Neither is the current
baseline; both remain useful diagnostic history.

## Remaining release qualification

Before readiness acceptance, repeat from the frozen clean candidate and retain:

- independent-host and public internet-path hostile traffic;
- trusted transaction and block propagation during attack load;
- release-hardware resource graphs and approved alert thresholds;
- combined chain-volume, disk-pressure, restart, and recovery behavior;
- an independent operator following this runbook; and
- the continuous seven-day release-candidate network rehearsal.
