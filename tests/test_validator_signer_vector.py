"""Cross-runtime public vector for the production validator signer protocol."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
SIGNER_DIR = ROOT / "wepo-blockchain" / "signer"
VECTOR_PATH = ROOT / "tests" / "vectors" / "validator_signer_protocol_v3.json"
SOURCE_PATH = ROOT / "tests" / "vectors" / "state_transition_oracle_v1.json"
GENERATOR_PATH = ROOT / "tests" / "generate_validator_signer_vector.mjs"
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(SIGNER_DIR))

from address_utils import generate_wepo_address  # noqa: E402
from dilithium import verify_dilithium_signature  # noqa: E402
from wepo_validator_signer import parse_signing_payload  # noqa: E402


def test_validator_signer_protocol_vector_is_reproducible_and_valid():
    vector_text = VECTOR_PATH.read_text(encoding="utf-8")
    regenerated_text = subprocess.check_output(
        ["node", str(GENERATOR_PATH)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    )
    assert regenerated_text == vector_text
    vector = json.loads(vector_text)
    assert vector["schema"] == "wepo-validator-signer-protocol-v3"
    assert vector["test_only"] is True
    assert hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest() == vector[
        "source_fixture_sha256"
    ]

    request = vector["request"]
    assert set(request) == {
        "version",
        "operation",
        "validator_address",
        "network",
        "block_height",
        "previous_block_hash",
        "message",
        "signing_payload",
    }
    assert request["version"] == 3
    assert request["operation"] == "sign"
    payload = bytes.fromhex(request["signing_payload"])
    message = hashlib.sha3_256(payload).digest()
    assert message.hex() == request["message"]
    assert hashlib.sha256(payload).hexdigest() == vector["expected"][
        "signing_payload_sha256"
    ]

    parsed = parse_signing_payload(payload)
    assert parsed.network == request["network"]
    assert parsed.height == request["block_height"]
    assert parsed.previous_block_hash == request["previous_block_hash"]
    assert parsed.validator_address == request["validator_address"]
    assert parsed.validator_public_key.hex() == vector["expected"][
        "validator_public_key"
    ]
    assert generate_wepo_address(
        parsed.validator_public_key,
        address_type="quantum",
    ) == request["validator_address"]

    response = vector["response"]
    assert set(response) == {"version", "ok", "signature"}
    assert response["version"] == 3 and response["ok"] is True
    assert verify_dilithium_signature(
        message,
        bytes.fromhex(response["signature"]),
        parsed.validator_public_key,
    )
