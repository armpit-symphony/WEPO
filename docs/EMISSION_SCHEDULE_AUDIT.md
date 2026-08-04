# WEPO Emission Schedule Audit

Status: **blocking finding; replacement economics not approved**
Audit date: 2026-08-01
Scope: genesis, every PoW phase, the complete PoS halving tail, paused PoS
pools, and the 69,000,003-WEPO hard-cap clamp

## Result

The implemented clamp is a valid consensus **ceiling**: canonical issuance can
never exceed 69,000,003 WEPO, transaction fees do not count as new issuance,
and unpaid PoS pools do not consume cap headroom.

The implemented reward schedule cannot reach that ceiling. Even its
maximum-issuance path stops at **26,006,468.86718600 WEPO**. That path assumes:

- every height through 1,008,000 is PoW where a PoW subsidy is available; and
- every PoS reward pool after activation has at least one eligible recipient.

The remaining **42,993,534.13281400 WEPO** is unreachable. The PoS pool decays
to one atomic unit per block and becomes zero at height 9,189,600. Consequently,
the clamp never activates under the current schedule.

## Independent recomputation

All values below are atomic-integer calculations. Genesis is included in the
PoW-path total because it is issued through the coinbase base path.

| Component | Exact WEPO |
|---|---:|
| Genesis + all scheduled PoW subsidies | 20,710,356.39932800 |
| Complete PoS pool tail, if every pool is paid | 5,296,112.46785800 |
| Maximum implemented issuance | 26,006,468.86718600 |
| Advertised hard cap | 69,000,003.00000000 |
| Unreachable capacity | 42,993,534.13281400 |

Two other valid paths demonstrate why issuance is path-dependent:

| Scenario | Exact WEPO |
|---|---:|
| Every scheduled PoW subsidy; no eligible PoS recipients | 20,710,356.39932800 |
| Pre-PoS PoW, then all PoS blocks; every PoS pool paid | 12,196,512.46718600 |

The pre-PoS fixed reward is `52.51141552 WEPO`. Across 131,400 blocks it emits
`6,899,999.99932800 WEPO`, not exactly 6.9 million, because a constant atomic
reward cannot represent the fractional remainder.

## Corrected consensus arithmetic

The audit also found that binary floating-point construction made the Phase 2B
and 2C constants one atomic unit lower than their documented values:

| Phase | Previous runtime value | Intended exact value |
|---|---:|---:|
| 2B | 16.57999999 | 16.58000000 |
| 2C | 8.28999999 | 8.29000000 |

Because mainnet genesis is not finalized, the constants were corrected to exact
integer arithmetic before release. Blocks-per-year and all duplicated bridge
amounts now also avoid binary floating point.

## Reproducible evidence

- `tests/vectors/emission_schedule_v1.json` pins all mainnet inputs, phase
  totals, boundary rewards, tail heights, scenarios, and the exact shortfall.
- `tests/emission_schedule_oracle.mjs` independently recomputes the schedule in
  JavaScript without importing the Python blockchain.
- `tests/test_emission_schedule_oracle.py` binds those vectors back to the
  production Python constants and reward functions.
- One-atomic-unit and one-height tampering fails closed for rewards, phase
  boundaries, cap, totals, and the terminal PoS height.

## Required owner decision

Mainnet parameters must not be frozen until one coherent policy is approved:

1. **Keep 69,000,003 as a ceiling only.** Publish that actual terminal issuance
   is path-dependent and at most 26,006,468.86718600 under the present curve.
2. **Redesign emission to target the cap.** Specify the PoW/PoS allocation,
   treatment of unpaid pools, tail reward, and whether missed issuance carries
   forward. A positive tail can reach the cap only when qualifying payouts keep
   occurring.
3. **Lower the advertised cap.** This still does not create one guaranteed
   terminal supply unless path-dependent issuance and unpaid pools are also
   resolved.

Changing the curve is a material consensus and tokenomics decision. It requires
new vectors, full regression, independent review, and—after all other gates are
green—a fresh 30-day release clock. Until then, `MAINNET_GENESIS_FINALIZED`
remains `False`.
