#!/usr/bin/env python3
"""Fail-closed Ghost subprocess-verifier boundary regressions."""

import hashlib
import json
import os
import threading
import shutil
import struct
import subprocess
import sys
import tempfile
from unittest.mock import patch

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

import blockchain as B  # noqa: E402
import shielded as S  # noqa: E402
import wepo_node as N  # noqa: E402
from shielded_verifier import (  # noqa: E402
    MAX_PROOF_BYTES,
    PROTOCOL_MAGIC,
    VERIFIER_COMMAND_ENV,
    SubprocessShieldedVerifier,
    load_release_shielded_verifier_from_env,
    load_shielded_verifier_from_env,
)

FAILURES = []


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


def completed(returncode):
    return subprocess.CompletedProcess(args=["ghost-verify"], returncode=returncode)


def test_subprocess_boundary():
    digest = bytes(range(32))
    proof = b"winterfell-proof-fixture"
    verifier = SubprocessShieldedVerifier(["ghost-verify", "--stdio"], environment={})

    with patch("shielded_verifier.subprocess.run", return_value=completed(0)) as run:
        check("exit zero accepts a proof", verifier.verify(digest, proof))
        kwargs = run.call_args.kwargs
        request = kwargs["input"]
        check(
            "verifier runs without a shell or output pipes",
            kwargs["shell"] is False
            and kwargs["stdout"] is subprocess.DEVNULL
            and kwargs["stderr"] is subprocess.DEVNULL,
        )
        check(
            "request framing is versioned and length-prefixed",
            request
            == PROTOCOL_MAGIC
            + digest
            + struct.pack("<I", len(proof))
            + proof,
        )

    for name, result in (
        ("invalid proof exit fails closed", completed(1)),
        ("verifier crash exit fails closed", completed(101)),
    ):
        with patch("shielded_verifier.subprocess.run", return_value=result):
            check(name, verifier.verify(digest, proof) is False)

    for name, failure in (
        (
            "verifier timeout fails closed",
            subprocess.TimeoutExpired(["ghost-verify"], 5),
        ),
        ("missing verifier fails closed", FileNotFoundError("ghost-verify")),
    ):
        with patch("shielded_verifier.subprocess.run", side_effect=failure):
            check(name, verifier.verify(digest, proof) is False)

    with patch("shielded_verifier.subprocess.run") as run:
        check("wrong statement size is rejected before process spawn", not verifier.verify(b"x", proof))
        check("empty proof is rejected before process spawn", not verifier.verify(digest, b""))
        check(
            "oversized proof is rejected before process spawn",
            not verifier.verify(digest, b"x" * (MAX_PROOF_BYTES + 1)),
        )
        check("invalid requests never spawn the verifier", run.call_count == 0)


def test_real_process_isolation():
    digest = bytes([8]) * 32
    proof = b"real-subprocess-proof"
    expected = (
        PROTOCOL_MAGIC
        + digest
        + struct.pack("<I", len(proof))
        + proof
    )
    accept_code = (
        "import sys;"
        "data=sys.stdin.buffer.read();"
        f"raise SystemExit(0 if data.hex()=='{expected.hex()}' else 1)"
    )
    verifier = SubprocessShieldedVerifier(
        [sys.executable, "-c", accept_code],
        timeout_seconds=1,
        environment={},
    )
    check("real child process receives exact framing", verifier.verify(digest, proof))
    check("real child rejects a changed statement", not verifier.verify(bytes([9]) * 32, proof))

    crashing = SubprocessShieldedVerifier(
        [sys.executable, "-c", "import os; os._exit(7)"],
        timeout_seconds=1,
        environment={},
    )
    check("real crashing child fails closed", not crashing.verify(digest, proof))

    hanging = SubprocessShieldedVerifier(
        [sys.executable, "-c", "import time; time.sleep(2)"],
        timeout_seconds=0.05,
        environment={},
    )
    check("real hanging child is terminated by timeout", not hanging.verify(digest, proof))


def test_concurrent_process_limit_fails_closed():
    digest = bytes([8]) * 32
    proof = b"bounded-proof"
    entered = threading.Event()
    release = threading.Event()

    def blocking_child(*args, **kwargs):
        entered.set()
        if not release.wait(timeout=2):
            return completed(9)
        return completed(0)

    verifier = SubprocessShieldedVerifier(
        ["ghost-verify"], environment={}, max_concurrent_processes=1
    )
    result = []

    with patch("shielded_verifier.subprocess.run", side_effect=blocking_child) as run:
        worker = threading.Thread(
            target=lambda: result.append(verifier.verify(digest, proof))
        )
        worker.start()
        check("first verifier child occupies the only process slot", entered.wait(1))
        check("saturated verifier fails closed without spawning", not verifier.verify(digest, proof))
        check("saturated request did not invoke a second child", run.call_count == 1)
        release.set()
        worker.join(timeout=2)
        check("first verifier child completed", result == [True] and not worker.is_alive())
        check("released verifier slot is reusable", verifier.verify(digest, proof))
        check("only admitted requests spawned children", run.call_count == 2)


