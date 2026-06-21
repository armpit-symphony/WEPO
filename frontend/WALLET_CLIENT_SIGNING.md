# WEPO Wallet — Client-Side Signing Integration

This describes how the web wallet signs transactions itself, as required by the
consensus spend-authorization model (see `wepo-blockchain/core/blockchain.py`).

## Status: IMPLEMENTED (2026-06-21)

The self-custody migration is wired end to end:

- **`src/contexts/WalletContext.js`** — `createWallet` now generates a BIP-39
  mnemonic locally, derives the `wepo1q…` address via `deriveWepoKeypair`, and
  registers only the address with the backend (no server-side key). `loginWallet`
  decrypts the locally stored phrase; `recoverWallet` imports a phrase on a new
  device; `sendWepo` runs build-unsigned → sign → submit `signed_tx`.
- **`src/components/WalletSetup.js`** — shows the 12-word recovery phrase with a
  mandatory backup-confirmation step before entering the wallet.
- **`src/components/WalletLogin.js`** — adds a "Restore from recovery phrase" mode.
- **`backend/server.py`** — added `POST /api/transaction/build-unsigned` (proxy to
  node) and changed `POST /api/transaction/send` to accept `{signed_tx}` and proxy
  it; `POST /api/wallet/create` accepts the client-derived `address`. The old
  custodial `from_address`/session gate on send is removed — the Dilithium
  signature is the spend authorization, enforced by consensus.

> **Backend target:** the wallet must point at the **`server.py` gateway** (or the
> node's API directly). The legacy `wepo-fast-test-bridge.py` does **not** expose
> `/api/transaction/build-unsigned` and is custodial — do not point a self-custody
> build at it. Set `REACT_APP_BACKEND_URL` accordingly before building.

The mnemonic is stored only via `secureStorage` (AES, encrypted with the wallet
password) and is cleared on logout. The recovery phrase is shown exactly once at
creation and is never logged or sent to the server.

## Signing primitives (verified)

- **Algorithm:** ML-DSA-44 (FIPS 204), interoperable Python (node) ↔ JavaScript
  (wallet). Proven: a JS-signed transaction verifies on the Python node and is
  accepted by consensus (`tests/run_wallet_signer_test.sh`).
- **`src/utils/wepoSigner.js`** provides:
  - `deriveWepoKeypair(mnemonic, passphrase)` → `{ publicKey, secretKey, publicKeyHex, address }`
  - `deriveAddress(publicKey)` → `wepo1q…` (= `sha256(pubkeyHex)[:39]`, matches the node)
  - `canonicalSighashHex(tx)` → matches `Transaction.get_canonical_sighash`
  - `signTransaction(unsignedTx, secretKey, publicKey, expectedSighashHex)` → signed tx
  - `verifyTransactionInput(tx, i)` → optional local check

## Required wallet-model change (product decision)

The current live wallet is a **custodial backend account**: `createWallet` posts
`username`/`password` to `/api/wallet/create` and the backend derives the address
from the username (`custodyMode: 'backend_account'`, no mnemonic, no client key).
That model is incompatible with self-custody — the address must be `H(pubkey)` of
a key the **user** holds.

To adopt client signing, the wallet must move to a self-custody identity:

1. **Create:** generate a BIP-39 mnemonic locally → `deriveWepoKeypair(mnemonic)`
   → show the mnemonic for backup. The `wepo1q…` address is derived from the
   public key; the backend no longer mints the address.
2. **Store:** keep only the mnemonic (encrypted, as today via `secureStorage`).
   Re-derive the keypair on demand; do not persist the 2560-byte secret key.
3. **Recover:** mnemonic → `deriveWepoKeypair` reproduces the same keypair/address.

## Send flow (replaces the `from_address`-only POST)

```js
import { deriveWepoKeypair, signTransaction } from '../utils/wepoSigner';

// keypair re-derived from the unlocked mnemonic
const { address, publicKey, secretKey } = deriveWepoKeypair(mnemonic, passphrase);

// 1) ask the node to build the unsigned skeleton + sighash
const build = await fetch(`${backendUrl}/api/transaction/build-unsigned`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ from_address: address, to_address: toAddress, amount, fee }),
}).then(r => r.json());

// 2) sign locally (verifies the node's sighash matches our recomputation)
const signedTx = signTransaction(build.unsigned_tx, secretKey, publicKey, build.sighash);

// 3) submit the signed transaction
const res = await fetch(`${backendUrl}/api/transaction/send`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ signed_tx: signedTx }),
}).then(r => r.json());
```

The same build → sign → submit pattern applies to staking and masternode
operations via `/api/stake`, `/api/stake/deactivate`, `/api/masternode`,
`/api/masternode/deactivate` (each returns `{ unsigned_tx, sighash }`).

## Notes

- `@noble/post-quantum` is added to `package.json`. ML-DSA-44 keygen is
  deterministic from a 32-byte seed, so mnemonic-based recovery is reproducible.
- This is a hard fork: legacy `wepo1` (sha256-of-seed/username) addresses are not
  valid on mainnet.
