"""Deployment contract for fail-closed Redis rate limiting."""

from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "wepo-production-deployment"


def test_staging_assets_require_and_verify_redis_rate_limiting():
    environment = (DEPLOYMENT / "backend.env.example").read_text(
        encoding="utf-8"
    )
    guide = (DEPLOYMENT / "CANONICAL_STAGING_DEPLOYMENT.md").read_text(
        encoding="utf-8"
    )
    verifier = DEPLOYMENT / "verify-canonical-staging-host.sh"
    verifier_text = verifier.read_text(encoding="utf-8")

    assert 'WEPO_REQUIRE_REDIS_RATE_LIMIT="1"' in environment
    assert "Redis required for distributed rate limiting" in guide
    assert "Redis optional" not in guide
    assert 'REQUIRE_REDIS_RATE_LIMIT_VALUE="${WEPO_REQUIRE_REDIS_RATE_LIMIT:-}"' in verifier_text
    assert 'WEPO_REQUIRE_REDIS_RATE_LIMIT must be 1' in verifier_text
    assert "Redis.from_url" in verifier_text
    assert "client.ping()" in verifier_text

    result = subprocess.run(
        ["bash", "-n"],
        input=verifier_text.replace("\r", "").encode("utf-8"),
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8")



def test_redis_outage_evidence_assets_are_wired_and_redacted():
    template = (DEPLOYMENT / "redis-outage-evidence.template.json").read_text(
        encoding="utf-8"
    )
    validator = DEPLOYMENT / "verify-redis-outage-evidence.py"
    validator_text = validator.read_text(encoding="utf-8")
    qualification = (DEPLOYMENT / "PRODUCTION_HOST_QUALIFICATION.md").read_text(
        encoding="utf-8"
    )

    assert "wepo-redis-outage-evidence-v1" in template
    assert "require_redis_rate_limit" in template
    assert "startup_unavailable_fails_closed" in template
    assert "no_successful_rate_limited_request_during_outage" in template
    assert "verify-redis-outage-evidence.py" in qualification
    assert "Do not publish Redis URLs" in qualification
    assert "redis://" in validator_text
    assert "must be {expected_status}" in validator_text
    assert "client/IP address must be redacted" in validator_text

    result = subprocess.run(
        ["python", "-m", "py_compile", str(validator)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
