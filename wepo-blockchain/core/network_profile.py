#!/usr/bin/env python3
"""Shared WEPO network profile helpers."""

from __future__ import annotations

from dataclasses import dataclass
import os
import time

COIN = 100000000

MAINNET_GENESIS_TIMESTAMP = 1735138800
GENESIS_BOOTSTRAP_REWARD = 400 * COIN
PRE_POS_REWARD = int(6900000 * COIN / 131400)
PHASE_2A_REWARD = int(33.17 * COIN)
PHASE_2B_REWARD = int(16.58 * COIN)
PHASE_2C_REWARD = int(8.29 * COIN)
PHASE_2D_REWARD = int(4.15 * COIN)


@dataclass(frozen=True)
class NetworkProfile:
    name: str
    network_label: str
    genesis_timestamp: int
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
    blocks_per_year_longterm = int(365.25 * 24 * 60 / 9)
    return NetworkProfile(
        name="mainnet",
        network_label="mainnet",
        genesis_timestamp=MAINNET_GENESIS_TIMESTAMP,
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
        genesis_timestamp=int(os.getenv("WEPO_TEST_GENESIS_TIMESTAMP", str(int(time.time())))),
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
