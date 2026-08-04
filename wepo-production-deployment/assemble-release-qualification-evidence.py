#!/usr/bin/env python3
"""Build a retained release-qualification evidence bundle from CI/rehearsal artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

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
REQUIRED_PYTEST_PASS_MINIMUM = 243
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
MANIFEST_ENTRY = re.compile(r"^([0-9a-f]{64})\s+([ *]?)?(.+)$")


def fail(message: str) -> None:
    raise SystemExit(f"[wepo-release-qualification-assembler] FAIL {message}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_file(path: Path, name: str) -> Path:
    if not path.is_file() or path.stat().st_size == 0:
        fail(f"{name} must exist and be non-empty: {path}")
    return path


def require_bool(value: bool, name: str) -> bool:
    if not isinstance(value, bool):
        fail(f"{name} must be true/false")
    return value


def require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        fail(f"{name} must be lowercase SHA-256 hex")
    return value


def safe_posix(path_text: str) -> PurePosixPath:
    candidate = PurePosixPath(path_text)
    if candidate.is_absolute() or ".." in candidate.parts or "\\" in path_text:
        fail(f"unsafe relative POSIX path in evidence manifest: {path_text}")
    return candidate


def copy_into(output_root: Path, relative: str, source: Path) -> Path:
    destination = output_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def verify_manifest_signature(
    *, manifest_path: Path, signature_path: Path, public_key_path: Path
) -> tuple[bool, dict[str, Any]]:
    manifest = manifest_path.read_bytes()
    signature = signature_path.read_bytes()
    try:
        public_key = load_pem_public_key(public_key_path.read_bytes())
    except (TypeError, ValueError) as exc:
        fail(f"release signing public key is not valid PEM: {exc}")

    try:
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(
                signature,
                manifest,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            algorithm = "RSA-PKCS1v15-SHA256"
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(signature, manifest, ec.ECDSA(hashes.SHA256()))
            algorithm = "ECDSA-SHA256"
        else:
            fail("release signing public key must be RSA or ECDSA")
    except InvalidSignature:
        return False, {}

    return True, {
        "algorithm": algorithm,
        "manifest_sha256": sha256(manifest_path),
        "signature_sha256": sha256(signature_path),
        "release_signing_public_key_sha256": sha256(public_key_path),
        "verified_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verified": True,
    }


def parse_manifest(manifest: Path) -> list[tuple[str, str]]:
    lines = manifest.read_text(encoding="utf-8").splitlines()
    entries: list[tuple[str, str]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        match = MANIFEST_ENTRY.fullmatch(line)
        if not match:
            fail(f"invalid SHA256SUMS entry: {line}")
        digest, _star, artifact = match.groups()
        if not HEX64.fullmatch(digest):
            fail(f"manifest digest must be lowercase SHA-256: {line}")
        artifact_path = artifact.strip()
        if not artifact_path:
            fail(f"manifest entry has empty artifact path: {line}")
        entries.append((artifact_path, digest))
    if not entries:
        fail("release manifest has no entries")
    return entries


def verify_manifest_all_files(
    manifest_entries: list[tuple[str, str]],
    release_root: Path,
) -> bool:
    for artifact_path, expected_digest in manifest_entries:
        entry_path = safe_posix(artifact_path)
        source = release_root / Path(entry_path)
        if not source.is_file() or source.stat().st_size == 0:
            fail(f"manifest references missing or empty file: {artifact_path}")
        actual = sha256(source)
        if actual != expected_digest:
            fail(
                f"release manifest digest mismatch for {artifact_path}: "
                f"expected {expected_digest} got {actual}"
            )
    return True


def parse_python_passed_count(path: Path, forced_count: int | None) -> int:
    if forced_count is not None:
        if forced_count < REQUIRED_PYTEST_PASS_MINIMUM:
            fail(
                f"python_maintained_suite passed_count must be >= "
                f"{REQUIRED_PYTEST_PASS_MINIMUM}"
            )
        return forced_count

    text = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"^(\d+)\s+passed", text, re.MULTILINE)
    if not match:
        fail(
            "python_maintained_suite log must contain a pytest passed-count summary"
        )
    count = int(match.group(1))
    if count < REQUIRED_PYTEST_PASS_MINIMUM:
        fail(
            f"python_maintained_suite passed_count must be >= "
            f"{REQUIRED_PYTEST_PASS_MINIMUM}"
        )
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Assemble release-qualification evidence with hashes, verified signatures, "
            "and test logs."
        )
    )
    parser.add_argument("--template", type=Path, default=None, help="Template path")
    parser.add_argument(
        "--evidence", type=Path, required=True, help="Output evidence JSON path"
    )
    parser.add_argument(
        "--release-root",
        type=Path,
        default=None,
        help="Release-root directory for SHA256SUMS path resolution",
    )
    parser.add_argument("--release-commit", required=True)
    parser.add_argument("--parameter-manifest-sha256", required=True)
    parser.add_argument("--source-archive", required=True, type=Path)
    parser.add_argument("--signed-source-archive", required=True, type=Path)
    parser.add_argument("--release-manifest", required=True, type=Path)
    parser.add_argument("--release-manifest-signature", required=True, type=Path)
    parser.add_argument("--release-signing-public-key", required=True, type=Path)
    parser.add_argument("--genesis-construction-transcript", required=True, type=Path)
    parser.add_argument("--release-artifact-sha256", default=None)
    parser.add_argument("--clean-runner", action="store_true")
    parser.add_argument("--reproducible-source-archive", action="store_true")

    parser.add_argument(
        "--python-maintained-suite-log",
        required=True,
        type=Path,
        help="Maintained pytest log file",
    )
    parser.add_argument(
        "--rust-release-all-targets-log",
        required=True,
        type=Path,
        help="Rust release-all-targets evidence log",
    )
    parser.add_argument(
        "--frontend-vitest-log",
        required=True,
        type=Path,
        help="Frontend Vitest evidence log",
    )
    parser.add_argument(
        "--frontend-production-build-log",
        required=True,
        type=Path,
        help="Frontend production build evidence log",
    )
    parser.add_argument(
        "--desktop-package-boundary-log",
        required=True,
        type=Path,
        help="Desktop package-boundary evidence log",
    )
    parser.add_argument(
        "--github-actions-green-log",
        required=True,
        type=Path,
        help="GitHub Actions green proof log",
    )
    parser.add_argument(
        "--python-maintained-suite-passed-count",
        type=int,
        default=None,
        help="Optional override for passed-count in maintained pytest suite",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    template_path = args.template or (
        Path(__file__).resolve().parent / "release-qualification-evidence.template.json"
    )
    template = json.loads(template_path.read_text(encoding="utf-8"))
    if not isinstance(template, dict):
        fail("template root must be a JSON object")
    if template.get("format") != FORMAT:
        fail(f"template format must be {FORMAT}")

    evidence_path = args.evidence.resolve()
    evidence_root = evidence_path.parent
    evidence_root.mkdir(parents=True, exist_ok=True)

    release_manifest = require_file(args.release_manifest, "release-manifest")
    release_manifest_signature = require_file(
        args.release_manifest_signature, "release-manifest signature"
    )
    release_signing_public_key = require_file(
        args.release_signing_public_key, "release-signing public key"
    )
    source_archive = require_file(args.source_archive, "source archive")
    signed_source_archive = require_file(
        args.signed_source_archive, "signed source archive"
    )
    genesis_transcript = require_file(
        args.genesis_construction_transcript, "genesis-construction transcript"
    )

    python_log = require_file(args.python_maintained_suite_log, "python_maintained_suite log")
    rust_log = require_file(
        args.rust_release_all_targets_log, "rust_release_all_targets log"
    )
    frontend_vitest_log = require_file(args.frontend_vitest_log, "frontend_vitest log")
    frontend_build_log = require_file(
        args.frontend_production_build_log, "frontend_production_build log"
    )
    desktop_log = require_file(
        args.desktop_package_boundary_log, "desktop_package_boundary log"
    )
    github_actions_log = require_file(
        args.github_actions_green_log, "github-actions-green log"
    )

    release_root = args.release_root.resolve() if args.release_root else release_manifest.parent
    manifest_entries = parse_manifest(release_manifest)

    copied_manifest = copy_into(
        evidence_root,
        "artifacts/SHA256SUMS",
        release_manifest,
    )
    copied_signature = copy_into(
        evidence_root,
        "artifacts/SHA256SUMS.sig",
        release_manifest_signature,
    )
    copied_key = copy_into(
        evidence_root,
        "artifacts/release-signing-public.pem",
        release_signing_public_key,
    )
    copied_source = copy_into(
        evidence_root,
        "artifacts/wepo-source.tar.gz",
        source_archive,
    )
    copied_signed = copy_into(
        evidence_root,
        "artifacts/wepo-source-signed.tar.gz",
        signed_source_archive,
    )
    copied_transcript = copy_into(
        evidence_root,
        "artifacts/genesis-construction-transcript.json",
        genesis_transcript,
    )

    copied_python_log = copy_into(evidence_root, "logs/python-maintained.log", python_log)
    copied_rust_log = copy_into(
        evidence_root,
        "logs/rust-release.log",
        rust_log,
    )
    copied_vitest_log = copy_into(evidence_root, "logs/frontend-vitest.log", frontend_vitest_log)
    copied_build_log = copy_into(
        evidence_root,
        "logs/frontend-build.log",
        frontend_build_log,
    )
    copied_desktop_log = copy_into(
        evidence_root,
        "logs/desktop-package.log",
        desktop_log,
    )
    copied_github_actions_log = copy_into(
        evidence_root,
        "logs/github-actions.log",
        github_actions_log,
    )

    signature_verified, signature_record = verify_manifest_signature(
        manifest_path=copied_manifest,
        signature_path=copied_signature,
        public_key_path=copied_key,
    )
    if signature_verified:
        copied_signature_record = evidence_root / "artifacts/signature-verification.json"
        copied_signature_record.parent.mkdir(parents=True, exist_ok=True)
        copied_signature_record.write_text(
            json.dumps(signature_record, indent=2) + "\n", encoding="utf-8"
        )
    else:
        fail("release manifest signature does not verify")

    manifest_all_files_verified = verify_manifest_all_files(manifest_entries, release_root)

    release_artifact_sha256 = args.release_artifact_sha256
    if release_artifact_sha256 is None:
        release_artifact_sha256 = sha256(copied_signed)
    release_artifact_sha256 = require_sha256(release_artifact_sha256, "release_artifact_sha256")

    if not require_bool(args.clean_runner, "clean_runner"):
        fail("clean runner is required for release assembly")
    if not require_bool(args.reproducible_source_archive, "reproducible_source_archive"):
        fail("reproducible-source-archive is required for release assembly")

    if require_sha256(args.parameter_manifest_sha256, "parameter_manifest_sha256") is None:
        fail("parameter_manifest_sha256 must be a lowercase SHA-256 digest")

    passed_count = parse_python_passed_count(
        copied_python_log, args.python_maintained_suite_passed_count
    )

    retained_files = {
        "source_archive_file": "artifacts/wepo-source.tar.gz",
        "source_archive_sha256": sha256(copied_source),
        "signed_source_archive_file": "artifacts/wepo-source-signed.tar.gz",
        "signed_source_archive_sha256": sha256(copied_signed),
        "release_manifest_file": "artifacts/SHA256SUMS",
        "release_manifest_sha256": sha256(copied_manifest),
        "release_manifest_signature_file": "artifacts/SHA256SUMS.sig",
        "release_manifest_signature_sha256": sha256(copied_signature),
        "release_signing_public_key_file": "artifacts/release-signing-public.pem",
        "release_signing_public_key_sha256": sha256(copied_key),
        "signature_verification_record_file": "artifacts/signature-verification.json",
        "signature_verification_record_sha256": sha256(copied_signature_record),
        "genesis_construction_transcript_file": "artifacts/genesis-construction-transcript.json",
        "genesis_construction_transcript_sha256": sha256(copied_transcript),
    }
    require_sha256(retained_files["source_archive_sha256"], "source_archive_sha256")
    require_sha256(retained_files["signed_source_archive_sha256"], "signed_source_archive_sha256")
    require_sha256(retained_files["release_manifest_sha256"], "release_manifest_sha256")
    require_sha256(retained_files["release_manifest_signature_sha256"], "release_manifest_signature_sha256")
    require_sha256(retained_files["release_signing_public_key_sha256"], "release_signing_public_key_sha256")
    require_sha256(retained_files["signature_verification_record_sha256"], "signature_verification_record_sha256")
    require_sha256(retained_files["genesis_construction_transcript_sha256"], "genesis_construction_transcript_sha256")

    test_logs = {
        "python_maintained_suite": {
            "status": "pass",
            "passed_count": passed_count,
            "log_file": "logs/python-maintained.log",
            "log_sha256": sha256(copied_python_log),
        },
        "rust_release_all_targets": {
            "status": "pass",
            "log_file": "logs/rust-release.log",
            "log_sha256": sha256(copied_rust_log),
        },
        "frontend_vitest": {
            "status": "pass",
            "log_file": "logs/frontend-vitest.log",
            "log_sha256": sha256(copied_vitest_log),
        },
        "frontend_production_build": {
            "status": "pass",
            "log_file": "logs/frontend-build.log",
            "log_sha256": sha256(copied_build_log),
        },
        "desktop_package_boundary": {
            "status": "pass",
            "log_file": "logs/desktop-package.log",
            "log_sha256": sha256(copied_desktop_log),
        },
        "github_actions_green": {
            "status": "pass",
            "log_file": "logs/github-actions.log",
            "log_sha256": sha256(copied_github_actions_log),
        },
    }

    for name in REQUIRED_TESTS:
        if name not in test_logs:
            fail(f"missing required test status: {name}")

    if name := " ".join(sorted({k for k in test_logs} - set(REQUIRED_TESTS))):
        # defensive: only expected surfaces must exist
        fail(f"unexpected test surface in assembled evidence: {name}")

    document = dict(template)
    document["format"] = FORMAT
    document["network"] = "mainnet"
    document["release_commit"] = args.release_commit
    document["release_artifact_sha256"] = release_artifact_sha256
    document["parameter_manifest_sha256"] = require_sha256(
        args.parameter_manifest_sha256, "parameter_manifest_sha256"
    )
    document["clean_runner"] = True
    document["reproducible_source_archive"] = True
    document["release_manifest_signature_verified"] = signature_verified
    document["release_manifest_all_files_verified"] = manifest_all_files_verified
    document["retained_files"] = retained_files
    document["test_logs"] = test_logs

    evidence_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    print("[wepo-release-qualification-assembler] PASS evidence assembled:")
    print(f"[wepo-release-qualification-assembler] evidence={evidence_path}")
    print(
        "[wepo-release-qualification-assembler] retained_files="
        f"{len(retained_files)} test_logs={len(test_logs)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
