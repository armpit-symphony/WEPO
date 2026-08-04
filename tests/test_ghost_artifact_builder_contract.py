"""The Ghost release builder must be reproducible and hash-pinned."""

from __future__ import annotations

import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "wepo-production-deployment" / "build-ghost-artifacts.py"


def test_builder_requires_clean_locked_wasm_release_inputs() -> None:
    source = BUILDER.read_text(encoding="utf-8")
    py_compile.compile(str(BUILDER), doraise=True)
    for marker in (
        "wepo-ghost-artifacts-v1",
        "--locked",
        "--target",
        "wasm32-unknown-unknown",
        "refusing to overwrite existing artifact directory",
        "release Ghost artifacts require a clean worktree",
        "zk_cargo_lock_sha256",
        "builder_sha256",
        "sha256_file",
        "ghost_wallet_bridge",
        "wepo_zk.wasm",
    ):
        assert marker in source


def test_desktop_packaging_consumes_only_the_manifest_bound_artifacts() -> None:
    package = (ROOT / "wepo-desktop-wallet" / "package.json").read_text(
        encoding="utf-8"
    )
    verifier = (
        ROOT / "wepo-desktop-wallet" / "scripts" / "verify-canonical-client.js"
    ).read_text(encoding="utf-8")
    for marker in (
        "../release-artifacts/ghost/artifacts/ghost_wallet_bridge.exe",
        "../release-artifacts/ghost/artifacts/wepo_zk.wasm",
        "../release-artifacts/ghost/ghost-artifacts.json",
    ):
        assert marker in package
    assert "wepo-ghost-artifacts-v1" in verifier
    for marker in (
        "clean_worktree !== true",
        "crypto.createHash('sha256')",
        "Ghost artifact hash mismatch",
    ):
        assert marker in verifier
