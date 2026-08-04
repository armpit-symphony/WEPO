"""Cold-key stake lifecycle, policy, replay, and authorization regressions."""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
SIGNER = ROOT / "wepo-blockchain" / "signer"
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(SIGNER))
os.environ.setdefault("WEPO_NETWORK_PROFILE", "test")

from blockchain import Transaction, TransactionInput, TransactionOutput  # noqa: E402
from dilithium import verify_dilithium_signature  # noqa: E402
from stake_transaction_policy import (  # noqa: E402
    AUTHORIZATION_FORMAT,
    MAX_STAKE_FEE_ATOMIC,
    StakePolicyRefusal,
    validate_stake_authorization,
)
from validator_signer import SubprocessValidatorSigner  # noqa: E402
from wepo_validator_signer import (  # noqa: E402
    ProductionValidatorSigner,
    SignerRefusal,
    initialize_validator_key,
    load_validator_key,
)


COIN = 100_000_000


def _key(tmp_path: Path):
    path = tmp_path / "private" / "validator-key.json"
    initialize_validator_key(path, "test")
    return path, load_validator_key(path, "test", allow_insecure_permissions=True)


def _create_authorization(key, *, txid: str = "11" * 32, fee: int = 10_000):
    principal = 100 * COIN
    input_amount = 125 * COIN
    stake_id = f"stake_{key.validator_address}_1800000000"
    tx = Transaction(
        version=1,
        inputs=[TransactionInput(txid, 0, b"signature_placeholder", 0xFFFFFFFF)],
        outputs=[
            TransactionOutput(
                principal,
                f"stake_lock:{stake_id}".encode("ascii"),
                key.validator_address,
            ),
            TransactionOutput(
                input_amount - principal - fee,
                b"change_script",
                key.validator_address,
            ),
        ],
        lock_time=0,
        fee=fee,
        tx_type="stake_create",
        extra_data={
            "stake_id": stake_id,
            "staker_address": key.validator_address,
            "amount": principal,
        },
        timestamp=1_800_000_000,
    )
    return {
        "format": AUTHORIZATION_FORMAT,
        "network": "test",
        "validator_address": key.validator_address,
        "unsigned_tx": tx.to_dict(),
        "input_utxos": [{
            "prev_txid": txid,
            "prev_vout": 0,
            "amount": input_amount,
            "address": key.validator_address,
            "script_pubkey": b"coinbase_output".hex(),
        }],
        "sighash": tx.get_canonical_sighash("test").hex(),
    }


def _sign_request(authorization: dict) -> dict:
    return {
        "version": 3,
        "operation": "sign_stake_transaction",
        "validator_address": authorization["validator_address"],
        "network": authorization["network"],
        "sighash": authorization["sighash"],
        "unsigned_tx": authorization["unsigned_tx"],
        "input_utxos": authorization["input_utxos"],
    }


def test_transaction_sighash_is_network_bound(tmp_path):
    _path, key = _key(tmp_path)
    authorization = _create_authorization(key)
    tx = Transaction.from_dict(authorization["unsigned_tx"])
    assert tx.get_canonical_sighash("test") != tx.get_canonical_sighash("mainnet")
    assert tx.sign_all_inputs(key.private_key, key.public_key, "test")
    assert tx.verify_quantum_signature(0, key.validator_address, "test")
    assert not tx.verify_quantum_signature(0, key.validator_address, "mainnet")


def test_stake_signer_requires_exact_operator_authorization_and_is_idempotent(tmp_path):
    _path, key = _key(tmp_path)
    state = tmp_path / "state" / "signer.sqlite3"
    signer = ProductionValidatorSigner(key, state, allow_insecure_permissions=True)
    document = _create_authorization(key)
    parsed = validate_stake_authorization(
        document,
        expected_network="test",
        validator_address=key.validator_address,
    )

    with pytest.raises(SignerRefusal, match="no exact operator authorization"):
        signer.handle(_sign_request(document))

    approved, status = signer.approve_stake(document)
    assert approved.sighash.hex() == document["sighash"]
    assert status == "approved"
    response = signer.handle(_sign_request(document))
    signature = bytes.fromhex(response["signature"])
    assert verify_dilithium_signature(parsed.sighash, signature, key.public_key)
    assert signer.handle(_sign_request(document))["signature"] == response["signature"]

    with sqlite3.connect(state) as connection:
        assert connection.execute(
            "SELECT operation, status FROM stake_authorizations"
        ).fetchall() == [("stake_create", "signed")]
        assert connection.execute(
            "SELECT prev_txid, prev_vout FROM stake_authorized_outpoints"
        ).fetchall() == [("11" * 32, 0)]


