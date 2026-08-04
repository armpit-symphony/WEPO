#!/usr/bin/env python3
"""Regression contract for quantitative mainnet parameter decision evidence."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "wepo-blockchain" / "scripts" / "wepo_parameter_decision_evidence.py"
VECTOR = ROOT / "tests" / "vectors" / "mainnet_parameter_decision_evidence_v1.json"
DOCUMENT = ROOT / "docs" / "MAINNET_PARAMETER_DECISION_EVIDENCE.md"


def load_generator():
    spec = importlib.util.spec_from_file_location(
        "wepo_parameter_decision_evidence", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_decision_evidence_matches_source_vectors_and_exact_boundaries():
    generator = load_generator()
    evidence = generator.build_evidence()
    committed = json.loads(VECTOR.read_text(encoding="utf-8"))

    assert committed == evidence
    relay = evidence["relay_fee"]
    representative = relay["representative_transaction"]
    assert representative["canonical_bytes"] == 8160
    assert representative["default_fee_atomic"] == 10000
    assert representative["maximum_compatible_rate_atomic_per_kb"] == 1225
    candidates = {
        item["rate_atomic_per_kb"]: item for item in relay["candidate_rates"]
    }
    assert candidates[1000]["required_fee_atomic"] == 8160
    assert candidates[1000]["default_fee_headroom_atomic"] == 1840
    assert candidates[1225]["default_fee_passes"] is True
    assert candidates[1226]["default_fee_passes"] is False

    maturity = evidence["coinbase_maturity"]
    assert maturity["conservative_candidate_blocks"] == 100
    assert maturity["candidate_time_envelope"] == {
        "pre_pos_minutes": 600,
        "hybrid_fast_minutes": 300,
        "hybrid_slow_minutes": 900,
    }

    emission = evidence["emission"]
    assert emission["cap_reachable_under_current_schedule"] is False
    assert emission["maximum_path_shortfall_atomic"] == "4299353413281400"
    assert emission["no_eligible_pos_shortfall_atomic"] == "4828964660067200"


def test_decision_evidence_cli_accepts_exact_committed_vector():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", str(VECTOR)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "DECISION EVIDENCE MATCH\n"
    assert result.stderr == ""


def test_decision_evidence_cli_rejects_semantic_tampering(tmp_path):
    document = json.loads(VECTOR.read_text(encoding="utf-8"))
    document["relay_fee"]["compatible_round_candidate_atomic_per_kb"] = 1226
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(document), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", str(tampered)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "DECISION EVIDENCE MISMATCH\n"


def test_decision_document_preserves_candidates_and_unresolved_boundaries():
    document = DOCUMENT.read_text(encoding="utf-8")

    assert "no mainnet parameter is approved" in document
    assert "8,160 bytes" in document
    assert "1,000 atomic/kB" in document
    assert "100-block" in document
    assert "42,993,534.13281400" in document
    assert "48,289,646.60067200" in document
    assert "fee/signature size loop" in document
    assert "None of these actions starts the 30-day release clock" in document
