# Wallet Authorization and Recovery Security Audit

Date: 2026-08-01
Scope: canonical web wallet and the desktop package that embeds that frontend
Status: critical local findings fixed; release gate remains open

## Finding WLT-01: unsigned transaction was not bound to user intent

Severity: Critical
Disposition: Fixed and regression-tested

The wallet previously verified that the node-provided unsigned transaction
matched the node-provided sighash. That proves internal consistency, but a
malicious or compromised builder could return a different, self-consistent
transaction and obtain a valid wallet signature.

Before signing a standard send, the client now requires:

- the exact approved recipient and atomic amount;
- the fixed 10,000-atomic fee;
- version 1, transfer type, zero lock time, and no metadata/privacy/shielded data;
- one canonical payment output and at most one owner-only change output;
- canonical unsigned inputs, unique outpoints, final sequence, and the node
  builder's exact script markers;
- safe integer values and consensus input-count bounds.

Every attached ML-DSA signature is then verified locally. After submission, the
node's transaction ID must match the locally computed signed-transaction ID.

## Finding WLT-02: local vault password could reach legacy login

Severity: High
Disposition: Fixed and regression-tested

When local decryption failed, the wallet previously fell back to
`/api/wallet/login` with the supplied username and password. A mistyped local
vault password could therefore leave the device.

Wallet unlock is now local-only. An existing but undecryptable/incomplete vault
fails locally, and a device with no vault directs the user to recovery-phrase
restore. Tests prove neither path calls the login endpoint.

## Finding WLT-03: attacker-controlled vault KDF work factor

Severity: Medium
Disposition: Fixed and regression-tested

Version-2 vault parsing accepted arbitrary iteration counts above a floor. A
localStorage attacker could choose an extreme value and cause a CPU denial of
service before authentication.

The parser now requires the exact audited version-2 work factor (310,000),
validates fixed salt/IV/MAC encodings and Base64 ciphertext, and rejects
oversized serialized data before PBKDF2. The existing encrypt-then-MAC check
continues to reject wrong passwords and valid-shape ciphertext tampering.

## Evidence

- Full maintained Python blockchain suite: 143 passed.
- Full frontend suite: 35 passed.
- Focused wallet frontend matrix: 30 passed.
- Python wallet-vector and gateway contract matrix: 7 passed.
- Production frontend build: passed.
- JavaScript syntax and Biome checks: passed.
- Published JS/Python wallet vector remains byte-for-byte valid.
- Package content verification passed for executable
  `ee95c53dfae0fe85c31e7afecffd5f0cd7a48b242423fdf6522472d5a70df867`;
  source/packed frontend hashes, seven icon frames, and hardened wallet markers
  match.
- Intent-bound live transaction `461ee4ff...e4f6` settled exactly 123,456,789
  atomic units and retained txid, height, and balance after database restart.

Adversarial tests cover recipient, amount, fee, change owner, extra output,
metadata, lock time, shielded data, duplicate input, sequence, unsigned input
placeholder, pre-attached signature, unsafe integer, builder sighash, returned
txid, wrong password, missing local vault, malformed vault envelope,
attacker-selected KDF cost, ciphertext tampering, and oversized vault data.

## Remaining release work

This audit does not close the wallet readiness gate. Still required:

- human-visible clean-profile recovery and signed-send UI acceptance on final
  signed installed web and desktop release artifacts;
- independent wallet/security review of the release candidate;
- retained signed artifact hashes and clean-runner logs;
- resolution of all other protocol, economics, operations, and launch gates.

No release date should be set from this local evidence alone.
