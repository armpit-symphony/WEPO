#!/usr/bin/env python3
"""Prove trusted WEPO transaction/block propagation during hostile P2P load."""

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
import tracemalloc
from datetime import datetime, timezone
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
ROOT = SCRIPT_PATH.parents[2]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from address_utils import generate_wepo_address  # noqa: E402
from blockchain import Transaction, WepoBlockchain  # noqa: E402
from dilithium import generate_dilithium_keypair, require_real_mldsa  # noqa: E402
from p2p_network import MAX_BANNED_HOSTS, MAX_PEERS, WepoP2PNode  # noqa: E402
from wepo_p2p_hostile_soak import (  # noqa: E402
    _directory_bytes,
    _process_metrics,
    _sha256,
    _write_json_exclusive,
)


EVIDENCE_FORMAT = "wepo-p2p-trusted-under-load-v1"
LOCAL_BASELINE_SECONDS = 120
LOCAL_BASELINE_PROPAGATIONS = 40
LOCAL_BASELINE_ATTACKS = 2400


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reserve_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


def _wait_until(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def _source_ip(index: int) -> str:
    value = index + 100
    return (
        f"127.{1 + ((value // (254 * 254)) % 254)}."
        f"{1 + ((value // 254) % 254)}.{1 + (value % 254)}"
    )


def _peer_connected(node: WepoP2PNode, host: str = "127.0.0.1") -> bool:
    return any(
        peer.address[0] == host and peer.is_connected()
        for peer in list(node.peers.values())
    )


def _wire(node: WepoP2PNode, chain: WepoBlockchain) -> None:
    def accept_block(payload: dict) -> bool:
        try:
            block = chain.deserialize_block(payload)
        except Exception:
            return False
        return chain.add_block_with_priority(block)

    def accept_transaction(payload: dict) -> bool:
        if not isinstance(payload, dict) or set(payload) != {"txid", "tx_data"}:
            return False
        try:
            transaction = Transaction.from_dict(payload["tx_data"])
        except Exception:
            return False
        if transaction.calculate_txid() != payload["txid"]:
            return False
        return chain.add_transaction_to_mempool(transaction)

    node.on_new_block = accept_block
    node.on_new_transaction = accept_transaction
    node.get_block_callback = chain.get_block_payload
    node.get_headers_callback = chain.get_headers_after_locator
    node.get_transaction_callback = chain.get_transaction_payload
    node.has_transaction_callback = chain.has_transaction
    node.get_block_hashes_callback = chain.get_block_hashes_after_locator
    node.get_height_callback = chain.get_block_height
    node.get_locator_callback = chain.get_block_locator_hashes


def _attack_worker(
    node: WepoP2PNode,
    port: int,
    stop: threading.Event,
    rate: float,
    counters: dict[str, int],
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
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(0.5)
            sock.bind((_source_ip(index), 0))
            sock.connect(("127.0.0.1", port))
            sock.sendall(header)
            counters["delivered"] += 1
            counters["peak_peer_entries"] = max(
                counters["peak_peer_entries"], len(node.peers)
            )
            try:
                while sock.recv(4096):
                    pass
            except OSError:
                pass
        except OSError:
            counters["connect_or_send_error"] += 1
        finally:
            sock.close()
        counters["scheduled"] += 1
        index += 1
        next_attack += 1.0 / rate
        if next_attack < time.monotonic() - 1.0:
            next_attack = time.monotonic()


def _run(args: argparse.Namespace) -> dict[str, Any]:
    require_real_mldsa()
    work_directory = Path(args.work_directory).resolve()
    work_directory.mkdir(parents=True, exist_ok=False)
    source_directory = work_directory / "source"
    target_directory = work_directory / "target"
    os.environ["WEPO_STATIC_PEERS"] = "off"
    os.environ["WEPO_DNS_SEEDS"] = "off"

    metrics_before = None
    metrics_after = None
    source_chain = None
    target_chain = None
    source = None
    target = None
    stop = threading.Event()
    attack_thread = None
    counters = {
        "scheduled": 0,
        "delivered": 0,
        "connect_or_send_error": 0,
        "peak_peer_entries": 0,
    }
    propagations: list[dict[str, Any]] = []
    valid_peer_failures = 0
    started_at = _utc_now()
    tracemalloc.start()
    metrics_before = _process_metrics()
    soak_started = time.monotonic()

    with open(os.devnull, "w", encoding="utf-8") as devnull:
        with contextlib.redirect_stdout(devnull):
            source_chain = WepoBlockchain(
                data_dir=str(source_directory),
                network_profile="test",
                fixed_difficulty=1,
            )
            target_chain = WepoBlockchain(
                data_dir=str(target_directory),
                network_profile="test",
                fixed_difficulty=1,
            )
            source_chain._next_block_timestamp = (
                lambda: source_chain.get_latest_block().header.timestamp + 1
            )

            keypair = generate_dilithium_keypair()
            actor = generate_wepo_address(
                keypair.public_key, address_type="quantum"
            )
            sink = generate_wepo_address(
                b"WEPO_TRUSTED_UNDER_LOAD_SINK_V1", address_type="quantum"
            )
            miner = generate_wepo_address(
                b"WEPO_TRUSTED_UNDER_LOAD_MINER_V1", address_type="quantum"
            )
            funding = source_chain.mine_block(actor)
            if funding is None:
                raise RuntimeError("failed to mine actor funding block")

            source_port = _reserve_port()
            target_port = _reserve_port()
            while target_port == source_port:
                target_port = _reserve_port()
            source = WepoP2PNode(
                "127.0.0.1", source_port, network_profile="test"
            )
            target = WepoP2PNode(
                "127.0.0.1", target_port, network_profile="test"
            )
            _wire(source, source_chain)
            _wire(target, target_chain)
            source.start_server()
            target.start_server()
            if not source.connect_to_peer("127.0.0.1", target_port):
                raise RuntimeError("source could not connect to attacked target")
            if not _wait_until(
                lambda: (
                    target_chain.get_latest_block().get_block_hash()
                    == funding.get_block_hash()
                ),
                args.propagation_timeout_seconds,
            ):
                raise RuntimeError("initial funding block did not synchronize")

            attack_thread = threading.Thread(
                target=_attack_worker,
                args=(target, target_port, stop, args.attack_rate, counters),
                daemon=True,
                name="wepo-hostile-load-generator",
            )
            attack_thread.start()
            next_cycle = time.monotonic()
            next_progress = next_cycle + max(1.0, args.progress_every_seconds)
            while time.monotonic() - soak_started < args.duration_seconds:
                now = time.monotonic()
                if not _peer_connected(source) or not _peer_connected(target):
                    valid_peer_failures += 1
                if now < next_cycle:
                    time.sleep(min(next_cycle - now, 0.01))
                    continue

                transaction = source_chain.create_transaction(
                    from_address=actor,
                    to_address=sink,
                    amount=1,
                    fee=0,
                )
                if transaction is None or not transaction.sign_all_inputs(
                    keypair.private_key, keypair.public_key
                ):
                    raise RuntimeError("failed to build trusted signed transfer")
                if not source_chain.add_transaction_to_mempool(transaction):
                    raise RuntimeError("source rejected trusted signed transfer")
                envelope = {
                    "txid": transaction.calculate_txid(),
                    "tx_data": transaction.to_dict(),
                }
                transaction_started = time.monotonic()
                source.broadcast_to_peers(
                    source.create_transaction_message(envelope)
                )
                transaction_arrived = _wait_until(
                    lambda: target_chain.has_transaction(envelope["txid"]),
                    args.propagation_timeout_seconds,
                )
                transaction_latency = time.monotonic() - transaction_started
                if not transaction_arrived:
                    raise RuntimeError("trusted transaction propagation timed out")

                extension = source_chain.mine_block(miner)
                if extension is None:
                    raise RuntimeError("failed to mine trusted confirmation block")
                block_started = time.monotonic()
                source.broadcast_block({"hash": extension.get_block_hash()})
                block_arrived = _wait_until(
                    lambda: (
                        target_chain.get_latest_block().get_block_hash()
                        == extension.get_block_hash()
                    ),
                    args.propagation_timeout_seconds,
                )
                block_latency = time.monotonic() - block_started
                if not block_arrived:
                    raise RuntimeError("trusted block propagation timed out")
                propagations.append(
                    {
                        "height": extension.height,
                        "txid": envelope["txid"],
                        "block_hash": extension.get_block_hash(),
                        "transaction_latency_seconds": round(
                            transaction_latency, 6
                        ),
                        "block_latency_seconds": round(block_latency, 6),
                        "hostile_delivered": counters["delivered"],
                    }
                )
                next_cycle += args.propagation_interval_seconds
                if next_cycle < time.monotonic():
                    next_cycle = time.monotonic()
                if time.monotonic() >= next_progress:
                    print(
                        f"[trusted-under-load] elapsed="
                        f"{time.monotonic() - soak_started:.1f}s "
                        f"propagations={len(propagations)} "
                        f"attacks={counters['delivered']}",
                        file=sys.__stdout__,
                        flush=True,
                    )
                    next_progress = time.monotonic() + args.progress_every_seconds

            stop.set()
            attack_thread.join(timeout=3.0)
            attack_thread_joined = not attack_thread.is_alive()
            source_tip = source_chain.get_latest_block().get_block_hash()
            target_tip = target_chain.get_latest_block().get_block_hash()
            source_height = source_chain.get_block_height()
            target_height = target_chain.get_block_height()
            source_supply = source_chain.get_issued_supply()
            target_supply = target_chain.get_issued_supply()
            target_quick_check = target_chain.conn.execute(
                "PRAGMA quick_check"
            ).fetchone()[0]
            target_foreign_key_violations = len(
                target_chain.conn.execute("PRAGMA foreign_key_check").fetchall()
            )
            with target._peer_policy_lock:
                target_banned_hosts = len(target.banned_until)
            peak_peer_entries = max(counters["peak_peer_entries"], len(target.peers))

            source.stop_server()
            target.stop_server()
            services_joined = not source._service_threads and not target._service_threads
            peers_empty = not source.peers and not target.peers
            source_chain.conn.close()
            target_chain.conn.close()

    metrics_after = _process_metrics()
    heap_current, heap_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    duration_actual = time.monotonic() - soak_started
    maximum_transaction_latency = max(
        (item["transaction_latency_seconds"] for item in propagations),
        default=None,
    )
    maximum_block_latency = max(
        (item["block_latency_seconds"] for item in propagations), default=None
    )
    thread_growth = metrics_after["threads"] - metrics_before["threads"]
    handle_growth = None
    if (
        metrics_after["handles_or_fds"] is not None
        and metrics_before["handles_or_fds"] is not None
    ):
        handle_growth = (
            metrics_after["handles_or_fds"]
            - metrics_before["handles_or_fds"]
        )
    rss_growth = None
    if (
        metrics_after["rss_bytes"] is not None
        and metrics_before["rss_bytes"] is not None
    ):
        rss_growth = metrics_after["rss_bytes"] - metrics_before["rss_bytes"]

    acceptance = {
        "hostile_traffic_delivered": counters["delivered"] > 0,
        "no_connect_or_send_failures": counters["connect_or_send_error"] == 0,
        "valid_control_peer_survived": valid_peer_failures == 0,
        "trusted_propagations_completed": len(propagations) > 0,
        "transaction_latency_bounded": (
            maximum_transaction_latency is not None
            and maximum_transaction_latency <= args.propagation_timeout_seconds
        ),
        "block_latency_bounded": (
            maximum_block_latency is not None
            and maximum_block_latency <= args.propagation_timeout_seconds
        ),
        "chains_converged": (
            source_height == target_height
            and source_tip == target_tip
            and source_supply == target_supply
        ),
        "target_mempool_drained": len(target_chain.mempool) == 0,
        "target_database_integrity": (
            target_quick_check == "ok" and target_foreign_key_violations == 0
        ),
        "peer_registry_bounded": peak_peer_entries <= MAX_PEERS,
        "ban_registry_bounded": target_banned_hosts <= MAX_BANNED_HOSTS,
        "malformed_hosts_were_banned": target_banned_hosts > 0,
        "attack_thread_joined": attack_thread_joined,
        "service_threads_joined": services_joined,
        "peer_registries_empty_after_shutdown": peers_empty,
        "thread_growth_bounded": thread_growth <= args.max_thread_growth,
        "handle_growth_bounded": (
            handle_growth is None or handle_growth <= args.max_handle_growth
        ),
        "rss_growth_bounded": (
            rss_growth is None
            or rss_growth <= args.max_rss_growth_mib * 1024 * 1024
        ),
        "python_heap_bounded": heap_peak <= args.max_heap_mib * 1024 * 1024,
    }
    local_baseline_met = (
        duration_actual >= LOCAL_BASELINE_SECONDS
        and len(propagations) >= LOCAL_BASELINE_PROPAGATIONS
        and counters["delivered"] >= LOCAL_BASELINE_ATTACKS
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
            "hostile_soak_dependency_sha256": _sha256(
                SCRIPT_PATH.with_name("wepo_p2p_hostile_soak.py")
            ),
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
            "propagation_interval_seconds": args.propagation_interval_seconds,
            "propagation_timeout_seconds": args.propagation_timeout_seconds,
        },
        "actual": {
            "duration_seconds": round(duration_actual, 6),
            "hostile": counters,
            "propagation_count": len(propagations),
            "maximum_transaction_latency_seconds": maximum_transaction_latency,
            "maximum_block_latency_seconds": maximum_block_latency,
            "source_height": source_height,
            "target_height": target_height,
            "source_tip": source_tip,
            "target_tip": target_tip,
            "source_supply": source_supply,
            "target_supply": target_supply,
            "target_banned_hosts": target_banned_hosts,
            "target_database_bytes": _directory_bytes(target_directory),
            "target_quick_check": target_quick_check,
            "target_foreign_key_violations": target_foreign_key_violations,
        },
        "resources": {
            "before": metrics_before,
            "after": metrics_after,
            "rss_growth_bytes": rss_growth,
            "python_heap_current_bytes": heap_current,
            "python_heap_peak_bytes": heap_peak,
            "handle_or_fd_growth": handle_growth,
            "thread_growth": thread_growth,
        },
        "acceptance": acceptance,
        "local_baseline": {
            "required_duration_seconds": LOCAL_BASELINE_SECONDS,
            "required_propagations": LOCAL_BASELINE_PROPAGATIONS,
            "required_delivered_attacks": LOCAL_BASELINE_ATTACKS,
            "met": local_baseline_met,
            "meaning": "local engineering baseline only; not release qualification",
        },
        "propagations": propagations,
        "work_directory": str(work_directory),
        "remaining_release_gates": [
            "repeat from the frozen clean candidate on independent hosts",
            "public internet-path hostile traffic and independent monitoring",
            "release-hardware resource thresholds and alerting",
            "continuous seven-day release-candidate network rehearsal",
        ],
    }
    _write_json_exclusive(Path(args.output), evidence)
    return evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-directory", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--duration-seconds", type=float, default=120.0)
    parser.add_argument("--attack-rate", type=float, default=25.0)
    parser.add_argument("--propagation-interval-seconds", type=float, default=2.0)
    parser.add_argument("--propagation-timeout-seconds", type=float, default=5.0)
    parser.add_argument("--progress-every-seconds", type=float, default=10.0)
    parser.add_argument("--max-rss-growth-mib", type=int, default=128)
    parser.add_argument("--max-heap-mib", type=int, default=64)
    parser.add_argument("--max-handle-growth", type=int, default=128)
    parser.add_argument("--max-thread-growth", type=int, default=2)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if (
        args.duration_seconds <= 0
        or args.attack_rate <= 0
        or args.propagation_interval_seconds <= 0
        or args.propagation_timeout_seconds <= 0
        or args.progress_every_seconds <= 0
    ):
        raise SystemExit("durations, intervals, timeouts, and attack rate must be positive")
    evidence = _run(args)
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "output": str(Path(args.output).resolve()),
                "propagations": evidence["actual"]["propagation_count"],
                "hostile_delivered": evidence["actual"]["hostile"]["delivered"],
                "local_baseline_met": evidence["local_baseline"]["met"],
            },
            sort_keys=True,
        )
    )
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
