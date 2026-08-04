# WEPO Production Validator Signer

Status: executable, protocol, public vector, retained local three-node hybrid
rehearsal, and a disposable separate-user Linux deployment baseline implemented;
release-image deployment, extended multi-host rehearsal, and independent review
remain open. Mainnet PoS remains fail-closed and is mandatory for launch.

## Security objective

The full node must never read or receive a validator private key. It invokes
`wepo-blockchain/signer/wepo_validator_signer.py` through the bounded
`SubprocessValidatorSigner` protocol. In production the signer runs as a
separate `wepo-signer` operating-system account. The node account receives only
permission to execute the exact signer command; it receives no shell as that
account and no read or write access to signer files.

Protocol v3 never asks a signer to authorize an opaque digest. A PoS sign
request carries the complete canonical PoS signing payload plus its claimed:

- network profile;
- block height;
- parent block hash;
- validator address;
- 32-byte SHA3-256 signing message.

The signer independently parses `WEPO_POS_BLOCK_SIGNATURE_V1` and
`WEPO_BLOCK_HEADER_V2`, recomputes the digest, and requires a version-1 PoS
header with zero work fields, an empty validator signature, the configured
network/address/public key, and exact height and parent binding. Unknown fields,
trailing bytes, wrong domains, arbitrary digests, malformed lengths, and cross-
network requests fail closed.

The SQLite anti-equivocation store has a unique key over network, validator,
and height. An identical retry returns the retained signature. A different
parent or signing message at an already signed height is refused. An unsigned
height below the highest retained height is also refused. The database uses
`synchronous=FULL`, a write-ahead log, and an immediate transaction around the
check/sign/insert sequence.

Protocol v3 also closes the cold validator-key lifecycle. Stake creation and
deactivation are built by the live node, but the isolated signer independently
recomputes the network-bound `WEPO_SIGHASH_V3` digest and applies
`stake_transaction_policy.py`. The policy requires exact transaction and UTXO
schemas, validator ownership of every input and output, value conservation,
network-specific minimum stake, a 10,000-atomic fee ceiling, and the one
permitted stake-lock or stake-unlock shape. An operator must approve the exact
request through the signer-only `--authorize-stake-request` path before the
node's `--stdio` command can sign it. Authorized outpoints are fenced in SQLite;
an identical retry returns the retained signatures and any conflicting use is
refused.

The node's exact sudo rule deliberately permits only `--stdio`. It cannot invoke
the authorization path. The operator workflow is exposed by
`wepo-production-deployment/validator_stake_ceremony.py` as separate prepare,
authorize, sign, and submit steps; signing never broadcasts implicitly. The
validator private key is never exported to the controller, browser, or node.

## Key and state format

The key file is strict JSON with format `wepo-validator-key-v1`, the network,
validator address, ML-DSA-44 public key, and ML-DSA-44 private key. Loading it
checks exact field names and sizes, public-key ownership of the address, and a
sign/verify self-test proving that the private and public keys match.

On a production POSIX host:

- the key must be a regular non-symlink file with no group/other permissions;
- the state directory must be a real non-symlink directory with no group/other
  permissions;
- an existing state database must be a private regular non-symlink file;
- newly created key and state files are mode `0600` and their directories are
  mode `0700`.

The hidden `--allow-insecure-permissions-for-test` switch exists only so the
cross-platform regression suite can exercise the executable on Windows. Never
place that switch in deployment configuration.

## Linux deployment contract

Create separate locked service accounts and directories. Adapt `/opt/wepo` to
the frozen release path, but do not broaden ownership or command permissions.

```sh
sudo useradd --system --home /var/lib/wepo-signer --shell /usr/sbin/nologin wepo-signer
sudo install -d -m 0700 -o wepo-signer -g wepo-signer /var/lib/wepo-signer/private
sudo install -d -m 0700 -o wepo-signer -g wepo-signer /var/lib/wepo-signer/state
sudo -u wepo-signer /opt/wepo/venv/bin/python \
  /opt/wepo/current/wepo-blockchain/signer/wepo_validator_signer.py \
  --network test \
  --key-file /var/lib/wepo-signer/private/validator-key.json \
  --init-key
```

Key initialization uses exclusive creation and refuses to overwrite a file.
It prints only the network, validator address, and public key. Capture those
public values for review; never copy the private JSON into release evidence.

Install an exact sudoers rule after substituting the actual immutable release
path. The node account must not have general `sudo -u wepo-signer`, interpreter,
file-copy, editor, or shell permission.

