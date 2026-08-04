"""Exact integer difficulty-retarget and phase-boundary regressions."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import sys


os.environ.setdefault("WEPO_NETWORK_PROFILE", "test")
ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

import blockchain as B  # noqa: E402


def _chain_with_elapsed(elapsed, *, bits=4):
    interval_count = 9
    base_spacing, remainder = divmod(elapsed, interval_count)
    timestamp = 0
    blocks = [
        SimpleNamespace(
            header=SimpleNamespace(
                timestamp=timestamp,
                bits=bits,
                consensus_type="pow",
            )
        )
    ]
    for index in range(interval_count):
        timestamp += base_spacing + (1 if index < remainder else 0)
        blocks.append(
            SimpleNamespace(
                header=SimpleNamespace(
                    timestamp=timestamp,
                    bits=bits,
                    consensus_type="pow",
                )
            )
        )
    return blocks


def _difficulty(elapsed, current_height, *, bits=4):
    chain = object.__new__(B.WepoBlockchain)
    chain.fixed_difficulty = None
    chain.current_difficulty = bits
    chain.chain = _chain_with_elapsed(elapsed, bits=bits)
    chain.get_block_height = lambda: current_height
    return chain.calculate_expected_difficulty()


def test_retarget_uses_exact_boundaries_and_next_block_phase():
    initial_target = B.BLOCK_TIME_INITIAL_18_MONTHS
    long_target = B.BLOCK_TIME_POW_HYBRID
    base = 4
    interval_count = 9
    lower_scaled = initial_target * 3 * interval_count
    upper_scaled = initial_target * 5 * interval_count
    lower_below = (lower_scaled - 1) // 4
    lower_at_or_above = (lower_scaled + 3) // 4
    upper_at_or_below = upper_scaled // 4
    upper_above = upper_at_or_below + 1
    initial_height = min(100, B.TOTAL_INITIAL_BLOCKS - 1)

    assert _difficulty(lower_below, initial_height, bits=base) == base + 1
    assert _difficulty(lower_at_or_above, initial_height, bits=base) == base
    assert _difficulty(upper_at_or_below, initial_height, bits=base) == base
    assert _difficulty(upper_above, initial_height, bits=base) == base - 1

    # When the current tip is the final initial-phase block, the candidate is
    # already in the long-term phase and must use that phase's target.
    post_phase_fast = (long_target * 3 * interval_count - 1) // 4
    assert (
        _difficulty(
            post_phase_fast,
            B.TOTAL_INITIAL_BLOCKS,
            bits=base,
        )
        == base + 1
    )


def test_hybrid_retarget_ignores_pos_bits_and_timestamps():
    bits = 5
    pow_spacing = B.BLOCK_TIME_POW_HYBRID
    blocks = []
    for index in range(10):
        pow_timestamp = index * pow_spacing
        blocks.append(
            SimpleNamespace(
                header=SimpleNamespace(
                    timestamp=pow_timestamp,
                    bits=bits,
                    consensus_type="pow",
                )
            )
        )
        blocks.append(
            SimpleNamespace(
                header=SimpleNamespace(
                    timestamp=pow_timestamp + max(1, pow_spacing // 2),
                    bits=0,
                    consensus_type="pos",
                )
            )
        )

    chain = object.__new__(B.WepoBlockchain)
    chain.fixed_difficulty = None
    chain.current_difficulty = bits
    chain.chain = blocks
    chain.get_block_height = lambda: B.TOTAL_INITIAL_BLOCKS + len(blocks)

    assert chain.chain[-1].header.consensus_type == "pos"
    assert chain.chain[-1].header.bits == 0
    assert chain.calculate_expected_difficulty() == bits
