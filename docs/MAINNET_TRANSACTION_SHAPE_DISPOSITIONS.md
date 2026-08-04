# Mainnet Transaction Shape Dispositions

Status: enforced in source; mainnet itself remains closed
Recorded: 2026-08-01

This is the authoritative inventory of transaction shapes that can affect WEPO
mainnet v1. It records both consensus admission and wallet fee-approval status
so an optional feature cannot become reachable by changing only a UI, backend,
or environment flag.

## Matrix

| Shape | Wire representation | Mainnet disposition | Consensus boundary | Fee quote / approval |
|---|---|---|---|---|
| Transparent transfer | `tx_type=transfer`, no shielded bundle | Launch-readiness | Admitted when ordinary transaction, value, signature, resource, and block rules pass | Implemented: node quote, local intent/sighash/size/floor verification, explicit approval, live-policy recheck before key decryption |
| Coinbase/reward | Coinbase-shaped `tx_type=transfer` | Protocol-only | Constructed and admitted only in the exact block coinbase position; never accepted as a mempool send | Not applicable |
| Stake create | `tx_type=stake_create` | Decision required; currently disabled | Rejected by builders, mempool validation, and block validation while `pos_consensus_ready=false` | Not complete; must use transparent-send-equivalent quote and approval before enablement |
| Stake deactivate | `tx_type=stake_deactivate` | Decision required; currently disabled | Same PoS/lifecycle readiness gate | Not complete; explicit fee field is not release acceptance |
| Masternode create | `tx_type=masternode_create` | Decision required; currently disabled | Same PoS/lifecycle readiness gate | Not complete; explicit fee field is not release acceptance |
| Masternode deactivate | `tx_type=masternode_deactivate` | Decision required; currently disabled | Same PoS/lifecycle readiness gate | Not complete; explicit fee field is not release acceptance |
| RWA creation | `tx_type=rwa_create` | Deferred | Rejected while `rwa_consensus_ready=false`; manifest binds `rwa_disposition=deferred` | Not complete; fixed anti-spam minimum is not a dynamic relay quote |
| Messaging-key registration | `tx_type=key_register` | Deferred | Rejected while `messaging_consensus_ready=false`; manifest binds `messaging_disposition=deferred` | Not complete; fixed anti-spam minimum is not a dynamic relay quote |
| Ghost/shielded transfer | `tx_type=transfer` with a shielded bundle | Decision required; currently disabled | Rejected unless Ghost readiness is true and a reviewed activation height has been reached | Not complete; wallet note/prover and fee-approval flow remain open |

Coinbase is listed separately even though it shares the `transfer` type because
its empty/synthetic input shape and block-only admission make it a distinct
consensus path. Ghost is listed separately because the shielded bundle adds a
separate activation and verifier boundary to the ordinary `transfer` type.

## Enforcement hierarchy

1. `NetworkProfile` readiness fields govern consensus admission. The shared
   transaction-shape validator is called by transaction, mempool, block, replay,
   and branch-validation paths.
2. Every affected local builder calls the same readiness predicate before any
   state or balance lookup.
3. The mainnet parameter manifest binds dispositions to readiness bits and the
   release gate rejects an enabled/not-ready or deferred/enabled mismatch.
4. Backend and frontend gates provide defense in depth and prevent disabled
   features from being advertised; they are not the consensus authority.
5. The test profile deliberately enables optional types so their consensus,
   reorg, state-oracle, and cryptographic behavior remains testable.

Regression coverage submits otherwise-valid, correctly signed RWA and
messaging-key transactions, then proves direct validation and mempool admission
fail when their profile readiness is false. It also proves all four signed PoS
lifecycle shapes fail the shared consensus boundary and all six optional
builders fail before state lookup on the mainnet profile.

## Activation rule

No deferred shape may be activated by an environment variable, API deployment,
or wallet release. Activation requires all of the following:

- an explicit reviewed consensus release commit;
- a matching disposition/readiness pair in the frozen parameter manifest;
- deterministic node quote plus wallet-side intent, size, fee-floor, approval,
  and live-policy recheck behavior for the exact shape;
- adversarial mempool, block, reorg, restart, and cross-runtime tests;
- intended-release-host performance and abuse evidence;
- independent security review appropriate to the feature; and
- a reviewed activation height or upgrade mechanism where applicable.

Because activation changes consensus or transaction authorization, it resets
the 30-day release clock under `MAINNET_READINESS_AND_RELEASE_POLICY.md`.