def test_consensus_seam_and_audit_gate():
    sighash = bytes([3]) * 32
    bundle = S.ShieldedBundle(
        outputs=[
            S.OutputDescription(
                commitment=bytes([4]) * 32,
                enc_note=b"opaque-note-ciphertext",
            )
        ],
        proof=b"known-complete-circuit-proof",
    )
    digest = bundle.statement_digest(sighash)
    expected_request = (
        PROTOCOL_MAGIC
        + digest
        + struct.pack("<I", len(bundle.proof))
        + bundle.proof
    )
    verifier = SubprocessShieldedVerifier(["ghost-verify"], environment={})

    def accept_only_known_statement(*args, **kwargs):
        return completed(0 if kwargs.get("input") == expected_request else 1)

    try:
        with patch(
            "shielded_verifier.subprocess.run",
            side_effect=accept_only_known_statement,
        ):
            S.register_verifier(verifier)
            ok, reason = S.verify_bundle(
                bundle,
                sighash,
                S.AnchorSet(),
                S.NullifierSet(),
            )
            check("unaudited subprocess verifier is blocked from consensus", not ok)
            check("registration alone does not claim an audit", not S.verifier_is_audited())

            wrong_ok, _ = S.verify_bundle(
                bundle,
                bytes([5]) * 32,
                S.AnchorSet(),
                S.NullifierSet(),
            )
            check("proof is rejected under a different transaction sighash", not wrong_ok)

            S.register_verifier(verifier, audit_approved=True)
            check("audit state requires explicit approval", S.verifier_is_audited())
            approved_ok, approved_reason = S.verify_bundle(
                bundle,
                sighash,
                S.AnchorSet(),
                S.NullifierSet(),
            )
            check("audit-approved subprocess verifier reaches the consensus seam",
                  approved_ok and approved_reason == "ok")
    finally:
        S.register_verifier(S.RejectAllVerifier())

    check("reject-all restoration clears audit state", not S.verifier_is_audited())


def test_environment_loader():
    old_command = os.environ.get(VERIFIER_COMMAND_ENV)
    old_timeout = os.environ.get("WEPO_SHIELDED_VERIFIER_TIMEOUT_SECONDS")
    old_limit = os.environ.get("WEPO_SHIELDED_VERIFIER_MAX_PROOF_BYTES")
    old_concurrency = os.environ.get("WEPO_SHIELDED_VERIFIER_MAX_CONCURRENT")
    try:
        os.environ.pop(VERIFIER_COMMAND_ENV, None)
        os.environ.pop("WEPO_SHIELDED_VERIFIER_TIMEOUT_SECONDS", None)
        os.environ.pop("WEPO_SHIELDED_VERIFIER_MAX_PROOF_BYTES", None)
        os.environ.pop("WEPO_SHIELDED_VERIFIER_MAX_CONCURRENT", None)
        check("unset command leaves the reject-all default available", load_shielded_verifier_from_env() is None)

        os.environ[VERIFIER_COMMAND_ENV] = "ghost-verify --shell-string"
        try:
            load_shielded_verifier_from_env()
        except ValueError:
            check("shell command strings are rejected", True)
        else:
            check("shell command strings are rejected", False)

        os.environ[VERIFIER_COMMAND_ENV] = json.dumps(
            ["C:/Program Files/WEPO/ghost-verify.exe", "--stdio"]
        )
        os.environ["WEPO_SHIELDED_VERIFIER_TIMEOUT_SECONDS"] = "2.5"
        os.environ["WEPO_SHIELDED_VERIFIER_MAX_PROOF_BYTES"] = "262144"
        os.environ["WEPO_SHIELDED_VERIFIER_MAX_CONCURRENT"] = "3"
        loaded = load_shielded_verifier_from_env()
        check(
            "JSON argv and numeric limits load without shell parsing",
            loaded.command == ("C:/Program Files/WEPO/ghost-verify.exe", "--stdio")
            and loaded.timeout_seconds == 2.5
            and loaded.max_proof_bytes == 262144
            and loaded.max_concurrent_processes == 3,
        )
    finally:
        if old_command is None:
            os.environ.pop(VERIFIER_COMMAND_ENV, None)
        else:
            os.environ[VERIFIER_COMMAND_ENV] = old_command
        if old_timeout is None:
            os.environ.pop("WEPO_SHIELDED_VERIFIER_TIMEOUT_SECONDS", None)
        else:
            os.environ["WEPO_SHIELDED_VERIFIER_TIMEOUT_SECONDS"] = old_timeout
        if old_limit is None:
            os.environ.pop("WEPO_SHIELDED_VERIFIER_MAX_PROOF_BYTES", None)
        else:
            os.environ["WEPO_SHIELDED_VERIFIER_MAX_PROOF_BYTES"] = old_limit
        if old_concurrency is None:
            os.environ.pop("WEPO_SHIELDED_VERIFIER_MAX_CONCURRENT", None)
        else:
            os.environ["WEPO_SHIELDED_VERIFIER_MAX_CONCURRENT"] = old_concurrency


