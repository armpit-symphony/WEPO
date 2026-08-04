#!/usr/bin/env python3
"""External validator-signer boundary regressions.

Run: python tests/test_validator_signer_boundary.py
"""

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import Mock, patch

os.environ["WEPO_NETWORK_PROFILE"] = "test"

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

import blockchain as consensus  # noqa: E402
from address_utils import generate_wepo_address  # noqa: E402
from blockchain import StakeInfo, WepoBlockchain  # noqa: E402
from dilithium import (  # noqa: E402
    DILITHIUM_PUBKEY_SIZE,
    DILITHIUM_SIGNATURE_SIZE,
    generate_dilithium_keypair,
    sign_with_dilithium,
)
from validator_signer import (  # noqa: E402
    MAX_RESPONSE_BYTES,
    SIGNER_COMMAND_ENV,
    PosSigningContext,
    SubprocessValidatorSigner,
    ValidatorSignerError,
    _BoundedProcessResult,
    load_validator_signer_from_env,
)

FAILURES = []


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


def expect_signer_error(name, callback):
    try:
        callback()
    except ValidatorSignerError:
        check(name, True)
    else:
        check(name, False)


def completed(stdout, returncode=0, stderr="", exceeded=False):
    if isinstance(stdout, str):
        stdout = stdout.encode("utf-8")
    if isinstance(stderr, str):
        stderr = stderr.encode("utf-8")
    return _BoundedProcessResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        output_exceeded_limit=exceeded,
    )


class InMemorySigner:
    """Test-only signer proving consensus consumes capability, not private key."""

    def __init__(self, keypair):
        self.keypair = keypair
        self.messages = []

    def get_public_key(self, validator_address):
        return self.keypair.public_key

    def sign(self, validator_address, message, *, context):
        self.messages.append((validator_address, message, context))
        return sign_with_dilithium(message, self.keypair.private_key)


def test_consensus_boundary():
    old_activation = consensus.POS_ACTIVATION_HEIGHT
    old_min_stake = consensus.MIN_STAKE_AMOUNT
    temp_dir = tempfile.mkdtemp(prefix="wepo-validator-signer-")
    try:
        chain = WepoBlockchain(data_dir=temp_dir, network_profile="test")
        consensus.POS_ACTIVATION_HEIGHT = 0
        consensus.MIN_STAKE_AMOUNT = 1
        keypair = generate_dilithium_keypair()
        address = generate_wepo_address(keypair.public_key, address_type="quantum")
        stake = StakeInfo(
            stake_id="signer-boundary-stake",
            staker_address=address,
            amount=100,
            start_height=0,
            start_time=0,
        )
        chain.get_active_stakes = lambda: [stake]
        signer = InMemorySigner(keypair)

        slot_time = chain.get_latest_block().header.timestamp + consensus.BLOCK_TIME_POS
        with patch("blockchain.time.time", return_value=slot_time):
            block = chain._produce_pos_block(address, signer)
        check("external signer produces a valid PoS block", block is not None)
        check("externally signed block passes full validation", chain.validate_block(block))
        check(
            "signer receives the canonical digest and independently checkable context",
            len(signer.messages) == 1
            and signer.messages[0][0] == address
            and signer.messages[0][1] == chain.get_pos_signing_message(block)
            and signer.messages[0][2].signing_payload
            == chain.get_pos_signing_payload(block)
        )

        class FailingSigner:
            def get_public_key(self, validator_address):
                raise RuntimeError("secret backend detail")

            def sign(self, validator_address, message, *, context):
                raise AssertionError("unreachable")

        check(
            "signer failure produces no PoS block",
            chain._produce_pos_block(address, FailingSigner()) is None,
        )
    finally:
        consensus.POS_ACTIVATION_HEIGHT = old_activation
        consensus.MIN_STAKE_AMOUNT = old_min_stake
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_subprocess_protocol():
    address = "wepo1q" + ("0" * 39)
    signing_payload = b"WEPO signer boundary payload"
    message = hashlib.sha3_256(signing_payload).digest()
    context = PosSigningContext(
        network="test",
        block_height=17,
        previous_block_hash="ab" * 32,
        signing_payload=signing_payload,
    )
    signer = SubprocessValidatorSigner(["validator-signer"], environment={})

    public_key = bytes([7]) * DILITHIUM_PUBKEY_SIZE
    public_response = json.dumps(
        {"version": 3, "ok": True, "public_key": public_key.hex()}
    )
    with patch.object(SubprocessValidatorSigner, "_run_bounded", return_value=completed(public_response)) as run:
        check("valid public-key response is accepted", signer.get_public_key(address) == public_key)
        request_bytes = run.call_args.args[0]
        request = json.loads(request_bytes)
        check(
            "public-key request is bounded, versioned, and address-scoped",
            len(request_bytes) <= 4096
            and request == {
                "operation": "public_key",
                "validator_address": address,
                "version": 3,
            },
        )

    signature = bytes([9]) * DILITHIUM_SIGNATURE_SIZE
    signature_response = json.dumps(
        {"version": 3, "ok": True, "signature": signature.hex()}
    )
    with patch.object(SubprocessValidatorSigner, "_run_bounded", return_value=completed(signature_response)) as run:
        check("valid signature response is accepted", signer.sign(address, message, context=context) == signature)
        request = json.loads(run.call_args.args[0])
        check(
            "sign request contains the canonical message but no private key field",
            request["operation"] == "sign"
            and request["message"] == message.hex()
            and request["network"] == "test"
            and request["block_height"] == 17
            and request["previous_block_hash"] == "ab" * 32
            and request["signing_payload"] == signing_payload.hex()
            and "private_key" not in request,
        )

    cases = [
        (
            "nonzero signer exit fails closed",
            completed("", returncode=2, stderr="internal failure"),
            lambda: signer.get_public_key(address),
        ),
        (
            "malformed signer JSON fails closed",
            completed("not-json"),
            lambda: signer.get_public_key(address),
        ),
        (
            "wrong public-key length fails closed",
            completed(json.dumps({"version": 3, "ok": True, "public_key": "00"})),
            lambda: signer.get_public_key(address),
        ),
        (
            "wrong signature length fails closed",
            completed(json.dumps({"version": 3, "ok": True, "signature": "00"})),
            lambda: signer.sign(address, message, context=context),
        ),
        (
            "oversized signer response fails closed",
            completed("x" * (MAX_RESPONSE_BYTES + 1), exceeded=True),
            lambda: signer.get_public_key(address),
        ),
    ]
    for name, result, callback in cases:
        with patch.object(SubprocessValidatorSigner, "_run_bounded", return_value=result):
            expect_signer_error(name, callback)

    with patch.object(
        SubprocessValidatorSigner,
        "_run_bounded",
        side_effect=subprocess.TimeoutExpired(["validator-signer"], 5),
    ):
        expect_signer_error(
            "signer timeout fails closed",
            lambda: signer.get_public_key(address),
        )

    with patch.object(SubprocessValidatorSigner, "_run_bounded") as run:
        expect_signer_error(
            "oversized validator address is rejected before process launch",
            lambda: signer.get_public_key("x" * 129),
        )
        expect_signer_error(
            "non-ASCII validator address is rejected before process launch",
            lambda: signer.get_public_key("wepo1q\u00e9"),
        )
        check("invalid address never launches the signer", not run.called)


