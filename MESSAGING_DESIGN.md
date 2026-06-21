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
- **Metadata privacy (AI-resistant):** route relay traffic over the Layer-1
  transport (Tor / `WEPO_SOCKS5_PROXY`) so the relay never sees real IPs; envelope
  carries no plaintext, subject, or length-revealing structure beyond ciphertext.

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

## 5. Next slices (not in this commit)

1. Blind-relay endpoints: `POST /api/messages` (store envelope),
   `GET /api/messages/{address}` (fetch envelopes), `GET/POST /api/messages/keys`
   (public-key registry; keys signed by the owner). All ciphertext-only.
2. Wallet UI (`QuantumMessaging.js`) wired to the new module + relay.
3. Retire `quantum_messaging.py` (RSA/server-key) once the relay is live.
4. Optional: anchor messaging public keys on-chain for trustless key discovery.

## 6. Non-negotiables

- Server never holds private keys and cannot read content (blind relay).
- Post-quantum only (ML-KEM + ML-DSA + AES-256-GCM); no RSA/ECC.
- Built from vetted primitives (`@noble/post-quantum`, `@noble/ciphers`); no
  hand-rolled crypto.