def test_release_artifact_pin():
    old_command = os.environ.get(VERIFIER_COMMAND_ENV)
    descriptor, executable_path = tempfile.mkstemp(prefix="wepo-ghost-verifier-")
    try:
        artifact = b"fixed audited ghost verifier artifact"
        os.write(descriptor, artifact)
        os.close(descriptor)
        descriptor = None
        os.chmod(executable_path, 0o700)
        expected = hashlib.sha256(artifact).hexdigest()

        os.environ[VERIFIER_COMMAND_ENV] = json.dumps([executable_path])
        try:
            load_release_shielded_verifier_from_env(
                audit_approved=False,
                expected_sha256=expected,
            )
        except RuntimeError:
            check("release loader rejects missing source audit approval", True)
        else:
            check("release loader rejects missing source audit approval", False)

        try:
            load_release_shielded_verifier_from_env(
                audit_approved=True,
                expected_sha256="0" * 64,
            )
        except RuntimeError:
            check("release loader rejects an artifact digest mismatch", True)
        else:
            check("release loader rejects an artifact digest mismatch", False)

        os.environ[VERIFIER_COMMAND_ENV] = json.dumps([executable_path, "--argument"])
        try:
            load_release_shielded_verifier_from_env(
                audit_approved=True,
                expected_sha256=expected,
            )
        except RuntimeError:
            check("release loader rejects argument/interpreter indirection", True)
        else:
            check("release loader rejects argument/interpreter indirection", False)

        os.environ[VERIFIER_COMMAND_ENV] = json.dumps([executable_path])
        loaded = load_release_shielded_verifier_from_env(
            audit_approved=True,
            expected_sha256=expected,
        )
        check(
            "release loader pins the exact direct executable",
            loaded.command == (os.path.realpath(executable_path),),
        )

        with open(executable_path, "wb") as executable:
            executable.write(b"replaced after startup")
        with patch("shielded_verifier.subprocess.run") as run:
            check(
                "release verifier rehashes and rejects replacement before every proof",
                not loaded.verify(bytes(32), b"proof"),
            )
            check(
                "replaced release verifier is never executed",
                run.call_count == 0,
            )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(executable_path)
        except FileNotFoundError:
            pass
        if old_command is None:
            os.environ.pop(VERIFIER_COMMAND_ENV, None)
        else:
            os.environ[VERIFIER_COMMAND_ENV] = old_command


def test_activation_startup_gate():
    old_enabled = B.PRIVACY_CONSENSUS_ENABLED
    old_height = B.SHIELDED_ACTIVATION_HEIGHT
    data_dir = tempfile.mkdtemp(prefix="wepo-shielded-startup-")
    try:
        B.PRIVACY_CONSENSUS_ENABLED = True
        B.SHIELDED_ACTIVATION_HEIGHT = 1
        S.register_verifier(S.RejectAllVerifier())
        try:
            B.WepoBlockchain(data_dir=data_dir, network_profile="test")
        except RuntimeError:
            check("enabled chain refuses startup without audited verifier", True)
        else:
            check("enabled chain refuses startup without audited verifier", False)

        B.SHIELDED_ACTIVATION_HEIGHT = None
        S.register_verifier(
            SubprocessShieldedVerifier(["ghost-verifier"], environment={}),
            audit_approved=True,
        )
        try:
            B.WepoBlockchain(data_dir=data_dir, network_profile="test")
        except RuntimeError:
            check("enabled chain refuses missing activation height", True)
        else:
            check("enabled chain refuses missing activation height", False)
    finally:
        B.PRIVACY_CONSENSUS_ENABLED = old_enabled
        B.SHIELDED_ACTIVATION_HEIGHT = old_height
        S.register_verifier(S.RejectAllVerifier())
        shutil.rmtree(data_dir, ignore_errors=True)

    with patch.object(B, "PRIVACY_CONSENSUS_ENABLED", True), patch.object(
        N.shielded_verifier_boundary,
        "SHIELDED_VERIFIER_RELEASE_AUDIT_APPROVED",
        False,
    ):
        try:
            N.configure_release_shielded_verifier()
        except RuntimeError:
            check("full node refuses enabled Ghost without release audit gate", True)
        else:
            check("full node refuses enabled Ghost without release audit gate", False)


def main():
    print("Ghost subprocess verifier boundary:")
    test_subprocess_boundary()
    test_real_process_isolation()
    test_concurrent_process_limit_fails_closed()
    test_consensus_seam_and_audit_gate()
    test_environment_loader()
    test_release_artifact_pin()
    test_activation_startup_gate()

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
