#!/usr/bin/env python3
"""Sustained real-socket hostile-traffic and disk-growth soak for WEPO P2P."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import struct
import sys
import threading
import time
import tracemalloc
from datetime import datetime, timezone
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
ROOT = SCRIPT_PATH.parents[2]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from blockchain import WepoBlockchain  # noqa: E402
from p2p_network import (  # noqa: E402
    HANDSHAKE_TIMEOUT_SECONDS,
    MAX_BANNED_HOSTS,
    MAX_MESSAGE_SIZE,
    MAX_PEERS,
    WepoP2PNode,
)


EVIDENCE_FORMAT = "wepo-p2p-hostile-soak-v1"
LOCAL_BASELINE_SECONDS = 300
LOCAL_BASELINE_ATTACKS = 6000


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _double_sha256(payload: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()


def _reserve_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


def _source_ip(index: int) -> str:
    value = index + 100
    second = 1 + ((value // (254 * 254)) % 254)
    third = 1 + ((value // 254) % 254)
    fourth = 1 + (value % 254)
    return f"127.{second}.{third}.{fourth}"


def _directory_bytes(path: Path) -> int:
    return sum(
        entry.stat().st_size
        for entry in path.rglob("*")
        if entry.is_file()
    )


def _windows_process_metrics() -> tuple[int | None, int | None]:
    if os.name != "nt":
        return None, None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetProcessHandleCount.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    process = kernel32.GetCurrentProcess()
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    rss = None
    if psapi.GetProcessMemoryInfo(
        process, ctypes.byref(counters), counters.cb
    ):
        rss = int(counters.WorkingSetSize)
    handle_count = ctypes.c_ulong()
    handles = None
    if kernel32.GetProcessHandleCount(process, ctypes.byref(handle_count)):
        handles = int(handle_count.value)
    return rss, handles


def _process_metrics() -> dict[str, Any]:
    rss, handles = _windows_process_metrics()
    if rss is None:
        try:
            import resource

            maximum = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            rss = maximum if platform.system() == "Darwin" else maximum * 1024
        except (ImportError, OSError):
            rss = None
    if handles is None:
        fd_directory = Path("/proc/self/fd")
        if fd_directory.is_dir():
            try:
                handles = len(list(fd_directory.iterdir()))
            except OSError:
                handles = None
    heap_current, heap_peak = tracemalloc.get_traced_memory()
    return {
        "rss_bytes": rss,
        "handles_or_fds": handles,
        "python_heap_current_bytes": heap_current,
        "python_heap_peak_bytes": heap_peak,
        "threads": threading.active_count(),
        "process_cpu_seconds": time.process_time(),
    }


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite soak evidence: {path}")
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


def _wait_until(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def _wire_chain(node: WepoP2PNode, chain: WepoBlockchain) -> None:
    def accept_block(payload: dict) -> bool:
        try:
            block = chain.deserialize_block(payload)
        except Exception:
            return False
        return chain.add_block_with_priority(block)

    node.on_new_block = accept_block
    node.on_new_transaction = lambda _payload: False
    node.get_block_callback = chain.get_block_payload
    node.get_headers_callback = chain.get_headers_after_locator
    node.get_transaction_callback = chain.get_transaction_payload
    node.has_transaction_callback = chain.has_transaction
    node.get_block_hashes_callback = chain.get_block_hashes_after_locator
    node.get_height_callback = chain.get_block_height
    node.get_locator_callback = chain.get_block_locator_hashes


def _peer_snapshot(node: WepoP2PNode) -> list:
    for _ in range(3):
        try:
            return list(node.peers.values())
        except RuntimeError:
            time.sleep(0)
    return []


def _attack_payload(node: WepoP2PNode, category: str) -> bytes:
    if category == "invalid_magic":
        return struct.pack(
            "<4s12sI4s", b"NOPE", b"ping".ljust(12, b"\x00"), 0, b"\x00" * 4
        )
    if category == "oversized_declaration":
        return struct.pack(
            "<4s12sI4s",
            node.network_magic,
            b"tx".ljust(12, b"\x00"),
            MAX_MESSAGE_SIZE + 1,
            b"\x00" * 4,
        )
    if category == "bad_checksum":
        payload = b"{}"
        return struct.pack(
            "<4s12sI4s",
            node.network_magic,
            b"ping".ljust(12, b"\x00"),
            len(payload),
            b"\x00" * 4,
        ) + payload
    if category == "prehandshake_ping":
        return node.create_message("ping", b'{"nonce":1}')
    if category == "malformed_version":
        return node.create_message("version", b"{}")
    if category == "partial_header":
        return node.network_magic[:1]
    return b""


def _attack_once(
    node: WepoP2PNode,
    port: int,
    source_ip: str,
    category: str,
) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.75)
        sock.bind((source_ip, 0))
        sock.connect(("127.0.0.1", port))
        payload = _attack_payload(node, category)
        if payload:
            sock.sendall(payload)
        if category not in {"churn", "partial_header"}:
            try:
                while sock.recv(4096):
                    pass
            except OSError:
                pass
        return "sent"
    except OSError:
        return "connect_or_send_error"
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _run(args: argparse.Namespace) -> dict[str, Any]:
    work_directory = Path(args.work_directory).resolve()
    work_directory.mkdir(parents=True, exist_ok=False)
    data_directory = work_directory / "node-data"
    os.environ["WEPO_STATIC_PEERS"] = "off"
    os.environ["WEPO_DNS_SEEDS"] = "off"

    server_port = _reserve_port()
    client_port = _reserve_port()
    while client_port == server_port:
        client_port = _reserve_port()

    server = None
    client = None
    chain = None
    slow_sockets: list[socket.socket] = []
    slow_hosts: list[str] = []
    attack_counts = {
        category: 0
        for category in (
            "invalid_magic",
            "oversized_declaration",
            "bad_checksum",
            "prehandshake_ping",
            "malformed_version",
            "partial_header",
            "churn",
        )
    }
    attack_results = {"sent": 0, "connect_or_send_error": 0}
    samples: list[dict[str, Any]] = []
    valid_peer_failures = 0
    slow_deadlines_observed = args.slow_clients == 0
    started_at = _utc_now()
    tracemalloc.start()
    metrics_before = _process_metrics()

    with open(os.devnull, "w", encoding="utf-8") as devnull:
        with contextlib.redirect_stdout(devnull):
            chain = WepoBlockchain(
                data_dir=str(data_directory),
                network_profile="test",
                fixed_difficulty=1,
            )
            database_bytes_before = _directory_bytes(data_directory)
            initial_height = chain.get_block_height()
            initial_tip = chain.get_latest_block().get_block_hash()

            server = WepoP2PNode(
                host="127.0.0.1", port=server_port, network_profile="test"
            )
            _wire_chain(server, chain)
            server.start_server()
            client = WepoP2PNode(
                host="127.0.0.1", port=client_port, network_profile="test"
            )
            if not client.connect_to_peer("127.0.0.1", server_port):
                raise RuntimeError("valid control peer could not connect")
            if not _wait_until(
                lambda: any(peer.is_connected() for peer in _peer_snapshot(server))
                and any(peer.is_connected() for peer in _peer_snapshot(client)),
                5.0,
            ):
                raise RuntimeError("valid control peer handshake did not complete")

            for index in range(args.slow_clients):
                source_ip = f"127.0.0.{index + 2}"
                slow = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                slow.settimeout(2.0)
                slow.bind((source_ip, 0))
                slow.connect(("127.0.0.1", server_port))
                slow_sockets.append(slow)
                slow_hosts.append(source_ip)

            categories = tuple(attack_counts)
            soak_started = time.monotonic()
            next_attack = soak_started
            next_sample = soak_started
            next_progress = soak_started + max(1, args.progress_every_seconds)
            attack_index = 0
            while True:
                now = time.monotonic()
                elapsed = now - soak_started
                if elapsed >= args.duration_seconds:
                    break
                if now >= next_attack:
                    category = categories[attack_index % len(categories)]
                    result = _attack_once(
                        server,
                        server_port,
                        _source_ip(attack_index),
                        category,
                    )
                    attack_counts[category] += 1
                    attack_results[result] += 1
                    attack_index += 1
                    next_attack += 1.0 / args.attack_rate
                    if next_attack < now - 1.0:
                        next_attack = now
                if now >= next_sample:
                    peers = _peer_snapshot(server)
                    connected = [peer for peer in peers if peer.is_connected()]
                    valid_connected = any(
                        peer.address[0] == "127.0.0.1" for peer in connected
                    )
                    if not valid_connected:
                        valid_peer_failures += 1
                    with server._peer_policy_lock:
                        banned_count = len(server.banned_until)
                        slow_banned = sum(
                            1 for host in slow_hosts if host in server.banned_until
                        )
                    maximum_buffer = max(
                        (len(peer.receive_buffer) for peer in peers), default=0
                    )
                    sample = {
                        "elapsed_seconds": round(elapsed, 6),
                        "peer_entries": len(peers),
                        "connected_peers": len(connected),
                        "valid_control_connected": valid_connected,
                        "banned_hosts": banned_count,
                        "slow_hosts_banned": slow_banned,
                        "maximum_receive_buffer_bytes": maximum_buffer,
                        "database_bytes": _directory_bytes(data_directory),
                        **_process_metrics(),
                    }
                    samples.append(sample)
                    if (
                        args.slow_clients > 0
                        and elapsed >= HANDSHAKE_TIMEOUT_SECONDS + 2
                        and slow_banned == args.slow_clients
                        and len(peers) <= 1
                    ):
                        slow_deadlines_observed = True
                    next_sample = now + args.sample_interval_seconds
                if now >= next_progress:
                    print(
                        f"[p2p-hostile-soak] elapsed={elapsed:.1f}s "
                        f"attacks={attack_index} bans={len(server.banned_until)}",
                        file=sys.__stdout__,
                        flush=True,
                    )
                    next_progress = now + args.progress_every_seconds
                time.sleep(0.001)

            for slow in slow_sockets:
                try:
                    slow.close()
                except OSError:
                    pass
            slow_sockets.clear()
            _wait_until(
                lambda: len(_peer_snapshot(server)) <= 1,
                5.0,
            )
            peers_before_shutdown = _peer_snapshot(server)
            with server._peer_policy_lock:
                final_banned_hosts = len(server.banned_until)
            database_bytes_after_traffic = _directory_bytes(data_directory)
            quick_check = chain.conn.execute("PRAGMA quick_check").fetchone()[0]
            foreign_key_violations = len(
                chain.conn.execute("PRAGMA foreign_key_check").fetchall()
            )
            ending_height = chain.get_block_height()
            ending_tip = chain.get_latest_block().get_block_hash()

            client.stop_server()
            server.stop_server()
            service_threads_joined = _wait_until(
                lambda: not any(
                    thread.name.startswith("wepo-p2p-")
                    for thread in threading.enumerate()
                ),
                5.0,
            )
            peers_after_shutdown = len(server.peers)
            service_threads_after_shutdown = len(server._service_threads)
            chain.conn.close()

    metrics_after = _process_metrics()
    heap_current, heap_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    duration_actual = time.monotonic() - soak_started
    rss_observations = [
        metrics_before["rss_bytes"],
        metrics_after["rss_bytes"],
        *(sample["rss_bytes"] for sample in samples),
    ]
    peak_rss = max((value for value in rss_observations if value is not None), default=None)
    initial_rss = metrics_before["rss_bytes"]
    rss_growth = (
        peak_rss - initial_rss
        if peak_rss is not None and initial_rss is not None
        else None
    )
    initial_handles = metrics_before["handles_or_fds"]
    final_handles = metrics_after["handles_or_fds"]
    handle_growth = (
        final_handles - initial_handles
        if final_handles is not None and initial_handles is not None
        else None
    )
    thread_growth = (
        metrics_after["threads"] - metrics_before["threads"]
    )
    peak_peer_entries = max(
        (sample["peer_entries"] for sample in samples), default=0
    )
    peak_banned_hosts = max(
        (sample["banned_hosts"] for sample in samples), default=0
    )
    maximum_receive_buffer = max(
        (sample["maximum_receive_buffer_bytes"] for sample in samples),
        default=0,
    )
    total_attacks = sum(attack_counts.values())
    database_growth = database_bytes_after_traffic - database_bytes_before
    acceptance = {
        "all_attacks_delivered": (
            attack_results["connect_or_send_error"] == 0
        ),
        "valid_control_peer_survived": valid_peer_failures == 0,
        "slow_handshake_deadlines_observed": slow_deadlines_observed,
        "peer_registry_bounded": peak_peer_entries <= MAX_PEERS,
        "ban_registry_bounded": peak_banned_hosts <= MAX_BANNED_HOSTS,
        "receive_buffers_bounded": maximum_receive_buffer <= MAX_MESSAGE_SIZE + 24,
        "chain_unchanged": ending_height == initial_height and ending_tip == initial_tip,
        "database_integrity": quick_check == "ok" and foreign_key_violations == 0,
        "hostile_traffic_did_not_grow_database": database_growth == 0,
        "rss_growth_bounded": (
            rss_growth is None
            or rss_growth <= args.max_rss_growth_mib * 1024 * 1024
        ),
        "python_heap_growth_bounded": heap_peak <= args.max_heap_mib * 1024 * 1024,
        "handle_growth_bounded": (
            handle_growth is None or handle_growth <= args.max_handle_growth
        ),
        "thread_growth_bounded": thread_growth <= args.max_thread_growth,
        "service_threads_joined": (
            service_threads_joined
            and service_threads_after_shutdown == 0
        ),
        "peer_registry_empty_after_shutdown": peers_after_shutdown == 0,
        "malformed_hosts_were_banned": final_banned_hosts > 0,
    }
    local_baseline_met = (
        duration_actual >= LOCAL_BASELINE_SECONDS
        and total_attacks >= LOCAL_BASELINE_ATTACKS
        and peak_banned_hosts == MAX_BANNED_HOSTS
        and all(acceptance.values())
    )
    evidence = {
        "format": EVIDENCE_FORMAT,
        "status": "pass" if all(acceptance.values()) else "fail",
        "release_qualification": False,
        "started_at_utc": started_at,
        "completed_at_utc": _utc_now(),
        "repository": {
            "script_sha256": _sha256(SCRIPT_PATH),
            "p2p_network_sha256": _sha256(CORE / "p2p_network.py"),
            "blockchain_sha256": _sha256(CORE / "blockchain.py"),
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "requested": {
            "duration_seconds": args.duration_seconds,
            "attack_rate_per_second": args.attack_rate,
            "slow_clients": args.slow_clients,
            "sample_interval_seconds": args.sample_interval_seconds,
        },
        "actual": {
            "duration_seconds": round(duration_actual, 6),
            "attack_counts": attack_counts,
            "attack_results": attack_results,
            "total_attacks": total_attacks,
            "peak_peer_entries": peak_peer_entries,
            "peak_banned_hosts": peak_banned_hosts,
            "final_banned_hosts": final_banned_hosts,
            "maximum_receive_buffer_bytes": maximum_receive_buffer,
            "valid_peer_failure_samples": valid_peer_failures,
            "slow_deadlines_observed": slow_deadlines_observed,
            "database_bytes_before": database_bytes_before,
            "database_bytes_after_traffic": database_bytes_after_traffic,
            "database_growth_bytes": database_growth,
            "quick_check": quick_check,
            "foreign_key_violations": foreign_key_violations,
            "initial_height": initial_height,
            "ending_height": ending_height,
            "initial_tip": initial_tip,
            "ending_tip": ending_tip,
            "peers_before_shutdown": len(peers_before_shutdown),
            "peers_after_shutdown": peers_after_shutdown,
        },
        "resources": {
            "before": metrics_before,
            "after": metrics_after,
            "peak_rss_bytes": peak_rss,
            "rss_growth_bytes": rss_growth,
            "python_heap_current_bytes": heap_current,
            "python_heap_peak_bytes": heap_peak,
            "handle_or_fd_growth": handle_growth,
            "thread_growth": thread_growth,
        },
        "acceptance": acceptance,
        "local_baseline": {
            "required_duration_seconds": LOCAL_BASELINE_SECONDS,
            "required_total_attacks": LOCAL_BASELINE_ATTACKS,
            "requires_ban_registry_cap_exercised": True,
            "met": local_baseline_met,
            "meaning": "local engineering baseline only; not release qualification",
        },
        "samples": samples,
        "work_directory": str(work_directory),
        "remaining_release_gates": [
            "repeat from the frozen clean candidate on release hardware",
            "multi-host internet-path traffic and independent monitoring",
            "trusted valid transaction/block propagation during hostile load",
            "seven-day release-candidate network rehearsal",
            "approved CPU, memory, handle, and disk alert thresholds",
        ],
    }
    _write_json_exclusive(Path(args.output), evidence)
    return evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-directory", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--duration-seconds", type=float, default=LOCAL_BASELINE_SECONDS)
    parser.add_argument("--attack-rate", type=float, default=25.0)
    parser.add_argument("--slow-clients", type=int, default=MAX_PEERS - 1)
    parser.add_argument("--sample-interval-seconds", type=float, default=1.0)
    parser.add_argument("--progress-every-seconds", type=float, default=10.0)
    parser.add_argument("--max-rss-growth-mib", type=int, default=128)
    parser.add_argument("--max-heap-mib", type=int, default=64)
    parser.add_argument("--max-handle-growth", type=int, default=128)
    parser.add_argument("--max-thread-growth", type=int, default=2)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.duration_seconds <= 0 or args.attack_rate <= 0:
        raise SystemExit("duration and attack rate must be positive")
    if args.slow_clients < 0 or args.slow_clients >= MAX_PEERS:
        raise SystemExit(f"slow clients must be between 0 and {MAX_PEERS - 1}")
    if args.sample_interval_seconds <= 0 or args.progress_every_seconds <= 0:
        raise SystemExit("sample and progress intervals must be positive")
    evidence = _run(args)
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "output": str(Path(args.output).resolve()),
                "total_attacks": evidence["actual"]["total_attacks"],
                "peak_banned_hosts": evidence["actual"]["peak_banned_hosts"],
                "local_baseline_met": evidence["local_baseline"]["met"],
            },
            sort_keys=True,
        )
    )
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
