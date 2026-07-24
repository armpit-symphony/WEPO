/**
 * WEPO client-side signer (self-custody).
 *
 * Implements the wallet side of the spend-authorization model enforced by
 * consensus (see wepo-blockchain/core/blockchain.py):
 *   - keypair: ML-DSA-44 (FIPS 204), deterministically derived from the mnemonic
 *   - address: "wepo1q" + sha256(pubkeyHex)[:39]   (matches generate_wepo_address)
 *   - sighash: SHA256 of the canonical "|"-joined transaction message
 *              (matches Transaction.get_canonical_sighash)
 *   - sign:    ML-DSA-44 over the 32-byte sighash; the node verifies the signature
 *              and that the public key hashes to the spent UTXO's address.
 *
 * Cross-language interop (JS sign -> Python verify), the address derivation, and
 * the canonical sighash are all verified byte-for-byte against the Python node.
 */
import { ml_dsa44 } from '@noble/post-quantum/ml-dsa.js';
import { sha256 } from '@noble/hashes/sha2.js';

// ---- hex / byte helpers ----
export function bytesToHex(bytes) {
  let h = '';
  for (let i = 0; i < bytes.length; i++) h += bytes[i].toString(16).padStart(2, '0');
  return h;
}

export function hexToBytes(hex) {
  if (!hex) return new Uint8Array(0);
  const clean = hex.length % 2 ? '0' + hex : hex;
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(clean.substr(i * 2, 2), 16);
  return out;
}

const utf8 = (str) => new TextEncoder().encode(str);

// sha256 hex of a UTF-8 string (matches Python hashlib.sha256(s.encode()).hexdigest())
function sha256HexOfString(str) {
  return bytesToHex(sha256(utf8(str)));
}

// ---- key derivation ----

/**
 * Deterministically derive the WEPO ML-DSA-44 keypair + address from a mnemonic.
 * The 32-byte ML-DSA seed is domain-separated so it never collides with other
 * key material derived from the same mnemonic (e.g. the BTC path).
 */
export function deriveWepoKeypair(mnemonic, passphrase = '') {
  const seed = sha256(utf8(`${mnemonic}${passphrase}|wepo_mldsa_v1`)); // 32 bytes
  const { publicKey, secretKey } = ml_dsa44.keygen(seed);
  return {
    publicKey,
    secretKey,
    publicKeyHex: bytesToHex(publicKey),
    address: deriveAddress(publicKey),
  };
}

/** address = "wepo1q" + sha256(pubkeyHex)[:39] */
export function deriveAddress(publicKey) {
  const pubHex = bytesToHex(publicKey);
  return 'wepo1q' + sha256HexOfString(pubHex).slice(0, 39);
}

/**
 * Same derivation as deriveAddress but from a hex-encoded public key. Matches the
 * Python node's generate_wepo_address(pubkey_hex, "quantum") used by consensus, so
 * it can be used to verify an ML-DSA-44 public key really owns a given address.
 */
export function deriveAddressFromHex(publicKeyHex) {
  return 'wepo1q' + sha256HexOfString(publicKeyHex).slice(0, 39);
}

// ---- canonical sighash (must match Transaction.get_canonical_sighash) ----

function hexMarkerToText(hex) {
  if (!hex) return '';
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(hexToBytes(hex));
  } catch (e) {
    return hex; // not valid UTF-8 -> hex fallback (matches Python .hex())
  }
}

// json.dumps(obj, sort_keys=True, separators=(",",":")) for flat string/number maps
function canonicalJson(obj) {
  const o = obj || {};
  const keys = Object.keys(o).sort();
  return '{' + keys.map((k) => JSON.stringify(k) + ':' + JSON.stringify(o[k])).join(',') + '}';
}

export function canonicalSighashHex(tx) {
  const parts = [
    'WEPO-SIGHASH-v1',
    String(tx.version),
    String(tx.lock_time),
    String(tx.fee),
    String(tx.tx_type),
  ];
  for (const i of tx.inputs) {
    parts.push(String(i.prev_txid), String(i.prev_vout), String(i.sequence));
  }
  for (const o of tx.outputs) {
    const marker = o.script_pubkey ? hexMarkerToText(o.script_pubkey) : '';
    parts.push(String(o.value), String(o.address), marker);
  }
  parts.push(canonicalJson(tx.extra_data));
  return sha256HexOfString(parts.join('|'));
}

// ---- signing ----

/**
 * Sign every input of an unsigned transaction (single-owner spend) and return
 * the completed transaction ready for POST /api/transaction/send {signed_tx}.
 *
 * If expectedSighashHex is provided (the node's build-unsigned response), the
 * locally recomputed sighash must match it, otherwise we refuse to sign — this
 * prevents a malicious node from getting the wallet to authorize a different tx.
 */
export function signTransaction(unsignedTx, secretKey, publicKey, expectedSighashHex) {
  const localSighashHex = canonicalSighashHex(unsignedTx);
  if (expectedSighashHex && localSighashHex !== expectedSighashHex.toLowerCase()) {
    throw new Error('Refusing to sign: locally computed sighash does not match the node.');
  }
  const sighashBytes = hexToBytes(localSighashHex);
  const sigHex = bytesToHex(ml_dsa44.sign(sighashBytes, secretKey)); // (msg, sk)
  const pubHex = bytesToHex(publicKey);
  return {
    ...unsignedTx,
    inputs: unsignedTx.inputs.map((inp) => ({
      ...inp,
      signature_type: 'dilithium',
      quantum_public_key: pubHex,
      quantum_signature: sigHex,
      script_sig: '',
    })),
  };
}

/**
 * Sign an arbitrary 32-byte digest with the spend key (ML-DSA-44). Used for
 * non-transaction proofs of address ownership (e.g. messaging key registry and
 * inbox-fetch authorization), returned as a hex signature.
 */
export function signDigest(digestBytes, secretKey) {
  return bytesToHex(ml_dsa44.sign(digestBytes, secretKey));
}

/** Optional client-side verification (the node enforces this regardless). */
export function verifyTransactionInput(tx, inputIndex) {
  const inp = tx.inputs[inputIndex];
  if (!inp || inp.signature_type !== 'dilithium') return false;
  const sighashBytes = hexToBytes(canonicalSighashHex(tx));
  return ml_dsa44.verify(
    hexToBytes(inp.quantum_signature),
    sighashBytes,
    hexToBytes(inp.quantum_public_key),
  );
}
