#!/usr/bin/env python3
"""Read-only validator for the WEPO mainnet readiness decision package."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FORMAT = "wepo-mainnet-readiness-decision-package-v1"
REQUIRED_APPROVERS = ("protocol", "security", "wallet", "operations")
REQUIRED_AUDITS = ("protocol", "security", "wallet", "operations")
REQUIRED_EVIDENCE_HASHES = (
    "seed_node_inventory_sha256",
    "redis_outage_evidence_sha256",
    "monitoring_evidence_sha256",
    "backup_restore_evidence_sha256",
    "seven_day_rehearsal_evidence_sha256",
    "external_audit_package_sha256",
    "release_qualification_evidence_sha256",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SECRET_PATTERNS = (
    re.compile(r"redis://", re.IGNORECASE),
    re.compile(r"rediss://", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"private[_ -]?key", re.IGNORECASE),
    re.compile(r"mnemonic", re.IGNORECASE),
    re.compile(r"cookie", re.IGNORECASE),
    re.compile(r"authorization", re.IGNORECASE),
    re.compile(r"bearer\s+[a-z0-9._~+/=-]+", re.IGNORECASE),
)


def fail(message: str) -> None:
    raise SystemExit(f"[wepo-readiness-package] FAIL {message}")


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
    if not HEX64.fullmatch(value):
        fail(f"{key} must be lowercase SHA-256 hex")
    return value


def assert_no_secret_text(value: object, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert_no_secret_text(key, path=f"{path}.{key}")
            assert_no_secret_text(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_secret_text(item, path=f"{path}[{index}]")
        return
    if not isinstance(value, str):
        return
    for pattern in SECRET_PATTERNS:
        if pattern.search(value):
            fail(f"secret-like material is not allowed in readiness package at {path}")


def validate_tests(tests: dict[str, object]) -> None:
    python_suite = require_dict(tests, "python_maintained_suite")
    if require_string(python_suite, "status") != "pass":
        fail("python maintained suite must pass")
    count = python_suite.get("passed_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 243:
        fail("python maintained suite must record at least 243 passing tests")
    require_sha256(python_suite, "evidence_ref")
    for key in ("rust_release_all_targets", "frontend_vitest", "frontend_production_build", "desktop_package_boundary", "github_actions_green"):
        item = require_dict(tests, key)
        if require_string(item, "status") != "pass":
            fail(f"{key} must pass")
        require_sha256(item, "evidence_ref")


def validate_rehearsal(rehearsal: dict[str, object]) -> None:
    if require_string(rehearsal, "status") != "pass":
        fail("seven-day rehearsal must pass")
    duration = rehearsal.get("duration_hours")
    if not isinstance(duration, (int, float)) or duration < 168:
        fail("seven-day rehearsal must cover at least 168 hours")
    if not require_bool(rehearsal, "no_unexplained_consensus_divergence"):
        fail("seven-day rehearsal must have no unexplained consensus divergence")
    require_sha256(rehearsal, "evidence_sha256")


def validate_audits(audits: list[object]) -> None:
    by_scope: dict[str, dict[str, object]] = {}
    for item in audits:
        if not isinstance(item, dict):
            fail("audit entries must be objects")
        scope = require_string(item, "scope")
        if scope not in REQUIRED_AUDITS:
            fail(f"unsupported audit scope: {scope}")
        if scope in by_scope:
            fail(f"duplicate audit scope: {scope}")
        by_scope[scope] = item
        if not require_bool(item, "independent"):
            fail(f"audit must be independent: {scope}")
        if not require_bool(item, "critical_and_high_closed"):
            fail(f"critical/high audit findings must be closed: {scope}")
        require_sha256(item, "report_sha256")
    missing = sorted(set(REQUIRED_AUDITS) - set(by_scope))
    if missing:
        fail("missing required audit scopes: " + ", ".join(missing))


def validate_disabled_features(features: list[object]) -> None:
    if not features:
        fail("disabled features and enforcement points must be listed")
    for item in features:
        if not isinstance(item, dict):
            fail("disabled feature entries must be objects")
        require_string(item, "feature")
        points = require_list(item, "enforcement_points")
        if not points or not all(isinstance(point, str) and point.strip() for point in points):
            fail("each disabled feature needs enforcement points")
        if not require_bool(item, "client_claims_absent"):
            fail("disabled feature claims must be absent from clients")


def validate_approvals(
    approvals: dict[str, object],
    *,
    release_commit: str,
    manifest_sha256: str,
    signing_key_sha256: str,
) -> None:
    for role in REQUIRED_APPROVERS:
        item = approvals.get(role)
        if not isinstance(item, dict):
            fail(f"missing approval: {role}")
        if require_string(item, "decision") != "GO":
            fail(f"approval must be GO: {role}")
        if require_string(item, "release_commit") != release_commit:
            fail(f"approval commit mismatch: {role}")
        if require_string(item, "parameter_manifest_sha256") != manifest_sha256:
            fail(f"approval manifest mismatch: {role}")
        if require_string(item, "release_signing_public_key_sha256") != signing_key_sha256:
            fail(f"approval signing-key mismatch: {role}")
        require_string(item, "approver")
        require_string(item, "approved_at_utc")


def validate(document: dict[str, object]) -> None:
    assert_no_secret_text(document)
    if document.get("format") != FORMAT:
        fail(f"format must be {FORMAT}")
    if require_string(document, "network") != "mainnet":
        fail("network must be mainnet")
    release_commit = require_string(document, "release_commit")
    manifest_sha256 = require_sha256(document, "parameter_manifest_sha256")
    signing_key_sha256 = require_sha256(document, "release_signing_public_key_sha256")
    for key in ("source_archive_sha256", "signed_source_archive_sha256", "genesis_construction_transcript_sha256"):
        require_sha256(document, key)
    if not require_bool(document, "signed_release_artifacts"):
        fail("release artifacts must be signed")
    validate_tests(require_dict(document, "automated_tests"))
    rehearsal = require_dict(document, "seven_day_rehearsal")
    validate_rehearsal(rehearsal)
    validate_audits(require_list(document, "external_audits"))
    evidence_hashes = require_dict(document, "evidence_hashes")
    for key in REQUIRED_EVIDENCE_HASHES:
        require_sha256(evidence_hashes, key)
    if rehearsal.get("evidence_sha256") != evidence_hashes.get(
        "seven_day_rehearsal_evidence_sha256"
    ):
        fail(
            "seven-day rehearsal summary hash must match evidence_hashes"
        )
    validate_disabled_features(require_list(document, "disabled_features"))
    if not require_bool(document, "public_claims_match_enforcement"):
        fail("public claims must match enforcement")
    validate_approvals(
        require_dict(document, "approvals"),
        release_commit=release_commit,
        manifest_sha256=manifest_sha256,
        signing_key_sha256=signing_key_sha256,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    with args.package.open("r", encoding="utf-8") as source:
        document = json.load(source)
    if not isinstance(document, dict):
        fail("readiness package root must be an object")
    validate(document)
    print("[wepo-readiness-package] PASS readiness decision package is complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
