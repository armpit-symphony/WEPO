import {
  refreshGhostWitnesses,
  validateGhostWalletState,
} from './ghostWalletState.js';
import { hexToBytes } from './wepoSigner.js';

const LOCAL_BRIDGE_KIND = 'wepo-local-ghost-crypto-v1';
const WITNESS_FORMAT = 'wepo-ghost-witness-v1';
const MERKLE_PATH_DEPTH = 32;
const HEX_32 = /^[0-9a-f]{64}$/u;

function fail(reason) {
  throw new Error(`Ghost witness refresh: ${reason}`);
}

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function assertHex(value, name) {
  if (typeof value !== 'string' || !HEX_32.test(value)) fail(`${name} is invalid`);
  return value;
}

function decodeWitness(payload, note, expectedTip) {
  if (!isRecord(payload) || payload.format !== WITNESS_FORMAT
      || payload.commitment !== note.commitment) {
    fail('witness response is not bound to the requested note');
  }
  if (!isRecord(payload.chain_tip)
      || payload.chain_tip.height !== expectedTip.height
      || payload.chain_tip.hash !== expectedTip.hash) {
    fail('chain tip changed during witness refresh');
  }
  assertHex(payload.anchor, 'witness anchor');
  if (!Number.isSafeInteger(payload.position)
      || payload.position < 0 || payload.position > 0xffffffff
      || !Array.isArray(payload.siblings)
      || payload.siblings.length !== MERKLE_PATH_DEPTH
      || payload.siblings.some((sibling) => !HEX_32.test(sibling))) {
    fail('witness path is malformed');
  }
  return {
    anchor: payload.anchor,
    position: payload.position,
    siblings: payload.siblings,
  };
}

/**
 * Fetch and locally verify witnesses for every unspent durable note.
 * `fetchWitness` must return the parsed response from `/api/shielded/witness`.
 * A chain-tip race or any bridge rejection leaves the input state unchanged.
 */
export async function refreshGhostWitnessesFromNode({ state, fetchWitness, bridge }) {
  const validated = validateGhostWalletState(state);
  if (typeof fetchWitness !== 'function') fail('a witness source is required');
  if (!bridge || bridge.kind !== LOCAL_BRIDGE_KIND || bridge.localOnly !== true
      || typeof bridge.verifyMerklePath !== 'function') {
    fail('the audited local bridge must verify Merkle witnesses');
  }
  const unspent = validated.notes.filter((note) => !note.spent);
  if (unspent.length > 0 && validated.tip.height < 0) {
    fail('unspent notes cannot be refreshed without a canonical chain tip');
  }

  const updates = [];
  const verified = new Set();
  for (const note of unspent) {
    const payload = await fetchWitness({ commitment: note.commitment });
    const witness = decodeWitness(payload, note, validated.tip);
    const accepted = await bridge.verifyMerklePath({
      commitment: hexToBytes(note.commitment),
      anchor: hexToBytes(witness.anchor),
      position: witness.position,
      siblings: witness.siblings.map((sibling) => hexToBytes(sibling)),
    });
    if (accepted !== true) fail('local bridge rejected a witness');
    verified.add(note.commitment);
    updates.push({ commitment: note.commitment, witness });
  }

  return refreshGhostWitnesses(
    validated,
    updates,
    async (note, _witness, tip) => verified.has(note.commitment)
      && tip.height === validated.tip.height
      && tip.hash === validated.tip.hash,
  );
}
