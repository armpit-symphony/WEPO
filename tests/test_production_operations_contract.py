"""Static fail-closed contract for the inert production operations pack."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "wepo-production-deployment"
RUNBOOKS = ROOT / "docs" / "runbooks"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def bash_syntax(text: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-n"],
        input=text.replace("\r", "").encode("utf-8"),
        capture_output=True,
        timeout=30,
    )


def test_production_examples_are_inert_and_fail_placeholder_verification():
    backend = read(DEPLOYMENT / "backend-production.env.example")
    node = read(DEPLOYMENT / "node-production.env.example")
    qualification = read(DEPLOYMENT / "PRODUCTION_HOST_QUALIFICATION.md")
    verifier = read(DEPLOYMENT / "verify-production-host.sh")

    assert 'WEPO_NETWORK_PROFILE="mainnet"' in backend
    assert 'WEPO_REQUIRE_REDIS_RATE_LIMIT="1"' in backend
    assert 'WEPO_TRUST_PROXY_HEADERS="1"' in backend
    assert 'WEPO_NODE_API_URL="http://127.0.0.1:8122"' in backend
    assert 'WEPO_ALLOWED_ORIGINS="https://wallet.example.invalid"' in backend
    for feature in ("PRIVACY", "RWA", "BTC", "MESSAGING"):
        assert f'WEPO_FEATURE_{feature}="0"' in backend
    assert 'WEPO_ENABLE_STAGING_TOGGLES="0"' in backend

    assert 'WEPO_REQUIRE_MAINNET_SEEDS="1"' in node
    assert node.count(".example.invalid:22567") == 3
    assert 'WEPO_NODE_API_HOST="127.0.0.1"' in node
    assert 'WEPO_SHIELDED_VERIFIER_COMMAND_JSON="[\\"/opt/wepo/current/zk/target/release/ghost_verifier\\"]"' in node
    assert 'WEPO_SHIELDED_VERIFIER_TIMEOUT_SECONDS="5"' in node
    assert 'WEPO_SHIELDED_VERIFIER_MAX_PROOF_BYTES="1048576"' in node
    assert 'WEPO_SHIELDED_VERIFIER_MAX_CONCURRENT="2"' in node
    assert "--difficulty-override" not in node
    assert "WEPO_TEST_" not in node

    assert "example.invalid" in backend and "REPLACE" in backend
    assert "example.invalid" in node
    assert "example\\.invalid|REPLACE" in verifier
    assert "does not authorize" in qualification and "mainnet" in qualification
    assert "No script in this pack provisions or mutates a host" in qualification
    assert "redis-outage-evidence.template.json" in qualification
    assert "verify-redis-outage-evidence.py" in qualification


def test_production_nginx_requires_tls_limits_and_header_overwrite():
    nginx = read(DEPLOYMENT / "nginx-wepo-api-production.conf.example")

    required = (
        "return 308 https://$host$request_uri",
        "ssl_protocols TLSv1.2 TLSv1.3",
        "ssl_session_tickets off",
        "client_max_body_size 2m",
        "client_body_timeout 15s",
        "client_header_timeout 15s",
        "limit_req zone=wepo_api_per_ip",
        "limit_conn wepo_api_connections",
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "X-Content-Type-Options nosniff",
        "proxy_set_header X-Real-IP $remote_addr",
        "proxy_set_header X-Forwarded-For $remote_addr",
        "proxy_set_header X-Forwarded-Proto https",
        "proxy_request_buffering on",
    )
    for marker in required:
        assert marker in nginx
    assert "$proxy_add_x_forwarded_for" not in nginx
    assert "return 200" not in nginx
    assert "proxy_pass http://wepo_backend_api/api/" in nginx
    assert "listen 8011" not in nginx and "listen 8122" not in nginx


def test_production_units_use_distinct_locked_boundaries_and_hardening():
    node = read(DEPLOYMENT / "wepo-node-production.service.example")
    backend = read(DEPLOYMENT / "wepo-backend-production.service.example")

    assert "User=wepo-node" in node
    assert "Group=wepo-node" in node
    assert "User=wepo-api" in backend
    assert "Group=wepo-api" in backend
    assert "EnvironmentFile=/etc/wepo/node.env" in node
    assert "EnvironmentFile=/etc/wepo/backend.env" in backend
    assert "EnvironmentFile=-" not in node + backend
    assert "--api-host 127.0.0.1" in node
    assert "--api-port 8122" in node
    assert "--p2p-port 22567" in node
    assert "--network-profile mainnet" in node
    assert "--no-mining" in node
    assert "--difficulty-override" not in node
    assert "--host 127.0.0.1 --port 8011" in backend
    assert "--forwarded-allow-ips=127.0.0.1" in backend

    hardening = (
        "UMask=0077",
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "PrivateDevices=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "ProtectKernelTunables=true",
        "ProtectKernelModules=true",
        "ProtectControlGroups=true",
        "ProtectProc=invisible",
        "LockPersonality=true",
        "RestrictSUIDSGID=true",
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
    )
    for marker in hardening:
        assert marker in node
        assert marker in backend
    assert "ReadWritePaths=/var/lib/wepo/node" in node
    assert "ReadWritePaths=/var/lib/wepo/backend" in backend
    for resource_limit in ("TasksMax=128", "CPUQuota=200%", "MemoryHigh=60%", "MemoryMax=75%"):
        assert resource_limit in node
        assert resource_limit not in backend


def test_host_verifier_is_read_only_and_checks_runtime_boundaries():
    verifier = read(DEPLOYMENT / "verify-production-host.sh")
    syntax = bash_syntax(verifier)
    assert syntax.returncode == 0, syntax.stderr.decode("utf-8")

    required = (
        "readlink -f",
        "openssl dgst -sha256 -verify",
        "RELEASE_MANIFEST_SIGNATURE_PATH",
        "WEPO_SHIELDED_VERIFIER_COMMAND_JSON",
        "SHIELDED_VERIFIER_RELEASE_AUDIT_APPROVED",
        "SHIELDED_VERIFIER_RELEASE_SHA256",
        "Ghost verifier executable must not be a symlink",
        "Ghost verifier must be root-owned and not group/other writable",
        "installed Ghost verifier does not match the audited SHA-256",
        "mandatory Ghost verifier is direct, immutable, audited, and hash-bound",
        "validate_shielded_verifier",
        "mainnet_release_blockers",
        "mainnet release decision gate is closed",
        '[[ "${EXPECTED_NETWORK}" != "mainnet" ]]',
        "sha256sum --strict --check",
        "WEPO_REQUIRE_REDIS_RATE_LIMIT",
        "WEPO_TRUST_PROXY_HEADERS",
        "systemctl is-enabled",
        "systemctl is-active",
        "p2p_block_rejections_total",
        "block_validation_rejections_total",
        "misbehavior_events_total",
        "NoNewPrivileges",
        "CPUQuotaPerSecUSec",
        "MemoryHigh MemoryMax TasksMax",
        "TasksMax exceeds 128",
        "node and verifier child process tree has finite CPU, memory, and task ceilings",
        "nginx -t",
        "openssl x509 -checkend",
        "--proto '=https'",
        "proxy_set_header X-Forwarded-For $remote_addr",
        "port 22567 is not bound for external reachability",
        "datastore port {port} has a wildcard listener",
        "test_redis_rate_limit_fail_closed.py",
        '"chain_height", "latest_block_hash", "peers", "mempool_size", "mempool_bytes"',
        "no service or file was mutated",
    )
    for marker in required:
        assert marker in verifier

    forbidden_patterns = (
        r"systemctl\s+(start|stop|restart|reload|enable|disable)",
        r"\b(install|chmod|chown|useradd|groupadd|ufw|iptables|nft|rm|mv)\s+",
        r"\bln\s+-",
        r"\bsed\s+-i",
        r"\b(aws|doctl|gcloud|az)\s+",
    )
    for pattern in forbidden_patterns:
        assert not re.search(pattern, verifier), pattern


def test_required_incident_runbooks_exist_and_forbid_unsafe_repair():
    requirements = {
        "DEPLOY_AND_ROLLBACK.md": (
            "signed manifest", "Rollback is permitted only", "Never edit"
        ),
        "CHAIN_STALL_AND_FORK.md": (
            "three independent failure domains", "Do not restart every node", "manually select a tip"
        ),
        "SEED_LOSS.md": (
            "three independently hosted seeds", "external network", "home/NAT"
        ),
        "VALIDATOR_KEY_COMPROMISE.md": (
            "Fence the signer host", "retire the validator identity", "private key"
        ),
        "SECURITY_DISCLOSURE.md": (
            "critical", "regression", "resets the readiness soak"
        ),
        "MONITORING_AND_ALERTS.md": (
            "height, tip, supply", "Redis", "certificate", "Known implementation boundary"
        ),
        "MAINNET_PARAMETER_FREEZE_CEREMONY.md": (
            "render-manifest", "policy_not_implemented", "byte-for-byte"
        ),
    }
    for name, markers in requirements.items():
        document = read(RUNBOOKS / name)
        for marker in markers:
            assert marker in document, f"{name} lacks {marker}"

    combined = "\n".join(read(RUNBOOKS / name) for name in requirements)
    assert "older consensus binary merely" in combined
    assert "Never copy the private key" in combined
    assert "Never perform this drill" not in combined  # lives in qualification, not incident automation


def test_v1_scope_and_readiness_describe_current_signer_and_operations_state():
    scope = read(ROOT / "MAINNET_V1_LAUNCH_SCOPE.md")
    readiness = read(ROOT / "MAINNET_READINESS_AND_RELEASE_POLICY.md")

    assert "pending a production signer executable/deployment" not in scope
    assert "Protocol v3" in scope
    assert "signer-only cold-key stake authorization" in scope
    assert "intended-release-image" in scope.lower()
    assert "independent audit remain" in scope
    assert "signed release-manifest verification" in readiness
    assert "process-scoped structured consensus" in readiness
    assert "[x] Runbooks cover deploy, rollback" in readiness
    assert "[x] The v1 scope document matches the code" in readiness



def _valid_redis_outage_evidence() -> dict[str, object]:
    return {
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


def _run_redis_evidence_validator(tmp_path, evidence):
    evidence_path = tmp_path / "redis-outage-evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(DEPLOYMENT / "verify-redis-outage-evidence.py"),
            "--evidence",
            str(evidence_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_redis_outage_evidence_validator_accepts_redacted_fail_closed_drill(tmp_path):
    result = _run_redis_evidence_validator(tmp_path, _valid_redis_outage_evidence())

    assert result.returncode == 0, result.stderr
    assert "PASS Redis outage evidence" in result.stdout


def test_redis_outage_evidence_validator_rejects_fail_open_or_secret_evidence(tmp_path):
    evidence = _valid_redis_outage_evidence()
    evidence["drill"]["global_rate_limited_route_during_outage"]["http_status"] = 200
    result = _run_redis_evidence_validator(tmp_path, evidence)
    assert result.returncode != 0
    assert "http_status must be 429" in result.stderr

    evidence = _valid_redis_outage_evidence()
    evidence["redis"]["identity_redacted"] = "redis://:password@10.0.0.8:6379/0"
    result = _run_redis_evidence_validator(tmp_path, evidence)
    assert result.returncode != 0
    assert "secret-like" in result.stderr

    evidence = _valid_redis_outage_evidence()
    evidence["mainnet_live_network"] = True
    result = _run_redis_evidence_validator(tmp_path, evidence)
    assert result.returncode != 0
    assert "live public mainnet" in result.stderr



def _valid_readiness_decision_package() -> dict[str, object]:
    release_commit = "ab7ca8b8d2e26ac4b6d2534526ba3e7ac41952b2"
    manifest_sha = "1" * 64
    return {
        "format": "wepo-mainnet-readiness-decision-package-v1",
        "network": "mainnet",
        "release_commit": release_commit,
        "parameter_manifest_sha256": manifest_sha,
        "source_archive_sha256": "2" * 64,
        "signed_source_archive_sha256": "3" * 64,
        "genesis_construction_transcript_sha256": "4" * 64,
        "release_signing_public_key_sha256": "5" * 64,
        "signed_release_artifacts": True,
        "automated_tests": {
            "python_maintained_suite": {
                "status": "pass",
                "passed_count": 243,
                "evidence_ref": "2" * 64,
            },
            "rust_release_all_targets": {"status": "pass", "evidence_ref": "3" * 64},
            "frontend_vitest": {"status": "pass", "evidence_ref": "4" * 64},
            "frontend_production_build": {"status": "pass", "evidence_ref": "5" * 64},
            "desktop_package_boundary": {"status": "pass", "evidence_ref": "6" * 64},
            "github_actions_green": {"status": "pass", "evidence_ref": "7" * 64},
        },
        "seven_day_rehearsal": {
            "status": "pass",
            "duration_hours": 168,
            "no_unexplained_consensus_divergence": True,
            "evidence_sha256": "e" * 64,
        },
        "external_audits": [
            {"scope": "protocol", "independent": True, "critical_and_high_closed": True, "report_sha256": "6" * 64},
            {"scope": "security", "independent": True, "critical_and_high_closed": True, "report_sha256": "7" * 64},
            {"scope": "wallet", "independent": True, "critical_and_high_closed": True, "report_sha256": "8" * 64},
            {"scope": "operations", "independent": True, "critical_and_high_closed": True, "report_sha256": "9" * 64},
        ],
        "evidence_hashes": {
            "seed_node_inventory_sha256": "a" * 64,
            "redis_outage_evidence_sha256": "b" * 64,
            "monitoring_evidence_sha256": "c" * 64,
            "backup_restore_evidence_sha256": "d" * 64,
            "seven_day_rehearsal_evidence_sha256": "e" * 64,
            "external_audit_package_sha256": "f" * 64,
            "release_qualification_evidence_sha256": "0" * 64,
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
                "release_signing_public_key_sha256": "5" * 64,
                "approved_at_utc": "2026-08-01T00:00:00Z",
            }
            for role in ("protocol", "security", "wallet", "operations")
        },
    }


def _run_readiness_package_validator(tmp_path, package):
    package_path = tmp_path / "readiness-decision-package.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(DEPLOYMENT / "verify-readiness-decision-package.py"),
            "--package",
            str(package_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_readiness_decision_package_validator_accepts_complete_go_package(tmp_path):
    result = _run_readiness_package_validator(
        tmp_path, _valid_readiness_decision_package()
    )

    assert result.returncode == 0, result.stderr
    assert "PASS readiness decision package" in result.stdout


def test_readiness_decision_package_validator_rejects_missing_audit_or_mismatched_approval(tmp_path):
    package = _valid_readiness_decision_package()
    package["external_audits"] = package["external_audits"][:-1]
    result = _run_readiness_package_validator(tmp_path, package)
    assert result.returncode != 0
    assert "missing required audit scopes" in result.stderr

    package = _valid_readiness_decision_package()
    package["approvals"]["security"]["release_commit"] = "different"
    result = _run_readiness_package_validator(tmp_path, package)
    assert result.returncode != 0
    assert "approval commit mismatch" in result.stderr

    package = _valid_readiness_decision_package()
    package["approvals"]["security"]["release_signing_public_key_sha256"] = "9" * 64
    result = _run_readiness_package_validator(tmp_path, package)
    assert result.returncode != 0
    assert "approval signing-key mismatch" in result.stderr

    package = _valid_readiness_decision_package()
    package["external_audits"].append(dict(package["external_audits"][0]))
    result = _run_readiness_package_validator(tmp_path, package)
    assert result.returncode != 0
    assert "duplicate audit scope" in result.stderr

    package = _valid_readiness_decision_package()
    package["seven_day_rehearsal"]["evidence_sha256"] = "9" * 64
    result = _run_readiness_package_validator(tmp_path, package)
    assert result.returncode != 0
    assert "summary hash must match" in result.stderr


def test_readiness_decision_package_assets_are_wired_and_secret_safe():
    template = (DEPLOYMENT / "readiness-decision-package.template.json").read_text(
        encoding="utf-8"
    )
    validator = (DEPLOYMENT / "verify-readiness-decision-package.py").read_text(
        encoding="utf-8"
    )
    readiness = (ROOT / "MAINNET_READINESS_AND_RELEASE_POLICY.md").read_text(
        encoding="utf-8"
    )
    checklist = (DEPLOYMENT / "PUBLIC_RELEASE_CHECKLIST.md").read_text(
        encoding="utf-8"
    )

    assert "wepo-mainnet-readiness-decision-package-v1" in template
    assert "verify-readiness-decision-package.py" in readiness
    assert "readiness decision package" in checklist
    assert "REQUIRED_APPROVERS" in validator
    assert "REQUIRED_AUDITS" in validator
    assert "seven-day rehearsal" in validator
    assert "at least 243 passing tests" in validator
    assert "secret-like material" in validator
