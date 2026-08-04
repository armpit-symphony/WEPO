"""Contract for exposing only audited Ghost wallet controls in the UI."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_uses_the_real_ghost_vault_surface():
    dashboard = (ROOT / "frontend/src/components/Dashboard.jsx").read_text(encoding="utf-8")
    vault = (ROOT / "frontend/src/components/GhostVault.jsx").read_text(encoding="utf-8")
    context = (ROOT / "frontend/src/contexts/WalletContext.jsx").read_text(encoding="utf-8")
    assert "import GhostVault from './GhostVault';" in dashboard
    assert "<GhostVault" in dashboard
    for marker in (
        "refreshGhostWalletWitnesses",
        "createGhostReceiverAddress",
        "/api/shielded/witness",
        "loadGhostWasmBridge",
        "createGhostBridge()",
        "saveGhostState(password, refreshed)",
    ):
        assert marker in context
    for marker in (
        "Refresh witnesses",
        "Generate receive address",
        "disabled={busy || isPreGenesis || !password}",
        "local-verification",
        "Ghost transfers remain disabled until mainnet activation",
    ):
        assert marker in vault
    assert "private_key" not in vault
    assert "sendGhostTransaction" not in vault
