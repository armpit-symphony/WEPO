#!/usr/bin/env python3
"""Source and dependency contracts for the isolated Ghost fuzz targets."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ZK = ROOT / "zk"
FUZZ = ZK / "fuzz"


def test_ghost_fuzz_target_is_isolated_and_reproducible():
    root_manifest = (ZK / "Cargo.toml").read_text(encoding="utf-8")
    fuzz_manifest = (FUZZ / "Cargo.toml").read_text(encoding="utf-8")
    target = (FUZZ / "fuzz_targets" / "ghost_protocol.rs").read_text(
        encoding="utf-8"
    )
    verifier_target = (FUZZ / "fuzz_targets" / "ghost_verifier_request.rs").read_text(
        encoding="utf-8"
    )
    root_lock = (ZK / "Cargo.lock").read_text(encoding="utf-8")
    fuzz_lock = (FUZZ / "Cargo.lock").read_text(encoding="utf-8")

    assert "libfuzzer-sys" not in root_manifest
    assert "libfuzzer-sys" not in root_lock
    assert 'libfuzzer-sys = "0.4"' in fuzz_manifest
    assert 'name = "libfuzzer-sys"' in fuzz_lock
    assert '[dependencies.wepo-zk]' in fuzz_manifest
    assert 'path = ".."' in fuzz_manifest
    assert 'name = "ghost_protocol"' in fuzz_manifest
    assert 'name = "ghost_verifier_request"' in fuzz_manifest
    assert "parse_request(data)" in target
    assert "parse_envelope(data)" in target
    assert "parse_envelope(envelope_bytes)" in target
    assert "statement_digest(&envelope.statement)" in target
    assert "panic::set_hook" in verifier_target
    assert "verify_request(data)" in verifier_target


def test_production_subprocess_and_fuzzer_share_one_verifier_core():
    core = (ZK / "src" / "ghost" / "verifier.rs").read_text(encoding="utf-8")
    binary = (ZK / "src" / "bin" / "ghost_verifier.rs").read_text(
        encoding="utf-8"
    )

    assert "pub fn verify_request(request: &[u8]) -> bool" in core
    assert "complete_bundle::production::verify_complete_bundle" in core
    assert "verifier::{verify_request, MAX_REQUEST_BYTES}" in binary
    assert "fn verify_request(" not in binary


def test_fuzz_inputs_and_outputs_have_explicit_retention_policy():
    ignored = (FUZZ / ".gitignore").read_text(encoding="utf-8").splitlines()
    dictionary = (FUZZ / "dictionaries" / "ghost_protocol.dict").read_text(
        encoding="utf-8"
    )
    seeds = FUZZ / "seeds" / "ghost_protocol"

    assert {"target", "corpus", "artifacts", "coverage"} <= set(ignored)
    assert "WEPO_GHOST_VERIFY_V1" in dictionary
    assert "WEPO_GHOST_PROOF_V1" in dictionary
    assert (seeds / "request_magic").is_file()
    assert (seeds / "proof_magic").is_file()
    hashed_seeds = [path for path in seeds.iterdir() if len(path.name) == 40]
    assert len(hashed_seeds) >= 30
    assert sum(path.stat().st_size for path in hashed_seeds) < 64 * 1024


def test_release_ci_runs_a_pinned_bounded_fuzz_smoke():
    workflow = (ROOT / ".github" / "workflows" / "release-validation.yml").read_text(
        encoding="utf-8"
    )

    required = (
        "rust-ghost-fuzz:",
        "toolchain: nightly-2026-07-31",
        "cargo install cargo-fuzz --version 0.13.2 --locked",
        "cargo fuzz run ghost_protocol fuzz/seeds/ghost_protocol",
        "-dict=fuzz/dictionaries/ghost_protocol.dict",
        "-runs=1000000",
        "cargo run --release --locked --bin ghost_fixture",
        "cargo fuzz run ghost_verifier_request",
        "-runs=1000",
        "-max_len=131072",
        "-max_len=4096",
        "-timeout=5",
        "timeout-minutes: 15",
    )
    for marker in required:
        assert marker in workflow
