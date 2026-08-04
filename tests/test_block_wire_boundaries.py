#!/usr/bin/env python3
"""Consensus block-header and serialized-size boundary regressions.

Run: python3 tests/test_block_wire_boundaries.py
"""

import copy
import json
import os
import shutil
import sys
import tempfile

os.environ["WEPO_NETWORK_PROFILE"] = "test"

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

from blockchain import (  # noqa: E402
    MAX_BLOCK_SIZE,
    MAX_BLOCK_TRANSACTIONS,
    WepoBlockchain,
)

FAILURES = []
MINER_ADDRESS = "wepo1q" + ("2" * 39)


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


def mine_header(chain, block):
    while not chain.miner.check_difficulty(
        chain.miner.calculate_pow_hash(block.header),
        block.header.bits,
    ):
        block.header.nonce += 1


def main():
    temp_dir = tempfile.mkdtemp(prefix="wepo-block-wire-")
    try:
        chain = WepoBlockchain(data_dir=temp_dir, network_profile="test")
        chain.fixed_difficulty = 1
        chain.current_difficulty = 1

        print("Block wire/header boundaries:")
        valid = chain.create_new_block(MINER_ADDRESS)
        mine_header(chain, valid)
        check("honest calculated-size PoW block is accepted", chain.validate_block(valid))

        encoded = json.loads(chain.serialize_block(valid))
        restored = chain.deserialize_block(encoded)
        check(
            "canonical block wire envelope round-trips exactly",
            restored.get_block_hash() == valid.get_block_hash()
            and restored.size == valid.size,
        )

        wrong_declared_size = copy.deepcopy(encoded)
        wrong_declared_size["size"] -= 1
        try:
            chain.deserialize_block(wrong_declared_size)
        except ValueError:
            rejected_wrong_size = True
        else:
            rejected_wrong_size = False
        check("wire block rejects a spoofed declared size", rejected_wrong_size)

        unknown_block_field = copy.deepcopy(encoded)
        unknown_block_field["future_field"] = 1
        try:
            chain.deserialize_block(unknown_block_field)
        except ValueError:
            rejected_unknown_block = True
        else:
            rejected_unknown_block = False
        check("wire block rejects unknown root fields", rejected_unknown_block)

        unknown_tx_field = copy.deepcopy(encoded)
        unknown_tx_field["transactions"][0]["future_field"] = 1
        try:
            chain.deserialize_block(unknown_tx_field)
        except ValueError:
            rejected_unknown_tx = True
        else:
            rejected_unknown_tx = False
        check("wire block uses the strict transaction decoder", rejected_unknown_tx)

        excessive_transactions = copy.deepcopy(encoded)
        excessive_transactions["transactions"] *= MAX_BLOCK_TRANSACTIONS + 1
        try:
            chain.deserialize_block(excessive_transactions)
        except ValueError:
            rejected_excessive_transactions = True
        else:
            rejected_excessive_transactions = False
        check(
            "wire block rejects excessive transaction counts before construction",
            rejected_excessive_transactions,
        )

        excessive_in_memory = copy.deepcopy(valid)
        excessive_in_memory.transactions *= MAX_BLOCK_TRANSACTIONS + 1
        excessive_in_memory.header.merkle_root = (
            excessive_in_memory.calculate_merkle_root()
        )
        check(
            "direct block validation rejects excessive transaction counts",
            not chain.validate_block(excessive_in_memory),
        )

        oversized = chain.create_new_block(MINER_ADDRESS)
        oversized.transactions[0].extra_data = {"padding": "x" * (MAX_BLOCK_SIZE + 1)}
        oversized.header.merkle_root = oversized.calculate_merkle_root()
        oversized.size = 1
        check(
            "spoofed declared size cannot bypass the serialized-size limit",
            not chain.validate_block(oversized),
        )
        check("oversized calculation exceeds the limit", oversized.calculate_size() > MAX_BLOCK_SIZE)

        malformed_hash = copy.deepcopy(valid)
        malformed_hash.header.prev_hash = "not-a-hash"
        check("malformed previous hash is rejected without parsing crash", not chain.validate_block(malformed_hash))

        malformed_nonce = copy.deepcopy(valid)
        malformed_nonce.header.nonce = -1
        check("negative nonce is rejected before hashing", not chain.validate_block(malformed_nonce))

        wrong_version = copy.deepcopy(valid)
        wrong_version.header.version = 2
        check("unknown block-header version is rejected", not chain.validate_block(wrong_version))

        pow_with_validator = copy.deepcopy(valid)
        pow_with_validator.header.validator_address = MINER_ADDRESS
        pow_with_validator.header.validator_public_key = b"x"
        pow_with_validator.header.validator_signature = b"y"
        check(
            "PoW block cannot carry malleable validator fields",
            not chain.validate_pow_block(pow_with_validator),
        )

        unsigned_size = valid.calculate_size()
        signed_shape = copy.deepcopy(valid)
        signed_shape.header.consensus_type = "pos"
        signed_shape.header.validator_address = MINER_ADDRESS
        signed_shape.header.validator_public_key = b"p" * 1312
        signed_shape.header.validator_signature = b"s" * 2420
        check(
            "size accounting includes PoS public key and signature",
            signed_shape.calculate_size() > unsigned_size + 3700,
        )

        unsupported = copy.deepcopy(valid)
        unsupported.transactions[0].extra_data = {"object": object()}
        check(
            "non-serializable consensus payload is rejected without escaping size checks",
            not chain.validate_block(unsupported),
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
