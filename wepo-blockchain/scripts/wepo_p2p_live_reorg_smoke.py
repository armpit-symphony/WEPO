#!/usr/bin/env python3
"""Three-node live fork/reorg smoke for WEPO P2P consensus behavior."""

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
NODE_A_P2P_PORT = 22671
NODE_B_P2P_PORT = 22672
NODE_C_P2P_PORT = 22673
NODE_A_API_PORT = 8131
NODE_B_API_PORT = 8132
NODE_C_API_PORT = 8133
HTTP_TIMEOUT_SECONDS = 5


class SmokeFailure(RuntimeError):
    """Raised when the live reorg smoke hits a failed assertion."""


class ManagedNode:
    """Lifecycle wrapper for a WEPO node subprocess with configurable static peers."""

    def __init__(
        self,
        *,
        name: str,
        data_dir: Path,
        log_dir: Path,
        p2p_port: int,
        api_port: int,
        miner_address: str,
        static_peers: str,
    ) -> None:
        self.name = name
        self.data_dir = data_dir
        self.log_dir = log_dir
        self.p2p_port = p2p_port
        self.api_port = api_port
        self.miner_address = miner_address
        self.static_peers = static_peers
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
        environment["WEPO_STATIC_PEERS"] = self.static_peers

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

    def restart(self, *, static_peers: str | None = None) -> None:
        if static_peers is not None:
            self.static_peers = static_peers
        self.stop()
        self.start()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WEPO live three-node reorg smoke")
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep the temporary chain data and logs after completion",
    )
    parser.add_argument(
        "--work-dir",
        help="Optional working directory for logs and chain state",
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


def get_chain_info(base_url: str) -> dict:
    return get_json(f"{base_url}/api/blockchain/info")


def get_status(base_url: str) -> dict:
    return get_json(f"{base_url}/api/network/status")


def has_any_peer(base_url: str) -> bool:
    return bool(get_status(base_url).get("connections"))


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
    result = post_json(
        f"{base_url}/api/mining/submit",
        {
            "job_id": work["job_id"],
            "nonce": nonce,
            "miner_address": miner_address,
        },
    )
    if not result.get("accepted"):
        raise SmokeFailure(f"Mining submission rejected: {result}")
    return result


def mine_to_height(base_url: str, miner_address: str, miner: WepoArgon2Miner, target_height: int) -> None:
    while get_chain_info(base_url)["height"] < target_height:
        mine_one_block(base_url, miner_address, miner)


def wait_for_height(base_url: str, target_height: int, timeout_seconds: int, label: str) -> None:
    wait_for_condition(
        lambda: get_chain_info(base_url)["height"] >= target_height,
        timeout_seconds=timeout_seconds,
        description=f"{label} height {target_height}",
    )


def wait_for_tip(base_url: str, tip_hash: str, timeout_seconds: int, label: str) -> None:
    wait_for_condition(
        lambda: get_chain_info(base_url)["best_block_hash"] == tip_hash,
        timeout_seconds=timeout_seconds,
        description=f"{label} tip {tip_hash}",
    )


def main() -> int:
    args = parse_args()
    miner = WepoArgon2Miner()

    miner_a = generate_wepo_address("wepo-live-reorg-node-a", address_type="regular")
    miner_b = generate_wepo_address("wepo-live-reorg-node-b", address_type="regular")
    miner_c = generate_wepo_address("wepo-live-reorg-node-c", address_type="regular")

    workspace = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="wepo-live-reorg-"))
    log_dir = workspace / "logs"

    node_a = ManagedNode(
        name="node_a",
        data_dir=workspace / "node_a",
        log_dir=log_dir,
        p2p_port=NODE_A_P2P_PORT,
        api_port=NODE_A_API_PORT,
        miner_address=miner_a,
        static_peers="none",
    )
    node_b = ManagedNode(
        name="node_b",
        data_dir=workspace / "node_b",
        log_dir=log_dir,
        p2p_port=NODE_B_P2P_PORT,
        api_port=NODE_B_API_PORT,
        miner_address=miner_b,
        static_peers=f"127.0.0.1:{NODE_C_P2P_PORT}",
    )
    node_c = ManagedNode(
        name="node_c",
        data_dir=workspace / "node_c",
        log_dir=log_dir,
        p2p_port=NODE_C_P2P_PORT,
        api_port=NODE_C_API_PORT,
        miner_address=miner_c,
        static_peers="none",
    )

    for port in (
        NODE_A_P2P_PORT,
        NODE_B_P2P_PORT,
        NODE_C_P2P_PORT,
        NODE_A_API_PORT,
        NODE_B_API_PORT,
        NODE_C_API_PORT,
    ):
        ensure_port_free(port)

    try:
        node_a.start()
        node_c.start()
        node_b.start()

        wait_for_condition(
            lambda: has_any_peer(node_b.base_url) and has_any_peer(node_c.base_url),
            timeout_seconds=20,
            description="initial B/C peer mesh",
        )

        mine_to_height(node_a.base_url, miner_a, miner, 2)
        branch_a_info = get_chain_info(node_a.base_url)

        mine_to_height(node_b.base_url, miner_b, miner, 2)
        wait_for_height(node_c.base_url, 2, 20, "node_c sync from node_b")
        branch_b_info = get_chain_info(node_b.base_url)
        branch_c_info = get_chain_info(node_c.base_url)

        if branch_a_info["best_block_hash"] == branch_b_info["best_block_hash"]:
            raise SmokeFailure("Partitioned fork race did not produce distinct height-2 tips")
        if branch_b_info["best_block_hash"] != branch_c_info["best_block_hash"]:
            raise SmokeFailure("Node C did not follow node B on the shared partition branch")

        branch_a_tip_height2 = branch_a_info["best_block_hash"]
        branch_bc_tip_height2 = branch_b_info["best_block_hash"]

        node_a.restart(
            static_peers=f"127.0.0.1:{NODE_B_P2P_PORT},127.0.0.1:{NODE_C_P2P_PORT}"
        )
        wait_for_condition(
            lambda: has_any_peer(node_a.base_url),
            timeout_seconds=20,
            description="node_a reconnect to shared partition",
        )

        time.sleep(3)
        node_a_post_reconnect = get_chain_info(node_a.base_url)
        if node_a_post_reconnect["height"] != 2:
            raise SmokeFailure("Node A height changed unexpectedly during equal-height fork exchange")
        if node_a_post_reconnect["best_block_hash"] != branch_a_tip_height2:
            raise SmokeFailure("Node A abandoned its canonical tip before the competing branch became longer")

        mine_to_height(node_b.base_url, miner_b, miner, 3)
        longer_branch_info = get_chain_info(node_b.base_url)
        wait_for_tip(node_c.base_url, longer_branch_info["best_block_hash"], 20, "node_c longer-branch sync")
        wait_for_tip(node_a.base_url, longer_branch_info["best_block_hash"], 20, "node_a live reorg adoption")

        node_c.stop()
        mine_to_height(node_b.base_url, miner_b, miner, 5)
        final_source_info = get_chain_info(node_b.base_url)
        wait_for_tip(node_a.base_url, final_source_info["best_block_hash"], 20, "node_a post-reorg catch-up")

        node_c.restart(static_peers=f"127.0.0.1:{NODE_B_P2P_PORT}")
        wait_for_condition(
            lambda: has_any_peer(node_c.base_url),
            timeout_seconds=20,
            description="node_c restart reconnect",
        )
        wait_for_tip(node_c.base_url, final_source_info["best_block_hash"], 30, "node_c restart catch-up")

        final_a_info = get_chain_info(node_a.base_url)
        final_c_info = get_chain_info(node_c.base_url)

        result = {
            "workspace": str(workspace),
            "branch_a_tip_height2": branch_a_tip_height2,
            "branch_bc_tip_height2": branch_bc_tip_height2,
            "same_height_conflict_preserved": node_a_post_reconnect["best_block_hash"] == branch_a_tip_height2,
            "longer_branch_adopted_by_a": final_a_info["best_block_hash"] == final_source_info["best_block_hash"],
            "restart_catchup_verified_for_c": final_c_info["best_block_hash"] == final_source_info["best_block_hash"],
            "node_b_height_final": final_source_info["height"],
            "node_a_height_final": final_a_info["height"],
            "node_c_height_final": final_c_info["height"],
            "shared_final_tip": final_source_info["best_block_hash"],
        }
        print(json.dumps(result, indent=2))
        return 0
    finally:
        node_a.stop()
        node_b.stop()
        node_c.stop()
        if not args.keep_artifacts and not args.work_dir:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
