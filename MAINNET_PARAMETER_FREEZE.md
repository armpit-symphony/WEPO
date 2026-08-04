# WEPO Permanent Mainnet Parameter Freeze

> **Status update 2026-07-27:** Parameters are not frozen. Mainnet genesis is
> explicitly unfinalized in code and full-node startup refuses it. The final
> timestamp must be at least 30 full days after readiness acceptance under
> `MAINNET_READINESS_AND_RELEASE_POLICY.md`. The 400 WEPO bootstrap recipient
> or burn/distribution policy remains a blocking consensus decision. PoS and
> Ghost dispositions are owner-decided as mandatory `enabled` launch features,
> but their readiness flags remain unresolved. Ghost activation is source-set
> to height 1 and awaits formal manifest freeze and independent review.

Status: Draft for go/no-go review (Blocker 5 of MAINNET_GENESIS_RELEASE_CHECKLIST.md)
Date: 2026-07-28
Source of truth: values extracted from `wepo-blockchain/core/network_profile.py`
and `wepo-blockchain/core/blockchain.py` in the current readiness branch. This document
is the single canonical record; if code and this doc disagree, reconcile before
launch.

Freeze commit: pending; record the reviewed release-candidate commit at formal freeze.

## Machine-readable release gate

Full-node mainnet startup now evaluates the complete decision set through
`network_profile.mainnet_release_blockers()`. Setting only
`MAINNET_GENESIS_FINALIZED=True` cannot open mainnet. The gate also requires:

- a non-placeholder timestamp and quantum genesis address;
- `MAINNET_GENESIS_REWARD_POLICY` set to `burn` or
  `auditable_distribution`;
- `MAINNET_EMISSION_POLICY` set to `ceiling_only`,
  `redesigned_target_cap`, or `lowered_cap`, after the corresponding economics
  and oracle evidence are approved;
- positive coinbase maturity and a nonnegative node-local relay-fee rate;
- mandatory `enabled` dispositions for PoS and Ghost, each consistent with its
  consensus activation flag, plus a positive reviewed Ghost activation height;
- owner-confirmed `deferred` dispositions for RWA creation and messaging-key
  registration, each bound to a false consensus-readiness flag; and
- an exact `MAINNET_PARAMETER_MANIFEST.json` generated from
  `build_mainnet_parameter_manifest()`, whose raw SHA-256 is frozen in
  `MAINNET_PARAMETER_MANIFEST_SHA256`.

Allowed does not mean implemented. Current consensus implements
`auditable_distribution` for the genesis reward and `ceiling_only` for
emission. `burn`, `redesigned_target_cap`, and `lowered_cap` deliberately return
a `*_policy_not_implemented` blocker until their actual consensus behavior,
vectors, documentation, and review exist. A policy label alone can never clear
the gate.

Operators inspect the gate and generate canonical bytes with the read-only
`wepo-blockchain/scripts/wepo_mainnet_release_gate.py` CLI. `status` exits
nonzero while closed; `render-manifest` refuses every non-manifest blocker and
writes only to stdout. Follow
`docs/runbooks/MAINNET_PARAMETER_FREEZE_CEREMONY.md` for the reviewed workflow.

The manifest binds genesis, supply ceiling, release policies, timings, phase
lengths, minimum stake/collateral, and every collateral schedule. Startup and
the production-host verifier reject a missing manifest, invalid JSON, a byte
hash mismatch, or semantically changed content even when an attacker recomputes
the file hash. No finalized manifest exists yet; that absence is intentional
and remains a launch blocker.

The stable blocker codes are operational evidence. Retain their complete output
before freeze and retain an empty blocker result, manifest bytes, digest,
signature, release commit, and independent review when the decision package is
eventually accepted.

> Rule: no accelerated `test`-profile values (15s blocks, reduced collateral,
> compressed activation) may appear in mainnet. All values below are the
> `mainnet` profile.

## Decisions recorded (2026-06-20)

Owner decisions captured for the items below (final go/no-go still required):

- **Supply:** the headline cap **69,000,003 WEPO is authoritative and fixed**.
  Consensus clamping enforces it for any PoW/PoS mix (see §3); independent
  recomputation and review remain required before formal freeze.
- **Genesis timestamp:** left **set-at-launch** (see §9). It is not fixed until
  every blocker is green. `PRODUCTION_MODE` is already `True` and is not a
  launch-day toggle; mainnet remains closed by the complete release gate.
