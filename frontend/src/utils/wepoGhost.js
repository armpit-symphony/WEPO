/**
 * WEPO Ghost wallet core — self-custodial receiver and encrypted-note handling.
 *
 * This module deliberately does not implement Rescue or Winterfell in
 * JavaScript. Consensus note commitments, diversified keys, witnesses, and
 * proofs must come from the audited local Ghost crypto bridge. A missing bridge
 * fails closed; there is no network prover and no legacy privacy fallback.
 */
import { gcm } from '@noble/ciphers/aes.js';
import { hkdf } from '@noble/hashes/hkdf.js';
import { sha256 } from '@noble/hashes/sha2.js';
import { shake256 } from '@noble/hashes/sha3.js';
import { ml_kem768 } from '@noble/post-quantum/ml-kem.js';
import { randomBytes } from '@noble/post-quantum/utils.js';
import { mnemonicToSeedSync, validateMnemonic } from '@scure/bip39';
import { wordlist as englishWordlist } from '@scure/bip39/wordlists/english.js';

export const GHOST_WALLET_VERSION = 1;
export const GHOST_RECEIVER_PREFIX = 'wepog1';
export const GHOST_DIVERSIFIER_BYTES = 11;
export const GHOST_POOL_VALUE_BYTES = 32;
export const GHOST_KEM_PUBLIC_KEY_BYTES = 1184;
export const GHOST_KEM_SECRET_KEY_BYTES = 2400;
export const GHOST_KEM_CIPHERTEXT_BYTES = 1088;
export const GHOST_NOTE_MAX_MEMO_BYTES = 512;
export const GHOST_NOTE_MAX_VALUE = (1n << 61n) - 1n;
export const GHOST_MAX_ENCRYPTED_NOTE_BYTES = 16 * 1024;
export const GHOST_LOCAL_CRYPTO_BRIDGE_KIND = 'wepo-local-ghost-crypto-v1';

const GOLDILOCKS_MODULUS = (1n << 64n) - (1n << 32n) + 1n;
const utf8 = (value) => new TextEncoder().encode(value);
const fromUtf8 = (value) => new TextDecoder('utf-8', { fatal: true }).decode(value);
const RECEIVER_CHECKSUM_DOMAIN = utf8('WEPO_GHOST_RECEIVER_V1\0');
const NOTE_KDF_DOMAIN = utf8('WEPO_GHOST_NOTE_KDF_V1\0');
const NOTE_AAD_DOMAIN = utf8('WEPO_GHOST_NOTE_AAD_V1\0');
const NOTE_ENVELOPE_MAGIC = utf8('WEPO_GHOST_ENC_NOTE_V1\0');
const KEY_DERIVATION_DOMAIN = utf8('WEPO_GHOST_WALLET_KEYS_V1\0');

function fail(message) {
  throw new Error(`Ghost wallet: ${message}`);
}

function isUint8Array(value) {
  return Object.prototype.toString.call(value) === '[object Uint8Array]';
}

function bytes(value, name, length = null) {
  if (!isUint8Array(value)) fail(`${name} must be bytes`);
  if (length !== null && value.length !== length) {
    fail(`${name} must be ${length} bytes`);
  }
  return value;
}

function concat(...parts) {
  const length = parts.reduce((sum, part) => sum + part.length, 0);
  const result = new Uint8Array(length);
  let offset = 0;
  for (const part of parts) {
    result.set(part, offset);
    offset += part.length;
  }
  return result;
}

function u16(value) {
  if (!Number.isInteger(value) || value < 0 || value > 0xffff) fail('u16 value is invalid');
  const result = new Uint8Array(2);
  new DataView(result.buffer).setUint16(0, value, true);
  return result;
}

function u32(value) {
  if (!Number.isInteger(value) || value < 0 || value > 0xffffffff) fail('u32 value is invalid');
  const result = new Uint8Array(4);
  new DataView(result.buffer).setUint32(0, value, true);
  return result;
}

function u64(value) {
  const parsed = BigInt(value);
  if (parsed < 0n || parsed > ((1n << 64n) - 1n)) fail('u64 value is invalid');
  const result = new Uint8Array(8);
  new DataView(result.buffer).setBigUint64(0, parsed, true);
  return result;
}

function networkBytes(network) {
  if (typeof network !== 'string' || network.length < 1 || network.length > 32
      || !/^[a-z][a-z0-9_-]{0,31}$/.test(network)) {
    fail('network is invalid');
  }
  return utf8(network);
}

