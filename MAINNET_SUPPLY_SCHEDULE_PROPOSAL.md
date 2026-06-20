# WEPO Emission Schedule Correction — Proposal

Status: PROPOSAL — awaiting owner approval before any consensus constant changes
Date: 2026-06-20
Decision context: owner fixed the cap at **69,000,003 WEPO** (2026-06-20) and asked
that the emission schedule be corrected to match it.
Source: `wepo-blockchain/core/blockchain.py`, `wepo-blockchain/core/network_profile.py`

## 1. Goal

Total WEPO ever issued must equal **exactly 69,000,003** — guaranteed, not
approximately — across genesis + pre-PoS + PoW phases 2A–2D + the PoS/masternode
era.

## 2. Current model (as coded)

- One shared block-height counter; every block is `pow`, `pos`, or `hybrid`.
- `calculate_block_reward(height)` pays the PoW curve by height:
  genesis 400 → pre-PoS 52.51 → 2A 33.17 → 2B 16.58 → 2C 8.29 → 2D 4.15 → 0.
- `calculate_pos_reward(height)` pays `int(phase_reward * 0.33)` during 2A–2D,
  then 0 (fee redistribution only).
- Phase lengths use `blocks_per_year_longterm = int(365.25*24*60/9)` (9-minute
  cadence).
- Intended split (code comment): pre-PoS 6.9M (10%) + PoW 2A–2D 13.8M (20%) +
  PoS/MN 48.3M (70%) = 69.0M.

## 3. Findings (why it does not reconcile)

1. **Blocks/year is 58,440, not 58,400** (the code comment is wrong), so every
   long-term phase is larger than documented.
2. **Constant per-block rewards do not divide into round phase totals** — e.g.
   `6,900,000 / 131,400` is not an integer number of atomic units, so pre-PoS
   cannot emit exactly 6,900,000 with a single per-block value.
3. **Hybrid height ambiguity.** Phase end-heights assume a 9-minute cadence, but
   PoS adds 3-minute blocks to the *same* height counter. With both streams
   running, a phase's end-height is reached far sooner in calendar time, and the
   per-height curve over-emits relative to the intended per-phase totals.
4. **PoS emission during 2A–2D is uncounted** in the "20.7M PoW" figure, and the
   PoS reward uses a magic `0.33` rather than an exact ratio.
5. **No hard cap enforcement.** Nothing stops cumulative issuance from exceeding
   (or undershooting) 69,000,003. The `total_supply` stat (blockchain.py:4130)
   only sums PoW rewards by height — it ignores PoS rewards and fees, so even the
   reported number is wrong.
6. **Headline offset:** 6.9M + 13.8M + 48.3M = 69,000,000; +400 genesis =
   69,000,400, which is neither 69,000,000 nor the vanity cap 69,000,003.

Because the PoW/PoS block mix is **variable and non-deterministic**, no fixed
per-block schedule can be guaranteed to sum to an exact target. The total must be
guaranteed by enforcement, not by arithmetic on per-block rewards.

## 4. Decisions required from the owner

- **D1 — Genesis in cap?** Is the 400 WEPO genesis bootstrap counted inside the
  69,000,003 cap? (Recommended: yes, inside.)
- **D2 — Phase boundaries.** Confirm phases are bounded by block height (as
  coded) and accept that, with hybrid PoS, calendar durations differ from the
  "3yr/6yr" labels; or redefine boundaries by time/halving. (Recommended: keep
  height-bounded, fix the labels/comments to match.)
- **D3 — Emission curve vs cap.** Approve guaranteeing the total via a hard cap
  (below), with the phase curve only shaping issuance speed. (Recommended: yes.)

## 5. Recommended solution

### 5.1 Hard supply-cap enforcement (guarantees the exact total)

Track cumulative issuance and clamp every coinbase so the total can never exceed
the cap:

```
SUPPLY_CAP = 69_000_003 * COIN

# in coinbase construction, given already-issued total `issued`:
remaining = max(0, SUPPLY_CAP - issued)
reward    = min(scheduled_reward, remaining)   # truncate the final rewards
# PoS rewards clamped the same way; once remaining == 0, only fees are paid
```

This makes 69,000,003 exact by construction regardless of the PoW/PoS block mix.
Add a persisted `issued_supply` accumulator (or derive it from the UTXO/coinbase
ledger) so the clamp is deterministic across restarts and reorgs.

### 5.2 Target-driven phase allocation (shapes the curve, sums to the cap)

Assuming D1 = "genesis inside cap":

| Component | Target WEPO | Notes |
|---|---|---|
| Genesis bootstrap | 400 | fixed |
| Pre-PoS (131,400 blocks) | 6,900,000 | the 10% / 6.9M figure |
| PoW phases 2A–2D | 13,800,000 | the 20% figure |
| PoS / masternode era | **48,299,603** | remainder = 69,000,003 − 400 − 6,900,000 − 13,800,000 |
| **Total** | **69,000,003** | exact |

The PoS/MN remainder absorbs the vanity offset (48,299,603 rather than a round
48,300,000), so the components sum exactly. Per-block rewards are then derived as
`phase_target // phase_blocks`, with the cap clamp (5.1) absorbing all rounding
remainders at the tail of each phase.

### 5.3 Housekeeping fixes

- Correct the `58,400 → 58,440` blocks/year comment.
- Replace the PoS `0.33` magic factor with an exact ratio (e.g. `// 3`).
- Fix the `total_supply` stat to count genesis + PoW + PoS issuance consistently
  (or rename it to "pow_issued" if that is the intent).
- Update `TOTAL_POW_SUPPLY` / `TOTAL_SUPPLY` constants and
  `MAINNET_PARAMETER_FREEZE.md` §3 to the reconciled values.

## 6. Implementation plan (after approval)

1. Add `SUPPLY_CAP` + cumulative-issuance accumulator + clamp in coinbase
   creation (PoW and PoS), with reorg-safe accounting.
2. Re-derive phase per-block rewards from §5.2 targets.
3. Apply housekeeping fixes (§5.3).
4. Add `tests/test_supply_cap.py`: simulate emission to/after the cap and assert
   cumulative issuance == 69,000,003 exactly and never exceeds it, across a mixed
   PoW/PoS block sequence and across a reorg.
5. Update the parameter-freeze doc with final reconciled numbers.

No consensus constants will change until §4 (D1–D3) is approved.
