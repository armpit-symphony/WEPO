#!/usr/bin/env python3
"""Abruptly restart an attacked WEPO node and prove exact peer catch-up."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import platform
import socket
import struct
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
ROOT = SCRIPT_PATH.parents[2]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from blockchain import WepoBlockchain  # noqa: E402
from p2p_network import MAX_BANNED_HOSTS, MAX_PEERS  # noqa: E402
from wepo_p2p_hostile_soak import (  # noqa: E402
    _directory_bytes,
    _sha256,
    _write_json_exclusive,
)
from wepo_p2p_sync_smoke import (  # noqa: E402
    SOURCE_API_PORT,
    SOURCE_P2P_PORT,
    TARGET_API_PORT,
    TARGET_P2P_PORT,
    ManagedNode,
    WepoArgon2Miner,
    connected_to_remote_peer,
    ensure_port_free,
    generate_wepo_address,
    get_chain_info,
    get_status,
    has_any_peer_connection,
    mine_to_height,
    wait_for_condition,
    wait_for_height,
)


EVIDENCE_FORMAT = "wepo-p2p-restart-under-load-v1"
LOCAL_BASELINE_INITIAL_HEIGHT = 10
LOCAL_BASELINE_OFFLINE_BLOCKS = 5
LOCAL_BASELINE_ONLINE_ATTACKS = 100
LOCAL_BASELINE_POST_RESTART_ATTACKS = 50


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_ip(index: int) -> str:
    value = index + 100
    return (
        f"127.{1 + ((value // (254 * 254)) % 254)}."
        f"{1 + ((value // 254) % 254)}.{1 + (value % 254)}"
    )


def _attack_worker(
    stop: threading.Event,
    phase: dict[str, str],
    counters: dict[str, int],
    rate: float,
) -> None:
    header = struct.pack(
        "<4s12sI4s",
        b"NOPE",
        b"ping".ljust(12, b"\x00"),
        0,
        b"\x00" * 4,
    )
    next_attack = time.monotonic()
    index = 0
    while not stop.is_set():
        now = time.monotonic()
        if now < next_attack:
            stop.wait(min(next_attack - now, 0.01))
            continue
        phase_name = phase["name"]
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(0.5)
            sock.bind((_source_ip(index), 0))
            sock.connect(("127.0.0.1", TARGET_P2P_PORT))
            sock.sendall(header)
            counters[f"{phase_name}_delivered"] += 1
            try:
                while sock.recv(4096):
                    pass
            except OSError:
                pass
        except OSError:
            # Attribute a connect/send failure at observation time. The planned
            # kill can otherwise misclassify an in-flight attempt as online.
            phase_name = phase["name"]
            counters[f"{phase_name}_errors"] += 1
        finally:
            sock.close()
        counters[f"{phase_name}_scheduled"] += 1
        index += 1
        next_attack += 1.0 / rate
        if next_attack < time.monotonic() - 1.0:
            next_attack = time.monotonic()


def _wait_for_counter(counters: dict[str, int], key: str, minimum: int) -> None:
    wait_for_condition(
        lambda: counters[key] >= minimum,
        timeout_seconds=20,
        description=f"{key} >= {minimum}",
        interval_seconds=0.05,
    )


def _replay_snapshot(data_directory: Path) -> dict[str, Any]:
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        with contextlib.redirect_stdout(devnull):
            chain = WepoBlockchain(
                data_dir=str(data_directory),
                network_profile="test",
                fixed_difficulty=1,
            )
    try:
        return {
            "height": chain.get_block_height(),
            "tip": chain.get_latest_block().get_block_hash(),
            "issued_supply": chain.get_issued_supply(),
            "quick_check": chain.conn.execute("PRAGMA quick_check").fetchone()[0],
            "foreign_key_violations": len(
                chain.conn.execute("PRAGMA foreign_key_check").fetchall()
            ),
        }
    finally:
        chain.conn.close()


def _run(args: argparse.Namespace) -> dict[str, Any]:
    work_directory = Path(args.work_directory).resolve()
    work_directory.mkdir(parents=True, exist_ok=False)
    log_directory = work_directory / "logs"
    source_directory = work_directory / "source"
    target_directory = work_directory / "target"
    output_path = Path(args.output).resolve()

    for port in (
        SOURCE_P2P_PORT,
        TARGET_P2P_PORT,
        SOURCE_API_PORT,
        TARGET_API_PORT,
    ):
        ensure_port_free(port)

    miner = WepoArgon2Miner()
    miner_address = generate_wepo_address(
        "wepo-p2p-restart-under-load", address_type="quantum"
    )
    source = ManagedNode(
        name="source",
        data_dir=source_directory,
        log_dir=log_directory,
        p2p_port=SOURCE_P2P_PORT,
        api_port=SOURCE_API_PORT,
        miner_address=miner_address,
    )
    target = ManagedNode(
        name="target",
        data_dir=target_directory,
        log_dir=log_directory,
        p2p_port=TARGET_P2P_PORT,
        api_port=TARGET_API_PORT,
        miner_address=miner_address,
    )
    phase = {"name": "online"}
    counters = {
        f"{name}_{suffix}": 0
        for name in ("online", "outage", "post_restart")
        for suffix in ("scheduled", "delivered", "errors")
    }
    stop = threading.Event()
    attack_thread = threading.Thread(
        target=_attack_worker,
        args=(stop, phase, counters, args.attack_rate),
        daemon=True,
        name="wepo-restart-hostile-load-generator",
    )
    started_at = _utc_now()
    started = time.monotonic()
    abrupt_exit_code = None
    target_before_kill = None
    source_while_target_offline = None
    source_after = None
    target_after = None
    target_status_after = None
    attack_thread_joined = False

    try:
        target.start()
        source.start()
        wait_for_condition(
            lambda: connected_to_remote_peer(source.base_url, TARGET_P2P_PORT),
            timeout_seconds=20,
            description="source connection to target",
        )
        wait_for_condition(
            lambda: has_any_peer_connection(target.base_url),
            timeout_seconds=20,
            description="target connection to source",
        )
        attack_thread.start()

        mine_to_height(
            source.base_url,
            miner_address,
            miner,
            args.initial_height,
        )
        wait_for_height(
            target.base_url,
            args.initial_height,
            30,
            "attacked target initial sync",
        )
        _wait_for_counter(
            counters, "online_delivered", args.minimum_online_attacks
        )
        target_before_kill = get_chain_info(target.base_url)
        target_database_bytes_before_kill = _directory_bytes(target_directory)

        phase["name"] = "outage"
        abrupt_exit_code = target.force_kill()
        mine_to_height(
            source.base_url,
            miner_address,
            miner,
            args.initial_height + args.offline_blocks,
        )
        source_while_target_offline = get_chain_info(source.base_url)
        _wait_for_counter(counters, "outage_scheduled", 5)

        target.start()
        wait_for_condition(
            lambda: has_any_peer_connection(target.base_url),
            timeout_seconds=30,
            description="target peer reconnect after abrupt restart",
        )
        wait_for_height(
            target.base_url,
            args.initial_height + args.offline_blocks,
            45,
            "target catch-up after abrupt restart",
        )
        wait_for_condition(
            lambda: (
                get_chain_info(target.base_url)["best_block_hash"]
                == get_chain_info(source.base_url)["best_block_hash"]
            ),
            timeout_seconds=20,
            description="exact target tip convergence",
        )

        phase["name"] = "post_restart"
        _wait_for_counter(
            counters,
            "post_restart_delivered",
            args.minimum_post_restart_attacks,
        )
        source_after = get_chain_info(source.base_url)
        target_after = get_chain_info(target.base_url)
        target_status_after = get_status(target.base_url)
    finally:
        stop.set()
        if attack_thread.is_alive():
            attack_thread.join(timeout=3.0)
        attack_thread_joined = not attack_thread.is_alive()
        source.stop()
        target.stop()

    source_replay = _replay_snapshot(source_directory)
    target_replay = _replay_snapshot(target_directory)
    target_database_bytes_after_recovery = _directory_bytes(target_directory)
    completed_at = _utc_now()
    duration = time.monotonic() - started

    acceptance = {
        "abrupt_kill_was_nonzero": abrupt_exit_code not in (None, 0),
        "target_was_current_before_kill": (
            target_before_kill is not None
            and target_before_kill["height"] == args.initial_height
        ),
        "source_advanced_during_outage": (
            source_while_target_offline is not None
            and source_while_target_offline["height"]
            == args.initial_height + args.offline_blocks
        ),
        "online_hostile_traffic_delivered": counters["online_delivered"]
        >= args.minimum_online_attacks,
        "online_attack_delivery_had_no_errors": counters["online_errors"] == 0,
        "planned_outage_was_exercised": counters["outage_errors"] > 0,
        "post_restart_hostile_traffic_delivered": (
            counters["post_restart_delivered"]
            >= args.minimum_post_restart_attacks
        ),
        "post_restart_attack_delivery_had_no_errors": (
            counters["post_restart_errors"] == 0
        ),
        "source_and_target_api_tips_match": (
            source_after is not None
            and target_after is not None
            and source_after["height"] == target_after["height"]
            and source_after["best_block_hash"]
            == target_after["best_block_hash"]
        ),
        "target_reconnected_to_peer": (
            target_status_after is not None
            and len(target_status_after.get("connections", [])) >= 1
        ),
        "source_replay_integrity": (
            source_replay["quick_check"] == "ok"
            and source_replay["foreign_key_violations"] == 0
        ),
        "target_replay_integrity": (
            target_replay["quick_check"] == "ok"
            and target_replay["foreign_key_violations"] == 0
        ),
        "replayed_state_matches_exactly": source_replay == target_replay,
        "attack_thread_joined": attack_thread_joined,
        "configured_peer_bound_is_unchanged": MAX_PEERS == 8,
        "configured_ban_bound_is_unchanged": MAX_BANNED_HOSTS == 4096,
    }
    local_baseline_met = (
        args.initial_height >= LOCAL_BASELINE_INITIAL_HEIGHT
        and args.offline_blocks >= LOCAL_BASELINE_OFFLINE_BLOCKS
        and counters["online_delivered"] >= LOCAL_BASELINE_ONLINE_ATTACKS
        and counters["post_restart_delivered"]
        >= LOCAL_BASELINE_POST_RESTART_ATTACKS
        and all(acceptance.values())
    )
    evidence = {
        "format": EVIDENCE_FORMAT,
        "status": "pass" if all(acceptance.values()) else "fail",
        "release_qualification": False,
        "started_at_utc": started_at,
        "completed_at_utc": completed_at,
        "duration_seconds": round(duration, 6),
        "repository": {
            "script_sha256": _sha256(SCRIPT_PATH),
            "sync_smoke_dependency_sha256": _sha256(
                SCRIPT_PATH.with_name("wepo_p2p_sync_smoke.py")
            ),
            "p2p_network_sha256": _sha256(CORE / "p2p_network.py"),
            "blockchain_sha256": _sha256(CORE / "blockchain.py"),
            "node_sha256": _sha256(CORE / "wepo_node.py"),
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "requested": {
            "initial_height": args.initial_height,
            "offline_blocks": args.offline_blocks,
            "attack_rate_per_second": args.attack_rate,
            "minimum_online_attacks": args.minimum_online_attacks,
            "minimum_post_restart_attacks": args.minimum_post_restart_attacks,
        },
        "actual": {
            "abrupt_exit_code": abrupt_exit_code,
            "attack_counters": counters,
            "target_before_kill": target_before_kill,
            "source_while_target_offline": source_while_target_offline,
            "source_after": source_after,
            "target_after": target_after,
            "target_status_after": target_status_after,
            "source_replay": source_replay,
            "target_replay": target_replay,
            "target_database_bytes_before_kill": target_database_bytes_before_kill,
            "target_database_bytes_after_recovery": target_database_bytes_after_recovery,
        },
        "logs": {
            "source_path": str(source.log_path),
            "source_sha256": _sha256(source.log_path),
            "target_path": str(target.log_path),
            "target_sha256": _sha256(target.log_path),
        },
        "acceptance": acceptance,
        "local_baseline": {
            "required_initial_height": LOCAL_BASELINE_INITIAL_HEIGHT,
            "required_offline_blocks": LOCAL_BASELINE_OFFLINE_BLOCKS,
            "required_online_attacks": LOCAL_BASELINE_ONLINE_ATTACKS,
            "required_post_restart_attacks": LOCAL_BASELINE_POST_RESTART_ATTACKS,
            "met": local_baseline_met,
            "meaning": "local engineering baseline only; not release qualification",
        },
        "work_directory": str(work_directory),
        "remaining_release_gates": [
            "repeat on independent hosts using the frozen candidate",
            "combine with production-volume disk pressure and monitoring",
            "repeat with real internet-path hostile traffic",
            "continuous seven-day release-candidate rehearsal",
        ],
    }
    _write_json_exclusive(output_path, evidence)
    return evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-directory", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--initial-height", type=int, default=10)
    parser.add_argument("--offline-blocks", type=int, default=5)
    parser.add_argument("--attack-rate", type=float, default=25.0)
    parser.add_argument("--minimum-online-attacks", type=int, default=100)
    parser.add_argument("--minimum-post-restart-attacks", type=int, default=50)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if (
        args.initial_height <= 0
        or args.offline_blocks <= 0
        or args.attack_rate <= 0
        or args.minimum_online_attacks <= 0
        or args.minimum_post_restart_attacks <= 0
    ):
        raise SystemExit("heights, attack rate, and attack minimums must be positive")
    evidence = _run(args)
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "output": str(Path(args.output).resolve()),
                "target_height": evidence["actual"]["target_replay"]["height"],
                "tips_match": evidence["acceptance"]["replayed_state_matches_exactly"],
                "local_baseline_met": evidence["local_baseline"]["met"],
            },
            sort_keys=True,
        )
    )
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
