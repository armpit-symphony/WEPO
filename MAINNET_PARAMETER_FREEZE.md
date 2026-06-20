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
| Total supply | 69,000,003 WEPO | blockchain.py:56 `TOTAL_SUPPLY` |
| Genesis bootstrap reward | 400 WEPO | network_profile.py:13 / blockchain.py:102 |
| Pre-PoS phase supply | 6,900,000 WEPO (10%) | blockchain.py:70 |
| Pre-PoS block reward | 6,900,000 / 131,400 ≈ 52.51 WEPO/block | network_profile.py:14 |
| Total PoW supply | 20,702,037 WEPO | blockchain.py:99 |

**DECISION-REQUIRED:** reconcile these constants against
`WEPO_FINAL_TOKENOMICS_OPTION_A.md`. Confirm genesis bootstrap (400) and the
PoS-era remainder sum to exactly `TOTAL_SUPPLY`; record the full issuance ledger.

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
| Blocks/year (long-term) | 58,400 (9-min blocks) | blockchain.py:73 |

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

## 9. Genesis block — MUST be set before launch

| Parameter | Current value | Status |
|---|---|---|
| Genesis timestamp | `1735138800` = 2024-12-25 15:00 UTC | **PLACEHOLDER — IN THE PAST. Must be reset to the real launch time.** |
| `PRODUCTION_MODE` | `False` (blockchain.py:117) | **Must be `True` for mainnet.** |
| Genesis block hash / merkle root | derived at genesis | Record the final canonical values once timestamp is set. |
| Genesis coinbase script | `b"WEPO Genesis - We The People"` | blockchain.py:1413 — confirm final message. |

## 10. Seed nodes, bootstrap, checkpoints — DECISION-REQUIRED (not in code)

- [ ] Seed node list + ownership (hostnames/IPs, who runs them).
- [ ] Bootstrap distribution plan (how the 400 WEPO genesis bootstrap / initial coins are handled).
- [ ] Checkpoints: include or not — state the policy explicitly.
- [ ] DNS seeds (if any).

## Sign-off

| Role | Name | Approved (Y/N) | Date |
|---|---|---|---|
| Protocol / chain | | | |
| Backend | | | |
| Wallet | | | |
| Security | | | |
| Ops / deployment | | | |

No value above may change after sign-off without re-approval.
