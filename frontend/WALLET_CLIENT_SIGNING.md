# WEPO Wallet — Client-Side Signing Integration

This describes how the web wallet signs transactions itself, as required by the
consensus spend-authorization model (see `wepo-blockchain/core/blockchain.py`).

## Status: IMPLEMENTED (2026-06-21)

The self-custody migration is wired end to end:

- **`src/contexts/WalletContext.jsx`** — `createWallet` now generates a BIP-39
  mnemonic locally, derives the `wepo1q…` address via `deriveWepoKeypair`, and
  registers only the address with the backend (no server-side key). `loginWallet`
  decrypts the locally stored phrase; `recoverWallet` imports a phrase on a new
  device; `sendWepo` runs build-unsigned → sign → submit `signed_tx`.
- **`src/components/WalletSetup.jsx`** — shows the 12-word recovery phrase with a
  mandatory backup-confirmation step before entering the wallet.
- **`src/components/WalletLogin.jsx`** — adds a "Restore from recovery phrase" mode.
- **`backend/server.py`** — added `POST /api/transaction/build-unsigned` (proxy to
  node) and changed `POST /api/transaction/send` to accept `{signed_tx}` and proxy
  it; `POST /api/wallet/create` accepts the client-derived `address`. The old
  custodial `from_address`/session gate on send is removed — the Dilithium
  signature is the spend authorization, enforced by consensus.

> **Backend target:** the wallet must point at the **`server.py` gateway** (or the
> node's API directly). The legacy `wepo-fast-test-bridge.py` does **not** expose
> `/api/transaction/build-unsigned` and is custodial — do not point a self-custody
> build at it. Set `REACT_APP_BACKEND_URL` accordingly before building.

The mnemonic and wallet descriptor are stored only via `secureStorage`.
Version 2 uses PBKDF2-HMAC-SHA256 with a fixed 310,000-round work factor,
AES-256-CBC encryption, and an independent HMAC-SHA256 encrypt-then-MAC key.
Malformed envelopes, attacker-selected KDF work factors, oversized payloads,
wrong passwords, and ciphertext tampering fail closed. Routine logout clears
the unlocked session and decrypted material but leaves the encrypted device
vault intact. The recovery phrase is shown exactly once at creation and is
never logged or sent to the server.

Wallet unlock is local-only. A vault password is never submitted to
`/api/wallet/login`; a clean device must use the recovery-phrase flow.

## Signing primitives (verified)

- **Algorithm:** ML-DSA-44 (FIPS 204), interoperable Python (node) ↔ JavaScript
  (wallet). Proven: a JS-signed transaction verifies on the Python node and is
  accepted by consensus (`tests/run_wallet_signer_test.sh`). The committed
  `tests/vectors/wallet_signing_v3.json` fixture also pins key/address and network
  derivation, exact sighash payload/preimage, canonical signed-transaction
  bytes, txid preimage/txid, PoW/PoS header bytes and IDs, and a reproducible
  signature; both runtimes verify it independently.
- **`src/utils/wepoSigner.js`** provides:
  - `deriveWepoKeypair(mnemonic, passphrase)` → `{ publicKey, secretKey, publicKeyHex, address }`
  - `deriveAddress(publicKey)` → `wepo1q…` (= `sha256(pubkeyHex)[:39]`, matches the node)
  - `canonicalSighashHex(tx, network)` → matches `Transaction.get_canonical_sighash(network)`
  - `canonicalSighashMaterialHex(tx, network)` → exact payload, preimage, and digest
  - `canonicalTransactionMaterialHex(tx)` ??? normalized payload, preimage, and txid
  - `canonicalTxidHex(tx)` ??? matches `Transaction.calculate_txid`
  - `signTransaction(unsignedTx, secretKey, publicKey, expectedSighashHex, network)` → signed tx
  - `verifyTransactionInput(tx, i, network)` → optional local check
  - `assertStandardSendIntent(tx, intent)` -> binds recipient, amount, fixed fee,
    transparent transfer shape, canonical inputs, and owner-only change before signing

## Implemented wallet model

1. **Create:** generate a BIP-39 mnemonic locally, derive the ML-DSA keypair and
   `wepo1q…` address, and show the phrase for one-time backup confirmation.
2. **Store:** persist only the encrypted mnemonic and wallet descriptor.
   Re-derive the keypair on demand; never persist the ML-DSA secret key.
3. **Recover:** restore the identical keypair and address from the mnemonic on a
   clean device.
4. **Rotate:** atomically re-encrypt the complete local vault under the new
   password, rolling back both records if either write fails.

Backend sessions govern account APIs only. Consensus spend authorization comes
from the client-side ML-DSA signature and public-key/address binding.

## Send flow (replaces the `from_address`-only POST)

```js
import {
  assertStandardSendIntent,
  canonicalTxidHex,
  deriveWepoKeypair,
  signTransaction,
  verifyTransactionInput,
} from '../utils/wepoSigner';
import { NETWORK_PROFILE } from '../config/featureFlags';

// keypair re-derived from the unlocked mnemonic
const { address, publicKey, secretKey } = deriveWepoKeypair(mnemonic, passphrase);

// 1) ask the node to build the unsigned skeleton + sighash
const build = await fetch(`${backendUrl}/api/transaction/build-unsigned`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ from_address: address, to_address: toAddress, amount, fee }),
}).then(r => r.json());
if (build.network !== NETWORK_PROFILE) {
  throw new Error('Node returned a transaction for the wrong network');
}

// 2) bind the skeleton to the exact user intent before any signing operation
assertStandardSendIntent(build.unsigned_tx, {
  senderAddress: address,
  recipientAddress: toAddress,
  amountAtomic,
  feeAtomic,
});
const signedTx = signTransaction(
  build.unsigned_tx, secretKey, publicKey, build.sighash, NETWORK_PROFILE,
);
if (!signedTx.inputs.every((_, index) => verifyTransactionInput(signedTx, index, NETWORK_PROFILE))) {
  throw new Error('Local signature verification failed');
}
const localTxid = canonicalTxidHex(signedTx);

// 3) submit, then require the node to identify the same signed transaction
const res = await fetch(`${backendUrl}/api/transaction/send`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ signed_tx: signedTx }),
}).then(r => r.json());
if ((res.transaction_id || res.tx_hash || res.txid).toLowerCase() !== localTxid) {
  throw new Error('Node returned a mismatched transaction ID');
}
```

The same network-bound build → sign → submit pattern applies to ordinary
wallet staking and masternode
operations via `/api/stake`, `/api/stake/deactivate`, `/api/masternode`,
`/api/masternode/deactivate` (each returns `{ unsigned_tx, sighash, network }`).
A production validator key must never enter this browser flow. Use
`wepo-production-deployment/validator_stake_ceremony.py` so the isolated signer
applies its strict stake policy, requires a separate signer-only operator
authorization, fences outpoints, and signs without exporting the private key.

## Notes

- `@noble/post-quantum` is added to `package.json`. ML-DSA-44 keygen is
  deterministic from a 32-byte seed, so mnemonic-based recovery is reproducible.
- This is a hard fork: legacy `wepo1` (sha256-of-seed/username) addresses are not
  valid on mainnet.
