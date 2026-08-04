import { describe, expect, it } from 'vitest';
import { refreshGhostWitnessesFromNode } from './ghostWitnessRefresh.js';

const commitment = 'a'.repeat(64);
const anchor = 'b'.repeat(64);
const blockHash = 'c'.repeat(64);
const siblings = Array(32).fill('d'.repeat(64));

function state() {
  return {
    format: 'wepo-ghost-wallet-state-v1',
    network: 'test',
    tip: { height: 0, hash: blockHash },
    notes: [{
      commitment,
      txid: '1'.repeat(64),
      outputIndex: 0,
      height: 0,
      blockHash,
      value: '10',
      rho: '2'.repeat(64),
      rcm: '3'.repeat(64),
      pkD: '4'.repeat(64),
      diversifier: '5'.repeat(22),
      encNote: 'AQ',
      spent: false,
    }],
    journal: [{
      height: 0,
      hash: blockHash,
      parentHash: null,
      commitments: [commitment],
      nullifiers: [],
    }],
  };
}

function bridge(accepted = true) {
  return {
    kind: 'wepo-local-ghost-crypto-v1',
    localOnly: true,
    verifyMerklePath: async () => accepted,
  };
}

describe('Ghost witness refresh boundary', () => {
  it('fetches witnesses and stores them only after local bridge verification', async () => {
    const refreshed = await refreshGhostWitnessesFromNode({
      state: state(),
      fetchWitness: async ({ commitment: requested }) => ({
        format: 'wepo-ghost-witness-v1',
        commitment: requested,
        anchor,
        position: 3,
        siblings,
        chain_tip: { height: 0, hash: blockHash },
      }),
      bridge: bridge(),
    });
    expect(refreshed.notes[0].witness).toEqual({ anchor, position: 3, siblings });
  });

  it('rejects a chain-tip race or a bridge rejection without storing a witness', async () => {
    const request = async () => ({
      format: 'wepo-ghost-witness-v1',
      commitment,
      anchor,
      position: 3,
      siblings,
      chain_tip: { height: 1, hash: 'e'.repeat(64) },
    });
    await expect(refreshGhostWitnessesFromNode({
      state: state(), fetchWitness: request, bridge: bridge(),
    })).rejects.toThrow(/chain tip changed/);
    await expect(refreshGhostWitnessesFromNode({
      state: state(),
      fetchWitness: async ({ commitment: requested }) => ({
        format: 'wepo-ghost-witness-v1', commitment: requested, anchor,
        position: 3, siblings, chain_tip: { height: 0, hash: blockHash },
      }),
      bridge: bridge(false),
    })).rejects.toThrow(/bridge rejected/);
  });
});