def test_bounded_subprocess_reader():
    flood = SubprocessValidatorSigner(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'x' * 1000000)",
        ],
        timeout_seconds=5,
        max_response_bytes=1024,
    )
    result = flood._run_bounded(b"{}\n")
    check("signer flood is detected during streaming", result.output_exceeded_limit)
    check(
        "signer flood retains at most limit plus one byte",
        len(result.stdout) <= 1025 and len(result.stderr) <= 1025,
    )


def test_environment_loader():
    old_command = os.environ.get(SIGNER_COMMAND_ENV)
    old_timeout = os.environ.get("WEPO_VALIDATOR_SIGNER_TIMEOUT_SECONDS")
    try:
        os.environ.pop(SIGNER_COMMAND_ENV, None)
        os.environ.pop("WEPO_VALIDATOR_SIGNER_TIMEOUT_SECONDS", None)
        check("unset signer command disables PoS signing", load_validator_signer_from_env() is None)

        os.environ[SIGNER_COMMAND_ENV] = "validator-signer --unsafe-string"
        expect_signer_error(
            "signer command must be an explicit JSON argv array",
            load_validator_signer_from_env,
        )

        os.environ[SIGNER_COMMAND_ENV] = json.dumps(
            ["C:/Program Files/WEPO/validator-signer.exe", "--stdio"]
        )
        os.environ["WEPO_VALIDATOR_SIGNER_TIMEOUT_SECONDS"] = "2.5"
        loaded = load_validator_signer_from_env()
        check(
            "JSON argv preserves command boundaries",
            loaded.command
            == ("C:/Program Files/WEPO/validator-signer.exe", "--stdio")
            and loaded.timeout_seconds == 2.5,
        )
    finally:
        if old_command is None:
            os.environ.pop(SIGNER_COMMAND_ENV, None)
        else:
            os.environ[SIGNER_COMMAND_ENV] = old_command
        if old_timeout is None:
            os.environ.pop("WEPO_VALIDATOR_SIGNER_TIMEOUT_SECONDS", None)
        else:
            os.environ["WEPO_VALIDATOR_SIGNER_TIMEOUT_SECONDS"] = old_timeout


def main():
    print("Validator signer boundary:")
    test_consensus_boundary()
    test_subprocess_protocol()
    test_bounded_subprocess_reader()
    test_environment_loader()

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
