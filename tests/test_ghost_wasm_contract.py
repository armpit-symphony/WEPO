"""The browser Ghost transport must use the Rust wallet protocol ABI."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wasm_exports_are_bounded_and_share_the_wallet_handler() -> None:
    source = (ROOT / "zk" / "src" / "ghost" / "wasm.rs").read_text(
        encoding="utf-8"
    )
    module = (ROOT / "zk" / "src" / "ghost" / "mod.rs").read_text(encoding="utf-8")
    loader = (
        ROOT / "frontend" / "src" / "utils" / "ghostWasmBridge.js"
    ).read_text(encoding="utf-8")

    assert "#[cfg(target_arch = \"wasm32\")]" in module
    assert "wallet_protocol::handle_request" in source
    assert "MAX_REQUEST_BYTES" in source
    for marker in (
        "wepo_ghost_alloc",
        "wepo_ghost_dealloc",
        "wepo_ghost_handle_request",
        "wepo_ghost_response_ptr",
        "wepo_ghost_response_len",
    ):
        assert marker in source
        assert marker in loader


def test_browser_loader_has_no_network_or_javascript_prover_fallback() -> None:
    loader = (
        ROOT / "frontend" / "src" / "utils" / "ghostWasmBridge.js"
    ).read_text(encoding="utf-8")
    assert "WebAssembly.instantiate" in loader
    assert "createGhostBridge" in loader
    assert "fetch(" not in loader