```text
wepo-node ALL=(wepo-signer) NOPASSWD:NOEXEC: /opt/wepo/venv/bin/python /opt/wepo/current/wepo-blockchain/signer/wepo_validator_signer.py --network test --key-file /var/lib/wepo-signer/private/validator-key.json --state-db /var/lib/wepo-signer/state/anti-equivocation.sqlite3 --stdio
```

Configure the node with an explicit JSON argv array:

```text
WEPO_VALIDATOR_SIGNER_COMMAND_JSON=["/usr/bin/sudo","-n","-u","wepo-signer","--","/opt/wepo/venv/bin/python","/opt/wepo/current/wepo-blockchain/signer/wepo_validator_signer.py","--network","test","--key-file","/var/lib/wepo-signer/private/validator-key.json","--state-db","/var/lib/wepo-signer/state/anti-equivocation.sqlite3","--stdio"]
WEPO_VALIDATOR_SIGNER_TIMEOUT_SECONDS=15
```

The immutable executable and its Python dependency lock must be hashed and tied
to the release manifest. The sudoers command must use that same immutable path.

The source-controlled deployment pack is:

- `wepo-production-deployment/install-validator-signer.sh`;
- `wepo-production-deployment/verify-validator-signer-host.sh`;
- `wepo-production-deployment/run_validator_signer_linux_rehearsal.py`.
- `wepo-production-deployment/validator_stake_ceremony.py`;

The installer defaults to `test`, matching the canonical staging node's only
supported non-mainnet profile. It accepts `mainnet` after the frozen parameter
gate clears. Before that, explicit `MAINNET_SIGNER_QUALIFICATION_ONLY=1` permits
mainnet-domain signer installation and verification only while the node service
is inactive; this does not bypass node startup or release gates. Every other
profile is rejected. It creates locked identities, private state,
the exact `NOEXEC` sudoers rule, a JSON argv environment file, and a systemd
drop-in that explicitly changes `NoNewPrivileges` and exposes only signer state
through the unit's protected filesystem namespace. The verifier proves the
allowed request plus forbidden command/argument paths and SQLite integrity.
Never substitute `mainnet` in these examples while that gate is closed.

## Backup, failover, and incident rules

The validator key and anti-equivocation state are one inseparable safety unit.
Back up both encrypted and off-host. Never restore only the key. Never run two
active signer instances for one key.

Before failover:

1. fence the old signer host and prove it cannot receive node requests;
2. restore the newest key plus state database to the replacement signer account;
3. verify ownership, `0700` directories, `0600` files, and release hashes;
4. query the retained maximum signed height and compare it with network state;
5. start one node/signer path and retain a signed operator record.

A lost or stale anti-equivocation database is not an automatic recovery case.
Keep that validator offline until a reviewed procedure establishes a safe
height. If host compromise may have exposed the private key, retire the key and
follow the consensus-approved validator-key replacement process; do not copy it
to another live host.

## Acceptance still required

This implementation closes the executable, opaque-digest, and cold-key
stake-lifecycle weaknesses.
It does not yet qualify mainnet PoS. Mandatory launch readiness still requires:

- reproduce `tests/vectors/validator_signer_protocol_v3.json` from the frozen
  build and retain its SHA-256
  `e6f2ba31d07f25ad71701b0a78dd7cb5e2d58d3c9471e712f7f17386a45cc868`;
- retain the completed local three-node test-profile partition/reorg baseline
  under `release-evidence/local/2026-08-01-pos-multinode-v2/`. It proves
  cold-key stake activation and real
  node-to-signer PoS production, stronger-PoW reorg, retained height-6
  anti-equivocation state, safe continuation at height 8, and equal all-table
  semantic state across all three nodes. Evidence SHA-256 is
  `1b26f02a9f7e88c29e82a78331903e42774277bcbe56a7486dd5389a02ba0879`;
- retain the completed pinned Debian 13 test-profile separate-user baseline
  under `release-evidence/local/2026-08-01-validator-signer-linux-v4/`. It proves
  immutable root-owned signer and stake-policy files, exact sudo delegation,
  negative permission
  paths, process restart, idempotence, conflict refusal, corrupt-state
  fail-closed behavior, complete key-plus-state restore, and continuation.
  Evidence SHA-256 is
  `afd8b045ad496a9d9844dcd366233c380fb37832929b9df19affc249c080ff8a`;
- deployment under separate users on the intended Linux release image;
- release-host restart, signer-timeout, corrupt-state, fencing, encrypted
  off-host backup, and failover drills;
- extended multi-host hybrid PoW/PoS partition and reorg rehearsal;
- source, deployment, and cryptographic review by an independent reviewer.

Until those gates pass, `pos_consensus_ready` remains false for mainnet. PoS
may not be removed or deferred from frozen v1 consensus.
