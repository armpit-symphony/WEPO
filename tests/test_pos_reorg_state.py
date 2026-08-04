#!/usr/bin/env python3
"""PoS slot pacing and branch-aware stake-state reorg regressions.

Run: python -X utf8 tests/test_pos_reorg_state.py
"""

import json
import os
import shutil
import sys
import tempfile
import time
from unittest.mock import patch

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

from address_utils import generate_wepo_address  # noqa: E402
from dilithium import generate_dilithium_keypair, sign_with_dilithium  # noqa: E402

VALIDATOR_KEYPAIR = generate_dilithium_keypair()
VALIDATOR_ADDRESS = generate_wepo_address(
    VALIDATOR_KEYPAIR.public_key,
    address_type="quantum",
)

os.environ["WEPO_NETWORK_PROFILE"] = "test"
os.environ["WEPO_TEST_GENESIS_ADDRESS"] = VALIDATOR_ADDRESS
os.environ["WEPO_TEST_GENESIS_TIMESTAMP"] = str(int(time.time()) - 3600)

import blockchain as consensus  # noqa: E402
from blockchain import COIN, WepoBlockchain  # noqa: E402

FAILURES = []


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


class ValidatorSigner:
    def get_public_key(self, validator_address):
        return VALIDATOR_KEYPAIR.public_key

    def sign(self, validator_address, message, *, context):
        return sign_with_dilithium(message, VALIDATOR_KEYPAIR.private_key)


def mine_pow(chain, miner_address):
    block = chain.mine_block(miner_address)
    if block is None:
        raise AssertionError("Unable to mine test PoW block")
    return block


def copy_block(source_chain, target_chain, block):
    copied = target_chain.deserialize_block(json.loads(source_chain.serialize_block(block)))
    if not target_chain.add_block(copied):
        raise AssertionError(f"Unable to copy common block {block.height}")
    return copied


def main():
    old_activation = consensus.POS_ACTIVATION_HEIGHT
    old_min_stake = consensus.MIN_STAKE_AMOUNT
    first_dir = tempfile.mkdtemp(prefix="wepo-pos-reorg-main-")
    second_dir = tempfile.mkdtemp(prefix="wepo-pos-reorg-side-")
    try:
        main_chain = WepoBlockchain(data_dir=first_dir, network_profile="test")
        side_chain = WepoBlockchain(data_dir=second_dir, network_profile="test")
        consensus.POS_ACTIVATION_HEIGHT = 0
        consensus.MIN_STAKE_AMOUNT = 1

        check(
            "independent nodes start from the same deterministic genesis",
            main_chain.get_latest_block().get_block_hash()
            == side_chain.get_latest_block().get_block_hash(),
        )

        # Height 1 passes activation so the canonical stake-create API can be
        # exercised using the validator-owned genesis allocation.
        common_one = mine_pow(main_chain, VALIDATOR_ADDRESS)
        copy_block(main_chain, side_chain, common_one)

        stake_tx = main_chain.create_stake(
            VALIDATOR_ADDRESS,
            100 * COIN,
            return_unsigned=True,
        )
        stake_id = stake_tx.extra_data["stake_id"]
        stake_tx.sign_all_inputs(
            VALIDATOR_KEYPAIR.private_key,
            VALIDATOR_KEYPAIR.public_key,
        )
        check(
            "signed stake creation enters the common branch",
            main_chain.add_transaction_to_mempool(stake_tx),
        )
        common_two = mine_pow(main_chain, VALIDATOR_ADDRESS)
        copy_block(main_chain, side_chain, common_two)
        check(
            "stake is active on both nodes before the fork",
            len(main_chain.get_active_stakes()) == 1
            and len(side_chain.get_active_stakes()) == 1,
        )

        # The current canonical branch deactivates the stake at height 3.
        deactivate_tx = main_chain.deactivate_stake(
            stake_id,
            VALIDATOR_ADDRESS,
            return_unsigned=True,
        )
        deactivate_tx.sign_all_inputs(
            VALIDATOR_KEYPAIR.private_key,
            VALIDATOR_KEYPAIR.public_key,
        )
        check(
            "signed stake deactivation enters the canonical branch",
            main_chain.add_transaction_to_mempool(deactivate_tx),
        )
        canonical_three = mine_pow(main_chain, VALIDATOR_ADDRESS)
        check(
            "stake is inactive on the original canonical branch",
            len(main_chain.get_active_stakes()) == 0,
        )

        # The competing branch keeps the stake active and has a distinct PoW
        # block at height 3, followed by one properly paced PoS block.
        alternate_miner = generate_wepo_address(
            generate_dilithium_keypair().public_key,
            address_type="quantum",
        )
        side_three = mine_pow(side_chain, alternate_miner)
        check(
            "fork blocks have distinct identities",
            side_three.get_block_hash() != canonical_three.get_block_hash(),
        )

        signer = ValidatorSigner()
        too_early_time = side_three.header.timestamp + consensus.BLOCK_TIME_POS - 1
        with patch("blockchain.time.time", return_value=too_early_time):
            early_template = side_chain.create_pos_block_template(
                VALIDATOR_ADDRESS,
                VALIDATOR_KEYPAIR.public_key,
            )
        early_signature = sign_with_dilithium(
            side_chain.get_pos_signing_message(early_template),
            VALIDATOR_KEYPAIR.private_key,
        )
        check(
            "PoS block before the next slot is rejected",
            side_chain.finalize_pos_block(early_template, early_signature) is None,
        )

        slot_time = side_three.header.timestamp + consensus.BLOCK_TIME_POS
        with patch("blockchain.time.time", return_value=slot_time):
            side_four = side_chain._produce_pos_block(VALIDATOR_ADDRESS, signer)
        check(
            "properly paced side-branch PoS block is valid",
            side_four is not None and side_chain.add_block(side_four),
        )

        check(
            "equal-work competing PoW block is retained without immediate reorg",
            main_chain.add_block_with_priority(
                main_chain.deserialize_block(json.loads(side_chain.serialize_block(side_three)))
            )
            is False,
        )
        adopted = main_chain.add_block_with_priority(
            main_chain.deserialize_block(json.loads(side_chain.serialize_block(side_four)))
        )
        check("higher-score PoS side branch is adopted", adopted)
        check(
            "adopted tip is the side-branch PoS block",
            main_chain.get_latest_block().get_block_hash() == side_four.get_block_hash(),
        )
        check(
            "stake state is replayed from the adopted branch, not the old tip",
            len(main_chain.get_active_stakes()) == 1
            and main_chain.get_active_stakes()[0].stake_id == stake_id,
        )
    finally:
        consensus.POS_ACTIVATION_HEIGHT = old_activation
        consensus.MIN_STAKE_AMOUNT = old_min_stake
        shutil.rmtree(first_dir, ignore_errors=True)
        shutil.rmtree(second_dir, ignore_errors=True)

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
