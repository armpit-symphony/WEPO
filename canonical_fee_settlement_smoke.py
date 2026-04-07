#!/usr/bin/env python3
"""
Repeatable local smoke test for canonical backend-originated fee settlement.

Default target stack:
- backend: http://127.0.0.1:8011
- node: http://127.0.0.1:8122
- mongo settings loaded from backend/.env when present

The script seeds a disposable wallet and RWA token in Mongo, executes
POST /api/dex/rwa-trade, verifies the returned settlement tx on-chain,
checks the persisted Mongo records, and exits non-zero on failure.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import argon2
import requests
from pymongo import MongoClient
from pymongo.collection import Collection

try:
    from dotenv import dotenv_values
except ImportError:  # pragma: no cover
    dotenv_values = None


DEFAULT_BACKEND_BASE_URL = "http://127.0.0.1:8011"
DEFAULT_NODE_BASE_URL = "http://127.0.0.1:8122"
DEFAULT_BACKEND_ENV_PATH = Path(__file__).resolve().parent / "backend" / ".env"
DEFAULT_WALLET_BALANCE = 1000.0
DEFAULT_TOKEN_AMOUNT = 5.0
DEFAULT_WEPO_AMOUNT = 100.0
DEFAULT_CONFIRM_TIMEOUT_SECONDS = 90
DEFAULT_POLL_INTERVAL_SECONDS = 2
POW_ARGON2_TIME_COST = 3
POW_ARGON2_MEMORY_COST = 4096
POW_ARGON2_PARALLELISM = 1
POW_ARGON2_HASH_LEN = 32
POW_ARGON2_SALT_LEN = 16


@dataclass
class SmokeContext:
    smoke_id: str
    wallet_address: str
    wallet_username: str
    token_id: str
    trade_id: Optional[str] = None
    settlement_txid: Optional[str] = None


class SmokeFailure(RuntimeError):
    pass


def load_backend_env(env_path: Path) -> Dict[str, str]:
    if not env_path.exists() or dotenv_values is None:
        return {}

    loaded = dotenv_values(env_path)
    return {key: value for key, value in loaded.items() if key and value}


def normalize_base_url(url: str) -> str:
    normalized = url.rstrip("/")
    if normalized.endswith("/api"):
        normalized = normalized[:-4]
    return normalized


def api_url(base_url: str, suffix: str) -> str:
    return f"{normalize_base_url(base_url)}{suffix}"


def make_wepo_address(seed: str) -> str:
    return f"wepo1{seed.replace('-', '')[:40]}"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def print_step(message: str) -> None:
    print(f"[wepo-smoke] {message}")


def preflight_http(session: requests.Session, backend_base_url: str, node_base_url: str) -> None:
    backend_response = session.get(api_url(backend_base_url, "/api/"))
    require(
        backend_response.ok,
        f"Backend is unreachable at {backend_base_url}: HTTP {backend_response.status_code}",
    )

    node_response = session.get(api_url(node_base_url, "/api/network/status"))
    require(
        node_response.ok,
        f"Node is unreachable at {node_base_url}: HTTP {node_response.status_code}",
    )

    node_data = node_response.json()
    print_step(
        "Node reachable"
        f" height={node_data.get('height')} peers={node_data.get('peers')}"
        f" mining_enabled={node_data.get('mining_enabled')}"
    )


def verify_settlement_wallet(
    session: requests.Session,
    node_base_url: str,
    settlement_address: Optional[str],
    required_fee: float,
) -> None:
    if not settlement_address:
        print_step(
            "Settlement wallet preflight skipped because "
            "WEPO_APP_FEE_SETTLEMENT_ADDRESS was not provided to the script"
        )
        return

    response = session.get(api_url(node_base_url, f"/api/wallet/{settlement_address}"))
    require(
        response.ok,
        f"Settlement wallet lookup failed for {settlement_address}: HTTP {response.status_code}",
    )
    payload = response.json()
    balance = float(payload.get("balance", 0.0))
    require(
        balance >= required_fee,
        f"Settlement wallet {settlement_address} balance {balance:.8f} is below required fee {required_fee:.8f}",
    )
    print_step(
        f"Settlement wallet {settlement_address} is funded with {balance:.8f} WEPO"
    )


def seed_wallet(wallets: Collection, context: SmokeContext, wallet_balance: float) -> None:
    wallet_doc = {
        "username": context.wallet_username,
        "address": context.wallet_address,
        "balance": wallet_balance,
        "created_at": int(time.time()),
        "version": "smoke",
        "bip39": False,
        "security_level": "smoke_test",
        "smoke_test_id": context.smoke_id,
    }
    wallets.insert_one(wallet_doc)


def seed_token(rwa_tokens: Collection, context: SmokeContext) -> None:
    token_doc = {
        "_id": context.token_id,
        "symbol": "SMOKE",
        "name": "Smoke Test Asset",
        "status": "active",
        "created_at": int(time.time()),
        "smoke_test_id": context.smoke_id,
    }
    rwa_tokens.insert_one(token_doc)


def execute_trade(
    session: requests.Session,
    backend_base_url: str,
    context: SmokeContext,
    token_amount: float,
    wepo_amount: float,
) -> Dict[str, Any]:
    request_body = {
        "token_id": context.token_id,
        "trade_type": "buy",
        "user_address": context.wallet_address,
        "token_amount": token_amount,
        "wepo_amount": wepo_amount,
        "privacy_enhanced": False,
    }
    response = session.post(api_url(backend_base_url, "/api/dex/rwa-trade"), json=request_body, timeout=20)
    require(
        response.ok,
        f"Trade request failed: HTTP {response.status_code} body={response.text[:500]}",
    )
    payload = response.json()
    require(payload.get("success") is True, f"Trade response did not report success: {payload}")
    return payload


def wait_for_confirmed_tx(
    session: requests.Session,
    node_base_url: str,
    txid: str,
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> Dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_payload: Optional[Dict[str, Any]] = None

    while time.time() < deadline:
        response = session.get(api_url(node_base_url, f"/api/tx/{txid}"), timeout=10)
        if response.ok:
            payload = response.json()
            last_payload = payload
            if payload.get("block_height") is not None and int(payload.get("confirmations", 0)) > 0:
                return payload
        time.sleep(poll_interval_seconds)

    raise SmokeFailure(
        f"Settlement tx {txid} was not confirmed within {timeout_seconds}s"
        f"; last_seen={last_payload}"
    )


def check_difficulty(block_hash: str, difficulty: int) -> bool:
    leading_zeros = 0
    for char in block_hash:
        if char == "0":
            leading_zeros += 1
        else:
            break
    return leading_zeros >= difficulty


def calculate_pow_hash(
    *,
    version: int,
    prev_hash: str,
    merkle_root: str,
    timestamp: int,
    bits: int,
    nonce: int,
) -> str:
    pow_input = struct.pack(
        "<I32s32sIII",
        version,
        bytes.fromhex(prev_hash),
        bytes.fromhex(merkle_root),
        timestamp,
        bits,
        nonce,
    ) + b"pow"
    salt = hashlib.sha256(b"WEPO_POW_SALT" + pow_input).digest()[:POW_ARGON2_SALT_LEN]
    pow_bytes = argon2.low_level.hash_secret_raw(
        secret=pow_input,
        salt=salt,
        time_cost=POW_ARGON2_TIME_COST,
        memory_cost=POW_ARGON2_MEMORY_COST,
        parallelism=POW_ARGON2_PARALLELISM,
        hash_len=POW_ARGON2_HASH_LEN,
        type=argon2.low_level.Type.ID,
    )
    return hashlib.sha256(pow_bytes).hexdigest()


def find_valid_nonce(work: Dict[str, Any], timeout_seconds: int) -> int:
    deadline = time.time() + timeout_seconds
    nonce = 0
    difficulty = int(work["target_difficulty"])
    while time.time() < deadline:
        block_hash = calculate_pow_hash(
            version=1,
            prev_hash=work["prev_hash"],
            merkle_root=work["merkle_root"],
            timestamp=int(work["timestamp"]),
            bits=int(work["bits"]),
            nonce=nonce,
        )
        if check_difficulty(block_hash, difficulty):
            return nonce
        nonce += 1

    raise SmokeFailure(
        f"Failed to mine a valid nonce within {timeout_seconds}s for job {work.get('job_id')}"
    )


def force_confirmation_block(
    session: requests.Session,
    node_base_url: str,
    miner_address: Optional[str],
    mine_timeout_seconds: int,
) -> None:
    params = {"miner_address": miner_address} if miner_address else None
    work_response = session.get(
        api_url(node_base_url, "/api/mining/getwork"),
        params=params,
        timeout=20,
    )
    require(
        work_response.ok,
        f"Getwork failed: HTTP {work_response.status_code} body={work_response.text[:500]}",
    )
    work = work_response.json()
    nonce = find_valid_nonce(work, mine_timeout_seconds)

    submit_payload: Dict[str, Any] = {"job_id": work["job_id"], "nonce": nonce}
    if work.get("miner_address"):
        submit_payload["miner_address"] = work["miner_address"]

    response = session.post(
        api_url(node_base_url, "/api/mining/submit"),
        json=submit_payload,
        timeout=20,
    )
    require(
        response.ok,
        f"Force-confirm block submission failed: HTTP {response.status_code} body={response.text[:500]}",
    )
    payload = response.json()
    require(payload.get("accepted") is True, f"Force-confirm block was rejected: {payload}")
    print_step(
        "Submitted confirmation block"
        f" height={payload.get('height')} hash={payload.get('hash')} nonce={nonce}"
    )


def verify_trade_response(
    payload: Dict[str, Any],
    expected_fee: float,
) -> Tuple[str, str]:
    require(payload.get("fee_applied_on_chain") is True, f"Trade did not settle on-chain: {payload}")
    require(
        payload.get("fee_settlement_policy") == "canonical_on_chain",
        f"Unexpected settlement policy: {payload.get('fee_settlement_policy')}",
    )

    observed_fee = round(float(payload.get("trade_fee", -1)), 8)
    require(
        observed_fee == round(expected_fee, 8),
        f"Unexpected trade fee {observed_fee:.8f}; expected {expected_fee:.8f}",
    )

    trade_id = payload.get("trade_id")
    settlement_txid = payload.get("fee_settlement_txid")
    require(bool(trade_id), f"Trade response missing trade_id: {payload}")
    require(bool(settlement_txid), f"Trade response missing fee_settlement_txid: {payload}")
    return trade_id, settlement_txid


def verify_database_state(
    db: Any,
    context: SmokeContext,
    initial_wallet_balance: float,
    token_amount: float,
    wepo_amount: float,
) -> None:
    expected_fee = round(wepo_amount * 0.001, 8)
    expected_wallet_balance = round(initial_wallet_balance - wepo_amount - expected_fee, 8)

    wallet_doc = db.wallets.find_one({"address": context.wallet_address})
    require(wallet_doc is not None, "Wallet record disappeared during smoke test")
    observed_wallet_balance = round(float(wallet_doc.get("balance", 0.0)), 8)
    require(
        observed_wallet_balance == expected_wallet_balance,
        f"Wallet balance mismatch: observed {observed_wallet_balance:.8f}, expected {expected_wallet_balance:.8f}",
    )

    balance_doc = db.rwa_balances.find_one(
        {"token_id": context.token_id, "address": context.wallet_address}
    )
    require(balance_doc is not None, "RWA balance record missing")
    observed_token_balance = round(float(balance_doc.get("balance", 0.0)), 8)
    require(
        observed_token_balance == round(token_amount, 8),
        f"RWA balance mismatch: observed {observed_token_balance:.8f}, expected {token_amount:.8f}",
    )

    trade_doc = db.rwa_trades.find_one({"trade_id": context.trade_id})
    require(trade_doc is not None, f"Trade record {context.trade_id} missing from Mongo")
    require(
        trade_doc.get("fee_settlement", {}).get("settlement_txid") == context.settlement_txid,
        f"Trade record settlement txid mismatch: {trade_doc}",
    )
    require(
        trade_doc.get("fee_settlement", {}).get("settlement_policy") == "canonical_on_chain",
        f"Trade record settlement policy mismatch: {trade_doc}",
    )

    ledger_doc = db.application_fee_ledger.find_one(
        {
            "fee_type": "rwa_trade",
            "settlement_txid": context.settlement_txid,
        }
    )
    require(
        ledger_doc is not None,
        f"Application fee ledger record missing for settlement tx {context.settlement_txid}",
    )
    require(
        ledger_doc.get("settlement_policy") == "canonical_on_chain",
        f"Ledger settlement policy mismatch: {ledger_doc}",
    )
    require(
        ledger_doc.get("applied_on_chain") is True,
        f"Ledger applied_on_chain mismatch: {ledger_doc}",
    )
    observed_ledger_fee = round(float(ledger_doc.get("fee_amount", 0.0)), 8)
    require(
        observed_ledger_fee == expected_fee,
        f"Ledger fee mismatch: observed {observed_ledger_fee:.8f}, expected {expected_fee:.8f}",
    )


def cleanup_artifacts(db: Any, context: SmokeContext) -> None:
    db.rwa_balances.delete_many(
        {"token_id": context.token_id, "address": context.wallet_address}
    )
    db.wallets.delete_many({"address": context.wallet_address})
    db.rwa_tokens.delete_many({"_id": context.token_id})

    if context.trade_id:
        db.rwa_trades.delete_many({"trade_id": context.trade_id})

    if context.settlement_txid:
        db.application_fee_ledger.delete_many({"settlement_txid": context.settlement_txid})


def build_context() -> SmokeContext:
    smoke_id = f"smoke_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    return SmokeContext(
        smoke_id=smoke_id,
        wallet_address=make_wepo_address(smoke_id),
        wallet_username=smoke_id,
        token_id=f"rwa_{smoke_id}",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke test canonical backend-originated WEPO fee settlement"
    )
    parser.add_argument(
        "--backend-base-url",
        default=os.getenv("WEPO_BACKEND_API_URL", DEFAULT_BACKEND_BASE_URL),
        help="Backend base URL without the /api suffix",
    )
    parser.add_argument(
        "--node-base-url",
        default=os.getenv("WEPO_NODE_API_URL", DEFAULT_NODE_BASE_URL),
        help="Node base URL without the /api suffix",
    )
    parser.add_argument(
        "--backend-env",
        default=str(DEFAULT_BACKEND_ENV_PATH),
        help="Path to backend .env used for Mongo defaults",
    )
    parser.add_argument(
        "--mongo-url",
        default=os.getenv("MONGO_URL"),
        help="Mongo URL override",
    )
    parser.add_argument(
        "--db-name",
        default=os.getenv("DB_NAME"),
        help="Mongo database name override",
    )
    parser.add_argument(
        "--settlement-address",
        default=os.getenv("WEPO_APP_FEE_SETTLEMENT_ADDRESS"),
        help="Settlement wallet address for optional preflight validation",
    )
    parser.add_argument(
        "--wallet-balance",
        type=float,
        default=DEFAULT_WALLET_BALANCE,
        help="Initial disposable wallet balance to seed in Mongo",
    )
    parser.add_argument(
        "--token-amount",
        type=float,
        default=DEFAULT_TOKEN_AMOUNT,
        help="RWA token amount to buy in the smoke trade",
    )
    parser.add_argument(
        "--wepo-amount",
        type=float,
        default=DEFAULT_WEPO_AMOUNT,
        help="WEPO notional for the smoke trade",
    )
    parser.add_argument(
        "--confirm-timeout",
        type=int,
        default=DEFAULT_CONFIRM_TIMEOUT_SECONDS,
        help="Seconds to wait for the settlement tx to appear on-chain",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        help="Polling interval in seconds while waiting for confirmation",
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep the disposable Mongo records after the smoke test",
    )
    parser.add_argument(
        "--disable-force-confirm",
        action="store_true",
        help="Do not call the node mining submit endpoint to confirm the settlement tx immediately",
    )
    parser.add_argument(
        "--mine-timeout",
        type=int,
        default=30,
        help="Seconds to spend mining a valid nonce when force-confirming locally",
    )
    return parser.parse_args()


def resolve_mongo_config(args: argparse.Namespace) -> Tuple[str, str]:
    env_values = load_backend_env(Path(args.backend_env))
    mongo_url = args.mongo_url or env_values.get("MONGO_URL") or "mongodb://127.0.0.1:27018"
    db_name = args.db_name or env_values.get("DB_NAME") or "test_database"
    return mongo_url, db_name


def main() -> int:
    args = parse_args()
    mongo_url, db_name = resolve_mongo_config(args)
    session = requests.Session()
    mongo_client: Optional[MongoClient] = None
    context = build_context()

    expected_fee = round(args.wepo_amount * 0.001, 8)

    print_step(f"backend={args.backend_base_url}")
    print_step(f"node={args.node_base_url}")
    print_step(f"mongo={mongo_url} db={db_name}")
    print_step(f"smoke_id={context.smoke_id}")

    try:
        preflight_http(session, args.backend_base_url, args.node_base_url)
        verify_settlement_wallet(
            session,
            args.node_base_url,
            args.settlement_address,
            expected_fee,
        )

        mongo_client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command("ping")
        db = mongo_client[db_name]

        seed_wallet(db.wallets, context, args.wallet_balance)
        seed_token(db.rwa_tokens, context)
        print_step(
            f"Seeded disposable wallet {context.wallet_address} and token {context.token_id}"
        )

        trade_payload = execute_trade(
            session,
            args.backend_base_url,
            context,
            args.token_amount,
            args.wepo_amount,
        )
        context.trade_id, context.settlement_txid = verify_trade_response(
            trade_payload,
            expected_fee,
        )
        print_step(
            f"Trade executed trade_id={context.trade_id} settlement_txid={context.settlement_txid}"
        )

        if not args.disable_force_confirm:
            force_confirmation_block(
                session,
                args.node_base_url,
                args.settlement_address,
                args.mine_timeout,
            )

        tx_payload = wait_for_confirmed_tx(
            session,
            args.node_base_url,
            context.settlement_txid,
            args.confirm_timeout,
            args.poll_interval,
        )
        print_step(
            "Settlement tx confirmed"
            f" block_height={tx_payload.get('block_height')}"
            f" confirmations={tx_payload.get('confirmations')}"
        )

        verify_database_state(
            db,
            context,
            args.wallet_balance,
            args.token_amount,
            args.wepo_amount,
        )
        print_step("Mongo verification passed for wallet, rwa_trades, rwa_balances, and application_fee_ledger")

        if not args.keep_artifacts:
            cleanup_artifacts(db, context)
            print_step("Temporary Mongo artifacts cleaned up")

        print_step("PASS canonical fee settlement smoke test completed successfully")
        return 0
    except (requests.RequestException, SmokeFailure, Exception) as exc:
        print_step(f"FAIL {exc}")
        if mongo_client is not None and not args.keep_artifacts:
            try:
                cleanup_artifacts(mongo_client[db_name], context)
            except Exception:
                pass
        return 1
    finally:
        session.close()
        if mongo_client is not None:
            mongo_client.close()


if __name__ == "__main__":
    sys.exit(main())
