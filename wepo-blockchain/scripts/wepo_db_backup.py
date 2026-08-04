#!/usr/bin/env python3
"""Create, verify, and restore atomic WEPO SQLite chain backups."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3
from typing import Any


CHUNK_SIZE = 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path(backup_path: Path) -> Path:
    return backup_path.with_name(f"{backup_path.name}.json")


def _open_read_only(database_path: Path) -> sqlite3.Connection:
    uri = f"{database_path.resolve().as_uri()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _database_evidence(connection: sqlite3.Connection) -> dict[str, Any]:
    integrity = connection.execute("PRAGMA quick_check").fetchone()
    if not integrity or integrity[0] != "ok":
        detail = integrity[0] if integrity else "no result"
        raise RuntimeError(f"database integrity check failed: {detail}")
    tip = connection.execute(
        "SELECT height, hash FROM blocks ORDER BY height DESC LIMIT 1"
    ).fetchone()
    return {
        "quick_check": "ok",
        "height": int(tip[0]) if tip else -1,
        "tip_hash": str(tip[1]) if tip else None,
        "page_count": int(
            connection.execute("PRAGMA page_count").fetchone()[0]
        ),
        "page_size": int(
            connection.execute("PRAGMA page_size").fetchone()[0]
        ),
    }


def create_backup(
    database_path: str | os.PathLike[str],
    output_directory: str | os.PathLike[str],
) -> tuple[Path, Path]:
    """Create and atomically publish a verified online SQLite backup."""
    source_path = Path(database_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"blockchain database not found: {source_path}")

    output_path = Path(output_directory).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_path = output_path / f"wepo-chain-{timestamp}.sqlite3"
    temporary_backup = output_path / f".{backup_path.name}.{os.getpid()}.tmp"
    manifest_path = _manifest_path(backup_path)
    temporary_manifest = output_path / f".{manifest_path.name}.{os.getpid()}.tmp"

    source = None
    destination = None
    try:
        source = _open_read_only(source_path)
        destination = sqlite3.connect(temporary_backup)
        source.backup(destination)
        destination.commit()
        evidence = _database_evidence(destination)
        destination.close()
        destination = None

        size_bytes = temporary_backup.stat().st_size
        digest = _sha256(temporary_backup)
        manifest = {
            "format": "wepo-sqlite-backup-v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "backup_file": backup_path.name,
            "size_bytes": size_bytes,
            "sha256": digest,
            **evidence,
        }
        with temporary_manifest.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(manifest, output, sort_keys=True, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())

        os.replace(temporary_backup, backup_path)
        os.replace(temporary_manifest, manifest_path)
        return backup_path, manifest_path
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
        temporary_backup.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)


def verify_backup(
    backup_path: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Verify manifest binding and SQLite structure, returning the manifest."""
    backup = Path(backup_path).resolve()
    manifest_file = (
        Path(manifest_path).resolve()
        if manifest_path is not None
        else _manifest_path(backup)
    )
    if not backup.is_file() or not manifest_file.is_file():
        raise FileNotFoundError("backup and manifest are both required")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    required_fields = {
        "format",
        "created_at_utc",
        "backup_file",
        "size_bytes",
        "sha256",
        "quick_check",
        "height",
        "tip_hash",
        "page_count",
        "page_size",
    }
    if not isinstance(manifest, dict) or set(manifest) != required_fields:
        raise ValueError("backup manifest has an invalid schema")
    if manifest["format"] != "wepo-sqlite-backup-v1":
        raise ValueError("unsupported backup manifest format")
    if manifest["backup_file"] != backup.name:
        raise ValueError("manifest is bound to a different backup filename")
    if type(manifest["size_bytes"]) is not int:
        raise ValueError("manifest size is not canonical")
    if backup.stat().st_size != manifest["size_bytes"]:
        raise ValueError("backup size does not match manifest")
    if _sha256(backup) != manifest["sha256"]:
        raise ValueError("backup hash does not match manifest")

    connection = _open_read_only(backup)
    try:
        evidence = _database_evidence(connection)
    finally:
        connection.close()
    for key in ("quick_check", "height", "tip_hash", "page_count", "page_size"):
        if evidence[key] != manifest[key]:
            raise ValueError(f"backup evidence mismatch for {key}")
    return manifest


def restore_backup(
    backup_path: str | os.PathLike[str],
    target_database_path: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str] | None = None,
) -> Path:
    """Verify and atomically restore a backup without overwriting live data."""
    backup = Path(backup_path).resolve()
    target = Path(target_database_path).resolve()
    if target.exists():
        raise FileExistsError(
            f"refusing to overwrite existing blockchain database: {target}"
        )
    verify_backup(backup, manifest_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_target = target.parent / f".{target.name}.{os.getpid()}.restore"
    try:
        shutil.copy2(backup, temporary_target)
        connection = _open_read_only(temporary_target)
        try:
            _database_evidence(connection)
        finally:
            connection.close()
        os.replace(temporary_target, target)
        return target
    finally:
        temporary_target.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--database", required=True)
    create.add_argument("--output-directory", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--backup", required=True)
    verify.add_argument("--manifest")
    restore = subparsers.add_parser("restore")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--manifest")
    restore.add_argument("--target", required=True)
    args = parser.parse_args()

    if args.command == "create":
        backup, manifest = create_backup(args.database, args.output_directory)
        print(json.dumps({"backup": str(backup), "manifest": str(manifest)}))
    elif args.command == "verify":
        print(json.dumps(verify_backup(args.backup, args.manifest), sort_keys=True))
    else:
        restored = restore_backup(args.backup, args.target, args.manifest)
        print(json.dumps({"restored": str(restored)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
