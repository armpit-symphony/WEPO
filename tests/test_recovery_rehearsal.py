"""Contract smoke for the production-volume recovery rehearsal tool."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "wepo-blockchain" / "scripts" / "wepo_recovery_rehearsal.py"


def test_recovery_rehearsal_forced_kill_backup_restore_contract(tmp_path):
    work_directory = tmp_path / "work"
    output_path = tmp_path / "evidence.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--work-directory",
            str(work_directory),
            "--output",
            str(output_path),
            "--blocks",
            "8",
            "--actors",
            "1",
            "--progress-every",
            "2",
            "--timeout-seconds",
            "120",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr

    evidence = json.loads(output_path.read_text(encoding="utf-8"))
    assert evidence["format"] == "wepo-recovery-rehearsal-v1"
    assert evidence["status"] == "pass"
    assert evidence["release_qualification"] is False
    assert evidence["committed"]["height"] == 8
    assert evidence["committed"]["block_rows"] == 9
    assert evidence["committed"]["signed_transfers"] == 7
    assert evidence["committed"]["transaction_rows"] == 16
    assert evidence["source_recovery"]["tip_hash"] == evidence["committed"]["tip_hash"]
    assert evidence["restored_database"]["snapshot"] == evidence["source_recovery"]
    assert evidence["recovery_point_loss_committed_blocks"] == 0
    assert evidence["local_baseline"]["met"] is False
    assert evidence["forced_kill"]["boundary"] == (
        "active uncommitted SQLite block transaction"
    )
    assert evidence["backup"]["manifest"]["quick_check"] == "ok"
    assert Path(evidence["backup"]["path"]).is_file()
    assert Path(evidence["backup"]["manifest_path"]).is_file()
