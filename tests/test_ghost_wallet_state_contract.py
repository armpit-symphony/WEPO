"""Durable Ghost note state must stay bounded and reorg-safe."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "frontend" / "src" / "utils" / "ghostWalletState.js"


def test_ghost_state_contract_has_atomic_scan_reorg_and_secure_storage_paths():
    source = STATE.read_text(encoding="utf-8")
    for marker in (
        "wepo-ghost-wallet-state-v1",
        "GHOST_MAX_NOTE_RECORDS = 4096",
        "GHOST_MAX_BLOCK_JOURNAL = 4096",
        "applyGhostCanonicalBlock",
        "disconnectGhostToHeight",
        "refreshGhostWitnesses",
        "a local output scanner is required",
        "a local verifier",
        "saveGhostWalletState",
        "getSecureItem",
        "tip hash does not match the journal",
    ):
        assert marker in source
