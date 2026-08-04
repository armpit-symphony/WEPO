"""Witness refresh must use the canonical node source and local bridge verifier."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_refresh_adapter_is_tip_bound_and_uses_no_browser_hash_fallback():
    source = (ROOT / "frontend/src/utils/ghostWitnessRefresh.js").read_text(
        encoding="utf-8"
    )
    for marker in (
        "wepo-ghost-witness-v1",
        "/api/shielded/witness",
        "chain tip changed during witness refresh",
        "bridge.verifyMerklePath",
        "refreshGhostWitnesses(",
        "hexToBytes(note.commitment)",
    ):
        assert marker in source
    assert "sha3" not in source.lower()
    assert "rescue" not in source.lower()


def test_node_and_bridge_share_the_merkle_verification_boundary():
    node = (ROOT / "wepo-blockchain/core/wepo_node.py").read_text(encoding="utf-8")
    bridge = (ROOT / "frontend/src/utils/ghostBridge.js").read_text(encoding="utf-8")
    protocol = (ROOT / "zk/src/ghost/wallet_protocol.rs").read_text(encoding="utf-8")
    wallet = (ROOT / "zk/src/ghost/wallet.rs").read_text(encoding="utf-8")
    for source, markers in (
        (node, ("/api/shielded/witness", "shielded_commitments", "chain_tip")),
        (bridge, ("OP_VERIFY_MERKLE_PATH = 5", "verifyMerklePath", "Merkle witness was rejected")),
        (protocol, ("OP_VERIFY_MERKLE_PATH: u8 = 5", "wallet::verify_merkle_path")),
        (wallet, ("pub fn verify_merkle_path", "Merkle witness does not match anchor")),
    ):
        for marker in markers:
            assert marker in source
