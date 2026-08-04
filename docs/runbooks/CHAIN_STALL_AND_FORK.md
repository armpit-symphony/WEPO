# Chain Stall and Fork Investigation

## Trigger

Open an incident when block age exceeds the reviewed consensus threshold,
trusted nodes disagree on height/tip/supply, reorg depth exceeds policy, block
rejections spike, or a node cannot catch up after restart.

## Immediate safety

1. Declare the incident and preserve timestamps.
2. Fence validator signers and automated block production if equivocation or
   divergent consensus is possible. Do not delete keys or state.
3. Keep public read APIs available only if their status remains truthful. Pause
   transaction submission when canonical state is uncertain.
4. Do not restart every node simultaneously, clear databases, force checkpoints,
   lower difficulty, edit tables, or manually select a tip.

## Collect before changing state

From at least three independent failure domains record:

- release/parameter/genesis hashes;
- height, tip, latest block timestamp, supply, consensus type, peer count,
  mempool count/bytes, and recent block headers;
- static/DNS seed resolution and established peer endpoints;
- database `quick_check`, disk/RAM/time synchronization, service restarts, and
  rejection/reorg logs;
- signer maximum authorized height and anti-equivocation `quick_check`, without
  copying the validator private key.

Create verified online backups before any repair attempt.

## Classify

- **Isolation:** one node lacks healthy peers while independent nodes agree.
- **Production stall:** all trusted nodes share a tip and no valid next block.
- **Natural reorg:** nodes converge by cumulative work under the reviewed bound.
- **Consensus split:** valid-looking nodes persist on incompatible tips or state.
- **Data corruption:** a node fails integrity/replay or disagrees with its own
  canonical payload.
- **Signer incident:** conflicting authorization, stale state, timeout, or key
  compromise is implicated.

## Recovery

For isolation, restore reachability and allow normal locator/header/block sync.
For corruption, rebuild only from the validated canonical block sequence or a
verified backup, then catch up from trusted peers. For a consensus split, keep
affected production/signing paths fenced and escalate to protocol/security
owners; recovery requires a reviewed release or consensus decision, never a
local database edit. For signer incidents, follow
`VALIDATOR_KEY_COMPROMISE.md` and `docs/VALIDATOR_SIGNER_SECURITY.md`.

## Close

Require all intended nodes to converge on exact height, tip, supply, genesis,
and parameter hashes; database checks to pass; peer diversity to recover; and
no unexplained signer authorization to exist. Retain a timeline, root cause,
corrective actions, and a test that would have detected the incident sooner.
