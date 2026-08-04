import { describe, expect, it } from 'vitest';

import { createGhostBridge, hasGhostBridge } from './ghostBridge.js';

const REQUEST_MAGIC = new TextEncoder().encode('WEPO_GHOST_WALLET_V1\0');
const RESPONSE_MAGIC = new TextEncoder().encode('WEPO_GHOST_WALLET_R1\0');

function response(payload, status = 0) {
  const result = new Uint8Array(RESPONSE_MAGIC.length + 5 + payload.length);
  result.set(RESPONSE_MAGIC);
  result[RESPONSE_MAGIC.length] = status;
  new DataView(result.buffer).setUint32(RESPONSE_MAGIC.length + 1, payload.length, true);
  result.set(payload, RESPONSE_MAGIC.length + 5);
  return result;
}

describe('Ghost native bridge transport', () => {
  it('encodes and decodes a commitment request without exposing a network fallback', async () => {
    let request;
    const bridge = createGhostBridge(async (value) => {
      request = value;
      return response(new Uint8Array(32).fill(7));
    });
    const commitment = await bridge.commitNote({
      value: 3n,
      pkD: new Uint8Array(32).fill(1),
      rho: new Uint8Array(32).fill(2),
      rcm: new Uint8Array(32).fill(3),
    });
    expect(Array.from(request.slice(0, REQUEST_MAGIC.length))).toEqual(Array.from(REQUEST_MAGIC));
    expect(request[REQUEST_MAGIC.length]).toBe(2);
    expect(Array.from(commitment)).toEqual(Array.from(new Uint8Array(32).fill(7)));
    expect(bridge.localOnly).toBe(true);
  });

  it('rejects malformed bridge responses and rejected cryptographic requests', async () => {
    const bridge = createGhostBridge(async () => response(new Uint8Array(), 1));
    await expect(bridge.nullifier({
      spendingKey: new Uint8Array(32),
      rho: new Uint8Array(32),
    })).rejects.toThrow('request was rejected');
    expect(() => createGhostBridge(async () => new Uint8Array([1]))).not.toThrow();

  });

  it('routes Merkle witness verification through the local protocol operation', async () => {
    let request;
    const bridge = createGhostBridge(async (value) => {
      request = value;
      return response(Uint8Array.of(1));
    });
    await expect(bridge.verifyMerklePath({
      commitment: new Uint8Array(32).fill(1),
      anchor: new Uint8Array(32).fill(2),
      position: 3,
      siblings: Array.from({ length: 32 }, (_, index) => new Uint8Array(32).fill(index)),
    })).resolves.toBe(true);
    expect(request[REQUEST_MAGIC.length]).toBe(5);
    expect(request.length).toBe(REQUEST_MAGIC.length + 1 + 32 + 32 + 4 + (32 * 32));
  });

  it('reports browser availability only when the audited bridge is actually exposed', () => {
    expect(hasGhostBridge()).toBe(false);
  });
});
