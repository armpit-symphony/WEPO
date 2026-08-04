# WEPO Mainnet v1 — Release Candidate Scope (Not Yet Frozen)

> **Status update 2026-07-28:** There is no release date. The readiness gates
> and 30-day post-readiness clock in `MAINNET_READINESS_AND_RELEASE_POLICY.md`
> supersede older schedule language. Client-side ML-DSA signing is implemented
> and tested; it is no longer the stated hard blocker. Mainnet genesis remains
> deliberately unfinalized and the node refuses to start it.
>
> PoS block authentication now uses canonical, domain-separated ML-DSA
> signatures through a fail-closed external signer boundary. Mainnet PoS
> remains fail-closed while qualification is incomplete. Protocol v3,
> signer-only cold-key stake authorization,
> public vectors, a local three-node partition/reorg rehearsal, and a pinned
> separate-user Debian deployment rehearsal pass. Intended-release-image and
> extended multi-host qualification plus independent audit remain.
>
> **Owner decision 2026-08-02:** PoS with external validator signing and Ghost
> privacy transfers are mandatory at mainnet v1 launch. Deferral is prohibited.
> The
> fail-closed Python boundary, complete Rust verifier, honest proof integration,
> 4-spend/2-output layout, transaction-bound STARK public inputs, and inactive
> persistent/reorg-safe consensus state now exist. Resource/fuzz testing, wallet
> wiring, a reviewed activation specification, and independent audit remain.

Status: Scope CONFIRMED 2026-06-20 (owner confirmed the dispositions below); final go/no-go still required
Date: 2026-07-28
Owner sign-off required: protocol/chain, backend, wallet, security, operations

> Current policy: every optional surface defaults off in both backend and
> frontend deployment examples. For on-chain transaction types, network-profile
> consensus-readiness flags are authoritative: disabled types are rejected during
> mempool and block validation even when a correctly signed transaction is
> submitted directly. Backend request gates and frontend build gates provide
> additional defense and prevent disabled features from being presented as live.
> BTC gating covers address proxying, relay, demo market rates, simulated
> liquidity, and swap routes—not only the final swap action.
>
> These are hard locks on mainnet, not production activation switches: feature
> environment flags are honored only by explicit test/staging profiles in both
> API layers and the frontend build configuration.
>
> On-chain, owner-bound RWA creation and spend-key-bound messaging now exist,
> but both remain optional until their own release acceptance and deployment
> privacy requirements are approved. RWA trading, BTC integration, mobile,
> dApp, and governance remain separate tracks. Ghost remains fail-closed until its
> independent audit, resource/fuzz closure, wallet/prover integration, pinned
> audited verifier artifact, and activation specification are all complete; all are launch blockers.

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
| Permanent chain / node | **launch-readiness gate** | Consensus enforces spend authorization and canonical wire/resource limits. Mainnet remains unavailable until parameter freeze, full regression, multi-node rehearsal, and external review are complete. |
| Backend / API | **launch-readiness gate** | Canonical FastAPI backend. Production requires trusted-proxy configuration, Redis-backed rate limiting with `WEPO_REQUIRE_REDIS_RATE_LIMIT=1`, and deployment rehearsal. |
| Web wallet | **launch-readiness gate** | Client-side ML-DSA keygen/signing, local recovery, atomic vault rollback/rotation, canonical quantum-address validation, and exact decimal gateway forwarding have automated coverage. A controlled live signer/gateway/node send and restart persistence now pass with retained evidence. Interactive installed-app, UX, and production rehearsal acceptance remain. |
| Browser mining lab | **disabled-at-launch** | The gateway flow is in-memory session telemetry, not consensus mining. Mainnet API and UI hard-lock it off; real miners use the node mining API. |
| Desktop wallet | **launch-readiness gate** | Canonical frontend hashes, all PE icon frames, zero shipped dependency findings, fail-closed transitive build-tool verification, and fail-closed Windows signing are automated. A trusted certificate/timestamped release, installed-app UX acceptance, and independent artifact review remain. |
| Mobile wallets (iOS/Android) | **post-launch** | Per WEPO_iOS_HANDOFF_DOCUMENT.md these are early-stage (months of work). Not in v1. |
| Masternodes | **decision-required; disabled in current mainnet profile** | Registration/deactivation uses client signing and is governed by the same PoS/lifecycle consensus disposition. Directly submitted lifecycle transactions are rejected while readiness is false. Parameter freeze, a quote/approval fee boundary, multi-node rehearsal, and operational acceptance remain required before enablement. |
| Staking / PoS | **mandatory launch-readiness gate** | Protocol v3 binds PoS and cold-key stake lifecycle authorization to the network, exact payload, owner-only value flow, fee ceiling, and persistent anti-equivocation/outpoint state. Directly submitted stake lifecycle transactions are rejected while readiness is false. Public vectors, adversarial tests, a local three-node partition/reorg rehearsal, and a pinned separate-user Debian rehearsal pass. Intended-release-image, quote/approval fee support, extended multi-host qualification, backup/failover drills, and independent audit remain mandatory. PoS may not be deferred from v1. |
| Ghost privacy sends / Quantum Vault | **mandatory launch-readiness gate** | The complete Winterfell verifier and inactive consensus state exist, but independent cryptographic audit, resource/fuzz closure, production wallet note/prover/recovery integration, a reviewed activation height, and release-host rehearsal are still required. Legacy `privacy.py` APIs are retired and `production_zk_stark.py` is not an acceptable verifier. Ghost may not be deferred from v1. |
| RWA asset creation | **post-launch; consensus-deferred** | Owner-bound on-chain issuance exists, but mainnet's source disposition is `deferred` and its consensus-readiness flag is false; the formal manifest schema binds both. Direct signed `rwa_create` transactions and local builder requests fail closed. A quote/approval fee boundary and separate acceptance are required before a later activation. |
| Messaging key registration | **post-launch; consensus-deferred** | Owner-bound on-chain key anchoring exists, but mainnet's source disposition is `deferred` and its consensus-readiness flag is false; the formal manifest schema binds both. Direct signed `key_register` transactions and local builder requests fail closed. A quote/approval fee boundary and deployment privacy review are required before a later activation. |
| RWA trading | **disabled-at-launch** | The WEPO leg is lab-mode accounting layered on live node balance, not true on-chain user settlement (Blocker 6). Must not handle real value until settled on-chain. |
| Governance | **post-launch** | Not security-reviewed for v1; depends on masternode set maturing. |
| Bitcoin integration (masternode relay / mixing) | **post-launch** | Active wallet BTC path is simplified, not production-grade signing/sync. Defer until a real indexer/relay is integrated. |
| Self-custodial BTC view (no relay) | **decision-required** | If shipped, it must be read-only/self-custodial with no placeholder relay endpoints exposed. Default recommendation: keep off until the BTC path is production-grade. |

