"""Fail-closed audit coverage for mandatory Ghost and PoS launch features."""

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


def _helpers():
    spec = importlib.util.spec_from_file_location("release_gate_helpers", CLI_TEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_package(tmp_path: Path) -> Path:
    path = tmp_path / "external-audit-package.json"
    _helpers()._write_valid_external_audit_package(path, MANIFEST_SHA)
    return path


def _run(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(DEPLOYMENT / "verify-external-audit-package.py"),
            "--package",
            str(path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_complete_mandatory_feature_audit_coverage_passes(tmp_path):
    result = _run(_write_package(tmp_path))

    assert result.returncode == 0, result.stderr


def test_false_mandatory_feature_assertion_fails_closed(tmp_path):
    path = _write_package(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["mandatory_feature_coverage"]["ghost"][
        "wallet_prover_and_recovery_reviewed"
    ] = False
    path.write_text(json.dumps(document), encoding="utf-8")

    result = _run(path)

    assert result.returncode != 0
    assert "ghost.wallet_prover_and_recovery_reviewed" in result.stderr


def test_missing_feature_or_audit_scope_fails_closed(tmp_path):
    path = _write_package(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["mandatory_feature_coverage"].pop("proof_of_stake")
    path.write_text(json.dumps(document), encoding="utf-8")
    missing_feature = _run(path)
    assert missing_feature.returncode != 0
    assert "exactly Ghost and Proof-of-Stake" in missing_feature.stderr

    path = _write_package(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["mandatory_feature_coverage"]["proof_of_stake"][
        "covered_by_scopes"
    ].remove("operations")
    path.write_text(json.dumps(document), encoding="utf-8")
    missing_scope = _run(path)
    assert missing_scope.returncode != 0
    assert "covered by every audit scope" in missing_scope.stderr
