#!/usr/bin/env python3
"""Read-only validator for retained WEPO Redis outage drill evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

FORMAT = "wepo-redis-outage-evidence-v1"
SECRET_PATTERNS = (
    re.compile(r"redis://", re.IGNORECASE),
    re.compile(r"rediss://", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"cookie", re.IGNORECASE),
    re.compile(r"authorization", re.IGNORECASE),
    re.compile(r"bearer\s+[a-z0-9._~+/=-]+", re.IGNORECASE),
)
IPV4_PATTERN = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")


def fail(message: str) -> None:
    raise SystemExit(f"[wepo-redis-evidence] FAIL {message}")


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


def assert_redacted(value: object, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert_redacted(key, path=f"{path}.{key}")
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
    for match in IPV4_PATTERN.finditer(value):
        parts = match.group(0).split(".")
        if all(0 <= int(part) <= 255 for part in parts):
            fail(f"raw client/IP address must be redacted at {path}")


def validate_https_url(value: str, *, key: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        fail(f"{key} must be an https URL")
    if parsed.hostname in {"example.invalid", "localhost"}:
        fail(f"{key} must not use a placeholder host")


def validate_probe(probe: dict[str, object], *, key: str, expected_status: int) -> None:
    if probe.get("http_status") != expected_status:
        fail(f"{key}.http_status must be {expected_status}")
    require_string(probe, "route")
    require_string(probe, "observed_at_utc")
    if require_bool(probe, "returned_success"):
        fail(f"{key} must not report returned_success=true")


def validate(document: dict[str, object]) -> None:
    assert_redacted(document)
    if document.get("format") != FORMAT:
        fail(f"format must be {FORMAT}")
    if require_string(document, "network_profile") not in {"test", "release-candidate", "mainnet-candidate"}:
        fail("network_profile must be a release-host rehearsal profile")
    if require_bool(document, "mainnet_live_network"):
        fail("this evidence format must not be used for an unapproved live public mainnet drill")
    validate_https_url(require_string(document, "public_api_base_url"), key="public_api_base_url")
    require_string(document, "release_commit")
    require_string(document, "backend_artifact_sha256")
    redis = require_dict(document, "redis")
    require_string(redis, "identity_redacted")
    if require_string(redis, "endpoint_visibility") not in {"private-network", "local-socket", "loopback"}:
        fail("redis.endpoint_visibility must be private-network, local-socket, or loopback")
    if not require_bool(redis, "require_redis_rate_limit"):
        fail("WEPO_REQUIRE_REDIS_RATE_LIMIT must be true in evidence")
    if not require_bool(redis, "startup_unavailable_fails_closed"):
        fail("startup-unavailable Redis check must fail closed")
    drill = require_dict(document, "drill")
    if not require_bool(drill, "change_approval_recorded"):
        fail("change approval must be recorded")
    if not require_bool(drill, "redis_only_endpoint_disrupted"):
        fail("drill must disrupt only the Redis endpoint")
    if not require_bool(drill, "backend_remained_running"):
        fail("backend must remain running during the Redis outage drill")
    if require_bool(drill, "unsafe_configuration_change_required"):
        fail("recovery must not require unsafe configuration changes")
    validate_probe(require_dict(drill, "global_rate_limited_route_during_outage"), key="global_rate_limited_route_during_outage", expected_status=429)
    validate_probe(require_dict(drill, "strict_endpoint_during_outage"), key="strict_endpoint_during_outage", expected_status=429)
    if not require_bool(drill, "normal_requests_before_outage_passed"):
        fail("normal pre-outage requests must pass")
    if not require_bool(drill, "recovery_after_restore_passed"):
        fail("post-restore recovery must pass")
    if not require_bool(drill, "no_successful_rate_limited_request_during_outage"):
        fail("evidence must prove no rate-limited request succeeded during outage")
    if not require_bool(drill, "logs_redacted"):
        fail("logs must be redacted before retention")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    with args.evidence.open("r", encoding="utf-8") as source:
        document = json.load(source)
    if not isinstance(document, dict):
        fail("evidence root must be an object")
    validate(document)
    print("[wepo-redis-evidence] PASS Redis outage evidence is structurally complete and redacted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
