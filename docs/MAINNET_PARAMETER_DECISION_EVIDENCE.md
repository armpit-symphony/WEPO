# Mainnet Parameter Decision Evidence

Status: reproducible decision support; no mainnet parameter is approved by this
document.

Canonical JSON:
`tests/vectors/mainnet_parameter_decision_evidence_v1.json`

Reproduce it without importing production consensus code:

```bash
python wepo-blockchain/scripts/wepo_parameter_decision_evidence.py \
  --check tests/vectors/mainnet_parameter_decision_evidence_v1.json
```

The generator reads the committed cross-runtime wallet and emission vectors and
binds both source-file SHA-256 values into its output. Semantic tampering causes
the check command to exit nonzero.

## Relay-fee evidence

The representative committed transparent transaction has one ML-DSA input, two
outputs, and a canonical size of 8,160 bytes. The current wallet default fee is
10,000 atomic units (0.00010000 WEPO).

| Rate (atomic/kB) | Required fee | Default passes | Headroom |
|---:|---:|:---:|---:|
| 100 | 816 | yes | 9,184 |
| 1,000 | 8,160 | yes | 1,840 |
| 1,225 | 9,996 | yes | 4 |
| 1,226 | 10,005 | no | -5 |

A round **1,000 atomic/kB** is the strongest currently evidenced compatibility
candidate. It is not approved. The 8,160-byte vector proves only its own shape;
transactions with additional inputs or metadata are larger. A fixed 10,000-unit
wallet fee will eventually underpay any positive per-byte policy.

The shipping transparent wallet now calculates the exact fixed-size ML-DSA
signed shape without a private key, converges the node quote, reproduces the
canonical size and fee floor locally, displays fee/rate/total for explicit
approval, and rechecks live policy before decrypting and signing. Before freezing
a positive rate, multi-input coverage must remain green. Every other mainnet
shape (stake, masternode, RWA, messaging, or Ghost) is currently consensus-
deferred and must adopt that same boundary before a later activation.
Deferral closes mainnet admission; it does not close each deferred shape's
fee/signature size loop or provide evidence for later activation.
Release-host load evidence must also show the chosen
rate and P2P resource limits resist cheap mempool spam.

The 2-MiB division gives an upper bound of 257 representative transactions per
block before coinbase and block framing. It is not a throughput promise.

## Coinbase-maturity evidence

| Depth | Six-minute phase | Hybrid fastest (3m) | Hybrid slowest (9m) |
|---:|---:|---:|---:|
| 50 | 300 min | 150 min | 450 min |
| 100 | 600 min | 300 min | 900 min |
| 200 | 1,200 min | 600 min | 1,800 min |

A **100-block** depth is the conservative candidate carried into the evidence
vector. It is not approved. Consensus measures blocks, not time; the time values
only explain wallet usability.

Before selection, multi-host testing must retain the maximum observed honest and
fault-injected reorg depths across restart, partition, competing PoW, PoS
continuation, and signer-failover scenarios. Wallets and pools must display
immature value and refuse selection until the next-block spend height. The final
depth needs independent consensus and operations review.

## Emission feasibility

| Quantity | Exact WEPO |
|---|---:|
| Hard ceiling | 69,000,003.00000000 |
| Maximum qualifying issuance | 26,006,468.86718600 |
| Shortfall on maximum path | 42,993,534.13281400 |
| Issuance with no eligible PoS recipients | 20,710,356.39932800 |
| Shortfall with no eligible PoS recipients | 48,289,646.60067200 |

The current curve therefore implements a ceiling, not an exact terminal supply.
Its PoS pool reaches zero after height 9,189,599. Merely scaling the advertised
cap, changing a policy label, or relying on the final clamp cannot make an exact
target reachable.

An exact-target redesign must define and test all of the following:

- scheduled qualifying issuance totals at least the hard cap;
- unpaid/ineligible rewards have deterministic, reorg-safe treatment;
- every valid continuing-chain path eventually has a payable recipient;
- the final payout clamps exactly to remaining cap headroom;
- PoW/PoS mixing cannot double-mint or strand issuance;
- regenerated Python/JavaScript vectors cover maximum, minimum, empty-recipient,
  fork, restart, terminal-payout, and post-cap paths;
- independent monetary-policy and consensus review accepts the design.

If those properties are not desired, `ceiling_only` is coherent with current
code but explicitly amends the earlier statement that 69,000,003 must be issued
exactly. That amendment must be made by the owner and published truthfully.

## Decisions still required

1. Preserve the exact 69,000,003 target and authorize an emission redesign, or
   amend the policy to ceiling-only.
2. Approve a maturity depth after multi-host evidence; 100 blocks is the current
   evidence candidate.
3. Approve a relay-fee rate only after the transparent quote/approval boundary
   has intended-host evidence and every other enabled mainnet transaction shape
   adopts it or remains deferred; 1,000 atomic/kB is the current candidate.
4. Decide the auditable recipient and controls for the 400-WEPO genesis output,
   or authorize actual provable-burn consensus work.

None of these actions starts the 30-day release clock.
