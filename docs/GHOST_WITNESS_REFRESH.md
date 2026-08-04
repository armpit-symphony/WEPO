# Ghost witness refresh boundary

`POST /api/shielded/witness` returns only public data for a known commitment:
the position, 32 Merkle siblings, current shielded anchor, commitment height,
and canonical chain tip. It never receives or returns spending keys, note
plaintext, or proofs.

`frontend/src/utils/ghostWitnessRefresh.js` binds every response to the
durable wallet tip and sends the commitment, anchor, position, and siblings to
`bridge.verifyMerklePath`. The Rust native/WASM bridge performs the
consensus Rescue-Prime path recomputation. A tip race, malformed path, unknown
commitment, or bridge rejection aborts the entire refresh; no witness is
persisted partially.

The browser must not implement a SHA3, Rescue, or other fallback verifier. The
same hash implementation used by the consensus/prover bridge is mandatory.
