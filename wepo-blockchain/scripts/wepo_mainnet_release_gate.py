#!/usr/bin/env python3
"""Read-only status and canonical-manifest output for the mainnet release gate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


CORE = Path(__file__).resolve().parents[1] / "core"
sys.path.insert(0, str(CORE))

import network_profile as profiles  # noqa: E402


MANIFEST_BLOCKER_PREFIX = "parameter_manifest_"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT = REPO_ROOT / "wepo-production-deployment"
EVIDENCE_VALIDATORS = {
    "seed_node_inventory": (
        DEPLOYMENT / "verify-seed-node-inventory.py",
        "--inventory",
        "seed_node_inventory_evidence_missing",
        "seed_node_inventory_evidence_invalid",
    ),
    "redis_outage": (
        DEPLOYMENT / "verify-redis-outage-evidence.py",
        "--evidence",
        "redis_outage_evidence_missing",
        "redis_outage_evidence_invalid",
    ),
    "monitoring": (
        DEPLOYMENT / "verify-monitoring-evidence.py",
        "--evidence",
        "monitoring_evidence_missing",
        "monitoring_evidence_invalid",
    ),
    "backup_restore": (
        DEPLOYMENT / "verify-backup-restore-evidence.py",
        "--evidence",
        "backup_restore_evidence_missing",
        "backup_restore_evidence_invalid",
    ),
    "seven_day_rehearsal": (
        DEPLOYMENT / "verify-seven-day-rehearsal-evidence.py",
        "--evidence",
        "seven_day_rehearsal_evidence_missing",
        "seven_day_rehearsal_evidence_invalid",
    ),
    "external_audit_package": (
        DEPLOYMENT / "verify-external-audit-package.py",
        "--package",
        "external_audit_package_missing",
        "external_audit_package_invalid",
    ),
    "release_qualification": (
        DEPLOYMENT / "verify-release-qualification-evidence.py",
        "--evidence",
        "release_qualification_evidence_missing",
        "release_qualification_evidence_invalid",
    ),
    "readiness_decision_package": (
        DEPLOYMENT / "verify-readiness-decision-package.py",
        "--package",
        "readiness_decision_package_missing",
        "readiness_decision_package_invalid",
    ),
}


def _validate_evidence(kind: str, path: str | None) -> tuple[str | None, dict[str, str | None]]:
    validator, argument, missing_blocker, invalid_blocker = EVIDENCE_VALIDATORS[kind]
    result: dict[str, str | None] = {
        "path": path,
        "status": "missing" if path is None else "unchecked",
        "error": None,
    }
    if path is None:
        return missing_blocker, result
    evidence_path = Path(path)
    if not evidence_path.is_file():
        result["status"] = "missing"
        result["error"] = f"not a file: {path}"
        return missing_blocker, result
    completed = subprocess.run(
        [sys.executable, str(validator), argument, str(evidence_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        result["status"] = "invalid"
        result["error"] = (completed.stderr or completed.stdout).strip()
        return invalid_blocker, result
    result["status"] = "pass"
    return None, result


def evidence_blockers(
    *,
    seed_inventory_path: str | None = None,
    redis_outage_evidence_path: str | None = None,
    monitoring_evidence_path: str | None = None,
    backup_restore_evidence_path: str | None = None,
    seven_day_rehearsal_evidence_path: str | None = None,
    external_audit_package_path: str | None = None,
    release_qualification_evidence_path: str | None = None,
    readiness_package_path: str | None = None,
) -> tuple[list[str], dict[str, dict[str, str | None]]]:
    blockers: list[str] = []
    evidence: dict[str, dict[str, str | None]] = {}
    for kind, path in (
        ("seed_node_inventory", seed_inventory_path),
        ("redis_outage", redis_outage_evidence_path),
        ("monitoring", monitoring_evidence_path),
        ("backup_restore", backup_restore_evidence_path),
        ("seven_day_rehearsal", seven_day_rehearsal_evidence_path),
        ("external_audit_package", external_audit_package_path),
        ("release_qualification", release_qualification_evidence_path),
        ("readiness_decision_package", readiness_package_path),
    ):
        blocker, result = _validate_evidence(kind, path)
        evidence[kind] = result
        if blocker is not None:
            blockers.append(blocker)
    return blockers, evidence


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path) -> dict | None:
    with path.open("r", encoding="utf-8") as source:
        document = json.load(source)
    if not isinstance(document, dict):
        return None
    return document


def _bind_readiness_package(
    *,
    readiness_package_path: str | None,
    seed_inventory_path: str | None,
    redis_outage_evidence_path: str | None,
    monitoring_evidence_path: str | None,
    backup_restore_evidence_path: str | None,
    evidence: dict[str, dict[str, str | None]],
    seven_day_rehearsal_evidence_path: str | None,
    external_audit_package_path: str | None,
    release_qualification_evidence_path: str | None,
    expected_manifest_sha256: str | None,
) -> str | None:
    if readiness_package_path is None:
        return None
    result = evidence.get("readiness_decision_package")
    if not result or result.get("status") != "pass" or not expected_manifest_sha256:
        return None
    with Path(readiness_package_path).open("r", encoding="utf-8") as source:
        package = json.load(source)
    if not isinstance(package, dict):
        result["status"] = "invalid"
        result["error"] = "readiness package root must be an object"
        return "readiness_decision_package_invalid"
    release_commit = package.get("release_commit")
    if not isinstance(release_commit, str) or not release_commit.strip():
        result["status"] = "invalid"
        result["error"] = "readiness package release_commit must be a non-empty string"
        return "readiness_decision_package_invalid"
    result["release_commit"] = release_commit
    actual = package.get("parameter_manifest_sha256")
    if actual != expected_manifest_sha256:
        result["status"] = "invalid"
        result["error"] = "readiness package manifest hash does not match the evaluated mainnet parameter manifest"
        return "readiness_decision_package_manifest_mismatch"
    result["parameter_manifest_sha256"] = actual
    evidence_hashes = package.get("evidence_hashes")
    if not isinstance(evidence_hashes, dict):
        result["status"] = "invalid"
        result["error"] = "readiness package evidence_hashes must be an object"
        return "readiness_decision_package_invalid"
    for kind, key, supplied_path, blocker in (
        (
            "seed_node_inventory",
            "seed_node_inventory_sha256",
            seed_inventory_path,
            "readiness_decision_package_seed_inventory_hash_mismatch",
        ),
        (
            "redis_outage",
            "redis_outage_evidence_sha256",
            redis_outage_evidence_path,
            "readiness_decision_package_redis_outage_hash_mismatch",
        ),
        (
            "monitoring",
            "monitoring_evidence_sha256",
            monitoring_evidence_path,
            "readiness_decision_package_monitoring_hash_mismatch",
        ),
        (
            "backup_restore",
            "backup_restore_evidence_sha256",
            backup_restore_evidence_path,
            "readiness_decision_package_backup_restore_hash_mismatch",
        ),
        (
            "seven_day_rehearsal",
            "seven_day_rehearsal_evidence_sha256",
            seven_day_rehearsal_evidence_path,
            "readiness_decision_package_seven_day_rehearsal_hash_mismatch",
        ),
        (
            "external_audit_package",
            "external_audit_package_sha256",
            external_audit_package_path,
            "readiness_decision_package_external_audit_package_hash_mismatch",
        ),
        (
            "release_qualification",
            "release_qualification_evidence_sha256",
            release_qualification_evidence_path,
            "readiness_decision_package_release_qualification_hash_mismatch",
        ),
    ):
        if supplied_path is None or evidence.get(kind, {}).get("status") != "pass":
            continue
        expected = evidence_hashes.get(key)
        actual_hash = _sha256(Path(supplied_path))
        if expected != actual_hash:
            result["status"] = "invalid"
            result["error"] = f"readiness package {key} does not match supplied evidence file"
            return blocker
        result[key] = actual_hash
    bound_documents: dict[str, dict] = {}
    for kind, supplied_path, blocker in (
        (
            "seed_node_inventory",
            seed_inventory_path,
            "readiness_decision_package_seed_inventory_commit_mismatch",
        ),
        (
            "redis_outage",
            redis_outage_evidence_path,
            "readiness_decision_package_redis_outage_commit_mismatch",
        ),
        (
            "monitoring",
            monitoring_evidence_path,
            "readiness_decision_package_monitoring_commit_mismatch",
        ),
        (
            "backup_restore",
            backup_restore_evidence_path,
            "readiness_decision_package_backup_restore_commit_mismatch",
        ),
        (
            "seven_day_rehearsal",
            seven_day_rehearsal_evidence_path,
            "readiness_decision_package_seven_day_rehearsal_commit_mismatch",
        ),
        (
            "external_audit_package",
            external_audit_package_path,
            "readiness_decision_package_external_audit_package_commit_mismatch",
        ),
        (
            "release_qualification",
            release_qualification_evidence_path,
            "readiness_decision_package_release_qualification_commit_mismatch",
        ),
    ):
        if supplied_path is None or evidence.get(kind, {}).get("status") != "pass":
            continue
        supplied = _load_json_object(Path(supplied_path))
        if supplied is None:
            result["status"] = "invalid"
            result["error"] = f"supplied {kind} evidence root must be an object"
            return "readiness_decision_package_invalid"
        if supplied.get("release_commit") != release_commit:
            result["status"] = "invalid"
            result["error"] = (
                "readiness package release_commit does not match supplied "
                f"{kind} evidence"
            )
            return blocker
        bound_documents[kind] = supplied

    seed = bound_documents.get("seed_node_inventory")
    monitoring = bound_documents.get("monitoring")
    if seed is not None and monitoring is not None:
        seed_roles = {
            item.get("role")
            for item in seed.get("nodes", [])
            if isinstance(item, dict)
        }
        monitoring_roles = {
            item.get("role")
            for item in monitoring.get("node_observations", [])
            if isinstance(item, dict)
        }
        domain = seed.get("domain")
        seed_fqdns = {
            item.lower().rstrip(".")
            for item in domain.get("seed_fqdns", [])
            if isinstance(domain, dict) and isinstance(item, str)
        }
        monitoring_fqdns = {
            item.get("fqdn", "").lower().rstrip(".")
            for item in monitoring.get("node_observations", [])
            if isinstance(item, dict) and isinstance(item.get("fqdn"), str)
        }
        if seed_roles != monitoring_roles or seed_fqdns != monitoring_fqdns:
            result["status"] = "invalid"
            result["error"] = "monitoring evidence does not cover the selected seed inventory"
            return "readiness_decision_package_monitoring_seed_set_mismatch"

    backup = bound_documents.get("backup_restore")
    if monitoring is not None and backup is not None:
        if monitoring.get("release_artifact_sha256") != backup.get("release_artifact_sha256"):
            result["status"] = "invalid"
            result["error"] = "monitoring and backup/restore evidence use different release artifacts"
            return "readiness_decision_package_ops_artifact_hash_mismatch"
    rehearsal = bound_documents.get("seven_day_rehearsal")
    if seed is not None and rehearsal is not None:
        seed_roles = {
            item.get("role")
            for item in seed.get("nodes", [])
            if isinstance(item, dict)
        }
        rehearsal_roles = {
            item.get("role")
            for item in rehearsal.get("node_observations", [])
            if isinstance(item, dict)
        }
        domain = seed.get("domain")
        seed_fqdns = {
            item.lower().rstrip(".")
            for item in domain.get("seed_fqdns", [])
            if isinstance(domain, dict) and isinstance(item, str)
        }
        rehearsal_fqdns = {
            item.get("fqdn", "").lower().rstrip(".")
            for item in rehearsal.get("node_observations", [])
            if isinstance(item, dict) and isinstance(item.get("fqdn"), str)
        }
        if seed_roles != rehearsal_roles or seed_fqdns != rehearsal_fqdns:
            result["status"] = "invalid"
            result["error"] = "seven-day rehearsal does not cover the selected seed inventory"
            return "readiness_decision_package_rehearsal_seed_set_mismatch"
    audit_package = bound_documents.get("external_audit_package")
    release_qualification = bound_documents.get("release_qualification")
    candidate_documents = [
        item for item in (monitoring, backup, rehearsal, audit_package, release_qualification) if item is not None
    ]
    candidate_artifacts = {
        item.get("release_artifact_sha256") for item in candidate_documents
    }
    if len(candidate_artifacts) > 1:
        result["status"] = "invalid"
        result["error"] = "operations, rehearsal, and audit evidence use different release artifacts"
        return "readiness_decision_package_candidate_artifact_mismatch"
    for kind, item in (
        ("seven-day rehearsal", rehearsal),
        ("external audit", audit_package),
        ("release qualification", release_qualification),
    ):
        if item is not None and item.get("parameter_manifest_sha256") != actual:
            result["status"] = "invalid"
            result["error"] = f"{kind} evidence does not match the parameter manifest"
            return "readiness_decision_package_candidate_manifest_mismatch"

    if rehearsal is not None:
        supporting = rehearsal.get("supporting_evidence")
        if not isinstance(supporting, dict):
            result["status"] = "invalid"
            result["error"] = "seven-day rehearsal supporting_evidence must be an object"
            return "readiness_decision_package_invalid"
        for key, path, kind in (
            ("seed_node_inventory_sha256", seed_inventory_path, "seed_node_inventory"),
            ("redis_outage_evidence_sha256", redis_outage_evidence_path, "redis_outage"),
            ("monitoring_evidence_sha256", monitoring_evidence_path, "monitoring"),
            ("backup_restore_evidence_sha256", backup_restore_evidence_path, "backup_restore"),
        ):
            if path is None or evidence.get(kind, {}).get("status") != "pass":
                continue
            if supporting.get(key) != _sha256(Path(path)):
                result["status"] = "invalid"
                result["error"] = f"seven-day rehearsal {key} does not match supplied evidence"
                return "readiness_decision_package_rehearsal_supporting_hash_mismatch"

    if audit_package is not None:
        package_audits = package.get("external_audits")
        retained_audits = audit_package.get("audits")
        if not isinstance(package_audits, list) or not isinstance(retained_audits, list):
            result["status"] = "invalid"
            result["error"] = "audit summaries must be lists"
            return "readiness_decision_package_invalid"
        package_reports = {
            item.get("scope"): item.get("report_sha256")
            for item in package_audits
            if isinstance(item, dict)
        }
        retained_reports = {
            item.get("scope"): item.get("report_sha256")
            for item in retained_audits
            if isinstance(item, dict)
        }
        if package_reports != retained_reports:
            result["status"] = "invalid"
            result["error"] = "readiness audit summaries do not match retained audit reports"
            return "readiness_decision_package_external_audit_summary_mismatch"

    if release_qualification is not None:
        retained_files = release_qualification.get("retained_files")
        if not isinstance(retained_files, dict):
            result["status"] = "invalid"
            result["error"] = "release qualification retained_files must be an object"
            return "readiness_decision_package_invalid"
        artifact_summary = {
            "source_archive_sha256": retained_files.get("source_archive_sha256"),
            "signed_source_archive_sha256": retained_files.get("signed_source_archive_sha256"),
            "genesis_construction_transcript_sha256": retained_files.get("genesis_construction_transcript_sha256"),
            "release_signing_public_key_sha256": retained_files.get("release_signing_public_key_sha256"),
        }
        if any(package.get(key) != value for key, value in artifact_summary.items()):
            result["status"] = "invalid"
            result["error"] = "readiness release artifact summaries do not match retained qualification artifacts"
            return "readiness_decision_package_release_artifact_summary_mismatch"
        if not package.get("signed_release_artifacts") or not release_qualification.get(
            "release_manifest_signature_verified"
        ) or not release_qualification.get("release_manifest_all_files_verified"):
            result["status"] = "invalid"
            result["error"] = "readiness signed artifact summary does not match qualification evidence"
            return "readiness_decision_package_release_artifact_summary_mismatch"
        package_tests = package.get("automated_tests")
        retained_tests = release_qualification.get("test_logs")
        if not isinstance(package_tests, dict) or not isinstance(retained_tests, dict):
            result["status"] = "invalid"
            result["error"] = "release test summaries must be objects"
            return "readiness_decision_package_invalid"
        if set(package_tests) != set(retained_tests):
            result["status"] = "invalid"
            result["error"] = "readiness test surfaces do not match release qualification"
            return "readiness_decision_package_release_test_summary_mismatch"
        for name, retained in retained_tests.items():
            summary = package_tests.get(name)
            if not isinstance(summary, dict) or not isinstance(retained, dict):
                result["status"] = "invalid"
                result["error"] = "release test summaries must be objects"
                return "readiness_decision_package_release_test_summary_mismatch"
            if summary.get("status") != retained.get("status") or summary.get(
                "evidence_ref"
            ) != retained.get("log_sha256"):
                result["status"] = "invalid"
                result["error"] = (
                    f"readiness test summary does not match retained log: {name}"
                )
                return "readiness_decision_package_release_test_summary_mismatch"
            if name == "python_maintained_suite" and summary.get(
                "passed_count"
            ) != retained.get("passed_count"):
                result["status"] = "invalid"
                result["error"] = (
                    "readiness Python test count does not match retained qualification log"
                )
                return "readiness_decision_package_release_test_summary_mismatch"

    return None

def status_document(

    manifest_path: str | None = None,
    *,
    seed_inventory_path: str | None = None,
    redis_outage_evidence_path: str | None = None,
    monitoring_evidence_path: str | None = None,
    backup_restore_evidence_path: str | None = None,
    readiness_package_path: str | None = None,
    seven_day_rehearsal_evidence_path: str | None = None,
    external_audit_package_path: str | None = None,
    release_qualification_evidence_path: str | None = None,
) -> dict:
    profile = profiles.get_network_profile("mainnet")
    decision_blockers = list(profiles.mainnet_release_blockers(profile, manifest_path))
    ops_blockers, evidence = evidence_blockers(
        seed_inventory_path=seed_inventory_path,
        redis_outage_evidence_path=redis_outage_evidence_path,
        monitoring_evidence_path=monitoring_evidence_path,
        backup_restore_evidence_path=backup_restore_evidence_path,
        readiness_package_path=readiness_package_path,
        seven_day_rehearsal_evidence_path=seven_day_rehearsal_evidence_path,
        external_audit_package_path=external_audit_package_path,
        release_qualification_evidence_path=release_qualification_evidence_path,
    )
    binding_blocker = _bind_readiness_package(
        readiness_package_path=readiness_package_path,
        seed_inventory_path=seed_inventory_path,
        redis_outage_evidence_path=redis_outage_evidence_path,
        monitoring_evidence_path=monitoring_evidence_path,
        backup_restore_evidence_path=backup_restore_evidence_path,
        seven_day_rehearsal_evidence_path=seven_day_rehearsal_evidence_path,
        external_audit_package_path=external_audit_package_path,
        release_qualification_evidence_path=release_qualification_evidence_path,
        evidence=evidence,
        expected_manifest_sha256=profiles.MAINNET_PARAMETER_MANIFEST_SHA256,
    )
    blockers = decision_blockers + ops_blockers
    if binding_blocker is not None:
        blockers.append(binding_blocker)
    return {
        "schema": "wepo-mainnet-release-gate-status-v1",
        "network": "mainnet",
        "ready": not blockers,
        "blockers": list(blockers),
        "decisions": {
            "genesis_finalized": profile.genesis_finalized,
            "genesis_reward_policy": profiles.MAINNET_GENESIS_REWARD_POLICY,
            "emission_policy": profiles.MAINNET_EMISSION_POLICY,
            "coinbase_maturity_blocks": profile.coinbase_maturity,
            "minimum_relay_fee_per_kb_atomic": profile.minimum_relay_fee_per_kb,
            "pos_disposition": profiles.MAINNET_POS_DISPOSITION,
            "pos_consensus_ready": profile.pos_consensus_ready,
            "rwa_disposition": profiles.MAINNET_RWA_DISPOSITION,
            "rwa_consensus_ready": profile.rwa_consensus_ready,
            "messaging_disposition": profiles.MAINNET_MESSAGING_DISPOSITION,
            "messaging_consensus_ready": profile.messaging_consensus_ready,
            "ghost_disposition": profiles.MAINNET_GHOST_DISPOSITION,
            "ghost_consensus_ready": profiles.MAINNET_GHOST_CONSENSUS_READY,
            "ghost_activation_height": profiles.MAINNET_GHOST_ACTIVATION_HEIGHT,
            "parameter_manifest_sha256": profiles.MAINNET_PARAMETER_MANIFEST_SHA256,
        },
        "evidence": evidence,
    }


def render_manifest_for_freeze() -> bytes:
    """Render only after every non-manifest decision blocker is closed."""
    profile = profiles.get_network_profile("mainnet")
    blockers = profiles.mainnet_release_blockers(profile)
    decision_blockers = [
        blocker
        for blocker in blockers
        if not blocker.startswith(MANIFEST_BLOCKER_PREFIX)
    ]
    if decision_blockers:
        raise RuntimeError(
            "mainnet decisions are incomplete: " + ", ".join(decision_blockers)
        )
    return profiles.render_mainnet_parameter_manifest(profile)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect WEPO's fail-closed mainnet decision gate or emit the exact "
            "manifest bytes to stdout. This command never edits a file."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser(
        "status", help="print structured gate status as JSON"
    )
    status.add_argument(
        "--manifest",
        help=(
            "manifest path to verify instead of the release-root default; useful "
            "during an operator-reviewed freeze ceremony"
        ),
    )
    status.add_argument(
        "--seed-inventory",
        help=(
            "filled seed-node inventory JSON validated by "
            "verify-seed-node-inventory.py"
        ),
    )
    status.add_argument(
        "--redis-outage-evidence",
        help=(
            "filled Redis outage evidence JSON validated by "
            "verify-redis-outage-evidence.py"
        ),
    )
    status.add_argument(
        "--monitoring-evidence",
        help=(
            "filled monitoring evidence JSON validated by "
            "verify-monitoring-evidence.py"
        ),
    )
    status.add_argument(
        "--backup-restore-evidence",
        help=(
            "filled backup/restore evidence JSON validated by "
            "verify-backup-restore-evidence.py"
        ),
    )
    status.add_argument(
        "--readiness-package",
        help=(
            "filled readiness decision package JSON validated by "
            "verify-readiness-decision-package.py"
        ),
    )

    status.add_argument(
        "--seven-day-rehearsal-evidence",
        help=(
            "filled seven-day rehearsal evidence JSON validated by "
            "verify-seven-day-rehearsal-evidence.py"
        ),
    )
    status.add_argument(
        "--external-audit-package",
        help=(
            "filled external-audit package JSON and adjacent retained files "
            "validated by verify-external-audit-package.py"
        ),
    )
    status.add_argument(
        "--release-qualification-evidence",
        help=(
            "filled retained release qualification JSON and adjacent artifacts "
            "validated by verify-release-qualification-evidence.py"
        ),
    )

    subparsers.add_parser(
        "render-manifest",
        help=(
            "write canonical manifest bytes to stdout only when every non-manifest "
            "decision blocker is closed"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "status":
        document = status_document(
            args.manifest,
            seed_inventory_path=args.seed_inventory,
            redis_outage_evidence_path=args.redis_outage_evidence,
            seven_day_rehearsal_evidence_path=args.seven_day_rehearsal_evidence,
            external_audit_package_path=args.external_audit_package,
            release_qualification_evidence_path=args.release_qualification_evidence,
            monitoring_evidence_path=args.monitoring_evidence,
            backup_restore_evidence_path=args.backup_restore_evidence,
            readiness_package_path=args.readiness_package,
        )
        sys.stdout.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
        return 0 if document["ready"] else 2

    try:
        manifest = render_manifest_for_freeze()
    except RuntimeError as exc:
        sys.stderr.write(f"REFUSED: {exc}\n")
        return 2
    try:
        sys.stdout.buffer.write(manifest)
    except BrokenPipeError:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