function equal(left, right) {
  if (!isUint8Array(left) || !isUint8Array(right)
      || left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left[index] ^ right[index];
  return difference === 0;
}

function assertCanonicalPoolValue(value, name) {
  bytes(value, name, GHOST_POOL_VALUE_BYTES);
  const view = new DataView(value.buffer, value.byteOffset, value.byteLength);
  for (let offset = 0; offset < value.length; offset += 8) {
    if (view.getBigUint64(offset, true) >= GOLDILOCKS_MODULUS) {
      fail(`${name} contains a non-canonical Goldilocks limb`);
    }
  }
  return value;
}

function base64UrlEncode(value) {
  let binary = '';
  for (const item of value) binary += String.fromCharCode(item);
  return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/u, '');
}

function base64UrlDecode(value) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]+$/u.test(value)) fail('receiver encoding is invalid');
  const padded = value.replaceAll('-', '+').replaceAll('_', '/')
    + '='.repeat((4 - (value.length % 4)) % 4);
  let binary;
  try {
    binary = atob(padded);
  } catch (_error) {
    fail('receiver encoding is invalid');
  }
  const result = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  if (base64UrlEncode(result) !== value) fail('receiver encoding is not canonical');
  return result;
}

class Reader {
  constructor(value) {
    this.value = bytes(value, 'encoded value');
    this.offset = 0;
  }

  take(length, name) {
    if (!Number.isInteger(length) || length < 0 || this.offset + length > this.value.length) {
      fail(`${name} is truncated`);
    }
    const result = this.value.slice(this.offset, this.offset + length);
    this.offset += length;
    return result;
  }

  byte(name) { return this.take(1, name)[0]; }

  uint16(name) {
    const value = this.take(2, name);
    return new DataView(value.buffer, value.byteOffset, 2).getUint16(0, true);
  }

  uint32(name) {
    const value = this.take(4, name);
    return new DataView(value.buffer, value.byteOffset, 4).getUint32(0, true);
  }

  uint64(name) {
    const value = this.take(8, name);
    return new DataView(value.buffer, value.byteOffset, 8).getBigUint64(0, true);
  }

  finish() {
    if (this.offset !== this.value.length) fail('encoded value has trailing bytes');
  }
}

function derivationInput(mnemonic, passphrase) {
  if (typeof mnemonic !== 'string' || !validateMnemonic(mnemonic, englishWordlist)) {
    fail('recovery phrase is not valid BIP-39 English');
  }
  if (typeof passphrase !== 'string') fail('passphrase must be a string');
  const seed = mnemonicToSeedSync(mnemonic.normalize('NFKD'), passphrase.normalize('NFKD'));
  return concat(KEY_DERIVATION_DOMAIN, u32(seed.length), seed);
}

function deriveBytes(master, label, length) {
  return shake256(concat(master, utf8(label)), { dkLen: length });
}

function deriveCanonicalPoolValue(master, label) {
  const output = new Uint8Array(GHOST_POOL_VALUE_BYTES);
  for (let limb = 0; limb < 4; limb += 1) {
    let counter = 0;
    while (true) {
      const candidate = deriveBytes(master, `${label}|${limb}|${counter}`, 8);
      const value = new DataView(
        candidate.buffer, candidate.byteOffset, candidate.byteLength,
      ).getBigUint64(0, true);
      if (value < GOLDILOCKS_MODULUS) {
        output.set(candidate, limb * 8);
        break;
      }
      counter += 1;
      if (counter > 0xffff) fail('canonical key derivation exhausted');
    }
  }
  return output;
}

/** Derive domain-separated Ghost secrets; nothing here is sent over the network. */
export function deriveGhostSecretMaterial(mnemonic, passphrase = '') {
  const master = derivationInput(mnemonic, passphrase);
  const incoming = ml_kem768.keygen(deriveBytes(master, '|incoming-ml-kem-768|', 64));
  const outgoing = ml_kem768.keygen(deriveBytes(master, '|outgoing-ml-kem-768|', 64));
  return {
    version: GHOST_WALLET_VERSION,
    spendingKey: deriveCanonicalPoolValue(master, '|spending-key|'),
    diversifier: deriveBytes(master, '|default-diversifier|', GHOST_DIVERSIFIER_BYTES),
    incomingViewingPublicKey: incoming.publicKey,
    incomingViewingSecretKey: incoming.secretKey,
    outgoingViewingPublicKey: outgoing.publicKey,
    outgoingViewingSecretKey: outgoing.secretKey,
  };
}