- **Disable-at-launch scope:** **confirmed as recommended** (see
- **Mandatory consensus features:** PoS with external validator signing and
  Ghost transfers must be `enabled` at launch; deferral is prohibited. Their
  remaining qualification gates do not become optional.
- **Ghost activation:** height **1**, the first post-genesis block. This makes
  Ghost available from launch without placing ordinary transactions in the
  genesis block. The value is hash-bound into the parameter manifest.
  MAINNET_V1_LAUNCH_SCOPE.md). Gating is enforced in code (commit 1a547b1).
- **Seed nodes / bootstrap:** **not yet provisioned** — recorded as open (see §10).

## 1. Network identity

| Parameter | Value | Source |
|---|---|---|
| Protocol version | `70001` | blockchain.py:44 `WEPO_VERSION` |
| Network magic | `b'WEPO'` | blockchain.py:45 `NETWORK_MAGIC` |
| Default P2P port | `22567` | blockchain.py:46 `DEFAULT_PORT` |
| Network name | `mainnet` | network_profile.py `_mainnet_profile` |
| Coin (atomic units) | `100000000` (1 WEPO = 1e8) | blockchain.py:47 `COIN` |
| Max block size | 2 MiB | blockchain.py:48 `MAX_BLOCK_SIZE` |
| Max future block drift | 2 h | blockchain.py:49 |

**DECISION-REQUIRED:** `NETWORK_MAGIC = b'WEPO'` is generic and short. Confirm it
is intentional for mainnet (4 bytes is fine; just freeze it knowingly). Confirm
there is no separate numeric chain-id required by any client.

### 1.1 Proof-of-work byte contract (corrected 2026-08-01)

The Argon2id input for a PoW header is frozen for review as the following exact
byte sequence; every numeric field is unsigned little-endian:

```text
u32(version) || bytes32(prev_hash) || bytes32(merkle_root)
|| u64(timestamp) || u32(bits) || u32(nonce) || ASCII("pow")
```

The salt is the first 16 bytes of
`SHA256(ASCII("WEPO_POW_SALT") || pow_input)`. Argon2id uses version 19,
`time_cost=3`, `memory_cost=4096 KiB`, `parallelism=1`, and a 32-byte output;
the consensus PoW digest is `SHA256(argon2_output)`.

The timestamp field was corrected from unsigned 32-bit to unsigned 64-bit
before mainnet genesis finalization so it matches the canonical block-header
width. This is a consensus serialization change: all evidence produced using
the former 32-bit PoW preimage is diagnostic only and cannot qualify a release
candidate. `tests/vectors/state_transition_oracle_v1.json` and the independent
Node.js oracle pin the corrected bytes, Argon2id result, target checks, and
difficulty-boundary behavior. The current expanded fixture SHA-256 is
`131914bc399642de4c44bd7990dc9d22762c852e45844f7730438cc32c03e306`;
any consensus change must replace it. Formal parameter freeze must record a reviewed
commit containing this contract and newly generated candidate evidence.

## 2. Address format (changed by the spend-authorization hard fork)

| Parameter | Value | Source |
|---|---|---|
| v1 spendable address | quantum `wepo1q` + H(pubkey), 45 chars | address_utils.py `WEPO_QUANTUM`; commit 3a0cb53 |
| Legacy address | `wepo1` + sha256(seed), 37 chars | **invalid on mainnet** (no key binding) |
| Signature scheme | FIPS 204 ML-DSA-44, pinned `dilithium-py==1.1.0` | core/dilithium.py |

The core contains no RSA/signature simulator or permissive verification path.
Missing `dilithium-py` disables every public cryptographic entry point, and
both mainnet node construction and production-backend startup fail before
state initialization. See `tests/test_mldsa_fail_closed.py`.

**DECISION-REQUIRED:** confirm the hard fork to quantum-only addresses. Any
pre-fork balances/addresses are not carried into mainnet genesis.

## 3. Supply and emission

| Parameter | Value | Source |
|---|---|---|
| Total supply (hard cap) | 69,000,003 WEPO | blockchain.py `SUPPLY_CAP` |
| Genesis bootstrap reward | 400 WEPO (**inside the cap**, D1) | network_profile.py:13 / blockchain.py |
| Pre-PoS phase supply | 6,900,000 WEPO (10%) | blockchain.py |
| Pre-PoS block reward | 6,900,000 / 131,400 ≈ 52.51 WEPO/block | network_profile.py:14 |
| PoW phases 2A–2D | 13,800,000 WEPO (nominal target) | blockchain.py |
| PoS / masternode era | 48,299,603 WEPO (fill-to-cap remainder) | derived |
| Blocks/year (9-min) | 58,440 | blockchain.py `BLOCKS_PER_YEAR_LONGTERM` |

