# WEPO Whitepaper / Project Specification

*A decentralized, post-quantum, privacy-centric freedom coin — self-custodied money,
private messaging, and on-chain real-world assets.*

Status legend: **✅ Live** (in consensus/code now) · **🔒 Built but gated** (needs
independent audit before enabling) · **🕒 Planned** (placeholder / future track).

Confirmed genesis: **2026-09-02, 18:00:00 UTC** (Unix epoch `1788372000`).

---

## 1. Project scope ✅

WEPO is a decentralized, privacy-centric "freedom coin": self-custody, post-quantum,
hybrid Proof-of-Work → Proof-of-Stake Layer-1. Three pillars:

1. **Private value transfer** — self-custodied money with a post-quantum shielded layer.
2. **Private messaging** — end-to-end, post-quantum encrypted, blind-relay chat.
3. **Real-world assets (RWA)** — on-chain issuance of asset records anchored to the chain.

## 2. Consensus & blockchain technology ✅

- **Model:** UTXO-based Layer-1 (Bitcoin-style UTXO + coinbase), custom node.
  Network magic `WEPO`, P2P port **22567**.
- **Hybrid PoW → PoS:** PoS activates at **block 131,400 (~18 months post-genesis)** and
  runs **hybrid alongside PoW** until PoW emission ends at **block 1,008,000**, then continues alone.
- **Proof-of-Work:** **Argon2id** (memory-hard) — `time_cost=3, memory=4 MB,
  parallelism=1, 32-byte hash`. Memory-hardness resists ASIC dominance and keeps mining
  **CPU-friendly** (in-wallet mining is viable).
- **Post-quantum signatures:** consensus spend authorization uses **ML-DSA-44 (NIST
  FIPS 204)** — not ECDSA. Addresses are `wepo1q…`, bound to the public-key hash.
  Spend authorization is enforced at the consensus layer (client-side signing).

### Post-quantum posture (accuracy note — do not overclaim)

- **True today:** the **money layer** (signatures) and the **messaging layer** use
  NIST-standardized post-quantum crypto (**FIPS 203 / FIPS 204**). Signatures and message
  confidentiality are quantum-resistant now.
- **Not yet true:** the **privacy / shielded layer (Ghost transfers + Quantum Vault)** is
  built by design but **not yet audited or enabled** — its zero-knowledge verifier is
  currently a stub and is gated OFF.
- **Approved public framing:** *"Post-quantum secure at the signature and messaging layers
  today (NIST FIPS 203/204); the private-transaction layer is post-quantum by design and
  ships after independent audit."*

## 3. Cryptocurrency specifications / tokenomics ✅

| Parameter | Value |
|---|---|
| Name / ticker | **WEPO** |
| Max supply | **69,000,003 WEPO** (hard cap, consensus-enforced clamp) |
| Smallest unit | 1 WEPO = 100,000,000 base units (8 decimals) |
| Genesis bootstrap | 400 WEPO |
| Block time — PoW Phase 1 | 6 min (360 s) |
| Block time — PoW Phases 2A–2D | 9 min (540 s) |
| Block time — PoS | 3 min (180 s) |
| Blocks per year (long-term) | ≈ 58,440 |
| Address format | `wepo1q` + hash(public key) |
| Network magic / P2P port | `WEPO` / 22567 |

### Emission schedule (halving structure)

| Phase | Block range | Duration | Reward / block |
|---|---|---|---|
| Phase 1 (pre-PoS PoW) | 1 – 131,400 | ~18 mo | **52.51** WEPO |
| Phase 2A | 131,401 – 306,720 | 3 yr | **33.17** |
| Phase 2B | 306,721 – 657,360 | 6 yr | **16.58** |
| Phase 2C | 657,361 – 832,680 | 3 yr | **8.29** |
| Phase 2D | 832,681 – 1,008,000 | 3 yr | **4.15** |
| PoW ends | block 1,008,000 | — | 0 |

Rewards halve across 2A→2B→2C→2D. Supply split: **~20.7 M (30%) to PoW**,
**~48.3 M (70%) to PoS** (fill-to-cap remainder = 48,299,603 WEPO).

### Fee distribution

- **Pre-PoS:** 100% of fees → miner (or 60% masternodes / 40% miner if masternodes exist).
- **Post-PoS:** **60% masternodes / 25% miner-validator / 15% stakers.**
- Fees are fully conserved (no dead coins; rounding rolls to the miner).

### Collateral / minimums

