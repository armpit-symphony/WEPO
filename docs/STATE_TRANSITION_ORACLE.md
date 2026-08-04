# Independent State-Transition Oracle

Status: v1 public consensus-state replay proven; real Ghost prover/verifier external audit pending

## Purpose

`tests/state_transition_oracle.mjs` is an implementation-independent replay
oracle for canonical WEPO block JSON. It runs in Node.js and does not import the
Python blockchain implementation or its SQLite state. The committed fixture is
built by the real Python node from valid blocks and deterministic JavaScript
ML-DSA signatures; the oracle independently derives the final state.

This is stronger than reopening the same database with the same implementation,
but it is not yet a complete second consensus implementation.

## Current covered state

The v1 fixture and oracle independently verify:

- contiguous heights, parent links, monotonic timestamps, and canonical header IDs;
- exact cross-runtime Argon2id PoW hashes with pinned v19, time, memory,
  parallelism, salt-domain, output-length, and 64-bit timestamp parameters;
- leading-zero difficulty targets and seven exact retarget vectors covering
  both thresholds, phase selection, insufficient history, and ignored PoS headers;
- an end-to-end non-fixed-difficulty fork where the slow height-15 branch has
  work 256, the fast branch retargets to difficulty 2 at height 10 and has work
  416, and the shorter higher-work branch wins from a common genesis ancestor;
- exact winning-branch transparent, RWA, and messaging-key state after the Python
  node's real reorg, including removal of losing-branch index rows;
- canonical stake-lock derivation from a real owner-signed `stake_create`;
- exact SHA3-256 stake-weighted validator selection from height, parent, and
  total active stake;
- first-slot pacing, address/public-key ownership, domain-separated PoS signing
  bytes, deterministic ML-DSA verification, signed block ID, and zero PoW work;
- canonical owner-signed stake deactivation, exact lock-outpoint spending, and
  principal conservation;
- canonical owner-signed masternode registration/deactivation, designated
  collateral preservation, endpoint validation, and lifecycle derivation;
- reward eligibility after current-block spends, stake-weighted and
  masternode-equal integer allocation, 60/40 joint splitting, empty-side
  rollover, exact pool conservation, reward history, synthetic reward UTXOs,
  and issued supply;
- RWA asset-ID uniqueness, owner binding, SHA-256 commitment shape, reserved
  metadata handling, and exact derived index rows;
- ML-KEM-768/ML-DSA-44 messaging-key shape, owner binding, registration history,
  and latest-confirmed-registration-wins indexing;
- exact metadata minimum fees, canonical coinbase redistribution, and zero
  issued-supply/UTXO delta; these fee-only metadata transactions do not burn
  value;
- shielded value balance, proof-excluded canonical sighashes, proof-included
  transaction IDs, commitments, anchors, nullifiers, transparent/pool supply
  reconciliation, and disconnect/reconnect reconstruction;
- independently reproduced Rescue-Prime Merkle roots and bundle statement
  digests using the pure-Python implementation pinned to the upstream Sage
  reference vector;
- canonical transaction IDs and transaction Merkle roots;
- ML-DSA signatures and public-key-to-UTXO-owner binding;
- transparent input uniqueness, UTXO consumption, and output creation;
- coinbase placement and configured maturity;
- exact transaction fees and value conservation;
- final unspent supply, canonical UTXO rows, and a domain-separated state
  commitment.

The fixture contains genesis plus three deterministic PoW blocks and two real
signed transfers. Its final identities are:

- tip: `afcc19dfce1a2b1568c8f39361e5cfe89634792b096df451ea591f0bb3a37e41`;
- issued supply: `55753424656` atomic units;
- six unspent outputs;
- state commitment:
  `312715397b01131d59764b9a927795cefeee48067a9e602c4b15645b779b27ee`;
- fixture SHA-256:
  `131914bc399642de4c44bd7990dc9d22762c852e45844f7730438cc32c03e306`.

The fork scenario's independently selected winner is
`short_fast_retargeted` at height 10:

- tip: `a9046ff9ad2e6d76f142b6e9c2703e3c1390140bfbb767f7a78b02bfe177fbda`;
- cumulative work: `416`, versus `256` for the height-15 slow branch;
- winning asset `rwa_winning_branch` replaces losing asset
  `rwa_losing_branch`, and the winning messaging registration
  `3b923f41734011dc0ad6dc928929bac59d4507f16d78cf5c299ccda0c2a71bcd`
  replaces the losing branch's registration;
- each branch independently conserves its two 10,000-atomic metadata fees in
  canonical coinbase settlement;
- the losing tip remains indexed but noncanonical in the Python node; and
- Python adoption occurs only when the final winning branch block arrives,
  after which its RWA and messaging tables exactly match the winning history.

The PoS candidate scenario independently derives one active 100-WEPO stake from
the height-14 parent chain, then verifies:

- parent tip:
  `d1b9b7871ceac189ff8a3453b6cb255b57b75b5e41129530c5257ec14a3607f9`;
- selected validator: `wepo1q26e5e12b5a553b16d0a93e21b4f247cdf204cd2`;
- candidate height 15 and signed block ID
  `f922214f947e1fb5c824295ad5eabb4fc8462f2753749cd07aabd8c55a9f032a`;
- signing digest
  `2869043f8ddedadce54153aee50915376f7a85bffbd8efe7fcbb2e6da2993f94`;
- deterministic 2,420-byte ML-DSA signature and exact cross-runtime validity.

The accepted protocol lifecycle continues through height 20:

- the active stake receives the full `1,250,000,000`-atomic-unit pool at
  heights 15, 16, and 17;
- a real signed masternode registration at height 17 preserves its complete
  500-WEPO test-profile collateral UTXO and is not rewarded in its own block;
