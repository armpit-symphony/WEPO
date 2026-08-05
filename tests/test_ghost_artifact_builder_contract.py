"""The Ghost release builder must be reproducible and hash-pinned."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import py_compile
import subprocess
from pathlib import Path

import pytest


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
        "sha256_git_blob",
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

    validation_workflow = (
        ROOT / ".github" / "workflows" / "release-validation.yml"
    ).read_text(encoding="utf-8")
    assert "Expected exactly one Windows Ghost bundle manifest" in validation_workflow
    assert "PSObject.Properties['ghost_wallet_bridge.exe']" in validation_workflow


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_builder():
    spec = importlib.util.spec_from_file_location("wepo_ghost_builder", BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prebuilt_bundle_is_verified_and_tamper_rejected(tmp_path: Path) -> None:
    module = _load_builder()
    bundle = tmp_path / "bundle"
    artifacts = bundle / "artifacts"
    artifacts.mkdir(parents=True)
    native = artifacts / "ghost_wallet_bridge.exe"
    wasm = artifacts / "wepo_zk.wasm"
    native.write_bytes(b"verified windows native ghost bridge")
    wasm.write_bytes(b"verified browser wasm ghost module")
    manifest = {
        "format": "wepo-ghost-artifacts-v1",
        "source": {
            "git_head": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "clean_worktree": True,
            "builder_sha256": module.sha256_git_blob(ROOT, BUILDER),
            "zk_cargo_lock_sha256": module.sha256_git_blob(
                ROOT, ROOT / "zk" / "Cargo.lock"
            ),
        },
        "artifacts": {
            native.name: {
                "path": "artifacts/ghost_wallet_bridge.exe",
                "bytes": native.stat().st_size,
                "sha256": _sha256(native),
            },
            wasm.name: {
                "path": "artifacts/wepo_zk.wasm",
                "bytes": wasm.stat().st_size,
                "sha256": _sha256(wasm),
            },
        },
    }
    (bundle / "ghost-artifacts.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    native_source, wasm_source, _, _ = module.load_verified_prebuilt_bundle(
        bundle, ROOT, native.name
    )
    assert native_source == native
    assert wasm_source == wasm

    native.write_bytes(b"x" * manifest["artifacts"][native.name]["bytes"])
    with pytest.raises(RuntimeError, match="hash mismatch"):
        module.load_verified_prebuilt_bundle(bundle, ROOT, native.name)


def test_source_bindings_hash_git_blobs_not_checkout_line_endings() -> None:
    module = _load_builder()
    tracked = "wepo-production-deployment/build-ghost-artifacts.py"
    committed = subprocess.run(
        ["git", "show", f"HEAD:{tracked}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    assert module.sha256_git_blob(ROOT, BUILDER) == hashlib.sha256(
        committed
    ).hexdigest()
