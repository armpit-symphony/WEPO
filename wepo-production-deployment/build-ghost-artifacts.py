#!/usr/bin/env python3
"""Build and hash-pin the native and browser-WASM Ghost artifacts.

The default mode is intentionally release-only: a dirty source tree or a
pre-existing output directory is refused. Use --allow-dirty only for local
qualification experiments; the desktop distribution command does not use it.
Windows release packaging consumes a verified prebuilt bundle because the
upstream winter-air crate contains the reserved filename src/air/aux.rs, which
a fresh Windows Cargo registry cannot extract.
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


def require_toolchain(
    root: Path, additional_targets: list[str] | None = None
) -> dict[str, str]:
    rustc = run_capture(["rustc", "--version"], cwd=root)
    cargo = run_capture(["cargo", "--version"], cwd=root)
    installed = run_capture(["rustup", "target", "list", "--installed"], cwd=root)
    required_targets = [WASM_TARGET, *(additional_targets or [])]
    for target in required_targets:
        if target not in installed.splitlines():
            raise RuntimeError(
                f"Rust target {target} is not installed; install it before release build"
            )
    return {"rustc": rustc, "cargo": cargo, "rustup_targets": installed}


def load_verified_prebuilt_bundle(
    bundle_dir: Path, root: Path, native_name: str
) -> tuple[Path, Path, Path, dict[str, object]]:
    manifest_path = bundle_dir / "ghost-artifacts.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"prebuilt Ghost bundle manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"prebuilt Ghost bundle manifest is invalid: {manifest_path}") from error
    if manifest.get("format") != FORMAT:
        raise RuntimeError("prebuilt Ghost bundle has an unsupported manifest format")
    current_head = run_capture(["git", "rev-parse", "HEAD"], cwd=root)
    source = manifest.get("source")
    if not isinstance(source, dict) or source.get("git_head") != current_head:
        raise RuntimeError("prebuilt Ghost bundle source commit does not match the packaging commit")
    if source.get("builder_sha256") != sha256_file(Path(__file__).resolve()):
        raise RuntimeError("prebuilt Ghost bundle builder does not match the packaging builder")
    if source.get("zk_cargo_lock_sha256") != sha256_file(root / "zk" / "Cargo.lock"):
        raise RuntimeError("prebuilt Ghost bundle Cargo.lock does not match the packaging lockfile")
    if source.get("clean_worktree") is not True:
        raise RuntimeError("prebuilt Ghost bundle was not built from a clean worktree")
    artifact_records = manifest.get("artifacts")
    if not isinstance(artifact_records, dict):
        raise RuntimeError("prebuilt Ghost bundle has no artifact records")

    paths: dict[str, Path] = {}
    for name in (native_name, "wepo_zk.wasm"):
        record = artifact_records.get(name)
        if not isinstance(record, dict):
            raise RuntimeError(f"prebuilt Ghost bundle is missing the {name} record")
        relative = record.get("path")
        expected_hash = record.get("sha256")
        expected_bytes = record.get("bytes")
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise RuntimeError(f"prebuilt Ghost bundle has an invalid {name} record")
        candidate = (bundle_dir / relative).resolve()
        try:
            candidate.relative_to(bundle_dir.resolve())
        except ValueError as error:
            raise RuntimeError(f"prebuilt Ghost bundle path escapes its directory: {relative}") from error
        if not candidate.is_file() or candidate.stat().st_size == 0:
            raise RuntimeError(f"prebuilt Ghost bundle artifact is missing or empty: {candidate}")
        if expected_bytes != candidate.stat().st_size:
            raise RuntimeError(f"prebuilt Ghost bundle size mismatch for {name}")
        if sha256_file(candidate) != expected_hash:
            raise RuntimeError(f"prebuilt Ghost bundle hash mismatch for {name}")
        paths[name] = candidate
    return paths[native_name], paths["wepo_zk.wasm"], manifest_path, manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument(
        "--prebuilt-dir",
        type=Path,
        help="consume a clean-runner Ghost bundle verified by its manifest",
    )
    parser.add_argument(
        "--native-target",
        help="build the native bridge for this Rust target triple",
    )
    parser.add_argument(
        "--native-name",
        help="name of the native artifact in the output bundle",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    zk = root / "zk"
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise RuntimeError(f"refusing to overwrite existing artifact directory: {output_dir}")

    clean = require_clean_tree(root, args.allow_dirty)
    suffix = ".exe" if os.name == "nt" else ""
    native_name = args.native_name or f"ghost_wallet_bridge{suffix}"
    prebuilt_manifest: dict[str, object] | None = None
    prebuilt_manifest_path: Path | None = None
    native_target = args.native_target
    if args.prebuilt_dir is not None:
        if native_target is not None:
            raise RuntimeError("--native-target cannot be combined with --prebuilt-dir")
        native_source, wasm_source, prebuilt_manifest_path, prebuilt_manifest = (
            load_verified_prebuilt_bundle(
                args.prebuilt_dir.resolve(), root, native_name
            )
        )
        toolchain = {
            "mode": "prebuilt-verified",
            "source_manifest": str(prebuilt_manifest_path),
        }
        commands = [["consume-prebuilt-bundle", str(prebuilt_manifest_path)]]
    else:
        toolchain = require_toolchain(
            root, [native_target] if native_target is not None else None
        )
        if native_target is None:
            native_source = zk / "target" / "release" / native_name
            native_command = [
                "cargo",
                "build",
                "--release",
                "--locked",
                "--manifest-path",
                str(zk / "Cargo.toml"),
                "--bin",
                "ghost_wallet_bridge",
            ]
        else:
            native_source = (
                zk / "target" / native_target / "release" / native_name
            )
            native_command = [
                "cargo",
                "build",
                "--release",
                "--locked",
                "--manifest-path",
                str(zk / "Cargo.toml"),
                "--target",
                native_target,
                "--bin",
                "ghost_wallet_bridge",
            ]
        wasm_source = zk / "target" / WASM_TARGET / "release" / "wepo_zk.wasm"
        commands = [
            native_command,
            [
                "cargo",
                "build",
                "--release",
                "--locked",
                "--manifest-path",
                str(zk / "Cargo.toml"),
                "--target",
                WASM_TARGET,
                "--lib",
            ],
        ]

    logs: list[dict[str, object]] = []
    for command in commands:
        try:
            output = run_capture(command, cwd=root) if command[0] == "cargo" else ""
            logs.append({"command": command, "status": "pass", "output": output[-4000:]})
        except subprocess.CalledProcessError as exc:
            logs.append({"command": command, "status": "fail", "returncode": exc.returncode})
            detail = (exc.stdout or "").strip()
            error_suffix = f"\n{detail[-8000:]}" if detail else ""
            raise RuntimeError(
                f"Ghost artifact build failed: {' '.join(command)}{error_suffix}"
            ) from exc

    for source in (native_source, wasm_source):
        if not source.is_file() or source.stat().st_size == 0:
            raise RuntimeError(f"required Ghost artifact is missing or empty: {source}")

    artifact_dir = output_dir / "artifacts"
    artifact_dir.mkdir(parents=True, mode=0o700)
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
        "prebuilt": {
            "verified": prebuilt_manifest is not None,
            "manifest_sha256": (
                sha256_file(prebuilt_manifest_path) if prebuilt_manifest_path is not None else None
            ),
        },
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
