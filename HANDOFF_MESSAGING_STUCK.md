# Handoff — Private messaging "send" stuck in a loop (spinner never clears)

You are a fresh Claude Code instance running on the user's PC, where the WEPO
stack is actually running (Mongo + backend gateway + frontend, optionally the
node). I (a prior instance) traced the code but cannot see the running stack.
Your advantage: you can open the browser DevTools Network/Console and read the
uvicorn/Mongo logs. Use that.

## Symptom (from the user)
Two self-custody wallets, each in its own browser session. Both opened Quantum
Messaging and appear to be connected/enabled. Sending a message from one wallet
to the other (recipient address copied from the wallet's Receive window) leaves
the Send button **stuck "sending" forever** — the spinner never clears, no error
is shown.

## What that symptom means (already established)
The Send button's `isLoading` is set true at `handleSend` and cleared in a
`finally` block — see `frontend/src/components/QuantumMessaging.js:81-104`. So a
permanently-stuck spinner means the `await sendMessage(...)` promise **never
resolves or rejects**. That only happens if a `fetch()` hangs open (TCP
connected, response never arrives). There are NO client-side fetch timeouts on
the messaging calls, so a hung fetch hangs forever. Find which fetch hangs.

## The send path (exact)
1. UI: `QuantumMessaging.js:81 handleSend` → `await sendMessage(to, content, pw)`.
2. `frontend/src/contexts/WalletContext.js:896 sendMessage`:
   a. `_messagingIdentity(password)` (sync, local crypto — not the hang).
   b. `await _resolveRecipientKeys(toAddress)`  ← **prime suspect**
   c. `encryptMessage(...)` (sync, ML-KEM-768 + AES-GCM — fast, not the hang).
   d. `await fetch(`${getRelayUrl()}/api/messages`, POST)`  ← second suspect.
3. `WalletContext.js:881 _resolveRecipientKeys`:
   - First: `GET ${getBackendUrl()}/api/messages/keys/onchain/{addr}` — wrapped
     in try/catch; ANY failure falls through. (try block `:882-888`)
   - Then: `GET ${getRelayUrl()}/api/messages/keys/{addr}` — 404 here THROWS
     "Recipient has not published messaging keys yet" (would show an error, not
     hang). (`:889-892`)

URL config (`WalletContext.js:132-138`):
- `getBackendUrl()` = `REACT_APP_BACKEND_URL` || `http://localhost:8001`
- `getRelayUrl()`   = `REACT_APP_MESSAGING_RELAY_URL` || `getBackendUrl()`

Backend handlers (`backend/server.py`):
- `:1091 GET /api/messages/keys/onchain/{address}` — **`async def` that calls
  BLOCKING `requests.get(node, timeout=5)`**. If the node is down with a refused
  connection it returns 502 fast; but if `WEPO_NODE_API_URL` points at a host
  that accepts the socket and never replies, it blocks the **single event loop**
  for the full timeout, and because it's blocking-in-async it stalls EVERY other
  request meanwhile.
  ⚠️ Default `WEPO_NODE_API_URL` is `http://127.0.0.1:8122` (`server.py:63`), NOT
  18212. If `backend/.env` doesn't set it, the proxy points at the wrong port.
- `:1106 GET /api/messages/keys/{address}` — relay registry, Mongo `message_keys`.
- `:1115 POST /api/messages` — stores envelope via `await db.messages.insert_one`.
  If Mongo isn't actually reachable, motor blocks on server-selection (~30s
  default) then errors — looks like a freeze, then an error.

## Ranked hypotheses (check in this order)
1. **A fetch is genuinely hanging open.** Most likely the on-chain proxy
   (`/api/messages/keys/onchain/{addr}`) blocking the event loop because
   `WEPO_NODE_API_URL` resolves to something that accepts but never answers, OR
   the node is half-up. Because the proxy uses blocking `requests` inside an
   `async def`, a single slow node call freezes the whole gateway.
2. **Mongo misconfigured/unreachable** → `insert_one` / `find_one` stall on
   motor server-selection. Check `MONGO_URL`/`DB_NAME` in `backend/.env` vs the
   actually-running mongod (user's manual uses port 27018, `wepo_test_wallet_lab`;
   the dev `.env` here had `test_database`).
3. **CORS** — if the origin isn't in `WEPO_ALLOWED_ORIGINS`, the browser blocks
   the POST and `fetch` rejects (this shows in Console; usually errors rather
   than hangs, but rule it out).
