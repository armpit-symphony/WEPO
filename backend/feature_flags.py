"""
Launch-scope feature gating (MAINNET_V1_LAUNCH_SCOPE.md).

Features that are not launch-ready are DISABLED by default and only served when
their env flag is explicitly enabled (e.g. in staging). Gating is applied in the
request middleware so disabled features cannot be exercised or appear live to
clients, regardless of which handler would otherwise run.

Flags (set to 1/true/yes/on to ENABLE the feature):
  WEPO_FEATURE_PRIVACY        privacy proofs / Quantum Vault (zk-STARK)
  WEPO_FEATURE_RWA            RWA on-chain asset CREATION + reads (real, self-custody)
  WEPO_FEATURE_RWA_TRADE      RWA trading / order matching (depends on the swap engine)
  WEPO_FEATURE_BTC            Bitcoin proxy/relay, demo rates, simulated liquidity,
                              and atomic/BTC swaps
  WEPO_FEATURE_MESSAGING      private messaging relay/key registry
  WEPO_ENABLE_STAGING_TOGGLES staging-only test hooks (e.g. genesis flip)
  WEPO_FEATURE_BROWSER_MINING browser mining lab/session controls
"""
import os


def is_mainnet_profile() -> bool:
    """Fail closed unless the process explicitly selects the exact test profile."""
    return os.environ.get("WEPO_NETWORK_PROFILE", "mainnet").strip().lower() != "test"


def feature_enabled(env_name: str) -> bool:
    # Launch-gated features are test/staging opt-ins, not production switches.
    # An accidentally copied environment flag must never expose them on mainnet.
    if is_mainnet_profile():
        return False
    return os.environ.get(env_name, "").strip().lower() in ("1", "true", "yes", "on")


# Order matters: more specific prefixes are listed before broader ones so the
# most descriptive label wins (e.g. /api/dex/rwa-trade before /api/dex/swap).
LAUNCH_GATED_PREFIXES = [
    ("/api/vault", "WEPO_FEATURE_PRIVACY", "Privacy / Quantum Vault"),
    # RWA trading rides the swap engine (mock/simplified), so it keeps its OWN flag
    # and stays off even when RWA creation (real, self-custody) is enabled.
    ("/api/dex/rwa-trade", "WEPO_FEATURE_RWA_TRADE", "RWA trading"),
    ("/api/rwa", "WEPO_FEATURE_RWA", "RWA"),
    ("/api/bitcoin/relay", "WEPO_FEATURE_BTC", "Bitcoin relay"),
    ("/api/dex/swap", "WEPO_FEATURE_BTC", "Atomic swap"),
    ("/api/dex/rate", "WEPO_FEATURE_BTC", "BTC market"),
    ("/api/swap/execute", "WEPO_FEATURE_BTC", "Atomic swap"),
    ("/api/swap", "WEPO_FEATURE_BTC", "BTC market"),
    ("/api/liquidity", "WEPO_FEATURE_BTC", "BTC liquidity"),
    # Server-side address lookups leak queried Bitcoin addresses to Esplora.
    ("/api/bitcoin", "WEPO_FEATURE_BTC", "Bitcoin integration"),
    ("/api/messages", "WEPO_FEATURE_MESSAGING", "Private messaging"),
    ("/api/mining/_toggle_genesis", "WEPO_ENABLE_STAGING_TOGGLES", "Staging genesis toggle"),
    ("/api/mining/connect", "WEPO_FEATURE_BROWSER_MINING", "Browser mining"),
    ("/api/mining/start", "WEPO_FEATURE_BROWSER_MINING", "Browser mining"),
    ("/api/mining/stop", "WEPO_FEATURE_BROWSER_MINING", "Browser mining"),
    ("/api/mining/work", "WEPO_FEATURE_BROWSER_MINING", "Browser mining"),
    ("/api/mining/submit", "WEPO_FEATURE_BROWSER_MINING", "Browser mining"),
    ("/api/mining/hashrate", "WEPO_FEATURE_BROWSER_MINING", "Browser mining"),
    ("/api/mining/leaderboard", "WEPO_FEATURE_BROWSER_MINING", "Browser mining"),
    ("/api/mining/stats", "WEPO_FEATURE_BROWSER_MINING", "Browser mining"),
]


def disabled_feature_for_path(path: str):
    """Return the label of a launch-disabled feature for this path, else None."""
    for prefix, env_name, label in LAUNCH_GATED_PREFIXES:
        if path.startswith(prefix) and not feature_enabled(env_name):
            return label
    return None
