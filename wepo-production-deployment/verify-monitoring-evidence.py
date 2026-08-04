#!/usr/bin/env python3
"""Read-only validator for retained WEPO monitoring and alert evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


FORMAT = "wepo-monitoring-evidence-v1"
REQUIRED_ALERTS = {
    "node_unreachable",
    "chain_stalled",
    "peer_count_low",
    "redis_unavailable",
    "certificate_expiry",
}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
FQDN = re.compile(r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
DOCUMENTATION_SUFFIXES = (".example", ".invalid", ".localhost", ".test")
FORBIDDEN_DOMAIN = "wepo.network"
SECRET_PATTERNS = (
    re.compile(r"redis(?:s)?://", re.IGNORECASE),
    re.compile(r"mongodb(?:\+srv)?://", re.IGNORECASE),
    re.compile(r"authorization\s*[:=]", re.IGNORECASE),
    re.compile(r"bearer\s+[a-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"(?:api[_ -]?key|password|private[_ -]?key)\s*[:=]", re.IGNORECASE),
)


def fail(message: str) -> None:
    raise SystemExit(f"[wepo-monitoring-evidence] FAIL {message}")


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


def validate_fqdn(value: str) -> str:
    fqdn = value.lower().rstrip(".")
    if FQDN.fullmatch(fqdn) is None:
        fail(f"invalid monitoring FQDN: {value}")
    if fqdn == FORBIDDEN_DOMAIN or fqdn.endswith("." + FORBIDDEN_DOMAIN) or fqdn.endswith(DOCUMENTATION_SUFFIXES):
        fail(f"monitoring FQDN is not approved owned-domain evidence: {fqdn}")
    return fqdn


def validate_node_observations(document: dict[str, object]) -> None:
    observations = require_list(document, "node_observations")
    if len(observations) < 3:
        fail("at least three seed-node observations are required")
    seen_roles: set[str] = set()
    seen_fqdns: set[str] = set()
    seen_heights: set[int] = set()
    seen_tips: set[str] = set()
    for index, item in enumerate(observations):
        if not isinstance(item, dict):
            fail(f"node observation {index} must be an object")
        role = require_string(item, "role")
        fqdn = validate_fqdn(require_string(item, "fqdn"))
        if role in seen_roles or fqdn in seen_fqdns:
            fail("node observations must use unique roles and FQDNs")
        seen_roles.add(role)
        seen_fqdns.add(fqdn)
        if item.get("p2p_port") != 22567:
            fail(f"{role} p2p_port must be 22567")
        if not require_bool(item, "p2p_reachable"):
            fail(f"{role} must be externally reachable on TCP 22567")
        if not require_bool(item, "dependency_health_passed"):
            fail(f"{role} dependency-aware health must pass")
        seen_heights.add(require_int(item, "chain_height"))
        seen_tips.add(require_sha256(item, "latest_block_hash"))
        require_int(item, "peer_count", minimum=2)
        require_string(item, "observed_at_utc")

    if len(seen_heights) != 1 or len(seen_tips) != 1:
        fail("seed-node observations must agree on chain height and tip")

def validate_alerts(document: dict[str, object]) -> None:
    alerts = require_list(document, "alert_tests")
    seen: set[str] = set()
    for index, item in enumerate(alerts):
        if not isinstance(item, dict):
            fail(f"alert test {index} must be an object")
        name = require_string(item, "name")
        if name in seen:
            fail(f"duplicate alert test: {name}")
        seen.add(name)
        if require_string(item, "status") != "pass":
            fail(f"alert test must pass: {name}")
        if not require_bool(item, "notification_received"):
            fail(f"alert notification was not received: {name}")
        require_string(item, "observed_at_utc")
        require_string(item, "evidence_ref")
    missing = sorted(REQUIRED_ALERTS - seen)
    if missing:
        fail("missing required alert tests: " + ", ".join(missing))


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
    window = require_dict(document, "observation_window")
    require_string(window, "started_at_utc")
    require_string(window, "ended_at_utc")
    require_int(window, "duration_minutes", minimum=30)
    metrics = require_dict(document, "metrics")
    for key in (
        "chain_height_and_tip",
        "peer_count",
        "mempool_size_and_bytes",
        "consensus_rejections",
        "redis_health",
        "certificate_expiry",
    ):
        if not require_bool(metrics, key):
            fail(f"required metric is not collected: {key}")
    validate_node_observations(document)
    validate_alerts(document)
    retention = require_dict(document, "retention")
    require_int(retention, "days", minimum=30)
    require_sha256(retention, "dashboard_snapshot_sha256")
    require_sha256(retention, "alert_test_log_sha256")
    if not require_bool(retention, "logs_redacted"):
        fail("retained monitoring logs must be redacted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    with args.evidence.open("r", encoding="utf-8") as source:
        document = json.load(source)
    if not isinstance(document, dict):
        fail("evidence root must be an object")
    validate(document)
    print("[wepo-monitoring-evidence] PASS monitoring and alert evidence is complete and redacted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
