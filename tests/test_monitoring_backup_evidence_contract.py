"""Contracts for release-candidate monitoring and backup/restore evidence."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "wepo-production-deployment"


def valid_monitoring_evidence() -> dict[str, object]:
    return {
        "format": "wepo-monitoring-evidence-v1",
        "network_profile": "release-candidate",
        "mainnet_live_network": False,
        "release_commit": "ab7ca8b8d2e26ac4b6d2534526ba3e7ac41952b2",
        "release_artifact_sha256": "1" * 64,
        "observation_window": {
            "started_at_utc": "2026-08-01T00:00:00Z",
            "ended_at_utc": "2026-08-01T01:00:00Z",
            "duration_minutes": 60,
        },
        "metrics": {
            "chain_height_and_tip": True,
            "peer_count": True,
            "mempool_size_and_bytes": True,
            "consensus_rejections": True,
            "redis_health": True,
            "certificate_expiry": True,
        },
        "node_observations": [
            {
                "role": role,
                "fqdn": f"{role}.owned-wepo-domain.org",
                "p2p_port": 22567,
                "p2p_reachable": True,
                "dependency_health_passed": True,
                "chain_height": 100,
                "latest_block_hash": "2" * 64,
                "peer_count": 2,
                "observed_at_utc": "2026-08-01T00:30:00Z",
            }
            for role in ("seed-a", "seed-b", "seed-c")
        ],
        "alert_tests": [
            {
                "name": name,
                "status": "pass",
                "notification_received": True,
                "observed_at_utc": "2026-08-01T00:45:00Z",
                "evidence_ref": f"retained-{name}-alert-log",
            }
            for name in (
                "node_unreachable",
                "chain_stalled",
                "peer_count_low",
                "redis_unavailable",
                "certificate_expiry",
            )
        ],
        "retention": {
            "days": 30,
            "dashboard_snapshot_sha256": "3" * 64,
            "alert_test_log_sha256": "4" * 64,
            "logs_redacted": True,
        },
    }


def valid_backup_restore_evidence() -> dict[str, object]:
    return {
        "format": "wepo-backup-restore-evidence-v1",
        "network_profile": "release-candidate",
        "mainnet_live_network": False,
        "release_commit": "ab7ca8b8d2e26ac4b6d2534526ba3e7ac41952b2",
        "release_artifact_sha256": "1" * 64,
        "backup": {
            "scope": ["node-chainstate", "backend-durable-state"],
            "encrypted_at_rest": True,
            "encrypted_in_transit": True,
            "off_host_copy": True,
            "encryption_key_separated": True,
            "validator_private_keys_included": False,
            "wallet_seed_phrases_included": False,
            "created_at_utc": "2026-08-01T00:00:00Z",
            "encrypted_artifact_sha256": "6" * 64,
        },
        "restore_drill": {
            "change_approval_recorded": True,
            "isolated_environment": True,
            "restored_from_off_host_copy": True,
            "restore_completed": True,
            "node_started": True,
            "application_health_passed": True,
            "peer_sync_resumed": True,
            "destructive_live_restore_performed": False,
            "expected_chain_height": 100,
            "restored_chain_height": 100,
            "expected_chain_tip_sha256": "7" * 64,
            "restored_chain_tip_sha256": "7" * 64,
            "rpo_target_minutes": 60,
            "rpo_observed_minutes": 20,
            "rto_target_minutes": 120,
            "rto_observed_minutes": 45,
            "completed_at_utc": "2026-08-01T02:00:00Z",
            "evidence_log_sha256": "8" * 64,
            "logs_redacted": True,
        },
        "retention": {
            "independent_failure_domains": 2,
            "retained_copies": 2,
            "restore_drill_interval_days": 30,
        },
    }


def run_validator(tmp_path, script_name: str, evidence: dict[str, object]):
    evidence_path = tmp_path / f"{script_name}.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(DEPLOYMENT / script_name),
            "--evidence",
            str(evidence_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_monitoring_evidence_accepts_three_nodes_metrics_and_alert_delivery(tmp_path):
    result = run_validator(
        tmp_path, "verify-monitoring-evidence.py", valid_monitoring_evidence()
    )

    assert result.returncode == 0, result.stderr
    assert "PASS monitoring and alert evidence" in result.stdout


def test_monitoring_evidence_rejects_missing_alert_and_secret_material(tmp_path):
    evidence = valid_monitoring_evidence()
    evidence["alert_tests"] = evidence["alert_tests"][:-1]
    result = run_validator(tmp_path, "verify-monitoring-evidence.py", evidence)
    assert result.returncode != 0
    assert "missing required alert tests" in result.stderr

    evidence = valid_monitoring_evidence()
    evidence["alert_tests"][0]["evidence_ref"] = "authorization: Bearer leaked-token"
    result = run_validator(tmp_path, "verify-monitoring-evidence.py", evidence)
    assert result.returncode != 0
    assert "secret-like material" in result.stderr

    evidence = valid_monitoring_evidence()
    evidence["node_observations"][0]["fqdn"] = "seed-a.example.invalid"
    result = run_validator(tmp_path, "verify-monitoring-evidence.py", evidence)
    assert result.returncode != 0
    assert "approved owned-domain evidence" in result.stderr

    evidence = valid_monitoring_evidence()
    evidence["node_observations"][0]["latest_block_hash"] = "9" * 64
    result = run_validator(tmp_path, "verify-monitoring-evidence.py", evidence)
    assert result.returncode != 0
    assert "agree on chain height and tip" in result.stderr


def test_backup_restore_evidence_accepts_encrypted_isolated_restore(tmp_path):
    result = run_validator(
        tmp_path,
        "verify-backup-restore-evidence.py",
        valid_backup_restore_evidence(),
    )

    assert result.returncode == 0, result.stderr
    assert "PASS encrypted backup/restore evidence" in result.stdout


def test_backup_restore_evidence_rejects_key_material_or_wrong_restored_tip(tmp_path):
    evidence = valid_backup_restore_evidence()
    evidence["backup"]["validator_private_keys_included"] = True
    result = run_validator(tmp_path, "verify-backup-restore-evidence.py", evidence)
    assert result.returncode != 0
    assert "must exclude key material" in result.stderr

    evidence = valid_backup_restore_evidence()
    evidence["restore_drill"]["restored_chain_tip_sha256"] = "9" * 64
    result = run_validator(tmp_path, "verify-backup-restore-evidence.py", evidence)
    assert result.returncode != 0
    assert "restored chain tip must match" in result.stderr

    evidence = valid_backup_restore_evidence()
    evidence["operator_note"] = "seed phrase: alpha beta gamma delta"
    result = run_validator(tmp_path, "verify-backup-restore-evidence.py", evidence)
    assert result.returncode != 0
    assert "secret-like material" in result.stderr

    evidence = valid_backup_restore_evidence()
    evidence["retention"]["restore_drill_interval_days"] = 365
    result = run_validator(tmp_path, "verify-backup-restore-evidence.py", evidence)
    assert result.returncode != 0
    assert "at most 90 days" in result.stderr


def test_monitoring_and_backup_assets_are_inert_and_wired_to_release_policy():
    monitoring_template = (
        DEPLOYMENT / "monitoring-evidence.template.json"
    ).read_text(encoding="utf-8")
    backup_template = (
        DEPLOYMENT / "backup-restore-evidence.template.json"
    ).read_text(encoding="utf-8")
    qualification = (DEPLOYMENT / "PRODUCTION_HOST_QUALIFICATION.md").read_text(
        encoding="utf-8"
    )
    checklist = (DEPLOYMENT / "PUBLIC_RELEASE_CHECKLIST.md").read_text(
        encoding="utf-8"
    )
    readiness = (ROOT / "MAINNET_READINESS_AND_RELEASE_POLICY.md").read_text(
        encoding="utf-8"
    )

    assert "wepo-monitoring-evidence-v1" in monitoring_template
    assert "wepo-backup-restore-evidence-v1" in backup_template
    assert '"mainnet_live_network": false' in monitoring_template
    assert '"mainnet_live_network": false' in backup_template
    assert "verify-monitoring-evidence.py" in qualification
    assert "verify-backup-restore-evidence.py" in qualification
    assert "monitoring evidence" in checklist
    assert "backup/restore evidence" in checklist
    assert "--monitoring-evidence" in readiness
    assert "--backup-restore-evidence" in readiness
