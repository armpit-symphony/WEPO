import { describe, expect, it } from 'vitest';
import { buildGhostBridgeWitness } from './ghostWitnessBuilder.js';

const anchor = 'a'.repeat(64);
const commitment = 'b'.repeat(64);
const nullifier = 'c'.repeat(64);
const outputCommitment = 'd'.repeat(64);
const sibling = 'e'.repeat(64);

function stateWithWitness() {
  return {
    format: 'wepo-ghost-wallet-state-v1',
    network: 'test',
    tip: { height: 0, hash: 'f'.repeat(64) },
    notes: [{
      commitment,
      txid: '1'.repeat(64),
      outputIndex: 0,
      height: 0,
      blockHash: 'f'.repeat(64),
      value: '12',
      rho: '2'.repeat(64),
      rcm: '3'.repeat(64),
      pkD: '4'.repeat(64),
      diversifier: '5'.repeat(22),
      encNote: 'AQ',
      spent: false,
      nullifier,
      witness: { anchor, position: 7, siblings: Array(32).fill(sibling) },
    }],
    journal: [{
      height: 0,
      hash: 'f'.repeat(64),
      parentHash: null,
      commitments: [commitment],
      nullifiers: [],
    }],
  };
}

function bundle() {
  return {
    spends: [{ anchor, nullifier }],
    outputs: [{ commitment: outputCommitment, enc_note: 'aa' }],
  };
}

function bridge() {
  return {
    kind: 'wepo-local-ghost-crypto-v1',
    localOnly: true,
    nullifier: async () => Uint8Array.from({ length: 32 }, () => 0xcc),
    commitNote: async () => Uint8Array.from({ length: 32 }, () => 0xdd),
  };
}

describe('Ghost durable-note witness construction', () => {
  it('builds bridge spends and outputs from durable notes without mutating state', async () => {
    const state = stateWithWitness();
    const witness = await buildGhostBridgeWitness({
      state,
      bundle: bundle(),
      secretMaterial: { spendingKey: new Uint8Array(32).fill(1) },
      spendNotes: [{ commitment }],
      outputNotes: [{
        value: 13n,
        pkD: new Uint8Array(32).fill(4),
        rho: new Uint8Array(32).fill(2),
        rcm: new Uint8Array(32).fill(3),
      }],
      bridge: bridge(),
    });

    expect(witness.spends).toHaveLength(1);
    expect(witness.spends[0].position).toBe(7);
    expect(witness.spends[0].siblings).toHaveLength(32);
    expect(witness.outputs[0].value).toBe(13n);
    expect(state.notes[0].spent).toBe(false);
    expect(state.notes[0].witness.anchor).toBe(anchor);
  });

  it('rejects a missing witness instead of constructing an unverifiable spend', async () => {
    const state = stateWithWitness();
    delete state.notes[0].witness;
    await expect(buildGhostBridgeWitness({
      state,
      bundle: bundle(),
      secretMaterial: { spendingKey: new Uint8Array(32).fill(1) },
      spendNotes: [{ commitment }],
      outputNotes: [],
      bridge: bridge(),
    })).rejects.toThrow(/no usable witness/);
  });

  it('rejects a nullifier or output commitment that is not bound to the bundle', async () => {
    const badNullifier = { ...bundle(), spends: [{ anchor, nullifier: '9'.repeat(64) }] };
    await expect(buildGhostBridgeWitness({
      state: stateWithWitness(),
      bundle: badNullifier,
      secretMaterial: { spendingKey: new Uint8Array(32).fill(1) },
      spendNotes: [{ commitment }],
      outputNotes: [],
      bridge: bridge(),
    })).rejects.toThrow(/computed nullifier/);

    const badOutput = { ...bundle(), outputs: [{ commitment: '8'.repeat(64), enc_note: 'aa' }] };
    await expect(buildGhostBridgeWitness({
      state: stateWithWitness(),
      bundle: badOutput,
      secretMaterial: { spendingKey: new Uint8Array(32).fill(1) },
      spendNotes: [{ commitment }],
      outputNotes: [{ value: 13n, pkD: new Uint8Array(32).fill(4),
        rho: new Uint8Array(32).fill(2), rcm: new Uint8Array(32).fill(3) }],
      bridge: bridge(),
    })).rejects.toThrow(/computed commitment/);
  });
});