**FREEZE BLOCKER - independent result (2026-08-01):** the table above contains
nominal allocation targets, not the terminal supply implemented by consensus.
The checked-in cross-runtime oracle derives these exact maxima:

| Implemented path | Exact WEPO |
|---|---:|
| Genesis plus every scheduled PoW subsidy | 20,710,356.39932800 |
| Complete paid PoS pool tail | 5,296,112.46785800 |
| Maximum implemented issuance | 26,006,468.86718600 |
| Unreachable capacity below the cap | 42,993,534.13281400 |

The PoS pool becomes zero at height 9,189,600, so the current schedule never
reaches or triggers the clamp. D1-D3 remain valid ceiling-safety decisions, but
D4 must settle ceiling-only versus redesigned/lowered emission before freeze.
See `docs/EMISSION_SCHEDULE_AUDIT.md`.


**DECISION (2026-06-20) — APPROVED & IMPLEMENTED (D1–D3):** 69,000,003 is the
fixed cap, guaranteed by **consensus-enforced hard-cap clamping**, not by the
phase schedule summing precisely.

- **D1 — genesis inside cap:** the 400 WEPO bootstrap is counted inside the
  69,000,003 total.
- **D2 — phases are height-bounded:** emission boundaries are by block height;
  the "3yr/6yr" labels are nominal (hybrid PoS makes calendar durations differ).
  Comments corrected (incl. the 58,400 → 58,440 fix).
- **D3 — hard cap clamp:** cumulative base-reward issuance (genesis + PoW + PoS)
  is clamped every coinbase so the network total can never exceed the cap; the
  final rewards truncate and, once exhausted, only fees are paid. Fee
  redistribution is not new issuance and is excluded from the cap.

**Why a clamp rather than a hand-tuned schedule:** the PoW/PoS block mix is
variable, so no fixed per-block schedule can sum exactly to a target. The clamp
makes 69,000,003 an exact ceiling regardless of the mix. It reaches that ceiling
only if qualifying scheduled issuance is large enough.

**Issuance model — distribution-only (owner decision 2026-06-20).** Every block
mints via at most two paths, both clamped to the cap in this order:
1. **Coinbase base reward** — genesis bootstrap, or the PoW block subsidy. **PoS
   blocks mint NO coinbase base reward**; the PoS forger earns through the staking
   distribution, and its coinbase carries only the fee share.
2. **PoS reward pool** — minted via `distribute_staking_rewards()` to stakers +
   masternodes, once per block above PoS activation. Split 60% stakers / 40%
   masternodes, satoshi-conserving, with an empty side's share rolling to the
   other so the full clamped pool is always paid out (no dead coins).

This closes a prior **double-mint** (the PoS coinbase used to pay a base reward on
top of the distribution) and a **cap bypass** (`distribute_staking_rewards` minted
UTXOs outside any cap check).

**Implementation (blockchain.py):** `SUPPLY_CAP`, `scheduled_coinbase_base()`,
`scheduled_pos_pool()`, `get_issued_supply()` (counts BOTH mint paths;
deterministic / reorg-safe, derived from the canonical chain),
`clamped_coinbase_base()`, `clamped_pos_pool()`. The coinbase clamp is applied in
`create_coinbase_transaction()` and **enforced as a consensus rule in
`validate_block()`** (a coinbase may mint at most clamped-base + this block's
fees); the PoS pool clamp is applied in `calculate_staking_reward_entries()`.
<!-- Superseded pre-oracle reconciliation text retained for decision history:
Reconciliation gaps noted previously (the ~7,919 WEPO `TOTAL_POW_SUPPLY` mismatch)
are absorbed by the clamp. **Fee redistribution is fully conserved — no dead coins
— and continues even after the cap is exhausted.** Tests:
`tests/test_supply_cap.py`, `tests/test_fee_redistribution.py`.
-->
The stale nominal `TOTAL_POW_SUPPLY` constant now derives from exact atomic
phase rewards and lengths. The clamp remains consensus-enforced ceiling safety;
it does not currently activate because the complete schedule ends below the cap.
Fee redistribution is fully conserved and excluded from issuance. Safety tests:
`tests/test_supply_cap.py`, `tests/test_fee_redistribution.py`, and
`tests/test_emission_schedule_oracle.py`.

