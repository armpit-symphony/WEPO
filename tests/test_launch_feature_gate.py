#!/usr/bin/env python3
"""
Launch-scope feature gating tests (Blocker 6).

Disabled-at-launch features must be rejected by default and only served when
their env flag is explicitly enabled. Verifies the backend path-prefix gate.

Run: python3 tests/test_launch_feature_gate.py
"""
import importlib
import os
import sys

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, os.path.abspath(BACKEND))

FAILURES = []


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


def reload_ff():
    import feature_flags
    return importlib.reload(feature_flags)


# Paths that must be gated when their feature is disabled.
GATED = {
    "/api/vault/create": "Privacy / Quantum Vault",
    "/api/vault/rwa/create": "Privacy / Quantum Vault",
    "/api/rwa/tokenize": "RWA",
    "/api/dex/rwa-trade": "RWA trading",
    "/api/bitcoin/relay/broadcast": "Bitcoin relay",
    "/api/dex/swap": "Atomic swap",
    "/api/swap/execute": "Atomic swap",
    "/api/mining/_toggle_genesis": "Staging genesis toggle",
}

# Paths that must NEVER be gated (core launch surface).
ALWAYS_OPEN = [
    "/api/wallet/create",
    "/api/transaction/send",
    "/api/transaction/build-unsigned",
    "/api/mining/status",
    "/api/quantum/status",
    "/api/swap/rate",            # read-only sanity endpoint stays open
    "/api/bitcoin/address/abc",  # read-only chain query stays open
    "/api/staking/info",
]


def main():
    # Default (no flags set): every gated feature is disabled.
    for k in ("WEPO_FEATURE_PRIVACY", "WEPO_FEATURE_RWA", "WEPO_FEATURE_BTC", "WEPO_ENABLE_STAGING_TOGGLES"):
        os.environ.pop(k, None)
    ff = reload_ff()

    print("Default (launch) profile: disabled features rejected:")
    for path, label in GATED.items():
        check(f"{path} -> blocked as '{label}'", ff.disabled_feature_for_path(path) == label)

    print("\nCore launch surface stays open:")
    for path in ALWAYS_OPEN:
        check(f"{path} -> open", ff.disabled_feature_for_path(path) is None)

    # Enabling a flag opens exactly that feature, leaving others gated.
    print("\nEnabling WEPO_FEATURE_RWA opens RWA only:")
    os.environ["WEPO_FEATURE_RWA"] = "1"
    ff = reload_ff()
    check("/api/rwa/tokenize -> open when RWA enabled", ff.disabled_feature_for_path("/api/rwa/tokenize") is None)
    check("/api/dex/rwa-trade -> open when RWA enabled", ff.disabled_feature_for_path("/api/dex/rwa-trade") is None)
    check("/api/vault/create -> still blocked (privacy still off)",
          ff.disabled_feature_for_path("/api/vault/create") == "Privacy / Quantum Vault")
    os.environ.pop("WEPO_FEATURE_RWA", None)

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
