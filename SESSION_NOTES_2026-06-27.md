# Session notes — Quantum Messaging two-wallet E2E debug (2026-06-27)

Env: Windows 11 PC, Brave + Chrome as two wallets, backend `127.0.0.1:18021`,
frontend `127.0.0.1:3000`. Branch of record: `wallet-lab-fixes-20260409`.

## Headline: the PC was running STALE, diverged frontend+backend code
The live two-wallet test on the PC exercised the **retired demo messaging
system**, not the current blind-relay design. Evidence:
- PC `WalletContext.js` = 762 lines; canonical = **1046** lines.
- PC used routes `/api/messaging/*` and a Mongo collection `messaging_keys`
  with a `published:true` flag.
- Canonical uses `/api/messages/*`, collection `message_keys` (`_id` = address)
  for the registry and `messages` for envelopes; on-chain anchoring via
  `/api/messages/keys/onchain/{addr}`; client helper `_resolveRecipientKeys`.
- Canonical commits present: on-chain key anchoring (`75c3f25`), Tor-routable
  relay (`9080d4b`), manual E2E guide (`a964069`).

**Consequence:** the new PQ blind-relay messaging (ML-KEM-768 + AES-256-GCM +
ML-DSA-44, server-blind, on-chain trustless key discovery) was never actually
tested. Reconcile the PC checkout before drawing conclusions about messaging.

### Reconcile the PC
```bash
cd <repo on PC>
git fetch
git checkout wallet-lab-fixes-20260409
git pull
# frontend env (rebuild/restart required — CRA bakes REACT_APP_* at startup)
#   frontend/.env: REACT_APP_BACKEND_URL=http://127.0.0.1:18021
cd frontend && npm install && npm start   # full restart, then hard-refresh browsers
```
Then re-run `MANUAL_E2E_MESSAGING.md`. The relay registry now lives in
`db.message_keys` (not `messaging_keys`); verify with:
```
mongosh "mongodb://127.0.0.1:27017/wepo_test_wallet_lab" \
  --eval 'db.message_keys.countDocuments(); db.messages.countDocuments()'
```

## Confirmed real finding #1 — Mongo was not running (infra)
Backend `.env` → `mongodb://127.0.0.1:27017`, but nothing listened. Every motor
call (key lookup, store, count) stalled on server-selection timeout → "1 not 2
published" and the perpetual Send spinner. Fixed on the PC with:
`docker run -d --name wepo-mongo -p 27017:27017 mongo:6`. After that, key publish
worked. This is environmental — keep a Mongo up before testing.

## Finding #2 — Dashboard polling (HARDENED in canonical, not the proven cause)
`Dashboard.js` polled `/api/mining/status` every 5s with a `focus` re-trigger.
The PC report attributed the "second browser hangs" to socket-pool saturation
(~6 conns/host). Caveat: in **canonical**, `/api/mining/status` is
`wallet_mining.get_mining_stats()` — a fast, local, non-blocking call
(`server.py:2190`), so idle keep-alive sockets are reused, not pinned. The PC's
saturation more likely came from the **old** `/api/messaging/*` path + Mongo
stalls. Still tightened as hygiene:
- interval 5s → 30s; skip polling while `document.hidden`; immediate refresh on
  `visibilitychange` return. (`Dashboard.js` second `useEffect`.)

## Lower-priority observations (carry forward)
- **Blocking I/O in async routes:** the node-proxy endpoints (e.g. RWA,
  on-chain key lookup, staking) use synchronous `requests.*` inside `async def`
  with a timeout. They won't hang forever (timeouts set), but a slow node call
  serializes the single event loop. If `WEPO_NODE_API_URL` ever points at a
  reachable-but-silent host, every request stalls up to the timeout. Consider
  `asyncio.to_thread(...)` for these before mainnet. Not blocking for the E2E.
- **Redis fallback warning** at startup (`localhost:6379` refused → in-memory
  fallback). Fine for dev; flag for prod.
- **create→login 401 race (PC, old code):** Chrome showed wallet/create 200 then
  3× wallet/login 401 before succeeding. Re-check on canonical after reconcile;
  if it reproduces, look for a read-after-write timing gap on the password hash.
- **WEPO_NODE_API_URL=18212** had nothing listening; `mining/status` handled the
  absence gracefully (canonical mining/status is local and doesn't proxy).

## State at end of session (PC)
- `wepo-mongo` container up on 27017; 2 wallets had published keys (old schema).
- Cross-wallet `db.messages` count stayed 0 (send never completed under old code
  + pool issue).
- Two test wallets: `wepo1389124005a9265cba51454bef27d9c7d`,
  `wepo173530c32f47c4efebaf40c84ef8d9b52`.

## Net next step
Reconcile PC onto `wallet-lab-fixes-20260409`, keep Mongo up, restart `npm start`
after setting `frontend/.env`, then re-run the manual E2E against the real
blind-relay messaging. Prior results do not count.
