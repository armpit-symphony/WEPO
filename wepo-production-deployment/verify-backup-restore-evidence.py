#!/usr/bin/env python3
"""Read-only validator for retained WEPO encrypted backup/restore evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


FORMAT = "wepo-backup-restore-evidence-v1"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
ALLOWED_SCOPE = {"node-chainstate", "backend-durable-state"}
SECRET_PATTERNS = (
    re.compile(r"(?:redis|mongodb(?:\+srv)?)://", re.IGNORECASE),
    re.compile(r"authorization\s*[:=]", re.IGNORECASE),
    re.compile(r"bearer\s+[a-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"(?:seed phrase|mnemonic|password|private[_ -]?key)\s*[:=]", re.IGNORECASE),
)


def fail(message: str) -> None:
    raise SystemExit(f"[wepo-backup-restore-evidence] FAIL {message}")


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


def validate(document: dict[str, object]) -> None:
    assert_redacted(document)
    if document.get("format") != FORMAT:
        fail(f"format must be {FORMAT}")
    if require_string(document, "network_profile") not in {
        "test",
        "release-candidate",
        "mainnet-candidate",
    }:
        fail("network_profile must be a release-host rehearsal profile")
    if require_bool(document, "mainnet_live_network"):
        fail("this evidence format must not authorize an unapproved live public mainnet drill")
    require_string(document, "release_commit")
    require_sha256(document, "release_artifact_sha256")

    backup = require_dict(document, "backup")
    scope = backup.get("scope")
    if not isinstance(scope, list) or not scope:
        fail("backup.scope must be a non-empty list")
    if any(not isinstance(item, str) or item not in ALLOWED_SCOPE for item in scope):
        fail("backup.scope contains an unsupported or key-bearing component")
    if len(set(scope)) != len(scope):
        fail("backup.scope must not contain duplicates")
    for key in (
        "encrypted_at_rest",
        "encrypted_in_transit",
        "off_host_copy",
        "encryption_key_separated",
    ):
        if not require_bool(backup, key):
            fail(f"backup security requirement must be true: {key}")
    for key in ("validator_private_keys_included", "wallet_seed_phrases_included"):
        if require_bool(backup, key):
            fail(f"backup must exclude key material: {key}")
    require_string(backup, "created_at_utc")
    require_sha256(backup, "encrypted_artifact_sha256")

    restore = require_dict(document, "restore_drill")
    for key in (
        "change_approval_recorded",
        "isolated_environment",
        "restored_from_off_host_copy",
        "restore_completed",
        "node_started",
        "application_health_passed",
        "peer_sync_resumed",
    ):
        if not require_bool(restore, key):
            fail(f"restore requirement must be true: {key}")
    if require_bool(restore, "destructive_live_restore_performed"):
        fail("qualification must not perform a destructive restore on a live public node")
    expected_height = require_int(restore, "expected_chain_height")
    restored_height = require_int(restore, "restored_chain_height")
    if restored_height != expected_height:
        fail("restored_chain_height must equal expected_chain_height")
    expected_tip = require_sha256(restore, "expected_chain_tip_sha256")
    restored_tip = require_sha256(restore, "restored_chain_tip_sha256")
    if restored_tip != expected_tip:
        fail("restored chain tip must match the expected chain tip")
    rpo_target = require_int(restore, "rpo_target_minutes", minimum=1)
    rpo_observed = require_int(restore, "rpo_observed_minutes")
    rto_target = require_int(restore, "rto_target_minutes", minimum=1)
    rto_observed = require_int(restore, "rto_observed_minutes")
    if rpo_observed > rpo_target:
        fail("observed RPO exceeds the recorded target")
    if rto_observed > rto_target:
        fail("observed RTO exceeds the recorded target")
    require_string(restore, "completed_at_utc")
    require_sha256(restore, "evidence_log_sha256")
    if not require_bool(restore, "logs_redacted"):
        fail("restore evidence logs must be redacted")

    retention = require_dict(document, "retention")
    require_int(retention, "independent_failure_domains", minimum=2)
    require_int(retention, "retained_copies", minimum=2)
    interval = require_int(retention, "restore_drill_interval_days", minimum=1)
    if interval > 90:
        fail("restore drill interval must be at most 90 days")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    with args.evidence.open("r", encoding="utf-8") as source:
        document = json.load(source)
    if not isinstance(document, dict):
        fail("evidence root must be an object")
    validate(document)
    print("[wepo-backup-restore-evidence] PASS encrypted backup/restore evidence is complete and redacted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
