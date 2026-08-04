# Validator Key Compromise Runbook

## Trigger

Treat suspected private-key disclosure, unexpected signer authorization,
anti-equivocation corruption/loss, unauthorized signer-host access, or an
unfenced duplicate signer as a critical incident.

## Immediate containment

1. Fence the signer host from every node and management path. Prove the fence
   from both sides; merely stopping one process is insufficient.
2. Disable the exact node sudo delegation and preserve the host for evidence.
3. Stop validator block/stake signing. Do not initialize a replacement with the
   old private key.
4. Record public validator identity, network, retained maximum signed height,
   authorization rows, database `quick_check`, release hashes, access logs, and
   timestamps. Never copy the private key into incident evidence.
5. Notify protocol/security owners and assess whether conflicting blocks or
   stake transactions were signed or broadcast.

## Decision paths

If the key was not exposed and only availability failed, use the reviewed
fencing/failover procedure in `docs/VALIDATOR_SIGNER_SECURITY.md`; restore the
complete encrypted key-plus-state safety unit, never the key alone.

If exposure is possible, retire the validator identity. A replacement requires
a consensus-supported, owner-authorized key/stake transition. Do not copy the
compromised key to a new host, clear anti-equivocation state, sign below the
retained height, or run old and new signers concurrently.

If the chain may contain conflicting signed blocks, keep signing fenced and use
`CHAIN_STALL_AND_FORK.md`. Local operator preference cannot choose the canonical
branch.

## Recovery acceptance

- old host and credential paths are provably fenced;
- no unreviewed signature occurred after the incident boundary;
- replacement identity/state transition is approved and independently reviewed;
- exact sudo, permissions, immutable hashes, backup, restore, and conflict
  refusal pass on the replacement;
- monitoring alerts on any request to the retired identity;
- incident evidence contains no secret key material.