4. **Recipient never actually published** → registry 404 → throws a visible
   error (NOT a hang). If you see this error instead of a hang, that's a separate
   issue (Enable Messaging didn't POST keys for that wallet).

## Do this first (localizes it in ~2 minutes)
1. In the sending wallet's browser: **DevTools → Network**, clear, click Send.
   Identify the request stuck in **(pending)**. Note its URL and how long it
   hangs. That single observation tells you which of the above it is:
   - stuck on `/api/messages/keys/onchain/...` → hypothesis 1 (node/proxy).
   - stuck on `/api/messages` POST → hypothesis 2 (Mongo) or event-loop blocked
     by a prior on-chain call.
   - red CORS error in **Console** → hypothesis 3.
   - `keys/{addr}` returns 404 + a visible "not published" error → hypothesis 4.
2. Watch the **uvicorn terminal** at the same moment — which route logged, any
   traceback, how long it took.

## Reproduce from the shell (no browser; isolates frontend vs backend)
Replace BACKEND and ADDR. ADDR_B = the recipient's address from its Receive window.
```bash
BACKEND=http://127.0.0.1:18021      # whatever REACT_APP_BACKEND_URL is
ADDR_B=wepo1q...                    # recipient

# Does the on-chain proxy hang? (time it)
time curl -sS "$BACKEND/api/messages/keys/onchain/$ADDR_B" ; echo

# Did the recipient actually publish to the relay registry?
curl -sS "$BACKEND/api/messages/keys/$ADDR_B" ; echo

# Is Mongo serving the relay? (use the port/db from backend/.env)
mongosh "mongodb://127.0.0.1:27018/wepo_test_wallet_lab" \
  --eval 'db.message_keys.find().toArray(); db.messages.countDocuments()'
```
If the first `curl` hangs for ~5s or longer → it's the node proxy
(`WEPO_NODE_API_URL`). If the second returns 404 → the recipient's Enable
Messaging never published. If `mongosh` can't connect → hypothesis 2.

## Likely fixes (apply the one the diagnosis points to)
- **Node proxy stalling the event loop (most likely):** in
  `backend/server.py:1091-1103`, the on-chain lookup shouldn't be able to freeze
  messaging when the node is down. Two complementary fixes:
  1. Make `getBackendUrl()`'s on-chain call non-fatal/fast on the client — it's
     already wrapped in try/catch, but add a short `AbortController` timeout
     (e.g. 3s) to `_resolveRecipientKeys`'s on-chain fetch in
     `WalletContext.js:882-888` so it can't hang the whole send. The registry
     fallback already exists.
  2. On the backend, run the blocking `requests.get` off the event loop
     (`await asyncio.to_thread(requests.get, ...)`) or lower `timeout` and ensure
     `WEPO_NODE_API_URL` is correct in `backend/.env` (set it to the running
     node, e.g. `http://127.0.0.1:18212`, or expect/handle node-down cleanly).
     This matters because EVERY messaging route is an `async def` doing blocking
     `requests`/motor work; one slow call stalls all of them.
- **Mongo:** fix `MONGO_URL`/`DB_NAME` in `backend/.env` to match the running
  mongod; restart uvicorn.
- **CORS:** add the exact frontend origin to `WEPO_ALLOWED_ORIGINS`, restart.
- **Recipient didn't publish:** in the recipient wallet, re-run Enable Messaging;
  confirm `db.message_keys` now has its address; the relay GET should return 200.

## Guardrails (preserve)
- Commit/push only if the user asks; branch is `wallet-lab-fixes-20260409`.
- Keep `backend/.env` and `frontend/.env` UNSTAGED (local-only edits).
- No hand-rolled soundness-critical crypto. Messaging crypto is vetted
  (`@noble/post-quantum`, `@noble/ciphers`) — don't touch it; this is a
  transport/plumbing hang, not a crypto bug.
- After fixing, sanity-check with: `python3 tests/test_messaging_relay.py`,
  `python3 tests/test_messaging_key_registration.py`, `bash tests/run_messaging_test.sh`.

## Reference docs in this repo
`MANUAL_E2E_MESSAGING.md` (the test the user is running), `MESSAGING_DESIGN.md`
(architecture). Send path code: `WalletContext.js:824-915`,
`QuantumMessaging.js:81-105`. Backend relay: `server.py:1031-1188`.
