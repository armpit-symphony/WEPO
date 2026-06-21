# WEPO Permanent Mainnet Parameter Freeze

Status: Draft for go/no-go review (Blocker 5 of MAINNET_GENESIS_RELEASE_CHECKLIST.md)
Date: 2026-06-20
Source of truth: values extracted from `wepo-blockchain/core/network_profile.py`
and `wepo-blockchain/core/blockchain.py` at the commit noted below. This document
is the single canonical record; if code and this doc disagree, reconcile before
launch.

Code reference commit: e281ebf (branch `wallet-lab-fixes-20260409`).

> Rule: no accelerated `test`-profile values (15s blocks, reduced collateral,
> compressed activation) may appear in mainnet. All values below are the
> `mainnet` profile.

## Decisions recorded (2026-06-20)

Owner decisions captured for the items below (final go/no-go still required):

- **Supply:** the headline cap **69,000,003 WEPO is authoritative and fixed**. The
  emission schedule must be corrected to sum exactly to it (see §3). A corrected-
  schedule proposal is pending owner approval before any constant changes.
- **Genesis timestamp / PRODUCTION_MODE:** left **set-at-launch** (see §9). Not
  fixed to a public date until every blocker is green, per the release checklist.
- **Disable-at-launch scope:** **confirmed as recommended** (see
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

## 2. Address format (changed by the spend-authorization hard fork)

| Parameter | Value | Source |
|---|---|---|
| v1 spendable address | quantum `wepo1q` + H(pubkey), 45 chars | address_utils.py `WEPO_QUANTUM`; commit 3a0cb53 |
| Legacy address | `wepo1` + sha256(seed), 37 chars | **invalid on mainnet** (no key binding) |
| Signature scheme | Dilithium2 (NIST ML-DSA), pure-Python `dilithium-py==1.1.0` | core/dilithium.py |

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
makes 69,000,003 exact by construction regardless of the mix.

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
Reconciliation gaps noted previously (the ~7,919 WEPO `TOTAL_POW_SUPPLY` mismatch)
are absorbed by the clamp. **Fee redistribution is fully conserved — no dead coins
— and continues even after the cap is exhausted.** Tests:
`tests/test_supply_cap.py`, `tests/test_fee_redistribution.py`.

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
| Phase 2A length | 3 × 58,400 = 175,200 blocks | network_profile.py:115 |
| Phase 2B length | 6 × 58,400 = 350,400 blocks | network_profile.py:116 |
| Phase 2C length | 3 × 58,400 = 175,200 blocks | network_profile.py:117 |
| Phase 2D length | 3 × 58,400 = 175,200 blocks | network_profile.py:118 |
| Blocks/year (long-term) | **58,440** (9-min blocks; code comment says 58,400 — comment is wrong) | blockchain.py:73 |

PoW phase rewards (post pre-PoS): 2A 33.17 → 2B 16.58 → 2C 8.29 → 2D 4.15
WEPO/block (network_profile.py:15-18).

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
| Fee split — post-PoS | masternodes 60% / miner 25% / stakers 15% | blockchain.py:2047-2050 |
| Fee split — pre-PoS, masternodes present | masternodes 60% / miner 40% (no staker share) | blockchain.py:2041-2042 |
| Fee split — pre-PoS, no masternodes | miner 100% | blockchain.py:2044-2045 |
| Canonical settlement | blockchain fee settlement canonical; app-fee settlement explicit | README / canonical_fee_settlement_smoke.py |

**DECISION-REQUIRED:** confirm the phase-dependent split above is intended
(staker share only exists once PoS is active at height 131,400). Record the
minimum relay fee policy explicitly.

## 9. Genesis block — set at launch (DECISION 2026-06-20)

Decision: the genesis timestamp and `PRODUCTION_MODE` flip are **deliberately
deferred to launch day**, per the release-checklist rule not to fix a public date
until every blocker is green. These are launch-day actions, tracked here.

| Parameter | Current value | Launch action |
|---|---|---|
| Genesis timestamp | `1735138800` = 2024-12-25 15:00 UTC (placeholder, in the past) | **SET-AT-LAUNCH:** set `MAINNET_GENESIS_TIMESTAMP` (network_profile.py:12) to the real launch time at deploy. |
| `PRODUCTION_MODE` | `False` (blockchain.py:117) | **SET-AT-LAUNCH:** flip to `True` at deploy. |
| Genesis block hash / merkle root | derived at genesis | Record the final canonical values once the timestamp is set. |
| Genesis coinbase script | `b"WEPO Genesis - We The People"` | blockchain.py:1413 — confirm final message before launch. |

## 10. Seed nodes, bootstrap, checkpoints — OPEN (decision 2026-06-20: not yet provisioned)

A blockchain creates its own genesis and rules, but a freshly started node cannot
discover peers without at least one reachable, well-known node address baked into
the software. Those are **seed nodes** — always-on servers the project operates.
Without them, every new node is isolated and may fork its own genesis (this is the
exact "stuck at height 0 / own genesis" failure seen on the multi-machine testnet).

Current code state:
- `wepo-blockchain/core/p2p_network.py:130` hardcodes DNS seeds
  `seed1.wepo.network`, `seed2.wepo.network`, `seed3.wepo.network` — these
  **do not resolve to anything yet** (placeholders).
- Static seed fallback defaults to `127.0.0.1:22567` (local/test only).

Open items (Blocker 7 — production infra):
- [ ] Operator runs ≥1 (recommended 2–3) always-on public nodes on port 22567.
- [ ] Point `seed{1,2,3}.wepo.network` DNS at those hosts, or ship their static IPs.
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
