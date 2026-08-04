"""Bounded contract smoke for trusted propagation during hostile P2P load."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "wepo-blockchain"
    / "scripts"
    / "wepo_p2p_trusted_under_load.py"
)


def test_trusted_under_load_evidence_contract(tmp_path):
    output = tmp_path / "evidence.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--work-directory",
            str(tmp_path / "work"),
            "--output",
            str(output),
            "--duration-seconds",
            "4",
            "--attack-rate",
            "20",
            "--propagation-interval-seconds",
            "1",
            "--propagation-timeout-seconds",
            "5",
            "--progress-every-seconds",
            "2",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["format"] == "wepo-p2p-trusted-under-load-v1"
    assert evidence["status"] == "pass"
    assert evidence["release_qualification"] is False
    assert evidence["actual"]["propagation_count"] >= 3
    assert evidence["actual"]["hostile"]["delivered"] >= 40
    assert evidence["actual"]["source_tip"] == evidence["actual"]["target_tip"]
    assert evidence["actual"]["source_supply"] == evidence["actual"]["target_supply"]
    assert evidence["local_baseline"]["met"] is False
    assert all(evidence["acceptance"].values())
