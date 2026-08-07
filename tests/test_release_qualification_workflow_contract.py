"""Contract for the clean-runner release qualification workflow."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_runs_all_required_surfaces_and_hashes_outputs():
    content = (ROOT / ".github/workflows/release-qualification.yml").read_text(encoding="utf-8")
    for marker in (
        "runs-on: ubuntu-24.04",
        "runs-on: windows-2022",
        "cargo test --release --locked --all-targets",
        "wasm32-unknown-unknown",
        "build-ghost-artifacts.py",
        "Expected exactly one Windows Ghost bundle manifest",
        "PSObject.Properties['ghost_wallet_bridge.exe']",
        "npm test -- --reporter=verbose",
        "npm run build",
        "npm run pack",
        "verify-packaged-desktop",
        "Get-FileHash -Algorithm SHA256",
        "github-actions-green.log",
        "ci-artifacts.sha256",
        "release_evidence_assembly=blocked_pending_signed_release_inputs",
        "actions/upload-artifact@v4",
    ):
        assert marker in content
    assert "--allow-dirty" not in content
    assert "$root\\wepo-desktop-wallet\\dist" in content
    assert "$root\\release-artifacts\\ghost" in content


def test_workflow_does_not_claim_signed_release_evidence_without_external_inputs():
    content = (ROOT / ".github/workflows/release-qualification.yml").read_text(encoding="utf-8")
    assert "SHA256SUMS.sig" in content
    assert "release_signing_public_key" in content
    assert "genesis_transcript" in content
    assert "parameter_manifest" in content
    assert "blocked_pending_signed_release_inputs" in content
