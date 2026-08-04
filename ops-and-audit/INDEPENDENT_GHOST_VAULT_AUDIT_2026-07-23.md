# WEPO Independent Ghost/Vault Audit - 2026-07-23

## Scope

Tracks requested in `AUDIT_HANDOFF.md`:

- Track A: mainnet security review around launch-critical consensus, custody, and deployment boundaries.
- Track B: Ghost Send disabled-state audit plus requirements for a future safe design.
- Track C: Quantum Vault disabled-state audit plus requirements for a future safe design.

This audit treats Ghost Send, Vault, messaging, RWA, and BTC relay/swap features as out of launch scope unless explicitly enabled for staging. The launchable product surface after these fixes is transparent WEPO wallet operations, canonical unsigned-build/local-sign transaction flow, mining/status reads, staking/masternode info, and read-only chain/explorer surfaces.

## Executive Result

Transparent-only public launch is conditionally supportable after operators configure production seed peers and Redis. Ghost Send and Quantum Vault are no-go for public launch and now remain disabled by default at gateway, node, UI, and deploy-script boundaries.

Operational conditions before launch:

- Set real mainnet P2P seeds through `WEPO_STATIC_PEERS` or `WEPO_DNS_SEEDS`.
- Keep `WEPO_REQUIRE_MAINNET_SEEDS=1` in production node service configuration.
- Run Redis and keep `WEPO_REQUIRE_REDIS_RATE_LIMIT=1` for public backend processes.
- Keep `WEPO_FEATURE_PRIVACY=0`, `WEPO_FEATURE_MESSAGING=0`, `WEPO_FEATURE_RWA=0`, and `WEPO_FEATURE_BTC=0` for v1 launch.

## Findings And Remediation

### Fixed: Consensus Value Creation

Before fix, a signed transaction could contain an oversized positive output offset by a negative output. `validate_transaction` compared only the algebraic output sum, which allowed value creation. Coinbase outputs had the same negative-offset problem.

Fix:

- `TransactionOutput` rejects non-integer, negative, and above-cap values at construction.
- Consensus validation rechecks output value shape before all value math, covering mutated/deserialized objects.
- Added regression coverage in `tests/test_consensus_value_invariants.py`.

Status: fixed and verified.

### Fixed: Additional Coinbase Issuance

Before fix, `validate_block` required transaction 0 to be coinbase but did not reject later coinbase transactions. Extra coinbases skipped normal UTXO/signature validation and could mint arbitrary value.

Fix:

- `validate_block` rejects any coinbase outside transaction index 0.
- Block fee accounting now validates non-coinbase transactions first and then uses recomputed fees for coinbase allowance.

Status: fixed and verified.

### Fixed: Placeholder Privacy Metadata In Consensus

Before fix, owner-signed transparent transactions with arbitrary `privacy_proof` or `ring_signature` fields were accepted. Those fields were not authorization, not verified privacy, and could mislead downstream surfaces.

Fix:

- Consensus rejects privacy fields while `PRIVACY_CONSENSUS_ENABLED = False`.
- This is hardcoded in consensus, not environment-driven.

Status: fixed and verified.

### Fixed: Server-Side Key Custody Routes

Before fix, node routes under `/api/quantum/wallet/create` returned private key material and `/api/quantum/transaction/create` accepted private keys for server-side signing on a parallel quantum chain.

Fix:

- Retired legacy node quantum wallet/status/transaction routes with HTTP 410.
- Removed parallel `QuantumWepoBlockchain` and `QuantumWallet` use from canonical node startup.
- Kept Dilithium implementation metadata route available.
- Node API now binds to `127.0.0.1` by default and no longer enables wildcard credentialed CORS.

Status: fixed and verified.

### Fixed: Legacy Bridge Deployment Exposure

Before fix, bridge-era deployment scripts could still publish `wepo-fast-test-bridge.py`, including placeholder Vault/Ghost surfaces.

Fix:

- `deploy-server.sh` and `upload-and-deploy.sh` fail closed immediately unless a deliberate legacy override string is set.
- Removed local absolute path references from those touched scripts.

Status: fixed and verified.

### Fixed: Messaging Registry Risk

The relay registry remains claim-based for first contact unless a recipient has an on-chain key anchor. That can misdirect first-contact messages to an attacker-controlled key.

Fix:

- `/api/messages*` is gated by `WEPO_FEATURE_MESSAGING=0` by default.
- Frontend messaging no longer auto-publishes keys or sends/fetches unless `REACT_APP_WEPO_FEATURE_MESSAGING` is explicitly enabled for staging.

Status: launch-gated. Future launch requires spend-key-bound registration or mandatory on-chain key anchors.

