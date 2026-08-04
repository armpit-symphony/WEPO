"""Pure builders for truthful, live-node status API responses."""

from typing import Any, Dict, Iterable, Optional


ATOMIC_UNITS_PER_WEPO = 100_000_000


def _non_negative_int(value: Any, field: str) -> int:
    if type(value) is bool:
        raise ValueError(f"{field} must be a non-negative integer")
    result = int(value)
    if result < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return result

def _required_non_negative_int(
    payload: Dict[str, Any],
    names: Iterable[str],
    field: str,
) -> int:
    for name in names:
        if name in payload and payload[name] is not None:
            return _non_negative_int(payload[name], field)
    raise ValueError(f"{field} is required")



def build_network_status(
    node_status: Dict[str, Any],
    *,
    staking_status: Optional[Dict[str, Any]] = None,
    masternodes: Optional[Iterable[Any]] = None,
    observed_at: int,
) -> Dict[str, Any]:
    """Normalize canonical node data without inventing unavailable telemetry."""
    if not isinstance(node_status, dict):
        raise ValueError("node_status must be an object")

    height = _required_non_negative_int(
        node_status,
        ("height", "chain_height"),
        "height",
    )
    issued_atomic = _required_non_negative_int(
        node_status, ("total_supply",), "total_supply"
    )
    cap_atomic = _required_non_negative_int(
        node_status, ("supply_cap",), "supply_cap"
    )
    staking_status = staking_status if isinstance(staking_status, dict) else {}
    relay_fee_rate = _required_non_negative_int(
        node_status,
        ("minimum_relay_fee_per_kb",),
        "minimum_relay_fee_per_kb",
    )

    return {
        "source": "live_node",
        "observed_at": int(observed_at),
        "block_height": height,
        "height": height,
        "best_block_hash": node_status.get(
            "best_block_hash", node_status.get("latest_block_hash")
        ),
        "network": node_status.get("network"),
        "network_profile": node_status.get("network_profile"),
        "consensus_type": node_status.get("consensus_type"),
        "difficulty": node_status.get("difficulty"),
        "peers": node_status.get("peers"),
        "connections": node_status.get("connections"),
        "network_hashrate": None,
        "network_hashrate_available": False,
        "active_masternodes": (
            None if masternodes is None else len(list(masternodes))
        ),
        "total_staked": staking_status.get("total_staked"),
        "total_supply_atomic": issued_atomic,
        "total_supply": issued_atomic / ATOMIC_UNITS_PER_WEPO,
        "supply_cap_atomic": cap_atomic,
        "supply_cap": cap_atomic / ATOMIC_UNITS_PER_WEPO,
        "minimum_relay_fee_per_kb_atomic": relay_fee_rate,
    }


def build_mining_status(
    node_status: Dict[str, Any],
    mining_info: Dict[str, Any],
    *,
    connected_browser_sessions: int,
    reported_browser_hashrate: float,
    observed_at: int,
) -> Dict[str, Any]:
    """Describe node mining state while labeling browser-only telemetry."""
    if not isinstance(mining_info, dict):
        raise ValueError("mining_info must be an object")

    height = _required_non_negative_int(
        node_status,
        ("height", "chain_height"),
        "height",
    )
    genesis_found = bool(
        node_status.get("best_block_hash", node_status.get("latest_block_hash"))
    )
    consensus_type = node_status.get("consensus_type")
    mining_enabled = bool(mining_info.get("mining_enabled"))

    if not genesis_found:
        mode = "pre-genesis"
        mode_display = "Genesis not available"
    elif not mining_enabled:
        mode = consensus_type or "online"
        mode_display = "Node online — mining API disabled"
    else:
        mode = consensus_type or "pow"
        mode_display = "Consensus mining available"

    return {
        "source": "live_node",
        "observed_at": int(observed_at),
        "node_reachable": True,
        "network": mining_info.get("network", node_status.get("network")),
        "network_profile": mining_info.get(
            "network_profile", node_status.get("network_profile")
        ),
        "block_height": height,
        "best_block_hash": node_status.get(
            "best_block_hash", node_status.get("latest_block_hash")
        ),
        "genesis_status": "found" if genesis_found else "unavailable",
        "genesis_launch_time": None,
        "mining_mode": mode,
        "mode_display": mode_display,
        "mining_enabled": mining_enabled,
        "background_mining_enabled": bool(
            mining_info.get("background_mining_enabled")
        ),
        "network_difficulty": mining_info.get(
            "difficulty", node_status.get("difficulty")
        ),
        "network_hashrate": None,
        "network_hashrate_available": False,
        "connected_browser_sessions": _non_negative_int(
            connected_browser_sessions, "connected_browser_sessions"
        ),
        "reported_browser_hashrate": max(0.0, float(reported_browser_hashrate)),
    }
