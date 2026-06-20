# WEPO Mainnet v1 — Launch Scope Freeze

Status: Draft for go/no-go review (Blocker 4 of MAINNET_GENESIS_RELEASE_CHECKLIST.md)
Date: 2026-06-20
Owner sign-off required: protocol/chain, backend, wallet, security

## Purpose

Lock exactly what ships in mainnet v1. Every feature is marked **launch**,
**disabled-at-launch**, or **post-launch**. A feature may only be **launch** if it
does not depend on lab-only accounting, demo/placeholder behavior, or incomplete
signing/verification. Dispositions below are recommendations grounded in the
2026-06 audit; the go/no-go meeting must confirm or override each one.

## Decision legend

- **launch** — shipped and enabled at genesis.
- **disabled-at-launch** — code present but gated off; not exposed in clients.
- **post-launch** — deferred to a later release.

## Scope table

| Feature | Disposition | Rationale / gating dependency |
|---|---|---|
| Permanent chain / node | **launch** | Consensus now enforces spend authorization (commit 3a0cb53). Requires parameter freeze (see MAINNET_PARAMETER_FREEZE.md). |
| Backend / API | **launch** | Canonical FastAPI backend. Rate-limit identity hardened (commit e281ebf). Must run behind nginx with `WEPO_TRUST_PROXY_HEADERS=1` + Redis-backed limiter for multi-worker. |
| Web wallet | **launch (blocked)** | Hard dependency: `WEPO-wallet` must implement client-side Dilithium keygen + signing (build-unsigned → sign → submit). Not shippable until that lands. |
| Desktop wallet | **launch (blocked)** | Same client-signing dependency as web wallet. |
| Mobile wallets (iOS/Android) | **post-launch** | Per WEPO_iOS_HANDOFF_DOCUMENT.md these are early-stage (months of work). Not in v1. |
| Masternodes | **launch** | Registration/deactivation migrated to client signing and tested. Collateral schedule frozen below. |
| Staking / PoS | **launch, dormant at genesis** | Code migrated to client signing. PoS activates at height 131,400 (~18 months post-genesis), so it is inert at launch by design — no separate enablement needed, but document the activation height publicly. |
| Privacy sends / Quantum Vault (zk-STARK) | **disabled-at-launch** | `production_zk_stark.py` verification contains "simplified … return True" shortcuts; shipping it would advertise a privacy guarantee the code does not enforce. Re-enable only after real verification is implemented and audited. |
| RWA asset + vault flows | **post-launch** | Depends on stable wallet/chain behavior first; not required for monetary launch. |
| RWA trading | **disabled-at-launch** | The WEPO leg is lab-mode accounting layered on live node balance, not true on-chain user settlement (Blocker 6). Must not handle real value until settled on-chain. |
| Governance | **post-launch** | Not security-reviewed for v1; depends on masternode set maturing. |
| Bitcoin integration (masternode relay / mixing) | **post-launch** | Active wallet BTC path is simplified, not production-grade signing/sync. Defer until a real indexer/relay is integrated. |
| Self-custodial BTC view (no relay) | **decision-required** | If shipped, it must be read-only/self-custodial with no placeholder relay endpoints exposed. Default recommendation: keep off until the BTC path is production-grade. |

## Hard launch dependencies (must be green before v1)

1. `WEPO-wallet` client-side Dilithium signing implemented and tested (web + desktop). Reference: `wepo-blockchain/scripts/wepo_accelerated_simulation.py`.
2. Address-format migration acknowledged: v1 addresses are quantum `wepo1q` + H(pubkey). Legacy `wepo1` = sha256(seed) addresses are invalid on mainnet (hard fork).
3. Parameter freeze approved (MAINNET_PARAMETER_FREEZE.md), including a real genesis timestamp (the current default is a past placeholder).
4. All **disabled-at-launch** features verifiably hidden in shipping clients and rejected/410 at the API, not merely hidden in the UI.

## Truthfulness checklist (Blocker 6 tie-in)

- [ ] No client surfaces privacy/Quantum Vault as live while zk-STARK verification is stubbed.
- [ ] No client surfaces RWA trading as live while the WEPO leg is lab accounting.
- [ ] No placeholder BTC init/sync/relay endpoints are exposed as if functional.
- [ ] Staging-only toggles (e.g. genesis flip `/api/mining/_toggle_genesis`) are removed or hard-gated out of production builds.
- [ ] Dashboards/status endpoints show live network values, not stale placeholders.
