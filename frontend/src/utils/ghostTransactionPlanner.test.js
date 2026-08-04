import { describe, expect, it } from 'vitest';
import {
  assertGhostTransactionPlan,
  createGhostTransactionPlan,
  GHOST_TRANSACTION_FLOWS,
} from './ghostTransactionPlanner.js';

const address = 'wepo1q' + 'a'.repeat(39);

function tx(flow) {
  return {
    version: 1,
    lock_time: 0,
    fee: flow === GHOST_TRANSACTION_FLOWS.SHIELDED ? 0 : 5,
    tx_type: 'transfer',
    timestamp: 1700000000,
    privacy_proof: null,
    ring_signature: null,
    extra_data: {},
    inputs: flow === GHOST_TRANSACTION_FLOWS.SHIELDING
      ? [{
        prev_txid: '1'.repeat(64),
        prev_vout: 0,
        sequence: 0xffffffff,
        script_sig: '7369676e61747572655f706c616365686f6c646572',
        signature_type: 'ecdsa',
        quantum_signature: null,
        quantum_public_key: null,
      }]
      : [],
    outputs: flow === GHOST_TRANSACTION_FLOWS.UNSHIELDING
      ? [{ value: 95, address, script_pubkey: '6f75747075745f736372697074' }]
      : [],
    shielded_bundle: {
      spends: flow === GHOST_TRANSACTION_FLOWS.SHIELDING ? [] : [{
        anchor: '2'.repeat(64), nullifier: '3'.repeat(64),
      }],
      outputs: [{ commitment: '4'.repeat(64), enc_note: 'aa'.repeat(32) }],
      value_balance: flow === GHOST_TRANSACTION_FLOWS.SHIELDING ? 100 : (
        flow === GHOST_TRANSACTION_FLOWS.UNSHIELDING ? -100 : 0
      ),
    },
  };
}

const prove = async ({ sighash }) => ({ proof: new Uint8Array([0x57, 0x50, 0x4f]), sighash });

describe('Ghost transaction planner', () => {
  for (const flow of Object.values(GHOST_TRANSACTION_FLOWS)) {
    it(`plans ${flow} with an exact proof binding`, async () => {
      const plan = await createGhostTransactionPlan({
        flow,
        unsignedTx: tx(flow),
        network: 'test',
        proveBundle: prove,
      });
      expect(plan.sighash).toHaveLength(64);
      expect(plan.transaction.shielded_bundle.proof).toBe('57504f');
      expect(assertGhostTransactionPlan(plan, plan.transaction)).toBe(true);
    });
  }

  it('rejects a prover that omits or changes the requested sighash', async () => {
    await expect(createGhostTransactionPlan({
      flow: GHOST_TRANSACTION_FLOWS.SHIELDING,
      unsignedTx: tx(GHOST_TRANSACTION_FLOWS.SHIELDING),
      network: 'test',
      proveBundle: async () => ({ proof: '00' }),
    })).rejects.toThrow(/bind its proof/);
  });

  it('rejects a mutation of a planned public field before submission', async () => {
    const plan = await createGhostTransactionPlan({
      flow: GHOST_TRANSACTION_FLOWS.SHIELDING,
      unsignedTx: tx(GHOST_TRANSACTION_FLOWS.SHIELDING),
      network: 'test',
      proveBundle: prove,
    });
    const candidate = structuredClone(plan.transaction);
    candidate.shielded_bundle.outputs[0].commitment = '5'.repeat(64);
    expect(() => assertGhostTransactionPlan(plan, candidate)).toThrow(/canonical sighash/);
  });
});
