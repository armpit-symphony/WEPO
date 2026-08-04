import { describe, expect, it } from 'vitest';

import { loadGhostWasmBridge } from './ghostWasmBridge.js';

describe('Ghost WASM bridge boundary', () => {
  it('fails closed when the module is absent', async () => {
    await expect(loadGhostWasmBridge({
      wasmUrl: '/missing/wepo_zk.wasm',
      fetchImpl: async () => ({ ok: false }),
    })).rejects.toThrow('could not be loaded');
  });
});
