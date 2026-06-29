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
  `verify_key_registration` (bundle must be self-signed by the messaging key it
  registers) and `verify_fetch_auth` (fresh signature by the messaging key
  currently registered for the address → only that key-holder reads the inbox).
- `backend/server.py` endpoints (Mongo-backed, ciphertext-only):
  `POST /api/messages/keys`, `GET /api/messages/keys/{address}`,
  `POST /api/messages` (store envelope; size-capped), `POST /api/messages/fetch`
  (auth by registered key), `POST /api/messages/ack` (auth by registered key).
- Client: `WalletContext.publishMessagingKeys / sendMessage / fetchMessages`
  (uses the device messaging key). UI: `QuantumMessaging.js` is a simple **send
  form** (recipient address + message + Send) plus an **Inbox** button that
  retrieves all messages — modeled on the WEPO send screen.
- Tests: `tests/test_messaging_relay.py` (registration + fetch-auth, accept/reject)
  and `tests/run_messaging_test.sh` (E2E envelope round-trip). All pass; JS→Python
  relay self-auth verified cross-runtime.

### Identity model (UX): click-and-use, device-local key

Messaging is wired to the wallet address and is **click-and-use**: no password, no
recovery phrase, no "enable" step, and sending is free (relay store, no on-chain
tx). It uses a **device-local messaging keypair** (ML-KEM + ML-DSA) that is:

- generated automatically the first time you open messaging for an address, then
  persisted on the device (`localStorage` `wepo_msgseed_<address>`, a random seed);
- **independent of the recovery phrase and the spend/funds key** — so it works for
  any wallet (even custodial / no phrase on this device) and never touches funds keys;
- self-registered with the relay (the messaging key signs its own registration) and
  used to authenticate inbox fetches.

The seed survives logout/login on the same device so the inbox stays readable;
`logout` only drops the in-memory copy.

**Trade-off (lab/test; messaging is gated pre-mainnet):** because registration is
authenticated by the messaging key itself, the relay does **not** prove those keys
belong to the address's spend-key owner — a malicious relay/attacker could
substitute keys at the registry layer (MITM) or squat an address (last-write-wins).
Message **content** stays end-to-end encrypted regardless. The trustless path is the
on-chain key anchor (spend-key-bound consensus tx), which clients resolve **first**;
the relay registry is the convenience fallback. Harden the binding (e.g. require the
on-chain anchor, or sign the device key with the spend key once) before mainnet.

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
