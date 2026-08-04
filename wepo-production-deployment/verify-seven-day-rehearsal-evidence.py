#!/usr/bin/env python3
"""Read-only validator for retained WEPO seven-day candidate evidence."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import re
import sys
from pathlib import Path


FORMAT = "wepo-seven-day-rehearsal-evidence-v1"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REQUIRED_SUPPORTING_HASHES = (
    "seed_node_inventory_sha256",
    "redis_outage_evidence_sha256",
    "monitoring_evidence_sha256",
    "ghost_wallet_acceptance_sha256",
    "ghost_verifier_host_qualification_sha256",
    "pos_multinode_rehearsal_sha256",
    "validator_signer_host_qualification_sha256",
    "validator_fencing_failover_sha256",
    "backup_restore_evidence_sha256",
)
REQUIRED_DRILLS = (
    "alert_delivery_passed",
    "backup_restore_passed",
    "redis_outage_passed",
    "hostile_traffic_passed",
    "restart_recovery_passed",
    "ghost_valid_transfer_passed",
    "ghost_invalid_proof_refused",
    "ghost_verifier_timeout_crash_refused",
    "ghost_wallet_backup_restore_recovery_passed",
    "pos_live_signing_passed",
    "pos_partition_reorg_passed",
    "validator_anti_equivocation_refused",
    "validator_signer_fencing_failover_passed",
)
SECRET_PATTERNS = (
    re.compile(r"(?:redis|mongodb(?:\+srv)?)://", re.IGNORECASE),
    re.compile(r"authorization\s*[:=]", re.IGNORECASE),
    re.compile(r"bearer\s+[a-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"(?:api[_ -]?key|password|private[_ -]?key|seed phrase|mnemonic)\s*[:=]", re.IGNORECASE),
)


def fail(message: str) -> None:
    raise SystemExit(f"[wepo-seven-day-evidence] FAIL {message}")


def require_string(mapping: dict[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"missing non-empty string: {key}")
    return value.strip()


def require_bool(mapping: dict[str, object], key: str) -> bool:
    value = mapping.get(key)
    if not isinstance(value, bool):
        fail(f"missing boolean: {key}")
    return value


def require_int(mapping: dict[str, object], key: str, *, minimum: int = 0) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        fail(f"{key} must be an integer >= {minimum}")
    return value


def require_dict(mapping: dict[str, object], key: str) -> dict[str, object]:
    value = mapping.get(key)
    if not isinstance(value, dict):
        fail(f"missing object: {key}")
    return value


def require_list(mapping: dict[str, object], key: str) -> list[object]:
    value = mapping.get(key)
    if not isinstance(value, list):
        fail(f"missing list: {key}")
    return value


def require_sha256(mapping: dict[str, object], key: str) -> str:
    value = require_string(mapping, key)
    if SHA256.fullmatch(value) is None:
        fail(f"{key} must be a lowercase SHA-256 digest")
    return value


def assert_redacted(value: object, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert_redacted(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_redacted(item, path=f"{path}[{index}]")
        return
    if not isinstance(value, str):
        return
    for pattern in SECRET_PATTERNS:
        if pattern.search(value):
            fail(f"unredacted secret-like material at {path}")


def parse_utc(value: str, *, key: str) -> datetime:
    if not value.endswith("Z"):
        fail(f"{key} must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        fail(f"{key} must be a valid UTC timestamp")
    return parsed


def validate_nodes(document: dict[str, object]) -> None:
    nodes = require_list(document, "node_observations")
    if len(nodes) < 3:
        fail("at least three independently hosted node observations are required")
    roles: set[str] = set()
    fqdns: set[str] = set()
    failure_domains: set[str] = set()
    final_heights: set[int] = set()
    final_tips: set[str] = set()
    for index, item in enumerate(nodes):
        if not isinstance(item, dict):
            fail(f"node observation {index} must be an object")
        role = require_string(item, "role")
        fqdn = require_string(item, "fqdn").lower().rstrip(".")
        failure_domain = require_string(item, "failure_domain").lower()
        if role in roles or fqdn in fqdns or failure_domain in failure_domains:
            fail("node roles, FQDNs, and failure domains must be unique")
        roles.add(role)
        fqdns.add(fqdn)
        failure_domains.add(failure_domain)
        if not require_bool(item, "p2p_reachable_at_end"):
            fail(f"node must remain P2P reachable at rehearsal end: {role}")
        start_height = require_int(item, "start_height")
        final_height = require_int(item, "final_height")
        if final_height <= start_height:
            fail(f"node chain must advance during rehearsal: {role}")
        final_heights.add(final_height)
        final_tips.add(require_sha256(item, "final_block_hash"))
        availability = item.get("availability_percent")
        if not isinstance(availability, (int, float)) or isinstance(availability, bool):
            fail(f"availability_percent must be numeric: {role}")
        if availability < 99.0 or availability > 100.0:
            fail(f"availability_percent must be between 99 and 100: {role}")
    if len(final_heights) != 1 or len(final_tips) != 1:
        fail("candidate nodes must agree on final chain height and tip")


def validate(document: dict[str, object]) -> None:
    assert_redacted(document)
    if document.get("format") != FORMAT:
        fail(f"format must be {FORMAT}")
    if require_string(document, "network_profile") not in {
        "release-candidate",
        "mainnet-candidate",
    }:
        fail("network_profile must identify a frozen release candidate")
    if require_bool(document, "mainnet_live_network"):
        fail("rehearsal evidence must not authorize a live public mainnet")
    require_string(document, "release_commit")
    require_sha256(document, "release_artifact_sha256")
    require_sha256(document, "parameter_manifest_sha256")

    window = require_dict(document, "observation_window")
    started = parse_utc(require_string(window, "started_at_utc"), key="started_at_utc")
    ended = parse_utc(require_string(window, "ended_at_utc"), key="ended_at_utc")
    duration_hours = require_int(window, "duration_hours", minimum=168)
    actual_seconds = (ended - started).total_seconds()
    if actual_seconds < 168 * 60 * 60:
        fail("observation timestamps must span at least 168 continuous hours")
    if actual_seconds != duration_hours * 60 * 60:
        fail("duration_hours must exactly match the observation timestamps")
    if not require_bool(window, "continuous_observation"):
        fail("monitoring observation must be continuous")

    summary = require_dict(document, "summary")
    if not require_bool(summary, "candidate_network_remained_available"):
        fail("candidate network must remain available")
    for key in (
        "unexplained_consensus_divergence_count",
        "unexplained_supply_mismatch_count",
        "unresolved_critical_incident_count",
        "irreversible_data_loss_count",
    ):
        if require_int(summary, key) != 0:
            fail(f"{key} must be zero")
    validate_nodes(document)

    drills = require_dict(document, "drills")
    for key in REQUIRED_DRILLS:
        if not require_bool(drills, key):
            fail(f"required rehearsal drill must pass: {key}")

    supporting = require_dict(document, "supporting_evidence")
    for key in REQUIRED_SUPPORTING_HASHES:
        require_sha256(supporting, key)
    retained = require_dict(document, "retained_evidence")
    for key in (
        "continuous_monitoring_log_sha256",
        "chain_sample_log_sha256",
        "incident_log_sha256",
        "drill_log_sha256",
    ):
        require_sha256(retained, key)
    if not require_bool(retained, "logs_redacted"):
        fail("retained rehearsal logs must be redacted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    with args.evidence.open("r", encoding="utf-8") as source:
        document = json.load(source)
    if not isinstance(document, dict):
        fail("evidence root must be an object")
    validate(document)
    print("[wepo-seven-day-evidence] PASS seven-day candidate evidence is complete and redacted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
