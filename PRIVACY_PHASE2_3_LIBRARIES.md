# WEPO Privacy — Phase 2/3 Library & Approach Evaluation

Status: RECOMMENDATION, 2026-06-21. Decides the cryptographic backbone for graph
privacy (Layer 2) and amount privacy (Layer 3) from PRIVACY_DESIGN.md. Requires
owner sign-off because it **revisits the earlier "proven scheme now, zk-STARK
later" lean** — see §4.

## 1. The blunt finding

There is **no audited, production-ready, drop-in post-quantum library** for either
anonymity (linkable ring signatures / RingCT) or confidential amounts today. Both
candidate families are real but immature:

| Family | Examples | Status (2026) |
|---|---|---|
| Lattice RingCT / linkable ring sigs | MatRiCT, MatRiCT+, Lattice RingCT (L2RS) | **Academic** with reference code; no audited production library; niche tooling. |
| Transparent PQ proof systems (STARK) | Winterfell, Plonky3, libiop | Toolkits/libraries, **explicitly "not production-ready"/unaudited**; fastest-maturing ecosystem. |
| zkVM provers | RISC Zero, SP1 | STARK prover is PQ, **but** they wrap in a **Groth16/BN254 SNARK** (ECC + trusted setup) for cheap on-chain verification — **the on-chain verifier is NOT post-quantum.** |

Implication: whichever direction we pick, WEPO needs a **funded external audit**
before the privacy gate (`WEPO_FEATURE_PRIVACY`) comes off. This is an R&D track,
not a dependency we can install and ship.

## 2. The post-quantum trap in zkVMs

RISC Zero / SP1 look attractive (mature, RISC-V circuits), but they achieve cheap
on-chain verification by wrapping the PQ STARK in a **Groth16 proof on BN254** —
which adds ~100-bit ECC pairing security + trusted-setup assumptions. That makes
the *verifier* quantum-breakable. For WEPO to be genuinely PQ, the chain must
**verify the raw STARK directly** (larger proofs, higher verify cost), accepting
no SNARK wrap.

## 3. Two viable directions

**A. Lattice RingCT (Monero-style, post-quantum).** Decoy ring + linkable ring
signature + lattice range proof (MatRiCT-family).
- Pros: familiar UTXO/decoy model; closest to "proven privacy UX."
- Cons: only reference implementations exist; we'd be productionizing + auditing
  academic code ourselves; lattice params/soundness are subtle; smaller talent pool.

**B. STARK shielded pool (Zcash-Orchard-style, but transparent + PQ).** One
zk-STARK circuit proves, per spend: membership (I own a note in the set),
nullifier correctness (no double-spend), and balance + range (no inflation,
amounts ≥ 0) — verified as a **raw STARK** on-chain (no SNARK wrap).
- Pros: **transparent + post-quantum end-to-end**, no trusted setup; consolidates
  Layers 2 **and** 3 into one circuit; fastest-maturing tooling (Plonky3 /
  Winterfell-derived); larger ecosystem to draw reviewers/auditors from.
- Cons: larger proofs / higher verify cost than a SNARK; circuit engineering is
  specialized; still needs audit. This is the very zk-STARK work the v1 audit
  flagged as stubbed (`production_zk_stark.py`) — done **for real** this time.

## 4. Recommendation — direction B (STARK shielded pool)

Counter to the earlier "avoid STARK for now" lean, the post-quantum requirement
**forces STARK forward**: the "proven, non-STARK" options (Pedersen+Bulletproofs,
Monero CLSAG) are discrete-log and quantum-breakable, and the PQ alternative
(lattice RingCT) is *also* unaudited and more niche. So if we must do unaudited-
until-reviewed crypto either way, do it on the **transparent, PQ, fastest-maturing
stack** and get one well-scoped circuit audited.

- **Proving stack:** build on **Plonky3** (or a Winterfell-derived prover);
  Goldilocks/Mersenne field; FRI-based, no trusted setup.
- **On-chain verifier:** verify the **raw STARK** in the node (no Groth16 wrap),
  preserving end-to-end PQ.
- **Scope creep guard:** a fixed, minimal circuit (membership + nullifier +
  balance/range), not a general zkVM.

If the owner prefers UX continuity with decoy/ring semantics over the STARK route,
direction A is the fallback — but with the same audit cost and weaker tooling.

## 5. Non-negotiables (unchanged)

- No hand-rolled soundness crypto; build on a maintained library, audited before
  enabling.
- Privacy stays `503` until the chosen layer is real **and** audited.
- No Groth16/SNARK wrap on the consensus verifier (it breaks PQ).

## 6. Proposed path (after owner picks A or B)

1. **Spike:** stand up the chosen prover; implement a *range-proof-only* circuit
   (the simplest real piece) with a raw on-chain verifier, behind the flag, on a
   throwaway testnet. Measure proof size / verify time to confirm feasibility.
2. **Circuit:** add membership + nullifier (full shielded spend); define the
   nullifier/commitment consensus rules + canonical sighash coverage.
3. **Interop:** WASM-compile the prover for the wallet (`wepoSigner`); cross-
   runtime tests (JS proves, node verifies), mirroring the ML-DSA pattern.
4. **Audit:** scope and fund an external review of the circuit + verifier.
5. **Enable:** lift `WEPO_FEATURE_PRIVACY` per layer only after audit sign-off.

## 7. Honest interim (does not overclaim)

Until §6 lands, privacy = **Layer 1 only** (Dandelion++ + Tor, already shipped):
real network/metadata privacy. Amounts and the spend graph remain transparent.
Clients must not present transactions as amount-private or unlinkable yet.

## Sources

- MatRiCT (post-quantum RingCT): https://dl.acm.org/doi/10.1145/3319535.3354200
- Lattice RingCT v1.0 / L2RS: https://eprint.iacr.org/2018/379.pdf
- Winterfell (STARK, "not production-ready"): https://github.com/facebook/winterfell
- Plonky3 (PIOP/STARK toolkit): https://github.com/Plonky3/Plonky3
- RISC Zero security model (STARK→Groth16 wrap, ECC verifier): https://dev.risczero.com/api/security-model
