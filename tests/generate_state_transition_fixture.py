#!/usr/bin/env python3
"""Generate a deterministic valid-chain fixture for the Node state oracle."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch
import tempfile


ROOT = Path(__file__).resolve().parents[1]
VECTOR_PATH = ROOT / "tests" / "vectors" / "wallet_signing_v3.json"
SIGNER_PATH = ROOT / "tests" / "oracle_sign_transaction.mjs"
WALLET_VECTOR = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
OWNER_ADDRESS = WALLET_VECTOR["expected"]["owner_address"]
OWNER_PUBLIC_KEY = bytes.fromhex(WALLET_VECTOR["expected"]["owner_public_key"])
OWNER_MNEMONIC = WALLET_VECTOR["owner_mnemonic"]

os.environ["WEPO_NETWORK_PROFILE"] = "test"
os.environ["WEPO_TEST_GENESIS_ADDRESS"] = OWNER_ADDRESS
os.environ["WEPO_TEST_GENESIS_TIMESTAMP"] = "1700000000"

CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

import blockchain as blockchain_module  # noqa: E402
import shielded as shielded_module  # noqa: E402
from blockchain import (  # noqa: E402
    BLOCK_TIME_INITIAL_18_MONTHS,
    BLOCK_TIME_POW_HYBRID,
    BLOCK_TIME_POS,
    MIN_STAKE_AMOUNT,
    MSG_KEY_REGISTER_MIN_FEE,
    RWA_CREATION_MIN_FEE,
    POS_ACTIVATION_HEIGHT,
    COIN,
    TOTAL_INITIAL_BLOCKS,
    Transaction,
    TransactionInput,
    TransactionOutput,
    WepoBlockchain,
)


FIXTURE_SCHEMA = "wepo-state-transition-oracle-v1"
STATE_DOMAIN = b"WEPO_STATE_ORACLE_V1\x00"


def _sign(unsigned_tx: dict) -> dict:
    request = json.dumps(
        {"mnemonic": OWNER_MNEMONIC, "network": "test", "unsigned_tx": unsigned_tx},
        separators=(",", ":"),
        ensure_ascii=False,
    )
    result = subprocess.run(
        ["node", str(SIGNER_PATH)],
        cwd=ROOT,
        input=request,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + "\n" + result.stderr)
    response = json.loads(result.stdout)
    if response["address"] != OWNER_ADDRESS:
        raise RuntimeError("Fixture signer derived an unexpected owner address")
    return response["signed_tx"]


def _sign_message(message: bytes) -> tuple[bytes, bytes]:
    request = json.dumps(
        {"mnemonic": OWNER_MNEMONIC, "message_hex": message.hex()},
        separators=(",", ":"),
    )
    result = subprocess.run(
        ["node", str(SIGNER_PATH)],
        cwd=ROOT,
        input=request,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + "\n" + result.stderr)
    response = json.loads(result.stdout)
    if (
        response["address"] != OWNER_ADDRESS
        or bytes.fromhex(response["public_key"]) != OWNER_PUBLIC_KEY
        or response["message_hex"] != message.hex()
    ):
        raise RuntimeError("Fixture message signer returned the wrong identity")
    return OWNER_PUBLIC_KEY, bytes.fromhex(response["signature"])


def _mine_at(chain: WepoBlockchain, timestamp: int, miner_address: str):
    block = chain.create_new_block(miner_address)
    block.transactions[0].timestamp = timestamp
    block.header.timestamp = timestamp
    block.header.merkle_root = block.calculate_merkle_root()
    mined = chain.miner.mine_block(block, 1)
    if mined is None or not chain.add_block(mined):
        raise RuntimeError(f"Could not mine deterministic fixture block {block.height}")
    return mined


def _mine_variable_at(
    chain: WepoBlockchain, timestamp: int, miner_address: str
):
    block = chain.create_new_block(miner_address)
    expected_bits = chain.calculate_expected_difficulty()
    block.transactions[0].timestamp = timestamp
    block.header.timestamp = timestamp
    block.header.bits = expected_bits
    block.header.merkle_root = block.calculate_merkle_root()
    mined = chain.miner.mine_block(block, expected_bits)
    if mined is None or not chain.add_block(mined):
        raise RuntimeError(f"Could not mine retarget fixture block {block.height}")
    return mined
def _unsigned_spend(
    *,
    prev_txid: str,
    prev_vout: int,
    amount: int,
    recipient_address: str,
    recipient_value: int,
    timestamp: int,
    label: str,
) -> dict:
    fee = 10_000
    change = amount - recipient_value - fee
    if change <= 0:
        raise ValueError("Fixture spend must leave positive change")
    return {
        "version": 1,
        "lock_time": 0,
        "fee": fee,
        "tx_type": "transfer",
        "timestamp": timestamp,
        "extra_data": {
            "label": label,
            "unicode": ["caf?", "??", "\ue000"],
        },
        "privacy_proof": None,
        "ring_signature": None,
        "shielded_bundle": None,
        "inputs": [
            {
                "prev_txid": prev_txid,
                "prev_vout": prev_vout,
                "sequence": 0xFFFFFFFF,
                "script_sig": "",
                "signature_type": "ecdsa",
                "quantum_signature": None,
                "quantum_public_key": None,
            }
        ],
        "outputs": [
            {
                "value": recipient_value,
                "address": recipient_address,
                "script_pubkey": "51",
            },
            {
                "value": change,
                "address": OWNER_ADDRESS,
                "script_pubkey": "51",
            },
        ],
    }


def _state_rows(chain: WepoBlockchain) -> list[dict]:
    rows = chain.conn.execute(
        "SELECT txid, vout, address, amount, script_pubkey, "
        "created_height, is_coinbase FROM utxos "
        "WHERE spent = FALSE ORDER BY txid, vout"
    ).fetchall()
    return [
        {
            "txid": txid,
            "vout": int(vout),
            "address": address,
            "amount": int(amount),
            "script_pubkey": bytes(script_pubkey).hex(),
            "created_height": int(created_height),
            "is_coinbase": bool(is_coinbase),
        }
        for (
            txid,
            vout,
            address,
            amount,
            script_pubkey,
            created_height,
            is_coinbase,
        ) in rows
    ]


def _state_commitment(rows: list[dict]) -> tuple[str, str]:
    payload = json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    preimage = STATE_DOMAIN + struct.pack("<I", len(payload)) + payload
    return payload.hex(), hashlib.sha256(preimage).hexdigest()




def _pow_headers_for_elapsed(elapsed: int, *, bits: int = 4) -> list[dict]:
    interval_count = 9
    spacing, remainder = divmod(elapsed, interval_count)
    timestamp = 0
    headers = [
        {"timestamp": timestamp, "bits": bits, "consensus_type": "pow"}
    ]
    for index in range(interval_count):
        timestamp += spacing + (1 if index < remainder else 0)
        headers.append(
            {"timestamp": timestamp, "bits": bits, "consensus_type": "pow"}
        )
    return headers


def _expected_difficulty(headers: list[dict], current_height: int) -> int:
    candidate = object.__new__(WepoBlockchain)
    candidate.fixed_difficulty = None
    candidate.current_difficulty = int(
        next(
            header["bits"]
            for header in reversed(headers)
            if header["consensus_type"] == "pow"
        )
    )
    candidate.chain = [
        SimpleNamespace(header=SimpleNamespace(**header)) for header in headers
    ]
    candidate.get_block_height = lambda: current_height
    return candidate.calculate_expected_difficulty()


def _difficulty_case(
    name: str,
    headers: list[dict],
    current_height: int,
) -> dict:
    return {
        "name": name,
        "current_height": current_height,
        "headers": headers,
        "expected_next_bits": _expected_difficulty(headers, current_height),
    }


def _difficulty_vectors() -> dict:
    intervals = 9
    initial = BLOCK_TIME_INITIAL_18_MONTHS
    hybrid = BLOCK_TIME_POW_HYBRID
    lower_scaled = initial * 3 * intervals
    upper_scaled = initial * 5 * intervals
    lower_below = (lower_scaled - 1) // 4
    lower_at = (lower_scaled + 3) // 4
    upper_at = upper_scaled // 4
    upper_above = upper_at + 1

    steady_pow = _pow_headers_for_elapsed(initial * intervals)
    interleaved = []
    for index, header in enumerate(steady_pow):
        interleaved.append(dict(header))
        if index < len(steady_pow) - 1:
            interleaved.append(
                {
                    "timestamp": header["timestamp"] + 1,
                    "bits": 0,
                    "consensus_type": "pos",
                }
            )

    post_phase_fast = (hybrid * 3 * intervals - 1) // 4
    cases = [
        _difficulty_case(
            "increase_below_lower_boundary",
            _pow_headers_for_elapsed(lower_below),
            10,
        ),
        _difficulty_case(
            "unchanged_at_lower_boundary",
            _pow_headers_for_elapsed(lower_at),
            10,
        ),
        _difficulty_case(
            "unchanged_at_upper_boundary",
            _pow_headers_for_elapsed(upper_at),
            10,
        ),
        _difficulty_case(
            "decrease_above_upper_boundary",
            _pow_headers_for_elapsed(upper_above),
            10,
        ),
        _difficulty_case(
            "pos_headers_do_not_affect_pow_retarget",
            interleaved,
            len(interleaved) - 1,
        ),
        _difficulty_case(
            "candidate_uses_post_activation_phase_target",
            _pow_headers_for_elapsed(post_phase_fast),
            TOTAL_INITIAL_BLOCKS,
        ),
        _difficulty_case(
            "insufficient_pow_history_keeps_last_bits",
            steady_pow[:5],
            5,
        ),
    ]
    return {
        "parameters": {
            "window_pow_headers": 10,
            "lower_ratio_numerator": 3,
            "lower_ratio_denominator": 4,
            "upper_ratio_numerator": 5,
            "upper_ratio_denominator": 4,
            "block_time_initial": initial,
            "block_time_pow_hybrid": hybrid,
            "total_initial_blocks": TOTAL_INITIAL_BLOCKS,
            "minimum_bits": 1,
        },
        "cases": cases,
    }
def _add_fork_metadata_transactions(
    chain: WepoBlockchain,
    *,
    branch_label: str,
    rwa_block_time: int,
    key_block_time: int,
) -> None:
    asset_hash = hashlib.sha256(
        f"WEPO fork {branch_label} asset commitment".encode("utf-8")
    ).hexdigest()
    transaction_time = rwa_block_time - 1
    with patch("blockchain.time.time", return_value=transaction_time):
        unsigned_rwa = chain.create_rwa_creation(
            owner_address=OWNER_ADDRESS,
            asset_hash=asset_hash,
            name=f"{branch_label.title()} Branch Asset",
            asset_type="reorg_fixture",
            fee=RWA_CREATION_MIN_FEE,
            metadata={
                "branch": branch_label,
                "purpose": "reorg_index_evidence",
            },
            asset_id=f"rwa_{branch_label}_branch",
            return_unsigned=True,
        )
    unsigned_rwa.timestamp = transaction_time
    rwa_transaction = Transaction.from_dict(_sign(unsigned_rwa.to_dict()))
    if not chain.add_transaction_to_mempool(rwa_transaction):
        raise RuntimeError(f"{branch_label} fork RWA creation was rejected")
    _mine_variable_at(chain, rwa_block_time, OWNER_ADDRESS)

    kem_public_key = hashlib.shake_256(
        f"WEPO_FORK_{branch_label.upper()}_MESSAGING_KEM".encode("utf-8")
    ).digest(1184).hex()
    transaction_time = key_block_time - 1
    with patch("blockchain.time.time", return_value=transaction_time):
        unsigned_key = chain.create_key_registration(
            OWNER_ADDRESS,
            kem_public_key,
            OWNER_PUBLIC_KEY.hex(),
            fee=MSG_KEY_REGISTER_MIN_FEE,
            return_unsigned=True,
        )
    unsigned_key.timestamp = transaction_time
    key_transaction = Transaction.from_dict(_sign(unsigned_key.to_dict()))
    if not chain.add_transaction_to_mempool(key_transaction):
        raise RuntimeError(
            f"{branch_label} fork messaging-key registration was rejected"
        )
    _mine_variable_at(chain, key_block_time, OWNER_ADDRESS)


def _branch_snapshot(
    chain: WepoBlockchain,
    name: str,
    blocks: list,
) -> dict:
    rows = _state_rows(chain)
    payload_hex, commitment = _state_commitment(rows)
    issued_supply = chain.get_issued_supply()
    unspent_total = sum(row["amount"] for row in rows)
    if issued_supply != unspent_total:
        raise RuntimeError(f"{name} branch supply does not match its UTXO total")
    rwa_assets = _rwa_rows(chain)
    messaging_keys = _messaging_key_rows(chain)
    pow_work, pos_blocks = chain._chain_score(blocks)
    return {
        "name": name,
        "blocks": [
            json.loads(chain.serialize_block(block)) for block in blocks
        ],
        "expected": {
            "height": blocks[-1].height,
            "tip": blocks[-1].get_block_hash(),
            "pow_hashes": [
                chain.miner.calculate_pow_hash(block.header)
                for block in blocks
            ],
            "score": {
                "pow_work": str(pow_work),
                "pos_blocks": pos_blocks,
            },
            "issued_supply": issued_supply,
            "utxo_total": unspent_total,
            "utxos": rows,
            "state_payload_utf8_hex": payload_hex,
            "state_commitment": commitment,
            "rwa_assets": rwa_assets,
            "messaging_keys": messaging_keys,
        },
    }


def _fork_choice_fixture(data_root: str) -> dict:
    main = WepoBlockchain(
        data_dir=str(Path(data_root) / "fork-main"),
        network_profile="test",
        fixed_difficulty=None,
    )
    side = WepoBlockchain(
        data_dir=str(Path(data_root) / "fork-side"),
        network_profile="test",
        fixed_difficulty=None,
    )
    try:
        if main.chain[0].get_block_hash() != side.chain[0].get_block_hash():
            raise RuntimeError("Fork fixture nodes have different genesis blocks")
        genesis_time = main.chain[0].header.timestamp

        _mine_variable_at(
            main,
            genesis_time + BLOCK_TIME_INITIAL_18_MONTHS,
            OWNER_ADDRESS,
        )
        _add_fork_metadata_transactions(
            main,
            branch_label="losing",
            rwa_block_time=genesis_time + 2 * BLOCK_TIME_INITIAL_18_MONTHS,
            key_block_time=genesis_time + 3 * BLOCK_TIME_INITIAL_18_MONTHS,
        )
        for height in range(4, 16):
            _mine_variable_at(
                main,
                genesis_time + height * BLOCK_TIME_INITIAL_18_MONTHS,
                OWNER_ADDRESS,
            )

        _mine_variable_at(side, genesis_time + 1, OWNER_ADDRESS)
        _add_fork_metadata_transactions(
            side,
            branch_label="winning",
            rwa_block_time=genesis_time + 2,
            key_block_time=genesis_time + 3,
        )
        for height in range(4, 11):
            _mine_variable_at(
                side,
                genesis_time + height,
                OWNER_ADDRESS,
            )

        main_blocks = list(main.chain)
        side_blocks = list(side.chain)
        if [block.header.bits for block in main_blocks[1:]] != [1] * 15:
            raise RuntimeError("Slow branch did not retain difficulty 1")
        if [block.header.bits for block in side_blocks[1:]] != [1] * 9 + [2]:
            raise RuntimeError("Fast branch did not cross the live retarget")

        main_snapshot = _branch_snapshot(
            main, "long_slow_difficulty_1", main_blocks
        )
        side_snapshot = _branch_snapshot(
            side, "short_fast_retargeted", side_blocks
        )
        if int(side_snapshot["expected"]["score"]["pow_work"]) <= int(
            main_snapshot["expected"]["score"]["pow_work"]
        ):
            raise RuntimeError("Short retargeted branch does not outrank main")
        if (
            main_snapshot["expected"]["rwa_assets"]
            == side_snapshot["expected"]["rwa_assets"]
            or main_snapshot["expected"]["messaging_keys"]
            == side_snapshot["expected"]["messaging_keys"]
        ):
            raise RuntimeError("Fork metadata state did not diverge")

        losing_tip = main_snapshot["expected"]["tip"]
        adoption_results = []
        for block in side_blocks[1:]:
            copied = main.deserialize_block(
                json.loads(side.serialize_block(block))
            )
            adoption_results.append(main.add_block_with_priority(copied))

        if adoption_results != ([False] * 9 + [True]):
            raise RuntimeError("Python node did not adopt at the expected tip")
        if main.get_latest_block().get_block_hash() != side_snapshot["expected"]["tip"]:
            raise RuntimeError("Python node adopted the wrong fork tip")

        canonical_rows = _state_rows(main)
        canonical_payload_hex, canonical_commitment = _state_commitment(
            canonical_rows
        )
        canonical_supply = main.get_issued_supply()
        canonical_rwa_assets = _rwa_rows(main)
        canonical_messaging_keys = _messaging_key_rows(main)
        if canonical_rows != side_snapshot["expected"]["utxos"]:
            raise RuntimeError("Adopted Python UTXO state differs from winner")
        if canonical_supply != side_snapshot["expected"]["issued_supply"]:
            raise RuntimeError("Adopted Python supply differs from winner")
        if canonical_rwa_assets != side_snapshot["expected"]["rwa_assets"]:
            raise RuntimeError("Adopted Python RWA index differs from winner")
        if canonical_messaging_keys != side_snapshot["expected"]["messaging_keys"]:
            raise RuntimeError("Adopted Python messaging index differs from winner")

        return {
            "parameters": {
                "pow_work": "2^(4*bits)",
                "branch_order": "pow_work_then_pos_count",
                "activation_height": POS_ACTIVATION_HEIGHT,
                "pre_pos_pow_reward": main.calculate_block_reward(1),
                "phase_2a_end_height": main.network_profile.phase_2a_end_height,
                "phase_2a_pow_reward": main.calculate_block_reward(
                    POS_ACTIVATION_HEIGHT + 1
                ),
                "rwa_creation_min_fee": RWA_CREATION_MIN_FEE,
                "messaging_key_register_min_fee": MSG_KEY_REGISTER_MIN_FEE,
                "ml_kem768_public_key_hex_length": 1184 * 2,
                "ml_dsa44_public_key_hex_length": 1312 * 2,
                "metadata_fee_policy": "fully_redistributed_via_coinbase",
            },
            "branches": [main_snapshot, side_snapshot],
            "expected": {
                "common_ancestor_height": 0,
                "winner": side_snapshot["name"],
                "loser": main_snapshot["name"],
                "python_adoption_results": adoption_results,
                "losing_tip_preserved_noncanonical": (
                    losing_tip in main.block_index
                    and losing_tip not in main.main_chain_hashes
                ),
                "canonical_height": main.get_block_height(),
                "canonical_tip": main.get_latest_block().get_block_hash(),
                "canonical_issued_supply": canonical_supply,
                "canonical_utxos": canonical_rows,
                "canonical_state_payload_utf8_hex": canonical_payload_hex,
                "canonical_state_commitment": canonical_commitment,
                "canonical_rwa_assets": canonical_rwa_assets,
                "canonical_messaging_keys": canonical_messaging_keys,
                "losing_rwa_assets_removed": all(
                    row not in canonical_rwa_assets
                    for row in main_snapshot["expected"]["rwa_assets"]
                ),
                "winning_rwa_assets_present": (
                    canonical_rwa_assets
                    == side_snapshot["expected"]["rwa_assets"]
                ),
                "losing_messaging_keys_replaced": all(
                    row not in canonical_messaging_keys
                    for row in main_snapshot["expected"]["messaging_keys"]
                ),
                "winning_messaging_keys_selected": (
                    canonical_messaging_keys
                    == side_snapshot["expected"]["messaging_keys"]
                ),
            },
        }
    finally:
        main.conn.close()
        side.conn.close()


def _stake_rows(chain: WepoBlockchain) -> list[dict]:
    rows = chain.conn.execute(
        "SELECT stake_id, staker_address, amount, start_height, start_time, "
        "last_reward_height, total_rewards, status, unlock_height, lock_txid, "
        "lock_vout, deactivation_txid FROM stakes ORDER BY staker_address, stake_id"
    ).fetchall()
    fields = (
        "stake_id",
        "staker_address",
        "amount",
        "start_height",
        "start_time",
        "last_reward_height",
        "total_rewards",
        "status",
        "unlock_height",
        "lock_txid",
        "lock_vout",
        "deactivation_txid",
    )
    return [
        {
            field: (
                int(value)
                if field in {
                    "amount",
                    "start_height",
                    "start_time",
                    "last_reward_height",
                    "total_rewards",
                    "unlock_height",
                    "lock_vout",
                }
                and value is not None
                else value
            )
            for field, value in zip(fields, row)
        }
        for row in rows
    ]



def _masternode_rows(chain: WepoBlockchain) -> list[dict]:
    rows = chain.conn.execute(
        "SELECT masternode_id, operator_address, collateral_txid, "
        "collateral_vout, ip_address, port, start_height, start_time, "
        "last_ping, status, total_rewards, deactivation_txid "
        "FROM masternodes ORDER BY masternode_id"
    ).fetchall()
    fields = (
        "masternode_id",
        "operator_address",
        "collateral_txid",
        "collateral_vout",
        "ip_address",
        "port",
        "start_height",
        "start_time",
        "last_ping",
        "status",
        "total_rewards",
        "deactivation_txid",
    )
    return [
        {
            field: (
                int(value)
                if field
                in {
                    "collateral_vout",
                    "port",
                    "start_height",
                    "start_time",
                    "last_ping",
                    "total_rewards",
                }
                and value is not None
                else value
            )
            for field, value in zip(fields, row)
        }
        for row in rows
    ]


def _reward_rows(chain: WepoBlockchain) -> list[dict]:
    rows = chain.conn.execute(
        "SELECT reward_id, recipient_address, recipient_type, amount, "
        "block_height, block_hash, timestamp FROM staking_rewards "
        "ORDER BY block_height, reward_id"
    ).fetchall()
    fields = (
        "reward_id",
        "recipient_address",
        "recipient_type",
        "amount",
        "block_height",
        "block_hash",
        "timestamp",
    )
    return [
        {
            field: (
                int(value)
                if field in {"amount", "block_height", "timestamp"}
                else value
            )
            for field, value in zip(fields, row)
        }
        for row in rows
    ]


def _rwa_rows(chain: WepoBlockchain) -> list[dict]:
    rows = chain.conn.execute(
        "SELECT asset_id, owner_address, asset_hash, name, asset_type, "
        "create_txid, create_height, created_time, metadata_json "
        "FROM rwa_assets ORDER BY asset_id"
    ).fetchall()
    return [
        {
            "asset_id": row[0],
            "owner_address": row[1],
            "asset_hash": row[2],
            "name": row[3],
            "asset_type": row[4],
            "create_txid": row[5],
            "create_height": int(row[6]),
            "created_time": int(row[7]),
            "metadata": json.loads(row[8]) if row[8] else {},
        }
        for row in rows
    ]


def _messaging_key_rows(chain: WepoBlockchain) -> list[dict]:
    rows = chain.conn.execute(
        "SELECT address, kem_pub, sig_pub, register_txid, "
        "register_height, registered_time "
        "FROM messaging_keys ORDER BY address"
    ).fetchall()
    return [
        {
            "address": row[0],
            "kem_pub": row[1],
            "sig_pub": row[2],
            "register_txid": row[3],
            "register_height": int(row[4]),
            "registered_time": int(row[5]),
        }
        for row in rows
    ]


class _StateOracleShieldedVerifier:
    """Audited test double for state-machine evidence, never proof evidence."""

    def verify(self, statement_digest: bytes, proof: bytes) -> bool:
        return (
            len(statement_digest) == 32
            and proof.startswith(b"state-oracle:")
        )


def _shielded_index_rows(chain: WepoBlockchain) -> dict:
    commitments = chain.conn.execute(
        "SELECT position, commitment, block_height, txid, output_index "
        "FROM shielded_commitments ORDER BY position"
    ).fetchall()
    nullifiers = chain.conn.execute(
        "SELECT nullifier, block_height, txid, spend_index "
        "FROM shielded_nullifiers ORDER BY block_height, txid, spend_index"
    ).fetchall()
    anchors = chain.conn.execute(
        "SELECT anchor, block_height FROM shielded_anchors "
        "ORDER BY block_height, anchor"
    ).fetchall()
    return {
        "commitments": [
            {
                "position": int(row[0]),
                "commitment": bytes(row[1]).hex(),
                "block_height": int(row[2]),
                "txid": row[3],
                "output_index": int(row[4]),
            }
            for row in commitments
        ],
        "nullifiers": [
            {
                "nullifier": bytes(row[0]).hex(),
                "block_height": int(row[1]),
                "txid": row[2],
                "spend_index": int(row[3]),
            }
            for row in nullifiers
        ],
        "anchors": [
            {"anchor": bytes(row[0]).hex(), "block_height": int(row[1])}
            for row in anchors
        ],
    }


def _shielded_scenario_fixture(data_root: str) -> dict:
    old_enabled = blockchain_module.PRIVACY_CONSENSUS_ENABLED
    old_height = blockchain_module.SHIELDED_ACTIVATION_HEIGHT
    old_verifier = shielded_module.active_verifier()
    old_audited = shielded_module.verifier_is_audited()
    chain = None
    blockchain_module.PRIVACY_CONSENSUS_ENABLED = True
    blockchain_module.SHIELDED_ACTIVATION_HEIGHT = 1
    shielded_module.register_verifier(
        _StateOracleShieldedVerifier(),
        audit_approved=True,
    )
    try:
        chain = WepoBlockchain(
            data_dir=str(Path(data_root) / "shielded-state"),
            network_profile="test",
            fixed_difficulty=1,
        )
        genesis_time = chain.chain[0].header.timestamp
        genesis_utxo = chain.conn.execute(
            "SELECT txid, vout, amount FROM utxos "
            "WHERE created_height = 0 AND spent = FALSE"
        ).fetchone()
        if genesis_utxo is None:
            raise RuntimeError("Shielded fixture genesis UTXO is missing")

        shielded_value = 5 * COIN
        fee = 10_000
        change = int(genesis_utxo[2]) - shielded_value - fee
        first_commitment = shielded_module.field_elements_to_bytes(
            [1_001, 1_002, 1_003, 1_004]
        )
        first_bundle = shielded_module.ShieldedBundle(
            outputs=[
                shielded_module.OutputDescription(
                    commitment=first_commitment,
                    enc_note=b"state-oracle-note-one",
                )
            ],
            value_balance=shielded_value,
            proof=b"state-oracle:shield",
        )
        first_unsigned = Transaction(
            version=1,
            inputs=[
                TransactionInput(
                    prev_txid=genesis_utxo[0],
                    prev_vout=int(genesis_utxo[1]),
                    script_sig=b"signature_placeholder",
                    sequence=0xFFFFFFFF,
                )
            ],
            outputs=[
                TransactionOutput(
                    value=change,
                    script_pubkey=b"change_script",
                    address=OWNER_ADDRESS,
                )
            ],
            lock_time=0,
            fee=fee,
            tx_type="transfer",
            shielded_bundle=first_bundle,
            timestamp=genesis_time + 60,
        )
        first_transaction = Transaction.from_dict(
            _sign(first_unsigned.to_dict())
        )
        if not chain.add_transaction_to_mempool(first_transaction):
            raise RuntimeError("Shielded fixture deposit was rejected")
        _mine_at(chain, genesis_time + 120, OWNER_ADDRESS)
        first_root = chain.shielded_tree.root()

        nullifier = shielded_module.field_elements_to_bytes(
            [2_001, 2_002, 2_003, 2_004]
        )
        second_commitment = shielded_module.field_elements_to_bytes(
            [3_001, 3_002, 3_003, 3_004]
        )
        second_bundle = shielded_module.ShieldedBundle(
            spends=[
                shielded_module.SpendDescription(
                    anchor=first_root,
                    nullifier=nullifier,
                )
            ],
            outputs=[
                shielded_module.OutputDescription(
                    commitment=second_commitment,
                    enc_note=b"state-oracle-note-two",
                )
            ],
            value_balance=0,
            proof=b"state-oracle:spend",
        )
        second_transaction = Transaction(
            version=1,
            inputs=[],
            outputs=[],
            lock_time=0,
            fee=0,
            tx_type="transfer",
            shielded_bundle=second_bundle,
            timestamp=genesis_time + 180,
        )
        if not chain.add_transaction_to_mempool(second_transaction):
            raise RuntimeError("Shielded fixture spend was rejected")
        _mine_at(chain, genesis_time + 240, OWNER_ADDRESS)
        final_root = chain.shielded_tree.root()
        blocks = list(chain.chain)
        final_indexes = _shielded_index_rows(chain)
        if (
            len(final_indexes["commitments"]) != 2
            or len(final_indexes["nullifiers"]) != 1
            or final_indexes["anchors"][-1]["anchor"] != final_root.hex()
        ):
            raise RuntimeError("Shielded fixture indexes are incomplete")

        chain._rebuild_canonical_state_from_blocks(blocks[:2])
        chain.conn.commit()
        disconnected_indexes = _shielded_index_rows(chain)
        disconnected_root = chain.shielded_tree.root()
        if (
            len(disconnected_indexes["commitments"]) != 1
            or disconnected_indexes["nullifiers"]
            or disconnected_root != first_root
        ):
            raise RuntimeError(
                "Shielded fixture disconnect did not restore prefix state"
            )

        chain._rebuild_canonical_state_from_blocks(blocks)
        chain.conn.commit()
        replayed_indexes = _shielded_index_rows(chain)
        if (
            replayed_indexes != final_indexes
            or chain.shielded_tree.root() != final_root
        ):
            raise RuntimeError(
                "Shielded fixture canonical replay changed final state"
            )

        rows = _state_rows(chain)
        payload_hex, commitment = _state_commitment(rows)
        issued_supply = chain.get_issued_supply()
        utxo_total = sum(row["amount"] for row in rows)
        if issued_supply - utxo_total != shielded_value:
            raise RuntimeError(
                "Shielded pool balance does not reconcile with supply"
            )

        first_sighash = first_transaction.get_canonical_sighash()
        second_sighash = second_transaction.get_canonical_sighash()
        return {
            "parameters": {
                "activation_height": 1,
                "merkle_depth": shielded_module.MERKLE_DEPTH,
                "anchor_window": 100,
                "maximum_spends": shielded_module.MAX_SHIELDED_SPENDS,
                "maximum_outputs": shielded_module.MAX_SHIELDED_OUTPUTS,
                "maximum_proof_bytes": (
                    shielded_module.MAX_SHIELDED_PROOF_BYTES
                ),
                "pool_hash": shielded_module.POOL_HASH_ALGORITHM,
                "node_hash_domain": shielded_module.DOMAIN_NODE,
                "empty_leaf_domain": shielded_module.DOMAIN_LEAF,
                "bundle_statement_tag": (
                    "WEPO-Shielded-BundleStatement-v1"
                ),
                "proof_evidence": (
                    "state-machine test double; real proof validity is covered "
                    "by test_ghost_verifier_integration.py"
                ),
            },
            "blocks": [
                json.loads(chain.serialize_block(block))
                for block in blocks
            ],
            "expected": {
                "height": chain.get_block_height(),
                "tip": chain.get_latest_block().get_block_hash(),
                "pow_hashes": [
                    chain.miner.calculate_pow_hash(block.header)
                    for block in blocks
                ],
                "issued_supply": issued_supply,
                "utxo_total": utxo_total,
                "shielded_pool_balance": shielded_value,
                "supply_minus_transparent_utxo_total": (
                    issued_supply - utxo_total
                ),
                "utxos": rows,
                "state_payload_utf8_hex": payload_hex,
                "state_commitment": commitment,
                "commitments": final_indexes["commitments"],
                "nullifiers": final_indexes["nullifiers"],
                "anchors": final_indexes["anchors"],
                "tree_root": final_root.hex(),
                "transaction_ids": [
                    first_transaction.calculate_txid(),
                    second_transaction.calculate_txid(),
                ],
                "sighashes": [
                    first_sighash.hex(),
                    second_sighash.hex(),
                ],
                "statement_digests": [
                    first_bundle.statement_digest(first_sighash).hex(),
                    second_bundle.statement_digest(second_sighash).hex(),
                ],
                "disconnect": {
                    "height": 1,
                    "tree_root": disconnected_root.hex(),
                    "commitments": disconnected_indexes["commitments"],
                    "nullifiers": disconnected_indexes["nullifiers"],
                    "anchors": disconnected_indexes["anchors"],
                },
                "reconnect_restored_exact_state": (
                    replayed_indexes == final_indexes
                    and chain.shielded_tree.root() == final_root
                ),
            },
        }
    finally:
        if chain is not None:
            chain.conn.close()
        blockchain_module.PRIVACY_CONSENSUS_ENABLED = old_enabled
        blockchain_module.SHIELDED_ACTIVATION_HEIGHT = old_height
        shielded_module.register_verifier(
            old_verifier,
            audit_approved=old_audited,
        )


def _pos_scenario_fixture(data_root: str) -> dict:
    chain = WepoBlockchain(
        data_dir=str(Path(data_root) / "pos-parent"),
        network_profile="test",
        fixed_difficulty=None,
    )
    try:
        genesis_time = chain.chain[0].header.timestamp
        for height in range(1, POS_ACTIVATION_HEIGHT + 2):
            _mine_variable_at(
                chain,
                genesis_time + height * BLOCK_TIME_INITIAL_18_MONTHS,
                OWNER_ADDRESS,
            )

        stake_time = chain.get_latest_block().header.timestamp + 1
        with patch("blockchain.time.time", return_value=stake_time):
            unsigned_stake = chain.create_stake(
                OWNER_ADDRESS,
                MIN_STAKE_AMOUNT,
                return_unsigned=True,
            )
        unsigned_stake.timestamp = stake_time
        stake_signed = _sign(unsigned_stake.to_dict())
        stake_transaction = Transaction.from_dict(stake_signed)
        if not chain.add_transaction_to_mempool(stake_transaction):
            raise RuntimeError("PoS fixture stake transaction was rejected")

        stake_block_time = (
            genesis_time
            + (POS_ACTIVATION_HEIGHT + 2) * BLOCK_TIME_INITIAL_18_MONTHS
        )
        _mine_variable_at(chain, stake_block_time, OWNER_ADDRESS)
        active_stakes = _stake_rows(chain)
        if len(active_stakes) != 1 or active_stakes[0]["status"] != "active":
            raise RuntimeError("PoS fixture did not create one active stake")

        candidate_height = chain.get_block_height() + 1
        parent_hash = chain.get_latest_block().get_block_hash()
        selected = chain.select_pos_validator(
            candidate_height,
            parent_hash=parent_hash,
        )
        if selected != OWNER_ADDRESS:
            raise RuntimeError("PoS fixture selected an unexpected validator")

        slot_anchor = chain.get_latest_block().header.timestamp
        candidate_time = slot_anchor + BLOCK_TIME_POS
        with patch("blockchain.time.time", return_value=candidate_time):
            unsigned_candidate = chain.create_pos_block_template(
                OWNER_ADDRESS,
                OWNER_PUBLIC_KEY,
            )
        if unsigned_candidate is None:
            raise RuntimeError("PoS fixture could not create a block template")
        signing_message = chain.get_pos_signing_message(unsigned_candidate)
        public_key, signature = _sign_message(signing_message)
        if public_key != OWNER_PUBLIC_KEY:
            raise RuntimeError("PoS fixture signer returned the wrong public key")
        candidate = chain.finalize_pos_block(unsigned_candidate, signature)
        if (
            candidate is None
            or not chain.validate_pos_block(candidate)
            or not chain.validate_block(candidate)
        ):
            raise RuntimeError("PoS fixture candidate failed Python validation")

        parent = _branch_snapshot(
            chain,
            "pos_parent",
            list(chain.chain),
        )
        pos_reward_per_block = chain.calculate_pos_reward(candidate.height)
        if pos_reward_per_block != (25 * COIN) // 2:
            raise RuntimeError("PoS fixture has an unexpected initial reward")

        if not chain.add_block(candidate):
            raise RuntimeError("PoS fixture candidate could not be committed")
        stake_id = active_stakes[0]["stake_id"]

        funding_time = candidate_time + 1
        required_masternode_collateral = (
            chain.get_masternode_collateral_for_height(
                chain.get_block_height() + 2
            )
        )
        with patch("blockchain.time.time", return_value=funding_time):
            unsigned_funding = chain.create_transaction(
                OWNER_ADDRESS,
                OWNER_ADDRESS,
                required_masternode_collateral,
                fee=0,
            )
        if unsigned_funding is None:
            raise RuntimeError("PoS fixture could not fund masternode collateral")
        unsigned_funding.timestamp = funding_time
        funding_transaction = Transaction.from_dict(
            _sign(unsigned_funding.to_dict())
        )
        if not chain.add_transaction_to_mempool(funding_transaction):
            raise RuntimeError("PoS fixture masternode funding was rejected")
        funding_block = _mine_variable_at(
            chain,
            candidate_time + BLOCK_TIME_INITIAL_18_MONTHS,
            OWNER_ADDRESS,
        )

        registration_time = funding_block.header.timestamp + 1
        with patch("blockchain.time.time", return_value=registration_time):
            unsigned_registration = chain.create_masternode(
                OWNER_ADDRESS,
                funding_transaction.calculate_txid(),
                0,
                ip_address="203.0.113.10",
                port=22567,
                return_unsigned=True,
                fee=0,
            )
        unsigned_registration.timestamp = registration_time
        registration_transaction = Transaction.from_dict(
            _sign(unsigned_registration.to_dict())
        )
        if not chain.add_transaction_to_mempool(registration_transaction):
            raise RuntimeError("PoS fixture masternode registration was rejected")
        registration_block = _mine_variable_at(
            chain,
            candidate_time + 2 * BLOCK_TIME_INITIAL_18_MONTHS,
            OWNER_ADDRESS,
        )
        registered_masternodes = _masternode_rows(chain)
        if (
            len(registered_masternodes) != 1
            or registered_masternodes[0]["status"] != "active"
            or registered_masternodes[0]["total_rewards"] != 0
        ):
            raise RuntimeError(
                "PoS fixture did not create one unrewarded active masternode"
            )

        joint_reward_block = _mine_variable_at(
            chain,
            candidate_time + 3 * BLOCK_TIME_INITIAL_18_MONTHS,
            OWNER_ADDRESS,
        )
        masternode_id = registered_masternodes[0]["masternode_id"]
        stake_deactivation_time = joint_reward_block.header.timestamp + 1
        with patch(
            "blockchain.time.time",
            return_value=stake_deactivation_time,
        ):
            unsigned_stake_deactivation = chain.deactivate_stake(
                stake_id,
                OWNER_ADDRESS,
                return_unsigned=True,
                fee=0,
            )
        unsigned_stake_deactivation.timestamp = stake_deactivation_time
        stake_deactivation_transaction = Transaction.from_dict(
            _sign(unsigned_stake_deactivation.to_dict())
        )
        if not chain.add_transaction_to_mempool(
            stake_deactivation_transaction
        ):
            raise RuntimeError("PoS fixture stake deactivation was rejected")

        masternode_deactivation_time = stake_deactivation_time + 1
        with patch(
            "blockchain.time.time",
            return_value=masternode_deactivation_time,
        ):
            unsigned_masternode_deactivation = chain.deactivate_masternode(
                masternode_id,
                OWNER_ADDRESS,
                return_unsigned=True,
                fee=0,
            )
        unsigned_masternode_deactivation.timestamp = (
            masternode_deactivation_time
        )
        masternode_deactivation_transaction = Transaction.from_dict(
            _sign(unsigned_masternode_deactivation.to_dict())
        )
        if not chain.add_transaction_to_mempool(
            masternode_deactivation_transaction
        ):
            raise RuntimeError("PoS fixture masternode deactivation was rejected")

        deactivation_block = _mine_variable_at(
            chain,
            candidate_time + 4 * BLOCK_TIME_INITIAL_18_MONTHS,
            OWNER_ADDRESS,
        )
        if chain.get_active_stakes() or chain.get_active_masternodes():
            raise RuntimeError(
                "PoS fixture protocol locks remained active after deactivation"
            )
        post_deactivation_block = _mine_variable_at(
            chain,
            candidate_time + 5 * BLOCK_TIME_INITIAL_18_MONTHS,
            OWNER_ADDRESS,
        )

        asset_hash = hashlib.sha256(
            b"WEPO state-oracle property-title commitment v1"
        ).hexdigest()
        rwa_time = post_deactivation_block.header.timestamp + 1
        with patch("blockchain.time.time", return_value=rwa_time):
            unsigned_rwa = chain.create_rwa_creation(
                owner_address=OWNER_ADDRESS,
                asset_hash=asset_hash,
                name="Oracle Property Title",
                asset_type="real_estate",
                fee=RWA_CREATION_MIN_FEE,
                metadata={
                    "document_version": 1,
                    "jurisdiction": "US-NY",
                },
                asset_id="rwa_state_oracle_001",
                return_unsigned=True,
            )
        unsigned_rwa.timestamp = rwa_time
        rwa_transaction = Transaction.from_dict(_sign(unsigned_rwa.to_dict()))
        if not chain.add_transaction_to_mempool(rwa_transaction):
            raise RuntimeError("PoS fixture RWA creation was rejected")
        rwa_block = _mine_variable_at(
            chain,
            candidate_time + 6 * BLOCK_TIME_INITIAL_18_MONTHS,
            OWNER_ADDRESS,
        )

        messaging_sig_pub = OWNER_PUBLIC_KEY.hex()
        messaging_kem_v1 = hashlib.shake_256(
            b"WEPO_STATE_ORACLE_MESSAGING_KEM_V1"
        ).digest(1184).hex()
        messaging_kem_v2 = hashlib.shake_256(
            b"WEPO_STATE_ORACLE_MESSAGING_KEM_V2"
        ).digest(1184).hex()
        key_v1_time = rwa_block.header.timestamp + 1
        with patch("blockchain.time.time", return_value=key_v1_time):
            unsigned_key_v1 = chain.create_key_registration(
                OWNER_ADDRESS,
                messaging_kem_v1,
                messaging_sig_pub,
                fee=MSG_KEY_REGISTER_MIN_FEE,
                return_unsigned=True,
            )
        unsigned_key_v1.timestamp = key_v1_time
        key_v1_transaction = Transaction.from_dict(
            _sign(unsigned_key_v1.to_dict())
        )
        if not chain.add_transaction_to_mempool(key_v1_transaction):
            raise RuntimeError("PoS fixture messaging-key v1 was rejected")
        key_v1_block = _mine_variable_at(
            chain,
            candidate_time + 7 * BLOCK_TIME_INITIAL_18_MONTHS,
            OWNER_ADDRESS,
        )

        key_v2_time = key_v1_block.header.timestamp + 1
        with patch("blockchain.time.time", return_value=key_v2_time):
            unsigned_key_v2 = chain.create_key_registration(
                OWNER_ADDRESS,
                messaging_kem_v2,
                messaging_sig_pub,
                fee=MSG_KEY_REGISTER_MIN_FEE,
                return_unsigned=True,
            )
        unsigned_key_v2.timestamp = key_v2_time
        key_v2_transaction = Transaction.from_dict(
            _sign(unsigned_key_v2.to_dict())
        )
        if not chain.add_transaction_to_mempool(key_v2_transaction):
            raise RuntimeError("PoS fixture messaging-key v2 was rejected")
        key_v2_block = _mine_variable_at(
            chain,
            candidate_time + 8 * BLOCK_TIME_INITIAL_18_MONTHS,
            OWNER_ADDRESS,
        )

        rwa_rows = _rwa_rows(chain)
        messaging_key_rows = _messaging_key_rows(chain)
        if (
            len(rwa_rows) != 1
            or rwa_rows[0]["asset_id"] != "rwa_state_oracle_001"
            or rwa_rows[0]["asset_hash"] != asset_hash
            or rwa_rows[0]["metadata"]
            != {"document_version": 1, "jurisdiction": "US-NY"}
            or len(messaging_key_rows) != 1
            or messaging_key_rows[0]["kem_pub"] != messaging_kem_v2
            or messaging_key_rows[0]["sig_pub"] != messaging_sig_pub
            or messaging_key_rows[0]["register_txid"]
            != key_v2_transaction.calculate_txid()
        ):
            raise RuntimeError(
                "PoS fixture metadata indexes are unexpected: "
                f"rwa={rwa_rows!r} messaging={messaging_key_rows!r}"
            )

        metadata_transactions = (
            (rwa_block, rwa_transaction),
            (key_v1_block, key_v1_transaction),
            (key_v2_block, key_v2_transaction),
        )
        metadata_fee_blocks = []
        for metadata_block, metadata_transaction in metadata_transactions:
            scheduled_base = chain.calculate_block_reward(
                metadata_block.height
            )
            coinbase_total = sum(
                output.value
                for output in metadata_block.transactions[0].outputs
            )
            redistributed_fee = coinbase_total - scheduled_base
            if redistributed_fee != metadata_transaction.fee:
                raise RuntimeError(
                    "Metadata fee was not fully redistributed at height "
                    f"{metadata_block.height}: fee={metadata_transaction.fee} "
                    f"redistributed={redistributed_fee}"
                )
            metadata_fee_blocks.append(
                {
                    "height": metadata_block.height,
                    "transaction_type": metadata_transaction.tx_type,
                    "transaction_id": metadata_transaction.calculate_txid(),
                    "fee": metadata_transaction.fee,
                    "scheduled_pow_base": scheduled_base,
                    "coinbase_output_total": coinbase_total,
                    "redistributed_fee": redistributed_fee,
                }
            )

        final_stakes = _stake_rows(chain)
        final_masternodes = _masternode_rows(chain)
        reward_rows = _reward_rows(chain)
        joint_staker_reward = pos_reward_per_block * 60 // 100
        joint_masternode_reward = pos_reward_per_block - joint_staker_reward
        expected_stake_rewards = (
            3 * pos_reward_per_block + joint_staker_reward
        )
        expected_total_rewards = (
            expected_stake_rewards + joint_masternode_reward
        )
        if (
            len(final_stakes) != 1
            or final_stakes[0]["status"] != "inactive"
            or final_stakes[0]["unlock_height"] != deactivation_block.height
            or final_stakes[0]["last_reward_height"]
            != joint_reward_block.height
            or final_stakes[0]["total_rewards"]
            != expected_stake_rewards
            or len(final_masternodes) != 1
            or final_masternodes[0]["status"] != "inactive"
            or final_masternodes[0]["last_ping"]
            != joint_reward_block.header.timestamp
            or final_masternodes[0]["total_rewards"]
            != joint_masternode_reward
            or len(reward_rows) != 5
            or sum(row["amount"] for row in reward_rows)
            != expected_total_rewards
        ):
            raise RuntimeError(
                "PoS fixture protocol lifecycle/reward state is unexpected: "
                f"stakes={final_stakes!r} "
                f"masternodes={final_masternodes!r} "
                f"rewards={reward_rows!r} "
                f"expected_per_block={pos_reward_per_block}"
            )

        final_rows = _state_rows(chain)
        final_payload_hex, final_commitment = _state_commitment(final_rows)
        final_supply = chain.get_issued_supply()
        final_unspent_total = sum(row["amount"] for row in final_rows)
        if final_supply != final_unspent_total:
            raise RuntimeError("PoS lifecycle supply differs from UTXO total")
        return {
            "parameters": {
                "network_name": chain.network_profile.name,
                "activation_height": POS_ACTIVATION_HEIGHT,
                "first_active_height": POS_ACTIVATION_HEIGHT + 1,
                "block_time_pos": BLOCK_TIME_POS,
                "minimum_stake_amount": MIN_STAKE_AMOUNT,
                "minimum_masternode_collateral": required_masternode_collateral,
                "rwa_creation_min_fee": RWA_CREATION_MIN_FEE,
                "messaging_key_register_min_fee": MSG_KEY_REGISTER_MIN_FEE,
                "ml_kem768_public_key_hex_length": 1184 * 2,
                "ml_dsa44_public_key_hex_length": 1312 * 2,
                "metadata_fee_policy": "fully_redistributed_via_coinbase",
                "phase_2a_end_height": chain.network_profile.phase_2a_end_height,
                "phase_2a_pow_reward": chain.calculate_block_reward(POS_ACTIVATION_HEIGHT + 1),
                "initial_pos_base_reward": 25 * COIN,
                "pos_pool_divisor": 2,
                "staker_pool_percent": 60,
                "masternode_pool_percent": 40,
                "empty_side_rolls_over": True,
                "selection_domain": "WEPO_POS_VALIDATOR_SELECTION_V1\\0",
                "signature_domain": "WEPO_POS_BLOCK_SIGNATURE_V1\\0",
                "score_order": "pow_work_then_pos_count",
            },
            "parent": parent,
            "active_stakes": active_stakes,
            "active_masternodes_after_registration": registered_masternodes,
            "candidate": json.loads(chain.serialize_block(candidate)),
            "continuation_blocks": [
                json.loads(chain.serialize_block(funding_block)),
                json.loads(chain.serialize_block(registration_block)),
                json.loads(chain.serialize_block(joint_reward_block)),
                json.loads(chain.serialize_block(deactivation_block)),
                json.loads(chain.serialize_block(post_deactivation_block)),
                json.loads(chain.serialize_block(rwa_block)),
                json.loads(chain.serialize_block(key_v1_block)),
                json.loads(chain.serialize_block(key_v2_block)),
            ],
            "expected_final": {
                "height": chain.get_block_height(),
                "tip": chain.get_latest_block().get_block_hash(),
                "pow_hashes": [
                    chain.miner.calculate_pow_hash(block.header)
                    for block in chain.chain
                ],
                "issued_supply": final_supply,
                "utxo_total": final_unspent_total,
                "utxos": final_rows,
                "state_payload_utf8_hex": final_payload_hex,
                "state_commitment": final_commitment,
                "stakes": final_stakes,
                "masternodes": final_masternodes,
                "rewards": reward_rows,
                "rwa_assets": rwa_rows,
                "messaging_keys": messaging_key_rows,
                "metadata_fee_blocks": metadata_fee_blocks,
                "metadata_fee_total": sum(
                    row["fee"] for row in metadata_fee_blocks
                ),
                "metadata_fee_redistributed_total": sum(
                    row["redistributed_fee"]
                    for row in metadata_fee_blocks
                ),
                "supply_minus_utxo_total": (
                    final_supply - final_unspent_total
                ),
                "rwa_create_txid": rwa_transaction.calculate_txid(),
                "messaging_registration_txids": [
                    key_v1_transaction.calculate_txid(),
                    key_v2_transaction.calculate_txid(),
                ],
                "stake_deactivation_txid": (
                    stake_deactivation_transaction.calculate_txid()
                ),
                "masternode_deactivation_txid": (
                    masternode_deactivation_transaction.calculate_txid()
                ),
                "masternode_registration_txid": (
                    registration_transaction.calculate_txid()
                ),
                "masternode_id": masternode_id,
                "stake_rewards": sum(
                    row["amount"]
                    for row in reward_rows
                    if row["recipient_type"] == "staker"
                ),
                "masternode_rewards": sum(
                    row["amount"]
                    for row in reward_rows
                    if row["recipient_type"] == "masternode"
                ),
                "total_pos_rewards": expected_total_rewards,
            },
            "expected": {
                "selected_validator": selected,
                "slot_anchor": slot_anchor,
                "candidate_height": candidate.height,
                "candidate_timestamp": candidate.header.timestamp,
                "signing_message_hex": signing_message.hex(),
                "validator_public_key": OWNER_PUBLIC_KEY.hex(),
                "validator_signature": signature.hex(),
                "candidate_hash": candidate.get_block_hash(),
            },
        }
    finally:
        chain.conn.close()


def generate() -> dict:
    recipient_address = WALLET_VECTOR["expected"]["recipient_address"]
    with tempfile.TemporaryDirectory(prefix="wepo-state-oracle-") as data_dir:
        with open(os.devnull, "w", encoding="utf-8") as devnull:
            with contextlib.redirect_stdout(devnull):
                chain = WepoBlockchain(
                    data_dir=data_dir,
                    network_profile="test",
                    fixed_difficulty=1,
                )
                try:
                    genesis_time = chain.chain[0].header.timestamp
                    _mine_at(chain, genesis_time + 120, OWNER_ADDRESS)

                    genesis_utxo = chain.conn.execute(
                        "SELECT txid, vout, amount FROM utxos "
                        "WHERE created_height = 0 AND spent = FALSE"
                    ).fetchone()
                    if genesis_utxo is None:
                        raise RuntimeError("Fixture genesis UTXO is missing")

                    first_signed = _sign(
                        _unsigned_spend(
                            prev_txid=genesis_utxo[0],
                            prev_vout=int(genesis_utxo[1]),
                            amount=int(genesis_utxo[2]),
                            recipient_address=recipient_address,
                            recipient_value=25 * COIN,
                            timestamp=genesis_time + 180,
                            label="genesis-spend",
                        )
                    )
                    first_tx = Transaction.from_dict(first_signed)
                    if not chain.add_transaction_to_mempool(first_tx):
                        raise RuntimeError("First fixture transaction was rejected")
                    _mine_at(chain, genesis_time + 240, OWNER_ADDRESS)

                    first_change = first_tx.outputs[1].value
                    second_signed = _sign(
                        _unsigned_spend(
                            prev_txid=first_tx.calculate_txid(),
                            prev_vout=1,
                            amount=first_change,
                            recipient_address=recipient_address,
                            recipient_value=7 * COIN,
                            timestamp=genesis_time + 300,
                            label="change-spend",
                        )
                    )
                    second_tx = Transaction.from_dict(second_signed)
                    if not chain.add_transaction_to_mempool(second_tx):
                        raise RuntimeError("Second fixture transaction was rejected")
                    _mine_at(chain, genesis_time + 360, OWNER_ADDRESS)

                    state_rows = _state_rows(chain)
                    state_payload_hex, state_commitment = _state_commitment(
                        state_rows
                    )
                    issued_supply = chain.get_issued_supply()
                    unspent_total = sum(row["amount"] for row in state_rows)
                    if issued_supply != unspent_total:
                        raise RuntimeError(
                            "Fixture requires non-burning transfer fees so supply "
                            "equals the independently replayable UTXO total"
                        )

                    fixture = {
                        "schema": FIXTURE_SCHEMA,
                        "test_only": True,
                        "network_profile": "test",
                        "coverage": {
                            "covered": [
                                "block linkage and canonical header IDs",
                                "Argon2id proof of work and leading-zero targets",
                                "exact PoW difficulty retarget and phase boundaries",
                                "live difficulty retarget",
                                "cumulative-work fork selection and replay",
                                "RWA and messaging-key disconnect/reconnect "
                                "under cumulative-work reorganization",
                                "shielded commitments, anchors, nullifiers, "
                                "and transparent-pool supply reconciliation",
                                "shielded disconnect/reconnect and "
                                "proof-statement digest binding",
                                "PoS slot and stake-weighted validator selection",
                                "ML-DSA-authorized PoS header candidate",
                                "canonical signed stake deactivation",
                                "stake reward eligibility and exact accrual",
                                "canonical signed masternode registration and deactivation",
                                "masternode collateral preservation and lifecycle indexes",
                                "joint staker/masternode reward allocation and accrual",
                                "RWA asset uniqueness, ownership, and derived indexes",
                                "messaging-key shape, ownership, and latest-wins indexes",
                                "metadata fee redistribution and supply conservation",
                                "synthetic reward UTXOs and issued supply",
                                "transaction IDs and Merkle roots",
                                "ML-DSA owner-bound spend authorization",
                                "transparent UTXO creation and consumption",
                                "coinbase maturity",
                                "exact fees and value conservation",
                                "issued supply and canonical state commitment",
                            ],
                            "not_covered": [
                                "external cryptographic audit of the real "
                                "shielded prover and verifier",
                            ],
                        },
                        "coinbase_maturity": chain.coinbase_maturity,
                        "difficulty": _difficulty_vectors(),
                        "pow": {
                            "algorithm": "argon2id-v19",
                            "time_cost": chain.miner.time_cost,
                            "memory_cost_kib": chain.miner.memory_cost,
                            "parallelism": chain.miner.parallelism,
                            "hash_length": chain.miner.hash_len,
                            "salt_length": chain.miner.salt_len,
                            "salt_domain": "WEPO_POW_SALT",
                            "timestamp_bits": 64,
                        },
                        "fork_choice": _fork_choice_fixture(data_dir),
                        "shielded_scenario": _shielded_scenario_fixture(data_dir),
                        "pos_scenario": _pos_scenario_fixture(data_dir),
                        "state_domain": "WEPO_STATE_ORACLE_V1\\0",
                        "blocks": [
                            json.loads(chain.serialize_block(block))
                            for block in chain.chain
                        ],
                        "expected": {
                            "height": chain.get_block_height(),
                            "tip": chain.get_latest_block().get_block_hash(),
                            "pow_hashes": [
                                chain.miner.calculate_pow_hash(block.header)
                                for block in chain.chain
                            ],
                            "issued_supply": issued_supply,
                            "utxo_total": unspent_total,
                            "utxos": state_rows,
                            "state_payload_utf8_hex": state_payload_hex,
                            "state_commitment": state_commitment,
                        },
                    }
                    return fixture
                finally:
                    chain.conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fixture = generate()
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(fixture, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
    print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
