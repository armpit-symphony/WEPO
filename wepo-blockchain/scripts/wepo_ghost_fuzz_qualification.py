#!/usr/bin/env python3
"""Run retained Ghost fuzz qualification evidence in the pinned Rust image."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


FORMAT = "wepo-ghost-fuzz-qualification-v1"
IMAGE = "rustlang/rust@sha256:512278c783d00322db4554dba748671cc269162b1b43fd577715118f5f64a033"
CARGO_FUZZ_VERSION = "0.13.2"
NIGHTLY_TOOLCHAIN = "nightly-2026-07-31"
DEFAULT_VERIFIER_SECONDS = 300
DEFAULT_PARSER_SECONDS = 0
MAX_VERIFIER_INPUT = 131_072
MAX_PARSER_INPUT = 4_096
PRIVATE_HEX = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{5120}(?![0-9a-f])")
STAT_RE = re.compile(r"^stat::(?P<name>[a-z_]+):\s+(?P<value>\d+)", re.MULTILINE)
DONE_RE = re.compile(r"^Done (?P<runs>\d+) runs", re.MULTILINE)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_capture(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def write_exclusive(path: Path, document: dict[str, object]) -> None:
    serialized = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if PRIVATE_HEX.search(serialized) or '"private_key"' in serialized:
        raise RuntimeError("refusing to retain private key material")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(serialized)


def parse_stats(log_text: str) -> dict[str, int]:
    stats = {match.group("name"): int(match.group("value")) for match in STAT_RE.finditer(log_text)}
    done = DONE_RE.search(log_text)
    if done:
        stats["done_runs"] = int(done.group("runs"))
    return stats


def docker_path(path: Path) -> str:
    return str(path.resolve())


def shell_script(parser_seconds: int, verifier_seconds: int) -> str:
    parser_block = ""
    if parser_seconds > 0:
        parser_block = f"""
mkdir -p /evidence/corpus/ghost_protocol
cp -a fuzz/seeds/ghost_protocol/. /evidence/corpus/ghost_protocol/
cargo fuzz run ghost_protocol /evidence/corpus/ghost_protocol -- \\
  -dict=fuzz/dictionaries/ghost_protocol.dict \\
  -max_total_time={parser_seconds} \\
  -max_len={MAX_PARSER_INPUT} \\
  -timeout=5 \\
  -jobs=1 \\
  -workers=1 \\
  -print_final_stats=1
cp -f fuzz-0.log /evidence/logs/ghost_protocol.fuzz-0.log
"""

    verifier_block = ""
    if verifier_seconds > 0:
        verifier_block = f"""
mkdir -p /evidence/corpus/ghost_verifier_request
cargo run --release --locked --bin ghost_fixture -- \\
  /evidence/corpus/ghost_verifier_request/honest_request
cargo fuzz run ghost_verifier_request /evidence/corpus/ghost_verifier_request -- \\
  -max_total_time={verifier_seconds} \\
  -max_len={MAX_VERIFIER_INPUT} \\
  -timeout=5 \\
  -jobs=1 \\
  -workers=1 \\
  -print_final_stats=1
cp -f fuzz-0.log /evidence/logs/ghost_verifier_request.fuzz-0.log
"""

    return f"""
set -euo pipefail
mkdir -p /work /evidence/logs /evidence/artifacts
copy_artifacts() {{
  if [ -d /work/zk/fuzz/artifacts ]; then
    cp -a /work/zk/fuzz/artifacts/. /evidence/artifacts/
  fi
}}
trap copy_artifacts EXIT
tar -C /src \
  --exclude=.git \
  --exclude=release-evidence \
  --exclude=zk/target \
  --exclude=zk/fuzz/target \
  --exclude=zk/fuzz/artifacts \
  --exclude=zk/fuzz/corpus \
  --exclude=zk/fuzz/coverage \
  --exclude=frontend/node_modules \
  --exclude=frontend/build \
  --exclude=wepo-desktop-wallet/node_modules \
  --exclude=wepo-desktop-wallet/dist \
  -cf - . | tar -C /work -xf -