- **Masternode collateral (decreasing schedule):** 10,000 → 6,000 → 3,000 → 1,500 →
  **1,000 WEPO** (floor). Single locked UTXO, owner-address-bound.
- **Staking minimum:** **1,000 WEPO** initially, decreasing per schedule to 100.

## 4. Wallet & functions ✅

Self-custody wallet (web + desktop). **BIP39 12-word recovery phrase**, client-side key
derivation and transaction signing (the server never holds keys). Functions: send /
receive, in-wallet mining, staking, masternode setup, RWA creation, private messaging, and
(gated) Ghost transfers + Quantum Vault. Recovery/restore on any device from the phrase.

## 5. Private chat technology ✅

End-to-end **post-quantum** encrypted messaging. Per-message **ML-KEM-768 (FIPS 203)** key
encapsulation → **AES-256-GCM**, signed with **ML-DSA-44**. The server is a **blind relay**
(stores only opaque ciphertext, never keys, cannot read content). **Click-and-use**
(device-local messaging key, no password). Trustless key discovery via **on-chain key
anchoring**; optional **Tor** routing for metadata privacy. Live and tested (two-wallet
E2E succeeded).

## 6. Mining ✅ / 🕒

**Argon2id PoW, CPU-friendly, in-wallet mining** (no ASIC required). Software = the WEPO
node/wallet miner (`getwork` / `submit` endpoints). **Mining pools: 🕒 placeholder** — none
at launch, to be added post-launch.

## 7. Staking & masternodes ✅

- **Staking:** minimum **1,000 WEPO**; activates at block 131,400; stakers earn **15%** of
  network fees post-PoS.
- **Masternodes:** collateral **10,000 WEPO** at launch (decreasing schedule), single locked
  UTXO, owner-address-bound; earn **60%** of network fees post-PoS. Masternodes are the
  intended relay/service tier.

## 8. Security ✅ / 🕒

- Post-quantum consensus signatures (ML-DSA-44); chain-enforced spend authorization
  (client-side signing).
- Hard-cap + intra-block double-spend consensus guards; fee conservation.
- Rate-limiting with proxy-aware client identity; HSTS / CSP hardening on the gateway.
- **Smart-contract auditing:** WEPO has no general smart-contract VM at launch. Framed as
  *"consensus-level asset rules + a planned independent security/crypto audit before privacy
  features enable"* — **not** "smart-contract audits."

## 9. Privacy — Ghost transfers & Quantum Vault 🔒

- **Ghost transfers** (private sends) = a **post-quantum transparent-STARK shielded pool**
  (confidential amounts + unlinkability). **Built in design, gated OFF, verifier not yet
  audited** — ships after external audit.
- **Quantum Vault** = shielded holding, same track.
- **Live privacy today:** metadata privacy via **Dandelion++** transaction relay + optional
  **Tor**, and end-to-end private messaging.
- **Approved framing:** *"Ghost transfers & Vault — post-quantum private transactions,
  launching after independent audit."* (Do not imply they are live on day one.)

## 10. Governance 🕒

**Placeholder.** No on-chain voting at launch. Masternode-weighted governance is the
intended model, deferred to a post-launch track. Public framing: *"community / masternode
governance — on the roadmap."*

## 11. Ecosystem 🕒 / 🔒

- **DEX / exchange:** 🕒 planned (BTC swaps + RWA trading tracks) — placeholder at launch.
- **RWA issuance:** ✅ on-chain asset *creation* is built (gated at launch); *trading* is later.
- **Block explorer:** 🕒 not built — placeholder (worth prioritizing; users expect one at launch).
- **dApp platform:** 🕒 placeholder.

## 12. Roadmap & milestones

- **Now → September 2026:** genesis rehearsal, seed-node deploy (AWS + VPS + optional this
  server), parameter freeze, security signoff.
- **Genesis:** **2026-09-02, 18:00:00 UTC** (epoch `1788372000`).
- **~Month 18 (block 131,400):** PoS + staking + masternode rewards activate.
- **Post-launch, audited tracks (in order):** Ghost transfers + Quantum Vault → block
  explorer → RWA trading / DEX → governance → mobile.
- **Block 1,008,000:** PoW emission ends; PoS-only issuance continues to the 69,000,003 cap.

---

*This document is derived from the canonical consensus source
(`wepo-blockchain/core/blockchain.py`, `network_profile.py`, `p2p_network.py`). Where a
feature is marked 🔒 or 🕒, public/marketing copy must not present it as live. Figures are
consensus-frozen for the v1 mainnet launch.*
