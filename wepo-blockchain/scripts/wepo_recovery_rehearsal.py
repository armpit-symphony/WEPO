#!/usr/bin/env python3
"""Measure WEPO crash recovery, backup, restore, and replay at chain volume."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPOSITORY_ROOT = SCRIPT_PATH.parents[2]
CORE = REPOSITORY_ROOT / "wepo-blockchain" / "core"
SCRIPTS = REPOSITORY_ROOT / "wepo-blockchain" / "scripts"
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(SCRIPTS))

from blockchain import WepoBlockchain  # noqa: E402
from wepo_db_backup import create_backup, restore_backup, verify_backup  # noqa: E402


MAINNET_LAUNCH_BLOCK_SECONDS = 360
LOCAL_BASELINE_DAYS = 30
LOCAL_BASELINE_BLOCKS = (
    LOCAL_BASELINE_DAYS * 24 * 60 * 60 // MAINNET_LAUNCH_BLOCK_SECONDS
)
EVIDENCE_FORMAT = "wepo-recovery-rehearsal-v1"
EVENT_PREFIX = "WEPO_REHEARSAL_EVENT "


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _emit(event: str, **fields: Any) -> None:
    print(
        EVENT_PREFIX + json.dumps({"event": event, **fields}, sort_keys=True),
        file=sys.__stdout__,
        flush=True,
    )


def _chain_snapshot(chain: WepoBlockchain) -> dict[str, Any]:
    height = chain.get_block_height()
    tip_hash = chain.get_latest_block().get_block_hash()
    connection = chain.conn
    return {
        "height": height,
        "tip_hash": tip_hash,
        "issued_supply": chain.get_issued_supply(),
        "block_rows": int(
            connection.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
        ),
        "transaction_rows": int(
            connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        ),
        "utxo_rows": int(
            connection.execute("SELECT COUNT(*) FROM utxos").fetchone()[0]
        ),
        "wallet_activity_rows": int(
            connection.execute(
                "SELECT COUNT(*) FROM wallet_activity"
            ).fetchone()[0]
        ),
        "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
        "foreign_key_violations": len(
            connection.execute("PRAGMA foreign_key_check").fetchall()
        ),
        "page_count": int(
            connection.execute("PRAGMA page_count").fetchone()[0]
        ),
        "page_size": int(
            connection.execute("PRAGMA page_size").fetchone()[0]
        ),
        "chain_entries": len(chain.chain),
        "block_index_entries": len(chain.block_index),
        "main_chain_hash_entries": len(chain.main_chain_hashes),
        "mempool_entries": len(chain.mempool),
    }


def _assert_recovered_snapshot(
    snapshot: dict[str, Any], expected: dict[str, Any]
) -> None:
    exact_fields = {
        "height",
        "tip_hash",
        "issued_supply",
        "block_rows",
        "transaction_rows",
        "utxo_rows",
        "wallet_activity_rows",
    }
    mismatches = {
        field: {"expected": expected[field], "actual": snapshot[field]}
        for field in exact_fields
        if snapshot[field] != expected[field]
    }
    if mismatches:
        raise RuntimeError(f"recovered chain state mismatch: {mismatches}")
    if snapshot["quick_check"] != "ok":
        raise RuntimeError("recovered database quick_check failed")
    if snapshot["foreign_key_violations"] != 0:
        raise RuntimeError("recovered database has foreign-key violations")
    expected_entries = snapshot["height"] + 1
    for field in (
        "block_rows",
        "chain_entries",
        "block_index_entries",
        "main_chain_hash_entries",
    ):
        if snapshot[field] != expected_entries:
            raise RuntimeError(
                f"recovered canonical index mismatch for {field}: "
                f"{snapshot[field]} != {expected_entries}"
            )
    if snapshot["mempool_entries"] != 0:
        raise RuntimeError("recovered node unexpectedly retained volatile mempool state")


def _writer(args: argparse.Namespace) -> int:
    from address_utils import generate_wepo_address
    from dilithium import generate_dilithium_keypair, require_real_mldsa

    require_real_mldsa()
    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=False)
    if args.blocks <= args.actors:
        raise ValueError("blocks must exceed the actor-funding block count")

    actors = []
    for _ in range(args.actors):
        keypair = generate_dilithium_keypair()
        actors.append(
            (
                keypair,
                generate_wepo_address(
                    keypair.public_key, address_type="quantum"
                ),
            )
        )
    miner_address = generate_wepo_address(
        b"WEPO_RECOVERY_REHEARSAL_MINER_V1", address_type="quantum"
    )
    sink_address = generate_wepo_address(
        b"WEPO_RECOVERY_REHEARSAL_SINK_V1", address_type="quantum"
    )

    signed_transfers = 0
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        with contextlib.redirect_stdout(devnull):
            chain = WepoBlockchain(
                data_dir=str(data_dir),
                network_profile="test",
                fixed_difficulty=1,
            )
            # Accelerate timestamps from the deterministic test genesis while
            # preserving the consensus-required strict monotonic ordering.
            chain._next_block_timestamp = (
                lambda: chain.get_latest_block().header.timestamp + 1
            )
            for keypair, address in actors:
                if chain.mine_block(address) is None:
                    raise RuntimeError("failed to mine actor funding block")

    _emit(
        "ready",
        height=chain.get_block_height(),
        actors=args.actors,
        target_blocks=args.blocks,
    )

    while chain.get_block_height() < args.blocks:
        with open(os.devnull, "w", encoding="utf-8") as devnull:
            with contextlib.redirect_stdout(devnull):
                for keypair, address in actors:
                    transaction = chain.create_transaction(
                        from_address=address,
                        to_address=sink_address,
                        amount=1,
                        fee=0,
                    )
                    if transaction is None:
                        raise RuntimeError(
                            f"failed to build signed transfer at height "
                            f"{chain.get_block_height() + 1}"
                        )
                    if not transaction.sign_all_inputs(
                        keypair.private_key, keypair.public_key
                    ):
                        raise RuntimeError("failed to sign volume transaction")
                    if not chain.add_transaction_to_mempool(transaction):
                        raise RuntimeError("signed volume transaction was rejected")
                    signed_transfers += 1
                if chain.mine_block(miner_address) is None:
                    raise RuntimeError("failed to mine volume block")
        if (
            chain.get_block_height() % args.progress_every == 0
            or chain.get_block_height() == args.blocks
        ):
            _emit(
                "progress",
                height=chain.get_block_height(),
                signed_transfers=signed_transfers,
            )

    expected = _chain_snapshot(chain)
    expected["signed_transfers"] = signed_transfers
    _emit("committed", **expected)

    keypair, address = actors[0]
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        with contextlib.redirect_stdout(devnull):
            pending = chain.create_transaction(
                from_address=address,
                to_address=sink_address,
                amount=1,
                fee=0,
            )
            if pending is None or not pending.sign_all_inputs(
                keypair.private_key, keypair.public_key
            ):
                raise RuntimeError("failed to build armed crash transaction")
            if not chain.add_transaction_to_mempool(pending):
                raise RuntimeError("armed crash transaction was rejected")

            def pause_during_uncommitted_write() -> int:
                if chain.conn.in_transaction:
                    _emit(
                        "armed",
                        committed_height=expected["height"],
                        uncommitted_height=expected["height"] + 1,
                    )
                    while True:
                        time.sleep(60)
                return 0

            chain.conn.set_progress_handler(pause_during_uncommitted_write, 1)
            completed = chain.mine_block(miner_address)
    raise RuntimeError(f"armed block unexpectedly completed: {completed}")


def _reader(stream, destination: queue.Queue[str]) -> None:
    for line in iter(stream.readline, ""):
        destination.put(line.rstrip("\r\n"))


def _git_value(*arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, sort_keys=True, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _run(args: argparse.Namespace) -> dict[str, Any]:
    work_directory = Path(args.work_directory).resolve()
    work_directory.mkdir(parents=True, exist_ok=False)
    source_dir = work_directory / "source"
    backups_dir = work_directory / "backups"
    restore_dir = work_directory / "restored"
    output_queue: queue.Queue[str] = queue.Queue()
    stderr_lines: list[str] = []
    writer_diagnostics: list[str] = []

    child_command = [
        sys.executable,
        str(SCRIPT_PATH),
        "_writer",
        "--data-dir",
        str(source_dir),
        "--blocks",
        str(args.blocks),
        "--actors",
        str(args.actors),
        "--progress-every",
        str(args.progress_every),
    ]
    started_at = _utc_now()
    build_started = time.perf_counter()
    process = subprocess.Popen(
        child_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None and process.stderr is not None
    stdout_reader = threading.Thread(
        target=_reader, args=(process.stdout, output_queue), daemon=True
    )
    stderr_queue: queue.Queue[str] = queue.Queue()
    stderr_reader = threading.Thread(
        target=_reader, args=(process.stderr, stderr_queue), daemon=True
    )
    stdout_reader.start()
    stderr_reader.start()

    expected = None
    armed = False
    deadline = time.monotonic() + args.timeout_seconds
    try:
        while not armed:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("volume writer did not reach the armed boundary")
            try:
                line = output_queue.get(timeout=min(30, remaining))
            except queue.Empty:
                if process.poll() is not None:
                    break
                print("[recovery-rehearsal] waiting for writer progress", flush=True)
                continue
            if not line.startswith(EVENT_PREFIX):
                writer_diagnostics.append(line)
                continue
            try:
                event = json.loads(line[len(EVENT_PREFIX):])
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"writer emitted non-protocol output: {line}") from exc
            event_name = event.get("event")
            if event_name == "progress":
                print(
                    f"[recovery-rehearsal] height={event['height']} "
                    f"signed_transfers={event['signed_transfers']}",
                    flush=True,
                )
            elif event_name == "committed":
                expected = {key: value for key, value in event.items() if key != "event"}
            elif event_name == "armed":
                armed = True
            elif event_name != "ready":
                raise RuntimeError(f"unknown writer event: {event_name!r}")
            if process.poll() is not None and not armed:
                break

        if not armed or expected is None:
            while not stderr_queue.empty():
                stderr_lines.append(stderr_queue.get_nowait())
            raise RuntimeError(
                f"volume writer exited before crash boundary ({process.poll()}): "
                + " | ".join(stderr_lines[-20:])
            )
        process.kill()
        process.wait(timeout=15)
        if process.returncode == 0:
            raise RuntimeError("forced-kill writer unexpectedly exited successfully")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=15)
        stdout_reader.join(timeout=5)
        stderr_reader.join(timeout=5)
        while not stderr_queue.empty():
            stderr_lines.append(stderr_queue.get_nowait())
        process.stdout.close()
        process.stderr.close()
    build_seconds = time.perf_counter() - build_started

    source_database = source_dir / "blockchain.db"
    crash_artifacts = {
        label: (source_dir / f"blockchain.db{suffix}").stat().st_size
        for label, suffix in {
            "database": "",
            "wal": "-wal",
            "shared_memory": "-shm",
        }.items()
        if (source_dir / f"blockchain.db{suffix}").exists()
    }

    recovery_started = time.perf_counter()
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        with contextlib.redirect_stdout(devnull):
            recovered = WepoBlockchain(
                data_dir=str(source_dir),
                network_profile="test",
                fixed_difficulty=1,
            )
    source_snapshot = _chain_snapshot(recovered)
    _assert_recovered_snapshot(source_snapshot, expected)
    recovered.conn.close()
    recovery_seconds = time.perf_counter() - recovery_started
    source_database_sha256 = _sha256(source_database)

    backup_started = time.perf_counter()
    backup_path, backup_manifest_path = create_backup(
        source_database, backups_dir
    )
    backup_manifest = verify_backup(backup_path, backup_manifest_path)
    backup_seconds = time.perf_counter() - backup_started

    restore_started = time.perf_counter()
    restored_database = restore_backup(
        backup_path,
        restore_dir / "blockchain.db",
        backup_manifest_path,
    )
    restored_database_sha256_before_reopen = _sha256(restored_database)
    restore_copy_seconds = time.perf_counter() - restore_started

    restored_replay_started = time.perf_counter()
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        with contextlib.redirect_stdout(devnull):
            restored = WepoBlockchain(
                data_dir=str(restore_dir),
                network_profile="test",
                fixed_difficulty=1,
            )
    restored_snapshot = _chain_snapshot(restored)
    _assert_recovered_snapshot(restored_snapshot, expected)
    restored.conn.close()
    restored_replay_seconds = time.perf_counter() - restored_replay_started

    minimum_signed_transfers = args.blocks - args.actors
    local_baseline_met = (
        args.blocks >= LOCAL_BASELINE_BLOCKS
        and expected["signed_transfers"] >= minimum_signed_transfers
    )
    evidence = {
        "format": EVIDENCE_FORMAT,
        "status": "pass",
        "release_qualification": False,
        "started_at_utc": started_at,
        "completed_at_utc": _utc_now(),
        "repository": {
            "branch": _git_value("branch", "--show-current"),
            "head": _git_value("rev-parse", "HEAD"),
            "worktree_clean": _git_value("status", "--porcelain") == "",
            "rehearsal_script_sha256": _sha256(SCRIPT_PATH),
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "requested": {
            "post_genesis_blocks": args.blocks,
            "signing_actors": args.actors,
            "progress_every": args.progress_every,
        },
        "local_baseline": {
            "days": LOCAL_BASELINE_DAYS,
            "mainnet_launch_block_seconds": MAINNET_LAUNCH_BLOCK_SECONDS,
            "required_post_genesis_blocks": LOCAL_BASELINE_BLOCKS,
            "required_signed_transfers_for_this_actor_count": minimum_signed_transfers,
            "met": local_baseline_met,
            "meaning": "local engineering baseline only; not release qualification",
        },
        "forced_kill": {
            "boundary": "active uncommitted SQLite block transaction",
            "child_exit_code": process.returncode,
            "pre_recovery_artifact_bytes": crash_artifacts,
        },
        "writer_diagnostics": writer_diagnostics,
        "committed": expected,
        "source_recovery": source_snapshot,
        "source_database_sha256_after_recovery": source_database_sha256,
        "recovery_point_loss_committed_blocks": (
            expected["height"] - source_snapshot["height"]
        ),
        "backup": {
            "path": str(backup_path),
            "manifest_path": str(backup_manifest_path),
            "manifest": backup_manifest,
            "manifest_sha256": _sha256(backup_manifest_path),
        },
        "restored_database": {
            "path": str(restored_database),
            "sha256_before_reopen": restored_database_sha256_before_reopen,
            "snapshot": restored_snapshot,
        },
        "durations_seconds": {
            "build_to_forced_kill": round(build_seconds, 6),
            "source_crash_recovery_replay": round(recovery_seconds, 6),
            "backup_and_verify": round(backup_seconds, 6),
            "restore_copy": round(restore_copy_seconds, 6),
            "restored_replay": round(restored_replay_seconds, 6),
        },
        "work_directory": str(work_directory),
        "remaining_release_gates": [
            "repeat on frozen release-candidate hardware and filesystem",
            "derive transaction-volume target from public testnet telemetry with headroom",
            "encrypted off-host transfer and independent post-transfer verification",
            "trusted-peer catch-up after restore",
            "operator-independent runbook execution and approval",
        ],
    }
    _write_json_exclusive(Path(args.output), evidence)
    return evidence


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode")
    writer = subparsers.add_parser("_writer", help=argparse.SUPPRESS)
    writer.add_argument("--data-dir", required=True)
    writer.add_argument("--blocks", type=int, required=True)
    writer.add_argument("--actors", type=int, required=True)
    writer.add_argument("--progress-every", type=int, required=True)

    parser.add_argument("--work-directory")
    parser.add_argument("--output")
    parser.add_argument("--blocks", type=int, default=LOCAL_BASELINE_BLOCKS)
    parser.add_argument("--actors", type=int, default=1)
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.mode == "_writer":
        return _writer(args)
    if not args.work_directory or not args.output:
        raise SystemExit("--work-directory and --output are required")
    if args.blocks < 2 or args.actors < 1:
        raise SystemExit("--blocks >= 2 and --actors >= 1 are required")
    if args.progress_every < 1 or args.timeout_seconds < 1:
        raise SystemExit("progress and timeout values must be positive")
    evidence = _run(args)
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "output": str(Path(args.output).resolve()),
                "height": evidence["committed"]["height"],
                "signed_transfers": evidence["committed"]["signed_transfers"],
                "local_baseline_met": evidence["local_baseline"]["met"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
