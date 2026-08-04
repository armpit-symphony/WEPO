# Security Disclosure Runbook

## Intake

Publish one monitored private security contact before release. Acknowledge a
report without confirming exploitability, requesting production exploitation,
or asking the reporter to transmit private keys, mnemonics, customer data, or
unredacted environment files.

Create a restricted case containing reporter contact preference, received time,
affected version/hash, reproduction summary, potential impact, and disclosure
expectation. Preserve the original report and record every access.

## Triage

Assign protocol, wallet, backend, deployment, and privacy owners as applicable.
Classify at least:

- critical: unauthorized value creation/spend, consensus split, key extraction,
  remote code execution, or signer bypass;
- high: reliable denial of network, authentication/rate-limit bypass with
  material impact, sensitive-data exposure, or release-signing compromise;
- medium/low: bounded availability, hardening, or low-impact information issues.

Critical/high reports trigger incident handling, release freeze, and assessment
of whether users/operators need immediate protective action. Do not suppress a
known exploitable issue to preserve a release date.

## Fix and verification

Use a private, access-controlled branch when premature publication increases
risk. Add a regression that fails before the fix and proves the security
boundary afterward. Re-run consensus vectors, wallet cross-runtime vectors,
full tests, clean builds, artifact signing, deployment verification, and any
affected rehearsal. Independent review is required for consensus,
cryptographic, wallet-secret, or signer changes.

Any consensus/cryptographic release-candidate change resets the readiness soak
and 30-day clock. Preserve hashes and a sanitized decision record.

## Disclosure

Coordinate a factual advisory after patched artifacts and operator instructions
exist, unless active exploitation requires earlier warning. Credit the reporter
according to preference. State affected/fixed versions, impact, required action,
and verification hashes without publishing unnecessary weaponization details.

Never promise a bounty, legal safe harbor, embargo duration, or confidentiality
unless the authorized owner has approved that policy.