def test_stake_policy_refuses_value_escape_fee_abuse_network_replay_and_conflicts(tmp_path):
    _path, key = _key(tmp_path)
    signer = ProductionValidatorSigner(
        key,
        tmp_path / "state" / "signer.sqlite3",
        allow_insecure_permissions=True,
    )
    approved = _create_authorization(key)
    signer.approve_stake(approved)

    redirected = copy.deepcopy(approved)
    redirected["unsigned_tx"]["outputs"][1]["address"] = "wepo1q" + "0" * 39
    with pytest.raises(SignerRefusal, match="outside the validator"):
        signer.approve_stake(redirected)

    expensive = _create_authorization(key, txid="22" * 32, fee=MAX_STAKE_FEE_ATOMIC + 1)
    with pytest.raises(SignerRefusal, match="fee exceeds"):
        signer.approve_stake(expensive)

    wrong_network = copy.deepcopy(approved)
    wrong_network["network"] = "mainnet"
    with pytest.raises(SignerRefusal, match="wrong key or network"):
        signer.approve_stake(wrong_network)

    conflict = _create_authorization(key)
    conflict["unsigned_tx"]["timestamp"] += 1
    tx = Transaction.from_dict(conflict["unsigned_tx"])
    conflict["sighash"] = tx.get_canonical_sighash("test").hex()
    with pytest.raises(SignerRefusal, match="already authorized outpoint"):
        signer.approve_stake(conflict)


def test_stake_withdrawal_returns_principal_only_to_validator(tmp_path):
    _path, key = _key(tmp_path)
    principal = 100 * COIN
    stake_id = f"stake_{key.validator_address}_1800000000"
    tx = Transaction(
        version=1,
        inputs=[TransactionInput("33" * 32, 2, b"signature_placeholder", 0xFFFFFFFF)],
        outputs=[TransactionOutput(principal - 10_000, b"stake_unlock", key.validator_address)],
        lock_time=0,
        fee=10_000,
        tx_type="stake_deactivate",
        extra_data={
            "stake_id": stake_id,
            "staker_address": key.validator_address,
            "amount": principal,
        },
        timestamp=1_800_000_100,
    )
    document = {
        "format": AUTHORIZATION_FORMAT,
        "network": "test",
        "validator_address": key.validator_address,
        "unsigned_tx": tx.to_dict(),
        "input_utxos": [{
            "prev_txid": "33" * 32,
            "prev_vout": 2,
            "amount": principal,
            "address": key.validator_address,
            "script_pubkey": f"stake_lock:{stake_id}".encode().hex(),
        }],
        "sighash": tx.get_canonical_sighash("test").hex(),
    }
    signer = ProductionValidatorSigner(
        key,
        tmp_path / "state" / "signer.sqlite3",
        allow_insecure_permissions=True,
    )
    signer.approve_stake(document)
    signature = bytes.fromhex(signer.handle(_sign_request(document))["signature"])
    assert verify_dilithium_signature(bytes.fromhex(document["sighash"]), signature, key.public_key)

    malicious = copy.deepcopy(document)
    malicious["unsigned_tx"]["outputs"][0]["value"] -= 1
    with pytest.raises((SignerRefusal, StakePolicyRefusal)):
        signer.approve_stake(malicious)


def test_subprocess_boundary_carries_no_private_key_and_uses_protocol_v3(tmp_path):
    _path, key = _key(tmp_path)
    document = _create_authorization(key)
    signer = SubprocessValidatorSigner(["validator-signer"], environment={})
    signature = b"x" * 2420
    result = type("Result", (), {
        "returncode": 0,
        "stdout": json.dumps({"version": 3, "ok": True, "signature": signature.hex()}).encode(),
        "stderr": b"",
        "output_exceeded_limit": False,
    })()
    from unittest.mock import patch
    with patch.object(SubprocessValidatorSigner, "_run_bounded", return_value=result) as run:
        assert signer.sign_stake_transaction(
            key.validator_address,
            document["unsigned_tx"],
            document["input_utxos"],
            "test",
            document["sighash"],
        ) == signature
    request = json.loads(run.call_args.args[0])
    assert request["version"] == 3
    assert request["operation"] == "sign_stake_transaction"
    assert "private_key" not in json.dumps(request)