function requireLocalBridge(bridge, methods) {
  if (!bridge || bridge.kind !== GHOST_LOCAL_CRYPTO_BRIDGE_KIND || bridge.localOnly !== true) {
    fail('audited local Ghost crypto bridge is required');
  }
  for (const method of methods) {
    if (typeof bridge[method] !== 'function') fail(`local Ghost crypto bridge lacks ${method}`);
  }
  return bridge;
}

export function encodeGhostReceiver({ network, diversifier, pkD, incomingViewingPublicKey }) {
  const net = networkBytes(network);
  bytes(diversifier, 'diversifier', GHOST_DIVERSIFIER_BYTES);
  assertCanonicalPoolValue(pkD, 'pk_d');
  bytes(incomingViewingPublicKey, 'incoming viewing public key', GHOST_KEM_PUBLIC_KEY_BYTES);
  const payload = concat(
    Uint8Array.of(GHOST_WALLET_VERSION, net.length), net, diversifier, pkD,
    u16(incomingViewingPublicKey.length), incomingViewingPublicKey,
  );
  const checksum = sha256(concat(RECEIVER_CHECKSUM_DOMAIN, payload)).slice(0, 8);
  return GHOST_RECEIVER_PREFIX + base64UrlEncode(concat(payload, checksum));
}

export function decodeGhostReceiver(encoded, expectedNetwork = null) {
  if (typeof encoded !== 'string' || !encoded.startsWith(GHOST_RECEIVER_PREFIX)) {
    fail('receiver prefix is invalid');
  }
  const decoded = base64UrlDecode(encoded.slice(GHOST_RECEIVER_PREFIX.length));
  if (decoded.length < 8) fail('receiver is truncated');
  const payload = decoded.slice(0, -8);
  const checksum = decoded.slice(-8);
  const expectedChecksum = sha256(concat(RECEIVER_CHECKSUM_DOMAIN, payload)).slice(0, 8);
  if (!equal(checksum, expectedChecksum)) fail('receiver checksum mismatch');
  const reader = new Reader(payload);
  if (reader.byte('receiver version') !== GHOST_WALLET_VERSION) fail('receiver version is unsupported');
  const network = fromUtf8(reader.take(reader.byte('network length'), 'network'));
  networkBytes(network);
  if (expectedNetwork !== null && network !== expectedNetwork) fail('receiver belongs to a different network');
  const diversifier = reader.take(GHOST_DIVERSIFIER_BYTES, 'diversifier');
  const pkD = reader.take(GHOST_POOL_VALUE_BYTES, 'pk_d');
  assertCanonicalPoolValue(pkD, 'pk_d');
  const kemLength = reader.uint16('incoming viewing public key length');
  if (kemLength !== GHOST_KEM_PUBLIC_KEY_BYTES) fail('incoming viewing public key length is invalid');
  const incomingViewingPublicKey = reader.take(kemLength, 'incoming viewing public key');
  reader.finish();
  return { version: GHOST_WALLET_VERSION, network, diversifier, pkD, incomingViewingPublicKey };
}

export async function createGhostReceiver(secretMaterial, bridge, network = 'mainnet') {
  requireLocalBridge(bridge, ['deriveDiversifiedKey']);
  bytes(secretMaterial?.spendingKey, 'spending key', GHOST_POOL_VALUE_BYTES);
  bytes(secretMaterial?.diversifier, 'diversifier', GHOST_DIVERSIFIER_BYTES);
  bytes(
    secretMaterial?.incomingViewingPublicKey,
    'incoming viewing public key',
    GHOST_KEM_PUBLIC_KEY_BYTES,
  );
  const pkD = await bridge.deriveDiversifiedKey({
    spendingKey: secretMaterial.spendingKey.slice(),
    diversifier: secretMaterial.diversifier.slice(),
  });
  assertCanonicalPoolValue(pkD, 'bridge pk_d');
  return encodeGhostReceiver({
    network,
    diversifier: secretMaterial.diversifier,
    pkD,
    incomingViewingPublicKey: secretMaterial.incomingViewingPublicKey,
  });
}

function validateNote(note, recipient) {
  const value = BigInt(note?.value);
  if (value < 0n || value > GHOST_NOTE_MAX_VALUE) fail('note value is out of range');
  assertCanonicalPoolValue(note?.rho, 'rho');
  assertCanonicalPoolValue(note?.rcm, 'rcm');
  const memo = note.memo === undefined ? '' : note.memo;
  if (typeof memo !== 'string') fail('memo must be a string');
  const memoBytes = utf8(memo);
  if (memoBytes.length > GHOST_NOTE_MAX_MEMO_BYTES) fail('memo is too long');
  return {
    value,
    rho: note.rho,
    rcm: note.rcm,
    memo,
    memoBytes,
    pkD: recipient.pkD,
    diversifier: recipient.diversifier,
  };
}