### Fixed: Launch Configuration

Before fix, mainnet timing and node defaults were not launch-safe.

Fix:

- Mainnet genesis timestamp set to `1788372000` (2026-09-02 18:00:00 UTC).
- `PRODUCTION_MODE = True` in consensus module.
- Mainnet P2P no longer defaults to localhost static peers or fake DNS seeds.
- Production node service example requires seed configuration and removes testing difficulty override.

Status: fixed and verified. Operators must configure real seed peers before launch.

### Fixed: Frontend Claims And Local Storage

Before fix, active Send flow claimed all WEPO transactions were private by default using zk-STARKs and ring signatures. Local encrypted storage used CryptoJS passphrase encryption without explicit authentication.

Fix:

- Send flow now labels transactions as transparent and states Ghost/Vault privacy is disabled.
- Vault UI now states Vault/Ghost are unavailable until future audited activation.
- Secure storage now writes a versioned PBKDF2-HMAC-SHA256 + AES-CBC + HMAC-SHA256 format and migrates legacy blobs after successful decrypt.

Status: fixed and frontend build verified.

### Fixed: Redis Rate-Limit Production Mode

Before fix, Redis failure silently fell back to process memory. That is acceptable for local dev but weak for public multi-process deployments.

Fix:

- Added `WEPO_REQUIRE_REDIS_RATE_LIMIT=1` fail-closed startup mode.
- Rate-limit errors fail closed when Redis is required.
- Updated env/service examples and tests.

Status: fixed and verified.

## Ghost Send Future Requirements

Ghost Send must remain disabled until all of these are true:

- A formal transaction format commits privacy fields into txid and sighash rules.
- Spend authorization is replaced or extended with verified nullifiers and no double-spend bypass.
- Range proofs are real and independently audited; negative/overflow outputs are impossible by construction and consensus verification.
- The zk/STARK verifier rejects invalid proofs and has adversarial tests, not placeholder `true` behavior.
- Activation is by explicit consensus upgrade with activation height/hash, never by environment variable.
- Explorer and wallet UX distinguish transparent, shielded, and failed/invalid privacy states without trusting optional metadata.
- Testnet has adversarial vectors for forged proofs, duplicate nullifiers, malformed commitments, fee accounting, reorgs, and supply invariants.

## Quantum Vault Future Requirements

Vault must remain disabled until all of these are true:

- Deposits and withdrawals are canonical consensus transactions, not backend-only side state.
- Vault balances are backed by audited commitments, nullifiers, and range proofs.
- Withdrawal authorization cannot be forged by API parameters or placeholder proofs.
- Vault accounting is reorg-safe and supply-conserving.
- Vault UI exposes only active audited flows and cannot imply privacy before consensus activation.
- Recovery, watch-only, backup, and failure states are specified before handling user funds.

## Evidence

Baseline probe before fixes reproduced:

- Negative-output value creation accepted.
- Negative coinbase offset accepted.
- Additional coinbase issuance accepted.
- Owner-signed transactions with inert privacy fields accepted.
- Node wallet endpoint returned private key material.
- Legacy bridge deploy path was reachable.

Post-fix probe command:

```bash
python3 ops-and-audit/independent_wepo_audit_probe.py
```

Result: launch-boundary regression checks passed. Consensus mint probes are rejected, privacy metadata is rejected, node wallet endpoint returns 410, Vault remains gated, and legacy deploy scripts fail closed.

## Validation Commands

Run during remediation:

```bash
python3 tests/test_consensus_value_invariants.py
python3 tests/test_spend_authorization.py
python3 tests/test_supply_cap.py
python3 tests/test_node_launch_boundaries.py
python3 tests/test_double_spend.py
python3 tests/test_fee_redistribution.py
python3 tests/test_explorer_privacy.py
python3 tests/test_launch_feature_gate.py
python3 tests/test_launch_config.py
python3 tests/test_rate_limit_identity.py
python3 ops-and-audit/independent_wepo_audit_probe.py
python3 -m py_compile wepo-blockchain/core/blockchain.py wepo-blockchain/core/wepo_node.py wepo-blockchain/core/p2p_network.py wepo-blockchain/core/network_profile.py backend/security_utils.py backend/server.py
npm --prefix frontend run build
bash -n wepo-production-deployment/deploy-server.sh
bash -n wepo-production-deployment/upload-and-deploy.sh
```

## Final Go/No-Go

- Transparent WEPO launch: conditional go after production Redis and P2P seeds are configured and release scans pass.
- Ghost Send: no-go.
- Quantum Vault: no-go.
- Messaging: no-go unless address/key binding is redesigned and audited.
- Legacy bridge deployment: no-go; retired fail-closed.
