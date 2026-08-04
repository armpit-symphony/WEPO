#!/usr/bin/env python3
"""Operator-facing contract for the read-only mainnet release-gate CLI."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "wepo-blockchain" / "scripts" / "wepo_mainnet_release_gate.py"


def load_cli():
    spec = importlib.util.spec_from_file_location("wepo_mainnet_release_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_status_is_structured_read_only_and_nonzero_while_gate_is_closed(tmp_path):
    before = sorted(path.name for path in tmp_path.iterdir())
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "status"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    after = sorted(path.name for path in tmp_path.iterdir())

    assert result.returncode == 2
    assert result.stderr == ""
    assert before == after == []
    document = json.loads(result.stdout)
    assert document["schema"] == "wepo-mainnet-release-gate-status-v1"
    assert document["network"] == "mainnet"
    assert document["ready"] is False
    assert "genesis_parameters_unfinalized" in document["blockers"]
    assert "parameter_manifest_sha256_unset" in document["blockers"]
    assert "seed_node_inventory_evidence_missing" in document["blockers"]
    assert "redis_outage_evidence_missing" in document["blockers"]
    assert "readiness_decision_package_missing" in document["blockers"]
    assert document["evidence"]["seed_node_inventory"]["status"] == "missing"
    assert document["decisions"]["ghost_consensus_ready"] is False
    assert document["decisions"]["ghost_activation_height"] == 1


def test_manifest_render_refuses_incomplete_decisions_without_writing(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "render-manifest"],
        cwd=tmp_path,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr.startswith(b"REFUSED: mainnet decisions are incomplete:")
    assert b"genesis_reward_policy_unset" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_manifest_render_emits_only_canonical_bytes_after_decisions(monkeypatch):
    cli = load_cli()
    profiles = cli.profiles
    monkeypatch.setattr(
        profiles,
        "MAINNET_GENESIS_TIMESTAMP",
        profiles.REHEARSAL_MAINNET_GENESIS_TIMESTAMP + 1,
    )
    monkeypatch.setattr(
        profiles,
        "MAINNET_GENESIS_ADDRESS",
        "wepo1q" + ("3" * 39),
    )
    monkeypatch.setattr(profiles, "MAINNET_GENESIS_FINALIZED", True)
    monkeypatch.setattr(
        profiles, "MAINNET_GENESIS_REWARD_POLICY", "auditable_distribution"
    )
    monkeypatch.setattr(profiles, "MAINNET_EMISSION_POLICY", "ceiling_only")
    monkeypatch.setattr(profiles, "MAINNET_COINBASE_MATURITY", 100)
    monkeypatch.setattr(profiles, "MAINNET_MINIMUM_RELAY_FEE_PER_KB", 1000)
    monkeypatch.setattr(profiles, "MAINNET_POS_DISPOSITION", "enabled")
    monkeypatch.setattr(profiles, "MAINNET_POS_CONSENSUS_READY", True)
    monkeypatch.setattr(profiles, "MAINNET_GHOST_DISPOSITION", "enabled")
    monkeypatch.setattr(profiles, "MAINNET_GHOST_CONSENSUS_READY", True)
    monkeypatch.setattr(profiles, "MAINNET_GHOST_ACTIVATION_HEIGHT", 1)
    monkeypatch.setattr(profiles, "MAINNET_PARAMETER_MANIFEST_SHA256", None)

    rendered = cli.render_manifest_for_freeze()
    profile = profiles.get_network_profile("mainnet")
    assert rendered == profiles.render_mainnet_parameter_manifest(profile)
    assert rendered.endswith(b"\n")
    assert b"\r" not in rendered
    document = json.loads(rendered)
    assert document == profiles.build_mainnet_parameter_manifest(profile)
    assert document["status"] == "finalized"
    assert document["parameters"]["coinbase_maturity_blocks"] == 100



def _set_complete_deferred_profile(profiles, monkeypatch, tmp_path):
    monkeypatch.setattr(
        profiles,
        "MAINNET_GENESIS_TIMESTAMP",
        profiles.REHEARSAL_MAINNET_GENESIS_TIMESTAMP + 1,
    )
    monkeypatch.setattr(
        profiles,
        "MAINNET_GENESIS_ADDRESS",
        "wepo1q" + ("4" * 39),
    )
    monkeypatch.setattr(profiles, "MAINNET_GENESIS_FINALIZED", True)
    monkeypatch.setattr(
        profiles, "MAINNET_GENESIS_REWARD_POLICY", "auditable_distribution"
    )
    monkeypatch.setattr(profiles, "MAINNET_EMISSION_POLICY", "ceiling_only")
    monkeypatch.setattr(profiles, "MAINNET_COINBASE_MATURITY", 100)
    monkeypatch.setattr(profiles, "MAINNET_MINIMUM_RELAY_FEE_PER_KB", 1000)
    monkeypatch.setattr(profiles, "MAINNET_POS_DISPOSITION", "enabled")
    monkeypatch.setattr(profiles, "MAINNET_POS_CONSENSUS_READY", True)
    monkeypatch.setattr(profiles, "MAINNET_GHOST_DISPOSITION", "enabled")
    monkeypatch.setattr(profiles, "MAINNET_GHOST_CONSENSUS_READY", True)
    monkeypatch.setattr(profiles, "MAINNET_GHOST_ACTIVATION_HEIGHT", 1)
    profile = profiles.get_network_profile("mainnet")
    manifest_path = tmp_path / "MAINNET_PARAMETER_MANIFEST.json"
    manifest_bytes = profiles.render_mainnet_parameter_manifest(profile)
    manifest_path.write_bytes(manifest_bytes)
    monkeypatch.setattr(
        profiles,
        "MAINNET_PARAMETER_MANIFEST_SHA256",
        hashlib.sha256(manifest_bytes).hexdigest(),
    )
    return manifest_path


def _write_valid_seed_inventory(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "format": "wepo-seed-node-inventory-v1",
                "network_profile": "test",
                "mainnet_genesis_finalized": False,
                "release_commit": "ab7ca8b8d2e26ac4b6d2534526ba3e7ac41952b2",
                "domain": {
                    "registrable_domain": "owned-wepo-domain.org",
                    "registrar_account_owner": "WEPO operations owner",
                    "mfa_recovery_controls": "hardware MFA plus sealed recovery codes",
                    "dns_provider": "reviewed DNS provider",
                    "operational_control_verified": True,
                    "api_fqdn": "api.owned-wepo-domain.org",
                    "seed_fqdns": [
                        "seed-a.owned-wepo-domain.org",
                        "seed-b.owned-wepo-domain.org",
                        "seed-c.owned-wepo-domain.org",
                    ],
                },
                "nodes": [
                    {
                        "role": "seed-a",
                        "provider": "DigitalOcean",
                        "failure_domain": "nyc3",
                        "public_ip": "1.1.1.1",
                        "p2p_port": 22567,
                        "api_bind": "127.0.0.1:8122",
                        "firewall_allows_tcp_22567": True,
                        "static_peers": ["8.8.8.8:22567", "9.9.9.9:22567"],
                        "external_tcp_probe": {
                            "status": "pass",
                            "observed_from": "observer-a",
                            "observed_at_utc": "2026-08-01T00:00:00Z",
                        },
                    },
                    {
                        "role": "seed-b",
                        "provider": "AWS",
                        "failure_domain": "us-east-1a",
                        "public_ip": "8.8.8.8",
                        "p2p_port": 22567,
                        "api_bind": "127.0.0.1:8122",
                        "firewall_allows_tcp_22567": True,
                        "static_peers": ["1.1.1.1:22567", "9.9.9.9:22567"],
                        "external_tcp_probe": {
                            "status": "pass",
                            "observed_from": "observer-b",
                            "observed_at_utc": "2026-08-01T00:01:00Z",
                        },
                    },
                    {
                        "role": "seed-c",
                        "provider": "IndependentVPS",
                        "failure_domain": "region-1",
                        "public_ip": "9.9.9.9",
                        "p2p_port": 22567,
                        "api_bind": "127.0.0.1:8122",
                        "firewall_allows_tcp_22567": True,
                        "static_peers": ["1.1.1.1:22567", "8.8.8.8:22567"],
                        "external_tcp_probe": {
                            "status": "pass",
                            "observed_from": "observer-c",
                            "observed_at_utc": "2026-08-01T00:02:00Z",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_valid_redis_evidence(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "format": "wepo-redis-outage-evidence-v1",
                "network_profile": "test",
                "mainnet_live_network": False,
                "release_commit": "ab7ca8b8d2e26ac4b6d2534526ba3e7ac41952b2",
                "backend_artifact_sha256": "0" * 64,
                "public_api_base_url": "https://api.owned-wepo-domain.org",
                "redis": {
                    "identity_redacted": "private-redis-alias-a",
                    "endpoint_visibility": "private-network",
                    "require_redis_rate_limit": True,
                    "startup_unavailable_fails_closed": True,
                },
                "drill": {
                    "change_approval_recorded": True,
                    "redis_only_endpoint_disrupted": True,
                    "backend_remained_running": True,
                    "normal_requests_before_outage_passed": True,
                    "global_rate_limited_route_during_outage": {
                        "route": "global_api",
                        "http_status": 429,
                        "returned_success": False,
                        "observed_at_utc": "2026-08-01T00:00:00Z",
                    },
                    "strict_endpoint_during_outage": {
                        "route": "wallet_create",
                        "http_status": 429,
                        "returned_success": False,
                        "observed_at_utc": "2026-08-01T00:01:00Z",
                    },
                    "no_successful_rate_limited_request_during_outage": True,
                    "recovery_after_restore_passed": True,
                    "unsafe_configuration_change_required": False,
                    "logs_redacted": True,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_valid_monitoring_evidence(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "format": "wepo-monitoring-evidence-v1",
                "network_profile": "test",
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
        ),
        encoding="utf-8",
    )


def _write_valid_backup_restore_evidence(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "format": "wepo-backup-restore-evidence-v1",
                "network_profile": "test",
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
        ),
        encoding="utf-8",
    )


def _write_complete_ops_evidence(tmp_path):
    seed_path = tmp_path / "seed-node-inventory.json"
    redis_path = tmp_path / "redis-outage-evidence.json"
    monitoring_path = tmp_path / "monitoring-evidence.json"
    backup_path = tmp_path / "backup-restore-evidence.json"
    _write_valid_seed_inventory(seed_path)
    _write_valid_redis_evidence(redis_path)
    _write_valid_monitoring_evidence(monitoring_path)
    _write_valid_backup_restore_evidence(backup_path)
    return seed_path, redis_path, monitoring_path, backup_path


def _status_with_ops(cli, manifest_path, ops_paths, readiness_path):
    seed_path, redis_path, monitoring_path, backup_path = ops_paths[:4]
    kwargs = {
        "seed_inventory_path": str(seed_path),
        "redis_outage_evidence_path": str(redis_path),
        "monitoring_evidence_path": str(monitoring_path),
        "backup_restore_evidence_path": str(backup_path),
        "readiness_package_path": str(readiness_path),
    }
    if len(ops_paths) == 6:
        kwargs["seven_day_rehearsal_evidence_path"] = str(ops_paths[4])
        kwargs["external_audit_package_path"] = str(ops_paths[5])
        kwargs["release_qualification_evidence_path"] = str(
            ops_paths[0].parent / "release-qualification-evidence.json"
        )
    return cli.status_document(str(manifest_path), **kwargs)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_release_commit(path: Path, release_commit: str) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    document["release_commit"] = release_commit
    path.write_text(json.dumps(document), encoding="utf-8")

def _write_valid_seven_day_rehearsal(
    path: Path,
    manifest_sha: str,
    *,
    seed_path: Path,
    redis_path: Path,
    monitoring_path: Path,
    backup_path: Path,
) -> None:
    document = {
        "format": "wepo-seven-day-rehearsal-evidence-v1",
        "network_profile": "release-candidate",
        "mainnet_live_network": False,
        "release_commit": "ab7ca8b8d2e26ac4b6d2534526ba3e7ac41952b2",
        "release_artifact_sha256": "1" * 64,
        "parameter_manifest_sha256": manifest_sha,
        "observation_window": {
            "started_at_utc": "2026-08-01T00:00:00Z",
            "ended_at_utc": "2026-08-08T00:00:00Z",
            "duration_hours": 168,
            "continuous_observation": True,
        },
        "summary": {
            "candidate_network_remained_available": True,
            "unexplained_consensus_divergence_count": 0,
            "unexplained_supply_mismatch_count": 0,
            "unresolved_critical_incident_count": 0,
            "irreversible_data_loss_count": 0,
        },
        "node_observations": [
            {
                "role": role,
                "fqdn": f"{role}.owned-wepo-domain.org",
                "failure_domain": failure_domain,
                "p2p_reachable_at_end": True,
                "start_height": 10,
                "final_height": 1010,
                "final_block_hash": "a" * 64,
                "availability_percent": 99.9,
            }
            for role, failure_domain in (
                ("seed-a", "digitalocean-nyc3"),
                ("seed-b", "aws-us-east-1a"),
                ("seed-c", "independent-vps-region-1"),
            )
        ],
        "drills": {
            "alert_delivery_passed": True,
            "backup_restore_passed": True,
            "redis_outage_passed": True,
            "hostile_traffic_passed": True,
            "restart_recovery_passed": True,
            "ghost_valid_transfer_passed": True,
            "ghost_invalid_proof_refused": True,
            "ghost_verifier_timeout_crash_refused": True,
            "ghost_wallet_backup_restore_recovery_passed": True,
            "pos_live_signing_passed": True,
            "pos_partition_reorg_passed": True,
            "validator_anti_equivocation_refused": True,
            "validator_signer_fencing_failover_passed": True,
        },
        "supporting_evidence": {
            "seed_node_inventory_sha256": _sha256(seed_path),
            "redis_outage_evidence_sha256": _sha256(redis_path),
            "monitoring_evidence_sha256": _sha256(monitoring_path),
            "backup_restore_evidence_sha256": _sha256(backup_path),
            "ghost_wallet_acceptance_sha256": "2" * 64,
            "ghost_verifier_host_qualification_sha256": "3" * 64,
            "pos_multinode_rehearsal_sha256": "4" * 64,
            "validator_signer_host_qualification_sha256": "5" * 64,
            "validator_fencing_failover_sha256": "6" * 64,
        },
        "retained_evidence": {
            "continuous_monitoring_log_sha256": "b" * 64,
            "chain_sample_log_sha256": "c" * 64,
            "incident_log_sha256": "d" * 64,
            "drill_log_sha256": "e" * 64,
            "logs_redacted": True,
        },
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def _write_valid_external_audit_package(path: Path, manifest_sha: str) -> None:
    audits = []
    for scope in ("protocol", "security", "wallet", "operations"):
        artifacts = {}
        for name in ("scope", "independence", "report", "signature-verification", "dispositions"):
            suffix = "json" if name in {"dispositions", "signature-verification"} else "pdf"
            relative = Path("reports") / f"{scope}-{name}.{suffix}"
            artifact = path.parent / relative
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(f"retained {scope} {name} artifact\n".encode("utf-8"))
            artifacts[name] = (relative.as_posix(), _sha256(artifact))
        audits.append(
            {
                "scope": scope,
                "auditor_organization": f"Independent {scope.title()} Review LLC",
                "engagement_id": f"WEPO-2026-{scope.upper()}",
                "independence_attested": True,
                "report_signature_verified": True,
                "report_access_classification": "retained-confidential",
                "completed_at_utc": "2026-08-01T00:00:00Z",
                "critical_total": 0,
                "critical_open": 0,
                "high_total": 1,
                "high_open": 0,
                "medium_total": 1,
                "medium_open": 0,
                "low_total": 1,
                "low_open": 1,
                "scope_document_file": artifacts["scope"][0],
                "scope_document_sha256": artifacts["scope"][1],
                "independence_attestation_file": artifacts["independence"][0],
                "independence_attestation_sha256": artifacts["independence"][1],
                "report_file": artifacts["report"][0],
                "report_sha256": artifacts["report"][1],
                "signature_verification_file": artifacts["signature-verification"][0],
                "signature_verification_sha256": artifacts["signature-verification"][1],
                "disposition_log_file": artifacts["dispositions"][0],
                "disposition_log_sha256": artifacts["dispositions"][1],
            }
        )
    document = {
        "format": "wepo-external-audit-package-v1",
        "network": "mainnet",
        "release_commit": "ab7ca8b8d2e26ac4b6d2534526ba3e7ac41952b2",
        "release_artifact_sha256": "1" * 64,
        "parameter_manifest_sha256": manifest_sha,
        "mandatory_feature_coverage": {
            "ghost": {
                "covered_by_scopes": ["protocol", "security", "wallet", "operations"],
                "air_and_proof_system_reviewed": True,
                "transaction_and_consensus_binding_reviewed": True,
                "wallet_prover_and_recovery_reviewed": True,
                "verifier_boundary_and_resource_limits_reviewed": True,
                "activation_and_bundle_policy_reviewed": True,
            },
            "proof_of_stake": {
                "covered_by_scopes": ["protocol", "security", "wallet", "operations"],
                "consensus_selection_and_reorg_reviewed": True,
                "validator_signer_protocol_reviewed": True,
                "stake_lifecycle_policy_reviewed": True,
                "anti_equivocation_and_fail_closed_state_reviewed": True,
                "separate_user_deployment_backup_and_failover_reviewed": True,
            },
        },
        "audits": audits,
        "operations_reviewed_bundle": True,
        "security_reviewed_bundle": True,
        "reviewed_at_utc": "2026-08-01T01:00:00Z",
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def _write_valid_release_qualification(path: Path, manifest_sha: str) -> None:
    retained_files = {}
    for name in (
        "source_archive",
        "signed_source_archive",
        "release_manifest",
        "release_manifest_signature",
        "release_signing_public_key",
        "signature_verification_record",
        "genesis_construction_transcript",
    ):
        relative = Path("qualification") / "artifacts" / f"{name}.txt"
        artifact = path.parent / relative
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(f"retained {name} artifact\n".encode("utf-8"))
        retained_files[f"{name}_file"] = relative.as_posix()
        retained_files[f"{name}_sha256"] = _sha256(artifact)

    artifacts = {
        name: path.parent / retained_files[f"{name}_file"]
        for name in (
            "release_manifest",
            "release_manifest_signature",
            "release_signing_public_key",
            "signature_verification_record",
        )
    }
    manifest_bytes = b"1" * 64 + b"  wepo-release-artifact.bin\n"
    artifacts["release_manifest"].write_bytes(manifest_bytes)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    artifacts["release_manifest_signature"].write_bytes(
        private_key.sign(manifest_bytes, padding.PKCS1v15(), hashes.SHA256())
    )
    artifacts["release_signing_public_key"].write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    artifacts["signature_verification_record"].write_text(
        json.dumps({"algorithm": "RSA-PKCS1v15-SHA256", "verified": True}),
        encoding="utf-8",
    )
    for name, artifact in artifacts.items():
        retained_files[f"{name}_sha256"] = _sha256(artifact)

    test_logs = {}
    for name in (
        "python_maintained_suite",
        "rust_release_all_targets",
        "frontend_vitest",
        "frontend_production_build",
        "desktop_package_boundary",
        "github_actions_green",
    ):
        relative = Path("qualification") / "logs" / f"{name}.log"
        log = path.parent / relative
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_bytes(f"PASS {name}\n".encode("utf-8"))
        test_logs[name] = {
            "status": "pass",
            "log_file": relative.as_posix(),
            "log_sha256": _sha256(log),
        }
    test_logs["python_maintained_suite"]["passed_count"] = 243
    document = {
        "format": "wepo-release-qualification-evidence-v1",
        "network": "mainnet",
        "release_commit": "ab7ca8b8d2e26ac4b6d2534526ba3e7ac41952b2",
        "release_artifact_sha256": "1" * 64,
        "parameter_manifest_sha256": manifest_sha,
        "clean_runner": True,
        "reproducible_source_archive": True,
        "release_manifest_signature_verified": True,
        "release_manifest_all_files_verified": True,
        "retained_files": retained_files,
        "test_logs": test_logs,
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def _write_complete_release_evidence(tmp_path, manifest_sha: str):
    ops_paths = _write_complete_ops_evidence(tmp_path)
    seed_path, redis_path, monitoring_path, backup_path = ops_paths
    rehearsal_path = tmp_path / "seven-day-rehearsal-evidence.json"
    audit_path = tmp_path / "external-audit-package.json"
    qualification_path = tmp_path / "release-qualification-evidence.json"
    _write_valid_seven_day_rehearsal(
        rehearsal_path,
        manifest_sha,
        seed_path=seed_path,
        redis_path=redis_path,
        monitoring_path=monitoring_path,
        backup_path=backup_path,
    )
    _write_valid_external_audit_package(audit_path, manifest_sha)
    _write_valid_release_qualification(qualification_path, manifest_sha)
    return (*ops_paths, rehearsal_path, audit_path)


def _write_valid_readiness_package(
    path: Path,
    manifest_sha: str,
    *,
    seed_path: Path,
    redis_path: Path,
    monitoring_path: Path,
    rehearsal_path: Path,
    audit_path: Path,
    backup_path: Path,
) -> None:
    release_commit = "ab7ca8b8d2e26ac4b6d2534526ba3e7ac41952b2"
    audit_document = json.loads(audit_path.read_text(encoding="utf-8"))
    qualification_path = path.parent / "release-qualification-evidence.json"
    qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
    retained_files = qualification["retained_files"]
    test_logs = qualification["test_logs"]
    package = {
        "format": "wepo-mainnet-readiness-decision-package-v1",
        "network": "mainnet",
        "release_commit": release_commit,
        "parameter_manifest_sha256": manifest_sha,
        "source_archive_sha256": retained_files["source_archive_sha256"],
        "signed_source_archive_sha256": retained_files["signed_source_archive_sha256"],
        "genesis_construction_transcript_sha256": retained_files["genesis_construction_transcript_sha256"],
        "release_signing_public_key_sha256": retained_files["release_signing_public_key_sha256"],
        "signed_release_artifacts": True,
        "automated_tests": {
            "python_maintained_suite": {
                "status": "pass",
                "passed_count": test_logs["python_maintained_suite"]["passed_count"],
                "evidence_ref": test_logs["python_maintained_suite"]["log_sha256"],
            },
            **{
                name: {"status": item["status"], "evidence_ref": item["log_sha256"]}
                for name, item in test_logs.items()
                if name != "python_maintained_suite"
            },
        },
        "seven_day_rehearsal": {
            "status": "pass",
            "duration_hours": 168,
            "no_unexplained_consensus_divergence": True,
            "evidence_sha256": _sha256(rehearsal_path),
        },
        "external_audits": [
            {"scope": item["scope"], "independent": True,
             "critical_and_high_closed": True,
             "report_sha256": item["report_sha256"]}
            for item in audit_document["audits"]
        ],
        "evidence_hashes": {
            "seed_node_inventory_sha256": _sha256(seed_path),
            "redis_outage_evidence_sha256": _sha256(redis_path),
            "monitoring_evidence_sha256": _sha256(monitoring_path),
            "backup_restore_evidence_sha256": _sha256(backup_path),
            "seven_day_rehearsal_evidence_sha256": _sha256(rehearsal_path),
            "external_audit_package_sha256": _sha256(audit_path),
            "release_qualification_evidence_sha256": _sha256(qualification_path),
        },
        "disabled_features": [
            {
                "feature": "mobile_wallets",
                "enforcement_points": ["MAINNET_V1_LAUNCH_SCOPE.md"],
                "client_claims_absent": True,
            }
        ],
        "public_claims_match_enforcement": True,
        "approvals": {
            role: {
                "decision": "GO",
                "approver": f"{role} owner",
                "release_commit": release_commit,
                "parameter_manifest_sha256": manifest_sha,
                "release_signing_public_key_sha256": retained_files["release_signing_public_key_sha256"],
                "approved_at_utc": "2026-08-01T00:00:00Z",
            }
            for role in ("protocol", "security", "wallet", "operations")
        },
    }
    path.write_text(json.dumps(package), encoding="utf-8")


def test_status_keeps_readiness_closed_until_ops_evidence_is_valid(monkeypatch, tmp_path):
    cli = load_cli()
    profiles = cli.profiles
    manifest_path = _set_complete_deferred_profile(profiles, monkeypatch, tmp_path)

    missing = cli.status_document(str(manifest_path))
    assert missing["ready"] is False
    assert missing["blockers"] == [
        "seed_node_inventory_evidence_missing",
        "redis_outage_evidence_missing",
        "monitoring_evidence_missing",
        "backup_restore_evidence_missing",
        "seven_day_rehearsal_evidence_missing",
        "external_audit_package_missing",
        "release_qualification_evidence_missing",
        "readiness_decision_package_missing",
    ]

    partial_paths = _write_complete_ops_evidence(tmp_path)
    seed_path, redis_path, monitoring_path, backup_path = partial_paths
    still_missing_package = cli.status_document(
        str(manifest_path),
        seed_inventory_path=str(seed_path),
        redis_outage_evidence_path=str(redis_path),
        monitoring_evidence_path=str(monitoring_path),
        backup_restore_evidence_path=str(backup_path),
    )
    assert still_missing_package["ready"] is False
    assert still_missing_package["blockers"] == [
        "seven_day_rehearsal_evidence_missing",
        "external_audit_package_missing",
        "release_qualification_evidence_missing",
        "readiness_decision_package_missing",
    ]

    ready_manifest_sha = cli.profiles.MAINNET_PARAMETER_MANIFEST_SHA256
    assert ready_manifest_sha is not None
    release_paths = _write_complete_release_evidence(tmp_path, ready_manifest_sha)
    seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
    readiness_path = tmp_path / "readiness-decision-package.json"
    _write_valid_readiness_package(
        readiness_path,
        ready_manifest_sha,
        seed_path=seed_path,
        redis_path=redis_path,
        monitoring_path=monitoring_path,
        backup_path=backup_path,
        rehearsal_path=rehearsal_path,
        audit_path=audit_path,
    )
    ready = _status_with_ops(cli, manifest_path, release_paths, readiness_path)
    assert ready["ready"] is True
    assert ready["blockers"] == []
    for kind in (
        "seed_node_inventory",
        "redis_outage",
        "monitoring",
        "backup_restore",
        "seven_day_rehearsal",
        "external_audit_package",
    ):
        assert ready["evidence"][kind]["status"] == "pass"
    assert ready["evidence"]["readiness_decision_package"]["status"] == "pass"


def test_status_rejects_readiness_package_for_wrong_manifest(monkeypatch, tmp_path):
    cli = load_cli()
    profiles = cli.profiles
    manifest_path = _set_complete_deferred_profile(profiles, monkeypatch, tmp_path)
    assert cli.profiles.MAINNET_PARAMETER_MANIFEST_SHA256 is not None
    release_paths = _write_complete_release_evidence(
        tmp_path, cli.profiles.MAINNET_PARAMETER_MANIFEST_SHA256
    )
    seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
    readiness_path = tmp_path / "readiness-decision-package.json"
    _write_valid_readiness_package(
        readiness_path,
        "1" * 64,
        seed_path=seed_path,
        redis_path=redis_path,
        monitoring_path=monitoring_path,
        backup_path=backup_path,
        rehearsal_path=rehearsal_path,
        audit_path=audit_path,
    )

    document = _status_with_ops(cli, manifest_path, release_paths, readiness_path)

    assert document["ready"] is False
    assert document["blockers"] == ["readiness_decision_package_manifest_mismatch"]
    assert document["evidence"]["readiness_decision_package"]["status"] == "invalid"


def test_status_rejects_readiness_package_for_different_ops_evidence(monkeypatch, tmp_path):
    cli = load_cli()
    profiles = cli.profiles
    manifest_path = _set_complete_deferred_profile(profiles, monkeypatch, tmp_path)
    assert cli.profiles.MAINNET_PARAMETER_MANIFEST_SHA256 is not None
    manifest_sha = cli.profiles.MAINNET_PARAMETER_MANIFEST_SHA256
    release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
    seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
    readiness_path = tmp_path / "readiness-decision-package.json"
    qualification_path = tmp_path / "release-qualification-evidence.json"
    cases = (
        (seed_path, "readiness_decision_package_seed_inventory_hash_mismatch"),
        (redis_path, "readiness_decision_package_redis_outage_hash_mismatch"),
        (monitoring_path, "readiness_decision_package_monitoring_hash_mismatch"),
        (backup_path, "readiness_decision_package_backup_restore_hash_mismatch"),
        (rehearsal_path, "readiness_decision_package_seven_day_rehearsal_hash_mismatch"),
        (audit_path, "readiness_decision_package_external_audit_package_hash_mismatch"),
        (qualification_path, "readiness_decision_package_release_qualification_hash_mismatch"),
    )
    for evidence_path, expected_blocker in cases:
        release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
        seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
        _write_valid_readiness_package(
            readiness_path,
            manifest_sha,
            seed_path=seed_path,
            redis_path=redis_path,
            monitoring_path=monitoring_path,
            backup_path=backup_path,
            rehearsal_path=rehearsal_path,
            audit_path=audit_path,
        )
        matching_path = (
            qualification_path
            if evidence_path.name == qualification_path.name
            else next(path for path in release_paths if path.name == evidence_path.name)
        )
        matching_path.write_text(
            matching_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
        )
        mismatch = _status_with_ops(cli, manifest_path, release_paths, readiness_path)
        assert mismatch["ready"] is False
        assert mismatch["blockers"] == [expected_blocker]

    release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
    seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
    monitoring = json.loads(monitoring_path.read_text(encoding="utf-8"))
    monitoring["node_observations"][0]["fqdn"] = "alternate.owned-wepo-domain.org"
    monitoring_path.write_text(json.dumps(monitoring), encoding="utf-8")
    _write_valid_readiness_package(
        readiness_path,
        manifest_sha,
        seed_path=seed_path,
        redis_path=redis_path,
        monitoring_path=monitoring_path,
        backup_path=backup_path,
        rehearsal_path=rehearsal_path,
        audit_path=audit_path,
    )
    mismatch = _status_with_ops(cli, manifest_path, release_paths, readiness_path)
    assert mismatch["blockers"] == [
        "readiness_decision_package_monitoring_seed_set_mismatch"
    ]
    release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
    seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
    rehearsal = json.loads(rehearsal_path.read_text(encoding="utf-8"))
    rehearsal["node_observations"][0]["fqdn"] = "alternate.owned-wepo-domain.org"
    rehearsal_path.write_text(json.dumps(rehearsal), encoding="utf-8")
    _write_valid_readiness_package(
        readiness_path,
        manifest_sha,
        seed_path=seed_path,
        redis_path=redis_path,
        monitoring_path=monitoring_path,
        backup_path=backup_path,
        rehearsal_path=rehearsal_path,
        audit_path=audit_path,
    )
    mismatch = _status_with_ops(cli, manifest_path, release_paths, readiness_path)
    assert mismatch["blockers"] == [
        "readiness_decision_package_rehearsal_seed_set_mismatch"
    ]


    release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
    seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    backup["release_artifact_sha256"] = "9" * 64
    backup_path.write_text(json.dumps(backup), encoding="utf-8")
    _write_valid_readiness_package(
        readiness_path,
        manifest_sha,
        seed_path=seed_path,
        redis_path=redis_path,
        monitoring_path=monitoring_path,
        backup_path=backup_path,
        rehearsal_path=rehearsal_path,
        audit_path=audit_path,
    )
    mismatch = _status_with_ops(cli, manifest_path, release_paths, readiness_path)
    assert mismatch["blockers"] == ["readiness_decision_package_ops_artifact_hash_mismatch"]

    release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
    seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
    rehearsal = json.loads(rehearsal_path.read_text(encoding="utf-8"))
    rehearsal["release_artifact_sha256"] = "9" * 64
    rehearsal_path.write_text(json.dumps(rehearsal), encoding="utf-8")
    _write_valid_readiness_package(
        readiness_path, manifest_sha, seed_path=seed_path, redis_path=redis_path,
        monitoring_path=monitoring_path, backup_path=backup_path,
        rehearsal_path=rehearsal_path, audit_path=audit_path,
    )
    mismatch = _status_with_ops(cli, manifest_path, release_paths, readiness_path)
    assert mismatch["blockers"] == [
        "readiness_decision_package_candidate_artifact_mismatch"
    ]

    release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
    seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
    audit_document = json.loads(audit_path.read_text(encoding="utf-8"))
    audit_document["parameter_manifest_sha256"] = "9" * 64
    audit_path.write_text(json.dumps(audit_document), encoding="utf-8")
    _write_valid_readiness_package(
        readiness_path, manifest_sha, seed_path=seed_path, redis_path=redis_path,
        monitoring_path=monitoring_path, backup_path=backup_path,
        rehearsal_path=rehearsal_path, audit_path=audit_path,
    )
    mismatch = _status_with_ops(cli, manifest_path, release_paths, readiness_path)
    assert mismatch["blockers"] == [
        "readiness_decision_package_candidate_manifest_mismatch"
    ]

    release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
    seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
    rehearsal = json.loads(rehearsal_path.read_text(encoding="utf-8"))
    rehearsal["supporting_evidence"]["seed_node_inventory_sha256"] = "f" * 64
    rehearsal_path.write_text(json.dumps(rehearsal), encoding="utf-8")
    _write_valid_readiness_package(
        readiness_path, manifest_sha, seed_path=seed_path, redis_path=redis_path,
        monitoring_path=monitoring_path, backup_path=backup_path,
        rehearsal_path=rehearsal_path, audit_path=audit_path,
    )
    mismatch = _status_with_ops(cli, manifest_path, release_paths, readiness_path)
    assert mismatch["blockers"] == [
        "readiness_decision_package_rehearsal_supporting_hash_mismatch"
    ]

    release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
    seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
    _write_valid_readiness_package(
        readiness_path, manifest_sha, seed_path=seed_path, redis_path=redis_path,
        monitoring_path=monitoring_path, backup_path=backup_path,
        rehearsal_path=rehearsal_path, audit_path=audit_path,
    )
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    readiness["external_audits"][0]["report_sha256"] = "f" * 64
    readiness_path.write_text(json.dumps(readiness), encoding="utf-8")
    mismatch = _status_with_ops(cli, manifest_path, release_paths, readiness_path)
    assert mismatch["blockers"] == [
        "readiness_decision_package_external_audit_summary_mismatch"
    ]

    release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
    seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
    _write_valid_readiness_package(
        readiness_path, manifest_sha, seed_path=seed_path, redis_path=redis_path,
        monitoring_path=monitoring_path, backup_path=backup_path,
        rehearsal_path=rehearsal_path, audit_path=audit_path,
    )
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    readiness["source_archive_sha256"] = "f" * 64
    readiness_path.write_text(json.dumps(readiness), encoding="utf-8")
    mismatch = _status_with_ops(cli, manifest_path, release_paths, readiness_path)
    assert mismatch["blockers"] == [
        "readiness_decision_package_release_artifact_summary_mismatch"
    ]

    release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
    seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
    _write_valid_readiness_package(
        readiness_path, manifest_sha, seed_path=seed_path, redis_path=redis_path,
        monitoring_path=monitoring_path, backup_path=backup_path,
        rehearsal_path=rehearsal_path, audit_path=audit_path,
    )
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    readiness["automated_tests"]["frontend_vitest"]["evidence_ref"] = "f" * 64
    readiness_path.write_text(json.dumps(readiness), encoding="utf-8")
    mismatch = _status_with_ops(cli, manifest_path, release_paths, readiness_path)
    assert mismatch["blockers"] == [
        "readiness_decision_package_release_test_summary_mismatch"
    ]

    release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
    seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
    qualification_path = tmp_path / "release-qualification-evidence.json"
    qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
    qualification["release_artifact_sha256"] = "9" * 64
    qualification_path.write_text(json.dumps(qualification), encoding="utf-8")
    _write_valid_readiness_package(
        readiness_path, manifest_sha, seed_path=seed_path, redis_path=redis_path,
        monitoring_path=monitoring_path, backup_path=backup_path,
        rehearsal_path=rehearsal_path, audit_path=audit_path,
    )
    mismatch = _status_with_ops(cli, manifest_path, release_paths, readiness_path)
    assert mismatch["blockers"] == [
        "readiness_decision_package_candidate_artifact_mismatch"
    ]


def test_status_rejects_readiness_package_for_mixed_release_commits(monkeypatch, tmp_path):
    cli = load_cli()
    profiles = cli.profiles
    manifest_path = _set_complete_deferred_profile(profiles, monkeypatch, tmp_path)
    assert cli.profiles.MAINNET_PARAMETER_MANIFEST_SHA256 is not None
    manifest_sha = cli.profiles.MAINNET_PARAMETER_MANIFEST_SHA256
    release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
    seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
    readiness_path = tmp_path / "readiness-decision-package.json"
    qualification_path = tmp_path / "release-qualification-evidence.json"
    cases = (
        (seed_path, "readiness_decision_package_seed_inventory_commit_mismatch"),
        (redis_path, "readiness_decision_package_redis_outage_commit_mismatch"),
        (monitoring_path, "readiness_decision_package_monitoring_commit_mismatch"),
        (backup_path, "readiness_decision_package_backup_restore_commit_mismatch"),
        (rehearsal_path, "readiness_decision_package_seven_day_rehearsal_commit_mismatch"),
        (audit_path, "readiness_decision_package_external_audit_package_commit_mismatch"),
        (qualification_path, "readiness_decision_package_release_qualification_commit_mismatch"),
    )
    for index, (evidence_path, expected_blocker) in enumerate(cases):
        release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
        seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
        matching_path = (
            qualification_path
            if evidence_path.name == qualification_path.name
            else next(path for path in release_paths if path.name == evidence_path.name)
        )
        _rewrite_release_commit(matching_path, str(index + 1) * 40)
        _write_valid_readiness_package(
            readiness_path,
            manifest_sha,
            seed_path=seed_path,
            redis_path=redis_path,
            monitoring_path=monitoring_path,
            backup_path=backup_path,
            rehearsal_path=rehearsal_path,
            audit_path=audit_path,
        )
        mismatch = _status_with_ops(cli, manifest_path, release_paths, readiness_path)
        assert mismatch["ready"] is False
        assert mismatch["blockers"] == [expected_blocker]


def test_status_reports_invalid_ops_evidence(monkeypatch, tmp_path):
    cli = load_cli()
    profiles = cli.profiles
    manifest_path = _set_complete_deferred_profile(profiles, monkeypatch, tmp_path)
    assert cli.profiles.MAINNET_PARAMETER_MANIFEST_SHA256 is not None
    manifest_sha = cli.profiles.MAINNET_PARAMETER_MANIFEST_SHA256
    release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
    seed_path = release_paths[0]
    seed_path.write_text('{"format":"wrong"}', encoding="utf-8")

    document = _status_with_ops(
        cli,
        manifest_path,
        release_paths,
        tmp_path / "missing-readiness-package.json",
    )

    assert document["ready"] is False
    assert document["blockers"] == [
        "seed_node_inventory_evidence_invalid",
        "readiness_decision_package_missing",
    ]
    assert document["evidence"]["seed_node_inventory"]["status"] == "invalid"

    release_paths = _write_complete_release_evidence(tmp_path, manifest_sha)
    seed_path, redis_path, monitoring_path, backup_path, rehearsal_path, audit_path = release_paths
    readiness_path = tmp_path / "readiness-decision-package.json"
    _write_valid_readiness_package(
        readiness_path,
        manifest_sha,
        seed_path=seed_path,
        redis_path=redis_path,
        monitoring_path=monitoring_path,
        backup_path=backup_path,
        rehearsal_path=rehearsal_path,
        audit_path=audit_path,
    )
    document = cli.status_document(
        str(manifest_path),
        seed_inventory_path=str(seed_path),
        redis_outage_evidence_path=str(redis_path),
        monitoring_evidence_path=str(tmp_path / "missing-monitoring.json"),
        backup_restore_evidence_path=str(backup_path),
        seven_day_rehearsal_evidence_path=str(rehearsal_path),
        external_audit_package_path=str(audit_path),
        release_qualification_evidence_path=str(tmp_path / "release-qualification-evidence.json"),
        readiness_package_path=str(readiness_path),
    )
    assert document["ready"] is False
    assert document["blockers"] == ["monitoring_evidence_missing"]
