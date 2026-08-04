/**
 * Encrypted-wallet state machine for Ghost notes and canonical chain replay.
 *
 * This module stores only encrypted-at-rest wallet state through the caller's
 * secure storage adapter. It never derives a witness from untrusted node data:
 * witness refresh requires an explicit verifier callback.
 */

export const GHOST_WALLET_STATE_FORMAT = 'wepo-ghost-wallet-state-v1';
export const GHOST_WALLET_STATE_KEY = 'ghost_wallet_state';
export const GHOST_MAX_NOTE_RECORDS = 4096;
export const GHOST_MAX_BLOCK_JOURNAL = 4096;
export const GHOST_MAX_OUTPUTS_PER_BLOCK = 4096;
export const GHOST_MERKLE_PATH_DEPTH = 32;

const HEX_32 = /^[0-9a-f]{64}$/u;
const HEX_11 = /^[0-9a-f]{22}$/u;
const BASE64URL = /^[A-Za-z0-9_-]+$/u;

function fail(message) {
  throw new Error(`Ghost wallet state: ${message}`);
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function hex(value, name, length = 32) {
  if (!(value instanceof Uint8Array) || value.length !== length) {
    fail(`${name} must be ${length} bytes`);
  }
  return Array.from(value, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function hexString(value, name, pattern = HEX_32) {
  if (typeof value !== 'string' || !pattern.test(value)) fail(`${name} is invalid`);
  return value;
}

function base64url(value, name) {
  if (!(value instanceof Uint8Array) || value.length === 0) fail(`${name} must be non-empty bytes`);
  let binary = '';
  for (const byte of value) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/u, '');
}

function base64urlString(value, name) {
  if (typeof value !== 'string' || value.length < 1 || !BASE64URL.test(value)) {
    fail(`${name} is invalid`);
  }
  return value;
}

function finiteInteger(value, name, minimum = 0) {
  if (!Number.isSafeInteger(value) || value < minimum) fail(`${name} is invalid`);
  return value;
}

function assertNetwork(network) {
  if (typeof network !== 'string' || !/^[a-z][a-z0-9_-]{0,31}$/u.test(network)) {
    fail('network is invalid');
  }
  return network;
}

function assertWitness(witness) {
  if (!witness || typeof witness !== 'object') fail('witness is invalid');
  hexString(witness.anchor, 'witness anchor');
  finiteInteger(witness.position, 'witness position');
  if (!Array.isArray(witness.siblings) || witness.siblings.length !== GHOST_MERKLE_PATH_DEPTH) {
    fail('witness path depth is invalid');
  }
  witness.siblings.forEach((sibling) => hexString(sibling, 'witness sibling'));
  return witness;
}

function assertNote(note) {
  if (!note || typeof note !== 'object') fail('note is invalid');
  hexString(note.commitment, 'note commitment');
  hexString(note.txid, 'note transaction id');
  finiteInteger(note.outputIndex, 'note output index');
  finiteInteger(note.height, 'note height');
  hexString(note.blockHash, 'note block hash');
  if (typeof note.value !== 'string' || !/^(0|[1-9][0-9]*)$/u.test(note.value)) {
    fail('note value is invalid');
  }
  if (BigInt(note.value) > ((1n << 61n) - 1n)) fail('note value is out of range');
  hexString(note.rho, 'note rho');
  hexString(note.rcm, 'note rcm');
  hexString(note.pkD, 'note pk_d');
  hexString(note.diversifier, 'note diversifier', HEX_11);
  base64urlString(note.encNote, 'note encrypted payload');
  if (typeof note.spent !== 'boolean') fail('note spent flag is invalid');
  if (note.nullifier !== undefined) hexString(note.nullifier, 'note nullifier');
  if (note.spentBy !== undefined) hexString(note.spentBy, 'note spending block');
  if (note.memo !== undefined && typeof note.memo !== 'string') fail('note memo is invalid');
  if (note.witness !== undefined) assertWitness(note.witness);
  return note;
}

function assertBlockJournalEntry(entry) {
  if (!entry || typeof entry !== 'object') fail('block journal entry is invalid');
  finiteInteger(entry.height, 'journal height');
  hexString(entry.hash, 'journal hash');
  if (entry.parentHash !== null) hexString(entry.parentHash, 'journal parent hash');
  if (!Array.isArray(entry.commitments) || entry.commitments.length > GHOST_MAX_OUTPUTS_PER_BLOCK) {
    fail('journal commitments are invalid');
  }
  entry.commitments.forEach((commitment) => hexString(commitment, 'journal commitment'));
  if (!Array.isArray(entry.nullifiers) || entry.nullifiers.length > GHOST_MAX_OUTPUTS_PER_BLOCK) {
    fail('journal nullifiers are invalid');
  }
  entry.nullifiers.forEach((nullifier) => hexString(nullifier, 'journal nullifier'));
  return entry;
}

export function createEmptyGhostWalletState(network = 'mainnet') {
  return {
    format: GHOST_WALLET_STATE_FORMAT,
    network: assertNetwork(network),
    tip: { height: -1, hash: null },
    notes: [],
    journal: [],
  };
}

export function validateGhostWalletState(input) {
  const state = clone(input);
  if (state?.format !== GHOST_WALLET_STATE_FORMAT) fail('state format is unsupported');
  assertNetwork(state.network);
  if (!state.tip || state.tip.height < -1 || !Number.isSafeInteger(state.tip.height)) {
    fail('state tip is invalid');
  }
  if (state.tip.height === -1) {
    if (state.tip.hash !== null) fail('empty state must not have a tip hash');
  } else {
    hexString(state.tip.hash, 'state tip hash');
  }
  if (!Array.isArray(state.notes) || state.notes.length > GHOST_MAX_NOTE_RECORDS) {
    fail('state note count is invalid');
  }
  if (!Array.isArray(state.journal) || state.journal.length > GHOST_MAX_BLOCK_JOURNAL) {
    fail('state journal length is invalid');
  }
  const commitments = new Set();
  state.notes.forEach((note) => {
    assertNote(note);
    if (commitments.has(note.commitment)) fail('duplicate note commitment');
    commitments.add(note.commitment);
  });
  let previousHeight = -1;
  state.journal.forEach((entry) => {
    assertBlockJournalEntry(entry);
    if (entry.height !== previousHeight + 1) fail('journal heights are not contiguous');
    if (entry.height === 0 && entry.parentHash !== null) fail('genesis journal parent is invalid');
    if (entry.height > 0 && entry.parentHash !== state.journal[entry.height - 1].hash) {
      fail('journal parent does not match the prior tip');
    }
    previousHeight = entry.height;
  });
  if (state.tip.height !== previousHeight) fail('tip height does not match the journal');
  if (state.tip.height >= 0 && state.tip.hash !== state.journal.at(-1).hash) {
    fail('tip hash does not match the journal');
  }
  return state;
}

function normalizeOutput(output) {
  if (!output || typeof output !== 'object') fail('chain output is invalid');
  return {
    commitment: hexString(output.commitment, 'output commitment'),
    encNote: output.encNote instanceof Uint8Array
      ? base64url(output.encNote, 'output encrypted note')
      : base64urlString(output.encNote, 'output encrypted note'),
    txid: hexString(output.txid, 'output transaction id'),
    outputIndex: finiteInteger(output.outputIndex, 'output index'),
  };
}

function normalizeScannedNote(note, output, block) {
  if (!note) return null;
  return assertNote({
    commitment: output.commitment,
    txid: output.txid,
    outputIndex: output.outputIndex,
    height: block.height,
    blockHash: block.hash,
    value: String(note.value),
    rho: note.rho instanceof Uint8Array ? hex(note.rho, 'note rho') : note.rho,
    rcm: note.rcm instanceof Uint8Array ? hex(note.rcm, 'note rcm') : note.rcm,
    pkD: note.pkD instanceof Uint8Array ? hex(note.pkD, 'note pk_d') : note.pkD,
    diversifier: note.diversifier instanceof Uint8Array
      ? hex(note.diversifier, 'note diversifier', 11)
      : note.diversifier,
    encNote: output.encNote,
    memo: note.memo,
    nullifier: note.nullifier,
    spent: false,
  });
}

/** Apply one contiguous canonical block atomically after scanning its outputs. */
export async function applyGhostCanonicalBlock(stateInput, blockInput, scanOutput) {
  if (typeof scanOutput !== 'function') fail('a local output scanner is required');
  const state = validateGhostWalletState(stateInput);
  const block = blockInput;
  if (!block || !Number.isSafeInteger(block.height) || block.height !== state.tip.height + 1) {
    fail('block height is not the next canonical height');
  }
  const hash = hexString(block.hash, 'block hash');
  const parentHash = block.height === 0 ? null : hexString(block.parentHash, 'block parent hash');
  if (parentHash !== state.tip.hash) fail('block parent does not match wallet tip');
  if (!Array.isArray(block.outputs) || block.outputs.length > GHOST_MAX_OUTPUTS_PER_BLOCK) {
    fail('block output count is invalid');
  }
  if (!Array.isArray(block.nullifiers)) fail('block nullifiers are invalid');
  const outputs = block.outputs.map(normalizeOutput);
  const knownCommitments = new Set(state.notes.map((note) => note.commitment));
  const discovered = [];
  for (const output of outputs) {
    if (knownCommitments.has(output.commitment)) fail('chain repeated a known commitment');
    const scanned = await scanOutput({ ...output, blockHeight: block.height, blockHash: hash });
    const note = normalizeScannedNote(scanned, output, { height: block.height, hash });
    if (note) {
      knownCommitments.add(note.commitment);
      discovered.push(note);
    }
  }
  const nullifiers = block.nullifiers.map((nullifier) => hexString(nullifier, 'block nullifier'));
  const nullifierSet = new Set(nullifiers);
  for (const note of state.notes) {
    if (note.nullifier && nullifierSet.has(note.nullifier)) {
      note.spent = true;
      note.spentBy = hash;
      note.witness = undefined;
    }
  }
  state.notes.push(...discovered);
  state.journal.push({
    height: block.height,
    hash,
    parentHash,
    commitments: outputs.map((output) => output.commitment),
    nullifiers,
  });
  state.tip = { height: block.height, hash };
  return validateGhostWalletState(state);
}

/** Roll back canonical blocks; notes discovered there disappear and spends revert. */
export function disconnectGhostToHeight(stateInput, targetHeight) {
  const state = validateGhostWalletState(stateInput);
  finiteInteger(targetHeight, 'disconnect height', -1);
  if (targetHeight > state.tip.height) fail('disconnect height is ahead of the wallet tip');
  while (state.tip.height > targetHeight) {
    const removed = state.journal.pop();
    const removedCommitments = new Set(removed.commitments);
    state.notes = state.notes.filter((note) => !removedCommitments.has(note.commitment));
    for (const note of state.notes) {
      if (note.spentBy === removed.hash) {
        note.spent = false;
        delete note.spentBy;
      }
    }
    const prior = state.journal.at(-1);
    state.tip = prior ? { height: prior.height, hash: prior.hash } : { height: -1, hash: null };
  }
  return validateGhostWalletState(state);
}

/** Replace witnesses only after an explicit local verifier accepts every update. */
export async function refreshGhostWitnesses(stateInput, updates, verifyWitness) {
  if (!Array.isArray(updates) || typeof verifyWitness !== 'function') {
    fail('witness updates require a local verifier');
  }
  const state = validateGhostWalletState(stateInput);
  const byCommitment = new Map(state.notes.map((note) => [note.commitment, note]));
  const validated = [];
  for (const update of updates) {
    const note = byCommitment.get(update?.commitment);
    if (!note || note.spent) fail('witness update targets an unavailable note');
    const witness = assertWitness(update.witness);
    if (!await verifyWitness(note, witness, state.tip)) fail('witness verifier rejected an update');
    validated.push([note, clone(witness)]);
  }
  for (const [note, witness] of validated) note.witness = witness;
  return validateGhostWalletState(state);
}

export function saveGhostWalletState(storage, password, state) {
  if (!storage || typeof storage.setSecureItem !== 'function') fail('secure storage adapter is missing');
  const validated = validateGhostWalletState(state);
  if (!storage.setSecureItem(GHOST_WALLET_STATE_KEY, validated, password)) {
    fail('secure state write was rejected');
  }
  return validated;
}

export function loadGhostWalletState(storage, password, network = 'mainnet') {
  if (!storage || typeof storage.getSecureItem !== 'function') fail('secure storage adapter is missing');
  const stored = storage.getSecureItem(GHOST_WALLET_STATE_KEY, password);
  if (stored === null || stored === undefined) return createEmptyGhostWalletState(network);
  const state = validateGhostWalletState(stored);
  if (state.network !== network) fail('stored state belongs to a different network');
  return state;
}
