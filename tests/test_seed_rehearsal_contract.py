"""Contract checks for the isolated three-host seed rehearsal assets."""

from __future__ import annotations

from pathlib import Path
import json
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "wepo-production-deployment"


def test_seed_rehearsal_templates_are_explicitly_non_mainnet():
    environment = (DEPLOYMENT / "seed-rehearsal.env.example").read_text(
        encoding="utf-8"
    )
    unit = (DEPLOYMENT / "wepo-seed-rehearsal.service.example").read_text(
        encoding="utf-8"
    )
    runbook = (DEPLOYMENT / "THREE_HOST_SEED_REHEARSAL.md").read_text(
        encoding="utf-8"
    )

    assert 'WEPO_NETWORK_PROFILE="test"' in environment
    assert 'WEPO_REQUIRE_MAINNET_SEEDS="0"' in environment
    assert 'WEPO_DNS_SEEDS="off"' in environment
    assert 'WEPO_NODE_API_HOST="127.0.0.1"' in environment
    assert "--network-profile test" in unit
    assert "--no-mining" in unit
    assert "--api-host 127.0.0.1" in unit
    assert "--p2p-port 22567" in unit
    assert "not mainnet deployment" in runbook
    assert "Do not use this PC as the third public seed" in runbook


def test_seed_rehearsal_verifier_is_bash_parseable_and_read_only():
    verifier = DEPLOYMENT / "verify-seed-rehearsal-host.sh"
    content = verifier.read_text(encoding="utf-8")

    bash = shutil.which("bash")
    assert bash is not None
    verifier_argument = str(verifier.relative_to(ROOT)).replace("\\", "/")
    result = subprocess.run(
        [bash, "-n", verifier_argument],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "WEPO_NETWORK_PROFILE" in content
    assert "WEPO_STATIC_PEERS" in content
    assert "systemctl is-active" in content
    assert "curl --fail" in content
    assert "install " not in content
    assert "systemctl enable" not in content
    assert "systemctl restart" not in content



def _valid_seed_inventory() -> dict[str, object]:
    return {
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
                    "observed_from": "independent-observer-a",
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
                    "observed_from": "independent-observer-b",
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
                    "observed_from": "independent-observer-c",
                    "observed_at_utc": "2026-08-01T00:02:00Z",
                },
            },
        ],
    }


def _run_inventory_validator(tmp_path, inventory):
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(DEPLOYMENT / "verify-seed-node-inventory.py"),
            "--inventory",
            str(inventory_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_seed_inventory_validator_accepts_complete_public_three_host_evidence(tmp_path):
    result = _run_inventory_validator(tmp_path, _valid_seed_inventory())

    assert result.returncode == 0, result.stderr
    assert "PASS inventory evidence" in result.stdout


def test_seed_inventory_validator_rejects_placeholders_and_weak_topology(tmp_path):
    inventory = _valid_seed_inventory()
    del inventory["release_commit"]
    result = _run_inventory_validator(tmp_path, inventory)
    assert result.returncode != 0
    assert "release_commit" in result.stderr

    inventory = _valid_seed_inventory()
    inventory["domain"]["registrable_domain"] = "wepo.network"
    result = _run_inventory_validator(tmp_path, inventory)
    assert result.returncode != 0
    assert "registrable domain" in result.stderr

    inventory = _valid_seed_inventory()
    inventory["nodes"][2]["public_ip"] = "198.51.100.23"
    result = _run_inventory_validator(tmp_path, inventory)
    assert result.returncode != 0
    assert "globally routable" in result.stderr

    inventory = _valid_seed_inventory()
    inventory["nodes"][1]["failure_domain"] = "nyc3"
    inventory["nodes"][1]["provider"] = "DigitalOcean"
    result = _run_inventory_validator(tmp_path, inventory)
    assert result.returncode != 0
    assert "duplicate provider/failure domain" in result.stderr


def test_seed_inventory_template_and_runbook_are_wired_to_validator():
    template = (DEPLOYMENT / "seed-node-inventory.template.json").read_text(
        encoding="utf-8"
    )
    runbook = (DEPLOYMENT / "THREE_HOST_SEED_REHEARSAL.md").read_text(
        encoding="utf-8"
    )
    validator = (DEPLOYMENT / "verify-seed-node-inventory.py").read_text(
        encoding="utf-8"
    )

    assert "wepo-seed-node-inventory-v1" in template
    assert "wepocoin.org" in template
    assert "operational_control_verified" in template
    assert "verify-seed-node-inventory.py" in runbook
    assert "wepo.network" in validator
    assert "is_global" in validator
