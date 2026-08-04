#!/usr/bin/env python3
"""PoS validator-key authorization and header-binding regressions.

Run: python3 tests/test_pos_validator_signatures.py
"""

import copy
import json
import os
import shutil
import sys
from unittest.mock import patch
import tempfile
from dataclasses import replace

os.environ["WEPO_NETWORK_PROFILE"] = "test"

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

import blockchain as consensus  # noqa: E402
from address_utils import generate_wepo_address  # noqa: E402
from blockchain import StakeInfo, WepoBlockchain  # noqa: E402
from dilithium import generate_dilithium_keypair, sign_with_dilithium  # noqa: E402

FAILURES = []


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


def make_validator(stake_id, amount=100):
    keypair = generate_dilithium_keypair()
    address = generate_wepo_address(keypair.public_key, address_type="quantum")
    stake = StakeInfo(
        stake_id=stake_id,
        staker_address=address,
        amount=amount,
        start_height=0,
        start_time=0,
    )
    return keypair, address, stake




def sign_template(chain, validator_address, keypair):
    latest = chain.get_latest_block()
    last_pos_timestamp = chain.get_last_block_timestamp("pos")
    slot_anchor = last_pos_timestamp if last_pos_timestamp is not None else latest.header.timestamp
    with patch(
        "blockchain.time.time", return_value=slot_anchor + consensus.BLOCK_TIME_POS
    ):
        block = chain.create_pos_block_template(validator_address, keypair.public_key)
    if block is None:
        return None
    signature = sign_with_dilithium(
        chain.get_pos_signing_message(block), keypair.private_key
    )
    return chain.finalize_pos_block(block, signature)

def main():
    old_activation = consensus.POS_ACTIVATION_HEIGHT
    old_min_stake = consensus.MIN_STAKE_AMOUNT

    temp_dir = tempfile.mkdtemp(prefix="wepo-pos-signatures-")
    try:
        chain = WepoBlockchain(data_dir=temp_dir, network_profile="test")
        consensus.POS_ACTIVATION_HEIGHT = 0
        consensus.MIN_STAKE_AMOUNT = 1
        keypair, address, stake = make_validator("stake-a")
        other_keypair, other_address, other_stake = make_validator("stake-b")
        chain.get_active_stakes = lambda: [stake]

        print("PoS validator signatures:")
        block = sign_template(chain, address, keypair)
        check("selected validator can create a signed PoS block", block is not None)
        check("valid ML-DSA PoS signature is accepted", chain.validate_pos_block(block))
        check("valid signed PoS block passes full block validation", chain.validate_block(block))

        check("consensus runtime exposes no private-key signing method", not hasattr(chain, "sign_pos_block"))
        check(
            "validator address must be owned by the supplied public key",
            chain.create_pos_block_template(address, other_keypair.public_key) is None,
        )

        forged = copy.deepcopy(block)
        forged.header.validator_signature = bytes(len(forged.header.validator_signature))
        check("same-length forged signature is rejected", not chain.validate_pos_block(forged))

        tampered_time = copy.deepcopy(block)
        tampered_time.header.timestamp += 1
        check("signature commits to timestamp", not chain.validate_pos_block(tampered_time))

        tampered_merkle = copy.deepcopy(block)
        tampered_merkle.header.merkle_root = "1" * 64
        check("signature commits to Merkle root", not chain.validate_pos_block(tampered_merkle))

        substituted_key = copy.deepcopy(block)
        substituted_key.header.validator_public_key = other_keypair.public_key
        check("public-key substitution is rejected", not chain.validate_pos_block(substituted_key))

        replay_height = copy.deepcopy(block)
        replay_height.height += 1
        check("signature cannot be replayed at another height", not chain.validate_pos_block(replay_height))

        original_profile = chain.network_profile
        chain.network_profile = replace(original_profile, name="other-test-network")
        check("signature cannot be replayed on another network", not chain.validate_pos_block(block))
        chain.network_profile = original_profile

        encoded = json.loads(chain.serialize_block(block))
        restored = chain.deserialize_block(encoded)
        check(
            "validator public key and signature survive persistence",
            restored.header.validator_public_key == keypair.public_key
            and restored.header.validator_signature == block.header.validator_signature
            and chain.validate_pos_block(restored),
        )

        original_hash = block.get_block_hash()
        changed_signature = copy.deepcopy(block)
        changed_signature.header.validator_signature = (
            bytes([changed_signature.header.validator_signature[0] ^ 1])
            + changed_signature.header.validator_signature[1:]
        )
        check(
            "block id commits to validator signature",
            changed_signature.get_block_hash() != original_hash,
        )

        chain.get_active_stakes = lambda: [stake, other_stake]
        selection_a = chain.select_pos_validator(1)
        chain.get_active_stakes = lambda: [other_stake, stake]
        selection_b = chain.select_pos_validator(1)
        check("validator selection is independent of stake query order", selection_a == selection_b)

        keys = {
            address: keypair,
            other_address: other_keypair,
        }
        non_selected = other_address if selection_a == address else address
        non_selected_keypair = keys[non_selected]
        check(
            "non-selected active validator cannot produce the slot",
            chain.create_pos_block_template(non_selected, non_selected_keypair.public_key)
            is None,
        )
    finally:
        consensus.POS_ACTIVATION_HEIGHT = old_activation
        consensus.MIN_STAKE_AMOUNT = old_min_stake
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