The independent evidence is pinned in
`tests/vectors/emission_schedule_v1.json`, recomputed without Python imports by
`tests/emission_schedule_oracle.mjs`, and bound back to mainnet production code
by `tests/test_emission_schedule_oracle.py`. One-unit and one-height tampering
fails closed.


## 4. Block timing

| Phase | Block time | Source |
|---|---|---|
| Initial 18 months (pre-PoS) | 360 s (6 min) | network_profile.py:110 |
| Long-term PoW | 540 s (9 min) | network_profile.py:111 |
| PoS | 180 s (3 min) | network_profile.py:112 |
| PoW hybrid | 540 s (9 min) | network_profile.py:113 |

## 5. Phase / activation heights

| Parameter | Value | Source |
|---|---|---|
| Pre-PoS duration | 131,400 blocks (18 mo @ 6 min) | network_profile.py:114 |
| PoS activation height | 131,400 | blockchain.py:126 (= TOTAL_INITIAL_BLOCKS) |
| Phase 2A length | 3 × 58,440 = 175,320 blocks | network_profile.py:132 |
| Phase 2B length | 6 × 58,440 = 350,640 blocks | network_profile.py:133 |
| Phase 2C length | 3 × 58,440 = 175,320 blocks | network_profile.py:134 |
| Phase 2D length | 3 × 58,440 = 175,320 blocks | network_profile.py:135 |
| Blocks/year (long-term) | **58,440** (9-min blocks) | network_profile.py:115 |

PoW phase rewards (post pre-PoS): 2A 33.17 → 2B 16.58 → 2C 8.29 → 2D 4.15
WEPO/block (network_profile.py:15-18).

### 5.1 PoS selection, slot, and signature byte contract

For height above activation, active stakes are sorted by
`(staker_address, stake_id)`. The selection digest is:

```text
SHA3-256(
  "WEPO_POS_VALIDATOR_SELECTION_V1\0"
  || u64_le(block_height)
  || bytes32(parent_hash)
  || u64_le(total_active_stake)
)
```

The digest is interpreted as an unsigned big-endian integer modulo total active
stake. The selected validator is the first sorted stake whose cumulative amount
is strictly greater than that point. A validator must control one or more active
stakes totaling at least the frozen minimum.

The first PoS slot is at least `BLOCK_TIME_POS` after the parent timestamp;
later slots are anchored to the last canonical PoS timestamp. The validator
address must equal the quantum address derived from its ML-DSA-44 public key.
The signed 32-byte digest is:

```text
SHA3-256(
  "WEPO_POS_BLOCK_SIGNATURE_V1\0"
  || u32_le(network_name_length)
  || ASCII(network_name)
  || u64_le(block_height)
  || WEPO_BLOCK_HEADER_V2_without_validator_signature
)
```

The signed block ID includes the validator signature. PoS headers carry
`bits=0` and `nonce=0`, contribute zero cumulative PoW, and count only as a
tie-breaker after equal PoW. The expanded independent fixture pins a real
stake-derived height-15 candidate and all of these bytes before formal freeze.

Protocol rewards and lifecycle transitions use the following consensus ordering
within a block:

1. Serialized transactions spend their referenced UTXOs.
2. Reward eligibility is evaluated from already-active stakes and masternodes
   whose protocol lock UTXO remains unspent after those transactions.
3. Reward history, per-participant totals, and synthetic reward UTXOs are
   persisted.
4. Stake and masternode lifecycle indexes apply confirmed creates and
   deactivations.

Consequently, a participant registered in a block is first eligible in the next
block, while a participant whose lock is spent receives no reward in that
deactivation block. Synthetic coinbase-provenance UTXOs are named
`pos_reward_reward_staker_{height}_{stake_id}` and
`pos_reward_reward_masternode_{height}_{masternode_id}`.

When both participant classes are eligible, 60% of the pool goes to stakers and
the exact remainder goes to masternodes; an empty side rolls its share to the
other. Staker allocation is amount-weighted in canonical
`(staker_address, stake_id)` order. Masternode allocation is equal in
`masternode_id` order, with one atomic unit of remainder assigned to each
earliest ID until exhausted. Every allocation must exactly conserve the pool.
The independent fixture pins registration, both allocation modes, two signed
deactivations, and final issued supply/state commitment through height 20.

## 6. Staking parameters

| Parameter | Value | Source |
|---|---|---|
| Min stake amount | 1,000 WEPO | network_profile.py:119 |
| PoS collateral floor | 100 WEPO | network_profile.py:121 |
| PoS collateral (initial → post-PoW) | 1000 → 600 → 300 → 150 → 100 WEPO | network_profile.py:123-131 |

