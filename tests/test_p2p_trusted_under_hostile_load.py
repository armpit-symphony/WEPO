"""Trusted transaction/block propagation while the receiving node is attacked."""

from __future__ import annotations

import socket
import struct
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from address_utils import generate_wepo_address  # noqa: E402
from blockchain import Transaction, WepoBlockchain  # noqa: E402
from dilithium import generate_dilithium_keypair  # noqa: E402
from p2p_network import WepoP2PNode  # noqa: E402


def _reserve_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


def _wait_until(predicate, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


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


def _hostile_worker(
    node: WepoP2PNode,
    port: int,
    stop: threading.Event,
    delivered: list[int],
) -> None:
    header = struct.pack(
        "<4s12sI4s",
        b"NOPE",
        b"ping".ljust(12, b"\x00"),
        0,
        b"\x00" * 4,
    )
    index = 0
    while not stop.is_set():
        value = index + 100
        source_ip = (
            f"127.{1 + ((value // (254 * 254)) % 254)}."
            f"{1 + ((value // 254) % 254)}.{1 + (value % 254)}"
        )
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(0.25)
            sock.bind((source_ip, 0))
            sock.connect(("127.0.0.1", port))
            sock.sendall(header)
            delivered[0] += 1
            try:
                while sock.recv(4096):
                    pass
            except OSError:
                pass
        except OSError:
            pass
        finally:
            sock.close()
        index += 1


def test_trusted_transaction_and_block_propagate_during_hostile_load(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("WEPO_STATIC_PEERS", "off")
    monkeypatch.setenv("WEPO_DNS_SEEDS", "off")
    monkeypatch.delenv("WEPO_REQUIRE_MAINNET_SEEDS", raising=False)

    source_chain = WepoBlockchain(
        data_dir=str(tmp_path / "source"),
        network_profile="test",
        fixed_difficulty=1,
    )
    target_chain = WepoBlockchain(
        data_dir=str(tmp_path / "target"),
        network_profile="test",
        fixed_difficulty=1,
    )
    source = WepoP2PNode(
        "127.0.0.1", _reserve_port(), network_profile="test"
    )
    target = WepoP2PNode(
        "127.0.0.1", _reserve_port(), network_profile="test"
    )
    _wire(source, source_chain)
    _wire(target, target_chain)

    keypair = generate_dilithium_keypair()
    actor = generate_wepo_address(keypair.public_key, address_type="quantum")
    sink = generate_wepo_address(b"WEPO_HOSTILE_LOAD_SINK", address_type="quantum")
    miner = generate_wepo_address(b"WEPO_HOSTILE_LOAD_MINER", address_type="quantum")
    funding = source_chain.mine_block(actor)
    assert funding is not None

    stop = threading.Event()
    delivered = [0]
    attack_thread = threading.Thread(
        target=_hostile_worker,
        args=(target, target.port, stop, delivered),
        daemon=True,
    )
    try:
        source.start_server()
        target.start_server()
        assert source.connect_to_peer("127.0.0.1", target.port)
        assert _wait_until(
            lambda: target_chain.get_block_height() == 1
            and target_chain.get_latest_block().get_block_hash()
            == funding.get_block_hash()
        )

        attack_thread.start()
        assert _wait_until(lambda: delivered[0] >= 25)

        transaction = source_chain.create_transaction(
            from_address=actor,
            to_address=sink,
            amount=1,
            fee=0,
        )
        assert transaction is not None
        assert transaction.sign_all_inputs(
            keypair.private_key, keypair.public_key
        )
        assert source_chain.add_transaction_to_mempool(transaction)
        envelope = {
            "txid": transaction.calculate_txid(),
            "tx_data": transaction.to_dict(),
        }
        source.broadcast_to_peers(source.create_transaction_message(envelope))
        assert _wait_until(lambda: target_chain.has_transaction(envelope["txid"]))

        extension = source_chain.mine_block(miner)
        assert extension is not None
        source.broadcast_block({"hash": extension.get_block_hash()})
        assert _wait_until(
            lambda: target_chain.get_latest_block().get_block_hash()
            == extension.get_block_hash()
        )
        assert delivered[0] >= 25
        assert any(peer.is_connected() for peer in source.peers.values())
        assert any(peer.is_connected() for peer in target.peers.values())
    finally:
        stop.set()
        attack_thread.join(timeout=2.0)
        source.stop_server()
        target.stop_server()
        source_chain.conn.close()
        target_chain.conn.close()

    assert not attack_thread.is_alive()
