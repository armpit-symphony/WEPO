"""The legacy privacy demo must not be confused with launch Ghost transfers."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE_SOURCE = ROOT / "wepo-blockchain" / "core" / "wepo_node.py"


def test_legacy_privacy_demo_implementation_is_not_imported_or_advertised():
    source = NODE_SOURCE.read_text(encoding="utf-8")

    assert "from privacy import" not in source
    assert "create_privacy_proof(" not in source
    assert "verify_privacy_proof(" not in source
    assert "privacy_engine.generate_stealth_address" not in source
    assert "Production ready" not in source
    assert "Real cryptographic privacy implementation" not in source


def test_legacy_privacy_routes_are_explicitly_retired():
    source = NODE_SOURCE.read_text(encoding="utf-8")

    for route in (
        "/api/privacy/create-proof",
        "/api/privacy/verify-proof",
        "/api/privacy/stealth-address",
        "/api/privacy/info",
    ):
        assert route in source
    assert "status_code=410" in source
    assert "Legacy privacy API retired" in source