## 7. Masternode parameters

| Parameter | Value | Source |
|---|---|---|
| Collateral floor | 1,000 WEPO | network_profile.py:120 |
| Collateral (initial → post-PoW) | 10000 → 6000 → 3000 → 1500 → 1000 WEPO | network_profile.py:122-130 |
| Collateral steps tied to | PoW halving phase end heights | network_profile.py `masternode_schedule` |

## 8. Fee policy

| Parameter | Value | Source |
|---|---|---|
| Default tx fee | 10,000 atomic (0.0001 WEPO) | blockchain.py:2986 |
| RWA creation minimum fee | 10,000 atomic | blockchain.py `RWA_CREATION_MIN_FEE` |
| Messaging-key registration minimum fee | 10,000 atomic | blockchain.py `MSG_KEY_REGISTER_MIN_FEE` |
| Exact-fee metadata settlement | zero outputs allowed; fee fully redistributed, not burned | blockchain.py `FEE_ONLY_METADATA_TX_TYPES` |
| Fee split — post-PoS | masternodes 60% / miner 25% / stakers 15% | blockchain.py:2047-2050 |
| Fee split — pre-PoS, masternodes present | masternodes 60% / miner 40% (no staker share) | blockchain.py:2041-2042 |
| Fee split — pre-PoS, no masternodes | miner 100% | blockchain.py:2044-2045 |
| Canonical settlement | blockchain fee settlement canonical; app-fee settlement explicit | README / canonical_fee_settlement_smoke.py |
| Minimum relay fee rate | **UNSET for mainnet** | network_profile.py `minimum_relay_fee_per_kb` |


RWA creation commits one globally unique `asset_id`, an owner address, and a
64-hex-character SHA-256 asset hash. Every input and output is owner-bound.
Reserved fields (`asset_id`, `owner_address`, `asset_hash`, `name`, and
`asset_type`) populate the primary index; all other canonical metadata is
stored as the deterministic extra-metadata object.

Messaging-key registration binds an exact 1,184-byte ML-KEM-768 public key and
1,312-byte ML-DSA-44 public key to the spending owner. The latest confirmed
registration for an address wins during canonical replay.

Both transaction types may legitimately have no transparent output when one
input exactly equals the minimum fee. Despite being fee-only metadata
transactions, their fees are fully redistributed through the canonical
coinbase; they are not burned. The independent height-23 fixture proves 30,000
atomic units charged, 30,000 redistributed, and zero issued-supply/UTXO delta.

A separate cumulative-work fork fixture commits different RWA assets and
messaging keys on both branches. The Python node first indexes the losing
height-15 branch, then atomically reconstructs the winning height-10 branch's
RWA and messaging tables when its cumulative work reaches 416 versus 256. The
independent Node oracle derives the same winner and verifies 20,000 atomic units
charged and fully redistributed on each branch.

The shielded fixture separately reconciles a signed 5-WEPO deposit as issued
supply minus transparent UTXOs, then confirms an anchored spend, two commitment
positions, one nullifier, and exact disconnect/reconnect reconstruction. Its
final Rescue-Prime root is
`f94d7acc96668781c2d6acb9fc76e257df44c8be486dba5a0d9772d99eef69c4`.
JavaScript independently reproduces transaction identities and sighashes; the
Sage-pinned Rescue reference independently reproduces both tree roots and proof
statement digests. This public-state evidence does not replace the required
external audit of the real Ghost prover/verifier.

**DECISION-REQUIRED:** confirm the phase-dependent split above is intended
(staker share only exists once PoS is active at height 131,400). Select and
publish the mainnet minimum relay fee in atomic units per 1000 canonical bytes.

Relay fee enforcement is implemented only at mempool admission; it is not block
consensus, and regression coverage proves a locally non-relayable transaction
can remain valid in a block. Mainnet refuses relay while the rate is unset. The
test profile defaults to zero only to avoid imposing production economics on
functional tests. Stake and masternode create/deactivate transactions now carry
ordinary declared fees with canonical change or principal-return layouts.
Legacy stake side-state unlocks can no longer synthesize spendable UTXOs.

