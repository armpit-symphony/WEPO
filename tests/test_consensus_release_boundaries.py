#!/usr/bin/env python3
"""Release-boundary regressions for genesis, time, work, and PoS.

Run: python3 tests/test_consensus_release_boundaries.py
"""

import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

from address_utils import is_quantum_address  # noqa: E402
from blockchain import WepoBlockchain  # noqa: E402
from network_profile import get_network_profile  # noqa: E402

FAILURES = []


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


class WorkHeader:
    def __init__(self, difficulty, consensus_type):
        self.bits = difficulty
        self.consensus_type = consensus_type

    def is_pow_block(self):
        return self.consensus_type == "pow"


def work_block(difficulty, consensus_type="pow"):
    header = WorkHeader(difficulty, consensus_type)
    return SimpleNamespace(header=header)


def main():
    temp_dir = tempfile.mkdtemp(prefix="wepo-release-boundaries-")
    try:
        profile = get_network_profile("mainnet")
        chain = WepoBlockchain(data_dir=temp_dir, network_profile="mainnet")
        genesis = chain.get_latest_block()

        print("Consensus release boundaries:")
        check("mainnet genesis remains explicitly unfinalized", profile.genesis_finalized is False)
        check(
            "genesis reward uses a quantum-resistant address",
            is_quantum_address(genesis.transactions[0].outputs[0].address),
        )

        chain.fixed_difficulty = 1
        chain.current_difficulty = 1
        candidate = chain.create_new_block(profile.genesis_address)
        candidate.header.timestamp = genesis.header.timestamp - 1
        check(
            "block 1 before genesis is rejected",
            chain.validate_block(candidate) is False,
        )

        candidate.header.timestamp = genesis.header.timestamp
        check(
            "non-monotonic block timestamp is rejected",
            chain.validate_block(candidate) is False,
        )

        low_work = chain._block_chainwork(work_block(1))
        high_work = chain._block_chainwork(work_block(2))
        check("each hex difficulty step represents 16x work", high_work == low_work * 16)
        check(
            "shorter higher-work chain beats longer low-work chain",
            chain._chain_score([work_block(2)]) > chain._chain_score([work_block(1)] * 15),
        )

        many_pos_blocks = [
            work_block(0, consensus_type="pos") for _ in range(100)
        ]
        check(
            "PoS blocks cannot outweigh a branch with more cumulative PoW",
            chain._chain_score([work_block(1)]) > chain._chain_score(many_pos_blocks),
        )
        check(
            "valid PoS progress breaks ties only after cumulative PoW is equal",
            chain._chain_score([work_block(1), many_pos_blocks[0]]) > chain._chain_score([work_block(1)]),
        )

        pos_candidate = work_block(0, consensus_type="pos")
        check(
            "mainnet PoS remains disabled pending production signer deployment and audit",
            chain.validate_pos_block(pos_candidate) is False,
        )
        check(
            "mainnet PoS production is disabled",
            chain.create_pos_block_template(profile.genesis_address, b"") is None,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

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
