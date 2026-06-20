"""
Launch-scope feature gating (MAINNET_V1_LAUNCH_SCOPE.md).

Features that are not launch-ready are DISABLED by default and only served when
their env flag is explicitly enabled (e.g. in staging). Gating is applied in the
request middleware so disabled features cannot be exercised or appear live to
clients, regardless of which handler would otherwise run.

Flags (set to 1/true/yes/on to ENABLE the feature):
  WEPO_FEATURE_PRIVACY        privacy proofs / Quantum Vault (zk-STARK)
  WEPO_FEATURE_RWA            RWA assets, vault flows, and trading
  WEPO_FEATURE_BTC            Bitcoin relay and atomic/BTC swaps
  WEPO_ENABLE_STAGING_TOGGLES staging-only test hooks (e.g. genesis flip)
"""
import os


def feature_enabled(env_name: str) -> bool:
    return os.environ.get(env_name, "").strip().lower() in ("1", "true", "yes", "on")


# Order matters: more specific prefixes are listed before broader ones so the
# most descriptive label wins (e.g. /api/dex/rwa-trade before /api/dex/swap).
LAUNCH_GATED_PREFIXES = [
    ("/api/vault", "WEPO_FEATURE_PRIVACY", "Privacy / Quantum Vault"),
    ("/api/dex/rwa-trade", "WEPO_FEATURE_RWA", "RWA trading"),
    ("/api/rwa", "WEPO_FEATURE_RWA", "RWA"),
    ("/api/bitcoin/relay", "WEPO_FEATURE_BTC", "Bitcoin relay"),
    ("/api/dex/swap", "WEPO_FEATURE_BTC", "Atomic swap"),
    ("/api/swap/execute", "WEPO_FEATURE_BTC", "Atomic swap"),
    ("/api/mining/_toggle_genesis", "WEPO_ENABLE_STAGING_TOGGLES", "Staging genesis toggle"),
]


def disabled_feature_for_path(path: str):
    """Return the label of a launch-disabled feature for this path, else None."""
    for prefix, env_name, label in LAUNCH_GATED_PREFIXES:
        if path.startswith(prefix) and not feature_enabled(env_name):
            return label
    return None
