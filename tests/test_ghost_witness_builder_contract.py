"""The durable Ghost note state must feed only the audited local bridge."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "frontend" / "src" / "utils" / "ghostWitnessBuilder.js"


def test_witness_builder_is_fail_closed_and_commitment_bound():
    source = BUILDER.read_text(encoding="utf-8")
    for marker in (
        "validateGhostWalletState(state)",
        "bridge.kind !== LOCAL_BRIDGE_KIND",
        "bridge.nullifier",
        "note.witness",
        "witness.anchor !== anchor",
        "spendingKey: spendingKey.slice()",
        "computed nullifier",
        "bridge.commitNote",
        "computed commitment",
        "return { spends, outputs }",
    ):
        assert marker in source


def test_witness_builder_does_not_persist_secret_material():
    source = BUILDER.read_text(encoding="utf-8")
    assert "setSecureItem" not in source
    assert "saveGhostWalletState" not in source
