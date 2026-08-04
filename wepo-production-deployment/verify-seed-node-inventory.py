#!/usr/bin/env python3
"""Read-only validator for retained WEPO seed-node inventory evidence."""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from pathlib import Path

FORMAT = "wepo-seed-node-inventory-v1"
FORBIDDEN_DOMAINS = {"wepo.network"}
DOCUMENTATION_SUFFIXES = (".example", ".invalid", ".localhost", ".test")


def fail(message: str) -> None:
    raise SystemExit(f"[wepo-seed-inventory] FAIL {message}")


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


def require_list(mapping: dict[str, object], key: str) -> list[object]:
    value = mapping.get(key)
    if not isinstance(value, list):
        fail(f"missing list: {key}")
    return value


def validate_domain(document: dict[str, object]) -> str:
    domain = document.get("domain")
    if not isinstance(domain, dict):
        fail("missing domain object")
    registrable = require_string(domain, "registrable_domain").lower().rstrip(".")
    if registrable in FORBIDDEN_DOMAINS or registrable.endswith(DOCUMENTATION_SUFFIXES):
        fail(f"registrable domain is not approved evidence: {registrable}")
    for key in ("registrar_account_owner", "mfa_recovery_controls", "dns_provider"):
        require_string(domain, key)
    if not require_bool(domain, "operational_control_verified"):
        fail("domain operational control must be independently verified")
    api_fqdn = require_string(domain, "api_fqdn").lower().rstrip(".")
    if not api_fqdn.endswith("." + registrable):
        fail("api_fqdn must be under registrable_domain")
    seed_fqdns = require_list(domain, "seed_fqdns")
    if len(seed_fqdns) < 3:
        fail("record at least three selected seed FQDNs")
    for item in seed_fqdns:
        if not isinstance(item, str) or not item.strip():
            fail("seed_fqdns must contain strings")
        fqdn = item.lower().rstrip(".")
        if fqdn in FORBIDDEN_DOMAINS or fqdn.endswith(DOCUMENTATION_SUFFIXES):
            fail(f"seed FQDN is not approved evidence: {fqdn}")
        if not fqdn.endswith("." + registrable):
            fail(f"seed FQDN must be under registrable_domain: {fqdn}")
    return registrable


def validate_ip(value: str, *, label: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError as exc:
        fail(f"invalid IP for {label}: {value}")
    if not ip.is_global:
        fail(f"{label} must be a public globally routable IP: {value}")
    return ip


def validate_peer(peer: object, *, own_ip: str) -> None:
    if not isinstance(peer, str) or ":" not in peer:
        fail(f"invalid static peer endpoint: {peer!r}")
    host, port = peer.rsplit(":", 1)
    if port != "22567":
        fail(f"static peer must use TCP 22567: {peer}")
    validate_ip(host, label="static peer")
    if host == own_ip:
        fail(f"node lists itself as a static peer: {peer}")


def validate_nodes(document: dict[str, object]) -> None:
    nodes = require_list(document, "nodes")
    if len(nodes) < 3:
        fail("at least three seed nodes are required")
    seen_roles: set[str] = set()
    seen_ips: set[str] = set()
    seen_failure_domains: set[str] = set()
    for index, item in enumerate(nodes):
        if not isinstance(item, dict):
            fail(f"node {index} must be an object")
        role = require_string(item, "role")
        if role in seen_roles:
            fail(f"duplicate seed role: {role}")
        seen_roles.add(role)
        provider = require_string(item, "provider")
        failure_domain = require_string(item, "failure_domain")
        domain_key = f"{provider.lower()}::{failure_domain.lower()}"
        if domain_key in seen_failure_domains:
            fail(f"duplicate provider/failure domain: {provider}/{failure_domain}")
        seen_failure_domains.add(domain_key)
        public_ip = require_string(item, "public_ip")
        validate_ip(public_ip, label=f"{role} public_ip")
        if public_ip in seen_ips:
            fail(f"duplicate public IP: {public_ip}")
        seen_ips.add(public_ip)
        if item.get("p2p_port") != 22567:
            fail(f"{role} p2p_port must be 22567")
        if require_string(item, "api_bind") != "127.0.0.1:8122":
            fail(f"{role} API must remain loopback-only")
        if not require_bool(item, "firewall_allows_tcp_22567"):
            fail(f"{role} must have TCP 22567 allowed")
        probe = item.get("external_tcp_probe")
        if not isinstance(probe, dict):
            fail(f"{role} missing external_tcp_probe")
        if require_string(probe, "status") != "pass":
            fail(f"{role} external TCP probe must pass")
        require_string(probe, "observed_from")
        require_string(probe, "observed_at_utc")
        peers = require_list(item, "static_peers")
        if len(peers) < 2:
            fail(f"{role} must list at least two static peers")
        for peer in peers:
            validate_peer(peer, own_ip=public_ip)


def validate(document: dict[str, object]) -> None:
    if document.get("format") != FORMAT:
        fail(f"format must be {FORMAT}")
    if require_string(document, "network_profile") not in {"test", "release-candidate"}:
        fail("network_profile must be test or release-candidate")
    require_string(document, "release_commit")
    if require_bool(document, "mainnet_genesis_finalized"):
        fail("seed inventory must not finalize mainnet genesis")
    validate_domain(document)
    validate_nodes(document)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    args = parser.parse_args()
    with args.inventory.open("r", encoding="utf-8") as source:
        document = json.load(source)
    if not isinstance(document, dict):
        fail("inventory root must be an object")
    validate(document)
    print("[wepo-seed-inventory] PASS inventory evidence is structurally complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
