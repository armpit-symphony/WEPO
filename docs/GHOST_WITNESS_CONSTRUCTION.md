# Ghost witness construction

`frontend/src/utils/ghostWitnessBuilder.js` is the boundary between encrypted
durable wallet state and the local Ghost native/WASM proof bridge.

The caller must unlock the wallet and provide:

- the validated Ghost state from `loadGhostWalletState`;
- the transaction's public `shielded_bundle`;
- the in-memory `spendingKey` from `deriveGhostSecretMaterial`;
- spend references by durable note commitment; and
- plaintext output note material returned by the local output constructor.

For each spend, the builder requires an unspent durable note with a 32-level
Merkle witness whose anchor equals the transaction anchor. It recomputes the
nullifier through the audited local bridge and rejects any mismatch. For each
output, it recomputes the note commitment through the same bridge and rejects
any mismatch. Only after these checks does it return the byte-oriented
`spends` and `outputs` shape consumed by `createGhostBridgeProofProducer`.

The builder is deliberately non-persistent: it never stores the spending key,
does not mutate wallet state, and fails when a note has no verified witness.
Witness refresh remains a separate operation using
`refreshGhostWitnesses(state, updates, verifyWitness)`; a clean release must
qualify that refresh source and verifier against the canonical chain.

The intended composition is:

```js
const proveBundle = createGhostBridgeProofProducer(
  bridge,
  ({ bundle }) => buildGhostBridgeWitness({
    state,
    bundle,
    secretMaterial,
    spendNotes,
    outputNotes,
    bridge,
  }),
);
```

No remote prover, node-supplied witness, or persisted spending key is
permitted in this path.
