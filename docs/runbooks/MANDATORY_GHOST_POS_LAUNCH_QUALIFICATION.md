# Mandatory Ghost and PoS Launch Qualification

Status: active release-blocking procedure. This procedure does not authorize
mainnet or start the 30-day release clock.

## Fixed launch decision

Ghost privacy transfers and Proof-of-Stake with isolated validator signing are
mandatory for mainnet v1. Their mainnet dispositions must be `enabled`; neither
may be deferred. Ghost activates at height 1, the first post-genesis block.
Mainnet remains fail-closed until every step below has retained, hash-bound
evidence and the complete release gate returns no blockers.

## Step 1 — finish the production Ghost wallet

Implement and independently test a self-custodial wallet path that:

1. derives separate spend, nullifier, incoming-view, and outgoing-view keys;
2. creates authenticated encrypted notes without exposing keys to the node or
   backend;
3. scans commitments, trial-decrypts owned notes, and tracks nullifiers;
4. maintains Merkle witnesses across blocks, restarts, and bounded reorgs;
5. constructs transparent-to-shielded, shielded-to-shielded, and
   shielded-to-transparent transactions with exact fee/value conservation;
6. invokes a local production prover for the canonical transaction sighash;
7. backs up and restores keys, note state, witnesses, and recovery metadata;
8. refuses stale anchors, spent notes, malformed outputs, prover failure,
   verifier failure, and incomplete recovery state.

The deterministic Rust fixture is test/audit material and must not be exposed as
the wallet prover. The legacy `/api/privacy/*` demo is permanently retired.

Exit evidence: end-to-end vectors and retained logs for all three transaction
directions, restart/reorg recovery, backup/restore, invalid-proof refusal, and
cross-runtime serialization.

## Step 2 — qualify and freeze the Ghost verifier

Build `zk/target/release/ghost_verifier` reproducibly from the frozen source.
Measure valid and adversarial worst-case CPU, RSS, latency, timeout, crash, and
concurrency behavior on the intended node image. Obtain independent review of
the AIR, Rescue implementation, transcript/public-input binding, parser,
subprocess boundary, and operational limits. Close every critical/high finding.

Only then set both source gates in
`wepo-blockchain/core/shielded_verifier.py`:

- `SHIELDED_VERIFIER_RELEASE_AUDIT_APPROVED = True`
- `SHIELDED_VERIFIER_RELEASE_SHA256 = "<audited executable digest>"`

Never derive either value from an environment variable. The production host
must pass `verify-production-host.sh`, which checks the direct executable,
ownership/mode, source approval, and exact digest.

## Step 3 — qualify the validator signer on the intended image

Use a separate locked `wepo-signer` identity. Keep the private key and
anti-equivocation database inaccessible to `wepo-node`. Run the installer only
from the frozen release tree. Before the parameter gate clears, an explicit
`MAINNET_SIGNER_QUALIFICATION_ONLY=1` allows the mainnet-domain signer boundary
to be installed and checked only while the node service is inactive. This mode
does not bypass `WepoFullNode` startup, the parameter manifest, or the complete
release gate.

Retain:

- immutable release and dependency hashes;
- exact sudoers and systemd configuration;
- public validator metadata, never the private key;
- successful live signing and idempotent retry;
- conflicting-height and corrupt-state refusal;
- process restart and database integrity;
- encrypted off-host key-plus-state backup;
- old-host fencing, isolated restore, and single-active-signer failover.

Run the read-only host check after installation:

```bash
sudo NETWORK_PROFILE=mainnet \
  /opt/wepo/current/wepo-production-deployment/verify-validator-signer-host.sh
sudo MAINNET_SIGNER_QUALIFICATION_ONLY=1 \
```

## Step 4 — run the multi-host hybrid consensus rehearsal

Use at least three independently hosted release-candidate nodes in separate
failure domains. Activate real stake through the signer ceremony, produce PoS
blocks, partition the network, build competing PoW/PoS branches, reconnect, and
prove deterministic convergence. Include validator timeout, signer loss,
equivocation attempt, stale state, stronger-PoW reorg, and safe continuation.

Exit evidence: every node has the same final tip, height, supply, UTXO/stake/
masternode/shielded state commitments, and no unresolved divergence.

## Step 5 — qualify production infrastructure

Provision mandatory Redis-backed rate limiting and at least three public seed
nodes across independent providers. Prove TCP 22567 reachability externally.
The operator has supplied `wepocoin.org`. Replace DNS placeholders with
`api.wepocoin.org` and reviewed `seed-*.wepocoin.org` records only after
registrar/DNS operational control and live TCP/P2P resolution are independently
verified. Do not ship historical `wepo.network` or any unverified DNS name.

Run `verify-production-host.sh` on every intended host and retain its output.

## Step 6 — run the continuous seven-day candidate

Use the exact frozen release artifact and parameter manifest for at least 168
continuous hours. Complete every drill in
`seven-day-rehearsal-evidence.template.json`, including Ghost transfer,
invalid-proof, verifier timeout/crash, wallet recovery, live PoS signing,
partition/reorg, anti-equivocation, and signer fencing/failover. Hash the
supporting records and validate the filled document:

```bash
python3 wepo-production-deployment/verify-seven-day-rehearsal-evidence.py \
  --evidence /path/to/filled-seven-day-rehearsal-evidence.json
```

Any release artifact, consensus parameter, verifier, wallet, signer, or host
configuration change resets this rehearsal.

## Step 7 — obtain independent audits

Complete protocol, security, wallet, and operations audits. The retained audit
package must affirm every mandatory Ghost and PoS coverage assertion in
`external-audit-package.template.json`, contain no open critical/high finding,
and pass `verify-external-audit-package.py`.

## Step 8 — assemble frozen release evidence and decide readiness

On a clean runner, retain all required test/build logs and signed artifacts.
Run the release-evidence assembler before its verifier. Then run the full
mainnet release gate with all eight evidence documents. A passing gate is
necessary but does not itself launch mainnet.

After independent reviewers accept the complete readiness package, record the
readiness decision. The earliest launch planning date is 30 full days later. A
consensus, cryptography, wallet authorization, verifier, signer, genesis, or
network-identity change resets that clock.