The reproducible decision vector measures the committed one-input/two-output
ML-DSA wallet transaction at 8,160 canonical bytes. Its 10,000-atomic default
fee supports at most 1,225 atomic/kB. A round 1,000-atomic/kB candidate requires
8,160 atomic units and leaves 1,840 atomic units of headroom for that exact
shape; 1,226 atomic/kB already rejects it. The shipping transparent-send wallet
now asks the live node to converge a quote from the final fixed-size ML-DSA
shape, independently reproduces canonical size and the fee floor, displays the
exact fee/rate/total, and rechecks policy before decrypting and signing after
explicit approval. This still is not sufficient to freeze a rate by itself:
stake, masternode, RWA, messaging-key, and Ghost shapes are consensus-deferred
on mainnet and must adopt the same quote/verify/approve/recheck boundary before
any later activation. Intended-host load evidence is still required. Evidence is derived by
`wepo-blockchain/scripts/wepo_parameter_decision_evidence.py` and pinned in
`tests/vectors/mainnet_parameter_decision_evidence_v1.json`.

**Coinbase maturity - DECISION-REQUIRED:** mainnet has no configured depth.
The consensus mechanism is implemented: canonical UTXOs record creation height
and whether value was block-issued; immature issuance is rejected by mempool and
block validation and excluded from spendable wallet queries; restart/reorg replay
reconstructs that provenance. The deterministic test profile uses depth 1 only
for non-production functional testing. It is not a proposed mainnet value.

A conservative 100-block candidate corresponds to 600 minutes during the
six-minute pre-PoS phase and a 300-to-900-minute envelope under three-to-nine
minute hybrid pacing. The decision vector also pins 50- and 200-block cases.
Elapsed time is descriptive only; the final depth still requires review against
retained multi-host reorg, pool, and wallet usability evidence.

## 9. Genesis block — timestamp set at launch (DECISION 2026-06-20)

Decision: the genesis timestamp is deliberately deferred until readiness is
accepted and a date is chosen under the release policy. `PRODUCTION_MODE` is
already `True`; startup remains fail-closed through the complete release gate.

| Parameter | Current value | Launch action |
|---|---|---|
| Genesis timestamp | `1735138800` = 2024-12-25 15:00 UTC (placeholder, in the past) | **SET-AT-LAUNCH:** set `MAINNET_GENESIS_TIMESTAMP` (network_profile.py:12) to the real launch time at deploy. |
| `PRODUCTION_MODE` | `True` (blockchain.py) | Already enabled; not a readiness or launch toggle. |
| Genesis block hash / merkle root | derived at genesis | Record the final canonical values once the timestamp is set. |
| Genesis coinbase script | `b"WEPO Genesis - We The People"` | blockchain.py:1413 — confirm final message before launch. |

## 10. Seed nodes, bootstrap, checkpoints — OPEN (decision 2026-06-20: not yet provisioned)

A blockchain creates its own genesis and rules, but a freshly started node cannot
discover peers without at least one reachable, well-known node address baked into
the software. Those are **seed nodes** — always-on servers the project operates.
Without them, every new node is isolated and may fork its own genesis (this is the
exact "stuck at height 0 / own genesis" failure seen on the multi-machine testnet).

Current code state:
- mainnet has no hardcoded static or DNS peers;
- only the `test` profile defaults to loopback peers on ports 22567 and 22568;
- production configuration must explicitly set `WEPO_STATIC_PEERS` or
  `WEPO_DNS_SEEDS`, and `WEPO_REQUIRE_MAINNET_SEEDS=1` makes absence fatal;
- no production seed host or public DNS record is provisioned yet.

Open items (Blocker 7 — production infra):
- [ ] Operator runs ≥1 (recommended 2–3) always-on public nodes on port 22567.
- [x] Operator supplied the exact registrable domain `wepocoin.org` (reported
  2026-08-02).
- [ ] Record the registrar account owner, MFA/recovery controls, DNS provider,
  and selected API/seed FQDNs; independently verify operational control and
  publish the reviewed records. This item remains open and does not authorize
  DNS changes merely from the domain name being supplied.
- [ ] Use the owned `wepocoin.org` domain for reviewed DNS seed names, or ship
  reviewed static IPs. Do not publish the historical `wepo.network` placeholder
  or any unverified DNS name.
- [ ] Bootstrap distribution plan: how the genesis bootstrap (400 WEPO) / initial coins reach holders.
- [ ] Checkpoints: include or not — state the policy explicitly.

## Sign-off

| Role | Name | Approved (Y/N) | Date |
|---|---|---|---|
| Protocol / chain | | | |
| Backend | | | |
| Wallet | | | |
| Security | | | |
| Ops / deployment | | | |

No value above may change after sign-off without re-approval.
