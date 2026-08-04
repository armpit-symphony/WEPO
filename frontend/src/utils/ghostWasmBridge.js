import { createGhostBridge } from './ghostBridge.js';

const REQUIRED_EXPORTS = [
  'memory',
  'wepo_ghost_alloc',
  'wepo_ghost_dealloc',
  'wepo_ghost_handle_request',
  'wepo_ghost_response_ptr',
  'wepo_ghost_response_len',
];

function fail(message) {
  throw new Error('Ghost WASM bridge: ' + message);
}

export async function loadGhostWasmBridge({ wasmUrl, fetchImpl = fetch } = {}) {
  if (!wasmUrl) fail('WASM module URL is required');
  const response = await fetchImpl(wasmUrl);
  if (!response.ok) fail('WASM module could not be loaded');
  const bytes = await response.arrayBuffer();
  const { instance } = await WebAssembly.instantiate(bytes, {});
  for (const name of REQUIRED_EXPORTS) {
    if (!instance.exports[name]) fail('required WASM export is missing: ' + name);
  }
  const { memory } = instance.exports;
  return createGhostBridge(async (request) => {
    const input = instance.exports.wepo_ghost_alloc(request.length);
    if (!input) fail('WASM input allocation failed');
    try {
      new Uint8Array(memory.buffer, input, request.length).set(request);
      instance.exports.wepo_ghost_handle_request(input, request.length);
    } finally {
      instance.exports.wepo_ghost_dealloc(input, request.length);
    }
    const pointer = instance.exports.wepo_ghost_response_ptr();
    const length = instance.exports.wepo_ghost_response_len();
    if (!pointer || length > 1024 * 1024 + 4096) fail('WASM response is out of bounds');
    return new Uint8Array(memory.buffer, pointer, length).slice();
  });
}
