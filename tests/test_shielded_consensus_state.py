#!/usr/bin/env python3
"""Ghost transaction/state/reorg consensus integration regressions.

The proof verifier is replaced with an explicitly audit-approved test double so
these tests isolate the node state machine. The production default remains the
reject-all verifier and Ghost remains activation-height disabled.
"""

import copy
import os
import sys
import tempfile

CORE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
)
sys.path.insert(0, CORE)

import _backend_shim  # noqa: F401,E402
import blockchain as B  # noqa: E402
import shielded as S  # noqa: E402
from address_utils import generate_wepo_address  # noqa: E402


FAILURES = []


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


class StateMachineVerifier:
    """Accepting double used only after explicit test audit approval."""

    def verify(self, statement_digest, proof):
        return len(statement_digest) == 32 and proof.startswith(b"state-test:")


def pool_value(number):
    return S.field_elements_to_bytes([number, number + 1, number + 2, number + 3])


def bundle(*, anchor=None, nullifier=None, commitment=None, value_balance=0, tag=b"x"):
    spends = []
    if anchor is not None:
        spends.append(S.SpendDescription(anchor=anchor, nullifier=nullifier))
    outputs = []
    if commitment is not None:
        outputs.append(
            S.OutputDescription(
                commitment=commitment,
                enc_note=b"encrypted-note:" + tag,
            )
        )
    return S.ShieldedBundle(
        spends=spends,
        outputs=outputs,
        value_balance=value_balance,
        proof=b"state-test:" + tag,
    )


def shielded_tx(shielded_bundle, *, timestamp):
    return B.Transaction(
        version=1,
        inputs=[],
        outputs=[],
        lock_time=0,
        fee=0,
        shielded_bundle=shielded_bundle,
        timestamp=timestamp,
    )


def mine_candidate(chain, transactions, miner_address):
    height = chain.get_block_height() + 1
    coinbase = chain.create_coinbase_transaction(
        height,
        miner_address,
        "pow",
        transactions,
    )
    header = B.BlockHeader(
        version=1,
        prev_hash=chain.get_latest_block().get_block_hash(),
        merkle_root="",
        timestamp=chain._next_block_timestamp(),
        bits=chain.calculate_expected_difficulty(),
        nonce=0,
        consensus_type="pow",
    )
    block = B.Block(
        header=header,
        transactions=[coinbase, *transactions],
        height=height,
    )
    block.header.merkle_root = block.calculate_merkle_root()
    return chain.miner.mine_block(block, block.header.bits)


def table_count(chain, table):
    return chain.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_serialization_and_activation_gate():
    commitment = pool_value(10)
    tx = shielded_tx(
        bundle(commitment=commitment, tag=b"serialize"),
        timestamp=1_800_000_001,
    )
    encoded = tx.to_dict()
    decoded = B.Transaction.from_dict(encoded)
    check(
        "shielded bundle survives canonical transaction serialization",
        decoded.to_dict() == encoded,
    )
    check("shielded serialization preserves txid", decoded.calculate_txid() == tx.calculate_txid())
    check(
        "shielded serialization preserves sighash",
        decoded.get_canonical_sighash() == tx.get_canonical_sighash(),
    )

    changed_ciphertext = copy.deepcopy(tx)
    changed_ciphertext.shielded_bundle.outputs[0] = S.OutputDescription(
        commitment=commitment,
        enc_note=b"different-ciphertext",
    )
    check(
        "transaction sighash binds encrypted note payload",
        changed_ciphertext.get_canonical_sighash() != tx.get_canonical_sighash(),
    )

    changed_proof = copy.deepcopy(tx)
    changed_proof.shielded_bundle.proof = b"state-test:different-proof"
    check(
        "proof is excluded from the circular sighash",
        changed_proof.get_canonical_sighash() == tx.get_canonical_sighash(),
    )
    check(
        "proof is included in the transaction id",
        changed_proof.calculate_txid() != tx.calculate_txid(),
    )

    with tempfile.TemporaryDirectory() as data_dir:
        chain = B.WepoBlockchain(data_dir, network_profile="test")
        check(
            "Ghost transaction rejected while activation height is unset",
            not chain.validate_transaction(tx, validation_height=1),
        )
        chain.conn.close()


