import {
  canonicalSighashHex,
  canonicalTxidHex,
} from './wepoSigner.js';

export const GHOST_TRANSACTION_PLAN_FORMAT = 'wepo-ghost-transaction-plan-v1';
export const GHOST_TRANSACTION_FLOWS = Object.freeze({
  SHIELDING: 'shielding',
  SHIELDED: 'shielded',
  UNSHIELDING: 'unshielding',
});

const MAX_TRANSPARENT_INPUTS = 32;
const MAX_TRANSPARENT_OUTPUTS = 32;
const MAX_SHIELDED_SPENDS = 4;
const MAX_SHIELDED_OUTPUTS = 2;
const MAX_EXTRA_DATA_KEYS = 32;
const MAX_NOTE_BYTES = 4096;
const MAX_PROOF_BYTES = 1024 * 1024;
const MAX_SAFE_ATOMIC = Number.MAX_SAFE_INTEGER;
const I64_MIN = -(1n << 63n);
const I64_MAX = (1n << 63n) - 1n;
const ML_DSA44_PUBLIC_KEY_HEX_LENGTH = 1312 * 2;
const ML_DSA44_SIGNATURE_HEX_LENGTH = 2420 * 2;

function fail(reason) {
  throw new Error(`Refusing Ghost transaction: ${reason}`);
}

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isHex(value, bytes, { allowEmpty = false, exact = true } = {}) {
  if (typeof value !== 'string' || value.length % 2 !== 0) return false;
  if (!allowEmpty && value.length === 0) return false;
  return value.length <= bytes * 2 && /^[0-9a-f]*$/u.test(value)
    && (!exact || value.length === bytes * 2);
}

