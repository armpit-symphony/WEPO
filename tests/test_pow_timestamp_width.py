"""Consensus regression for the 64-bit timestamp in the Argon2 PoW preimage."""

from __future__ import annotations

from pathlib import Path
import struct
import sys


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from blockchain import BlockHeader, WepoArgon2Miner  # noqa: E402


def _header(timestamp: int) -> BlockHeader:
    return BlockHeader(
        version=1,
        prev_hash="11" * 32,
        merkle_root="22" * 32,
        timestamp=timestamp,
        bits=1,
        nonce=7,
        consensus_type="pow",
    )


def test_pow_preimage_supports_the_full_header_timestamp_width():
    miner = WepoArgon2Miner()
    timestamp = 0x1_0000_0000
    header = _header(timestamp)

    pow_input = miner._build_pow_input(header)
    numeric = struct.unpack("<I32s32sQII", pow_input[:-3])

    assert numeric[0] == header.version
    assert numeric[1] == bytes.fromhex(header.prev_hash)
    assert numeric[2] == bytes.fromhex(header.merkle_root)
    assert numeric[3] == timestamp
    assert numeric[4] == header.bits
    assert numeric[5] == header.nonce
    assert pow_input[-3:] == b"pow"

    high_hash = miner.calculate_pow_hash(header)
    low_hash = miner.calculate_pow_hash(_header(0))
    assert len(high_hash) == 64
    assert high_hash != low_hash
