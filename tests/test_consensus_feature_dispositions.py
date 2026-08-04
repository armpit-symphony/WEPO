#!/usr/bin/env python3
"""Consensus and builder gates for mainnet-deferred transaction surfaces."""

from __future__ import annotations

import copy
from dataclasses import replace
import os
import sys

import pytest


CORE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
)
sys.path.insert(0, CORE)

import blockchain as B  # noqa: E402
from address_utils import generate_wepo_address  # noqa: E402
from dilithium import generate_dilithium_keypair  # noqa: E402


KEM_PUBLIC_KEY = "a" * B.ML_KEM768_PUB_HEX_LEN
SIGNING_PUBLIC_KEY = "b" * B.ML_DSA44_PUB_HEX_LEN


def _owner():
    keypair = generate_dilithium_keypair()
    return keypair, generate_wepo_address(
        keypair.public_key, address_type="quantum"
    )


def _fund(chain: B.WepoBlockchain, address: str, txid: str) -> None:
    chain.conn.execute(
        "INSERT INTO utxos "
        "(txid, vout, address, amount, script_pubkey, spent) "
        "VALUES (?, 0, ?, ?, ?, FALSE)",
        (txid, address, B.COIN, b"output_script"),
    )
    chain.conn.commit()


def test_direct_signed_optional_transactions_fail_when_profile_is_deferred(tmp_path):
    chain = B.WepoBlockchain(
        data_dir=str(tmp_path / "test-chain"), network_profile="test"
    )
    keypair, address = _owner()
    _fund(chain, address, "a" * 64)

    rwa = chain.create_rwa_creation(
        address,
        "c" * B.RWA_ASSET_HASH_HEX_LEN,
        asset_id="deferred-rwa",
        return_unsigned=True,
    )
    rwa.sign_all_inputs(keypair.private_key, keypair.public_key)
    key_registration = chain.create_key_registration(
        address,
        KEM_PUBLIC_KEY,
        SIGNING_PUBLIC_KEY,
        return_unsigned=True,
    )
    key_registration.sign_all_inputs(keypair.private_key, keypair.public_key)

    # Establish that both are otherwise valid, owner-signed transactions.
    assert chain.validate_transaction(rwa)
    assert chain.validate_transaction(key_registration)

    chain.network_profile = replace(
        chain.network_profile,
        rwa_consensus_ready=False,
        messaging_consensus_ready=False,
    )

    for transaction in (rwa, key_registration):
        assert not chain.validate_transaction(transaction)
        assert not chain.add_transaction_to_mempool(transaction)


def test_every_pos_lifecycle_shape_fails_when_pos_is_deferred(tmp_path):
    chain = B.WepoBlockchain(
        data_dir=str(tmp_path / "test-chain"), network_profile="test"
    )
    keypair, address = _owner()
    _fund(chain, address, "d" * 64)
    base = chain.create_rwa_creation(
        address,
        "e" * B.RWA_ASSET_HASH_HEX_LEN,
        asset_id="shape-template",
        return_unsigned=True,
    )
    chain.network_profile = replace(chain.network_profile, pos_consensus_ready=False)

    for tx_type in B.PROTOCOL_LIFECYCLE_TX_TYPES:
        transaction = copy.deepcopy(base)
        transaction.tx_type = tx_type
        transaction.sign_all_inputs(keypair.private_key, keypair.public_key)
        assert not chain._validate_transaction_consensus_shape(
            transaction,
            height=1,
            allow_coinbase=False,
            context="deferred-lifecycle-test",
        )
        assert not chain.validate_transaction(transaction)
        assert not chain.add_transaction_to_mempool(transaction)


@pytest.mark.parametrize(
    ("tx_type", "invoke"),
    [
        (
            B.TX_TYPE_RWA_CREATE,
            lambda chain: chain.create_rwa_creation("owner", "f" * 64),
        ),
        (
            B.TX_TYPE_KEY_REGISTER,
            lambda chain: chain.create_key_registration(
                "owner", KEM_PUBLIC_KEY, SIGNING_PUBLIC_KEY
            ),
        ),
        (
            B.TX_TYPE_STAKE_CREATE,
            lambda chain: chain.create_stake("owner", B.MIN_STAKE_AMOUNT),
        ),
        (
            B.TX_TYPE_STAKE_DEACTIVATE,
            lambda chain: chain.deactivate_stake("missing", "owner"),
        ),
        (
            B.TX_TYPE_MASTERNODE_CREATE,
            lambda chain: chain.create_masternode("owner", "0" * 64, 0),
        ),
        (
            B.TX_TYPE_MASTERNODE_DEACTIVATE,
            lambda chain: chain.deactivate_masternode("missing", "owner"),
        ),
    ],
)
def test_mainnet_builders_fail_before_state_or_balance_lookup(
    tmp_path, tx_type, invoke
):
    chain = B.WepoBlockchain(
        data_dir=str(tmp_path / tx_type), network_profile="mainnet"
    )
    with pytest.raises(ValueError, match=rf"^{tx_type} is not consensus-enabled"):
        invoke(chain)
