/**
 * WEPO private messaging — post-quantum end-to-end encryption (client-side).
 *
 * See MESSAGING_DESIGN.md. All security-critical crypto runs on the client; the
 * server is a blind relay that only ever sees opaque envelopes.
 *
 *   - confidentiality: ML-KEM-768 (FIPS 203) encapsulation -> AES-256-GCM
 *   - authenticity:    ML-DSA-44 (FIPS 204) signature over the envelope
 *   - keys:            derived deterministically from the wallet mnemonic
 *                      (self-custody; the server never holds private keys)
 *
 * Built from vetted primitives (@noble/post-quantum, @noble/ciphers). No RSA/ECC,
 * no hand-rolled crypto.
 */
import { ml_kem768 } from '@noble/post-quantum/ml-kem.js';
import { ml_dsa44 } from '@noble/post-quantum/ml-dsa.js';
import { gcm } from '@noble/ciphers/aes.js';
import { sha256, sha512 } from '@noble/hashes/sha2.js';
import { randomBytes } from '@noble/post-quantum/utils.js';
import { bytesToHex, hexToBytes } from './wepoSigner.js';

const utf8 = (s) => new TextEncoder().encode(s);
const fromUtf8 = (b) => new TextDecoder().decode(b);

/**
 * Derive the messaging keypair set from a mnemonic. Domain-separated from the
 * spend key so messaging and funds never share key material.
 */
export function deriveMessagingKeypair(mnemonic, passphrase = '') {
  const kemSeed = sha512(utf8(`${mnemonic}${passphrase}|wepo_mlkem_v1`)); // 64 bytes
  const sigSeed = sha256(utf8(`${mnemonic}${passphrase}|wepo_msgsig_v1`)); // 32 bytes
  const kem = ml_kem768.keygen(kemSeed);
  const sig = ml_dsa44.keygen(sigSeed);
  return {
    kemPublicKey: kem.publicKey,
    kemSecretKey: kem.secretKey,
    sigPublicKey: sig.publicKey,
    sigSecretKey: sig.secretKey,
    // The public bundle is what a user publishes to the key registry.
    publicBundle: {
      kem: bytesToHex(kem.publicKey),
      sig: bytesToHex(sig.publicKey),
    },
  };
}

/**
 * A device-local messaging keypair: generated once per wallet address and kept on
 * the device, independent of the recovery phrase and the spend/funds key. This is
 * what makes messaging click-and-use (no password, works for any wallet). The seed
 * is a random 32-byte hex string persisted by the caller; deriving from it is
 * deterministic so the same device always rebuilds the same messaging identity.
 */
export function randomMessagingSeed() {
  return bytesToHex(randomBytes(32));
}

/** Sign a digest with the messaging ML-DSA key (used for relay self-auth). */
export function signMessagingDigest(digest, sigSecretKey) {
  return bytesToHex(ml_dsa44.sign(digest, sigSecretKey));
}

// Canonical digests signed (with the messaging key) to authenticate to the relay.
// These must match backend/messaging_relay.py byte-for-byte.
export function keyRegistryDigest(address, kemPubHex, sigPubHex) {
  return sha256(utf8(`WEPO-MSGKEY-v1|${address}|${kemPubHex}|${sigPubHex}`));
}

export function fetchAuthDigest(address, ts) {
  return sha256(utf8(`WEPO-MSGFETCH-v1|${address}|${ts}`));
}

// Deterministic bytes signed/verified for envelope authenticity.
function envelopeDigest(env) {
  const parts = [
    'WEPO-MSG-v1',
    String(env.v), String(env.from), String(env.to), String(env.ts),
    env.kem_ct, env.nonce, env.ct,
  ];
  return sha256(utf8(parts.join('|')));
}

/**
 * Encrypt a message to a recipient's ML-KEM public key and sign it.
 * `recipientKemPublicKeyHex` comes from the recipient's published public bundle.
 * Returns an opaque envelope safe to hand to the (blind) relay.
 */
export function encryptMessage({
  plaintext, fromAddress, toAddress,
  recipientKemPublicKeyHex, senderSigSecretKey, senderSigPublicKey,
}) {
  const { cipherText, sharedSecret } = ml_kem768.encapsulate(hexToBytes(recipientKemPublicKeyHex));
  const nonce = randomBytes(12);
  const ct = gcm(sharedSecret, nonce).encrypt(utf8(plaintext));

  const env = {
    v: 1,
    from: fromAddress,
    to: toAddress,
    ts: Math.floor(Date.now() / 1000),
    kem_ct: bytesToHex(cipherText),
    nonce: bytesToHex(nonce),
    ct: bytesToHex(ct),
  };
  env.sender_sig_pub = bytesToHex(senderSigPublicKey);
  env.sig = bytesToHex(ml_dsa44.sign(envelopeDigest(env), senderSigSecretKey));
  return env;
}

/** Verify the sender's ML-DSA signature over an envelope. */
export function verifyEnvelope(env) {
  if (!env || !env.sig || !env.sender_sig_pub) return false;
  try {
    return ml_dsa44.verify(hexToBytes(env.sig), envelopeDigest(env), hexToBytes(env.sender_sig_pub));
  } catch (e) {
    return false;
  }
}

/**
 * Decrypt an envelope with the recipient's ML-KEM secret key. Verifies the
 * sender signature first; throws if the message was tampered with or is not for
 * this key.
 */
export function decryptMessage(env, recipientKemSecretKey, { requireSignature = true } = {}) {
  const verified = verifyEnvelope(env);
  if (requireSignature && !verified) {
    throw new Error('Message signature verification failed (forged or tampered).');
  }
  const sharedSecret = ml_kem768.decapsulate(hexToBytes(env.kem_ct), recipientKemSecretKey);
  // AES-GCM auth tag fails (throws) if this key did not produce the ciphertext.
  const pt = gcm(sharedSecret, hexToBytes(env.nonce)).decrypt(hexToBytes(env.ct));
  return { plaintext: fromUtf8(pt), from: env.from, to: env.to, ts: env.ts, verified };
}
