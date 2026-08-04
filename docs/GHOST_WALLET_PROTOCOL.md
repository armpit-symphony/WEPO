# WEPO Ghost Wallet Protocol v1

Status: implementation in progress; not yet enabled in shipping clients.

## Security boundary

The wallet owns all Ghost secrets. The node and backend receive only public
receiver data, encrypted notes, commitments, nullifiers, and completed proofs.
There is no network prover. Rescue commitment/key derivation and Winterfell
proving must run through the audited local native/WASM bridge identified as
`wepo-local-ghost-crypto-v1`. Missing bridge methods fail closed.
The consensus-native bridge core is `zk/src/ghost/wallet.rs`. It reuses the
exact Rescue and complete-bundle AIR implementation imported by the production
verifier; it does not contain a parallel hash or proof implementation. Its
optimized production test generates a shielding proof and verifies that proof
through the production verifier before accepting it.


`zk/src/ghost/wallet_protocol.rs` defines the shared bounded binary transport.
The `ghost_wallet_bridge` native sidecar reads exactly one request from stdin
and writes exactly one response to stdout. It accepts no witness data in argv,
opens no socket, writes no witness to disk, and emits no witness-bearing logs.
Malformed and cryptographically invalid requests receive the same empty error
response. Successful proving returns only the public, versioned proof envelope.
The browser-WASM wrapper must call the same request handler rather than define a
second transport.

The deterministic Rust fixture remains test/audit material and is never exposed
through this bridge. The legacy `/api/privacy/*` API remains retired.

## Key hierarchy

The English BIP-39 recovery phrase is checksum-validated and converted to the
standard BIP-39 seed with its optional passphrase. That seed then feeds a
length-prefixed, domain-separated SHAKE-256 derivation. Separate labels produce:

- the 32-byte canonical Goldilocks spending key;
- the default 11-byte diversifier;
- an ML-KEM-768 incoming-view keypair;
- a separate ML-KEM-768 outgoing-recovery keypair.

Incoming and outgoing keys are never reused. The spending key is passed only to
the local bridge for consensus-compatible diversified-key derivation and proof
generation.

## Receiver encoding

A `wepog1` receiver is a canonical base64url encoding of version, network,
diversifier, 32-byte `pk_d`, and the 1,184-byte ML-KEM-768 public key, followed
by an eight-byte domain-separated SHA-256 checksum. Decoding rejects unknown
versions, noncanonical base64, wrong network, wrong lengths, trailing bytes,
checksum failure, and noncanonical Goldilocks limbs.

The receiver is intentionally large: it carries a post-quantum KEM public key
without relying on a trusted directory. A later compact on-chain registry may
be designed separately; it must not silently change this v1 encoding.

## Encrypted note

Each output contains two ML-KEM-768 + HKDF-SHA-256 + AES-256-GCM sections:

1. recipient trial decryption with the incoming-view secret key;
2. sender recovery with the outgoing-view secret key.

Both sections encrypt the same canonical plaintext: network, diversifier,
61-bit value, `rho`, `rcm`, `pk_d`, and an optional bounded UTF-8 memo. The KDF
salt and AEAD additional data bind the public note commitment, network, role,
and protocol version. Ciphertext swapping, wrong-network scanning, commitment
tampering, wrong keys, malformed plaintext, and trailing data fail closed.

After decryption the wallet recomputes the note commitment through the local
bridge and accepts the note only if it exactly matches the chain output.

## Still required

- package/integrate the native sidecar and add the browser-WASM wrapper;
- persist encrypted note/witness state atomically with wallet backup data;
- scan canonical blocks and maintain witnesses through disconnect/replay;
- build and prove shielding, fully shielded, and unshielding transactions;
- add cross-runtime receiver, note, commitment, nullifier, witness, and proof
  vectors;
- integrate explicit fee preview/approval and the shipping wallet UI.
