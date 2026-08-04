"""Bounded contract smoke for abrupt P2P restart under hostile load."""

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
    / "wepo_p2p_restart_under_load.py"
)


def test_restart_under_load_evidence_contract(tmp_path):
    output = tmp_path / "evidence.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--work-directory",
            str(tmp_path / "work"),
            "--output",
            str(output),
            "--initial-height",
            "2",
            "--offline-blocks",
            "1",
            "--attack-rate",
            "25",
            "--minimum-online-attacks",
            "5",
            "--minimum-post-restart-attacks",
            "5",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr

    evidence = json.loads(output.read_text(encoding="utf-8"))
    actual = evidence["actual"]
    counters = actual["attack_counters"]

    assert evidence["format"] == "wepo-p2p-restart-under-load-v1"
    assert evidence["status"] == "pass"
    assert evidence["release_qualification"] is False
    assert actual["abrupt_exit_code"] not in (None, 0)
    assert counters["online_delivered"] >= 5
    assert counters["online_errors"] == 0
    assert counters["outage_errors"] > 0
    assert counters["post_restart_delivered"] >= 5
    assert counters["post_restart_errors"] == 0
    assert actual["source_replay"] == actual["target_replay"]
    assert actual["target_replay"]["height"] == 3
    assert actual["target_replay"]["quick_check"] == "ok"
    assert actual["target_replay"]["foreign_key_violations"] == 0
    assert evidence["local_baseline"]["met"] is False
    assert all(evidence["acceptance"].values())
