"""End-to-end tests for assembling and validating release qualification evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "wepo-production-deployment"
ASSEMBLER = DEPLOYMENT / "assemble-release-qualification-evidence.py"
VERIFIER = DEPLOYMENT / "verify-release-qualification-evidence.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_inputs(tmp_path: Path) -> dict[str, Path]:
    release_root = tmp_path / "release-root"
    release_root.mkdir(parents=True)
    payload = release_root / "release-payload.bin"
    payload.write_bytes(b"release payload\n")
    manifest = release_root / "SHA256SUMS"
    manifest.write_text(f"{_sha256(payload)}  {payload.name}\n", encoding="utf-8")

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = release_root / "release-signing-public.pem"
    public_key.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    signature = release_root / "SHA256SUMS.sig"
    signature.write_bytes(
        private_key.sign(manifest.read_bytes(), padding.PKCS1v15(), hashes.SHA256())
    )

    source_archive = tmp_path / "wepo-source.tar.gz"
    source_archive.write_bytes(b"source archive\n")
    signed_source_archive = tmp_path / "wepo-source-signed.tar.gz"
    signed_source_archive.write_bytes(b"signed source archive\n")
    genesis_transcript = tmp_path / "genesis-construction-transcript.json"
    genesis_transcript.write_text('{"genesis":"constructed"}\n', encoding="utf-8")

    logs = {}
    log_contents = {
        "python-maintained.log": "243 passed in 1.23s\n",
        "rust-release.log": "rust all-targets: PASS\n",
        "frontend-vitest.log": "vitest: PASS\n",
        "frontend-build.log": "frontend production build: PASS\n",
        "desktop-package.log": "desktop package boundary: PASS\n",
        "github-actions.log": "github actions: green\n",
    }
    for filename, content in log_contents.items():
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        logs[filename] = path

    return {
        "release_root": release_root,
        "manifest": manifest,
        "signature": signature,
        "public_key": public_key,
        "source_archive": source_archive,
        "signed_source_archive": signed_source_archive,
        "genesis_transcript": genesis_transcript,
        "python_log": logs["python-maintained.log"],
        "rust_log": logs["rust-release.log"],
        "vitest_log": logs["frontend-vitest.log"],
        "build_log": logs["frontend-build.log"],
        "desktop_log": logs["desktop-package.log"],
        "github_actions_log": logs["github-actions.log"],
    }


def _assembler_args(inputs: dict[str, Path], evidence: Path) -> list[str]:
    return [
        sys.executable,
        str(ASSEMBLER),
        "--evidence",
        str(evidence),
        "--release-root",
        str(inputs["release_root"]),
        "--release-commit",
        "release-commit-for-test",
        "--parameter-manifest-sha256",
        "a" * 64,
        "--source-archive",
        str(inputs["source_archive"]),
        "--signed-source-archive",
        str(inputs["signed_source_archive"]),
        "--release-manifest",
        str(inputs["manifest"]),
        "--release-manifest-signature",
        str(inputs["signature"]),
        "--release-signing-public-key",
        str(inputs["public_key"]),
        "--genesis-construction-transcript",
        str(inputs["genesis_transcript"]),
        "--python-maintained-suite-log",
        str(inputs["python_log"]),
        "--rust-release-all-targets-log",
        str(inputs["rust_log"]),
        "--frontend-vitest-log",
        str(inputs["vitest_log"]),
        "--frontend-production-build-log",
        str(inputs["build_log"]),
        "--desktop-package-boundary-log",
        str(inputs["desktop_log"]),
        "--github-actions-green-log",
        str(inputs["github_actions_log"]),
        "--clean-runner",
        "--reproducible-source-archive",
    ]


def _run_assembler(inputs: dict[str, Path], evidence: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _assembler_args(inputs, evidence),
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _run_verifier(evidence: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFIER), "--evidence", str(evidence)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_assembler_output_passes_verifier_and_retains_verified_record(tmp_path):
    inputs = _write_inputs(tmp_path)
    evidence = tmp_path / "evidence" / "release-qualification-evidence.json"

    assembled = _run_assembler(inputs, evidence)

    assert assembled.returncode == 0, assembled.stderr
    document = json.loads(evidence.read_text(encoding="utf-8"))
    record_path = evidence.parent / document["retained_files"][
        "signature_verification_record_file"
    ]
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["verified"] is True
    assert record["algorithm"] == "RSA-PKCS1v15-SHA256"
    assert "BEGIN PUBLIC KEY" not in record_path.read_text(encoding="utf-8")

    verified = _run_verifier(evidence)

    assert verified.returncode == 0, verified.stderr
    assert "PASS retained artifacts" in verified.stdout


def test_assembler_rejects_malformed_detached_signature(tmp_path):
    inputs = _write_inputs(tmp_path)
    inputs["signature"].write_bytes(b"malformed signature\n")
    evidence = tmp_path / "evidence" / "release-qualification-evidence.json"

    result = _run_assembler(inputs, evidence)

    assert result.returncode != 0
    assert "signature does not verify" in result.stderr
    assert not evidence.exists()


def test_assembler_rejects_missing_log_and_missing_pytest_summary(tmp_path):
    inputs = _write_inputs(tmp_path)
    inputs["rust_log"].unlink()
    evidence = tmp_path / "missing-log" / "release-qualification-evidence.json"

    missing = _run_assembler(inputs, evidence)

    assert missing.returncode != 0
    assert "rust_release_all_targets log must exist and be non-empty" in missing.stderr
    assert not evidence.exists()

    summary_inputs_root = tmp_path / "missing-summary"
    inputs = _write_inputs(summary_inputs_root)
    inputs["python_log"].write_text("pytest collection started\n", encoding="utf-8")
    evidence = summary_inputs_root / "evidence" / "release-qualification-evidence.json"

    missing_summary = _run_assembler(inputs, evidence)

    assert missing_summary.returncode != 0
    assert "passed-count summary" in missing_summary.stderr
    assert not evidence.exists()
