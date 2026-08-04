function memoryStorage() {
  const values = new Map();
  return {
    get length() {
      return values.size;
    },
    clear() {
      values.clear();
    },
    getItem(key) {
      const normalized = String(key);
      return values.has(normalized) ? values.get(normalized) : null;
    },
    key(index) {
      return [...values.keys()][index] ?? null;
    },
    removeItem(key) {
      values.delete(String(key));
    },
    setItem(key, value) {
      values.set(String(key), String(value));
    },
  };
}

// Node 25 exposes an opt-in localStorage global that can shadow jsdom with an
// unusable instance. Install deterministic, per-worker Storage implementations
// so wallet persistence tests exercise the browser contract consistently.
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: memoryStorage(),
});
Object.defineProperty(globalThis, 'sessionStorage', {
  configurable: true,
  value: memoryStorage(),
});
