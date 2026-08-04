import { GHOST_LOCAL_CRYPTO_BRIDGE_KIND } from './wepoGhost.js';

const REQUEST_MAGIC = new TextEncoder().encode('WEPO_GHOST_WALLET_V1\0');
const RESPONSE_MAGIC = new TextEncoder().encode('WEPO_GHOST_WALLET_R1\0');
const MAX_REQUEST_BYTES = 64 * 1024;
const MAX_RESPONSE_BYTES = 1024 * 1024 + 4096;
const MERKLE_PATH_DEPTH = 32;

const OP_DERIVE_DIVERSIFIED_KEY = 1;
const OP_COMMIT_NOTE = 2;
const OP_NULLIFIER = 3;
const OP_PROVE_BUNDLE = 4;
const OP_VERIFY_MERKLE_PATH = 5;

function fail(message) {
  throw new Error('Ghost wallet bridge: ' + message);
}

function asBytes(value, name, length = null) {
  if (!(value instanceof Uint8Array)) fail(name + ' must be Uint8Array');
  if (length !== null && value.length !== length) fail(name + ' must be ' + length + ' bytes');
  return value;
}

function concat(...parts) {
  const result = new Uint8Array(parts.reduce((total, part) => total + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    result.set(part, offset);
    offset += part.length;
  }
  return result;
}

function u32(value) {
  if (!Number.isInteger(value) || value < 0 || value > 0xffffffff) fail('u32 is invalid');
  const result = new Uint8Array(4);
  new DataView(result.buffer).setUint32(0, value, true);
  return result;
}

function u64(value) {
  const parsed = BigInt(value);
  if (parsed < 0n || parsed > ((1n << 64n) - 1n)) fail('u64 is invalid');
  const result = new Uint8Array(8);
  new DataView(result.buffer).setBigUint64(0, parsed, true);
  return result;
}

function requestBytes(operation, ...parts) {
  const request = concat(REQUEST_MAGIC, Uint8Array.of(operation), ...parts);
  if (request.length > MAX_REQUEST_BYTES) fail('request is too large');
  return request;
}

function asResponseBytes(value) {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }
  fail('response is not bytes');
}

function decodeResponse(value) {
  const response = asResponseBytes(value);
  if (response.length > MAX_RESPONSE_BYTES || response.length < RESPONSE_MAGIC.length + 5) {
    fail('response is out of bounds');
  }
  const magic = response.slice(0, RESPONSE_MAGIC.length);
  if (magic.some((byte, index) => byte !== RESPONSE_MAGIC[index])) fail('response magic is invalid');
  const status = response[RESPONSE_MAGIC.length];
  const payloadLength = new DataView(
    response.buffer,
    response.byteOffset + RESPONSE_MAGIC.length + 1,
    4,
  ).getUint32(0, true);
  const payloadStart = RESPONSE_MAGIC.length + 5;
  if (payloadLength !== response.length - payloadStart) fail('response length is invalid');
  if (status !== 0) fail('request was rejected');
  return response.slice(payloadStart);
}

function getNativeRequester(requester) {
  if (requester) return requester;
  if (typeof window !== 'undefined' && window.electronAPI
      && typeof window.electronAPI.ghostWalletRequest === 'function') {
    return window.electronAPI.ghostWalletRequest;
  }
  fail('audited native/WASM transport is unavailable');
}

function createRequester(requester) {
  const send = getNativeRequester(requester);
  return async (request) => decodeResponse(await send(request));
}

function encodeBundle(bundle) {
  const spends = Array.isArray(bundle?.spends) ? bundle.spends : [];
  const outputs = Array.isArray(bundle?.outputs) ? bundle.outputs : [];
  if (spends.length > 4 || outputs.length > 2 || (spends.length === 0 && outputs.length === 0)) {
    fail('bundle shape is invalid');
  }
  const valueBalance = new DataView(new ArrayBuffer(8));
  valueBalance.setBigInt64(0, BigInt(bundle.valueBalance), true);
  const prefix = concat(
    Uint8Array.of(spends.length, outputs.length),
    new Uint8Array(valueBalance.buffer),
    asBytes(bundle.sighash, 'sighash', 32),
  );
  const spendParts = spends.map((spend) => {
    const siblings = Array.isArray(spend.siblings) ? spend.siblings : [];
    if (siblings.length !== MERKLE_PATH_DEPTH) fail('Merkle path is invalid');
    return concat(
      asBytes(spend.spendingKey, 'spending key', 32),
      asBytes(spend.diversifier, 'diversifier', 11),
      u64(spend.value),
      asBytes(spend.rho, 'rho', 32),
      asBytes(spend.rcm, 'rcm', 32),
      u32(spend.position),
      ...siblings.map((sibling) => asBytes(sibling, 'Merkle sibling', 32)),
    );
  });
  const outputParts = outputs.map((output) => concat(
    u64(output.value),
    asBytes(output.pkD, 'output pk_d', 32),
    asBytes(output.rho, 'output rho', 32),
    asBytes(output.rcm, 'output rcm', 32),
  ));
  return concat(prefix, ...spendParts, ...outputParts);
}

export function createGhostBridge(requester = null) {
  const request = createRequester(requester);
  return {
    kind: GHOST_LOCAL_CRYPTO_BRIDGE_KIND,
    localOnly: true,
    deriveDiversifiedKey: async ({ spendingKey, diversifier }) => (
      request(requestBytes(
        OP_DERIVE_DIVERSIFIED_KEY,
        asBytes(spendingKey, 'spending key', 32),
        asBytes(diversifier, 'diversifier', 11),
      )).then((payload) => asBytes(payload, 'pk_d', 32))
    ),
    commitNote: async ({ value, pkD, rho, rcm }) => (
      request(requestBytes(
        OP_COMMIT_NOTE,
        u64(value),
        asBytes(pkD, 'pk_d', 32),
        asBytes(rho, 'rho', 32),
        asBytes(rcm, 'rcm', 32),
      )).then((payload) => asBytes(payload, 'commitment', 32))
    ),
    nullifier: async ({ spendingKey, rho }) => (
      request(requestBytes(
        OP_NULLIFIER,
        asBytes(spendingKey, 'spending key', 32),
        asBytes(rho, 'rho', 32),
      )).then((payload) => asBytes(payload, 'nullifier', 32))
    ),
    verifyMerklePath: async ({ commitment, anchor, position, siblings }) => {
      const path = Array.isArray(siblings) ? siblings : [];
      if (path.length !== MERKLE_PATH_DEPTH) fail('Merkle path is invalid');
      const payload = await request(requestBytes(
        OP_VERIFY_MERKLE_PATH,
        asBytes(commitment, 'commitment', 32),
        asBytes(anchor, 'anchor', 32),
        u32(position),
        ...path.map((sibling) => asBytes(sibling, 'Merkle sibling', 32)),
      ));
      if (payload.length !== 1 || payload[0] !== 1) fail('Merkle witness was rejected');
      return true;
    },
    proveBundle: async (bundle) => request(requestBytes(OP_PROVE_BUNDLE, encodeBundle(bundle))),
  };
}

export function hasGhostBridge() {
  return typeof window !== 'undefined'
    && typeof window.electronAPI?.ghostWalletRequest === 'function';
}
