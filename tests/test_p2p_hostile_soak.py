"""Bounded contract smoke for the real-socket hostile P2P soak tool."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "wepo-blockchain" / "scripts" / "wepo_p2p_hostile_soak.py"


def test_hostile_soak_contract_smoke(tmp_path):
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
            "30",
            "--slow-clients",
            "0",
            "--sample-interval-seconds",
            "0.25",
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
    assert evidence["format"] == "wepo-p2p-hostile-soak-v1"
    assert evidence["status"] == "pass"
    assert evidence["release_qualification"] is False
    assert evidence["actual"]["total_attacks"] >= 50
    assert evidence["actual"]["peak_banned_hosts"] > 0
    assert evidence["actual"]["database_growth_bytes"] == 0
    assert evidence["actual"]["initial_tip"] == evidence["actual"]["ending_tip"]
    assert evidence["actual"]["peers_after_shutdown"] == 0
    assert evidence["local_baseline"]["met"] is False
    assert all(evidence["acceptance"].values())
