#!/usr/bin/env python3
"""
Hard supply-cap tests (owner decisions D1-D3, 2026-06-20).

Verifies that cumulative base-reward issuance is clamped to SUPPLY_CAP
(69,000,003 WEPO) by construction, regardless of the PoW/PoS block mix:

  * genesis bootstrap (400 WEPO) is counted INSIDE the cap (D1)
  * cumulative issuance never exceeds the cap and lands EXACTLY on it when the
    schedule would overshoot (D3)
  * the final reward is truncated and post-exhaustion rewards are 0
  * issuance is deterministic / reorg-safe (recompute from the canonical chain)
  * create_coinbase_transaction mints the clamped amount (production path)
  * validate_block rejects a coinbase that mints more than base+fees allows

Run: python3 tests/test_supply_cap.py
"""
import os
import sys
import types
import shutil
import tempfile

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

import blockchain as bc_mod  # noqa: E402
from blockchain import WepoBlockchain, COIN, GENESIS_BOOTSTRAP_REWARD  # noqa: E402
from address_utils import generate_wepo_address  # noqa: E402

RECIPIENT = generate_wepo_address("supply-cap-test-recipient", address_type="regular")

FAILURES = []


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILURES.append(name)


def fake_block(height, pos=False):
    """Minimal stand-in exposing the surface get_issued_supply() reads."""
    header = types.SimpleNamespace(is_pos_block=lambda pos=pos: pos)
    return types.SimpleNamespace(height=height, header=header)


def new_chain():
    tmp = tempfile.mkdtemp(prefix="wepo-supply-cap-")
    return WepoBlockchain(data_dir=tmp), tmp


