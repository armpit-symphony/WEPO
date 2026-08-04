"""Contracts for retained release artifacts, test logs, and genesis evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "wepo-production-deployment"
CLI_TEST = ROOT / "tests" / "test_mainnet_release_gate_cli.py"
MANIFEST_SHA = "1" * 64


def load_fixture_helpers():
    spec = importlib.util.spec_from_file_location("release_gate_test_helpers", CLI_TEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_qualification(tmp_path: Path) -> Path:
    path = tmp_path / "release-qualification-evidence.json"
    load_fixture_helpers()._write_valid_release_qualification(path, MANIFEST_SHA)
    return path


def run_validator(path: Path):
    return subprocess.run(
        [
            sys.executable,
            str(DEPLOYMENT / "verify-release-qualification-evidence.py"),
            "--evidence",
            str(path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_release_qualification_accepts_complete_retained_bundle(tmp_path):
    result = run_validator(write_qualification(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "PASS retained artifacts, test logs, and genesis evidence" in result.stdout


def test_release_qualification_rejects_tamper_escape_or_empty_artifact(tmp_path):
    path = write_qualification(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    artifact = path.parent / document["retained_files"]["source_archive_file"]
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    result = run_validator(path)
    assert result.returncode != 0
    assert "artifact hash mismatch" in result.stderr

    path = write_qualification(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    signature = path.parent / document["retained_files"][
        "release_manifest_signature_file"
    ]
    signature.write_bytes(signature.read_bytes() + b"tampered")
    document["retained_files"]["release_manifest_signature_sha256"] = (
        hashlib.sha256(signature.read_bytes()).hexdigest()
    )
    path.write_text(json.dumps(document), encoding="utf-8")
    result = run_validator(path)
    assert result.returncode != 0
    assert "detached signature verification failed" in result.stderr

    path = write_qualification(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["retained_files"]["source_archive_file"] = "../outside.tar.gz"
    path.write_text(json.dumps(document), encoding="utf-8")
    result = run_validator(path)
    assert result.returncode != 0
    assert "safe relative POSIX path" in result.stderr

    path = write_qualification(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    artifact = path.parent / document["retained_files"]["source_archive_file"]
    artifact.write_bytes(b"")
    result = run_validator(path)
    assert result.returncode != 0
    assert "missing or empty qualification artifact" in result.stderr


def test_release_qualification_rejects_incomplete_or_failed_test_surfaces(tmp_path):
    path = write_qualification(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["test_logs"]["frontend_vitest"]["status"] = "fail"
    path.write_text(json.dumps(document), encoding="utf-8")
    result = run_validator(path)
    assert result.returncode != 0
    assert "retained test log must pass" in result.stderr

    path = write_qualification(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["test_logs"].pop("desktop_package_boundary")
    path.write_text(json.dumps(document), encoding="utf-8")
    result = run_validator(path)
    assert result.returncode != 0
    assert "exactly the required maintained test surfaces" in result.stderr

    path = write_qualification(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["test_logs"]["python_maintained_suite"]["passed_count"] = 242
    path.write_text(json.dumps(document), encoding="utf-8")
    result = run_validator(path)
    assert result.returncode != 0
    assert "at least 243 passing tests" in result.stderr


def test_release_qualification_rejects_secret_text_or_false_attestations(tmp_path):
    path = write_qualification(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["operator_note"] = "api_key=do-not-retain-this"
    path.write_text(json.dumps(document), encoding="utf-8")
    result = run_validator(path)
    assert result.returncode != 0
    assert "secret-like material" in result.stderr

    for field in (
        "clean_runner",
        "reproducible_source_archive",
        "release_manifest_signature_verified",
        "release_manifest_all_files_verified",
    ):
        path = write_qualification(tmp_path)
        document = json.loads(path.read_text(encoding="utf-8"))
        document[field] = False
        path.write_text(json.dumps(document), encoding="utf-8")
        result = run_validator(path)
        assert result.returncode != 0
        assert "requirement must be true" in result.stderr


def test_release_qualification_assets_are_inert_complete_and_gate_wired():
    template = json.loads(
        (DEPLOYMENT / "release-qualification-evidence.template.json").read_text(
            encoding="utf-8"
        )
    )
    qualification = (DEPLOYMENT / "PRODUCTION_HOST_QUALIFICATION.md").read_text(
        encoding="utf-8"
    )
    checklist = (DEPLOYMENT / "PUBLIC_RELEASE_CHECKLIST.md").read_text(
        encoding="utf-8"
    )
    readiness = (ROOT / "MAINNET_READINESS_AND_RELEASE_POLICY.md").read_text(
        encoding="utf-8"
    )
    gate = (ROOT / "wepo-blockchain" / "scripts" / "wepo_mainnet_release_gate.py").read_text(
        encoding="utf-8"
    )

    assert template["clean_runner"] is False
    assert template["release_manifest_signature_verified"] is False
    assert set(template["test_logs"]) == {
        "python_maintained_suite",
        "rust_release_all_targets",
        "frontend_vitest",
        "frontend_production_build",
        "desktop_package_boundary",
        "github_actions_green",
    }
    assert "verify-release-qualification-evidence.py" in qualification
    assert "release qualification" in checklist.lower()
    assert "genesis transcript" in checklist.lower()
    assert "--release-qualification-evidence" in readiness
    assert "release_qualification_evidence_missing" in gate