cd /work/zk
rustc --version | tee /evidence/toolchain.txt
cargo --version | tee -a /evidence/toolchain.txt
cargo install cargo-fuzz --version {CARGO_FUZZ_VERSION} --locked
cargo fuzz --version | tee -a /evidence/toolchain.txt
{parser_block}
{verifier_block}
copy_artifacts
trap - EXIT
"""


def ensure_clean_evidence_dir(path: Path) -> None:
    if path.exists():
        raise RuntimeError(f"refusing to use existing evidence directory: {path}")
    path.mkdir(parents=True, mode=0o700)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
        help="New directory for retained logs, corpus, artifacts, and evidence.json",
    )
    parser.add_argument(
        "--parser-seconds",
        type=int,
        default=DEFAULT_PARSER_SECONDS,
        help="Seconds for the parser target; zero skips it",
    )
    parser.add_argument(
        "--verifier-seconds",
        type=int,
        default=DEFAULT_VERIFIER_SECONDS,
        help="Seconds for the real verifier target; zero skips it",
    )
    args = parser.parse_args()

    if args.parser_seconds < 0 or args.verifier_seconds < 0:
        raise RuntimeError("fuzz durations must be non-negative")
    if args.parser_seconds == 0 and args.verifier_seconds == 0:
        raise RuntimeError("at least one fuzz target must be enabled")
    if shutil.which("docker") is None:
        raise RuntimeError("docker is required for retained Ghost fuzz evidence")

    repo_root = Path(__file__).resolve().parents[2]
    evidence_dir = args.evidence_dir.resolve()
    ensure_clean_evidence_dir(evidence_dir)

    stdout_log = evidence_dir / "docker.stdout.log"
    stderr_log = evidence_dir / "docker.stderr.log"
    script_path = evidence_dir / "container-run.sh"
    script_path.write_text(
        shell_script(args.parser_seconds, args.verifier_seconds),
        encoding="utf-8",
        newline="\n",
    )

    command = [
        "docker",
        "run",
        "--rm",
        "--mount",
        f"type=bind,src={docker_path(repo_root)},dst=/src,readonly",
        "--mount",
        f"type=bind,src={docker_path(evidence_dir)},dst=/evidence",
        "-w",
        "/work",
        IMAGE,
        "bash",
        "/evidence/container-run.sh",
    ]

    status = "fail"
    error: str | None = None
    started = datetime.now(timezone.utc)
    with stdout_log.open("w", encoding="utf-8", newline="\n") as stdout, stderr_log.open(
        "w", encoding="utf-8", newline="\n"
    ) as stderr:
        try:
            subprocess.run(command, cwd=repo_root, stdout=stdout, stderr=stderr, check=True)
            status = "pass"
        except subprocess.CalledProcessError as exc:
            error = f"docker exited with {exc.returncode}"
    completed = datetime.now(timezone.utc)

    logs: dict[str, object] = {}
    for target in ("ghost_protocol", "ghost_verifier_request"):
        log_path = evidence_dir / "logs" / f"{target}.fuzz-0.log"
        if log_path.exists():
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            logs[target] = {
                "path": str(log_path.relative_to(evidence_dir)).replace("\\", "/"),
                "sha256": sha256(log_path),
                "stats": parse_stats(log_text),
            }

    corpus: dict[str, object] = {}
    corpus_root = evidence_dir / "corpus"
    if corpus_root.exists():
        for target_dir in sorted(path for path in corpus_root.iterdir() if path.is_dir()):
            files = sorted(path for path in target_dir.rglob("*") if path.is_file())
            corpus[target_dir.name] = {
                "files": len(files),
                "bytes": sum(path.stat().st_size for path in files),
                "sha256": {
                    str(path.relative_to(evidence_dir)).replace("\\", "/"): sha256(path)
                    for path in files[:200]
                },
            }

    artifacts_root = evidence_dir / "artifacts"
    artifact_files = sorted(path for path in artifacts_root.rglob("*") if path.is_file()) if artifacts_root.exists() else []

    try:
        git_head = run_capture(["git", "rev-parse", "HEAD"], cwd=repo_root)
    except subprocess.CalledProcessError:
        git_head = "unknown"

    document: dict[str, object] = {
        "format": FORMAT,
        "status": status,
        "error": error,
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "durations_seconds": {
            "parser": args.parser_seconds,
            "verifier": args.verifier_seconds,
        },
        "toolchain": {
            "image": IMAGE,
            "nightly_toolchain": NIGHTLY_TOOLCHAIN,
            "cargo_fuzz_version": CARGO_FUZZ_VERSION,
        },
        "limits": {
            "parser_max_len": MAX_PARSER_INPUT,
            "verifier_max_len": MAX_VERIFIER_INPUT,
            "timeout_seconds": 5,
            "jobs": 1,
            "workers": 1,
        },
        "source": {
            "git_head": git_head,
            "runner_sha256": sha256(Path(__file__).resolve()),
            "zk_cargo_lock_sha256": sha256(repo_root / "zk" / "Cargo.lock"),
            "fuzz_cargo_lock_sha256": sha256(repo_root / "zk" / "fuzz" / "Cargo.lock"),
            "verifier_target_sha256": sha256(
                repo_root / "zk" / "fuzz" / "fuzz_targets" / "ghost_verifier_request.rs"
            ),
            "protocol_target_sha256": sha256(
                repo_root / "zk" / "fuzz" / "fuzz_targets" / "ghost_protocol.rs"
            ),
        },
        "logs": logs,
        "corpus": corpus,
        "artifacts": {
            "files": len(artifact_files),
            "bytes": sum(path.stat().st_size for path in artifact_files),
        },
        "docker": {
            "repo_mount_read_only": True,
            "evidence_mount_writable": True,
            "container_removed_after_run": True,
        },
    }
    write_exclusive(evidence_dir / "evidence.json", document)
    print(f"{status.upper()} evidence={evidence_dir / 'evidence.json'}")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())