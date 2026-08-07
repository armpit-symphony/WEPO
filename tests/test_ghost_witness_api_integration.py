"""Executable node/API coverage for Ghost witness retrieval and verification."""
from __future__ import annotations
import asyncio
import os
import sys

os.environ.setdefault("WEPO_POOLHASH_PURE_PYTHON", "1")
os.environ.setdefault("WEPO_NETWORK_PROFILE", "test")
CORE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core"))
sys.path.insert(0, CORE)

import httpx  # noqa: E402
from wepo_node import WepoFullNode  # noqa: E402


def test_witness_endpoint_returns_a_real_tip_bound_path(tmp_path):
    node = WepoFullNode(
        data_dir=str(tmp_path / "node"),
        p2p_port=0,
        api_port=0,
        enable_mining=False,
        background_mining_enabled=False,
        difficulty_override=1,
        network_profile="test",
    )
    chain = node.blockchain
    chain._ensure_shielded_state()
    commitment = bytes.fromhex("11" * 32)
    position = chain.shielded_tree.append(commitment)
    height = chain.get_block_height()
    chain.conn.execute(
        "INSERT INTO shielded_commitments (position, commitment, block_height, txid, output_index) VALUES (?, ?, ?, ?, ?)",
        (position, commitment, height, "ghost-api-test-tx", 0),
    )
    anchor = chain.shielded_tree.root()
    chain.shielded_anchors.add(anchor, height)
    chain.conn.execute(
        "INSERT OR REPLACE INTO shielded_anchors (anchor, block_height) VALUES (?, ?)",
        (anchor, height),
    )
    chain.conn.commit()

    async def exercise():
        transport = httpx.ASGITransport(app=node.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://node.invalid") as client:
            malformed = await client.post("/api/shielded/witness", json={"commitment": "bad"})
            missing = await client.post("/api/shielded/witness", json={"commitment": "22" * 32})
            response = await client.post(
                "/api/shielded/witness", json={"commitment": commitment.hex()}
            )
        return malformed, missing, response

    malformed, missing, response = asyncio.run(exercise())
    assert malformed.status_code == 400
    assert missing.status_code == 404
    assert response.status_code == 200
    payload = response.json()
    assert payload["format"] == "wepo-ghost-witness-v1"
    assert payload["commitment"] == commitment.hex()
    assert payload["position"] == position
    assert payload["anchor"] == anchor.hex()
    chain_tip = chain.get_latest_block()
    if chain_tip is None:
        raise AssertionError("Canonical chain tip unavailable for assertion")
    chain_tip_hash = chain_tip.get_block_hash()
    if isinstance(chain_tip_hash, bytes):
        chain_tip_hash = chain_tip_hash.hex()
    assert payload["chain_tip"]["hash"] == str(chain_tip_hash).lower()
    assert len(payload["siblings"]) == 32
    assert payload["chain_tip"]["height"] == height
    path = chain.shielded_tree.path(position)
    assert path.compute_root(commitment) == anchor
    tampered = list(path.siblings)
    tampered[0] = bytes([tampered[0][0] ^ 1]) + tampered[0][1:]
    assert path.compute_root(commitment) != __import__("shielded").MerklePath(position, tampered).compute_root(commitment)


def test_bridge_and_protocol_expose_only_the_local_merkle_verifier():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    bridge = open(os.path.join(root, "frontend/src/utils/ghostBridge.js"), encoding="utf-8").read()
    protocol = open(os.path.join(root, "zk/src/ghost/wallet_protocol.rs"), encoding="utf-8").read()
    assert "OP_VERIFY_MERKLE_PATH = 5" in bridge
    assert "verifyMerklePath" in bridge
    assert "OP_VERIFY_MERKLE_PATH: u8 = 5" in protocol
    assert "wallet::verify_merkle_path" in protocol
    assert "Merkle witness was rejected" in bridge
