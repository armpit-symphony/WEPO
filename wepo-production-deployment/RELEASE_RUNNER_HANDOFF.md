# Clean-runner release qualification handoff

This document describes the CI evidence handoff. It does not authorize mainnet,
set a launch date, or replace the signed release-evidence assembler and verifier.
The 30-day launch-planning clock starts only after the complete readiness package
is accepted.

## 1. Run the qualification workflow

Run the GitHub Actions workflow named `WEPO release qualification` from the
frozen release commit. It uses clean Ubuntu 24.04 and Windows 2022 runners and
retains these surfaces:

- maintained Python pytest log with the 243-test minimum;
- locked Rust all-target release tests and native/WASM Ghost artifact hashes;
- frontend Vitest and production-build logs;
- Windows desktop package-boundary log and package/artifact hashes;
- an aggregate `github-actions-green.log` and `ci-artifacts.sha256`.

Download the artifact named
`wepo-ci-release-qualification-<commit-sha>` and preserve it outside the
repository with the frozen commit and workflow run URL.

The workflow deliberately records
`release_evidence_assembly=blocked_pending_signed_release_inputs`. CI cannot
invent or attest the source signature, release signing key, genesis transcript,
or frozen parameter manifest.

## 2. Assemble, then verify signed release evidence

After the workflow succeeds, collect the external release inputs listed in the
evidence template: source archive, signed source archive, `SHA256SUMS`,
`SHA256SUMS.sig`, retained signing public key, genesis-construction transcript,
parameter-manifest hash, and all required operational logs. On the clean release
runner, run the canonical assembler first:

```bash
python3 wepo-production-deployment/assemble-release-qualification-evidence.py \
  --template wepo-production-deployment/release-qualification-evidence.template.json \
  --evidence /secure/evidence/release-qualification-evidence.json \
  --release-root /secure/release-root \
  --release-commit <frozen-commit> \
  --parameter-manifest-sha256 <manifest-sha256> \
  --source-archive /secure/source.tar.gz \
  --signed-source-archive /secure/source-signed.tar.gz \
  --release-manifest /secure/release-root/SHA256SUMS \
  --release-manifest-signature /secure/release-root/SHA256SUMS.sig \
  --release-signing-public-key /secure/release-signing-public.pem \
  --genesis-construction-transcript /secure/genesis-transcript.json \
  --python-maintained-suite-log /secure/logs/python-maintained.log \
  --rust-release-all-targets-log /secure/logs/rust-release.log \
  --frontend-vitest-log /secure/logs/frontend-vitest.log \
  --frontend-production-build-log /secure/logs/frontend-build.log \
  --desktop-package-boundary-log /secure/logs/desktop-package.log \
  --github-actions-green-log /secure/logs/github-actions-green.log \
  --clean-runner --reproducible-source-archive
```

Only after successful assembly, run:

```bash
python3 wepo-production-deployment/verify-release-qualification-evidence.py \
  --evidence /secure/evidence/release-qualification-evidence.json
```

The assembler and verifier are separate fail-closed steps. A green CI artifact
alone is not signed release evidence.

## 3. DNS and public-host follow-up: `wepocoin.org`

The owned domain is `wepocoin.org`; no DNS mutation is performed by this
workflow. Before public release, the operator must record registrar/DNS-provider
control, MFA/recovery ownership, and the final reviewed records:

- `api.wepocoin.org` for the public HTTPS API endpoint;
- `seed-aws.wepocoin.org` on AWS;
- `seed-do-vps.wepocoin.org` on DigitalOcean or an independently hosted VPS;
- an optional third `seed-*.wepocoin.org` host in another failure domain.

Externally verify A/AAAA resolution, TLS, and TCP port `22567` reachability for
every seed. Keep static peer fallback records. Do not ship the historical
`wepo.network` placeholder or any invented/unverified hostname.

## 4. Remaining human/external gates

The bundle remains internal-only until production Redis-backed rate limiting,
three public seed nodes, Ghost verifier qualification, PoS signer ceremony,
seven continuous days of rehearsal, and independent protocol/security/wallet/
operations audits are retained and accepted. Any consensus, verifier, wallet,
signer, genesis, or network-identity change resets the rehearsal and the
post-acceptance 30-day planning clock.
