"""Production ML-DSA must have no simulated or permissive fallback path."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
DILITHIUM_SOURCE = CORE / "dilithium.py"
BACKEND_SOURCE = ROOT / "backend" / "server.py"

sys.path.insert(0, str(CORE))
import dilithium as D  # noqa: E402


def test_real_fips204_round_trip_and_metadata():
    D.require_real_mldsa()
    signer = D.DilithiumSigner()
    keypair = signer.generate_keypair()
    message = b"WEPO_MLDSA_FAIL_CLOSED_V1"
    signature = D.sign_with_dilithium(message, keypair.private_key)

    assert len(keypair.public_key) == D.DILITHIUM_PUBKEY_SIZE
    assert len(keypair.private_key) == D.DILITHIUM_PRIVKEY_SIZE
    assert len(signature) == D.DILITHIUM_SIGNATURE_SIZE
    assert D.verify_dilithium_signature(message, signature, keypair.public_key)
    assert not D.verify_dilithium_signature(
        message + b"-tampered",
        signature,
        keypair.public_key,
    )
    assert signer.get_algorithm_info() == {
        "algorithm": "ML-DSA-44",
        "variant": "FIPS 204 ML-DSA-44",
        "security_level": 128,
        "quantum_resistant": True,
        "public_key_size": 1312,
        "private_key_size": 2560,
        "signature_size": 2420,
        "implementation": "dilithium-py (Pure Python NIST ML-DSA)",
        "post_quantum": True,
        "nist_approved": True,
    }


def test_missing_mldsa_dependency_disables_every_public_crypto_entrypoint():
    script = f"""
import json
import sys
sys.path.insert(0, {str(CORE)!r})
import dilithium as d

assert d.REAL_DILITHIUM_AVAILABLE is False
assert d.ML_DSA_44 is None
operations = [
    d.require_real_mldsa,
    d.DilithiumSigner,
    d.generate_dilithium_keypair,
    d.get_dilithium_info,
    lambda: d.sign_with_dilithium(b'm', b'0' * d.DILITHIUM_PRIVKEY_SIZE),
    lambda: d.verify_dilithium_signature(
        b'm',
        b'0' * d.DILITHIUM_SIGNATURE_SIZE,
        b'0' * d.DILITHIUM_PUBKEY_SIZE,
    ),
    lambda: d.DilithiumVerifier().verify(
        b'm',
        b'0' * d.DILITHIUM_SIGNATURE_SIZE,
        b'0' * d.DILITHIUM_PUBKEY_SIZE,
    ),
    d.dilithium_system.generate_keypair,
    lambda: d.dilithium_system.sign(
        b'm',
        b'0' * d.DILITHIUM_PRIVKEY_SIZE,
    ),
    lambda: d.dilithium_system.verify(
        b'm',
        b'0' * d.DILITHIUM_SIGNATURE_SIZE,
        b'0' * d.DILITHIUM_PUBKEY_SIZE,
    ),
    d.dilithium_system.info,
]
errors = []
for operation in operations:
    try:
        operation()
    except RuntimeError as exc:
        errors.append(str(exc))
    else:
        raise AssertionError('cryptographic entrypoint did not fail closed')
assert len(errors) == len(operations)
assert all('unavailable' in message or 'requires' in message for message in errors)
print(json.dumps({{'blocked_entrypoints': len(errors)}}))
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {"blocked_entrypoints": 11}


def test_simulator_code_is_absent_and_backend_guard_precedes_database_work():
    source = DILITHIUM_SOURCE.read_text(encoding="utf-8")
    for forbidden in (
        "cryptography.hazmat",
        "rsa.generate_private_key",
        "_verify_rsa_simulation",
        "_format_to_dilithium_signature",
        "_format_to_dilithium_public",
        "_format_to_dilithium_private",
    ):
        assert forbidden not in source

    tree = ast.parse(BACKEND_SOURCE.read_text(encoding="utf-8"))
    startup = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "startup_event"
    )
    startup_source = ast.unparse(ast.Module(body=startup.body[:3], type_ignores=[]))
    assert "WEPO_NETWORK_PROFILE is None" in startup_source
    assert "WEPO_NETWORK_PROFILE.name == 'mainnet'" in startup_source
    assert "require_real_mldsa()" in startup_source
    assert "await db" not in startup_source
