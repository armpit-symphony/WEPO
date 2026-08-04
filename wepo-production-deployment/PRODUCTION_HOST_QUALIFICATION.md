# Production Host Qualification Contract

Status: source-controlled, inert pre-release contract. It does not authorize
mainnet, create cloud resources, install services, change DNS, or start the
30-day release clock.

## Security boundary

The intended release topology uses three locked identities:

- `wepo-node` owns only `/var/lib/wepo/node` and runs the loopback node API plus
  public P2P listener;
- `wepo-api` owns only `/var/lib/wepo/backend` and runs the loopback backend;
- `wepo-signer` owns validator key/state and is reachable only through the exact
  signer command in `docs/VALIDATOR_SIGNER_SECURITY.md`.

Nginx is the only public HTTP process. Ports 8011 and 8122 must remain
loopback-only. Port 22567 is P2P and must be externally reachable. MongoDB and
Redis must use private-network endpoints or private local sockets and must not
listen on a public interface.

The production node service cgroup includes every external Ghost verifier child
and must retain these effective ceilings: `TasksMax=128`, `CPUQuota=200%`,
The node environment must name exactly one direct Ghost verifier executable in
the signed release tree. `verify-production-host.sh` requires source-controlled
independent-audit approval and verifies the installed executable against the
source-frozen SHA-256.
`MemoryHigh=60%`, and `MemoryMax=75%`. The Python verifier boundary separately
admits at most two children by default and rejects excess work without spawning.
The host verifier refuses unlimited effective systemd values. Percentages adapt
to host RAM; the intended image still requires measured latency, peak RSS,
pressure behavior, OOM/restart recovery, and evidence that the chosen host size
is adequate.

## Canonical assets

- `backend-production.env.example`
- `node-production.env.example`
- `wepo-backend-production.service.example`
- `wepo-node-production.service.example`
- `nginx-wepo-api-production.conf.example`
- `verify-production-host.sh`
- `redis-outage-evidence.template.json`
- `verify-redis-outage-evidence.py`
- `monitoring-evidence.template.json`
- `.github/workflows/release-qualification.yml` (clean-runner CI evidence)
- `RELEASE_RUNNER_HANDOFF.md`
- `verify-monitoring-evidence.py`
- `backup-restore-evidence.template.json`
- `verify-backup-restore-evidence.py`
- `seven-day-rehearsal-evidence.template.json`
- `verify-seven-day-rehearsal-evidence.py`
- `external-audit-package.template.json`
- `verify-external-audit-package.py`
- `release-qualification-evidence.template.json`
- `assemble-release-qualification-evidence.py`
- `verify-release-qualification-evidence.py`

The examples intentionally contain `example.invalid` and `REPLACE` values.
The verifier refuses them. No script in this pack provisions or mutates a host.

## Release-image rehearsal order

1. Freeze one reviewed commit and build immutable release artifacts on a clean
   runner. Produce `SHA256SUMS` relative to the release root and sign the
   release manifest.
2. Create the locked service identities and private state directories through
   an operator-reviewed infrastructure change.
3. Install the release under a root-owned versioned directory such as
   `/opt/wepo/releases/<commit>`; make `/opt/wepo/current` point to the approved
   release only after manifest verification.
4. Render the production templates for the public `test`-profile release-image
   rehearsal. Keep the same users, paths, proxy, TLS, firewall, Redis, MongoDB,
   monitoring, and backup layout intended for release.
5. Install the detached release signature as `SHA256SUMS.sig` and the offline
   signing public key as `/etc/wepo/release-signing-public.pem`; the private
   release-signing key must never be present on a release host.
6. Store `/etc/wepo/backend.env` and `/etc/wepo/node.env` as root-owned regular
   files, mode 0640 or 0600. Never place credentials in the release tree.
7. Install a trusted certificate, validate the complete chain, and confirm at
   least 14 days remain before expiry.
8. Run the signer, seed, backup/restore, partition, hostile-traffic, and Redis
   outage rehearsals on the intended image.
9. Run `verify-validator-signer-host.sh` for the intended network and retain its
   permission-denial, anti-equivocation database, and public-identity evidence.
10. Run `verify-production-host.sh` and retain stdout, service/unit hashes,
   release-manifest hash, certificate fingerprint, public IP/failure-domain
   inventory, and independent port/TLS observations.
11. Repeat on the frozen mainnet configuration only after the parameter and
    genesis review. The verifier runs the machine-readable mainnet decision gate;
    mainnet must remain unable to start before that parameter gate returns no
    blockers. Final release acceptance separately runs
    `wepo_mainnet_release_gate.py status` with every required operations evidence
    file and the hash-bound readiness decision package.

