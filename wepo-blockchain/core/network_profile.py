#!/usr/bin/env python3
"""Shared WEPO network profile helpers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re

COIN = 100000000
MAINNET_SUPPLY_CAP_ATOMIC = 69_000_003 * COIN

# Mainnet is deliberately NOT finalized. These deterministic placeholder values
# keep local/rehearsal chains reproducible, but the production node service
# refuses to start mainnet while `genesis_finalized` is false. When the release
# candidate is accepted, replace both values in one reviewed consensus commit,
# set MAINNET_GENESIS_FINALIZED=True, and publish the genesis hash.
REHEARSAL_MAINNET_GENESIS_TIMESTAMP = 1735138800
REHEARSAL_MAINNET_GENESIS_ADDRESS = "wepo1q" + ("0" * 39)
MAINNET_GENESIS_TIMESTAMP = REHEARSAL_MAINNET_GENESIS_TIMESTAMP
MAINNET_GENESIS_ADDRESS = REHEARSAL_MAINNET_GENESIS_ADDRESS
MAINNET_GENESIS_FINALIZED = False

# These values are intentionally unset. Mainnet startup must not become possible
# merely because the genesis-finalized flag is flipped. The reviewed parameter
# freeze must set every decision and bind it to a signed manifest in the same
# consensus release commit.
MAINNET_GENESIS_REWARD_POLICY: str | None = None
MAINNET_EMISSION_POLICY: str | None = None
MAINNET_POS_DISPOSITION: str | None = None
MAINNET_GHOST_DISPOSITION: str | None = None
MAINNET_PARAMETER_MANIFEST_SHA256: str | None = None
MAINNET_COINBASE_MATURITY: int | None = None
MAINNET_GHOST_ACTIVATION_HEIGHT: int | None = 1
MAINNET_MINIMUM_RELAY_FEE_PER_KB: int | None = None
MAINNET_POS_CONSENSUS_READY = False
MAINNET_GHOST_CONSENSUS_READY = False
# The owner-confirmed v1 scope defers these optional on-chain surfaces. Keep
# both the disposition and the independent consensus-readiness bit in the
# frozen manifest so a later release cannot activate either feature by changing
# only an API or wallet flag.
MAINNET_RWA_DISPOSITION = "deferred"
MAINNET_MESSAGING_DISPOSITION = "deferred"
MAINNET_RWA_CONSENSUS_READY = False
MAINNET_MESSAGING_CONSENSUS_READY = False

ALLOWED_MAINNET_GENESIS_REWARD_POLICIES = frozenset({
    "burn",
    "auditable_distribution",
})
IMPLEMENTED_MAINNET_GENESIS_REWARD_POLICIES = frozenset({"auditable_distribution"})
ALLOWED_MAINNET_EMISSION_POLICIES = frozenset({
    "ceiling_only",
    "redesigned_target_cap",
    "lowered_cap",
})
IMPLEMENTED_MAINNET_EMISSION_POLICIES = frozenset({"ceiling_only"})
ALLOWED_MAINNET_FEATURE_DISPOSITIONS = frozenset({"enabled", "deferred"})
MANDATORY_MAINNET_FEATURE_DISPOSITIONS = {
    "pos": "enabled",
    "ghost": "enabled",
}
# The shared test profile must also have a deterministic genesis. Operators may
# override this before creating a separate test network, but wall-clock startup
# time can never be part of a peer-compatible network identity.
TEST_GENESIS_TIMESTAMP = 1704067200
GENESIS_BOOTSTRAP_REWARD = 400 * COIN
# Consensus amounts must never pass through binary floating point. The previous
# 16.58 and 8.29 expressions each rounded one atomic unit low on CPython.
PRE_POS_REWARD = 6_900_000 * COIN // 131_400
PHASE_2A_REWARD = 33 * COIN + 17_000_000
PHASE_2B_REWARD = 16 * COIN + 58_000_000
PHASE_2C_REWARD = 8 * COIN + 29_000_000
PHASE_2D_REWARD = 4 * COIN + 15_000_000


@dataclass(frozen=True)
class NetworkProfile:
    name: str
    network_label: str
    genesis_timestamp: int
    genesis_address: str
    genesis_finalized: bool
    # Consensus depth before block-issued value may be spent. Mainnet remains
    # deliberately unset until the parameter-freeze review approves a value.
    coinbase_maturity: int | None
    # Node-local admission rate in atomic units per 1000 canonical bytes.
    # This is relay policy, never block-consensus validity.
    minimum_relay_fee_per_kb: int | None
    pos_consensus_ready: bool
    rwa_consensus_ready: bool
    messaging_consensus_ready: bool
    block_time_initial: int
    block_time_longterm: int
    block_time_pos: int
    block_time_pow_hybrid: int
    pre_pos_duration_blocks: int
    phase_2a_blocks: int
    phase_2b_blocks: int
    phase_2c_blocks: int
    phase_2d_blocks: int
    min_stake_amount: int
    min_masternode_collateral: int
    min_pos_collateral: int
    masternode_collateral_initial: int
    pos_collateral_initial: int
    masternode_collateral_phase_2b: int
    pos_collateral_phase_2b: int
    masternode_collateral_phase_2c: int
    pos_collateral_phase_2c: int
    masternode_collateral_phase_2d: int
    pos_collateral_phase_2d: int
    masternode_collateral_post_pow: int
    pos_collateral_post_pow: int

    @property
    def total_initial_blocks(self) -> int:
        return self.pre_pos_duration_blocks

    @property
    def phase_2a_end_height(self) -> int:
        return self.pre_pos_duration_blocks + self.phase_2a_blocks

    @property
    def phase_2b_end_height(self) -> int:
        return self.phase_2a_end_height + self.phase_2b_blocks

    @property
    def phase_2c_end_height(self) -> int:
        return self.phase_2b_end_height + self.phase_2c_blocks

    @property
    def phase_2d_end_height(self) -> int:
        return self.phase_2c_end_height + self.phase_2d_blocks

    @property
    def pow_end_height(self) -> int:
        return self.phase_2d_end_height

    @property
    def pos_activation_height(self) -> int:
        return self.pre_pos_duration_blocks

    @property
    def staking_activation_delay(self) -> int:
        return self.pre_pos_duration_blocks * self.block_time_initial

    @property
    def masternode_schedule(self) -> dict[int, int]:
        return {
            0: self.masternode_collateral_initial,
            self.pre_pos_duration_blocks: self.masternode_collateral_initial,
            self.phase_2a_end_height: self.masternode_collateral_phase_2b,
            self.phase_2b_end_height: self.masternode_collateral_phase_2c,
            self.phase_2c_end_height: self.masternode_collateral_phase_2d,
            self.phase_2d_end_height: self.masternode_collateral_post_pow,
        }

    @property
    def pos_schedule(self) -> dict[int, int]:
        return {
            0: 0,
            self.pre_pos_duration_blocks: self.pos_collateral_initial,
            self.phase_2a_end_height: self.pos_collateral_phase_2b,
            self.phase_2b_end_height: self.pos_collateral_phase_2c,
            self.phase_2c_end_height: self.pos_collateral_phase_2d,
            self.phase_2d_end_height: self.pos_collateral_post_pow,
        }


def _mainnet_profile() -> NetworkProfile:
    blocks_per_year_longterm = 36_525 * 24 * 60 // (100 * 9)
    return NetworkProfile(
        name="mainnet",
        network_label="mainnet",
        genesis_timestamp=MAINNET_GENESIS_TIMESTAMP,
        genesis_address=MAINNET_GENESIS_ADDRESS,
        genesis_finalized=MAINNET_GENESIS_FINALIZED,
        coinbase_maturity=MAINNET_COINBASE_MATURITY,
        minimum_relay_fee_per_kb=MAINNET_MINIMUM_RELAY_FEE_PER_KB,
        # Canonical ML-DSA authorization and the external signer boundary exist.
        # Mainnet remains PoW-only until intended-release-image deployment,
        # extended multi-host rehearsal, and an independent audit are complete.
        pos_consensus_ready=MAINNET_POS_CONSENSUS_READY,
        rwa_consensus_ready=MAINNET_RWA_CONSENSUS_READY,
        messaging_consensus_ready=MAINNET_MESSAGING_CONSENSUS_READY,
        block_time_initial=360,
        block_time_longterm=540,
        block_time_pos=180,
        block_time_pow_hybrid=540,
        pre_pos_duration_blocks=131400,
        phase_2a_blocks=3 * blocks_per_year_longterm,
        phase_2b_blocks=6 * blocks_per_year_longterm,
        phase_2c_blocks=3 * blocks_per_year_longterm,
        phase_2d_blocks=3 * blocks_per_year_longterm,
        min_stake_amount=1000 * COIN,
        min_masternode_collateral=1000 * COIN,
        min_pos_collateral=100 * COIN,
        masternode_collateral_initial=10000 * COIN,
        pos_collateral_initial=1000 * COIN,
        masternode_collateral_phase_2b=6000 * COIN,
        pos_collateral_phase_2b=600 * COIN,
        masternode_collateral_phase_2c=3000 * COIN,
        pos_collateral_phase_2c=300 * COIN,
        masternode_collateral_phase_2d=1500 * COIN,
        pos_collateral_phase_2d=150 * COIN,
        masternode_collateral_post_pow=1000 * COIN,
        pos_collateral_post_pow=100 * COIN,
    )


def _test_profile() -> NetworkProfile:
    return NetworkProfile(
        name="test",
        network_label="test",
        genesis_timestamp=int(
            os.getenv("WEPO_TEST_GENESIS_TIMESTAMP", str(TEST_GENESIS_TIMESTAMP))
        ),
        genesis_address=os.getenv(
            "WEPO_TEST_GENESIS_ADDRESS",
            "wepo1q" + ("1" * 39),
        ),
        genesis_finalized=True,
        coinbase_maturity=int(os.getenv("WEPO_TEST_COINBASE_MATURITY", "1")),
        minimum_relay_fee_per_kb=int(
            os.getenv("WEPO_TEST_MIN_RELAY_FEE_PER_KB", "0")
        ),
        # PoS is enabled only for cryptographic consensus and signer-boundary tests.
        pos_consensus_ready=True,
        rwa_consensus_ready=True,
        messaging_consensus_ready=True,
        block_time_initial=int(os.getenv("WEPO_TEST_BLOCK_TIME_INITIAL", "15")),
        block_time_longterm=int(os.getenv("WEPO_TEST_BLOCK_TIME_LONGTERM", "20")),
        block_time_pos=int(os.getenv("WEPO_TEST_BLOCK_TIME_POS", "10")),
        block_time_pow_hybrid=int(os.getenv("WEPO_TEST_BLOCK_TIME_POW_HYBRID", "20")),
        pre_pos_duration_blocks=int(os.getenv("WEPO_TEST_PRE_POS_BLOCKS", "12")),
        phase_2a_blocks=int(os.getenv("WEPO_TEST_PHASE_2A_BLOCKS", "18")),
        phase_2b_blocks=int(os.getenv("WEPO_TEST_PHASE_2B_BLOCKS", "24")),
        phase_2c_blocks=int(os.getenv("WEPO_TEST_PHASE_2C_BLOCKS", "18")),
        phase_2d_blocks=int(os.getenv("WEPO_TEST_PHASE_2D_BLOCKS", "12")),
        min_stake_amount=int(os.getenv("WEPO_TEST_MIN_STAKE_WEPO", "100")) * COIN,
        min_masternode_collateral=int(os.getenv("WEPO_TEST_MIN_MASTERNODE_COLLATERAL_WEPO", "100")) * COIN,
        min_pos_collateral=int(os.getenv("WEPO_TEST_MIN_POS_COLLATERAL_WEPO", "25")) * COIN,
        masternode_collateral_initial=int(os.getenv("WEPO_TEST_MN_COLLATERAL_INITIAL_WEPO", "500")) * COIN,
        pos_collateral_initial=int(os.getenv("WEPO_TEST_POS_COLLATERAL_INITIAL_WEPO", "100")) * COIN,
        masternode_collateral_phase_2b=int(os.getenv("WEPO_TEST_MN_COLLATERAL_PHASE_2B_WEPO", "250")) * COIN,
        pos_collateral_phase_2b=int(os.getenv("WEPO_TEST_POS_COLLATERAL_PHASE_2B_WEPO", "50")) * COIN,
        masternode_collateral_phase_2c=int(os.getenv("WEPO_TEST_MN_COLLATERAL_PHASE_2C_WEPO", "125")) * COIN,
        pos_collateral_phase_2c=int(os.getenv("WEPO_TEST_POS_COLLATERAL_PHASE_2C_WEPO", "25")) * COIN,
        masternode_collateral_phase_2d=int(os.getenv("WEPO_TEST_MN_COLLATERAL_PHASE_2D_WEPO", "100")) * COIN,
        pos_collateral_phase_2d=int(os.getenv("WEPO_TEST_POS_COLLATERAL_PHASE_2D_WEPO", "20")) * COIN,
        masternode_collateral_post_pow=int(os.getenv("WEPO_TEST_MN_COLLATERAL_POST_POW_WEPO", "100")) * COIN,
        pos_collateral_post_pow=int(os.getenv("WEPO_TEST_POS_COLLATERAL_POST_POW_WEPO", "10")) * COIN,
    )


def build_mainnet_parameter_manifest(
    profile: NetworkProfile | None = None,
) -> dict:
    """Build the exact machine-readable release decision document."""
    candidate = profile if profile is not None else _mainnet_profile()
    if candidate.name != "mainnet":
        raise ValueError("mainnet parameter manifest requires the mainnet profile")
    return {
        "schema": "wepo-mainnet-parameter-manifest-v1",
        "status": "finalized",
        "network": "mainnet",
        "parameters": {
            "network_label": candidate.network_label,
            "genesis_timestamp": candidate.genesis_timestamp,
            "genesis_address": candidate.genesis_address,
            "genesis_bootstrap_atomic": GENESIS_BOOTSTRAP_REWARD,
            "genesis_reward_policy": MAINNET_GENESIS_REWARD_POLICY,
            "supply_cap_atomic": MAINNET_SUPPLY_CAP_ATOMIC,
            "emission_policy": MAINNET_EMISSION_POLICY,
            "coinbase_maturity_blocks": candidate.coinbase_maturity,
            "minimum_relay_fee_per_kb_atomic": candidate.minimum_relay_fee_per_kb,
            "pos_disposition": MAINNET_POS_DISPOSITION,
            "pos_consensus_ready": candidate.pos_consensus_ready,
            "rwa_disposition": MAINNET_RWA_DISPOSITION,
            "rwa_consensus_ready": candidate.rwa_consensus_ready,
            "messaging_disposition": MAINNET_MESSAGING_DISPOSITION,
            "messaging_consensus_ready": candidate.messaging_consensus_ready,
            "ghost_disposition": MAINNET_GHOST_DISPOSITION,
            "ghost_activation_height": MAINNET_GHOST_ACTIVATION_HEIGHT,
            "ghost_consensus_ready": MAINNET_GHOST_CONSENSUS_READY,
            "block_time_initial_seconds": candidate.block_time_initial,
            "block_time_longterm_seconds": candidate.block_time_longterm,
            "block_time_pos_seconds": candidate.block_time_pos,
            "block_time_pow_hybrid_seconds": candidate.block_time_pow_hybrid,
            "pre_pos_duration_blocks": candidate.pre_pos_duration_blocks,
            "phase_2a_blocks": candidate.phase_2a_blocks,
            "phase_2b_blocks": candidate.phase_2b_blocks,
            "phase_2c_blocks": candidate.phase_2c_blocks,
            "phase_2d_blocks": candidate.phase_2d_blocks,
            "minimum_stake_atomic": candidate.min_stake_amount,
            "minimum_masternode_collateral_atomic": candidate.min_masternode_collateral,
            "minimum_pos_collateral_atomic": candidate.min_pos_collateral,
            "masternode_collateral_schedule_atomic": {
                str(height): amount
                for height, amount in candidate.masternode_schedule.items()
            },
            "pos_collateral_schedule_atomic": {
                str(height): amount
                for height, amount in candidate.pos_schedule.items()
            },
        },
    }


def render_mainnet_parameter_manifest(
    profile: NetworkProfile | None = None,
) -> bytes:
    """Return the canonical UTF-8 bytes whose raw digest is frozen in source."""
    return (
        json.dumps(build_mainnet_parameter_manifest(profile), sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def mainnet_release_blockers(
    profile: NetworkProfile | None = None,
    manifest_path: str | os.PathLike[str] | None = None,
) -> tuple[str, ...]:
    """Return stable blocker codes for a partially finalized mainnet profile.

    This is deliberately stricter than any individual consensus parameter. A
    release commit may open mainnet only when the entire reviewed decision set
    and its signed-manifest digest are present and internally consistent.
    """
    candidate = profile if profile is not None else _mainnet_profile()
    if candidate.name != "mainnet":
        raise ValueError("mainnet release readiness requires the mainnet profile")

    blockers: list[str] = []
    if not candidate.genesis_finalized:
        blockers.append("genesis_parameters_unfinalized")
    if candidate.genesis_timestamp == REHEARSAL_MAINNET_GENESIS_TIMESTAMP:
        blockers.append("genesis_timestamp_is_rehearsal_placeholder")
    if candidate.genesis_address == REHEARSAL_MAINNET_GENESIS_ADDRESS:
        blockers.append("genesis_address_is_rehearsal_placeholder")

    if MAINNET_GENESIS_REWARD_POLICY is None:
        blockers.append("genesis_reward_policy_unset")
    elif MAINNET_GENESIS_REWARD_POLICY not in ALLOWED_MAINNET_GENESIS_REWARD_POLICIES:
        blockers.append("genesis_reward_policy_invalid")
    elif (
        MAINNET_GENESIS_REWARD_POLICY
        not in IMPLEMENTED_MAINNET_GENESIS_REWARD_POLICIES
    ):
        blockers.append("genesis_reward_policy_not_implemented")

    if MAINNET_EMISSION_POLICY is None:
        blockers.append("emission_policy_unset")
    elif MAINNET_EMISSION_POLICY not in ALLOWED_MAINNET_EMISSION_POLICIES:
        blockers.append("emission_policy_invalid")
    elif MAINNET_EMISSION_POLICY not in IMPLEMENTED_MAINNET_EMISSION_POLICIES:
        blockers.append("emission_policy_not_implemented")

    if candidate.coinbase_maturity is None:
        blockers.append("coinbase_maturity_unset")
    elif type(candidate.coinbase_maturity) is not int or candidate.coinbase_maturity <= 0:
        blockers.append("coinbase_maturity_invalid")

    if candidate.minimum_relay_fee_per_kb is None:
        blockers.append("minimum_relay_fee_unset")
    elif (
        type(candidate.minimum_relay_fee_per_kb) is not int
        or candidate.minimum_relay_fee_per_kb < 0
    ):
        blockers.append("minimum_relay_fee_invalid")

    if MAINNET_POS_DISPOSITION is None:
        blockers.append("pos_disposition_unset")
    elif MAINNET_POS_DISPOSITION not in ALLOWED_MAINNET_FEATURE_DISPOSITIONS:
        blockers.append("pos_disposition_invalid")
    elif MAINNET_POS_DISPOSITION != MANDATORY_MAINNET_FEATURE_DISPOSITIONS["pos"]:
        blockers.append("pos_required_at_launch_but_deferred")
        if candidate.pos_consensus_ready:
            blockers.append("pos_deferred_but_consensus_enabled")
    elif not candidate.pos_consensus_ready:
        blockers.append("pos_enabled_but_consensus_not_ready")

    if MAINNET_RWA_DISPOSITION not in ALLOWED_MAINNET_FEATURE_DISPOSITIONS:
        blockers.append("rwa_disposition_invalid")
    elif (
        MAINNET_RWA_DISPOSITION == "enabled"
        and not candidate.rwa_consensus_ready
    ):
        blockers.append("rwa_enabled_but_consensus_not_ready")
    elif (
        MAINNET_RWA_DISPOSITION == "deferred"
        and candidate.rwa_consensus_ready
    ):
        blockers.append("rwa_deferred_but_consensus_enabled")

    if MAINNET_MESSAGING_DISPOSITION not in ALLOWED_MAINNET_FEATURE_DISPOSITIONS:
        blockers.append("messaging_disposition_invalid")
    elif (
        MAINNET_MESSAGING_DISPOSITION == "enabled"
        and not candidate.messaging_consensus_ready
    ):
        blockers.append("messaging_enabled_but_consensus_not_ready")
    elif (
        MAINNET_MESSAGING_DISPOSITION == "deferred"
        and candidate.messaging_consensus_ready
    ):
        blockers.append("messaging_deferred_but_consensus_enabled")

    if MAINNET_GHOST_DISPOSITION is None:
        blockers.append("ghost_disposition_unset")
    elif MAINNET_GHOST_DISPOSITION not in ALLOWED_MAINNET_FEATURE_DISPOSITIONS:
        blockers.append("ghost_disposition_invalid")
    elif MAINNET_GHOST_DISPOSITION != MANDATORY_MAINNET_FEATURE_DISPOSITIONS["ghost"]:
        blockers.append("ghost_required_at_launch_but_deferred")
        if MAINNET_GHOST_CONSENSUS_READY:
            blockers.append("ghost_deferred_but_consensus_enabled")
    elif not MAINNET_GHOST_CONSENSUS_READY:
        blockers.append("ghost_enabled_but_consensus_not_ready")

    if MAINNET_GHOST_ACTIVATION_HEIGHT is None:
        blockers.append("ghost_activation_height_unset")
    elif type(MAINNET_GHOST_ACTIVATION_HEIGHT) is not int or MAINNET_GHOST_ACTIVATION_HEIGHT < 1:
        blockers.append("ghost_activation_height_invalid")

    manifest_sha256 = MAINNET_PARAMETER_MANIFEST_SHA256
    if manifest_sha256 is None:
        blockers.append("parameter_manifest_sha256_unset")
    elif re.fullmatch(r"[0-9a-f]{64}", manifest_sha256) is None:
        blockers.append("parameter_manifest_sha256_invalid")
    else:
        selected_path = (
            Path(manifest_path)
            if manifest_path is not None
            else Path(__file__).resolve().parents[2]
            / "MAINNET_PARAMETER_MANIFEST.json"
        )
        try:
            manifest_bytes = selected_path.read_bytes()
        except FileNotFoundError:
            blockers.append("parameter_manifest_missing")
        except OSError:
            blockers.append("parameter_manifest_unreadable")
        else:
            actual_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
            if actual_sha256 != manifest_sha256:
                blockers.append("parameter_manifest_sha256_mismatch")
            else:
                try:
                    manifest = json.loads(manifest_bytes.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    blockers.append("parameter_manifest_json_invalid")
                else:
                    if manifest != build_mainnet_parameter_manifest(candidate):
                        blockers.append("parameter_manifest_content_mismatch")


    return tuple(blockers)


def mainnet_release_ready(
    profile: NetworkProfile | None = None,
    manifest_path: str | os.PathLike[str] | None = None,
) -> bool:
    """Return true only for a fully populated, internally consistent profile."""
    return not mainnet_release_blockers(profile, manifest_path)


def get_network_profile(name: str | None) -> NetworkProfile:
    normalized = (name or "mainnet").strip().lower()
    if normalized == "mainnet":
        return _mainnet_profile()
    if normalized == "test":
        return _test_profile()
    raise ValueError(f"Unsupported network profile: {name}")


def build_collateral_schedule(profile: NetworkProfile) -> list[dict]:
    return [
        {
            "height": 0,
            "mn": int(profile.masternode_collateral_initial / COIN),
            "pos": 0,
            "phase": "Phase 1",
            "desc": "Genesis -> PoS Activation",
            "pos_avail": False,
        },
        {
            "height": profile.pre_pos_duration_blocks,
            "mn": int(profile.masternode_collateral_initial / COIN),
            "pos": int(profile.pos_collateral_initial / COIN),
            "phase": "Phase 2A",
            "desc": "PoS Activation -> 2nd Halving",
            "pos_avail": True,
        },
        {
            "height": profile.phase_2a_end_height,
            "mn": int(profile.masternode_collateral_phase_2b / COIN),
            "pos": int(profile.pos_collateral_phase_2b / COIN),
            "phase": "Phase 2B",
            "desc": "2nd Halving -> 3rd Halving",
            "pos_avail": True,
        },
        {
            "height": profile.phase_2b_end_height,
            "mn": int(profile.masternode_collateral_phase_2c / COIN),
            "pos": int(profile.pos_collateral_phase_2c / COIN),
            "phase": "Phase 2C",
            "desc": "3rd Halving -> 4th Halving",
            "pos_avail": True,
        },
        {
            "height": profile.phase_2c_end_height,
            "mn": int(profile.masternode_collateral_phase_2d / COIN),
            "pos": int(profile.pos_collateral_phase_2d / COIN),
            "phase": "Phase 2D",
            "desc": "4th Halving -> 5th Halving",
            "pos_avail": True,
        },
        {
            "height": profile.phase_2d_end_height,
            "mn": int(profile.masternode_collateral_post_pow / COIN),
            "pos": int(profile.pos_collateral_post_pow / COIN),
            "phase": "Phase 3",
            "desc": "Post-PoW Era",
            "pos_avail": True,
        },
    ]


def get_reward_phase_label(profile: NetworkProfile, height: int) -> str:
    if height <= 0:
        return "Genesis bootstrap"
    if height <= profile.pre_pos_duration_blocks:
        return "Pre-PoS"
    if height <= profile.phase_2a_end_height:
        return "Phase 2A"
    if height <= profile.phase_2b_end_height:
        return "Phase 2B"
    if height <= profile.phase_2c_end_height:
        return "Phase 2C"
    if height <= profile.phase_2d_end_height:
        return "Phase 2D"
    return "Post-PoW"


def get_pow_reward_for_height(profile: NetworkProfile, height: int) -> int:
    if height <= 0:
        return GENESIS_BOOTSTRAP_REWARD
    if height <= profile.pre_pos_duration_blocks:
        return PRE_POS_REWARD
    if height <= profile.phase_2a_end_height:
        return PHASE_2A_REWARD
    if height <= profile.phase_2b_end_height:
        return PHASE_2B_REWARD
    if height <= profile.phase_2c_end_height:
        return PHASE_2C_REWARD
    if height <= profile.phase_2d_end_height:
        return PHASE_2D_REWARD
    return 0


def get_pow_block_time_seconds(profile: NetworkProfile, height: int) -> int:
    if height <= profile.pre_pos_duration_blocks:
        return profile.block_time_initial
    return profile.block_time_pow_hybrid


def format_block_time(seconds: int) -> str:
    if seconds < 60:
        unit = "second" if seconds == 1 else "seconds"
        return f"{seconds} {unit}"

    minutes, remainder = divmod(seconds, 60)
    minute_unit = "minute" if minutes == 1 else "minutes"
    if remainder == 0:
        return f"{minutes} {minute_unit}"

    second_unit = "second" if remainder == 1 else "seconds"
    return f"{minutes} {minute_unit} {remainder} {second_unit}"


def describe_reward_schedule(profile: NetworkProfile) -> str:
    return (
        f"{profile.name} profile: pre-PoS through block {profile.pre_pos_duration_blocks}, "
        f"hybrid phase through block {profile.pow_end_height}, "
        f"post-PoW afterward"
    )
