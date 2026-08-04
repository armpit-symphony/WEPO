"""Contracts for the retained Ghost fuzz qualification runner."""

from __future__ import annotations

import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "wepo-blockchain" / "scripts" / "wepo_ghost_fuzz_qualification.py"


def test_ghost_fuzz_qualification_runner_is_pinned_and_retained():
    source = RUNNER.read_text(encoding="utf-8")

    py_compile.compile(str(RUNNER), doraise=True)
    assert "wepo-ghost-fuzz-qualification-v1" in source
    assert "rustlang/rust@sha256:512278c783d00322db4554dba748671cc269162b1b43fd577715118f5f64a033" in source
    assert 'CARGO_FUZZ_VERSION = "0.13.2"' in source
    assert 'NIGHTLY_TOOLCHAIN = "nightly-2026-07-31"' in source
    assert "cargo install cargo-fuzz --version" in source
    assert "cargo run --release --locked --bin ghost_fixture" in source
    assert "cargo fuzz run ghost_verifier_request" in source
    assert "cargo fuzz run ghost_protocol" in source
    assert "-max_total_time=" in source
    assert "MAX_VERIFIER_INPUT = 131_072" in source
    assert "MAX_PARSER_INPUT = 4_096" in source
    assert "-print_final_stats=1" in source


def test_ghost_fuzz_qualification_runner_preserves_source_and_evidence():
    source = RUNNER.read_text(encoding="utf-8")

    assert "refusing to use existing evidence directory" in source
    assert "write_exclusive(evidence_dir / \"evidence.json\"" in source
    assert "repo_mount_read_only" in source
    assert "dst=/src,readonly" in source
    assert "tar -C /src" in source
    assert "--exclude=.git" in source
    assert "--exclude=release-evidence" in source
    assert "--exclude=zk/target" in source
    assert "--exclude=zk/fuzz/target" in source
    assert "--exclude=frontend/node_modules" in source
    assert "--exclude=wepo-desktop-wallet/node_modules" in source
    assert "container_removed_after_run" in source
    assert "PRIVATE_HEX" in source
    assert "zk_cargo_lock_sha256" in source
    assert "fuzz_cargo_lock_sha256" in source
    assert "verifier_target_sha256" in source
    assert "trap copy_artifacts EXIT" in source
    assert "/work/zk/fuzz/artifacts" in source
    assert "protocol_target_sha256" in source
    assert "ghost_verifier_request.fuzz-0.log" in source
    assert "ghost_protocol.fuzz-0.log" in source


def test_ghost_fuzz_qualification_runner_keeps_mainnet_closed():
    source = RUNNER.read_text(encoding="utf-8")

    assert "MAINNET_GENESIS_FINALIZED" not in source
    assert "WEPO_NETWORK_PROFILE=mainnet" not in source
    assert "WEPO_REQUIRE_REDIS_RATE_LIMIT" not in source
    assert "aws" not in source.lower()
    assert "digitalocean" not in source.lower()