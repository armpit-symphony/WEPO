# Monitoring and Alert Contract

## Principles

Monitoring is read-only, tenant-free, and evidence-producing. It must not hold
wallet, validator, database, or TLS private keys. Alert delivery must not include
credentials, complete peer IP lists, customer IPs, transaction metadata, or
private messages.

Every release host must report its release-manifest hash, network/genesis/
parameter identity, service start time, and failure domain as immutable labels.
A monitor must compare independent nodes; a single node cannot prove its own
canonicality.

## Required signals

| Signal | Source | Initial alert policy (must be reviewed before release) |
|---|---|---|
| height, tip, supply | node `/api/network/status` | critical when trusted nodes persistently disagree |
| latest block age | latest-block API | warn at 2 expected intervals; critical at 4 |
| peer count/diversity | node status plus connection inventory | warn below 3; critical at 0 |
| reorg/rejected blocks | node operational counters/logs | warn on unexpected reorg or sustained rejection spike |
| mempool count/bytes | node status | warn at 75%; critical at 90% of either bound |
| node/backend service | systemd plus loopback health | critical after two consecutive failures |
| public API/TLS | independent HTTPS probe | critical on failure; warn 30 days before expiry, critical at 14 |
| Redis | authenticated private probe and backend behavior | critical on loss or any fail-open request |
| MongoDB | authenticated private health and latency | critical on loss; warn on sustained latency/error growth |
| disk/inodes | host metrics | warn at 70%, critical at 85%, with projected exhaustion |
| memory/CPU/handles | host and cgroup metrics | baseline-derived; alert on sustained exhaustion/leak trend |
| SQLite/WAL/backup | file metrics and scheduled verification | alert on abnormal growth, failed quick check, stale backup |
| signer | request latency/error, retained height, state integrity | critical on conflict, corrupt state, or unexpected identity |
| seed reachability | independent TCP/P2P probes | warn on one loss; critical below three failure domains |

The release candidate must establish normal baselines before thresholds are
frozen. Defaults above are starting policy, not claims of measured capacity.

## Alert evidence

Each alert records UTC start/end, release hash, host/failure domain, signal,
threshold, observed value, correlation ID, acknowledgement, actions, and closure
reason. Chain/fork alerts attach sanitized node identity and block hashes.

## Required synthetic checks

- HTTPS and certificate validation from at least two external networks;
- port 22567 TCP plus WEPO handshake from outside each provider;
- node/backend/Redis dependency-aware health;
- static-peer bootstrap with DNS disabled;
- DNS bootstrap with one seed unavailable;
- periodic verified backup restore to an isolated empty directory;
- alert-delivery test with no production mutation.

## Known implementation boundary

Current node status exposes height, tip, supply, consensus, peers, mempool count
and bytes, plus process-scoped structured block-validation, reorg, P2P rejection,
misbehavior-ban, and connection-failure counters. External monitoring must retain
and derive deltas because process counters reset on restart. A packaged exporter,
intended-host alert delivery, and threshold/retention qualification remain open.
