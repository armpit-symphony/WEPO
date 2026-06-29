# Manual E2E — Private Messaging (two wallets)

Step-by-step to verify the post-quantum messaging system end to end on your PC:
create two self-custody wallets, exchange an encrypted message, and (optionally)
verify trustless on-chain key discovery.

Ports used below: **Mongo 27018**, **node API 18212**, **backend gateway 18021**,
**frontend 3000**. Adjust if those clash on your machine.

---

## 0. Prerequisites

- Python 3.10+ with the backend/node deps installed:
  `pip install -r backend/requirements.txt` and `pip install dilithium-py`
  (the node also needs `fastapi`, `uvicorn`, `requests`).
- Node.js 18+ and `npm`.
- MongoDB running and reachable at `mongodb://127.0.0.1:27018`
  (any Mongo works — just match `MONGO_URL`).

> The **basic messaging test (Part B) does not need the blockchain node or any
> coins** — only Mongo + backend + frontend. The node is only required for
> balances and the optional on-chain anchoring in Part C.

---

## 1. Start the backend gateway (server.py)

```bash
cd backend
cp .env.example .env            # then edit if needed (Mongo URL, node URL)
# .env should contain at least:
#   MONGO_URL="mongodb://127.0.0.1:27018"
#   DB_NAME="wepo_test_wallet_lab"
#   WEPO_NODE_API_URL="http://127.0.0.1:18212"
#   WEPO_ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"
uvicorn server:app --host 127.0.0.1 --port 18021
```

Leave it running. (Messaging endpoints are ungated; you do **not** need to enable
`WEPO_FEATURE_*` for messaging.)

## 2. (Optional, for Part C) Start the blockchain node

```bash
cd wepo-blockchain/core
python3 wepo_node.py --api-port 18212 --network-profile test --difficulty-override 1
# Windows: add  --data-dir C:\temp\wepo
```

Skip this for Part B; if the node is down, wallet balances just show 0 and
messaging still works.

## 3. Start the frontend

```bash
cd frontend
cp .env.example .env
# set REACT_APP_BACKEND_URL=http://127.0.0.1:18021  in frontend/.env
npm install        # first time only
npm start          # serves http://localhost:3000
```

---

## Part B — Two-wallet encrypted message (the core test)

You need two separate browser sessions so each holds its own wallet:
**Window 1 = normal browser**, **Window 2 = incognito/private** (or a second
browser). Both open `http://localhost:3000`.

### B1. Create wallet A (Window 1)
1. Create Wallet → choose a username + password.
2. **Write down the 12-word recovery phrase**, confirm the backup checkbox, open
   the wallet.
3. Copy wallet A's address (starts with `wepo1q…`). Call it **ADDR_A**.

### B2. Create wallet B (Window 2, incognito)
Same as above; copy **ADDR_B**.

### B3. Open messaging on BOTH wallets
In each window: open **Messages**.
- There is **no password prompt and no “Enable” step** — messaging is live the
  moment the wallet is open. Each wallet automatically publishes its public keys to
  the relay registry so the other can encrypt to it.

### B4. Send A → B (Window 1)
1. In wallet A's Messages: **New** → recipient = **ADDR_B** → **Start chat**.
2. Type a message and press **Enter** (or tap the send button).
3. The message appears immediately as a purple bubble (end-to-end encrypted, free).

### B5. Receive on B (Window 2)
1. In wallet B's Messages the new conversation from **ADDR_A** appears within ~10s
   (the inbox auto-polls — no refresh button needed).
2. Open it: your plaintext shows with a green check (sender signature verified).

### B6. Reply B → A
Type a reply in the same thread and press Enter; it shows up in A's thread within
~10s. ✅ Round trip done.

### B7. Confirm the relay is blind (optional, convincing)
With the backend running, inspect what the server stored:
```bash
mongosh "mongodb://127.0.0.1:27018/wepo_test_wallet_lab" \
  --eval 'db.messages.find().limit(1).pretty()'
```
Expect only ciphertext fields (`kem_ct`, `nonce`, `ct`, `sig`, …) — **no
plaintext**. The server cannot read the message.

---

## Part C — Trustless on-chain key discovery (advanced; needs the node + coins)

This proves recipients can find your keys **without trusting the relay**. On-chain
anchoring costs a small fee, so it is **no longer surfaced as a button** in the
always-on/free messaging UI — it's an optional advanced step done via the API. The
client still *resolves* recipient keys on-chain first (registry only as fallback),
so anchoring via the API below is enough to exercise the trustless path.

### C1. Fund wallet A
Restart the node so it mines to ADDR_A:
```bash
cd wepo-blockchain/core
python3 wepo_node.py --api-port 18212 --network-profile test \
  --difficulty-override 1 --miner-address ADDR_A
```
Wait ~1 minute; refresh wallet A — it should show a balance.

### C2. Anchor A's keys on-chain (via API)
The on-chain anchor is built → signed → submitted like any tx. The signing happens
client-side, so the simplest way to exercise it manually is to build the unsigned
tx and submit it with a signer (mirror `scripts/wepo_accelerated_simulation.py`),
or temporarily call `registerMessagingKeysOnChain` from the wallet console. Then
verify it landed:
```bash
curl http://127.0.0.1:18212/api/messages/keys/onchain/ADDR_A
```
Expect a JSON record with `kem_pub`, `sig_pub`, `register_height`.

### C3. Send B → A and confirm on-chain resolution
Send a message from B to **ADDR_A**. The client resolves A's keys from the chain
first (registry only as fallback). The message round-trips exactly as in Part B —
but now key discovery required **no trust in the relay**.

---

## Negative checks (already covered by automated tests, optional to eyeball)

- Tampered ciphertext / wrong recipient → won't decrypt (see
  `tests/run_messaging_test.sh`).
- Forged/non-owner key publish or someone else fetching your inbox → rejected
  (see `tests/test_messaging_relay.py`).
- On-chain key registration ownership/size/fee rules → enforced (see
  `tests/test_messaging_key_registration.py`).

Run them all locally:
```bash
python3 tests/test_messaging_relay.py
python3 tests/test_messaging_key_registration.py
bash    tests/run_messaging_test.sh
```

---

## Troubleshooting

- **CORS errors in the browser:** add your frontend origin to
  `WEPO_ALLOWED_ORIGINS` in `backend/.env`, restart the backend.
- **“This address has not used messaging yet…”:** the recipient must have opened
  their wallet at least once on this relay so its keys auto-published (B3). Have
  them open **Messages** and try again.
- **Balance shows 0 / can't anchor on-chain:** the node isn't running or wallet A
  isn't funded (Part C1).
- **Two wallets share state:** use separate browser profiles/incognito — wallet
  keys live in that browser's local storage.
- **Backend won't start:** ensure Mongo is up and `MONGO_URL`/`DB_NAME` in
  `backend/.env` are correct.