## Hard launch dependencies (must be green before v1)

1. Web/desktop wallet release builds pass client-side ML-DSA, backup/restore, signing, fee/change, submission, and recovery acceptance tests.
2. Address-format migration acknowledged: v1 addresses are quantum `wepo1q` + H(pubkey). Legacy `wepo1` = sha256(seed) addresses are invalid on mainnet (hard fork).
3. Parameter freeze approved (MAINNET_PARAMETER_FREEZE.md), including a real genesis timestamp (the current default is a past placeholder).
4. PoS validator signing passes intended-release-host, multi-host partition/reorg, backup/fencing/failover, and independent-review gates.
5. Ghost passes wallet prover/note scanning/recovery, pinned verifier, activation, intended-host resource/failure, and independent cryptographic-audit gates.
6. All **disabled-at-launch** features verifiably hidden in shipping clients and rejected/410 at the API, not merely hidden in the UI.

## Truthfulness checklist (Blocker 6 tie-in)

- [x] No client surfaces Ghost/Quantum Vault as live before audit approval, wallet readiness, and consensus activation.
- [x] No client surfaces RWA trading as live while the WEPO leg is lab accounting.
- [x] No placeholder BTC init/sync/relay endpoints are exposed as if functional.
- [x] Staging-only toggles (e.g. genesis flip `/api/mining/_toggle_genesis`) are removed or hard-gated out of production builds.
- [x] Dashboards/status endpoints show live network values, not stale placeholders.

Code/build evidence: mainnet ignores enabling flags in the backend, node API,
and frontend. Consensus independently rejects every deferred on-chain type;
the complete mapping is frozen in
`docs/MAINNET_TRANSACTION_SHAPE_DISPOSITIONS.md`. Python launch-boundary tests, 35 Vitest tests, and the
optimized production build pass. Gateway status now fails closed if the node is
unavailable, reports canonical supply/height/consensus data, labels unavailable
telemetry instead of substituting zeros, and has no simulated hash rate or stale
genesis countdown. The in-memory browser-mining lab is hard-gated out of mainnet
API and UI surfaces. Release-artifact acceptance remains separate.
