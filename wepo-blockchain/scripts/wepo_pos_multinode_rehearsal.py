#!/usr/bin/env python3
"""Three-node hybrid PoW/PoS rehearsal using the real validator signer.

This is an isolated accelerated ``test``-profile exercise. It never finalizes or
starts mainnet. The rehearsal creates a client-signed canonical stake, produces
PoS blocks through the production signer subprocess, partitions the nodes into
a PoS branch and a stronger PoW branch, verifies the PoW branch wins on rejoin,
and proves the signer can continue above its retained anti-equivocation height.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import requests


ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = ROOT / "wepo-blockchain" / "core"
SIGNER_DIR = ROOT / "wepo-blockchain" / "signer"
NODE_SCRIPT = CORE_DIR / "wepo_node.py"
SIGNER_SCRIPT = SIGNER_DIR / "wepo_validator_signer.py"
VECTOR_PATH = ROOT / "tests" / "vectors" / "validator_signer_protocol_v3.json"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))
if str(SIGNER_DIR) not in sys.path:
    sys.path.insert(0, str(SIGNER_DIR))

os.environ.setdefault("WEPO_NETWORK_PROFILE", "test")
os.environ.setdefault("WEPO_TEST_PRE_POS_BLOCKS", "2")
os.environ.setdefault("WEPO_TEST_BLOCK_TIME_POS", "2")
os.environ.setdefault("WEPO_TEST_BLOCK_TIME_POW_HYBRID", "600")
os.environ.setdefault("WEPO_TEST_MIN_STAKE_WEPO", "100")
os.environ.setdefault("WEPO_TEST_POS_COLLATERAL_INITIAL_WEPO", "100")

from blockchain import BlockHeader, Transaction, WepoArgon2Miner  # noqa: E402
from validator_signer import SubprocessValidatorSigner  # noqa: E402
from wepo_validator_signer import initialize_validator_key  # noqa: E402


FORMAT = "wepo-pos-multinode-rehearsal-v1"
HTTP_TIMEOUT_SECONDS = 5
WAIT_TIMEOUT_SECONDS = 45
DEFAULT_P2P_BASE_PORT = 22701
DEFAULT_API_BASE_PORT = 8171


class RehearsalFailure(RuntimeError):
    """Raised when a required rehearsal invariant is not satisfied."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_port_free(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise RehearsalFailure(f"Port {port} is already in use")


def wait_for_condition(
    predicate: Callable[[], bool],
    *,
    description: str,
    timeout_seconds: int = WAIT_TIMEOUT_SECONDS,
    interval_seconds: float = 0.25,
) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            if predicate():
                return
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            last_error = exc
        time.sleep(interval_seconds)
    detail = f": {last_error}" if last_error else ""
    raise RehearsalFailure(f"Timed out waiting for {description}{detail}")


def get_json(url: str, **kwargs) -> object:
    response = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS, **kwargs)
    response.raise_for_status()
    return response.json()


