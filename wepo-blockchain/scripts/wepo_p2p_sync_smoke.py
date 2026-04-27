#!/usr/bin/env python3
"""Local two-node sync smoke for headers/data catch-up and restart recovery."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

import requests


CORE_DIR = Path(__file__).resolve().parents[1] / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from address_utils import generate_wepo_address  # noqa: E402
from blockchain import BlockHeader, WepoArgon2Miner  # noqa: E402


NODE_SCRIPT = CORE_DIR / "wepo_node.py"
SOURCE_P2P_PORT = 22667
TARGET_P2P_PORT = 22668
SOURCE_API_PORT = 8127
TARGET_API_PORT = 8128
HTTP_TIMEOUT_SECONDS = 5


class SmokeFailure(RuntimeError):
    """Raised when the smoke test encounters an assertion failure."""


class ManagedNode:
    """Lifecycle wrapper around a WEPO full node subprocess."""

    def __init__(
        self,
        *,
        name: str,
        data_dir: Path,
        log_dir: Path,
        p2p_port: int,
        api_port: int,
        miner_address: str,
    ) -> None:
        self.name = name
        self.data_dir = data_dir
        self.log_dir = log_dir
        self.p2p_port = p2p_port
        self.api_port = api_port
        self.miner_address = miner_address
        self.base_url = f"http://127.0.0.1:{api_port}"
        self.log_path = log_dir / f"{name}.log"
        self.process: subprocess.Popen[bytes] | None = None
        self.log_handle = None

    def start(self) -> None:
        if self.process is not None:
            raise SmokeFailure(f"{self.name} is already running")

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_handle = open(self.log_path, "ab")

        command = [
            sys.executable,
            str(NODE_SCRIPT),
            "--data-dir",
            str(self.data_dir),
            "--p2p-port",
            str(self.p2p_port),
            "--api-port",
            str(self.api_port),
            "--miner-address",
            self.miner_address,
            "--difficulty-override",
            "1",
            "--no-background-mining",
        ]
        environment = dict(os.environ)
        environment["WEPO_STATIC_PEERS"] = f"127.0.0.1:{SOURCE_P2P_PORT},127.0.0.1:{TARGET_P2P_PORT}"
        self.process = subprocess.Popen(
            command,
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            env=environment,
        )
        wait_for_condition(
            lambda: http_ready(self.base_url),
            timeout_seconds=30,
            description=f"{self.name} API readiness",
        )

    def stop(self) -> None:
        if self.process is None:
            return

        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        finally:
            self.process = None
            if self.log_handle is not None:
                self.log_handle.close()
                self.log_handle = None

    def restart(self) -> None:
        self.stop()
        self.start()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WEPO local P2P sync smoke")
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep temporary data and log directories after the run",
    )
    parser.add_argument(
        "--work-dir",
        help="Optional existing directory to use instead of a temporary one",
    )
    return parser.parse_args()


def ensure_port_free(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise SmokeFailure(f"Port {port} is already in use")


def http_ready(base_url: str) -> bool:
    try:
        response = requests.get(f"{base_url}/api/network/status", timeout=HTTP_TIMEOUT_SECONDS)
        return response.ok
    except requests.RequestException:
        return False


def get_json(url: str, **kwargs) -> dict:
    response = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS, **kwargs)
    response.raise_for_status()
    return response.json()


def post_json(url: str, payload: dict) -> dict:
    response = requests.post(url, json=payload, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def wait_for_condition(
    predicate: Callable[[], bool],
    *,
    timeout_seconds: int,
    description: str,
    interval_seconds: float = 0.5,
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval_seconds)
    raise SmokeFailure(f"Timed out waiting for {description}")


def get_status(base_url: str) -> dict:
    return get_json(f"{base_url}/api/network/status")


def get_chain_info(base_url: str) -> dict:
    return get_json(f"{base_url}/api/blockchain/info")


def connected_to_remote_peer(base_url: str, remote_port: int) -> bool:
    status = get_status(base_url)
    return any(peer.endswith(f":{remote_port}") for peer in status.get("connections", []))


def has_any_peer_connection(base_url: str) -> bool:
    status = get_status(base_url)
    return bool(status.get("connections"))


def solve_nonce(work: dict, miner: WepoArgon2Miner) -> int:
    header = BlockHeader(
        version=1,
        prev_hash=work["prev_hash"],
        merkle_root=work["merkle_root"],
        timestamp=int(work["timestamp"]),
        bits=int(work["bits"]),
        nonce=0,
        consensus_type="pow",
    )
    target_difficulty = int(work.get("target_difficulty", work["bits"]))

    nonce = 0
    while nonce < 2**32:
        header.nonce = nonce
        block_hash = miner.calculate_pow_hash(header)
        if miner.check_difficulty(block_hash, target_difficulty):
            return nonce
        nonce += 1

    raise SmokeFailure("Failed to find a valid nonce for local smoke block")


def mine_one_block(base_url: str, miner_address: str, miner: WepoArgon2Miner) -> dict:
    work = get_json(f"{base_url}/api/mining/getwork", params={"miner_address": miner_address})
    nonce = solve_nonce(work, miner)
    submission = post_json(
        f"{base_url}/api/mining/submit",
        {
            "job_id": work["job_id"],
            "nonce": nonce,
            "miner_address": miner_address,
        },
    )
    if not submission.get("accepted"):
        raise SmokeFailure(f"Mining submission rejected: {submission}")
    return submission


def mine_to_height(base_url: str, miner_address: str, miner: WepoArgon2Miner, target_height: int) -> None:
    while get_chain_info(base_url)["height"] < target_height:
        mine_one_block(base_url, miner_address, miner)


def wait_for_height(base_url: str, target_height: int, timeout_seconds: int, label: str) -> None:
    wait_for_condition(
        lambda: get_chain_info(base_url)["height"] >= target_height,
        timeout_seconds=timeout_seconds,
        description=f"{label} height {target_height}",
    )


def main() -> int:
    args = parse_args()
    miner = WepoArgon2Miner()
    miner_address = generate_wepo_address("wepo-p2p-sync-smoke", address_type="regular")

    workspace = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="wepo-p2p-sync-"))
    log_dir = workspace / "logs"
    source_data_dir = workspace / "source"
    target_data_dir = workspace / "target"

    source_node = ManagedNode(
        name="source",
        data_dir=source_data_dir,
        log_dir=log_dir,
        p2p_port=SOURCE_P2P_PORT,
        api_port=SOURCE_API_PORT,
        miner_address=miner_address,
    )
    target_node = ManagedNode(
        name="target",
        data_dir=target_data_dir,
        log_dir=log_dir,
        p2p_port=TARGET_P2P_PORT,
        api_port=TARGET_API_PORT,
        miner_address=miner_address,
    )

    for port in (SOURCE_P2P_PORT, TARGET_P2P_PORT, SOURCE_API_PORT, TARGET_API_PORT):
        ensure_port_free(port)

    try:
        target_node.start()
        source_node.start()

        wait_for_condition(
            lambda: connected_to_remote_peer(source_node.base_url, TARGET_P2P_PORT),
            timeout_seconds=20,
            description="source peer connection to target",
        )
        wait_for_condition(
            lambda: has_any_peer_connection(target_node.base_url),
            timeout_seconds=20,
            description="target peer connection to source",
        )

        mine_to_height(source_node.base_url, miner_address, miner, 2)
        wait_for_height(target_node.base_url, 2, 20, "initial target sync")

        target_height_before_restart = get_chain_info(target_node.base_url)["height"]
        target_node.stop()

        mine_to_height(source_node.base_url, miner_address, miner, 5)
        source_info_before_restart = get_chain_info(source_node.base_url)

        target_node.start()
        wait_for_condition(
            lambda: has_any_peer_connection(target_node.base_url),
            timeout_seconds=20,
            description="target reconnect to source",
        )
        wait_for_height(target_node.base_url, 5, 30, "post-restart target sync")

        source_info = get_chain_info(source_node.base_url)
        target_info = get_chain_info(target_node.base_url)

        if source_info["best_block_hash"] != target_info["best_block_hash"]:
            raise SmokeFailure("Target tip hash does not match source tip after catch-up")

        result = {
            "workspace": str(workspace),
            "source_height_before_restart": source_info_before_restart["height"],
            "target_height_before_restart": target_height_before_restart,
            "source_height_after_restart": source_info["height"],
            "target_height_after_restart": target_info["height"],
            "tips_match": source_info["best_block_hash"] == target_info["best_block_hash"],
            "source_tip": source_info["best_block_hash"],
            "target_tip": target_info["best_block_hash"],
        }
        print(json.dumps(result, indent=2))
        return 0
    finally:
        source_node.stop()
        target_node.stop()
        if not args.keep_artifacts and not args.work_dir:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
