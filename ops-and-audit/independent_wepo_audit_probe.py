#!/usr/bin/env python3
"""Independent post-fix regression probes for the 2026-07 WEPO audit.

A zero exit status means the audited launch-boundary controls are now enforced:
consensus value-creation probes are rejected, disabled privacy endpoints remain
gated, unsafe node custody routes are retired, and legacy bridge deploy scripts
fail closed.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CORE = REPO_ROOT / "wepo-blockchain" / "core"
BACKEND = REPO_ROOT / "backend"
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(BACKEND))

from address_utils import generate_wepo_address  # noqa: E402
from blockchain import (  # noqa: E402
    Block,
    BlockHeader,
    COIN,
    Transaction,
    TransactionInput,
    TransactionOutput,
    WepoBlockchain,
)
from dilithium import generate_dilithium_keypair  # noqa: E402
from feature_flags import disabled_feature_for_path  # noqa: E402


def make_owner():
    keypair = generate_dilithium_keypair()
    address = generate_wepo_address(keypair.public_key, address_type="quantum")
    return keypair, address


def insert_utxo(blockchain, txid, address, amount):
    blockchain.conn.execute(
        "INSERT INTO utxos "
        "(txid, vout, address, amount, script_pubkey, spent) "
        "VALUES (?, 0, ?, ?, ?, FALSE)",
        (txid, address, amount, b"audit_utxo"),
    )
    blockchain.conn.commit()


def mine_header(blockchain, header):
    while not blockchain.miner.check_difficulty(
        blockchain.miner.calculate_pow_hash(header),
        header.bits,
    ):
        header.nonce += 1


def make_next_block(blockchain, transactions):
    height = blockchain.get_block_height() + 1
    header = BlockHeader(
        version=1,
        prev_hash=blockchain.get_latest_block().get_block_hash(),
        merkle_root="",
        timestamp=blockchain.get_latest_block().header.timestamp + 360,
        bits=1,
        nonce=0,
        consensus_type="pow",
    )
    block = Block(header=header, transactions=transactions, height=height)
    block.header.merkle_root = block.calculate_merkle_root()
    mine_header(blockchain, block.header)
    return block


def probe_consensus():
    temp_dir = tempfile.mkdtemp(prefix="wepo-independent-audit-")
    try:
        blockchain = WepoBlockchain(data_dir=temp_dir)
        blockchain.fixed_difficulty = 1
        blockchain.current_difficulty = 1
        owner_keypair, owner_address = make_owner()
        _, recipient_address = make_owner()
        _, attacker_address = make_owner()

        input_amount = 10 * COIN
        insert_utxo(blockchain, "a" * 64, owner_address, input_amount)

        # A negative output offsets an arbitrarily large positive output. The
        # signed transaction conserves only the algebraic sum, not each output.
        excess = 1_000_000 * COIN
        fee = 10_000
        negative_tx = Transaction(
            version=1,
            inputs=[TransactionInput(prev_txid="a" * 64, prev_vout=0)],
            outputs=[
                TransactionOutput(
                    value=input_amount + excess,
                    script_pubkey=b"audit_positive",
                    address=attacker_address,
                ),
                TransactionOutput(
                    value=1,
                    script_pubkey=b"audit_negative",
                    address=recipient_address,
                ),
            ],
            lock_time=0,
            fee=fee,
        )
        negative_tx.outputs[1].value = -excess - fee
        negative_tx.sign_all_inputs(
            owner_keypair.private_key,
            owner_keypair.public_key,
        )
        negative_output_accepted = blockchain.validate_transaction(negative_tx)

        # Arbitrary privacy fields do not authorize an unsigned spend.
        insert_utxo(blockchain, "b" * 64, owner_address, input_amount)
        privacy_tx = Transaction(
            version=1,
            inputs=[TransactionInput(prev_txid="b" * 64, prev_vout=0)],
            outputs=[
                TransactionOutput(
                    value=input_amount - fee,
                    script_pubkey=b"audit_privacy",
                    address=recipient_address,
                ),
            ],
            lock_time=0,
            fee=fee,
            privacy_proof=b"forged-placeholder-proof",
            ring_signature=b"forged-placeholder-ring",
        )
        privacy_fields_authorize_unsigned = blockchain.validate_transaction(privacy_tx)
        privacy_tx.sign_all_inputs(
            owner_keypair.private_key,
            owner_keypair.public_key,
        )
        signed_with_inert_privacy_fields_accepted = blockchain.validate_transaction(
            privacy_tx
        )

        # validate_block constrains only transactions[0] as coinbase. A second
        # coinbase is skipped by both the double-spend and transaction checks.
        height = blockchain.get_block_height() + 1
        honest_coinbase = blockchain.create_coinbase_transaction(
            height,
            owner_address,
            "pow",
            [],
        )
        extra_coinbase = Transaction(
            version=1,
            inputs=[
                TransactionInput(
                    prev_txid="0" * 64,
                    prev_vout=0xFFFFFFFF,
                    script_sig=b"extra-coinbase",
                )
            ],
            outputs=[
                TransactionOutput(
                    value=10_000_000 * COIN,
                    script_pubkey=b"audit_extra_coinbase",
                    address=attacker_address,
                )
            ],
            lock_time=0,
            fee=0,
        )
        extra_coinbase_accepted = blockchain.validate_block(
            make_next_block(blockchain, [honest_coinbase, extra_coinbase])
        )

        # Even the first coinbase can net an oversized positive output against a
        # negative output because only the sum is compared with the reward limit.
        allowed = blockchain.clamped_base_reward(height, "pow")
        negative_coinbase = blockchain.create_coinbase_transaction(
            height,
            owner_address,
            "pow",
            [],
        )
        negative_coinbase.outputs = [
            TransactionOutput(
                value=allowed + excess,
                script_pubkey=b"audit_coinbase_positive",
                address=attacker_address,
            ),
            TransactionOutput(
                value=1,
                script_pubkey=b"audit_coinbase_negative",
                address=recipient_address,
            ),
        ]
        negative_coinbase.outputs[1].value = -excess
        negative_coinbase_accepted = blockchain.validate_block(
            make_next_block(blockchain, [negative_coinbase])
        )

        return {
            "negative_output_value_creation_accepted": negative_output_accepted,
            "privacy_fields_authorize_unsigned_spend": privacy_fields_authorize_unsigned,
            "owner_signed_tx_with_inert_privacy_fields_accepted": (
                signed_with_inert_privacy_fields_accepted
            ),
            "additional_coinbase_unlimited_issuance_accepted": extra_coinbase_accepted,
            "negative_coinbase_offset_accepted": negative_coinbase_accepted,
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def probe_node_api():
    import httpx
    from wepo_node import WepoFullNode

    temp_dir = tempfile.mkdtemp(prefix="wepo-independent-node-audit-")
    old_privacy = os.environ.pop("WEPO_FEATURE_PRIVACY", None)
    try:
        node = WepoFullNode(
            data_dir=temp_dir,
            p2p_port=0,
            api_port=0,
            enable_mining=False,
            background_mining_enabled=False,
            difficulty_override=1,
        )
        transport = httpx.ASGITransport(app=node.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://audit.invalid",
        ) as client:
            privacy_response = await client.post(
                "/api/privacy/create-proof",
                json={"transaction_data": {"amount": 1}},
            )
            key_response = await client.post("/api/quantum/wallet/create")
            key_payload = key_response.json()
        return {
            "node_privacy_default_status": privacy_response.status_code,
            "node_privacy_default_is_503": privacy_response.status_code == 503,
            "node_wallet_endpoint_status": key_response.status_code,
            "node_wallet_endpoint_retired": key_response.status_code == 410,
            "enabled_node_wallet_endpoint_returns_private_key": (
                key_response.status_code == 200
                and bool((key_payload.get("wallet") or {}).get("private_key"))
            ),
        }
    finally:
        if old_privacy is not None:
            os.environ["WEPO_FEATURE_PRIVACY"] = old_privacy
        shutil.rmtree(temp_dir, ignore_errors=True)


def probe_gates_and_deployment():
    bridge = (REPO_ROOT / "wepo-fast-test-bridge.py").read_text()
    legacy_deploy = (
        REPO_ROOT / "wepo-production-deployment" / "deploy-server.sh"
    ).read_text()
    legacy_upload = (
        REPO_ROOT / "wepo-production-deployment" / "upload-and-deploy.sh"
    ).read_text()
    return {
        "gateway_vault_default_is_gated": (
            disabled_feature_for_path("/api/vault/create")
            == "Privacy / Quantum Vault"
        ),
        "legacy_bridge_defines_vault_routes": (
            '@self.app.post("/api/vault/create")' in bridge
        ),
        "legacy_bridge_has_no_privacy_feature_gate": (
            "WEPO_FEATURE_PRIVACY" not in bridge
        ),
        "legacy_deploy_retired_fail_closed": (
            "LEGACY_DEPLOY_RETIRED=1" in legacy_deploy
            and "exit 1" in legacy_deploy
        ),
        "legacy_upload_retired_fail_closed": (
            "LEGACY_DEPLOY_RETIRED=1" in legacy_upload
            and "exit 1" in legacy_upload
        ),
    }


def main():
    results = {
        "consensus": probe_consensus(),
        "gates_and_deployment": probe_gates_and_deployment(),
        "node_api": asyncio.run(probe_node_api()),
    }
    print(json.dumps(results, indent=2, sort_keys=True))

    expected = [
        not results["consensus"]["negative_output_value_creation_accepted"],
        not results["consensus"]["privacy_fields_authorize_unsigned_spend"],
        not results["consensus"]["owner_signed_tx_with_inert_privacy_fields_accepted"],
        not results["consensus"]["additional_coinbase_unlimited_issuance_accepted"],
        not results["consensus"]["negative_coinbase_offset_accepted"],
        results["gates_and_deployment"]["gateway_vault_default_is_gated"],
        results["gates_and_deployment"]["legacy_bridge_defines_vault_routes"],
        results["gates_and_deployment"]["legacy_bridge_has_no_privacy_feature_gate"],
        results["gates_and_deployment"]["legacy_deploy_retired_fail_closed"],
        results["gates_and_deployment"]["legacy_upload_retired_fail_closed"],
        results["node_api"]["node_privacy_default_is_503"],
        results["node_api"]["node_wallet_endpoint_retired"],
        not results["node_api"]["enabled_node_wallet_endpoint_returns_private_key"],
    ]
    if all(expected):
        print("AUDIT PROBE: launch-boundary regression checks passed.")
        return 0
    print("AUDIT PROBE: one or more launch-boundary checks failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
