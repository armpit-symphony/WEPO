import { validateGhostWalletState } from './ghostWalletState.js';
import { bytesToHex, hexToBytes } from './wepoSigner.js';

const LOCAL_BRIDGE_KIND = 'wepo-local-ghost-crypto-v1';
const MERKLE_PATH_DEPTH = 32;
const MAX_NOTE_VALUE = (1n << 61n) - 1n;

function fail(reason) {
  throw new Error(`Ghost witness builder: ${reason}`);
}

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function asBytes(value, name, length) {
  if (value instanceof Uint8Array) {
    if (value.length !== length) fail(`${name} must be ${length} bytes`);
    return value.slice();
  }
  if (typeof value === 'string' && new RegExp(`^[0-9a-f]{${length * 2}}$`, 'u').test(value)) {
    return hexToBytes(value);
  }
  fail(`${name} must be ${length} bytes`);
}

function equalHex(left, right, name) {
  const actual = bytesToHex(left);
  if (actual !== right) fail(`${name} does not match the transaction`);
}

function validateBridge(bridge) {
  if (!bridge || bridge.kind !== LOCAL_BRIDGE_KIND || bridge.localOnly !== true) {
    fail('the audited local native/WASM bridge is required');
  }
  if (typeof bridge.nullifier !== 'function' || typeof bridge.commitNote !== 'function') {
    fail('the local bridge must expose nullifier and commitNote');
  }
  return bridge;
}

function noteReference(reference) {
  if (typeof reference === 'string') return reference;
  if (isRecord(reference) && typeof reference.commitment === 'string') return reference.commitment;
  fail('each spend note reference must identify a durable note commitment');
}

function validateWitness(witness, anchor) {
  if (!isRecord(witness) || witness.anchor !== anchor
      || !Number.isSafeInteger(witness.position)
      || witness.position < 0 || witness.position > 0xffffffff
      || !Array.isArray(witness.siblings) || witness.siblings.length !== MERKLE_PATH_DEPTH) {
    fail('a spend note has no usable witness for the requested anchor');
  }
  return {
    anchor: witness.anchor,
    position: witness.position,
    siblings: witness.siblings.map((sibling, index) => (
      asBytes(sibling, `Merkle sibling ${index}`, 32)
    )),
  };
}

function validateValue(value, name) {
  let parsed;
  try {
    parsed = BigInt(value);
  } catch (_error) {
    fail(`${name} is invalid`);
  }
  if (parsed < 0n || parsed > MAX_NOTE_VALUE) fail(`${name} is out of range`);
  return parsed;
}

/**
 * Resolve durable note records into the exact bridge witness shape.
 * This function never persists secrets or mutates wallet state. It requires
 * the caller to provide the unlocked spending key and plaintext output notes.
 */
export async function buildGhostBridgeWitness({
  state,
  bundle,
  secretMaterial,
  spendNotes = [],
  outputNotes = [],
  bridge,
}) {
  const validatedState = validateGhostWalletState(state);
  validateBridge(bridge);
  if (!isRecord(bundle) || !Array.isArray(bundle.spends) || !Array.isArray(bundle.outputs)) {
    fail('the public shielded bundle is invalid');
  }
  const spendingKey = asBytes(secretMaterial?.spendingKey, 'spending key', 32);
  if (!Array.isArray(spendNotes) || spendNotes.length !== bundle.spends.length) {
    fail('spend note references must match the transaction spends');
  }

  const notesByCommitment = new Map(
    validatedState.notes.map((note) => [note.commitment, note]),
  );
  const seenSpendCommitments = new Set();
  const spends = [];
  for (let index = 0; index < bundle.spends.length; index += 1) {
    const spend = bundle.spends[index];
    const commitment = noteReference(spendNotes[index]);
    if (seenSpendCommitments.has(commitment)) fail('a note is referenced more than once');
    seenSpendCommitments.add(commitment);
    const note = notesByCommitment.get(commitment);
    if (!note || note.spent) fail('a spend reference is not an unspent durable note');
    const witness = validateWitness(note.witness, spend.anchor);
    const nullifier = await bridge.nullifier({
      spendingKey: spendingKey.slice(),
      rho: asBytes(note.rho, 'note rho', 32),
    });
    equalHex(asBytes(nullifier, 'computed nullifier', 32), spend.nullifier, 'computed nullifier');
    spends.push({
      spendingKey: spendingKey.slice(),
      diversifier: asBytes(note.diversifier, 'note diversifier', 11),
      value: validateValue(note.value, 'note value'),
      rho: asBytes(note.rho, 'note rho', 32),
      rcm: asBytes(note.rcm, 'note rcm', 32),
      position: witness.position,
      siblings: witness.siblings,
    });
  }

  if (!Array.isArray(outputNotes) || outputNotes.length !== bundle.outputs.length) {
    fail('plaintext output notes must match the transaction outputs');
  }
  const outputs = [];
  for (let index = 0; index < bundle.outputs.length; index += 1) {
    const source = outputNotes[index];
    const note = isRecord(source?.note) ? source.note : source;
    if (!isRecord(note)) fail('a plaintext output note is missing');
    const value = validateValue(note.value, 'output note value');
    const pkD = asBytes(note.pkD, 'output pk_d', 32);
    const rho = asBytes(note.rho, 'output rho', 32);
    const rcm = asBytes(note.rcm, 'output rcm', 32);
    const commitment = await bridge.commitNote({
      value,
      pkD: pkD.slice(),
      rho: rho.slice(),
      rcm: rcm.slice(),
    });
    equalHex(asBytes(commitment, 'computed commitment', 32), bundle.outputs[index].commitment,
      'computed commitment');
    outputs.push({ value, pkD, rho, rcm });
  }

  return { spends, outputs };
}
