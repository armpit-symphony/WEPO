#!/usr/bin/env python3
"""Read-only validator for a retained WEPO external-audit bundle."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys


FORMAT = "wepo-external-audit-package-v1"
REQUIRED_SCOPES = {"protocol", "security", "wallet", "operations"}
REQUIRED_FEATURE_COVERAGE = {
    "ghost": (
        "air_and_proof_system_reviewed",
        "transaction_and_consensus_binding_reviewed",
        "wallet_prover_and_recovery_reviewed",
        "verifier_boundary_and_resource_limits_reviewed",
        "activation_and_bundle_policy_reviewed",
    ),
    "proof_of_stake": (
        "consensus_selection_and_reorg_reviewed",
        "validator_signer_protocol_reviewed",
        "stake_lifecycle_policy_reviewed",
        "anti_equivocation_and_fail_closed_state_reviewed",
        "separate_user_deployment_backup_and_failover_reviewed",
    ),
}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
PLACEHOLDER = re.compile(r"(?:REPLACE|example\.(?:com|invalid)|placeholder)", re.IGNORECASE)
SELF_AUDITOR = re.compile(r"(?:\bWEPO\b|Spark\s*Pit(?:\s+Labs)?)", re.IGNORECASE)
SECRET_PATTERNS = (
    re.compile(r"(?:redis|mongodb(?:\+srv)?)://", re.IGNORECASE),
    re.compile(r"authorization\s*[:=]", re.IGNORECASE),
    re.compile(r"bearer\s+[a-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"(?:api[_ -]?key|password|private[_ -]?key|seed phrase|mnemonic)\s*[:=]", re.IGNORECASE),
)


def fail(message: str) -> None:
    raise SystemExit(f"[wepo-external-audits] FAIL {message}")


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


def require_list(mapping: dict[str, object], key: str) -> list[object]:
    value = mapping.get(key)
    if not isinstance(value, list):
        fail(f"missing list: {key}")
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

def parse_utc(value: str, *, key: str) -> datetime:
    if not value.endswith("Z"):
        fail(f"{key} must be a UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        fail(f"{key} must be a valid UTC timestamp")



def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact(
    package_path: Path,
    item: dict[str, object],
    *,
    file_key: str,
    hash_key: str,
    seen_paths: set[Path],
) -> None:
    relative_text = require_string(item, file_key)
    relative = PurePosixPath(relative_text)
    if relative.is_absolute() or ".." in relative.parts or "\\" in relative_text:
        fail(f"{file_key} must be a safe relative POSIX path")
    bundle_root = package_path.parent.resolve()
    artifact = (bundle_root / Path(*relative.parts)).resolve()
    try:
        artifact.relative_to(bundle_root)
    except ValueError:
        fail(f"{file_key} escapes the audit bundle")
    if artifact in seen_paths:
        fail(f"audit artifact path is reused: {relative_text}")
    seen_paths.add(artifact)
    if not artifact.is_file():
        fail(f"missing audit artifact: {relative_text}")
    if artifact.stat().st_size == 0:
        fail(f"audit artifact must not be empty: {relative_text}")
    if sha256(artifact) != require_sha256(item, hash_key):
        fail(f"audit artifact hash mismatch: {relative_text}")


def validate(document: dict[str, object], *, package_path: Path) -> None:
    assert_redacted(document)
    if document.get("format") != FORMAT:
        fail(f"format must be {FORMAT}")
    if require_string(document, "network") != "mainnet":
        fail("network must be mainnet")
    require_string(document, "release_commit")
    require_sha256(document, "release_artifact_sha256")
    require_sha256(document, "parameter_manifest_sha256")

    coverage = require_dict(document, "mandatory_feature_coverage")
    if set(coverage) != set(REQUIRED_FEATURE_COVERAGE):
        fail("mandatory feature coverage must contain exactly Ghost and Proof-of-Stake")
    for feature, assertions in REQUIRED_FEATURE_COVERAGE.items():
        item = require_dict(coverage, feature)
        covered_by_scopes = require_list(item, "covered_by_scopes")
        if (
            any(not isinstance(scope, str) for scope in covered_by_scopes)
            or len(covered_by_scopes) != len(REQUIRED_SCOPES)
            or set(covered_by_scopes) != REQUIRED_SCOPES
        ):
            fail(
                f"mandatory feature must be covered by every audit scope: {feature}"
            )
        for assertion in assertions:
            if not require_bool(item, assertion):
                fail(
                    f"mandatory feature audit assertion must be true: "
                    f"{feature}.{assertion}"
                )

    audits = require_list(document, "audits")
    seen_scopes: set[str] = set()
    seen_paths: set[Path] = set()
    completed_times: list[datetime] = []
    for index, item in enumerate(audits):
        if not isinstance(item, dict):
            fail(f"audit entry {index} must be an object")
        scope = require_string(item, "scope")
        if scope not in REQUIRED_SCOPES:
            fail(f"unsupported audit scope: {scope}")
        if scope in seen_scopes:
            fail(f"duplicate audit scope: {scope}")
        seen_scopes.add(scope)
        organization = require_string(item, "auditor_organization")
        engagement = require_string(item, "engagement_id")
        if PLACEHOLDER.search(organization) or PLACEHOLDER.search(engagement):
            fail(f"audit identity contains a placeholder: {scope}")
        if not require_bool(item, "independence_attested"):
            fail(f"auditor independence must be attested: {scope}")
        if SELF_AUDITOR.search(organization):
            fail(f"audit organization must be external to WEPO/SparkPit: {scope}")
        if not require_bool(item, "report_signature_verified"):
            fail(f"audit report signature must be verified: {scope}")
        classification = require_string(item, "report_access_classification")
        if classification not in {"public", "retained-confidential"}:
            fail(f"unsupported report access classification: {scope}")
        completed_times.append(
            parse_utc(require_string(item, "completed_at_utc"), key=f"{scope}.completed_at_utc")
        )
        for prefix in ("critical", "high", "medium", "low"):
            total = require_int(item, f"{prefix}_total")
            opened = require_int(item, f"{prefix}_open")
            if opened > total:
                fail(f"open {prefix} findings exceed total: {scope}")
        if item.get("critical_open") != 0 or item.get("high_open") != 0:
            fail(f"critical and high findings must be closed: {scope}")
        for file_key, hash_key in (
            ("scope_document_file", "scope_document_sha256"),
            ("independence_attestation_file", "independence_attestation_sha256"),
            ("report_file", "report_sha256"),
            ("signature_verification_file", "signature_verification_sha256"),
            ("disposition_log_file", "disposition_log_sha256"),
        ):
            verify_artifact(
                package_path,
                item,
                file_key=file_key,
                hash_key=hash_key,
                seen_paths=seen_paths,
            )
    missing = sorted(REQUIRED_SCOPES - seen_scopes)
    if missing:
        fail("missing required audit scopes: " + ", ".join(missing))
    if not require_bool(document, "operations_reviewed_bundle"):
        fail("operations owner must review the retained audit bundle")
    if not require_bool(document, "security_reviewed_bundle"):
        fail("security owner must review the retained audit bundle")
    reviewed = parse_utc(require_string(document, "reviewed_at_utc"), key="reviewed_at_utc")
    if completed_times and reviewed < max(completed_times):
        fail("bundle review must occur after all audit reports are complete")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    with args.package.open("r", encoding="utf-8") as source:
        document = json.load(source)
    if not isinstance(document, dict):
        fail("audit package root must be an object")
    validate(document, package_path=args.package)
    print("[wepo-external-audits] PASS external-audit bundle and retained artifact hashes are complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
