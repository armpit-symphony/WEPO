"""Release-artifact wallet controls must fail closed if packaging regresses."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "wepo-desktop-wallet"


def test_windows_release_rebuilds_canonical_frontend_before_signing() -> None:
    package = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    command = package["scripts"]["dist-win"]
    stages = [stage.strip() for stage in command.split("&&")]

    assert stages[0] == "npm run build-ghost-artifacts"
    assert stages[1] == "npm run build-frontend"
    assert stages.index("npm run verify-canonical-client") < stages.index(
        "npm run signing-preflight"
    )
    assert stages.index("npm run signing-preflight") < stages.index(
        "electron-builder --win --x64"
    )
    assert stages[-1] == "npm run verify-windows-release"
    assert package["build"]["extraResources"][0]["from"] == "../frontend/build"
    assert "src/preload.js" in package["build"]["files"]
    assert {
        "from": "../release-artifacts/ghost/artifacts/ghost_wallet_bridge.exe",
        "to": "ghost/ghost_wallet_bridge.exe",
    } in package["build"]["extraResources"]
    assert {
        "from": "../release-artifacts/ghost/artifacts/wepo_zk.wasm",
        "to": "ghost/wepo_zk.wasm",
    } in package["build"]["extraResources"]
    assert {
        "from": "../release-artifacts/ghost/ghost-artifacts.json",
        "to": "ghost/ghost-artifacts.json",
    } in package["build"]["extraResources"]

    validation = (
        ROOT / ".github" / "workflows" / "release-validation.yml"
    ).read_text(encoding="utf-8")
    for marker in (
        "Prove release signing preflight fails closed without signing identity",
        "$preflightOutput = npm run signing-preflight 2>&1",
        "WEPO_WINDOWS_SIGNER_THUMBPRINT must be the 40-character SHA-1",
        "Release signing preflight failed for an unexpected reason.",
        "exit 0",
    ):
        assert marker in validation


def test_release_verifiers_pin_hardened_wallet_boundaries() -> None:
    canonical = (
        DESKTOP / "scripts" / "verify-canonical-client.js"
    ).read_text(encoding="utf-8")
    packaged = (
        DESKTOP / "scripts" / "verify-packaged-desktop.js"
    ).read_text(encoding="utf-8")
    wallet = (
        ROOT / "frontend" / "src" / "contexts" / "WalletContext.jsx"
    ).read_text(encoding="utf-8")
    main = (DESKTOP / "src" / "main.js").read_text(encoding="utf-8")
    preload = (DESKTOP / "src" / "preload.js").read_text(encoding="utf-8")

    for marker in (
        "export function assertStandardSendIntent",
        "assertStandardSendIntent(build.unsigned_tx",
        "canonicalTxidHex(signedTx)",
        "iterations !== SECURE_STORAGE_KDF_ITERATIONS",
        "startsWith('npm run build-ghost-artifacts && npm run build-frontend &&')",
    ):
        assert marker in canonical

    assert "/api/wallet/login" not in wallet
    for marker in (
        "ipcMain.handle('ghost-wallet-request'",
        "ghost_wallet_bridge",
        "windowsHide: true",
    ):
        assert marker in main
    assert "ghostWalletRequest" in preload
    assert "openWallet" not in preload
    assert "saveWallet" not in preload
    for marker in (
        "Refusing to sign: ",
        "node changed the approved recipient or amount",
        "Local wallet password is incorrect, or the encrypted vault is incomplete",
        "Node returned a transaction ID that does not match the signed transaction",
        "wepo-packaged-desktop-content-v1",
        "flag: 'wx'",
    ):
        assert marker in packaged


def test_live_acceptance_binds_package_intent_txid_and_restart() -> None:
    live = (ROOT / "tests" / "wallet_live_acceptance.mjs").read_text(
        encoding="utf-8"
    )
    restart = (
        ROOT / "tests" / "wallet_live_restart_verify.mjs"
    ).read_text(encoding="utf-8")

    for marker in (
        "WEPO_DESKTOP_UNPACKED_ROOT",
        "executable_sha256",
        "assertStandardSendIntent(unsigned.unsigned_tx",
        "const localTxid = canonicalTxidHex(signedTx)",
        "String(txid).toLowerCase() !== localTxid",
        "wepo-wallet-live-acceptance-v2",
        "intent_bound_before_signing: true",
        "private_key_exported: false",
        "mnemonic_exported: false",
        "flag: 'wx'",
    ):
        assert marker in live

    assert "wepo-wallet-live-acceptance-v2" in restart
    assert "prior.local_txid !== prior.txid" in restart
    assert "wepo-wallet-live-restart-evidence-v2" in restart
