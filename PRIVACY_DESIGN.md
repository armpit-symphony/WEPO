# WEPO Privacy Foundation — Design (v1)

Status: DESIGN, owner-directed 2026-06-21 ("true privacy + self-ownership,
quantum- and AI-resistant"; approach = proven primitives now, zk-STARK later).
Privacy ships disabled (`WEPO_FEATURE_PRIVACY=off`, HTTP 503) until each layer
below is real and externally audited. No soundness-critical crypto is hand-rolled.

## 1. Goal & threat model

Deliver private sends that hold up against a **quantum** adversary (can break
discrete-log / ECDSA) **and** an **AI/ML** adversary (can de-anonymize via chain
graph analysis, amount fingerprinting, and network/timing correlation).

A transfer leaks privacy on three independent channels; each needs its own
defense, and the weakest channel sets the real privacy level:

| Channel | What leaks | Defeated by |
|---|---|---|
| **Network/metadata** | IP, broadcast time, origin node | Dandelion++ + Tor/I2P |
| **Transaction graph** | who-pays-whom (input→output links) | decoy inputs + linkable ring signature |
| **Amounts** | value fingerprints / clustering | confidential amounts (commit + range proof) |

"Quantum" is handled by choosing post-quantum primitives on every channel that
uses crypto. "AI" is handled by making each channel statistically ambiguous, not
merely obscured — ML clustering must have nothing reliable to latch onto.

## 2. Why the current code is not the foundation

`wepo-blockchain/core/privacy.py` is ECDSA/SECP256k1 ring signatures + a
hand-rolled "bulletproof"/STARK. `production_zk_stark.py` "verifies" by checking
proof *shape* then `return True` (no FRI/soundness). These are discrete-log based
(quantum-breakable) and unaudited. They are the demo code that was disabled — the
foundation replaces them, it does not enable them.

## 3. Architecture — three layers, shipped independently

Privacy is additive: each layer is a real, separately-auditable guarantee, and a
transaction can opt into more layers over time. WEPO already carries
`Transaction.privacy_proof` and `Transaction.ring_signature` (preserved through
`to_dict`/`from_dict`), and `get_canonical_sighash` must commit to the new fields
so signatures bind to them.

### Layer 1 — Network/metadata privacy — IMPLEMENTED (2026-06-21)
- **Dandelion++** transaction propagation in `p2p_network.py`: a tx travels a
  random **stem** (single relay) before **fluff** (normal flood), so the
  broadcasting IP ≠ the origin. Defeats "first-node-to-announce = sender" AI
  heuristics. Per-epoch stem-relay selection (rotates every ~10 min), per-hop
  fluff probability, and an embargo failsafe that fluffs a stem tx if it is not
  relayed onward in time. Toggle `WEPO_DANDELION` (default on).
- **SOCKS5/Tor transport:** outbound P2P can be routed through a SOCKS5 proxy
  (`WEPO_SOCKS5_PROXY`, e.g. Tor `127.0.0.1:9050`); destinations are sent as
  domain names (no DNS leak, supports `.onion`). Run the node as a hidden service
  to also protect inbound.
- Tests: `tests/test_dandelion_privacy.py` (routing decisions, stem-vs-fluff,
  embargo failsafe, and the SOCKS5 handshake against a live in-process proxy).

### Layer 2 — Graph privacy / sender ambiguity (post-quantum)
- Each input references a **decoy set** of plausible UTXOs; a **linkable ring
  signature (LRS)** proves the spender owns *one* of them without revealing which,
  while a **key image** prevents double-spends.
- **Post-quantum**: use a vetted lattice- or hash-based LRS (e.g. MatRiCT-family
  or a Falcon/SPHINCS+-based construction) from an **audited library** — never
  hand-rolled. ML-DSA-44 is a signature scheme, not a ring construction, so it is
  not directly reusable here.
- Consensus changes: validate the ring proof + enforce key-image uniqueness in
  `validate_transaction`; canonical sighash commits to the decoy set + key image.

### Layer 3 — Amount privacy (post-quantum)
- Hide output values behind a **commitment** plus a **range proof** (value ≥ 0,
  no overflow) and a balance check (Σinputs = Σoutputs + fee) over commitments.
- **Honest quantum trade-off:** classic Pedersen + Bulletproofs are *not* PQ
  (binding rests on discrete log → a quantum adversary could forge amounts /
  inflate supply). PQ options: (a) **lattice range proofs** via a vetted library,
  or (b) **STARK range proofs** — a *bounded, well-scoped* reason to revisit zk
  (a transparent, PQ proof system) for this one job, with a real verifier + audit.
- Until a vetted PQ option lands, amounts stay transparent; Layers 1–2 still give
  strong network + graph privacy.

## 4. Quantum + AI coverage map

- **Quantum:** spends already use ML-DSA-44; Layers 2–3 use PQ ring/range proofs;
  no layer's security rests on discrete log.
- **AI:** L1 removes the network/timing signal; L2 makes the spend graph
  statistically ambiguous (clustering fails as decoy set grows); L3 removes amount
  fingerprints. An ML adversary is left with no reliable feature to correlate.

## 5. Integration points (WEPO specifics)

- `blockchain.py`: extend `get_canonical_sighash` to commit to decoy refs, key
  image, and amount commitments; add ring/range/key-image verification to
  `validate_transaction`; persist + index key images for double-spend prevention.
- `p2p_network.py`: Dandelion++ stem/fluff state machine in `broadcast_transaction`.
- Wallet (`wepoSigner.js` + `WalletContext.js`): decoy selection, ring signing,
  commitment/range-proof generation (via the same audited library compiled to WASM).
- Keep the `WEPO_FEATURE_PRIVACY` gate; flip per-layer only after audit.

> **Phase 2/3 backbone:** the post-quantum library evaluation
> (`PRIVACY_PHASE2_3_LIBRARIES.md`) found no audited PQ privacy library exists, and
> recommends a **transparent STARK shielded pool** (raw on-chain verification, no
> SNARK wrap) over lattice RingCT — which *revisits* the "zk-STARK later" lean.
> Awaiting owner pick (direction A lattice RingCT vs B STARK) before any L2/L3 code.

## 6. Phased plan

1. **Phase 1 — metadata privacy:** Dandelion++ in `p2p_network.py` + SOCKS5/Tor
   transport + tests. Real privacy value, no soundness crypto. **DONE 2026-06-21.**
2. **Phase 2 — graph privacy:** integrate a vetted PQ LRS lib; decoy selection;
   key-image consensus rules; sighash + validation; cross-runtime (JS↔Py) tests.
3. **Phase 3 — amount privacy:** integrate a vetted PQ range-proof lib (lattice,
   or scoped STARK); commitment balance rules; tests.
4. **Phase 4 — enable:** external audit per layer, then lift the 503 gate.

## 7. Non-negotiables

- No hand-rolled soundness-critical crypto; only vetted/audited libraries.
- Privacy stays 503 until the relevant layer is real **and** audited — we never
  advertise a guarantee the chain does not enforce.
- Every layer ships with consensus-level tests (forgery rejected, double-spend
  rejected, balance enforced) before its gate is lifted.

## 8. Related

- Messaging (separate track): `quantum_messaging.py` already exists; private
  messaging should reuse Layer 1 transport + PQ E2E encryption (own design doc).
- RWA *creation* (separate track): make issuance on-chain (currently a DB record).