- at height 18, the jointly active stake and masternode receive exactly
  `750,000,000` and `500,000,000` atomic units (60/40);
- signed stake and masternode deactivations spend both protocol locks at height
  19, so neither participant receives a same-block reward; height 20 confirms
  continued ineligibility;
- masternode ID:
  `mn_wepo1q26e5e12b5a553b16d0a93e21b4f247cdf204cd2_1700000236`;
- registration transaction:
  `f2dda26bcf682a973146c1aa78d9556b283481ad3f4fc1c648490f2f541a2d08`;
- stake deactivation transaction:
  `20c4abd45aa2248b88b2ba834552a5a102b8f5fa7a31e6ec3ea1a39f4c0d9def`;
- masternode deactivation transaction:
  `39a6ae2674ba70cf96f823aab0b93ee01821544b2c48283aa220f5ca5a926cad`;
- height-20 tip:
  `2b33ebeb5cd8f330dbb7413e955c282a736011aa2c29bb613ac9710b7eeb3d14`;
- height-20 state commitment:
  `ef1ff04684d1c72752d31fc950e81a0e9b5e0d37f428e1ebcc93be92fa897702`.

The metadata continuation extends the same chain through height 23:

- height 21 confirms owner-signed RWA asset `rwa_state_oracle_001` with creation
  transaction
  `292a7d976df5771b50c100000482a774d703c5c3cbef6af3c7327d9c9a77c230`;
- heights 22 and 23 confirm two owner-signed messaging-key registrations, with
  the height-23 transaction
  `2c2f07b6111ad9641a9827dfe9d6ca4406deaf897b5398d2baf29e85420fec42`
  replacing the prior key under the deterministic latest-wins rule;
- all three 10,000-atomic-unit metadata fees are independently found in their
  canonical coinbase outputs: 30,000 charged and 30,000 redistributed;
- issued supply minus the final UTXO total is exactly zero; there is no accepted
  fee-burning path for these transactions;
- final tip:
  `61b997a6e92696fb768013031b722ff2a3f5f603777f99b88fd40c25fcf77d8f`;
- final state commitment:
  `06e115743454538252025ec209519637d229dfbce3dce2aa971d496e8b656706`.

The shielded scenario contains genesis plus two deterministic PoW blocks:

- height 1 confirms an owner-signed 5-WEPO transparent-to-shielded deposit;
- height 2 spends against the prior block's anchor, records one nullifier, and
  appends a second commitment;
- JavaScript independently reproduces both transaction IDs and canonical
  sighashes, enforces `inputs - outputs - value_balance = fee`, and reconciles
  issued supply as transparent UTXOs plus the 5-WEPO shielded pool balance;
- the Sage-pinned Rescue reference independently derives the height-1 root
  `db40b87d9ea4ec39a42f4fdf1e992fa791067e4bc68c19f070e58953df3ff974`
  and final root
  `f94d7acc96668781c2d6acb9fc76e257df44c8be486dba5a0d9772d99eef69c4`;
- it also reproduces both proof statement digests from the JavaScript-derived
  sighashes, anchors, nullifier, commitments, and value balances; and
- Python disconnects height 2 back to the exact one-commitment/no-nullifier
  prefix, then reconnects to byte-identical final indexes and root.

The fixture uses an explicitly audit-approved deterministic test double only to
exercise state transitions. It does not claim that the test double proves
knowledge or balance. Real proof validity and transaction binding are separately
exercised end to end by `tests/test_ghost_verifier_integration.py` through the
Python subprocess boundary and the complete Rust circuit.

## Reproduce

Generate the fixture:

```powershell
python tests\generate_state_transition_fixture.py `
  --output tests\vectors\state_transition_oracle_v1.json
```

Run the independent oracle:

```powershell
node tests\state_transition_oracle.mjs `
  tests\vectors\state_transition_oracle_v1.json
```

Run the contract and tamper tests:

```powershell
pytest -q tests\test_state_transition_oracle.py
```

The generator must reproduce a byte-identical fixture. The tests require the
oracle to reject changed transaction signatures, invalid maturity, changed
expected UTXO state, PoW parameter or nonce tampering, incorrect retarget
vectors, a forged live branch difficulty, a forged cumulative-work score, a
false fork winner, mismatched derived stake or masternode state, an early PoS
slot, a forged validator signature, a changed PoS signing digest, false final
stake or masternode status, changed registration outpoint evidence, changed
reward history, a forged same-block reward after both protocol locks were
spent, forged RWA index state, a false messaging latest-wins result or
registration history, altered metadata fee redistribution, a nonzero
issued-supply/UTXO delta, forged winning-branch RWA or messaging indexes,
false Python disconnect/reconnect evidence, forged shielded commitment rows or
canonical sighashes, false shielded reconnect evidence, altered Rescue roots,
and altered proof statement digests.

## State commitment

The oracle sorts unspent rows by transaction ID and output index, encodes them
as canonical UTF-8 JSON with recursively sorted keys, and hashes:

```text
SHA256(
  "WEPO_STATE_ORACLE_V1\0"
  || u32_le(payload_length)
  || canonical_utxo_json
)
```

The committed payload bytes are included in the fixture so another
implementation can reproduce the commitment without trusting either runtime.

## Scope deliberately outside this oracle

The independent public-state replay gate is covered for the current v1
consensus scope. This does not authorize Ghost activation or qualify a release
candidate by itself.

The remaining Ghost blocker is security assurance of the real cryptographic
implementation: an independent audit of the prover, verifier, circuit, artifact
pinning, and subprocess boundary, with all critical and high findings closed.
Ghost remains consensus-disabled and hidden until that separate gate is
approved.