function isSafeAtomic(value, { allowZero = false } = {}) {
  return Number.isSafeInteger(value)
    && (allowZero ? value >= 0 : value > 0)
    && value <= MAX_SAFE_ATOMIC;
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

function normalizeProof(value) {
  let bytes;
  if (typeof value === 'string') {
    if (!isHex(value, MAX_PROOF_BYTES, { exact: false })) {
      fail('prover returned a malformed proof hex string');
    }
    return value.toLowerCase();
  }
  if (value instanceof Uint8Array) {
    bytes = value;
  } else if (value instanceof ArrayBuffer) {
    bytes = new Uint8Array(value);
  } else if (ArrayBuffer.isView(value)) {
    bytes = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  } else {
    fail('prover returned no proof bytes');
  }
  if (bytes.length < 1 || bytes.length > MAX_PROOF_BYTES) {
    fail('prover returned an empty or oversized proof');
  }
  let hex = '';
  for (const byte of bytes) hex += byte.toString(16).padStart(2, '0');
  return hex;
}

function validateBaseTransaction(transaction, { allowProof }) {
  if (!isRecord(transaction)) fail('transaction is not an object');
  if (transaction.version !== 1 || transaction.lock_time !== 0
      || transaction.tx_type !== 'transfer') {
    fail('Ghost transfers require the canonical transfer version, lock time, and type');
  }
  if (!Number.isSafeInteger(transaction.timestamp) || transaction.timestamp <= 0) {
    fail('transaction timestamp is invalid');
  }
  if (!isSafeAtomic(transaction.fee, { allowZero: true })) {
    fail('transaction fee is invalid');
  }
  if (transaction.privacy_proof != null || transaction.ring_signature != null) {
    fail('legacy privacy fields are not accepted in a Ghost transaction');
  }
  if (!isRecord(transaction.extra_data)
      || Object.keys(transaction.extra_data).length > MAX_EXTRA_DATA_KEYS) {
    fail('transaction metadata is invalid or unbounded');
  }

  if (!Array.isArray(transaction.inputs)
      || transaction.inputs.length > MAX_TRANSPARENT_INPUTS) {
    fail('transparent input count is invalid');
  }
  const outpoints = new Set();
  for (const input of transaction.inputs) {
    if (!isRecord(input) || !isHex(input.prev_txid, 32)
        || !Number.isInteger(input.prev_vout) || input.prev_vout < 0
        || input.prev_vout > 0xffffffff || input.sequence !== 0xffffffff) {
      fail('transparent input is not canonical');
    }
    const outpoint = `${input.prev_txid}:${input.prev_vout}`;
    if (outpoints.has(outpoint)) fail('duplicate transparent input outpoint');
    outpoints.add(outpoint);
    const hasSignature = input.quantum_signature != null || input.quantum_public_key != null;
    if (hasSignature) {
      if (input.signature_type !== 'dilithium'
          || !isHex(input.quantum_public_key, ML_DSA44_PUBLIC_KEY_HEX_LENGTH / 2)
          || !isHex(input.quantum_signature, ML_DSA44_SIGNATURE_HEX_LENGTH / 2)) {
        fail('transparent input signature is malformed');
      }
    } else if (input.quantum_signature != null || input.quantum_public_key != null) {
      fail('transparent input has a partial signature');
    }
  }

  if (!Array.isArray(transaction.outputs)
      || transaction.outputs.length > MAX_TRANSPARENT_OUTPUTS) {
    fail('transparent output count is invalid');
  }
  for (const output of transaction.outputs) {
    if (!isRecord(output) || !isSafeAtomic(output.value)
        || typeof output.address !== 'string'
        || !/^wepo1q[0-9a-f]{39}$/u.test(output.address)
        || typeof output.script_pubkey !== 'string'
        || !isHex(output.script_pubkey, 4096, { allowEmpty: true, exact: false })) {
      fail('transparent output is not canonical');
    }
  }

  const bundle = transaction.shielded_bundle;
  if (!isRecord(bundle)) fail('shielded bundle is missing');
  if (!Array.isArray(bundle.spends) || bundle.spends.length > MAX_SHIELDED_SPENDS
      || !Array.isArray(bundle.outputs) || bundle.outputs.length > MAX_SHIELDED_OUTPUTS) {
    fail('shielded bundle count is invalid');
  }
  if (bundle.spends.length === 0 && bundle.outputs.length === 0) {
    fail('shielded bundle is empty');
  }
  if (!Number.isSafeInteger(bundle.value_balance)) {
    fail('value_balance must be a safe signed integer');
  }
  const balance = BigInt(bundle.value_balance);
  if (balance < I64_MIN || balance > I64_MAX) fail('value_balance is outside signed i64');
  const nullifiers = new Set();
  for (const spend of bundle.spends) {
    if (!isRecord(spend) || !isHex(spend.anchor, 32) || !isHex(spend.nullifier, 32)) {
      fail('shielded spend description is malformed');
    }
    if (nullifiers.has(spend.nullifier)) fail('duplicate shielded nullifier');
    nullifiers.add(spend.nullifier);
  }
  if (bundle.spends.length > 1
      && bundle.spends.some((spend) => spend.anchor !== bundle.spends[0].anchor)) {
    fail('all shielded spends must use one anchor');
  }
  const commitments = new Set();
  for (const output of bundle.outputs) {
    if (!isRecord(output) || !isHex(output.commitment, 32)
        || !isHex(output.enc_note, MAX_NOTE_BYTES, { exact: false })) {
      fail('shielded output description is malformed');
    }
    if (commitments.has(output.commitment)) fail('duplicate shielded commitment');
    commitments.add(output.commitment);
  }
  if (allowProof) {
    if (!isHex(bundle.proof, MAX_PROOF_BYTES, { exact: false })) {
      fail('shielded proof is missing or malformed');
    }
  } else if (bundle.proof != null) {
    fail('unsigned Ghost transaction already contains a proof');
  }
  return bundle;
}

function validateFlow(flow, transaction, bundle) {
  if (!Object.values(GHOST_TRANSACTION_FLOWS).includes(flow)) fail('unknown Ghost flow');
  const hasTransparentInputs = transaction.inputs.length > 0;
  const hasTransparentOutputs = transaction.outputs.length > 0;
  const hasSpends = bundle.spends.length > 0;
  const hasShieldedOutputs = bundle.outputs.length > 0;
  const valueBalance = bundle.value_balance;
  if (flow === GHOST_TRANSACTION_FLOWS.SHIELDING
      && (!hasTransparentInputs || hasSpends || !hasShieldedOutputs || valueBalance <= 0)) {
    fail('shielding requires transparent inputs, shielded outputs, and positive value_balance');
  }
  if (flow === GHOST_TRANSACTION_FLOWS.SHIELDED
      && (hasTransparentInputs || !hasSpends || !hasShieldedOutputs || valueBalance !== 0
        || transaction.fee !== 0)) {
    fail('shielded transfer requires pool-only inputs/outputs, zero value_balance, and zero fee');
  }
  if (flow === GHOST_TRANSACTION_FLOWS.UNSHIELDING
      && (hasTransparentInputs || !hasSpends || !hasTransparentOutputs || valueBalance >= 0)) {
    fail('unshielding requires shielded spends, transparent outputs, and negative value_balance');
  }
}

export function assertGhostTransactionShape(transaction, flow, { allowProof = true } = {}) {
  const bundle = validateBaseTransaction(transaction, { allowProof });
  validateFlow(flow, transaction, bundle);
  return true;
}

/**
 * Build a Ghost plan only after the exact public transaction skeleton has been
 * validated and a local prover has produced a proof for its exact sighash.
 * `proveBundle` must return { proof, sighash }; a raw proof is rejected so a
 * caller cannot accidentally omit the transaction-binding assertion.
 */
export async function createGhostTransactionPlan({
  flow,
  unsignedTx,
  network,
  proveBundle,
}) {
  if (typeof network !== 'string' || network.length < 1) fail('network is missing');
  if (typeof proveBundle !== 'function') fail('a local proof producer is required');
  assertGhostTransactionShape(unsignedTx, flow, { allowProof: false });
  const tx = cloneJson(unsignedTx);
  const sighash = canonicalSighashHex(tx, network);
  const result = await proveBundle({
    sighash,
    transaction: cloneJson(tx),
    bundle: cloneJson(tx.shielded_bundle),
  });
  if (!isRecord(result) || result.sighash !== sighash) {
    fail('prover did not explicitly bind its proof to the requested sighash');
  }
  const proof = normalizeProof(result.proof);
  const transaction = {
    ...tx,
    shielded_bundle: { ...tx.shielded_bundle, proof },
  };
  assertGhostTransactionShape(transaction, flow, { allowProof: true });
  if (canonicalSighashHex(transaction, network) !== sighash) {
    fail('attaching the proof changed the canonical sighash');
  }
  return {
    format: GHOST_TRANSACTION_PLAN_FORMAT,
    flow,
    network,
    sighash,
    txid: canonicalTxidHex(transaction),
    transaction,
  };
}

/** Re-check a plan immediately before signing/submission and reject mutation. */
export function assertGhostTransactionPlan(plan, candidate) {
  if (!isRecord(plan) || plan.format !== GHOST_TRANSACTION_PLAN_FORMAT
      || typeof plan.network !== 'string' || typeof plan.sighash !== 'string'
      || !isHex(plan.sighash, 32)) {
    fail('transaction plan envelope is malformed');
  }
  assertGhostTransactionShape(candidate, plan.flow, { allowProof: true });
  if (canonicalSighashHex(candidate, plan.network) !== plan.sighash) {
    fail('candidate transaction does not match the planned canonical sighash');
  }
  if (candidate.shielded_bundle.proof !== plan.transaction?.shielded_bundle?.proof) {
    fail('candidate transaction proof differs from the planned proof');
  }
  return true;
}
