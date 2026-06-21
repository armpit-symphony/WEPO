# WEPO Private Messaging — Design (v1)

Status: DESIGN + client crypto implemented 2026-06-21. Owner priority #2 (true,
quantum- and AI-resistant private messaging). Built to the same ethos as the
wallet: self-custody keys, post-quantum crypto, server cannot read content.

## 1. Why the existing code is not it

`wepo-blockchain/core/quantum_messaging.py` is demo-grade and must be retired:
- **RSA** key exchange — quantum-breakable (not post-quantum).
- The **server generates and holds private keys** (`generate_messaging_keypair`,
  `recipient_private_keys`) — so the server *can* decrypt. That is not E2E.

## 2. Architecture — PQ end-to-end, blind relay

- **Keys (client-side, self-custody):** each user derives a messaging keypair set
  from their wallet mnemonic — an **ML-KEM-768 (FIPS 203)** key-encapsulation
  keypair (for confidentiality) and an **ML-DSA-44 (FIPS 204)** signing keypair
  (for authenticity). Deterministic, so recovery reproduces them. The server never
  sees private keys.
- **Encryption (E2E):** sender KEM-encapsulates to the recipient's ML-KEM public
  key → 32-byte shared secret → **AES-256-GCM** over the message content. Sender
  signs the envelope with ML-DSA-44. Quantum-safe confidentiality + authenticity.
- **Server = blind relay:** stores/forwards opaque envelopes keyed by recipient
  address and serves a **public-key registry** (public keys only). It cannot read
  or forge messages. (Relay endpoints are the next slice; the security-critical
  client crypto is implemented now.)
- **Metadata privacy (AI-resistant):** the envelope carries no plaintext, subject,
  or structure beyond ciphertext, so the relay only ever sees opaque blobs. To
  also hide the client's IP from the relay, the client must reach it over Tor —
  set `REACT_APP_MESSAGING_RELAY_URL` to a `.onion` hidden service and use Tor
  Browser (or a desktop build with a local SOCKS proxy). NOTE: this is distinct
  from the node's P2P Tor (`WEPO_SOCKS5_PROXY`); a browser cannot force Tor on its
  own, so client→relay IP privacy is a deployment choice, not automatic.

## 3. Envelope (opaque to the server)

```
{ v:1, from, to, ts,
  kem_ct,            // ML-KEM-768 ciphertext (encapsulated shared secret)
  nonce, ct,         // AES-256-GCM nonce + ciphertext of the message
  sender_sig_pub,    // ML-DSA-44 public key of the sender
  sig }              // ML-DSA-44 signature over sha256(canonical envelope)
```
The server stores this verbatim. Only the holder of the recipient ML-KEM secret
key can recover the shared secret and decrypt.

## 4. Implemented now

- `frontend/src/utils/wepoMessaging.js`:
  - `deriveMessagingKeypair(mnemonic)` → ML-KEM-768 + ML-DSA-44 keypairs + public
    bundle (deterministic from the mnemonic).
  - `encryptMessage(...)` → signed PQ envelope; `decryptMessage(...)` →
    plaintext + sender-verification; `verifyEnvelope(...)`.
- `tests/run_messaging_test.sh` (+ `.mjs`): round-trip, sender-signature
  verification, wrong-recipient cannot decrypt, tamper detection, deterministic
  recovery, and confirmation that the envelope carries no plaintext.

## 5. Blind relay — IMPLEMENTED (2026-06-21)

- `backend/messaging_relay.py` — verification core (pure, unit-tested):
  `verify_key_binding` (bundle must be spend-key-signed AND address == H(spend
  pubkey) → no key substitution / MITM) and `verify_fetch_auth` (fresh spend-key
  signature → only the owner reads their inbox).
- `backend/server.py` endpoints (Mongo-backed, ciphertext-only):
  `POST /api/messages/keys`, `GET /api/messages/keys/{address}`,
  `POST /api/messages` (store envelope; size-capped), `POST /api/messages/fetch`
  (owner-authenticated), `POST /api/messages/ack` (owner-authenticated delete).
- Client: `WalletContext.publishMessagingKeys / sendMessage / fetchMessages`
  (derives spend + messaging keys from the mnemonic). UI: `QuantumMessaging.js`
  rewired to the relay (unlock → enable → compose/send → inbox/threads).
- Tests: `tests/test_messaging_relay.py` (key-binding + fetch-auth, accept/reject)
  and `tests/run_messaging_test.sh` (E2E envelope round-trip). All pass.

## 6. Next slices

1. ~~Retire the demo `quantum_messaging.py` (RSA/server-key) + its
   `/api/messaging/*` routes.~~ **DONE 2026-06-21** — module deleted, bridge routes
   removed, and the prelaunch security suite repointed to verify the new relay's
   key-binding + owner-only-fetch guarantees.
2. ~~Route relay calls over Tor.~~ **DONE 2026-06-21** — messaging uses a
   separately-configurable relay endpoint (`REACT_APP_MESSAGING_RELAY_URL`) that
   can point at a `.onion` hidden service, reached over Tor Browser / a SOCKS
   proxy (browsers can't self-route Tor, so this is a deployment choice).
3. ~~Anchor messaging public keys on-chain for fully trustless key discovery.~~
   **DONE 2026-06-21** — `key_register` consensus tx anchors a user's ML-KEM-768 +
   ML-DSA-44 messaging keys on-chain, bound to the address (inputs must be the
   owner's); reorg-safe `messaging_keys` index; latest-wins. Node + gateway
   endpoints (`/api/messages/keys/build-unsigned-register`,
   `/api/messages/keys/onchain/{address}`); client anchors on-chain and resolves
   recipient keys on-chain-first with relay-registry fallback. Tests:
   `tests/test_messaging_key_registration.py`.
4. Live browser e2e (two wallets, enable → send → receive → verify).

## 6. Non-negotiables

- Server never holds private keys and cannot read content (blind relay).
- Post-quantum only (ML-KEM + ML-DSA + AES-256-GCM); no RSA/ECC.
- Built from vetted primitives (`@noble/post-quantum`, `@noble/ciphers`); no
  hand-rolled crypto.