def test_genesis_inside_cap():
    bc, tmp = new_chain()
    try:
        issued = bc.get_issued_supply()
        check("genesis is issued (400 WEPO) and counted inside the cap",
              issued == GENESIS_BOOTSTRAP_REWARD)
        check("genesis issuance is below the hard cap",
              issued <= bc_mod.SUPPLY_CAP)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_clamp_exact_and_never_exceeds():
    bc, tmp = new_chain()
    orig_cap = bc_mod.SUPPLY_CAP
    try:
        reward = bc.calculate_block_reward(1)  # pre-PoS per-block reward
        # Cap sits at 3.5 rewards: blocks 1-3 pay in full, block 4 truncates to 0.5r,
        # block 5+ pays nothing.
        bc_mod.SUPPLY_CAP = reward * 3 + reward // 2
        bc.chain = [fake_block(h, pos=False) for h in range(1, 6)]

        # Cumulative issuance over every prefix must stay <= cap and end == cap.
        prefixes = [bc.get_issued_supply(up_to_height=h) for h in range(1, 6)]
        check("issuance is monotonic and never exceeds the cap",
              all(prefixes[i] <= prefixes[i + 1] for i in range(len(prefixes) - 1))
              and all(p <= bc_mod.SUPPLY_CAP for p in prefixes))
        check("cumulative issuance lands EXACTLY on the cap when schedule overshoots",
              prefixes[-1] == bc_mod.SUPPLY_CAP)

        # block 4 reward is truncated to the remaining 0.5r
        check("final reward is truncated to remaining headroom",
              bc.clamped_base_reward(4, "pow") == reward // 2)
        # block 6 (cap already exhausted by 1-5) pays 0
        check("post-exhaustion reward is zero (fees only)",
              bc.clamped_base_reward(6, "pow") == 0)
    finally:
        bc_mod.SUPPLY_CAP = orig_cap
        shutil.rmtree(tmp, ignore_errors=True)


def test_reorg_deterministic_and_bounded():
    bc, tmp = new_chain()
    orig_cap = bc_mod.SUPPLY_CAP
    try:
        reward = bc.calculate_block_reward(1)
        bc_mod.SUPPLY_CAP = reward * 10  # generous; mixes stay under it

        # Two competing branches of equal height, different PoW/PoS mix.
        bc.chain = [fake_block(h, pos=(h % 2 == 0)) for h in range(1, 6)]
        issued_a1 = bc.get_issued_supply()
        issued_a2 = bc.get_issued_supply()
        check("issuance recompute is deterministic (pure function of the chain)",
              issued_a1 == issued_a2)

        # Simulate a reorg: swap to a different branch, recompute from scratch.
        bc.chain = [fake_block(h, pos=(h % 3 == 0)) for h in range(1, 6)]
        issued_b = bc.get_issued_supply()
        check("reorged branch issuance is still bounded by the cap",
              issued_b <= bc_mod.SUPPLY_CAP)
        check("reorged branch recompute is deterministic",
              issued_b == bc.get_issued_supply())
    finally:
        bc_mod.SUPPLY_CAP = orig_cap
        shutil.rmtree(tmp, ignore_errors=True)


def test_coinbase_creation_respects_cap():
    bc, tmp = new_chain()
    orig_cap = bc_mod.SUPPLY_CAP
    try:
        reward = bc.calculate_block_reward(1)
        bc_mod.SUPPLY_CAP = reward * 3 + reward // 2
        bc.chain = [fake_block(h, pos=False) for h in range(1, 4)]  # 3 full rewards issued

        # Next pow block (height 4) should mint only the remaining 0.5r as base.
        cb = bc.create_coinbase_transaction(4, RECIPIENT, "pow", [])
        base_out = cb.outputs[0].value  # first output is the producer's base reward
        check("created coinbase base reward is clamped to remaining headroom",
              base_out == reward // 2)

        # A block after the cap is exhausted mints zero base reward.
        bc.chain = [fake_block(h, pos=False) for h in range(1, 6)]
        cb2 = bc.create_coinbase_transaction(6, RECIPIENT, "pow", [])
        check("created coinbase mints zero base reward once cap is exhausted",
              cb2.outputs[0].value == 0)
    finally:
        bc_mod.SUPPLY_CAP = orig_cap
        shutil.rmtree(tmp, ignore_errors=True)


def test_validate_block_rejects_overmint():
    bc, tmp = new_chain()
    try:
        from blockchain import Block, BlockHeader

        height = bc.get_block_height() + 1
        prev_hash = bc.get_latest_block().get_block_hash()
        allowed = bc.clamped_base_reward(height, "pow")

        # Build an otherwise well-formed block (correct height/prev/merkle/coinbase)
        # whose coinbase mints far more than the allowed base reward (no fees).
        cb = bc.create_coinbase_transaction(height, RECIPIENT, "pow", [])
        cb.outputs[0].value = allowed * 2 + 1  # over-mint

        header = BlockHeader(
            version=1, prev_hash=prev_hash, merkle_root="",
            timestamp=bc.get_latest_block().header.timestamp + 360,
            bits=1, nonce=0, consensus_type="pow",
        )
        blk = Block(header=header, transactions=[cb], height=height)
        blk.header.merkle_root = blk.calculate_merkle_root()

        check("validate_block rejects a coinbase that over-mints beyond base+fees",
              bc.validate_block(blk) is False)

        # Sanity: the honestly-built coinbase satisfies the cap inequality.
        cb_ok = bc.create_coinbase_transaction(height, RECIPIENT, "pow", [])
        check("honest coinbase mints within base+fees allowance",
              sum(o.value for o in cb_ok.outputs) <= allowed)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_pos_distribution_single_count_and_capped():
    """Distribution-only PoS model: the PoS coinbase mints NO base reward, the PoS
    pool is the single PoS issuance path, it is counted by get_issued_supply, and
    it is clamped to the cap (no double-mint, no cap bypass)."""
    bc, tmp = new_chain()
    orig_cap = bc_mod.SUPPLY_CAP
    try:
        h = bc_mod.POS_ACTIVATION_HEIGHT + 1
        pool = bc.calculate_pos_reward(h)

        check("PoS coinbase mints zero base reward (distribution-only)",
              bc.scheduled_coinbase_base(h, "pos") == 0
              and bc.clamped_coinbase_base(h, "pos") == 0)
        check("PoS pool is the single PoS issuance (full pool far from cap)",
              bc.clamped_pos_pool(h, "pos") == pool and pool > 0)

        # get_issued_supply must account for the distribution pool, not just coinbase.
        bc.chain = [fake_block(h, pos=True)]
        check("issued supply counts the PoS distribution pool",
              bc.get_issued_supply() == pool)
        # A PoS block mints the pool exactly ONCE (base 0 + one pool), not twice.
        check("PoS block mints the reward once, not double",
              bc.clamped_coinbase_base(h, "pos") + pool == pool)

        # Cap bypass closed: once exhausted, the distribution pool clamps to 0 too.
        bc_mod.SUPPLY_CAP = pool  # exactly one pool fits
        bc.chain = [fake_block(h, pos=True)]
        check("PoS pool clamps to zero once the cap is exhausted (no bypass)",
              bc.clamped_pos_pool(h + 1, "pos") == 0)
    finally:
        bc_mod.SUPPLY_CAP = orig_cap
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    test_genesis_inside_cap()
    test_clamp_exact_and_never_exceeds()
    test_reorg_deterministic_and_bounded()
    test_coinbase_creation_respects_cap()
    test_validate_block_rejects_overmint()
    test_pos_distribution_single_count_and_capped()

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