def post_json(url: str, payload: dict) -> dict:
    response = requests.post(url, json=payload, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise RehearsalFailure(f"Expected object response from {url}")
    return result


class ManagedNode:
    """Lifecycle wrapper for one full-node subprocess."""

    def __init__(
        self,
        *,
        name: str,
        data_dir: Path,
        log_dir: Path,
        p2p_port: int,
        api_port: int,
        miner_address: str,
        base_environment: dict[str, str],
        signer_command: list[str] | None = None,
    ) -> None:
        self.name = name
        self.data_dir = data_dir
        self.log_path = log_dir / f"{name}.log"
        self.p2p_port = p2p_port
        self.api_port = api_port
        self.miner_address = miner_address
        self.base_environment = dict(base_environment)
        self.signer_command = list(signer_command) if signer_command else None
        self.static_peers = "none"
        self.background_mining = False
        self.base_url = f"http://127.0.0.1:{api_port}"
        self.process: subprocess.Popen[bytes] | None = None
        self.log_handle = None

    def start(self, *, static_peers: str, background_mining: bool = False) -> None:
        if self.process is not None:
            raise RehearsalFailure(f"{self.name} is already running")
        self.static_peers = static_peers
        self.background_mining = background_mining
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_handle = self.log_path.open("ab")
        command = [
            sys.executable,
            str(NODE_SCRIPT),
            "--network-profile",
            "test",
            "--data-dir",
            str(self.data_dir),
            "--p2p-port",
            str(self.p2p_port),
            "--api-host",
            "127.0.0.1",
            "--api-port",
            str(self.api_port),
            "--miner-address",
            self.miner_address,
            "--difficulty-override",
            "1",
        ]
        if not background_mining:
            command.append("--no-background-mining")
        environment = dict(self.base_environment)
        environment["WEPO_STATIC_PEERS"] = static_peers
        if self.signer_command:
            environment["WEPO_VALIDATOR_SIGNER_COMMAND_JSON"] = json.dumps(
                self.signer_command,
                separators=(",", ":"),
            )
            environment["WEPO_VALIDATOR_SIGNER_TIMEOUT_SECONDS"] = "15"
        else:
            environment.pop("WEPO_VALIDATOR_SIGNER_COMMAND_JSON", None)
            environment.pop("WEPO_VALIDATOR_SIGNER_TIMEOUT_SECONDS", None)
        self.process = subprocess.Popen(
            command,
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            env=environment,
        )
        wait_for_condition(
            lambda: self.api_ready(),
            description=f"{self.name} API readiness",
        )

    def api_ready(self) -> bool:
        if self.process is None or self.process.poll() is not None:
            return False
        try:
            response = requests.get(
                f"{self.base_url}/api/network/status",
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            return response.ok
        except requests.RequestException:
            return False

    def stop(self) -> None:
        if self.process is None:
            return
        process = self.process
        process.terminate()
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        finally:
            self.process = None
            if self.log_handle is not None:
                self.log_handle.close()
                self.log_handle = None

    def restart(self, *, static_peers: str, background_mining: bool = False) -> None:
        self.stop()
        self.start(static_peers=static_peers, background_mining=background_mining)

    def chain_info(self) -> dict:
        result = get_json(f"{self.base_url}/api/blockchain/info")
        if not isinstance(result, dict):
            raise RehearsalFailure(f"{self.name} returned invalid chain info")
        return result

    def network_status(self) -> dict:
        result = get_json(f"{self.base_url}/api/network/status")
        if not isinstance(result, dict):
            raise RehearsalFailure(f"{self.name} returned invalid network status")
        return result

    def block_at_height(self, height: int) -> dict:
        result = get_json(f"{self.base_url}/api/block/height/{height}")
        if not isinstance(result, dict):
            raise RehearsalFailure(f"{self.name} returned invalid block data")
        return result

    def latest_blocks(self, limit: int = 100) -> list[dict]:
        result = get_json(f"{self.base_url}/api/blocks/latest", params={"limit": limit})
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            raise RehearsalFailure(f"{self.name} returned invalid block list")
        return result


def peer_list(*ports: int) -> str:
    return ",".join(f"127.0.0.1:{port}" for port in ports) if ports else "none"


def wait_for_any_peer(nodes: Iterable[ManagedNode], description: str) -> None:
    node_list = list(nodes)
    wait_for_condition(
        lambda: all(bool(node.network_status().get("connections")) for node in node_list),
        description=description,
    )


def wait_for_tip(nodes: Iterable[ManagedNode], tip_hash: str, description: str) -> None:
    node_list = list(nodes)
    wait_for_condition(
        lambda: all(node.chain_info().get("best_block_hash") == tip_hash for node in node_list),
        description=description,
    )


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
    target = int(work.get("target_difficulty", work["bits"]))
    for nonce in range(2**32):
        header.nonce = nonce
        block_hash = miner.calculate_pow_hash(header)
        if miner.check_difficulty(block_hash, target):
            return nonce
    raise RehearsalFailure("Unable to solve accelerated PoW block")


def mine_one_block(node: ManagedNode, miner: WepoArgon2Miner) -> dict:
    work = get_json(
        f"{node.base_url}/api/mining/getwork",
        params={"miner_address": node.miner_address},
    )
    if not isinstance(work, dict):
        raise RehearsalFailure("Mining work response is invalid")
    result = post_json(
        f"{node.base_url}/api/mining/submit",
        {
            "job_id": work["job_id"],
            "nonce": solve_nonce(work, miner),
            "miner_address": node.miner_address,
        },
    )
    if result.get("accepted") is not True:
        raise RehearsalFailure(f"Mining submission rejected: {result}")
    return result


def mine_to_height(node: ManagedNode, miner: WepoArgon2Miner, target_height: int) -> None:
    while int(node.chain_info()["height"]) < target_height:
        mine_one_block(node, miner)


def submit_signed_stake(
    node: ManagedNode,
    *,
    validator_address: str,
    public_key: bytes,
    signer_command: list[str],
    authorization_path: Path,
) -> tuple[str, str]:
    built = post_json(
        f"{node.base_url}/api/stake",
        {
            "staker_address": validator_address,
            "amount": "100",
            "fee": "0",
        },
    )
    transaction = Transaction.from_dict(built["unsigned_tx"])
    network = built.get("network")
    if transaction.get_canonical_sighash(network).hex() != built.get("sighash"):
        raise RehearsalFailure("Stake API sighash differs from the reconstructed transaction")
    authorization = built.get("validator_signer_authorization")
    if not isinstance(authorization, dict):
        raise RehearsalFailure("Stake API omitted the signer authorization document")
    authorization_path.write_text(
        json.dumps(authorization, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    approval_command = [part for part in signer_command if part != "--stdio"] + [
        "--authorize-stake-request",
        str(authorization_path),
    ]
    completed = subprocess.run(
        approval_command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RehearsalFailure("Signer-only stake authorization failed")
    signer = SubprocessValidatorSigner(signer_command, timeout_seconds=15)
    signature = signer.sign_stake_transaction(
        validator_address,
        authorization["unsigned_tx"],
        authorization["input_utxos"],
        authorization["network"],
        authorization["sighash"],
    )
    for item in transaction.inputs:
        item.script_sig = b""
        item.signature_type = "dilithium"
        item.quantum_public_key = public_key
        item.quantum_signature = signature
    if not all(
        item.quantum_signature
        and item.quantum_public_key == public_key
        and item.script_sig == b""
        for item in transaction.inputs
    ):
        raise RehearsalFailure("Stake transaction did not normalize every signed input")
    local_txid = transaction.calculate_txid()
    submitted = post_json(
        f"{node.base_url}/api/transaction/send",
        {"signed_tx": transaction.to_dict()},
    )
    if submitted.get("transaction_id") != local_txid:
        raise RehearsalFailure("Node returned a different stake transaction ID")
    stake_id = str(built.get("stake_id") or "")
    if not stake_id:
        raise RehearsalFailure("Stake API omitted its canonical stake ID")
    return stake_id, local_txid


def wait_for_new_pos(node: ManagedNode, after_height: int, description: str) -> dict:
    result: dict[str, object] = {}

    def locate() -> bool:
        matches = [
            block
            for block in node.latest_blocks()
            if block.get("consensus_type") == "pos"
            and int(block.get("height", -1)) > after_height
        ]
        if not matches:
            return False
        result.update(max(matches, key=lambda item: int(item["height"])))
        return True

    wait_for_condition(locate, description=description)
    return dict(result)


def assert_active_stake(nodes: Iterable[ManagedNode], address: str, stake_id: str) -> None:
    for node in nodes:
        stakes = get_json(f"{node.base_url}/api/wallet/{address}/stakes")
        if not isinstance(stakes, list) or not any(
            item.get("stake_id") == stake_id and item.get("status") == "active"
            for item in stakes
            if isinstance(item, dict)
        ):
            raise RehearsalFailure(f"{node.name} does not expose the confirmed active stake")


def sqlite_integrity(path: Path) -> str:
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute("PRAGMA quick_check").fetchone()
    return str(row[0]) if row else "missing"


def chain_counts(path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            "SELECT consensus_type, COUNT(*) FROM blocks GROUP BY consensus_type"
        ).fetchall()
    return {str(consensus): int(count) for consensus, count in rows}



def semantic_database_sha256(path: Path) -> str:
    """Hash every user table by schema and deterministically sorted row values."""

    def normalize(value: object) -> object:
        if isinstance(value, bytes):
            return {"bytes_hex": value.hex()}
        if value is None or isinstance(value, (str, int, float)):
            return value
        raise RehearsalFailure(
            f"Unsupported SQLite value in semantic commitment: {type(value).__name__}"
        )

    document: list[dict[str, object]] = []
    with closing(sqlite3.connect(path)) as connection:
        tables = [
            str(row[0])
            for row in connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                   ORDER BY name"""
            ).fetchall()
        ]
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            columns = [
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({quoted})").fetchall()
            ]
            normalized_rows = [
                [normalize(value) for value in row]
                for row in connection.execute(f"SELECT * FROM {quoted}").fetchall()
            ]
            normalized_rows.sort(
                key=lambda row: json.dumps(
                    row,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            )
            document.append(
                {
                    "table": table,
                    "columns": columns,
                    "rows": normalized_rows,
                }
            )
    payload = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def read_signer_rows(path: Path) -> list[dict]:
    with closing(sqlite3.connect(path)) as connection:
        integrity = connection.execute("PRAGMA quick_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RehearsalFailure("Signer anti-equivocation database failed quick_check")
        rows = connection.execute(
            """SELECT network, validator_address, height, previous_block_hash,
                      hex(message), length(signature)
               FROM signed_blocks ORDER BY height"""
        ).fetchall()
    return [
        {
            "network": row[0],
            "validator_address": row[1],
            "height": int(row[2]),
            "previous_block_hash": row[3],
            "message": str(row[4]).lower(),
            "signature_bytes": int(row[5]),
        }
        for row in rows
    ]


def write_json_exclusive(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RehearsalFailure(f"Refusing to overwrite evidence file: {path}") from exc
    with os.fdopen(descriptor, "wb") as output:
        output.write(serialized)
        output.flush()
        os.fsync(output.fileno())


def retain_logs(log_dir: Path, evidence_path: Path) -> dict[str, dict[str, object]]:
    destination = evidence_path.parent / "logs"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=False, exist_ok=False)
    retained: dict[str, dict[str, object]] = {}
    for source in sorted(log_dir.glob("*.log")):
        target = destination / source.name
        shutil.copyfile(source, target)
        retained[source.name] = {
            "sha256": sha256_file(target),
            "bytes": target.stat().st_size,
            "path": str(target.relative_to(evidence_path.parent)).replace("\\", "/"),
        }
    return retained

def create_workspace_marker(workspace: Path) -> None:
    marker = workspace / ".wepo-pos-rehearsal-workspace"
    payload = f"{FORMAT}\n".encode("ascii")
    try:
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise RehearsalFailure("Unable to create rehearsal workspace marker") from exc
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)


def remove_workspace_verified(workspace: Path) -> None:
    if not workspace.exists():
        return
    if workspace.is_symlink():
        raise RehearsalFailure("Refusing to remove symlinked rehearsal workspace")
    resolved = workspace.resolve()
    forbidden = {
        Path(resolved.anchor),
        Path.home().resolve(),
        ROOT.resolve(),
    }
    if resolved in forbidden:
        raise RehearsalFailure(f"Refusing unsafe rehearsal cleanup target: {resolved}")
    marker = resolved / ".wepo-pos-rehearsal-workspace"
    try:
        marker_value = marker.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise RehearsalFailure("Rehearsal workspace marker is missing") from exc
    if marker_value != FORMAT:
        raise RehearsalFailure("Rehearsal workspace marker is invalid")

    last_error: OSError | None = None
    for _attempt in range(20):
        try:
            shutil.rmtree(resolved)
        except OSError as exc:
            last_error = exc
        if not resolved.exists():
            return
        time.sleep(0.25)
    raise RehearsalFailure(
        f"Rehearsal workspace cleanup failed after retries: {last_error}"
    )



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WEPO three-node PoS rehearsal")
    parser.add_argument("--evidence", type=Path, help="Fail-if-present evidence JSON path")
    parser.add_argument("--work-dir", type=Path, help="Optional isolated working directory")
    parser.add_argument("--keep-artifacts", action="store_true")
    parser.add_argument("--p2p-base-port", type=int, default=DEFAULT_P2P_BASE_PORT)
    parser.add_argument("--api-base-port", type=int, default=DEFAULT_API_BASE_PORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.evidence is not None and args.keep_artifacts:
        raise RehearsalFailure(
            "Retained evidence cannot be combined with private test artifacts"
        )
    if args.evidence is not None:
        if args.evidence.exists():
            raise RehearsalFailure(
                f"Refusing to overwrite evidence file: {args.evidence}"
            )
        if (args.evidence.parent / "logs").exists():
            raise RehearsalFailure("Refusing to overwrite retained rehearsal logs")
    started_at = utc_now()
    miner = WepoArgon2Miner()
    temporary_workspace = args.work_dir is None
    workspace = (
        Path(tempfile.mkdtemp(prefix="wepo-pos-multinode-"))
        if temporary_workspace
        else args.work_dir.resolve()
    )
    if not temporary_workspace:
        workspace.mkdir(parents=True, exist_ok=False)
    create_workspace_marker(workspace)
    log_dir = workspace / "logs"
    key_path = workspace / "signer-private" / "validator-key.json"
    signer_state_path = workspace / "signer-state" / "anti-equivocation.sqlite3"

    public = initialize_validator_key(key_path, "test")
    validator_address = public["validator_address"]
    validator_public_key = bytes.fromhex(public["public_key"])
    if "private_key" in public:
        raise RehearsalFailure("Signer initialization exported private key material")

    p2p_ports = [args.p2p_base_port + index for index in range(3)]
    api_ports = [args.api_base_port + index for index in range(3)]
    for port in [*p2p_ports, *api_ports]:
        ensure_port_free(port)

    base_environment = dict(os.environ)
    base_environment.update(
        {
            "WEPO_NETWORK_PROFILE": "test",
            "WEPO_TEST_GENESIS_ADDRESS": validator_address,
            "WEPO_TEST_GENESIS_TIMESTAMP": str(int(time.time()) - 10_000),
            "WEPO_TEST_COINBASE_MATURITY": "1",
            "WEPO_TEST_MIN_RELAY_FEE_PER_KB": "0",
            "WEPO_TEST_PRE_POS_BLOCKS": "2",
            "WEPO_TEST_BLOCK_TIME_INITIAL": "1",
            "WEPO_TEST_BLOCK_TIME_LONGTERM": "600",
            "WEPO_TEST_BLOCK_TIME_POS": "2",
            "WEPO_TEST_BLOCK_TIME_POW_HYBRID": "600",
            "WEPO_TEST_MIN_STAKE_WEPO": "100",
            "WEPO_TEST_POS_COLLATERAL_INITIAL_WEPO": "100",
            "WEPO_DNS_SEEDS": "off",
            "WEPO_REQUIRE_MAINNET_SEEDS": "0",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    signer_command = [
        sys.executable,
        str(SIGNER_SCRIPT),
        "--network",
        "test",
        "--key-file",
        str(key_path),
        "--state-db",
        str(signer_state_path),
        "--stdio",
        "--allow-insecure-permissions-for-test",
    ]

    nodes = [
        ManagedNode(
            name=f"node_{name}",
            data_dir=workspace / f"node_{name}",
            log_dir=log_dir,
            p2p_port=p2p_ports[index],
            api_port=api_ports[index],
            miner_address=validator_address,
            base_environment=base_environment,
            signer_command=signer_command if index == 0 else None,
        )
        for index, name in enumerate(("a", "b", "c"))
    ]
    node_a, node_b, node_c = nodes
    full_peers = {
        node_a.name: peer_list(node_b.p2p_port, node_c.p2p_port),
        node_b.name: peer_list(node_a.p2p_port, node_c.p2p_port),
        node_c.name: peer_list(node_a.p2p_port, node_b.p2p_port),
    }

    stages: dict[str, object] = {}
    successful = False
    try:
        node_c.start(static_peers=full_peers[node_c.name])
        node_b.start(static_peers=full_peers[node_b.name])
        node_a.start(static_peers=full_peers[node_a.name])
        wait_for_any_peer(nodes, "initial three-node peer mesh")

        mine_to_height(node_a, miner, 3)
        initial_tip = node_a.chain_info()["best_block_hash"]
        wait_for_tip(nodes, initial_tip, "pre-stake chain synchronization")
        stake_id, stake_txid = submit_signed_stake(
            node_a,
            validator_address=validator_address,
            public_key=validator_public_key,
            signer_command=signer_command,
            authorization_path=workspace / "stake-create-authorization.json",
        )
        mine_to_height(node_a, miner, 4)
        stake_tip = node_a.chain_info()["best_block_hash"]
        wait_for_tip(nodes, stake_tip, "stake confirmation synchronization")
        assert_active_stake(nodes, validator_address, stake_id)
        stages["stake"] = {
            "stake_id": stake_id,
            "transaction_id": stake_txid,
            "confirmed_height": 4,
            "operator_authorization_required": True,
            "isolated_signer_used": True,
            "controller_loaded_private_key": False,
            "network_bound_sighash": True,
            "all_nodes_active": True,
        }

        node_a.restart(
            static_peers=full_peers[node_a.name],
            background_mining=True,
        )
        first_pos = wait_for_new_pos(node_a, 4, "first signer-produced PoS block")
        node_a.restart(static_peers=full_peers[node_a.name])
        first_common_info = node_a.chain_info()
        wait_for_tip(nodes, first_common_info["best_block_hash"], "first PoS synchronization")
        if int(first_pos["height"]) > int(first_common_info["height"]):
            raise RehearsalFailure("First PoS observation exceeds the frozen common tip")
        stages["first_pos"] = {
            "height": int(first_pos["height"]),
            "hash": first_pos["hash"],
            "common_height": int(first_common_info["height"]),
            "common_tip": first_common_info["best_block_hash"],
            "all_nodes_synchronized": True,
        }

        common_height = int(first_common_info["height"])
        common_tip = str(first_common_info["best_block_hash"])
        for node in nodes:
            node.stop()
        node_b.start(static_peers=peer_list(node_a.p2p_port))
        node_c.start(static_peers="none")
        node_a.start(
            static_peers=peer_list(node_b.p2p_port),
            background_mining=True,
        )
        wait_for_any_peer((node_a, node_b), "partitioned A/B peer mesh")
        partition_pos = wait_for_new_pos(
            node_a,
            common_height,
            "partitioned signer-produced PoS block",
        )
        node_a.restart(static_peers=peer_list(node_b.p2p_port))
        signed_branch_info = node_a.chain_info()
        wait_for_tip(
            (node_a, node_b),
            signed_branch_info["best_block_hash"],
            "partitioned PoS branch synchronization",
        )
        if node_c.chain_info()["best_block_hash"] != common_tip:
            raise RehearsalFailure("Isolated node C changed before its competing PoW branch")

        pow_target_height = max(int(signed_branch_info["height"]) + 1, common_height + 2)
        mine_to_height(node_c, miner, pow_target_height)
        pow_branch_info = node_c.chain_info()
        if pow_branch_info["best_block_hash"] == signed_branch_info["best_block_hash"]:
            raise RehearsalFailure("Partition did not produce distinct PoS and PoW tips")
        stages["partition"] = {
            "common_height": common_height,
            "common_tip": common_tip,
            "signed_pos_height": int(partition_pos["height"]),
            "signed_pos_hash": partition_pos["hash"],
            "pos_branch_height": int(signed_branch_info["height"]),
            "pos_branch_tip": signed_branch_info["best_block_hash"],
            "pow_branch_height": int(pow_branch_info["height"]),
            "pow_branch_tip": pow_branch_info["best_block_hash"],
            "branches_distinct": True,
        }

        for node in nodes:
            node.stop()
        node_c.start(static_peers=full_peers[node_c.name])
        node_b.start(static_peers=full_peers[node_b.name])
        node_a.start(static_peers=full_peers[node_a.name])
        wait_for_any_peer(nodes, "rejoined three-node peer mesh")
        winning_tip = str(pow_branch_info["best_block_hash"])
        wait_for_tip(nodes, winning_tip, "stronger PoW branch adoption after rejoin")
        replacement = node_a.block_at_height(int(partition_pos["height"]))
        if replacement["hash"] == partition_pos["hash"]:
            raise RehearsalFailure("Signer-produced partition block remained canonical after PoW reorg")
        stages["rejoin"] = {
            "winning_height": int(pow_branch_info["height"]),
            "winning_tip": winning_tip,
            "all_nodes_adopted_stronger_pow_branch": True,
            "rolled_back_signed_height": int(partition_pos["height"]),
            "rolled_back_signed_hash": partition_pos["hash"],
            "canonical_replacement_hash": replacement["hash"],
            "canonical_replacement_consensus": replacement["consensus_type"],
        }

        node_a.restart(
            static_peers=full_peers[node_a.name],
            background_mining=True,
        )
        post_reorg_pos = wait_for_new_pos(
            node_a,
            int(pow_branch_info["height"]),
            "post-reorg signer continuation",
        )
        node_a.restart(static_peers=full_peers[node_a.name])
        final_info = node_a.chain_info()
        wait_for_tip(nodes, final_info["best_block_hash"], "final PoS synchronization")
        final_infos = {node.name: node.chain_info() for node in nodes}
        stages["post_reorg_pos"] = {
            "height": int(post_reorg_pos["height"]),
            "hash": post_reorg_pos["hash"],
            "final_height": int(final_info["height"]),
            "final_tip": final_info["best_block_hash"],
            "all_nodes_synchronized": all(
                info["best_block_hash"] == final_info["best_block_hash"]
                for info in final_infos.values()
            ),
        }

        for node in nodes:
            node.stop()
        signer_rows = read_signer_rows(signer_state_path)
        signed_heights = [row["height"] for row in signer_rows]
        if len(signer_rows) < 3 or len(signed_heights) != len(set(signed_heights)):
            raise RehearsalFailure("Signer state lacks three distinct PoS authorizations")
        if int(partition_pos["height"]) not in signed_heights:
            raise RehearsalFailure("Signer state lost the rolled-back authorization")
        if int(post_reorg_pos["height"]) <= max(
            height for height in signed_heights if height != int(post_reorg_pos["height"])
        ):
            raise RehearsalFailure("Post-reorg signer did not continue above retained state")

        chain_evidence = {}
        for node in nodes:
            database = node.data_dir / "blockchain.db"
            chain_evidence[node.name] = {
                "quick_check": sqlite_integrity(database),
                "consensus_counts": chain_counts(database),
                "database_sha256": sha256_file(database),
                "semantic_sha256": semantic_database_sha256(database),
            }
            if chain_evidence[node.name]["quick_check"] != "ok":
                raise RehearsalFailure(f"{node.name} database failed final quick_check")
        semantic_hashes = {
            item["semantic_sha256"] for item in chain_evidence.values()
        }
        if len(semantic_hashes) != 1:
            raise RehearsalFailure("Final node databases differ semantically")

        logs = retain_logs(log_dir, args.evidence) if args.evidence else {}
        workspace_cleanup_verified = False
        if not args.keep_artifacts:
            remove_workspace_verified(workspace)
            workspace_cleanup_verified = True
        workspace_retained = workspace.exists()

        evidence = {
            "format": FORMAT,
            "status": "pass",
            "test_only": True,
            "mainnet_mutated": False,
            "started_at": started_at,
            "completed_at": utc_now(),
            "network_profile": "test",
            "configuration": {
                "node_count": 3,
                "p2p_ports": p2p_ports,
                "api_ports": api_ports,
                "pre_pos_blocks": 2,
                "pos_block_time_seconds": 2,
                "pow_hybrid_block_time_seconds": 600,
                "difficulty_override": 1,
                "dns_seeds": "off",
                "require_mainnet_seeds": False,
            },
            "validator": {
                "address": validator_address,
                "public_key": validator_public_key.hex(),
                "private_key_retained": workspace_retained,
                "private_key_in_evidence": False,
                "private_key_loaded_by_controller": False,
            },
            "signer": {
                "protocol_version": 3,
                "script_sha256": sha256_file(SIGNER_SCRIPT),
                "vector_sha256": sha256_file(VECTOR_PATH),
                "anti_equivocation_quick_check": "ok",
                "signed_rows": signer_rows,
                "distinct_height_constraint_verified": True,
                "rolled_back_authorization_retained": True,
                "continued_above_retained_height": True,
            },
            "stages": stages,
            "final_nodes": final_infos,
            "chain_databases": chain_evidence,
            "semantic_state_equal": True,
            "artifacts": {
                "rehearsal_script_sha256": sha256_file(Path(__file__).resolve()),
                "node_script_sha256": sha256_file(NODE_SCRIPT),
                "logs": logs,
                "workspace_cleanup_verified": workspace_cleanup_verified,
                "workspace_retained": workspace_retained,
            },
        }
        if args.evidence:
            write_json_exclusive(args.evidence, evidence)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        successful = True
        return 0
    finally:
        for node in nodes:
            node.stop()
        if not args.keep_artifacts and (temporary_workspace or successful) and workspace.exists():
            remove_workspace_verified(workspace)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RehearsalFailure as exc:
        print(f"rehearsal failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
