# Ghost transaction flow contract

Ghost transfers are not enabled by merely having a note scanner or a proof
bridge. The wallet must construct one exact public transaction skeleton, hash
that skeleton with WEPO's canonical `WEPO_SIGHASH_V3` material, and obtain a
proof for that exact 32-byte digest.

The browser contract is implemented by
`frontend/src/utils/ghostTransactionPlanner.js`. It recognizes three explicit
flows:

| Flow | Transparent side | Shielded side | `value_balance` |
| --- | --- | --- | --- |
| shielding | one or more inputs, optional change | one or more new notes, no spends | positive |
| shielded | no transparent inputs or outputs | spends and new notes | zero; fee must be zero |
| unshielding | one or more transparent outputs | one or more spends, optional new notes | negative |

The planner rejects legacy privacy fields, unbounded arrays, malformed
outpoints, duplicate nullifiers or commitments, non-canonical addresses, and
proofs that are absent, malformed, or not explicitly returned for the requested
sighash. Attaching the proof must leave the canonical sighash unchanged. Before
signing or submitting, `assertGhostTransactionPlan` must be called again; any
change to a public field, note ciphertext, nullifier, commitment, fee, or
transparent output is rejected.

The proof callback is intentionally narrow:

```js
const result = await createGhostTransactionPlan({
  flow: 'unshielding',
  unsignedTx,
  network: 'mainnet',
  proveBundle: async ({ sighash, transaction, bundle }) => ({
    // Adapt the audited native/WASM bridge here.
    proof: await localGhostBridge.proveBundle(toBridgeWitness(bundle, sighash)),
    sighash,
  }),
});
```

The callback must not call a network prover or legacy privacy implementation.
The consensus verifier remains authoritative: it must parse the proof envelope,
recompute the statement digest from the transaction sighash and bundle, and
verify the proof against the active anchor/nullifier state. This planner does
not claim that the browser has produced a release-qualified proof until the
native and WASM artifact hash-pin, clean-runner build, and verifier boundary
evidence are complete.