function serializeNotePlaintext(network, note) {
  const net = networkBytes(network);
  return concat(
    Uint8Array.of(GHOST_WALLET_VERSION, net.length), net,
    note.diversifier, u64(note.value), note.rho, note.rcm, note.pkD,
    u16(note.memoBytes.length), note.memoBytes,
  );
}

function parseNotePlaintext(encoded, expectedNetwork) {
  const reader = new Reader(encoded);
  if (reader.byte('note version') !== GHOST_WALLET_VERSION) fail('note version is unsupported');
  const network = fromUtf8(reader.take(reader.byte('note network length'), 'note network'));
  networkBytes(network);
  if (network !== expectedNetwork) fail('encrypted note belongs to a different network');
  const diversifier = reader.take(GHOST_DIVERSIFIER_BYTES, 'note diversifier');
  const value = reader.uint64('note value');
  if (value > GHOST_NOTE_MAX_VALUE) fail('decrypted note value is out of range');
  const rho = reader.take(GHOST_POOL_VALUE_BYTES, 'note rho');
  const rcm = reader.take(GHOST_POOL_VALUE_BYTES, 'note rcm');
  const pkD = reader.take(GHOST_POOL_VALUE_BYTES, 'note pk_d');
  assertCanonicalPoolValue(rho, 'note rho');
  assertCanonicalPoolValue(rcm, 'note rcm');
  assertCanonicalPoolValue(pkD, 'note pk_d');
  const memoLength = reader.uint16('note memo length');
  if (memoLength > GHOST_NOTE_MAX_MEMO_BYTES) fail('decrypted note memo is too long');
  const memo = fromUtf8(reader.take(memoLength, 'note memo'));
  reader.finish();
  return { version: GHOST_WALLET_VERSION, network, diversifier, value, rho, rcm, pkD, memo };
}

function noteAad(network, commitment, role) {
  const net = networkBytes(network);
  return concat(NOTE_AAD_DOMAIN, Uint8Array.of(role, net.length), net, commitment);
}

function noteKey(sharedSecret, network, commitment, role) {
  const net = networkBytes(network);
  return hkdf(
    sha256,
    bytes(sharedSecret, 'ML-KEM shared secret', 32),
    commitment,
    concat(NOTE_KDF_DOMAIN, Uint8Array.of(role, net.length), net),
    32,
  );
}

function encryptSection(publicKey, plaintext, network, commitment, role) {
  const { cipherText, sharedSecret } = ml_kem768.encapsulate(publicKey);
  const nonce = randomBytes(12);
  const ciphertext = gcm(
    noteKey(sharedSecret, network, commitment, role), nonce,
    noteAad(network, commitment, role),
  ).encrypt(plaintext);
  return { cipherText, nonce, ciphertext };
}

function serializeEnvelope(recipientSection, outgoingSection) {
  const result = concat(
    NOTE_ENVELOPE_MAGIC,
    Uint8Array.of(GHOST_WALLET_VERSION),
    recipientSection.cipherText, recipientSection.nonce,
    u32(recipientSection.ciphertext.length), recipientSection.ciphertext,
    outgoingSection.cipherText, outgoingSection.nonce,
    u32(outgoingSection.ciphertext.length), outgoingSection.ciphertext,
  );
  if (result.length > GHOST_MAX_ENCRYPTED_NOTE_BYTES) fail('encrypted note exceeds consensus limit');
  return result;
}

function parseEnvelope(encoded) {
  if (encoded.length > GHOST_MAX_ENCRYPTED_NOTE_BYTES) fail('encrypted note exceeds consensus limit');
  const reader = new Reader(encoded);
  if (!equal(reader.take(NOTE_ENVELOPE_MAGIC.length, 'note envelope magic'), NOTE_ENVELOPE_MAGIC)) {
    fail('note envelope magic is invalid');
  }
  if (reader.byte('note envelope version') !== GHOST_WALLET_VERSION) {
    fail('note envelope version is unsupported');
  }
  const section = (label) => {
    const cipherText = reader.take(GHOST_KEM_CIPHERTEXT_BYTES, `${label} KEM ciphertext`);
    const nonce = reader.take(12, `${label} nonce`);
    const ciphertext = reader.take(reader.uint32(`${label} ciphertext length`), `${label} ciphertext`);
    if (ciphertext.length < 16) fail(`${label} ciphertext is too short`);
    return { cipherText, nonce, ciphertext };
  };
  const recipient = section('recipient');
  const outgoing = section('outgoing');
  reader.finish();
  return { recipient, outgoing };
}

