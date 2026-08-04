import { describe, expect, it } from 'vitest';

import {
  applyGhostCanonicalBlock,
  createEmptyGhostWalletState,
  disconnectGhostToHeight,
  loadGhostWalletState,
  refreshGhostWitnesses,
  saveGhostWalletState,
} from './ghostWalletState.js';

const H0 = '00'.repeat(32);
const H1 = '11'.repeat(32);
const H2 = '22'.repeat(32);
const TX0 = 'aa'.repeat(32);
const COMMITMENT = 'bb'.repeat(32);
const NULLIFIER = 'cc'.repeat(32);
const ENCRYPTED = 'YQ';

function output(commitment = COMMITMENT) {
  return { commitment, encNote: ENCRYPTED, txid: TX0, outputIndex: 0 };
}

function note() {
  return {
    value: 7n,
    rho: new Uint8Array(32).fill(1),
    rcm: new Uint8Array(32).fill(2),
    pkD: new Uint8Array(32).fill(3),
    diversifier: new Uint8Array(11).fill(4),
    memo: 'durable',
  };
}

function witness() {
  return { anchor: H1, position: 0, siblings: Array.from({ length: 32 }, () => H0) };
}

describe('Ghost durable wallet state', () => {
  it('scans notes atomically, tracks spends, and rolls back a disconnect', async () => {
    let state = createEmptyGhostWalletState();
    state = await applyGhostCanonicalBlock(state, {
      height: 0, hash: H1, parentHash: null, outputs: [output()], nullifiers: [],
    }, async () => note());
    state.notes[0].nullifier = NULLIFIER;
    state = await applyGhostCanonicalBlock(state, {
      height: 1, hash: H2, parentHash: H1, outputs: [], nullifiers: [NULLIFIER],
    }, async () => null);
    expect(state.notes[0].spent).toBe(true);
    state = disconnectGhostToHeight(state, 0);
    expect(state.notes).toHaveLength(1);
    expect(state.notes[0].spent).toBe(false);
    state = disconnectGhostToHeight(state, -1);
    expect(state.notes).toHaveLength(0);
    expect(state.tip.hash).toBeNull();
  });

  it('rejects non-contiguous or wrong-parent canonical blocks', async () => {
    const state = createEmptyGhostWalletState();
    await expect(applyGhostCanonicalBlock(state, {
      height: 1, hash: H1, parentHash: H0, outputs: [], nullifiers: [],
    }, async () => null)).rejects.toThrow('next canonical height');
  });

  it('requires an explicit witness verifier and preserves secure-storage boundaries', async () => {
    let state = await applyGhostCanonicalBlock(createEmptyGhostWalletState(), {
      height: 0, hash: H1, parentHash: null, outputs: [output()], nullifiers: [],
    }, async () => note());
    state = await refreshGhostWitnesses(
      state,
      [{ commitment: COMMITMENT, witness: witness() }],
      async () => true,
    );
    expect(state.notes[0].witness.anchor).toBe(H1);
    await expect(refreshGhostWitnesses(state, [], null)).rejects.toThrow('local verifier');

    const values = new Map();
    const storage = {
      setSecureItem: (key, value) => { values.set(key, value); return true; },
      getSecureItem: (key) => values.get(key),
    };
    saveGhostWalletState(storage, 'password', state);
    expect(loadGhostWalletState(storage, 'password').tip.hash).toBe(H1);
  });
});
