/**
 * WEPO client-side signer (self-custody).
 *
 * Implements the wallet side of the spend-authorization model enforced by
 * consensus (see wepo-blockchain/core/blockchain.py):
 *   - keypair: ML-DSA-44 (FIPS 204), deterministically derived from the mnemonic
 *   - address: "wepo1q" + sha256(pubkeyHex)[:39]   (matches generate_wepo_address)
 *   - sighash: SHA256 of versioned, length-prefixed canonical transaction JSON
 *              (matches Transaction.get_canonical_sighash byte-for-byte)
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

// Python compares Unicode strings by scalar value. JavaScript's default sort
// compares UTF-16 code units, which differs for some non-BMP metadata keys.
function pythonStringCompare(left, right) {
  const a = Array.from(left, (char) => char.codePointAt(0));
  const b = Array.from(right, (char) => char.codePointAt(0));
  const length = Math.min(a.length, b.length);
  for (let index = 0; index < length; index++) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return a.length - b.length;
}

// Python json.dumps(value, sort_keys=True, separators=(",",":"), ensure_ascii=False).
// Consensus metadata is JSON data; object keys are sorted recursively.
function canonicalJson(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) {
    return '[' + value.map((item) => canonicalJson(item)).join(',') + ']';
  }
  if (typeof value === 'object') {
    const keys = Object.keys(value).sort(pythonStringCompare);
    return '{' + keys
      .map((key) => JSON.stringify(key) + ':' + canonicalJson(value[key]))
      .join(',') + '}';
  }
  return JSON.stringify(value);
}

function canonicalShieldedBundle(bundle) {
  if (!bundle) return null;
  return {
    spends: (bundle.spends || []).map((spend) => ({
      anchor: String(spend.anchor || '').toLowerCase(),
      nullifier: String(spend.nullifier || '').toLowerCase(),
    })),
    outputs: (bundle.outputs || []).map((output) => ({
      commitment: String(output.commitment || '').toLowerCase(),
      enc_note: String(output.enc_note || '').toLowerCase(),
    })),
    value_balance: bundle.value_balance,
  };
}


function canonicalFullShieldedBundle(bundle) {
  if (!bundle) return null;
  return {
    spends: (bundle.spends || []).map((spend) => ({
      anchor: String(spend.anchor || '').toLowerCase(),
      nullifier: String(spend.nullifier || '').toLowerCase(),
    })),
    outputs: (bundle.outputs || []).map((output) => ({
      commitment: String(output.commitment || '').toLowerCase(),
      enc_note: String(output.enc_note || '').toLowerCase(),
    })),
    value_balance: bundle.value_balance,
    proof: String(bundle.proof || '').toLowerCase(),
  };
}

function canonicalTransactionObject(tx) {
  return {
    version: tx.version,
    lock_time: tx.lock_time,
    fee: tx.fee,
    tx_type: tx.tx_type,
    timestamp: tx.timestamp,
    extra_data: tx.extra_data || {},
    privacy_proof: tx.privacy_proof || null,
    ring_signature: tx.ring_signature || null,
    shielded_bundle: canonicalFullShieldedBundle(tx.shielded_bundle),
    inputs: tx.inputs.map((input) => ({
      prev_txid: input.prev_txid,
      prev_vout: input.prev_vout,
      sequence: input.sequence,
      script_sig: String(input.script_sig || '').toLowerCase(),
      signature_type: input.signature_type || 'ecdsa',
      quantum_signature: input.quantum_signature
        ? String(input.quantum_signature).toLowerCase()
        : null,
      quantum_public_key: input.quantum_public_key
        ? String(input.quantum_public_key).toLowerCase()
        : null,
    })),
    outputs: tx.outputs.map((output) => ({
      value: output.value,
      address: output.address,
      script_pubkey: String(output.script_pubkey || '').toLowerCase(),
    })),
  };
}
function canonicalSighashObject(tx) {
  return {
    version: tx.version,
    lock_time: tx.lock_time,
    timestamp: tx.timestamp,
    fee: tx.fee,
    tx_type: tx.tx_type,
    inputs: tx.inputs.map((input) => ({
      prev_txid: input.prev_txid,
      prev_vout: input.prev_vout,
      sequence: input.sequence,
    })),
    outputs: tx.outputs.map((output) => ({
      value: output.value,
      address: output.address,
      script_pubkey: String(output.script_pubkey || '').toLowerCase(),
    })),
    shielded_bundle: canonicalShieldedBundle(tx.shielded_bundle),
    extra_data: tx.extra_data || {},
  };
}

function domainSeparatedMaterial(domainText, value) {
  const payload = utf8(canonicalJson(value));
  const domain = utf8(domainText);
  const preimage = new Uint8Array(domain.length + 4 + payload.length);
  preimage.set(domain, 0);
  new DataView(preimage.buffer).setUint32(domain.length, payload.length, true);
  preimage.set(payload, domain.length + 4);
  return { payload, preimage };
}

export function canonicalSighashMaterialHex(tx, network) {
  if (typeof network !== 'string' || network.length < 1 || network.length > 32
      || !/^[\x00-\x7f]+$/.test(network)) {
    throw new Error('Transaction signing network is invalid');
  }
  const payload = utf8(canonicalJson(canonicalSighashObject(tx)));
  const domain = utf8('WEPO_SIGHASH_V3\u0000');
  const networkBytes = utf8(network);
  const preimage = new Uint8Array(
    domain.length + 4 + networkBytes.length + 4 + payload.length,
  );
  preimage.set(domain, 0);
  const view = new DataView(preimage.buffer);
  view.setUint32(domain.length, networkBytes.length, true);
  preimage.set(networkBytes, domain.length + 4);
  const payloadLengthOffset = domain.length + 4 + networkBytes.length;
  view.setUint32(payloadLengthOffset, payload.length, true);
  preimage.set(payload, payloadLengthOffset + 4);
  return {
    payload: bytesToHex(payload),
    preimage: bytesToHex(preimage),
    digest: bytesToHex(sha256(preimage)),
  };
}

export function canonicalSighashHex(tx, network) {
  return canonicalSighashMaterialHex(tx, network).digest;
}

export function canonicalTransactionMaterialHex(tx) {
  const { payload, preimage } = domainSeparatedMaterial(
    'WEPO_TXID_V2\u0000',
    canonicalTransactionObject(tx),
  );
  return {
    payload: bytesToHex(payload),
    preimage: bytesToHex(preimage),
    txid: bytesToHex(sha256(preimage)),
  };
}

export function canonicalTxidHex(tx) {
  return canonicalTransactionMaterialHex(tx).txid;
}

const ML_DSA44_PUBLIC_KEY_HEX_LENGTH = 1312 * 2;
const ML_DSA44_SIGNATURE_HEX_LENGTH = 2420 * 2;

export function estimateSignedTransactionWireSize(unsignedTx) {
  if (!unsignedTx || !Array.isArray(unsignedTx.inputs) || unsignedTx.inputs.length < 1) {
    throw new Error('Cannot estimate signed size for an invalid transaction');
  }
  const signedShape = {
    ...unsignedTx,
    inputs: unsignedTx.inputs.map((input) => ({
      ...input,
      signature_type: 'dilithium',
      quantum_public_key: '00'.repeat(ML_DSA44_PUBLIC_KEY_HEX_LENGTH / 2),
      quantum_signature: '00'.repeat(ML_DSA44_SIGNATURE_HEX_LENGTH / 2),
      script_sig: '',
    })),
  };
  return utf8(canonicalJson(canonicalTransactionObject(signedShape))).length;
}

// The standard wallet signs only the node builder's narrow, transparent
// transfer shape. Verifying the node's sighash is necessary but not sufficient:
// a compromised builder could return a different self-consistent transaction.
// This guard binds the skeleton to the recipient, amount, fee, and owner/change
// destination the user actually approved before any private-key operation.
export function assertStandardSendIntent(unsignedTx, {
  senderAddress,
  recipientAddress,
  amountAtomic,
  feeAtomic,
}) {
  const fail = (reason) => {
    throw new Error(`Refusing to sign: ${reason}`);
  };
  const isSafeAtomic = (value) => Number.isSafeInteger(value) && value > 0;
  const isAddress = (value) => /^wepo1q[0-9a-f]{39}$/.test(value);
  const isHex = (value, length) => (
    typeof value === 'string' && value.length === length && /^[0-9a-f]+$/.test(value)
  );

  if (!unsignedTx || typeof unsignedTx !== 'object' || Array.isArray(unsignedTx)) {
    fail('node returned no unsigned transaction object');
  }
  if (!isAddress(senderAddress) || !isAddress(recipientAddress)) {
    fail('send intent contains a non-canonical address');
  }

  let expectedAmount;
  let expectedFee;
  try {
    expectedAmount = BigInt(amountAtomic);
    expectedFee = BigInt(feeAtomic);
  } catch {
    fail('send intent contains an invalid atomic value');
  }
  if (expectedAmount <= 0n || expectedFee < 0n) {
    fail('send intent contains a non-positive amount or negative fee');
  }
  if (expectedAmount > BigInt(Number.MAX_SAFE_INTEGER)
      || expectedFee > BigInt(Number.MAX_SAFE_INTEGER)) {
    fail('send intent exceeds the client integer boundary');
  }

  if (unsignedTx.version !== 1 || unsignedTx.lock_time !== 0
      || unsignedTx.tx_type !== 'transfer') {
    fail('node changed the standard transfer version, lock time, or type');
  }
  if (!Number.isSafeInteger(unsignedTx.timestamp) || unsignedTx.timestamp <= 0) {
    fail('node returned an invalid transaction timestamp');
  }
  if (!Number.isSafeInteger(unsignedTx.fee)
      || BigInt(unsignedTx.fee) !== expectedFee) {
    fail('node changed the approved fee');
  }
  if (unsignedTx.privacy_proof != null || unsignedTx.ring_signature != null
      || unsignedTx.shielded_bundle != null) {
    fail('standard send unexpectedly contains privacy or shielded data');
  }
  if (!unsignedTx.extra_data || typeof unsignedTx.extra_data !== 'object'
      || Array.isArray(unsignedTx.extra_data)
      || Object.keys(unsignedTx.extra_data).length !== 0) {
    fail('standard send unexpectedly contains metadata');
  }

  if (!Array.isArray(unsignedTx.inputs)
      || unsignedTx.inputs.length < 1 || unsignedTx.inputs.length > 32) {
    fail('node returned an invalid input count');
  }
  const outpoints = new Set();
  for (const input of unsignedTx.inputs) {
    if (!input || typeof input !== 'object'
        || !isHex(input.prev_txid, 64)
        || !Number.isInteger(input.prev_vout)
        || input.prev_vout < 0 || input.prev_vout > 0xffffffff
        || input.sequence !== 0xffffffff
        || input.script_sig !== '7369676e61747572655f706c616365686f6c646572'
        || input.signature_type !== 'ecdsa'
        || input.quantum_signature != null
        || input.quantum_public_key != null) {
      fail('node returned a non-canonical unsigned input');
    }
    const outpoint = `${input.prev_txid}:${input.prev_vout}`;
    if (outpoints.has(outpoint)) fail('node returned a duplicate input outpoint');
    outpoints.add(outpoint);
  }

  if (!Array.isArray(unsignedTx.outputs)
      || unsignedTx.outputs.length < 1 || unsignedTx.outputs.length > 2) {
    fail('node returned a non-canonical output count');
  }
  const payment = unsignedTx.outputs[0];
  if (!payment || payment.address !== recipientAddress
      || !isSafeAtomic(payment.value)
      || BigInt(payment.value) !== expectedAmount
      || payment.script_pubkey !== '6f75747075745f736372697074') {
    fail('node changed the approved recipient or amount');
  }
  if (unsignedTx.outputs.length === 2) {
    const change = unsignedTx.outputs[1];
    if (!change || change.address !== senderAddress
        || !isSafeAtomic(change.value)
        || change.script_pubkey !== '6368616e67655f736372697074') {
      fail('node returned change to a non-owner or non-canonical output');
    }
  }
  return true;
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
export function signTransaction(unsignedTx, secretKey, publicKey, expectedSighashHex, network) {
  const localSighashHex = canonicalSighashHex(unsignedTx, network);
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
export function verifyTransactionInput(tx, inputIndex, network) {
  const inp = tx.inputs[inputIndex];
  if (!inp || inp.signature_type !== 'dilithium') return false;
  const sighashBytes = hexToBytes(canonicalSighashHex(tx, network));
  return ml_dsa44.verify(
    hexToBytes(inp.quantum_signature),
    sighashBytes,
    hexToBytes(inp.quantum_public_key),
  );
}
