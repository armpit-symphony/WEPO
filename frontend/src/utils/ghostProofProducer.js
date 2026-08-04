import { hexToBytes } from './wepoSigner.js';

const LOCAL_BRIDGE_KIND = 'wepo-local-ghost-crypto-v1';

function fail(reason) {
  throw new Error(`Ghost proof producer: ${reason}`);
}

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** Adapt witness material to the audited local native/WASM bridge only. */
export function createGhostBridgeProofProducer(bridge, buildWitness) {
  if (!bridge || bridge.kind !== LOCAL_BRIDGE_KIND || bridge.localOnly !== true) {
    fail('the proof producer must be the audited local native/WASM bridge');
  }
  if (typeof bridge.proveBundle !== 'function' || typeof buildWitness !== 'function') {
    fail('the local bridge and witness builder are required');
  }
  return async ({ sighash, transaction, bundle }) => {
    const witness = await buildWitness({ sighash, transaction, bundle });
    if (!isRecord(witness)) fail('local witness builder returned no witness object');
    const proof = await bridge.proveBundle({
      ...witness,
      valueBalance: bundle.value_balance,
      sighash: hexToBytes(sighash),
    });
    return { proof, sighash };
  };
}
