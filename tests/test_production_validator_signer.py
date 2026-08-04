"""Production validator signer contract and anti-equivocation regressions."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import struct
import sys
from unittest.mock import patch
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
SIGNER_DIR = ROOT / "wepo-blockchain" / "signer"
SIGNER_SCRIPT = SIGNER_DIR / "wepo_validator_signer.py"
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(SIGNER_DIR))

os.environ.setdefault("WEPO_NETWORK_PROFILE", "test")

from address_utils import generate_wepo_address  # noqa: E402
import blockchain as consensus  # noqa: E402
from blockchain import BlockHeader, StakeInfo, WepoBlockchain  # noqa: E402
from dilithium import verify_dilithium_signature  # noqa: E402
from validator_signer import (  # noqa: E402
    PosSigningContext,
    SubprocessValidatorSigner,
    ValidatorSignerError,
)
from wepo_validator_signer import (  # noqa: E402
    POS_DOMAIN,
    ProductionValidatorSigner,
    SignerRefusal,
    initialize_validator_key,
    load_validator_key,
)


def signing_payload(key, *, height=17, previous_hash="ab" * 32, merkle_root="cd" * 32):
    header = BlockHeader(
        version=1,
        prev_hash=previous_hash,
        merkle_root=merkle_root,
        timestamp=1_800_000_000,
        bits=0,
        nonce=0,
        consensus_type="pos",
        validator_address=key.validator_address,
        validator_public_key=key.public_key,
        validator_signature=None,
    )
    network = key.network.encode("ascii")
    return (
        POS_DOMAIN
        + struct.pack("<I", len(network))
        + network
        + struct.pack("<Q", height)
        + header.canonical_bytes(include_validator_signature=False)
    )


def sign_request(key, payload, *, height=17, previous_hash="ab" * 32):
    return {
        "version": 3,
        "operation": "sign",
        "validator_address": key.validator_address,
        "network": key.network,
        "block_height": height,
        "previous_block_hash": previous_hash,
        "message": hashlib.sha3_256(payload).hexdigest(),
        "signing_payload": payload.hex(),
    }


def create_key(tmp_path):
    key_path = tmp_path / "private" / "validator-key.json"
    public = initialize_validator_key(key_path, "test")
    assert "private_key" not in public
    assert public["validator_address"] == generate_wepo_address(
        bytes.fromhex(public["public_key"]),
        address_type="quantum",
    )
    key = load_validator_key(
        key_path,
        "test",
        allow_insecure_permissions=True,
    )
    return key_path, key


def test_signer_validates_payload_and_refuses_equivocation(tmp_path):
    key_path, key = create_key(tmp_path)
    with pytest.raises(SignerRefusal, match="overwrite"):
        initialize_validator_key(key_path, "test")

    state_path = tmp_path / "state" / "anti-equivocation.sqlite3"
    signer = ProductionValidatorSigner(
        key,
        state_path,
        allow_insecure_permissions=True,
    )
    public_response = signer.handle(
        {
            "version": 3,
            "operation": "public_key",
            "validator_address": key.validator_address,
        }
    )
    assert bytes.fromhex(public_response["public_key"]) == key.public_key

    payload = signing_payload(key)
    request = sign_request(key, payload)
    response = signer.handle(request)
    signature = bytes.fromhex(response["signature"])
    message = hashlib.sha3_256(payload).digest()
    assert verify_dilithium_signature(message, signature, key.public_key)
    assert signer.handle(request)["signature"] == response["signature"]

    conflicting_payload = signing_payload(key, merkle_root="ef" * 32)
    with pytest.raises(SignerRefusal, match="height already signed"):
        signer.handle(sign_request(key, conflicting_payload))

    arbitrary = b"not a canonical WEPO PoS signing payload"
    with pytest.raises(SignerRefusal, match="domain"):
        signer.handle(sign_request(key, arbitrary, height=18))

    wrong_network = dict(sign_request(key, signing_payload(key, height=18), height=18))
    wrong_network["network"] = "mainnet"
    with pytest.raises(SignerRefusal, match="network"):
        signer.handle(wrong_network)
    signer.store.connection.close()

    with sqlite3.connect(state_path) as connection:
        rows = connection.execute(
            "SELECT network, validator_address, height, previous_block_hash FROM signed_blocks"
        ).fetchall()
    assert rows == [("test", key.validator_address, 17, "ab" * 32)]


def test_node_boundary_invokes_real_signer_without_private_key(tmp_path):
    key_path, key = create_key(tmp_path)
    state_path = tmp_path / "state" / "anti-equivocation.sqlite3"
    command = [
        sys.executable,
        str(SIGNER_SCRIPT),
        "--network",
        "test",
        "--key-file",
        str(key_path),
        "--state-db",
        str(state_path),
        "--stdio",
        "--allow-insecure-permissions-for-test",
    ]
    boundary = SubprocessValidatorSigner(command, timeout_seconds=15)
    assert boundary.get_public_key(key.validator_address) == key.public_key

    payload = signing_payload(key)
    message = hashlib.sha3_256(payload).digest()
    context = PosSigningContext(
        network="test",
        block_height=17,
        previous_block_hash="ab" * 32,
        signing_payload=payload,
    )
    signature = boundary.sign(key.validator_address, message, context=context)
    assert verify_dilithium_signature(message, signature, key.public_key)
    assert boundary.sign(key.validator_address, message, context=context) == signature

    with pytest.raises(ValidatorSignerError, match="does not match"):
        boundary.sign(key.validator_address, b"x" * 32, context=context)


def test_real_signer_produces_a_fully_valid_pos_block(tmp_path, monkeypatch):
    key_path, key = create_key(tmp_path)
    state_path = tmp_path / "state" / "anti-equivocation.sqlite3"
    boundary = SubprocessValidatorSigner(
        [
            sys.executable,
            str(SIGNER_SCRIPT),
            "--network",
            "test",
            "--key-file",
            str(key_path),
            "--state-db",
            str(state_path),
            "--stdio",
            "--allow-insecure-permissions-for-test",
        ],
        timeout_seconds=15,
    )
    chain_path = tmp_path / "chain"
    chain = WepoBlockchain(data_dir=str(chain_path), network_profile="test")
    monkeypatch.setattr(consensus, "POS_ACTIVATION_HEIGHT", 0)
    monkeypatch.setattr(consensus, "MIN_STAKE_AMOUNT", 1)
    chain.get_active_stakes = lambda: [
        StakeInfo(
            stake_id="production-signer-stake",
            staker_address=key.validator_address,
            amount=100,
            start_height=0,
            start_time=0,
        )
    ]
    slot_time = chain.get_latest_block().header.timestamp + consensus.BLOCK_TIME_POS
    with patch("blockchain.time.time", return_value=slot_time):
        block = chain._produce_pos_block(key.validator_address, boundary)
    assert block is not None
    assert chain.validate_block(block)
    assert block.header.validator_public_key == key.public_key
    assert verify_dilithium_signature(
        chain.get_pos_signing_message(block),
        block.header.validator_signature,
        key.public_key,
    )
    with sqlite3.connect(state_path) as connection:
        signed = connection.execute(
            "SELECT height, previous_block_hash FROM signed_blocks"
        ).fetchall()
    assert signed == [(block.height, block.header.prev_hash)]

def test_production_mode_rejects_unverifiable_windows_permissions(tmp_path):
    if os.name == "posix":
        pytest.skip("Windows-specific fail-closed permission boundary")
    key_path, _key = create_key(tmp_path)
    with pytest.raises(SignerRefusal, match="POSIX"):
        load_validator_key(key_path, "test")
