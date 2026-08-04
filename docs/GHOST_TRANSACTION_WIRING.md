# Ghost transaction wiring

The Ghost transaction path is now connected end to end at the custody boundary:

1. `WalletContext.previewGhostTransaction` sends a public unsigned skeleton to
   `/api/transaction/build-ghost-unsigned`.
2. The node parses the canonical transaction, rejects legacy privacy fields and
   pre-existing signatures/proofs, checks shielded shape, verifies transparent
   input ownership, and enforces `inputs - outputs - value_balance = fee`.
3. `createGhostTransactionPlan` asks only a caller-supplied local prover for a
   proof of the exact node-verified sighash.
4. `WalletContext.sendGhostTransaction` signs transparent inputs locally,
   rechecks the plan, verifies the returned transaction identity, and submits
   the proof-bearing transaction to `/api/transaction/send`.

When callers do not supply a custom producer, `WalletContext.sendGhostTransaction`
constructs the callback from `ghostProofProducer.js`,
`ghostWitnessBuilder.js`, unlocked durable state, and the audited native/WASM
bridge. There is no network prover fallback. The builder refuses missing or
stale witnesses and rechecks every spend nullifier and output commitment before
the bridge receives witness material. The wallet UI must not expose a send
action until this local witness path and clean native/WASM artifact evidence
are qualified.
