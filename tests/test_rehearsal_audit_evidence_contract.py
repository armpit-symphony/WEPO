"""Contracts for seven-day rehearsal and retained external-audit evidence."""

from __future__ import annotations

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


def run_validator(script: str, argument: str, path: Path):
    return subprocess.run(
        [sys.executable, str(DEPLOYMENT / script), argument, str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def write_rehearsal(tmp_path: Path) -> Path:
    helpers = load_fixture_helpers()
    paths = []
    for name in ("seed.json", "redis.json", "monitoring.json", "backup.json"):
        path = tmp_path / name
        path.write_text(f"retained {name}\n", encoding="utf-8")
        paths.append(path)
    rehearsal = tmp_path / "seven-day-rehearsal.json"
    helpers._write_valid_seven_day_rehearsal(
        rehearsal,
        MANIFEST_SHA,
        seed_path=paths[0],
        redis_path=paths[1],
        monitoring_path=paths[2],
        backup_path=paths[3],
    )
    return rehearsal


def write_audit_package(tmp_path: Path) -> Path:
    helpers = load_fixture_helpers()
    package = tmp_path / "external-audit-package.json"
    helpers._write_valid_external_audit_package(package, MANIFEST_SHA)
    return package


def test_seven_day_validator_accepts_continuous_converged_candidate(tmp_path):
    rehearsal = write_rehearsal(tmp_path)
    result = run_validator(
        "verify-seven-day-rehearsal-evidence.py", "--evidence", rehearsal
    )

    assert result.returncode == 0, result.stderr
    assert "PASS seven-day candidate evidence" in result.stdout


def test_seven_day_validator_rejects_short_divergent_or_secret_evidence(tmp_path):
    rehearsal = write_rehearsal(tmp_path)
    document = json.loads(rehearsal.read_text(encoding="utf-8"))
    document["observation_window"]["ended_at_utc"] = "2026-08-07T23:59:59Z"
    rehearsal.write_text(json.dumps(document), encoding="utf-8")
    result = run_validator(
        "verify-seven-day-rehearsal-evidence.py", "--evidence", rehearsal
    )
    assert result.returncode != 0
    assert "at least 168 continuous hours" in result.stderr

    rehearsal = write_rehearsal(tmp_path)
    document = json.loads(rehearsal.read_text(encoding="utf-8"))
    document["node_observations"][0]["final_block_hash"] = "9" * 64
    rehearsal.write_text(json.dumps(document), encoding="utf-8")
    result = run_validator(
        "verify-seven-day-rehearsal-evidence.py", "--evidence", rehearsal
    )
    assert result.returncode != 0
    assert "agree on final chain height and tip" in result.stderr

    rehearsal = write_rehearsal(tmp_path)
    document = json.loads(rehearsal.read_text(encoding="utf-8"))
    document["operator_note"] = "authorization: Bearer leaked-token"
    rehearsal.write_text(json.dumps(document), encoding="utf-8")
    result = run_validator(
        "verify-seven-day-rehearsal-evidence.py", "--evidence", rehearsal
    )
    assert result.returncode != 0
    assert "secret-like material" in result.stderr


def test_seven_day_validator_requires_mandatory_ghost_and_pos_drills(tmp_path):
    rehearsal = write_rehearsal(tmp_path)
    document = json.loads(rehearsal.read_text(encoding="utf-8"))
    document["drills"]["ghost_valid_transfer_passed"] = False
    rehearsal.write_text(json.dumps(document), encoding="utf-8")

    result = run_validator(
        "verify-seven-day-rehearsal-evidence.py", "--evidence", rehearsal
    )

    assert result.returncode != 0
    assert "required rehearsal drill must pass: ghost_valid_transfer_passed" in result.stderr



def test_external_audit_validator_hashes_all_retained_bundle_files(tmp_path):
    package = write_audit_package(tmp_path)
    result = run_validator(
        "verify-external-audit-package.py", "--package", package
    )

    assert result.returncode == 0, result.stderr
    assert "PASS external-audit bundle" in result.stdout


def test_external_audit_validator_rejects_tamper_escape_or_open_high(tmp_path):
    package = write_audit_package(tmp_path)
    document = json.loads(package.read_text(encoding="utf-8"))
    report = package.parent / document["audits"][0]["report_file"]
    report.write_bytes(report.read_bytes() + b"tampered")
    result = run_validator(
        "verify-external-audit-package.py", "--package", package
    )
    assert result.returncode != 0
    assert "artifact hash mismatch" in result.stderr

    package = write_audit_package(tmp_path)
    document = json.loads(package.read_text(encoding="utf-8"))
    document["audits"][0]["report_file"] = "../outside.pdf"
    package.write_text(json.dumps(document), encoding="utf-8")
    result = run_validator(
        "verify-external-audit-package.py", "--package", package
    )
    assert result.returncode != 0
    assert "safe relative POSIX path" in result.stderr

    package = write_audit_package(tmp_path)
    document = json.loads(package.read_text(encoding="utf-8"))
    document["audits"][0]["high_open"] = 1
    package.write_text(json.dumps(document), encoding="utf-8")
    result = run_validator(
        "verify-external-audit-package.py", "--package", package
    )
    assert result.returncode != 0
    assert "critical and high findings must be closed" in result.stderr

    package = write_audit_package(tmp_path)
    document = json.loads(package.read_text(encoding="utf-8"))
    document["audits"][0]["auditor_organization"] = "WEPO Internal Review"
    package.write_text(json.dumps(document), encoding="utf-8")
    result = run_validator(
        "verify-external-audit-package.py", "--package", package
    )
    assert result.returncode != 0
    assert "must be external" in result.stderr

    package = write_audit_package(tmp_path)
    document = json.loads(package.read_text(encoding="utf-8"))
    document["reviewed_at_utc"] = "2026-07-31T23:59:59Z"
    package.write_text(json.dumps(document), encoding="utf-8")
    result = run_validator(
        "verify-external-audit-package.py", "--package", package
    )
    assert result.returncode != 0
    assert "after all audit reports" in result.stderr


def test_rehearsal_and_audit_assets_are_inert_complete_and_policy_wired():
    rehearsal_template = json.loads(
        (DEPLOYMENT / "seven-day-rehearsal-evidence.template.json").read_text(
            encoding="utf-8"
        )
    )
    audit_template = json.loads(
        (DEPLOYMENT / "external-audit-package.template.json").read_text(
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

    assert rehearsal_template["mainnet_live_network"] is False
    assert {item["scope"] for item in audit_template["audits"]} == {
        "protocol",
        "security",
        "wallet",
        "operations",
    }
    assert "verify-seven-day-rehearsal-evidence.py" in qualification
    assert "verify-external-audit-package.py" in qualification
    assert "seven-day rehearsal evidence" in checklist
    assert "external-audit package" in checklist
    assert "--seven-day-rehearsal-evidence" in readiness
    assert "--external-audit-package" in readiness
