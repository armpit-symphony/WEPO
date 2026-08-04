#!/usr/bin/env python3
"""Validate retained release artifacts, test logs, and genesis evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.serialization import load_pem_public_key


FORMAT = "wepo-release-qualification-evidence-v1"
REQUIRED_TESTS = (
    "python_maintained_suite",
    "rust_release_all_targets",
    "frontend_vitest",
    "frontend_production_build",
    "desktop_package_boundary",
    "github_actions_green",
)
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SECRET_PATTERNS = (
    re.compile(r"(?:redis|mongodb(?:\+srv)?)://", re.IGNORECASE),
    re.compile(r"authorization\s*[:=]", re.IGNORECASE),
    re.compile(r"bearer\s+[a-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"(?:api[_ -]?key|password|private[_ -]?key|seed phrase|mnemonic)\s*[:=]", re.IGNORECASE),
)


def fail(message: str) -> None:
    raise SystemExit(f"[wepo-release-qualification] FAIL {message}")


def require_string(mapping: dict[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"missing non-empty string: {key}")
    return value.strip()


def require_bool(mapping: dict[str, object], key: str) -> bool:
    value = mapping.get(key)
    if not isinstance(value, bool):
        fail(f"missing boolean: {key}")
    return value


def require_int(mapping: dict[str, object], key: str, *, minimum: int = 0) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        fail(f"{key} must be an integer >= {minimum}")
    return value


def require_dict(mapping: dict[str, object], key: str) -> dict[str, object]:
    value = mapping.get(key)
    if not isinstance(value, dict):
        fail(f"missing object: {key}")
    return value


def require_sha256(mapping: dict[str, object], key: str) -> str:
    value = require_string(mapping, key)
    if SHA256.fullmatch(value) is None:
        fail(f"{key} must be a lowercase SHA-256 digest")
    return value


def assert_redacted(value: object, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert_redacted(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_redacted(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            if pattern.search(value):
                fail(f"unredacted secret-like material at {path}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(
    package_path: Path,
    mapping: dict[str, object],
    *,
    file_key: str,
    hash_key: str,
    seen: set[Path],
) -> Path:
    relative_text = require_string(mapping, file_key)
    relative = PurePosixPath(relative_text)
    if relative.is_absolute() or ".." in relative.parts or "\\" in relative_text:
        fail(f"{file_key} must be a safe relative POSIX path")
    root = package_path.parent.resolve()
    artifact = (root / Path(*relative.parts)).resolve()
    try:
        artifact.relative_to(root)
    except ValueError:
        fail(f"{file_key} escapes the qualification bundle")
    if artifact in seen:
        fail(f"qualification artifact path is reused: {relative_text}")
    seen.add(artifact)
    if not artifact.is_file() or artifact.stat().st_size == 0:
        fail(f"missing or empty qualification artifact: {relative_text}")
    actual = sha256(artifact)
    if actual != require_sha256(mapping, hash_key):
        fail(f"qualification artifact hash mismatch: {relative_text}")
    return artifact


def verify_manifest_signature(
    *, manifest_path: Path, signature_path: Path, public_key_path: Path
) -> None:
    try:
        public_key = load_pem_public_key(public_key_path.read_bytes())
    except (TypeError, ValueError) as exc:
        fail(f"release signing public key is not valid PEM: {exc}")
    manifest = manifest_path.read_bytes()
    signature = signature_path.read_bytes()
    try:
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(
                signature,
                manifest,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(signature, manifest, ec.ECDSA(hashes.SHA256()))
        else:
            fail("release signing public key must be RSA or ECDSA")
    except InvalidSignature:
        fail("release manifest detached signature verification failed")


def validate(document: dict[str, object], *, package_path: Path) -> None:
    assert_redacted(document)
    if document.get("format") != FORMAT:
        fail(f"format must be {FORMAT}")
    if require_string(document, "network") != "mainnet":
        fail("network must be mainnet")
    require_string(document, "release_commit")
    require_sha256(document, "release_artifact_sha256")
    require_sha256(document, "parameter_manifest_sha256")
    for key in (
        "clean_runner",
        "reproducible_source_archive",
        "release_manifest_signature_verified",
        "release_manifest_all_files_verified",
    ):
        if not require_bool(document, key):
            fail(f"release qualification requirement must be true: {key}")

    seen: set[Path] = set()
    files = require_dict(document, "retained_files")
    verified_files: dict[str, Path] = {}
    for prefix in (
        "source_archive",
        "signed_source_archive",
        "release_manifest",
        "release_manifest_signature",
        "release_signing_public_key",
        "signature_verification_record",
        "genesis_construction_transcript",
    ):
        verified_files[prefix] = verify_file(
            package_path,
            files,
            file_key=f"{prefix}_file",
            hash_key=f"{prefix}_sha256",
            seen=seen,
        )
    verify_manifest_signature(
        manifest_path=verified_files["release_manifest"],
        signature_path=verified_files["release_manifest_signature"],
        public_key_path=verified_files["release_signing_public_key"],
    )

    tests = require_dict(document, "test_logs")
    if set(tests) != set(REQUIRED_TESTS):
        fail("test_logs must contain exactly the required maintained test surfaces")
    for name in REQUIRED_TESTS:
        item = require_dict(tests, name)
        if require_string(item, "status") != "pass":
            fail(f"retained test log must pass: {name}")
        verify_file(
            package_path,
            item,
            file_key="log_file",
            hash_key="log_sha256",
            seen=seen,
        )
    if require_int(require_dict(tests, "python_maintained_suite"), "passed_count") < 243:
        fail("python maintained suite must retain at least 243 passing tests")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    with args.evidence.open("r", encoding="utf-8") as source:
        document = json.load(source)
    if not isinstance(document, dict):
        fail("qualification evidence root must be an object")
    validate(document, package_path=args.evidence)
    print("[wepo-release-qualification] PASS retained artifacts, test logs, and genesis evidence are complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