/** Create one commitment-bound recipient + outgoing-recovery ciphertext. */
export async function createEncryptedGhostOutput({
  receiver,
  senderOutgoingViewingPublicKey,
  value,
  memo = '',
  bridge,
  rho = null,
  rcm = null,
}) {
  requireLocalBridge(bridge, ['commitNote']);
  const recipient = typeof receiver === 'string' ? decodeGhostReceiver(receiver) : receiver;
  const note = validateNote({
    value,
    memo,
    rho: rho || randomCanonicalFieldValue(),
    rcm: rcm || randomCanonicalFieldValue(),
  }, recipient);
  bytes(
    senderOutgoingViewingPublicKey,
    'outgoing viewing public key',
    GHOST_KEM_PUBLIC_KEY_BYTES,
  );
  const commitment = await bridge.commitNote({
    value: note.value,
    pkD: note.pkD.slice(),
    rho: note.rho.slice(),
    rcm: note.rcm.slice(),
  });
  assertCanonicalPoolValue(commitment, 'bridge commitment');
  const plaintext = serializeNotePlaintext(recipient.network, note);
  const recipientSection = encryptSection(
    recipient.incomingViewingPublicKey, plaintext, recipient.network, commitment, 1,
  );
  const outgoingSection = encryptSection(
    senderOutgoingViewingPublicKey, plaintext, recipient.network, commitment, 2,
  );
  return {
    commitment,
    encNote: serializeEnvelope(recipientSection, outgoingSection),
    note,
  };
}

async function decryptAndValidate({ section, role, secretKey, network, commitment, bridge }) {
  requireLocalBridge(bridge, ['commitNote']);
  bytes(secretKey, 'viewing secret key', GHOST_KEM_SECRET_KEY_BYTES);
  assertCanonicalPoolValue(commitment, 'commitment');
  let plaintext;
  try {
    const sharedSecret = ml_kem768.decapsulate(section.cipherText, secretKey);
    plaintext = gcm(
      noteKey(sharedSecret, network, commitment, role), section.nonce,
      noteAad(network, commitment, role),
    ).decrypt(section.ciphertext);
  } catch (_error) {
    return null;
  }
  let note;
  try {
    note = parseNotePlaintext(plaintext, network);
    const recomputed = await bridge.commitNote({
      value: note.value,
      pkD: note.pkD.slice(),
      rho: note.rho.slice(),
      rcm: note.rcm.slice(),
    });
    assertCanonicalPoolValue(recomputed, 'bridge commitment');
    if (!equal(recomputed, commitment)) return null;
  } catch (_error) {
    return null;
  }
  return note;
}

/** Trial-decrypt one output as its recipient. Non-owned/tampered outputs return null. */
export async function scanGhostOutput({ commitment, encNote, secretMaterial, network, bridge }) {
  const envelope = parseEnvelope(bytes(encNote, 'encrypted note'));
  const note = await decryptAndValidate({
    section: envelope.recipient,
    role: 1,
    secretKey: secretMaterial?.incomingViewingSecretKey,
    network,
    commitment,
    bridge,
  });
  if (note && !equal(note.diversifier, secretMaterial?.diversifier)) return null;
  return note;
}

/** Recover a sent note from its outgoing-view ciphertext. */
export async function recoverOutgoingGhostOutput({
  commitment, encNote, secretMaterial, network, bridge,
}) {
  const envelope = parseEnvelope(bytes(encNote, 'encrypted note'));
  return decryptAndValidate({
    section: envelope.outgoing,
    role: 2,
    secretKey: secretMaterial?.outgoingViewingSecretKey,
    network,
    commitment,
    bridge,
  });
}

export function randomCanonicalFieldValue() {
  const result = new Uint8Array(GHOST_POOL_VALUE_BYTES);
  for (let limb = 0; limb < 4; limb += 1) {
    while (true) {
      const candidate = randomBytes(8);
      const value = new DataView(
        candidate.buffer, candidate.byteOffset, candidate.byteLength,
      ).getBigUint64(0, true);
      if (value < GOLDILOCKS_MODULUS) {
        result.set(candidate, limb * 8);
        break;
      }
    }
  }
  return result;
}
