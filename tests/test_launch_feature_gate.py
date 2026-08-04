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
    "/api/bitcoin/address/abc": "Bitcoin integration",
    "/api/dex/swap": "Atomic swap",
    "/api/dex/rate": "BTC market",
    "/api/swap/execute": "Atomic swap",
    "/api/swap/rate": "BTC market",
    "/api/swap/history": "BTC market",
    "/api/liquidity/add": "BTC liquidity",
    "/api/messages": "Private messaging",
    "/api/messages/keys": "Private messaging",
    "/api/mining/_toggle_genesis": "Staging genesis toggle",
    "/api/mining/connect": "Browser mining",
}

# Paths that must NEVER be gated (core launch surface).
ALWAYS_OPEN = [
    "/api/wallet/create",
    "/api/transaction/send",
    "/api/transaction/build-unsigned",
    "/api/mining/status",
    "/api/quantum/status",
    "/api/staking/info",
]


def main():
    previous_profile = os.environ.get("WEPO_NETWORK_PROFILE")
    os.environ["WEPO_NETWORK_PROFILE"] = "mainnet"
    # Default (no flags set): every gated feature is disabled.
    for k in ("WEPO_FEATURE_PRIVACY", "WEPO_FEATURE_RWA", "WEPO_FEATURE_RWA_TRADE",
              "WEPO_FEATURE_BTC", "WEPO_FEATURE_MESSAGING", "WEPO_FEATURE_BROWSER_MINING", "WEPO_ENABLE_STAGING_TOGGLES"):
        os.environ.pop(k, None)
    ff = reload_ff()

    print("Default (launch) profile: disabled features rejected:")
    for path, label in GATED.items():
        check(f"{path} -> blocked as '{label}'", ff.disabled_feature_for_path(path) == label)

    print("\nCore launch surface stays open:")
    for path in ALWAYS_OPEN:
        check(f"{path} -> open", ff.disabled_feature_for_path(path) is None)


    # A mainnet profile stays locked even if every test/staging flag is set.
    print("\nMainnet ignores launch-feature opt-in flags:")
    for k in ("WEPO_FEATURE_PRIVACY", "WEPO_FEATURE_RWA", "WEPO_FEATURE_RWA_TRADE",
              "WEPO_FEATURE_BTC", "WEPO_FEATURE_MESSAGING", "WEPO_FEATURE_BROWSER_MINING", "WEPO_ENABLE_STAGING_TOGGLES"):
        os.environ[k] = "1"
    ff = reload_ff()
    for path, label in GATED.items():
        check(f"{path} -> remains blocked on mainnet",
              ff.disabled_feature_for_path(path) == label)

    # Feature flags are staging/test opt-ins, so exercise them off mainnet.
    os.environ["WEPO_NETWORK_PROFILE"] = "test"
    for k in ("WEPO_FEATURE_PRIVACY", "WEPO_FEATURE_RWA", "WEPO_FEATURE_RWA_TRADE",
              "WEPO_FEATURE_BTC", "WEPO_FEATURE_MESSAGING", "WEPO_FEATURE_BROWSER_MINING", "WEPO_ENABLE_STAGING_TOGGLES"):
        os.environ.pop(k, None)
    # Enabling RWA creation opens ONLY creation/reads — trading (mock swap engine) and
    # privacy stay gated behind their own flags.
    print("\nEnabling WEPO_FEATURE_RWA opens RWA creation only (not trading, not privacy):")
    os.environ["WEPO_FEATURE_RWA"] = "1"
    ff = reload_ff()
    check("/api/rwa/tokenize -> open when RWA enabled", ff.disabled_feature_for_path("/api/rwa/tokenize") is None)
    check("/api/dex/rwa-trade -> STILL blocked (trading has its own flag)",
          ff.disabled_feature_for_path("/api/dex/rwa-trade") == "RWA trading")
    check("/api/vault/create -> still blocked (privacy still off)",
          ff.disabled_feature_for_path("/api/vault/create") == "Privacy / Quantum Vault")
    os.environ.pop("WEPO_FEATURE_RWA", None)

    # Trading opens only under its own flag.
    print("\nEnabling WEPO_FEATURE_RWA_TRADE opens trading:")
    os.environ["WEPO_FEATURE_RWA_TRADE"] = "1"
    ff = reload_ff()
    check("/api/dex/rwa-trade -> open when RWA_TRADE enabled",
          ff.disabled_feature_for_path("/api/dex/rwa-trade") is None)
    os.environ.pop("WEPO_FEATURE_RWA_TRADE", None)

    print("\nEnabling WEPO_FEATURE_BTC opens the complete BTC-dependent surface:")
    os.environ["WEPO_FEATURE_BTC"] = "1"
    ff = reload_ff()
    for path in (
        "/api/bitcoin/address/abc",
        "/api/bitcoin/relay/status",
        "/api/dex/rate",
        "/api/dex/swap",
        "/api/swap/rate",
        "/api/swap/history",
        "/api/liquidity/stats",
    ):
        check(f"{path} -> open when BTC enabled", ff.disabled_feature_for_path(path) is None)
    os.environ.pop("WEPO_FEATURE_BTC", None)


    if previous_profile is None:
        os.environ.pop("WEPO_NETWORK_PROFILE", None)
    else:
        os.environ["WEPO_NETWORK_PROFILE"] = previous_profile

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


def test_regression_suite():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())


def test_unknown_network_profiles_fail_closed():
    os.environ["WEPO_FEATURE_PRIVACY"] = "1"
    previous_profile = os.environ.get("WEPO_NETWORK_PROFILE")
    try:
        for profile in ("", "staging", "mainent"):
            os.environ["WEPO_NETWORK_PROFILE"] = profile
            ff = reload_ff()
            assert ff.disabled_feature_for_path("/api/vault/create") == "Privacy / Quantum Vault"
    finally:
        os.environ.pop("WEPO_FEATURE_PRIVACY", None)
        if previous_profile is None:
            os.environ.pop("WEPO_NETWORK_PROFILE", None)
        else:
            os.environ["WEPO_NETWORK_PROFILE"] = previous_profile
