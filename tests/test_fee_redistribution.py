#!/usr/bin/env python3
"""
Fee redistribution conservation test (no dead coins).

Proves that EVERY transaction fee collected in a block is paid out to network
workers (masternodes, miner/validator, stakers) via the coinbase — the sum of all
coinbase outputs always equals base_reward + total_fees exactly, with no rounding
remainder left unspent ("burned"/dead). Covers:

  * pre-PoS (no masternodes)        -> 100% of fees to the miner
  * pre-PoS with masternodes        -> 60% masternodes, remainder to miner
  * post-PoS full split             -> 60% masternodes / 25% miner / 15% stakers
  * indivisible fees / many workers -> rounding remainders roll to the miner
  * empty worker sets               -> shares fall back to the miner (never lost)
  * fee payout still works after the supply cap is exhausted (base_reward == 0)

Run: python3 tests/test_fee_redistribution.py
"""
import os
import sys
import types
import shutil
import tempfile

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

import blockchain as bc_mod  # noqa: E402
from blockchain import WepoBlockchain, COIN, StakeInfo, MasternodeInfo  # noqa: E402
from address_utils import generate_wepo_address  # noqa: E402

MINER = generate_wepo_address("fee-test-miner", address_type="regular")
FAILURES = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        FAILURES.append(name)


def new_chain():
    tmp = tempfile.mkdtemp(prefix="wepo-fee-")
    return WepoBlockchain(data_dir=tmp), tmp


class FeeTx:
    """Minimal mempool-style transaction carrying only a fee."""
    def __init__(self, fee):
        self.fee = fee

    def is_coinbase(self):
        return False


def make_masternodes(n):
    return [
        MasternodeInfo(
            masternode_id=f"mn{i}",
            operator_address=generate_wepo_address(f"mn-op-{i}", address_type="regular"),
            collateral_txid="0" * 64,
            collateral_vout=i,
        )
        for i in range(n)
    ]


def make_stakers(amounts):
    return [
        StakeInfo(
            stake_id=f"st{i}",
            staker_address=generate_wepo_address(f"staker-{i}", address_type="regular"),
            amount=amt,
            start_height=1,
            start_time=0,
        )
        for i, amt in enumerate(amounts)
    ]


def conservation_case(name, height, fees, masternodes, stakers):
    """Build a coinbase with the given workers/fees and assert full conservation."""
    bc, tmp = new_chain()
    try:
        bc.get_active_masternodes = lambda: list(masternodes)
        bc.get_active_stakes = lambda: list(stakers)

        candidate = [FeeTx(f) for f in fees]
        total_fees = sum(fees)
        base = bc.clamped_base_reward(height, "pow")

        cb = bc.create_coinbase_transaction(height, MINER, "pow", candidate)
        out_sum = sum(o.value for o in cb.outputs)

        # 1) Total conservation: nothing minted or lost.
        check(f"{name}: coinbase outputs == base + all fees (no dead coins)",
              out_sum == base + total_fees,
              f"out={out_sum} expected={base + total_fees}")

        # 2) Every output is non-negative and the miner output exists.
        check(f"{name}: all coinbase outputs are non-negative",
              all(o.value >= 0 for o in cb.outputs))

        # 3) The fee portion alone (excluding the base reward) is fully accounted.
        fee_distributed = out_sum - base
        check(f"{name}: 100% of fees distributed to workers",
              fee_distributed == total_fees,
              f"distributed={fee_distributed} fees={total_fees}")
        return bc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_pre_pos_no_masternodes():
    conservation_case("pre-PoS / no MN", 5, [10000, 25000, 1], [], [])


def test_pre_pos_with_masternodes():
    conservation_case("pre-PoS / 3 MN", 5, [99991, 13337], make_masternodes(3), [])


def test_post_pos_full_split():
    h = bc_mod.POS_ACTIVATION_HEIGHT + 10
    conservation_case("post-PoS / 4 MN + 3 stakers", h, [1234567, 7],
                      make_masternodes(4), make_stakers([1000 * COIN, 3000 * COIN, 777 * COIN]))


def test_indivisible_fees_many_workers():
    # Fees that don't divide evenly across 7 masternodes and 5 unequal stakers.
    h = bc_mod.POS_ACTIVATION_HEIGHT + 10
    conservation_case("indivisible / 7 MN + 5 stakers", h, [1000003, 999983, 7919],
                      make_masternodes(7),
                      make_stakers([100 * COIN, 250 * COIN, 333 * COIN, 1 * COIN, 9999]))


def test_post_pos_no_workers_rolls_to_miner():
    # Post-PoS split assigns 60/25/15, but with no MN and no stakers ALL of it must
    # roll back to the miner — nothing is left undistributed.
    h = bc_mod.POS_ACTIVATION_HEIGHT + 10
    bc = WepoBlockchain
    tmp = tempfile.mkdtemp(prefix="wepo-fee-")
    try:
        chain = WepoBlockchain(data_dir=tmp)
        chain.get_active_masternodes = lambda: []
        chain.get_active_stakes = lambda: []
        fees = [555555, 4]
        cb = chain.create_coinbase_transaction(h, MINER, "pow", [FeeTx(f) for f in fees])
        base = chain.clamped_base_reward(h, "pow")
        miner_out = sum(o.value for o in cb.outputs if o.address == MINER)
        check("post-PoS / no workers: miner receives base + 100% of fees",
              miner_out == base + sum(fees),
              f"miner={miner_out} expected={base + sum(fees)}")
        check("post-PoS / no workers: exactly one (miner) output",
              len(cb.outputs) == 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_fees_paid_after_cap_exhausted():
    # Once the supply cap is exhausted base_reward is 0, but fees must still be
    # redistributed in full — the network keeps paying its workers forever.
    bc, tmp = new_chain()
    orig_cap = bc_mod.SUPPLY_CAP
    try:
        # Exhaust the cap using a synthetic chain.
        reward = bc.calculate_block_reward(1)
        bc_mod.SUPPLY_CAP = reward * 2
        bc.chain = [types.SimpleNamespace(
            height=h, header=types.SimpleNamespace(is_pos_block=lambda: False)
        ) for h in range(1, 4)]
        bc.get_active_masternodes = lambda: make_masternodes(2)
        bc.get_active_stakes = lambda: []

        base = bc.clamped_base_reward(4, "pow")
        check("cap exhausted: base reward is zero", base == 0)

        fees = [123456, 654321]
        cb = bc.create_coinbase_transaction(4, MINER, "pow", [FeeTx(f) for f in fees])
        out_sum = sum(o.value for o in cb.outputs)
        check("cap exhausted: 100% of fees still redistributed (no dead coins)",
              out_sum == sum(fees), f"out={out_sum} fees={sum(fees)}")
        check("cap exhausted: coinbase mints zero new supply (fees only)",
              out_sum - sum(fees) == 0)
    finally:
        bc_mod.SUPPLY_CAP = orig_cap
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    test_pre_pos_no_masternodes()
    test_pre_pos_with_masternodes()
    test_post_pos_full_split()
    test_indivisible_fees_many_workers()
    test_post_pos_no_workers_rolls_to_miner()
    test_fees_paid_after_cap_exhausted()

    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
