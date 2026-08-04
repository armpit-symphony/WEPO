# Mainnet Parameter Freeze Ceremony

Status: required before mainnet can start. This procedure does not authorize a
release date, cloud deployment, DNS changes, or genesis.

## Roles and evidence boundary

Use two people: an operator performs commands and an independent reviewer reads
the source diff, parameter document, manifest, and retained output. Neither role
may waive a blocker by editing evidence after the command runs.

The read-only command is:

```bash
python wepo-blockchain/scripts/wepo_mainnet_release_gate.py status
```

It exits `2` while any blocker remains and `0` only when the exact default
manifest is present, byte-bound to its source SHA-256, semantically equal to the
source-derived parameter set, and every decision is internally consistent.

## Policy implementation rule

An allowed policy label is not proof that consensus implements it.

Currently implemented:

- genesis reward: `auditable_distribution` (the 400-WEPO output goes to the
  reviewed quantum address);
- emission: `ceiling_only` (69,000,003 WEPO is a hard safety ceiling, while the
  present maximum schedule is 26,006,468.86718600 WEPO and path-dependent).

Allowed but deliberately rejected as not implemented:

- genesis reward: `burn`;
- emission: `redesigned_target_cap` and `lowered_cap`.

A burn requires explicit, reviewed consensus semantics; sending funds to a key
that someone claims was destroyed is not a provable burn. Redesigned or lowered
emission requires changed consensus constants/rules, regenerated cross-runtime
vectors, full regression, and independent review. Never clear a
`*_policy_not_implemented` blocker by changing only an implementation-set label.

The recorded owner statement that 69,000,003 is exact is not equivalent to the
currently implemented `ceiling_only` behavior. Selecting ceiling-only therefore
amends the published monetary-policy decision and must be explicit; otherwise
the emission curve must be redesigned and audited first.

## Pre-ceremony requirements

1. Resolve and record the genesis reward policy and recipient semantics.
2. Resolve emission policy and make its code, oracle vectors, and published
   language agree.
3. Select coinbase maturity and minimum relay fee from retained workload and
   security evidence.
4. Confirm the owner-decided mandatory `enabled` dispositions for PoS and Ghost,
   Ghost activation at height 1, and evidence that both consensus-readiness
   flags may be set true. Deferral is prohibited.
5. Replace the rehearsal genesis timestamp and address.
6. Complete clean-runner tests and required independent reviews for every
   changed consensus surface.
7. Record the reviewed source commit. The worktree must contain no unexplained
   files or edits.

## Canonical generation

Set every reviewed source constant except
`MAINNET_PARAMETER_MANIFEST_SHA256`. Confirm `status` reports only a
`parameter_manifest_*` blocker. Then render the exact bytes to stdout:

```bash
umask 077
python wepo-blockchain/scripts/wepo_mainnet_release_gate.py render-manifest \
  > MAINNET_PARAMETER_MANIFEST.json
```

The CLI itself never writes a file. The explicit shell redirection above is the
operator-authorized creation step. If any non-manifest blocker remains, the CLI
exits `2`, writes nothing to stdout, and names every remaining decision blocker
on stderr.

Compute the raw-file digest:

```bash
sha256sum MAINNET_PARAMETER_MANIFEST.json
```

Place that lowercase 64-character digest in
`MAINNET_PARAMETER_MANIFEST_SHA256` in the same reviewed source commit. Do not
pretty-print, reorder, or add whitespace to the generated file afterward; raw
bytes are part of the release identity.

## Independent reproduction

From a clean checkout of the proposed freeze commit, the reviewer must:

1. run the complete Python, Rust, JavaScript, web, and desktop release matrix;
2. run `status --manifest MAINNET_PARAMETER_MANIFEST.json` and require exit `0`;
3. rerun `render-manifest` to a separate temporary path and require byte-for-byte
   equality with the committed manifest;
4. recompute SHA-256 and match the source constant;
5. match every value to `MAINNET_PARAMETER_FREEZE.md`, the genesis evidence,
   emission oracle, and feature-scope decision;
6. prove the full node starts only with the complete package and still rejects
   a one-byte manifest change, a rehashed semantic change, and a changed policy
   or activation flag;
7. sign the release `SHA256SUMS` off-host and retain the detached signature,
   reviewer identity, commit, logs, and UTC timestamps.

## Abort and restart conditions

Abort the ceremony for any unexplained diff, nonzero test, blocker, manifest
mismatch, missing review, or disagreement between code and documentation.

Any later change to consensus, genesis, transaction authorization,
cryptographic verification, emission, fork choice, P2P identity, or the frozen
manifest invalidates this evidence. Repeat the ceremony after the change. The
30-day public-release clock starts only after every separate readiness gate is
green and formal readiness acceptance is recorded; this ceremony alone never
starts it.
