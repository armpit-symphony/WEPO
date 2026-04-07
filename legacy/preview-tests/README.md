# Legacy Preview Tests

This directory contains stale preview-era and bridge-era test scripts that are
kept only for historical reference.

They are not the canonical acceptance path for the current WEPO backend/node
stack.

Use the canonical local verification path instead:

```bash
/home/sparky/WEPO/wepo-blockchain/scripts/run_canonical_fee_smoke.sh
```

That launcher starts the dedicated local node and backend, runs the canonical
fee-settlement smoke, verifies on-chain settlement and Mongo state, and tears
the stack down automatically.
