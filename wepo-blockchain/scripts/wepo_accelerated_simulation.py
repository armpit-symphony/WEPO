#!/usr/bin/env python3
"""Accelerated WEPO chain simulation for schedule and wallet testing."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


CORE_DIR = Path(__file__).resolve().parents[1] / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from address_utils import generate_wepo_address  # noqa: E402
from blockchain import (  # noqa: E402
    BLOCK_TIME_INITIAL_18_MONTHS,
    BLOCK_TIME_LONGTERM,
    COIN,
    MAINNET_GENESIS_TIMESTAMP,
    MIN_STAKE_AMOUNT,
    PHASE_2A_END_HEIGHT,
    PHASE_2B_END_HEIGHT,
    PHASE_2C_END_HEIGHT,
    PHASE_2D_END_HEIGHT,
    POS_ACTIVATION_HEIGHT,
    POW_END_HEIGHT,
    PRE_POS_DURATION_BLOCKS,
    REWARD_Q1,
    WepoBlockchain,
)


class InstantMiner:
    """Simulation miner that accepts the next nonce immediately."""

    def calculate_pow_hash(self, header):
        return "0" * 64

    def check_difficulty(self, block_hash, difficulty):
        return True

    def mine_block(self, block, target_difficulty):
        block.header.nonce = block.height
        return block


def to_wepo(amount: int) -> float:
    return round(amount / COIN, 8)


def height_to_timestamp(height: int) -> int:
    if height <= PRE_POS_DURATION_BLOCKS:
        elapsed = height * BLOCK_TIME_INITIAL_18_MONTHS
    else:
        elapsed = PRE_POS_DURATION_BLOCKS * BLOCK_TIME_INITIAL_18_MONTHS
        elapsed += (height - PRE_POS_DURATION_BLOCKS) * BLOCK_TIME_LONGTERM
    return MAINNET_GENESIS_TIMESTAMP + elapsed


def height_to_iso(height: int) -> str:
    return datetime.fromtimestamp(height_to_timestamp(height), tz=timezone.utc).isoformat()


def collect_schedule_markers(chain: WepoBlockchain) -> list[dict]:
    markers = [
        0,
        1,
        PRE_POS_DURATION_BLOCKS,
        PRE_POS_DURATION_BLOCKS + 1,
        PHASE_2A_END_HEIGHT,
        PHASE_2A_END_HEIGHT + 1,
        PHASE_2B_END_HEIGHT,
        PHASE_2B_END_HEIGHT + 1,
        PHASE_2C_END_HEIGHT,
        PHASE_2C_END_HEIGHT + 1,
        PHASE_2D_END_HEIGHT,
        PHASE_2D_END_HEIGHT + 1,
        POW_END_HEIGHT + 1,
    ]

    results = []
    for height in sorted(set(markers)):
        phase = chain.get_current_phase_info(height)
        collateral = chain.get_collateral_info(height)
        results.append(
            {
                "height": height,
                "approx_time_utc": height_to_iso(height),
                "phase": phase["phase"],
                "description": phase["description"],
                "pow_reward_wepo": phase["pow_reward"],
                "pow_reward_direct_wepo": to_wepo(chain.calculate_block_reward(height)),
                "pos_reward_wepo": to_wepo(chain.calculate_pos_reward(height)),
                "pos_available": collateral["pos_available"],
                "masternode_collateral_wepo": collateral["masternode_collateral_wepo"],
                "pos_collateral_wepo": collateral["pos_collateral_wepo"],
                "next_adjustment": collateral["next_adjustment"],
            }
        )
    return results


def coinbase_output_totals(block) -> dict[str, int]:
    totals: dict[str, int] = {}
    for output in block.transactions[0].outputs:
        totals[output.address] = totals.get(output.address, 0) + output.value
    return totals


def send_and_confirm(chain: WepoBlockchain, miner_address: str, to_address: str, amount: int):
    funding_tx = chain.create_transaction(
        from_address=miner_address,
        to_address=to_address,
        amount=amount,
    )
    if funding_tx is None:
        raise RuntimeError(f"Failed to create funding transaction for {to_address}")
    if not chain.add_transaction_to_mempool(funding_tx):
        raise RuntimeError(f"Failed to add funding transaction for {to_address}")
    staking_info = chain.get_staking_info()
    current_pos_activation_height = staking_info.get("pos_activation_height", POS_ACTIVATION_HEIGHT)
    confirmation = (
        chain.mine_block(miner_address)
        if chain.get_block_height() >= current_pos_activation_height
        else chain.mine_next_block(miner_address)
    )
    if not confirmation:
        raise RuntimeError(f"Failed to confirm funding transaction for {to_address}")
    return funding_tx, confirmation


def main() -> int:
    temp_dir = tempfile.mkdtemp(prefix="wepo-sim-")
    try:
        chain = WepoBlockchain(data_dir=temp_dir)
        chain.miner = InstantMiner()
        chain.current_difficulty = 1
        chain.adjust_difficulty = lambda: None

        genesis_address = generate_wepo_address("wepo-mainnet-genesis", address_type="regular")
        miner_address = generate_wepo_address("sim-miner", address_type="regular")
        recipient_address = generate_wepo_address("sim-recipient", address_type="regular")
        staker_address = generate_wepo_address("sim-staker", address_type="regular")
        masternode_address = generate_wepo_address("sim-masternode", address_type="regular")

        genesis = chain.get_latest_block()
        genesis_balance = chain.get_balance(genesis_address)

        mined_blocks = []
        for _ in range(2):
            block = chain.mine_next_block(miner_address)
            if not block:
                raise RuntimeError("Failed to mine initial accelerated blocks")
            mined_blocks.append(
                {
                    "height": block.height,
                    "hash": block.get_block_hash(),
                    "coinbase_reward_wepo": to_wepo(block.transactions[0].outputs[0].value),
                }
            )

        sender_balance_before = chain.get_balance(miner_address)
        tx = chain.create_transaction(
            from_address=miner_address,
            to_address=recipient_address,
            amount=30 * COIN,
        )
        if tx is None:
            raise RuntimeError("Failed to create wallet transfer transaction")

        mempool_accepted = chain.add_transaction_to_mempool(tx)
        if not mempool_accepted:
            raise RuntimeError("Failed to add wallet transfer to mempool")

        confirmation_block = chain.mine_next_block(miner_address)
        if not confirmation_block:
            raise RuntimeError("Failed to mine confirmation block")
        sender_balance_after_initial_send = chain.get_balance(miner_address)
        recipient_balance_after_initial_send = chain.get_balance(recipient_address)

        for _ in range(17):
            block = chain.mine_next_block(miner_address)
            if not block:
                raise RuntimeError("Failed to mine remaining accelerated blocks")

        scheduled_pos_activation_height = POS_ACTIVATION_HEIGHT
        scheduled_pos_reward_at_activation = chain.calculate_pos_reward(scheduled_pos_activation_height)
        scheduled_pos_reward_after_activation = chain.calculate_pos_reward(scheduled_pos_activation_height + 1)
        pre_activation_probe_height = chain.get_block_height()
        stake_balance_before = chain.get_balance(miner_address)
        pre_activation_stake_id = None
        pre_activation_stake_error = None
        try:
            pre_activation_stake_id = chain.create_stake(miner_address, MIN_STAKE_AMOUNT)
        except Exception as exc:  # pragma: no cover - simulation reporting path
            pre_activation_stake_error = str(exc)
        stake_balance_after = chain.get_balance(miner_address)
        schedule_markers = collect_schedule_markers(chain)

        pre_pos_fee_tx = chain.create_transaction(
            from_address=miner_address,
            to_address=recipient_address,
            amount=5 * COIN,
        )
        if pre_pos_fee_tx is None:
            raise RuntimeError("Failed to create pre-PoS fee probe transaction")
        if not chain.add_transaction_to_mempool(pre_pos_fee_tx):
            raise RuntimeError("Failed to add pre-PoS fee probe transaction to mempool")

        pre_pos_fee_block = chain.mine_next_block(miner_address)
        if not pre_pos_fee_block:
            raise RuntimeError("Failed to mine pre-PoS fee probe block")

        pre_pos_fee_coinbase = coinbase_output_totals(pre_pos_fee_block)
        pre_pos_fee_without_masternode = {
            "height": pre_pos_fee_block.height,
            "miner_fee_share_wepo": to_wepo(
                pre_pos_fee_coinbase.get(miner_address, 0) - chain.calculate_block_reward(pre_pos_fee_block.height)
            ),
            "masternode_fee_share_wepo": to_wepo(pre_pos_fee_coinbase.get(masternode_address, 0)),
            "staker_fee_share_wepo": to_wepo(pre_pos_fee_coinbase.get(staker_address, 0)),
            "tx_fee_wepo": to_wepo(pre_pos_fee_tx.fee),
        }

        masternode_collateral_amount = 10000 * COIN
        while chain.get_balance(miner_address) < masternode_collateral_amount + COIN:
            block = chain.mine_next_block(miner_address)
            if not block:
                raise RuntimeError("Failed to mine pre-PoS masternode collateral blocks")

        pre_pos_masternode_funding_tx, _ = send_and_confirm(
            chain,
            miner_address,
            masternode_address,
            masternode_collateral_amount,
        )
        masternode_utxos = chain.get_utxos_for_address(masternode_address)
        collateral_utxo = next(
            (
                utxo
                for utxo in masternode_utxos
                if utxo["txid"] == pre_pos_masternode_funding_tx.calculate_txid()
                and utxo["amount"] >= masternode_collateral_amount
            ),
            None,
        )
        if collateral_utxo is None:
            raise RuntimeError("Failed to locate pre-PoS masternode collateral UTXO")

        pre_pos_masternode_id = chain.create_masternode(
            masternode_address,
            collateral_utxo["txid"],
            collateral_utxo["vout"],
            ip_address="127.0.0.1",
        )
        pre_pos_masternode_registration_block = chain.mine_next_block(miner_address)
        if not pre_pos_masternode_registration_block:
            raise RuntimeError("Failed to confirm canonical pre-PoS masternode registration")

        pre_pos_fee_tx_with_masternode = chain.create_transaction(
            from_address=miner_address,
            to_address=recipient_address,
            amount=2 * COIN,
        )
        if pre_pos_fee_tx_with_masternode is None:
            raise RuntimeError("Failed to create pre-PoS fee probe transaction with masternode")
        if not chain.add_transaction_to_mempool(pre_pos_fee_tx_with_masternode):
            raise RuntimeError("Failed to add pre-PoS fee probe transaction with masternode to mempool")

        pre_pos_fee_block_with_masternode = chain.mine_next_block(miner_address)
        if not pre_pos_fee_block_with_masternode:
            raise RuntimeError("Failed to mine pre-PoS fee probe block with masternode")

        pre_pos_fee_coinbase_with_masternode = coinbase_output_totals(pre_pos_fee_block_with_masternode)
        pre_pos_fee_with_masternode = {
            "height": pre_pos_fee_block_with_masternode.height,
            "miner_fee_share_wepo": to_wepo(
                pre_pos_fee_coinbase_with_masternode.get(miner_address, 0)
                - chain.calculate_block_reward(pre_pos_fee_block_with_masternode.height)
            ),
            "masternode_fee_share_wepo": to_wepo(pre_pos_fee_coinbase_with_masternode.get(masternode_address, 0)),
            "staker_fee_share_wepo": to_wepo(pre_pos_fee_coinbase_with_masternode.get(staker_address, 0)),
            "tx_fee_wepo": to_wepo(pre_pos_fee_tx_with_masternode.fee),
            "masternode_id": pre_pos_masternode_id,
        }

        while chain.get_block_height() < 220:
            block = chain.mine_next_block(miner_address)
            if not block:
                raise RuntimeError("Failed to mine collateral-prep accelerated blocks")

        activation_result = chain.activate_production_staking()

        staker_funding_tx, _ = send_and_confirm(chain, miner_address, staker_address, MIN_STAKE_AMOUNT)

        activated_stake_id = chain.create_stake(staker_address, MIN_STAKE_AMOUNT)
        activated_stake_confirmation_block = chain.mine_block(miner_address)
        if not activated_stake_confirmation_block:
            raise RuntimeError("Failed to confirm canonical stake registration")
        masternode_id = pre_pos_masternode_id

        staker_balance_before_reward = chain.get_balance(staker_address)
        masternode_balance_before_reward = chain.get_balance(masternode_address)
        reward_preview = chain.calculate_staking_rewards(chain.get_block_height() + 1)

        reward_block = chain.mine_block(miner_address)
        if not reward_block:
            raise RuntimeError("Failed to mine staking reward distribution block")

        staker_balance_after_reward = chain.get_balance(staker_address)
        masternode_balance_after_reward = chain.get_balance(masternode_address)

        fee_series = []
        prior_staker_balance = staker_balance_after_reward
        prior_masternode_balance = masternode_balance_after_reward
        prior_recipient_balance = chain.get_balance(recipient_address)

        for block_offset in range(3):
            fee_tx = chain.create_transaction(
                from_address=miner_address,
                to_address=recipient_address,
                amount=(block_offset + 1) * COIN,
            )
            if fee_tx is None:
                raise RuntimeError("Failed to create fee-series transaction")
            if not chain.add_transaction_to_mempool(fee_tx):
                raise RuntimeError("Failed to add fee-series transaction to mempool")

            next_height = chain.get_block_height() + 1
            expected_pos_rewards = chain.calculate_staking_rewards(next_height)
            expected_masternode_fee = int(fee_tx.fee * 0.60)
            expected_validator_fee = int(fee_tx.fee * 0.25)
            expected_staker_fee = fee_tx.fee - expected_masternode_fee - expected_validator_fee

            fee_block = chain.mine_block(miner_address)
            if not fee_block:
                raise RuntimeError("Failed to mine fee-series block")

            fee_coinbase_totals = coinbase_output_totals(fee_block)

            current_staker_balance = chain.get_balance(staker_address)
            current_masternode_balance = chain.get_balance(masternode_address)
            current_recipient_balance = chain.get_balance(recipient_address)

            fee_series.append(
                {
                    "height": fee_block.height,
                    "txid": fee_tx.calculate_txid(),
                    "fee_wepo": to_wepo(fee_tx.fee),
                    "expected_coinbase_staker_fee_wepo": to_wepo(expected_staker_fee),
                    "expected_coinbase_masternode_fee_wepo": to_wepo(expected_masternode_fee),
                    "actual_coinbase_staker_fee_wepo": to_wepo(fee_coinbase_totals.get(staker_address, 0)),
                    "actual_coinbase_masternode_fee_wepo": to_wepo(fee_coinbase_totals.get(masternode_address, 0)),
                    "expected_total_staker_delta_wepo": to_wepo(
                        expected_pos_rewards.get(staker_address, 0) + expected_staker_fee
                    ),
                    "expected_total_masternode_delta_wepo": to_wepo(
                        expected_pos_rewards.get(masternode_address, 0) + expected_masternode_fee
                    ),
                    "actual_total_staker_delta_wepo": to_wepo(current_staker_balance - prior_staker_balance),
                    "actual_total_masternode_delta_wepo": to_wepo(
                        current_masternode_balance - prior_masternode_balance
                    ),
                    "recipient_balance_delta_wepo": to_wepo(current_recipient_balance - prior_recipient_balance),
                }
            )

            prior_staker_balance = current_staker_balance
            prior_masternode_balance = current_masternode_balance
            prior_recipient_balance = current_recipient_balance

        result = {
            "genesis": {
                "height": genesis.height if genesis else None,
                "hash": genesis.get_block_hash() if genesis else None,
                "timestamp_utc": height_to_iso(0),
                "configured_genesis_reward_wepo": to_wepo(REWARD_Q1),
                "scheduled_phase_1_reward_wepo": to_wepo(chain.calculate_block_reward(1)),
                "genesis_address": genesis_address,
                "genesis_balance_wepo": to_wepo(genesis_balance),
            },
            "wallet_flow": {
                "miner_address": miner_address,
                "recipient_address": recipient_address,
                "sender_balance_before_send_wepo": to_wepo(sender_balance_before),
                "transfer_amount_wepo": 30.0,
                "mempool_accepted": mempool_accepted,
                "confirmation_block_height": confirmation_block.height,
                "confirmation_block_reward_wepo": to_wepo(confirmation_block.transactions[0].outputs[0].value),
                "sender_balance_after_send_wepo": to_wepo(sender_balance_after_initial_send),
                "recipient_balance_wepo": to_wepo(recipient_balance_after_initial_send),
                "transaction_fee_wepo": to_wepo(tx.fee),
            },
            "staking_probe": {
                "current_height": pre_activation_probe_height,
                "pos_activation_height": scheduled_pos_activation_height,
                "pre_activation_stake_attempt": "created" if pre_activation_stake_id else "blocked",
                "stake_id": pre_activation_stake_id,
                "stake_error": pre_activation_stake_error,
                "stake_amount_wepo": to_wepo(MIN_STAKE_AMOUNT),
                "balance_before_stake_wepo": to_wepo(stake_balance_before),
                "balance_after_stake_wepo": to_wepo(stake_balance_after),
                "pos_reward_at_activation_wepo": to_wepo(scheduled_pos_reward_at_activation),
                "pos_reward_after_activation_wepo": to_wepo(scheduled_pos_reward_after_activation),
            },
            "reward_distribution_probe": {
                "activation_result": activation_result,
                "staker_address": staker_address,
                "masternode_address": masternode_address,
                "staker_funding_txid": staker_funding_tx.calculate_txid(),
                "masternode_funding_txid": pre_pos_masternode_funding_tx.calculate_txid(),
                "stake_id": activated_stake_id,
                "masternode_id": masternode_id,
                "reward_block_height": reward_block.height,
                "reward_block_pos_pool_wepo": to_wepo(chain.calculate_pos_reward(reward_block.height)),
                "expected_staker_reward_wepo": to_wepo(reward_preview.get(staker_address, 0)),
                "expected_masternode_reward_wepo": to_wepo(reward_preview.get(masternode_address, 0)),
                "actual_staker_reward_wepo": to_wepo(staker_balance_after_reward - staker_balance_before_reward),
                "actual_masternode_reward_wepo": to_wepo(
                    masternode_balance_after_reward - masternode_balance_before_reward
                ),
                "staker_balance_after_reward_wepo": to_wepo(staker_balance_after_reward),
                "masternode_balance_after_reward_wepo": to_wepo(masternode_balance_after_reward),
            },
            "pre_pos_fee_policy_probe": {
                "no_masternode": pre_pos_fee_without_masternode,
                "with_masternode": pre_pos_fee_with_masternode,
            },
            "fee_redistribution_series": fee_series,
            "schedule_markers": schedule_markers,
        }

        print(json.dumps(result, indent=2))
        return 0
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