Example read-only verification command:

```bash
sudo PUBLIC_API_HOST=api.wepocoin.org \
  EXPECTED_NETWORK=test \
  /opt/wepo/current/wepo-production-deployment/verify-production-host.sh
```

## Controlled Redis outage drill

The automated suite proves that an unreachable required Redis fails startup and
that a runtime Redis exception denies rate-limited requests. Release-host
qualification additionally requires a controlled real outage:

1. obtain change approval and open an evidence log;
2. verify normal HTTPS requests and record Redis identity/health;
3. make only the release-candidate Redis endpoint unavailable while the backend
   remains running;
4. issue requests to global and strict per-endpoint rate-limited routes from an
   external client;
5. require denial (HTTP 429) and prove that no request fell back to process
   memory or returned success;
6. restore Redis, verify recovery, and confirm the backend did not require an
   unsafe configuration change;
7. fill `redis-outage-evidence.template.json` with timestamps, status-only
   request results, redacted Redis identity, backend/release hashes, and
   log-redaction confirmation;
8. validate the retained evidence before go/no-go review:

   ```bash
   python3 /opt/wepo/current/wepo-production-deployment/verify-redis-outage-evidence.py \
     --evidence /path/to/filled-redis-outage-evidence.json
   ```

Never perform this drill against a live public network without explicit change
approval. Do not publish Redis URLs, credentials, cookies, wallet material, or
client IP addresses in evidence.

## Monitoring and alert qualification

Retain one filled `monitoring-evidence.template.json` for the frozen release
commit. It must cover at least three distinct seed nodes, external TCP 22567
reachability, dependency-aware health, chain height/tip, peer count, mempool,
consensus rejection, Redis, and certificate-expiry metrics. Exercise and receive
test notifications for node-unreachable, chain-stalled, low-peer-count, Redis
unavailable, and certificate-expiry alerts. Retain redacted dashboard and alert
test logs for at least 30 days, then validate the artifact:

```bash
python3 /opt/wepo/current/wepo-production-deployment/verify-monitoring-evidence.py \
  --evidence /path/to/filled-monitoring-evidence.json
```

This validator records evidence; it does not configure a monitoring backend or
send alerts. Credentials, authorization headers, private datastore URLs, and
notification-provider tokens must not enter the retained artifact.

## Encrypted backup/restore qualification

Retain one filled `backup-restore-evidence.template.json` for the same release
commit and release-artifact hash used by monitoring evidence. The rehearsal must
create an encrypted off-host copy of node chainstate and any selected backend
durable state, keep the encryption key separate, and
exclude validator private keys and wallet seed phrases. Restore into an isolated
environment, prove the exact expected height and chain-tip hash, start the node,
pass dependency-aware health, resume peer synchronization, and record measured
RPO/RTO within approved targets. Keep at least two copies across two independent
failure domains, then validate the artifact:

```bash
python3 /opt/wepo/current/wepo-production-deployment/verify-backup-restore-evidence.py \
  --evidence /path/to/filled-backup-restore-evidence.json
```

The qualification format refuses a destructive live restore and does not permit
key-bearing backup scopes. It is not authorization to change a live public
network.

## Continuous seven-day candidate qualification

After every shorter rehearsal passes, keep the frozen candidate under continuous
observation for at least 168 hours. Use at least three independently hosted nodes
and retain final convergence, availability, supply, incident, drill, and redacted
monitoring records. The filled rehearsal artifact must hash-bind the exact seed,
Redis outage, monitoring, and backup/restore evidence used for the candidate:

```bash
python3 /opt/wepo/current/wepo-production-deployment/verify-seven-day-rehearsal-evidence.py \
  --evidence /path/to/filled-seven-day-rehearsal-evidence.json
```

Any unexplained consensus or supply divergence, unresolved critical incident,
irreversible data loss, observation gap, failed required drill, or candidate
artifact/configuration change resets the rehearsal. The validator records a
completed rehearsal; it does not create or accelerate the required seven days.
The filled evidence must include every mandatory Ghost and PoS drill plus hashes
of the wallet/verifier, PoS multi-node, validator-host, and signer-failover
records required by `docs/runbooks/MANDATORY_GHOST_POS_LAUNCH_QUALIFICATION.md`.

## Retained external-audit bundle

