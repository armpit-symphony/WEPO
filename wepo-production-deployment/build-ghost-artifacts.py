#!/usr/bin/env python3
"""Build and hash-pin the native and browser-WASM Ghost artifacts.

The default mode is intentionally release-only: a dirty source tree or a
pre-existing output directory is refused. Use --allow-dirty only for local
qualification experiments; the desktop distribution command does not use it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


FORMAT = "wepo-ghost-artifacts-v1"
WASM_TARGET = "wasm32-unknown-unknown"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_capture(command: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.stdout.strip()


def require_clean_tree(root: Path, allow_dirty: bool) -> bool:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout
    dirty = bool(status.strip())
    if dirty and not allow_dirty:
        raise RuntimeError(
            "release Ghost artifacts require a clean worktree; "
            "use --allow-dirty only for local qualification"
        )
    return not dirty


def require_toolchain(root: Path) -> dict[str, str]:
    rustc = run_capture(["rustc", "--version"], cwd=root)
    cargo = run_capture(["cargo", "--version"], cwd=root)
    installed = run_capture(["rustup", "target", "list", "--installed"], cwd=root)
    if WASM_TARGET not in installed.splitlines():
        raise RuntimeError(
            f"Rust target {WASM_TARGET} is not installed; install it before release build"
        )
    return {"rustc": rustc, "cargo": cargo, "rustup_targets": installed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    zk = root / "zk"
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise RuntimeError(f"refusing to overwrite existing artifact directory: {output_dir}")

    clean = require_clean_tree(root, args.allow_dirty)
    toolchain = require_toolchain(root)
    suffix = ".exe" if os.name == "nt" else ""
    native_source = zk / "target" / "release" / f"ghost_wallet_bridge{suffix}"
    wasm_source = zk / "target" / WASM_TARGET / "release" / "wepo_zk.wasm"

    commands = [
        ["cargo", "build", "--release", "--locked", "--manifest-path", str(zk / "Cargo.toml"), "--bin", "ghost_wallet_bridge"],
        ["cargo", "build", "--release", "--locked", "--manifest-path", str(zk / "Cargo.toml"), "--target", WASM_TARGET, "--lib"],
    ]
    logs: list[dict[str, object]] = []
    for command in commands:
        try:
            output = run_capture(command, cwd=root)
            logs.append({"command": command, "status": "pass", "output": output[-4000:]})
        except subprocess.CalledProcessError as exc:
            logs.append({"command": command, "status": "fail", "returncode": exc.returncode})
            raise RuntimeError(f"Ghost artifact build failed: {' '.join(command)}") from exc

    for source in (native_source, wasm_source):
        if not source.is_file() or source.stat().st_size == 0:
            raise RuntimeError(f"required Ghost artifact is missing or empty: {source}")

    artifact_dir = output_dir / "artifacts"
    artifact_dir.mkdir(parents=True, mode=0o700)
    native_name = f"ghost_wallet_bridge{suffix}"
    shutil.copy2(native_source, artifact_dir / native_name)
    shutil.copy2(wasm_source, artifact_dir / "wepo_zk.wasm")
    artifacts = {}
    for name in (native_name, "wepo_zk.wasm"):
        path = artifact_dir / name
        artifacts[name] = {
            "path": f"artifacts/{name}",
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }

    git_head = run_capture(["git", "rev-parse", "HEAD"], cwd=root)
    manifest = {
        "format": FORMAT,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "git_head": git_head,
            "clean_worktree": clean,
            "zk_cargo_lock_sha256": sha256_file(zk / "Cargo.lock"),
            "builder_sha256": sha256_file(Path(__file__).resolve()),
        },
        "toolchain": toolchain,
        "commands": commands,
        "artifacts": artifacts,
        "build_logs": logs,
        "allow_dirty": args.allow_dirty,
    }
    manifest_path = output_dir / "ghost-artifacts.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"PASS Ghost artifacts: {manifest_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"FAIL Ghost artifact build: {error}", file=sys.stderr)
        raise SystemExit(1) from error