def test_persistence_atomicity_and_replay():
    old_enabled = B.PRIVACY_CONSENSUS_ENABLED
    old_height = B.SHIELDED_ACTIVATION_HEIGHT
    S.register_verifier(StateMachineVerifier(), audit_approved=True)
    B.PRIVACY_CONSENSUS_ENABLED = True
    B.SHIELDED_ACTIVATION_HEIGHT = 1

    try:
        with tempfile.TemporaryDirectory() as data_dir:
            chain = B.WepoBlockchain(data_dir, network_profile="test")
            chain.fixed_difficulty = 1
            miner = generate_wepo_address(b"shielded-state-miner", address_type="quantum")

            first_commitment = pool_value(100)
            first_tx = shielded_tx(
                bundle(commitment=first_commitment, tag=b"first"),
                timestamp=1_800_000_101,
            )
            check("activated Ghost transaction enters mempool", chain.add_transaction_to_mempool(first_tx))
            first_block = chain.mine_block(miner)
            check("activated Ghost transaction commits in a block", first_block is not None)
            check("commitment persisted exactly once", table_count(chain, "shielded_commitments") == 1)
            check("commitment tree advanced exactly once", chain.shielded_tree.size == 1)
            first_root = chain.shielded_tree.root()
            check("new block-boundary anchor persisted", chain.shielded_anchors.is_valid(first_root))

            round_trip = chain.deserialize_block(
                __import__("json").loads(chain.serialize_block(first_block))
            )
            check(
                "block serialization preserves shielded bundle",
                round_trip.transactions[1].to_dict() == first_tx.to_dict(),
            )

            # Force a failure after shielded state has been staged. add_block must
            # roll back SQLite, disconnect the candidate, and invalidate memory.
            failed_commitment = pool_value(200)
            failed_tx = shielded_tx(
                bundle(commitment=failed_commitment, tag=b"forced-failure"),
                timestamp=1_800_000_102,
            )
            failed_block = mine_candidate(chain, [failed_tx], miner)
            original_apply = chain._apply_shielded_state

            def apply_then_fail(block):
                original_apply(block)
                raise RuntimeError("forced post-shielded-state failure")

            chain._apply_shielded_state = apply_then_fail
            check("post-state persistence failure rejects the block", not chain.add_block(failed_block))
            chain._apply_shielded_state = original_apply
            check("failed block is disconnected from memory", chain.get_block_height() == 1)
            check(
                "failed block leaves no commitment row",
                table_count(chain, "shielded_commitments") == 1,
            )
            chain._ensure_shielded_state()
            check(
                "failed block leaves no in-memory commitment",
                chain.shielded_tree.size == 1 and chain.shielded_tree.root() == first_root,
            )

            nullifier = pool_value(300)
            second_commitment = pool_value(400)
            spend_tx = shielded_tx(
                bundle(
                    anchor=first_root,
                    nullifier=nullifier,
                    commitment=second_commitment,
                    tag=b"spend",
                ),
                timestamp=1_800_000_103,
            )
            check("anchored shielded spend enters mempool", chain.add_transaction_to_mempool(spend_tx))

            conflicting = shielded_tx(
                bundle(
                    anchor=first_root,
                    nullifier=nullifier,
                    commitment=pool_value(500),
                    tag=b"mempool-conflict",
                ),
                timestamp=1_800_000_104,
            )
            check(
                "mempool rejects a conflicting shielded nullifier",
                not chain.add_transaction_to_mempool(conflicting),
            )

            second_block = chain.mine_block(miner)
            check("shielded spend commits", second_block is not None)
            check("nullifier persisted", nullifier in chain.shielded_nullifiers)
            check("second commitment persisted", chain.shielded_tree.size == 2)

            fresh_nullifier = pool_value(600)
            duplicate_a = shielded_tx(
                bundle(
                    anchor=chain.shielded_tree.root(),
                    nullifier=fresh_nullifier,
                    commitment=pool_value(700),
                    tag=b"duplicate-a",
                ),
                timestamp=1_800_000_105,
            )
            duplicate_b = shielded_tx(
                bundle(
                    anchor=chain.shielded_tree.root(),
                    nullifier=fresh_nullifier,
                    commitment=pool_value(800),
                    tag=b"duplicate-b",
                ),
                timestamp=1_800_000_106,
            )
            duplicate_block = mine_candidate(chain, [duplicate_a, duplicate_b], miner)
            check(
                "block validation rejects same-block nullifier reuse",
                not chain.validate_block(duplicate_block),
            )

            original_chain = list(chain.chain)
            chain._rebuild_canonical_state_from_blocks(original_chain[:2])
            chain.conn.commit()
            check("disconnect removes shielded nullifier", nullifier not in chain.shielded_nullifiers)
            check("disconnect removes appended commitment", chain.shielded_tree.size == 1)
            check("disconnect restores prior anchor", chain.shielded_tree.root() == first_root)

            chain._rebuild_canonical_state_from_blocks(original_chain)
            chain.conn.commit()
            check("canonical replay restores nullifier", nullifier in chain.shielded_nullifiers)
            check("canonical replay restores commitment tree", chain.shielded_tree.size == 2)

            # Persisted tree/anchor disagreement must fail closed when state loads.
            chain.conn.execute(
                "UPDATE shielded_anchors SET anchor = ? WHERE block_height = ?",
                (pool_value(900), chain.get_block_height()),
            )
            chain._reset_shielded_memory_state()
            try:
                chain._ensure_shielded_state()
                mismatch_rejected = False
            except RuntimeError:
                mismatch_rejected = True
            check("persisted anchor/tree mismatch fails closed", mismatch_rejected)
            chain.conn.rollback()
            chain._reset_shielded_memory_state()
            chain._ensure_shielded_state()

            chain.conn.close()

            restarted = B.WepoBlockchain(data_dir, network_profile="test")
            restarted.fixed_difficulty = 1
            restarted._ensure_shielded_state()
            check("restart restores shielded commitment tree", restarted.shielded_tree.size == 2)
            check("restart restores spent nullifiers", nullifier in restarted.shielded_nullifiers)
            check(
                "restart restores the canonical anchor",
                restarted.shielded_anchors.is_valid(restarted.shielded_tree.root()),
            )
            restarted.conn.close()
    finally:
        B.PRIVACY_CONSENSUS_ENABLED = old_enabled
        B.SHIELDED_ACTIVATION_HEIGHT = old_height
        S.register_verifier(S.RejectAllVerifier(), audit_approved=False)


def main():
    print("Shielded transaction serialization and activation:")
    test_serialization_and_activation_gate()
    print("\nShielded persistence, atomicity, nullifiers, and replay:")
    test_persistence_atomicity_and_replay()

    if FAILURES:
        print(f"\nRESULT: {len(FAILURES)} FAILURE(S)")
        for failure in FAILURES:
            print(f"  - {failure}")
        raise SystemExit(1)
    print("\nRESULT: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