Use `external-audit-package.template.json` only after independent protocol,
security, wallet, and operations engagements are complete. Keep each scope
document, independence attestation, signed report, and finding-disposition log
inside the bundle using safe relative paths. Critical and high findings must be
closed. The validator hashes every referenced file and refuses missing,
tampered, path-escaping, reused, placeholder, or incomplete evidence:

```bash
python3 /opt/wepo/current/wepo-production-deployment/verify-external-audit-package.py \
  --package /path/to/filled-external-audit-package.json
```

A structural pass does not create auditor independence or validate the technical
quality of a report. Named security and operations owners must inspect the
retained files, signature-verification records, scope coverage, and dispositions
before approving the readiness package. Confidential reports remain controlled
evidence and must not be committed to the public repository.

The clean-runner workflow is an evidence source, not the release-evidence
assembler. After the workflow artifact is downloaded, run the canonical
`assemble-release-qualification-evidence.py` tool first; only a successful
assembly may be passed to `verify-release-qualification-evidence.py`. This
ordering is mandatory because the assembler copies and hash-binds the retained
artifacts and verifies the detached manifest signature before the verifier
reviews the complete bundle.

## Retained release qualification evidence

Build the frozen candidate on a clean runner and prepare the required source,
signature, transcript, and test-log inputs. The canonical assembler is
`assemble-release-qualification-evidence.py`; run it first to copy the retained
artifacts, verify the detached manifest signature, hash-check every manifest
file, and emit the machine-readable bundle:

```bash
python3 /opt/wepo/current/wepo-production-deployment/assemble-release-qualification-evidence.py \
  --template /opt/wepo/current/wepo-production-deployment/release-qualification-evidence.template.json \
  --evidence /path/to/release-qualification-evidence.json \
  --release-root /path/to/release-root \
  --release-commit <frozen-commit> \
  --parameter-manifest-sha256 <parameter-manifest-sha256> \
  --source-archive /path/to/wepo-source.tar.gz \
  --signed-source-archive /path/to/wepo-source-signed.tar.gz \
  --release-manifest /path/to/release-root/SHA256SUMS \
  --release-manifest-signature /path/to/release-root/SHA256SUMS.sig \
  --release-signing-public-key /path/to/release-signing-public.pem \
  --genesis-construction-transcript /path/to/genesis-construction-transcript.json \
  --python-maintained-suite-log /path/to/python-maintained.log \
  --rust-release-all-targets-log /path/to/rust-release.log \
  --frontend-vitest-log /path/to/frontend-vitest.log \
  --frontend-production-build-log /path/to/frontend-build.log \
  --desktop-package-boundary-log /path/to/desktop-package.log \
  --github-actions-green-log /path/to/github-actions.log \
  --clean-runner \
  --reproducible-source-archive
```

Only after successful assembly, run the canonical verifier against the emitted
JSON:

```bash
python3 /opt/wepo/current/wepo-production-deployment/verify-release-qualification-evidence.py \
  --evidence /path/to/release-qualification-evidence.json
```

The bundle must keep the source archive, signed source archive, release manifest
and signature, signing public key, signature-verification record, genesis
construction transcript, and logs for every maintained Python, Rust, frontend,
desktop, and CI test surface. The validator verifies safe paths, nonempty
retained files, hashes, passing test summaries, and fail-closed attestations. It
also directly verifies the detached manifest signature with the retained PEM
public key, accepting RSA PKCS#1-v1.5/SHA-256 or ECDSA/SHA-256. It does not create
a signature, establish runner trust, or prove reproducibility by itself;
reviewers must verify those properties independently before approval. The
readiness package and every named GO approval must bind the retained public-key
SHA-256 fingerprint so a matching replacement key and signature cannot silently
substitute for the approved key.

## TLS and proxy acceptance

The rendered nginx configuration must:

- redirect HTTP to HTTPS;
- allow only TLS 1.2 and 1.3;
- disable session tickets;
- set HSTS, `nosniff`, frame denial, restrictive CSP and permissions policy;
- cap bodies, connections, request rate, header size, and timeouts;
- overwrite `X-Real-IP` and `X-Forwarded-For` with `$remote_addr`;
- expose a dependency-aware health path, not a static always-healthy response.

The backend must explicitly trust proxy headers only because it is bound to
loopback and nginx overwrites them. Direct public access to 8011 or 8122 fails
qualification.

## Evidence that remains external

A local pass of the contract tests proves the pack's structure, not a production
deployment. Release acceptance still requires intended-host output, independent
port 22567 and TLS observations, encrypted off-host backup/restore, monitoring
alerts, multi-host fault injection, seven continuous days without unexplained
divergence, and independent security review.
