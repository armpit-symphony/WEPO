#!/usr/bin/env python3
"""
WEPO P2P Network Implementation
Peer-to-peer networking for revolutionary cryptocurrency
"""

import socket
import threading
import time
import json
import struct
import hashlib
import os
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass
from enum import IntEnum
import random
import select

# Network Constants
NETWORK_MAGICS = {
    "mainnet": b"WEPO",
    "test": b"WET1",
}
PROTOCOL_VERSION = 70001
MIN_PROTOCOL_VERSION = 70001
MAX_USER_AGENT_BYTES = 256
DEFAULT_PORT = 22567
MAX_PEERS = 8
CONNECTION_TIMEOUT = 30
HANDSHAKE_TIMEOUT_SECONDS = 30
PARTIAL_MESSAGE_TIMEOUT_SECONDS = 60
PING_INTERVAL = 60
MAX_MESSAGE_SIZE = 4 * 1024 * 1024
MAX_INVENTORY_ITEMS = 5000
MAX_ADDR_ITEMS = 1000
MAX_KNOWN_ADDRESSES = 10000
MAX_LOCATOR_HASHES = 101
MAX_HEADERS = 2000
MISBEHAVIOR_BAN_SECONDS = 60 * 60
MAX_BANNED_HOSTS = 4096
CONNECTION_BACKOFF_BASE_SECONDS = 5
CONNECTION_BACKOFF_MAX_SECONDS = 10 * 60


def _is_hash256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def _is_wire_address(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"ip", "port"}
        and isinstance(value["ip"], str)
        and bool(value["ip"])
        and len(value["ip"].encode("utf-8")) <= 255
        and type(value["port"]) is int
        and 1 <= value["port"] <= 65535
    )


# Dandelion++ transaction-origin privacy (metadata layer — see PRIVACY_DESIGN.md L1).
# A new tx first travels a random single-relay "stem" before "fluff" (normal flood),
# so the broadcasting IP is decoupled from the originating IP. This defeats the
# "first node to announce == sender" heuristic that AI/heuristic de-anon relies on.
DANDELION_EPOCH_SECONDS = 600        # rotate the stem route every ~10 min
DANDELION_FLUFF_PROBABILITY = 0.1    # per-hop chance to switch from stem to fluff
DANDELION_EMBARGO_SECONDS = 45       # failsafe: fluff a stem tx if not relayed onward in time

class MessageType(IntEnum):
    """P2P Message types"""
    VERSION = 0x01
    VERACK = 0x02
    PING = 0x03
    PONG = 0x04
    GETADDR = 0x05
    ADDR = 0x06
    INV = 0x07
    GETDATA = 0x08
    BLOCK = 0x09
    TX = 0x0A
    GETBLOCKS = 0x0B
    GETHEADERS = 0x0C
    HEADERS = 0x0D
    MEMPOOL = 0x0E
    REJECT = 0x0F
    
    # WEPO-specific messages
    MASTERNODE = 0x10
    STAKE = 0x11
    PRIVACY = 0x12
    DEXORDER = 0x13
    ATOMICSWAP = 0x14

class InventoryType(IntEnum):
    """Inventory object types"""
    ERROR = 0
    MSG_TX = 1
    MSG_BLOCK = 2
    MSG_FILTERED_BLOCK = 3
    MSG_CMPCT_BLOCK = 4

@dataclass
class NetworkAddress:
    """Network address structure"""
    time: int
    services: int
    ip: str
    port: int

@dataclass
class InventoryVector:
    """Inventory vector for announcing objects"""
    type: int
    hash: str

@dataclass
class P2PMessage:
    """P2P network message"""
    magic: bytes
    command: str
    length: int
    checksum: bytes
    payload: bytes

class WepoP2PNode:
    """WEPO P2P Network Node"""
    
    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT,
                 user_agent: str = "/WepoCore:1.0.0/", network_profile: Optional[str] = None):
        self.host = host
        self.port = port
        self.user_agent = user_agent
        self.network_profile = (network_profile or os.getenv("WEPO_NETWORK_PROFILE", "mainnet")).strip().lower()
        if self.network_profile not in NETWORK_MAGICS:
            raise ValueError(f"Unsupported WEPO network profile: {self.network_profile}")
        self.network_magic = NETWORK_MAGICS[self.network_profile]
        self.node_id = hashlib.sha256(f"{host}:{port}:{time.time()}".encode()).hexdigest()[:16]
        
        # Network state
        self.peers: Dict[str, 'WepoPeer'] = {}
        self.known_addresses: Set[tuple] = set()
        self.banned_until: Dict[str, float] = {}
        self.connection_backoff: Dict[str, tuple[int, float]] = {}
        self._peer_policy_lock = threading.Lock()
        self._connecting_sockets: Set[socket.socket] = set()
        self._connecting_lock = threading.Lock()

        self.process_started_at = int(time.time())
        self.misbehavior_events_total = 0
        self.connection_failures_total = 0
        self.running = False
        self.server_socket: Optional[socket.socket] = None
        self._stop_event = threading.Event()
        self._service_threads: List[threading.Thread] = []
        
        # Message handlers
        self.message_handlers: Dict[str, Callable] = {
            'version': self.handle_version,
            'verack': self.handle_verack,
            'ping': self.handle_ping,
            'pong': self.handle_pong,
            'getaddr': self.handle_getaddr,
            'addr': self.handle_addr,
            'inv': self.handle_inv,
            'getdata': self.handle_getdata,
            'block': self.handle_block,
            'tx': self.handle_tx,
            'getblocks': self.handle_getblocks,
            'getheaders': self.handle_getheaders,
            'headers': self.handle_headers,
        }
        
        # Callbacks for blockchain integration
        self.on_new_block: Optional[Callable] = None
        self.on_new_transaction: Optional[Callable] = None
        self.get_block_callback: Optional[Callable] = None
        self.get_headers_callback: Optional[Callable] = None
        self.get_transaction_callback: Optional[Callable] = None
        self.has_transaction_callback: Optional[Callable] = None
        self.get_block_hashes_callback: Optional[Callable] = None
        self.get_height_callback: Optional[Callable] = None
        self.get_locator_callback: Optional[Callable] = None

        # Dandelion++ transaction-origin privacy state
        self.dandelion_enabled = os.getenv("WEPO_DANDELION", "1").strip().lower() not in {
            "0", "off", "false", "no", "disabled"
        }
        self.dandelion_epoch_seconds = DANDELION_EPOCH_SECONDS
        self.dandelion_fluff_probability = DANDELION_FLUFF_PROBABILITY
        self.dandelion_embargo_seconds = DANDELION_EMBARGO_SECONDS
        self._dandelion_rng = random.Random()
        self._stem_pool: Dict[str, tuple] = {}  # txid -> (tx_data, embargo_deadline)
        self._stem_lock = threading.Lock()

        # Optional outbound SOCKS5 proxy (e.g. Tor at 127.0.0.1:9050) so the P2P
        # layer never exposes a real IP. See PRIVACY_DESIGN.md L1.
        self.socks5_proxy = self._parse_socks5_proxy(os.getenv("WEPO_SOCKS5_PROXY", ""))

        self.static_seed_addresses = self._load_static_seed_addresses()
        self.dns_seeds = self._load_dns_seeds()
        if self._requires_mainnet_seeds() and not self.static_seed_addresses and not self.dns_seeds:
            raise RuntimeError(
                "Mainnet P2P seeds are required. Set WEPO_STATIC_PEERS or WEPO_DNS_SEEDS."
            )

        print(f"WEPO P2P Node initialized: {self.node_id}")
        print(f"Listening on: {host}:{port}")

    def _network_profile_name(self) -> str:
        return self.network_profile

    def _requires_mainnet_seeds(self) -> bool:
        return (
            self._network_profile_name() == "mainnet"
            and os.getenv("WEPO_REQUIRE_MAINNET_SEEDS", "").strip().lower()
            in {"1", "true", "yes", "on"}
        )

    def _load_static_seed_addresses(self) -> List[tuple[str, int]]:
        """Load fixed seed peers, allowing test/smoke overrides through env."""
        configured_peers = os.getenv("WEPO_STATIC_PEERS", "").strip()
        if configured_peers.lower() in {"none", "off", "disabled", "-"}:
            return []
        if not configured_peers:
            if self._network_profile_name() == "test":
                return [
                    ("127.0.0.1", 22567),
                    ("127.0.0.1", 22568),
                ]
            return []

        seed_addresses: List[tuple[str, int]] = []
        for entry in configured_peers.split(","):
            host_port = entry.strip()
            if not host_port or ":" not in host_port:
                continue
            host, port_text = host_port.rsplit(":", 1)
            try:
                seed_addresses.append((host.strip(), int(port_text)))
            except ValueError:
                continue
        return seed_addresses

    def _load_dns_seeds(self) -> List[str]:
        configured_seeds = os.getenv("WEPO_DNS_SEEDS", "").strip()
        if configured_seeds.lower() in {"none", "off", "disabled", "-"}:
            return []
        if not configured_seeds:
            return []
        return [seed.strip() for seed in configured_seeds.split(",") if seed.strip()]

    def _is_self_endpoint(self, host: str, port: int) -> bool:
        """Reject obvious loopback/self peer targets during local discovery."""
        if port != self.port:
            return False

        normalized_host = (host or "").strip().lower()
        normalized_self_host = (self.host or "").strip().lower()
        local_aliases = {"127.0.0.1", "localhost", "0.0.0.0"}

        if normalized_host == normalized_self_host:
            return True
        if normalized_host in local_aliases and normalized_self_host in local_aliases:
            return True
        return False
    
    @staticmethod
    def _peer_host(peer: 'WepoPeer') -> Optional[str]:
        address = getattr(peer, "address", None)
        if (
            isinstance(address, tuple)
            and address
            and isinstance(address[0], str)
            and address[0]
        ):
            return address[0]
        return None

    def _prune_peer_policy(self, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        with self._peer_policy_lock:
            self.banned_until = {
                host: expiry
                for host, expiry in self.banned_until.items()
                if expiry > now
            }
            self.connection_backoff = {
                peer_id: state
                for peer_id, state in self.connection_backoff.items()
                if state[1] + (CONNECTION_BACKOFF_MAX_SECONDS * 2) > now
            }

    def is_host_banned(self, host: str, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        with self._peer_policy_lock:
            expiry = self.banned_until.get(host, 0)
            if expiry <= now:
                self.banned_until.pop(host, None)
                return False
            return True

    def penalize_peer(
        self,
        peer: 'WepoPeer',
        reason: str,
        ban_seconds: int = MISBEHAVIOR_BAN_SECONDS,
    ) -> None:
        host = self._peer_host(peer)
        with self._peer_policy_lock:
            self.misbehavior_events_total += 1
            if host is not None:
                if len(self.banned_until) >= MAX_BANNED_HOSTS:
                    oldest_host = min(self.banned_until, key=self.banned_until.get)
                    self.banned_until.pop(oldest_host, None)
                self.banned_until[host] = max(
                    self.banned_until.get(host, 0),
                    time.time() + max(1, ban_seconds),
                )
        if host is not None:
            print(f"Banned peer host {host}: {reason}")
        disconnect = getattr(peer, "disconnect", None)
        if callable(disconnect):
            disconnect()

    def _outbound_backoff_active(
        self, peer_id: str, now: Optional[float] = None
    ) -> bool:
        now = time.time() if now is None else now
        with self._peer_policy_lock:
            state = self.connection_backoff.get(peer_id)
            return bool(state and state[1] > now)

    def _record_connection_failure(self, peer_id: str) -> None:
        with self._peer_policy_lock:
            self.connection_failures_total += 1
            previous_attempts = self.connection_backoff.get(peer_id, (0, 0))[0]
            attempts = min(previous_attempts + 1, 16)
            delay = min(
                CONNECTION_BACKOFF_MAX_SECONDS,
                CONNECTION_BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)),
            )
            self.connection_backoff[peer_id] = (attempts, time.time() + delay)

    def _record_connection_success(self, peer_id: str) -> None:
        with self._peer_policy_lock:
            self.connection_backoff.pop(peer_id, None)

    def _track_connecting_socket(self, sock: socket.socket) -> bool:
        with self._connecting_lock:
            if self._stop_event.is_set():
                return False
            self._connecting_sockets.add(sock)
            return True

    def _untrack_connecting_socket(self, sock: socket.socket) -> None:
        with self._connecting_lock:
            self._connecting_sockets.discard(sock)

    def create_message(self, command: str, payload: bytes = b'') -> bytes:
        """Create a P2P protocol message"""
        if len(payload) > MAX_MESSAGE_SIZE:
            raise ValueError("P2P payload exceeds the maximum message size")
        # Calculate checksum
        checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        
        # Create header
        header = struct.pack('<4s12sI4s', 
                           self.network_magic,
                           command.encode().ljust(12, b'\x00'),
                           len(payload),
                           checksum)
        
        return header + payload
    
    def parse_message(self, data: bytes) -> Optional[P2PMessage]:
        """Parse incoming P2P message"""
        if len(data) < 24:  # Header size
            return None
        
        try:
            # Parse header
            magic, command_bytes, length, checksum = struct.unpack('<4s12sI4s', data[:24])
            
            if length > MAX_MESSAGE_SIZE:
                print(f"Oversized P2P message rejected: {length} bytes")
                return None

            if magic != self.network_magic:
                print(f"Invalid magic bytes: {magic}")
                return None
            
            command = command_bytes.rstrip(b'\x00').decode()
            
            if len(data) < 24 + length:
                print(f"Incomplete message: expected {24 + length}, got {len(data)}")
                return None
            
            payload = data[24:24 + length]
            
            # Verify checksum
            expected_checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
            if checksum != expected_checksum:
                print(f"Invalid checksum for {command}")
                return None
            
            return P2PMessage(magic, command, length, checksum, payload)
            
        except Exception as e:
            print(f"Error parsing message: {e}")
            return None
    
    def create_version_message(self) -> bytes:
        """Create version message"""
        payload_data = {
            'version': PROTOCOL_VERSION,
            'services': 1,  # NODE_NETWORK
            'timestamp': int(time.time()),
            'addr_recv': {'ip': '127.0.0.1', 'port': self.port},
            'addr_from': {'ip': self.host, 'port': self.port},
            'nonce': random.randint(0, 2**64 - 1),
            'user_agent': self.user_agent,
            'start_height': self.get_height_callback() if self.get_height_callback else 0,
            'network_profile': self.network_profile,
            'relay': True
        }
        
        payload = json.dumps(payload_data).encode()
        return self.create_message('version', payload)
    
    def start_server(self):
        """Start P2P server"""
        if self.running:
            return
        try:
            self._stop_event.clear()
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(MAX_PEERS)
            self.running = True
            
            print(f"P2P server started on {self.host}:{self.port}")
            
            # Start accepting connections
            accept_thread = threading.Thread(
                target=self.accept_connections,
                daemon=True,
                name=f"wepo-p2p-accept-{self.port}",
            )
            accept_thread.start()
            
            # Start periodic tasks
            periodic_thread = threading.Thread(
                target=self.periodic_tasks,
                daemon=True,
                name=f"wepo-p2p-periodic-{self.port}",
            )
            periodic_thread.start()
            self._service_threads = [accept_thread, periodic_thread]
            
        except Exception as e:
            print(f"Failed to start P2P server: {e}")
            self.running = False
    
    def stop_server(self):
        """Stop P2P server"""
        print("Stopping P2P server...")
        self.running = False
        self._stop_event.set()

        with self._connecting_lock:
            connecting_sockets = list(self._connecting_sockets)
            self._connecting_sockets.clear()
        for connecting_socket in connecting_sockets:
            try:
                connecting_socket.close()
            except OSError:
                pass
        
        # Close all peer connections
        for peer in list(self.peers.values()):
            peer.disconnect()
        
        # Close server socket
        if self.server_socket:
            self.server_socket.close()
            self.server_socket = None

        current_thread = threading.current_thread()
        for thread in self._service_threads:
            if thread is not current_thread:
                thread.join(timeout=2.0)
        self._service_threads = [
            thread for thread in self._service_threads
            if thread.is_alive()
        ]
        
        print("P2P server stopped")
    
    def accept_connections(self):
        """Accept incoming peer connections"""
        while self.running:
            try:
                if self.server_socket:
                    # Use select for non-blocking accept
                    ready, _, _ = select.select([self.server_socket], [], [], 1.0)
                    if ready:
                        conn, addr = self.server_socket.accept()
                        if self.is_host_banned(addr[0]):
                            conn.close()
                            continue

                        if len(self.peers) < MAX_PEERS:
                            peer = WepoPeer(conn, addr, self, incoming=True)
                            peer.start()
                        else:
                            conn.close()
            except Exception as e:
                if self.running:
                    print(f"Error accepting connection: {e}")
                break
    
    def connect_to_peer(self, host: str, port: int) -> bool:
        """Connect to a peer"""
        if self._stop_event.is_set():
            return False
        if len(self.peers) >= MAX_PEERS:
            return False

        if self._is_self_endpoint(host, port):
            return False
        
        peer_id = f"{host}:{port}"
        if self.is_host_banned(host) or self._outbound_backoff_active(peer_id):
            return False

        if peer_id in self.peers:
            return False

        sock = None
        try:
            if self.socks5_proxy:
                # Route outbound P2P through the SOCKS5 proxy (e.g. Tor).
                sock = self._socks5_connect(self.socks5_proxy, host, port)
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if not self._track_connecting_socket(sock):
                    sock.close()
                    return False
                try:
                    sock.settimeout(CONNECTION_TIMEOUT)
                    sock.connect((host, port))
                finally:
                    self._untrack_connecting_socket(sock)

            peer = WepoPeer(sock, (host, port), self, incoming=False)
            peer.start()
            return True

        except Exception as e:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            if not self._stop_event.is_set():
                self._record_connection_failure(peer_id)
                print(f"Failed to connect to {host}:{port}: {e}")
            return False
    
    def discover_peers(self):
        """Discover peers through DNS seeds and existing connections"""
        print("Discovering peers...")
        if self._stop_event.is_set():
            return
        
        if not self.static_seed_addresses and not self.dns_seeds:
            print("No P2P seed peers configured; set WEPO_STATIC_PEERS or WEPO_DNS_SEEDS to bootstrap peers.")

        for host, port in self.static_seed_addresses:
            if self._stop_event.is_set():
                return
            if len(self.peers) < MAX_PEERS:
                self.connect_to_peer(host, port)

        resolved_dns_peers: Set[tuple[str, int]] = set()
        for seed in self.dns_seeds:
            if self._stop_event.is_set():
                return
            try:
                results = socket.getaddrinfo(
                    seed,
                    DEFAULT_PORT,
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                )
            except socket.gaierror as exc:
                print(f"Failed to resolve DNS seed {seed}: {exc}")
                continue
            for result in results:
                resolved_dns_peers.add((result[4][0], result[4][1]))

        for host, port in sorted(resolved_dns_peers):
            if self._stop_event.is_set():
                return
            if len(self.peers) < MAX_PEERS:
                self.connect_to_peer(host, port)

        # Request addresses from existing peers
        for peer in list(self.peers.values()):
            if peer.is_connected():
                peer.send_getaddr()
    
    def periodic_tasks(self):
        """Periodic maintenance tasks"""
        while self.running:
            try:
                self._prune_peer_policy()
                # Clean up disconnected peers
                disconnected = [peer_id for peer_id, peer in list(self.peers.items())
                              if not peer.is_connected()]
                for peer_id in disconnected:
                    self.peers.pop(peer_id, None)
                
                # Send pings to peers
                for peer in list(self.peers.values()):
                    if peer.is_connected():
                        peer.send_ping()
                
                # Try to maintain connections
                if len(self.peers) < MAX_PEERS // 2:
                    self.discover_peers()

                # Dandelion++ failsafe: fluff any stem tx whose embargo expired.
                self.process_embargoes()

                if self._stop_event.wait(PING_INTERVAL):
                    break
                
            except Exception as e:
                print(f"Error in periodic tasks: {e}")
    
    def broadcast_to_peers(self, message: bytes, exclude_peer_id: Optional[str] = None):
        """Broadcast message to all connected peers"""
        for peer_id, peer in list(self.peers.items()):
            if peer_id == exclude_peer_id:
                continue
            if peer.is_connected():
                peer.send_raw(message)
    
    def broadcast_transaction(self, tx_data: dict):
        """Originate a transaction onto the network with Dandelion++ origin privacy."""
        self.dandelion_relay_transaction(tx_data, from_peer_id=None)

    # ===== Dandelion++ transaction-origin privacy (PRIVACY_DESIGN.md L1) =====

    def _dandelion_epoch_index(self, now: Optional[float] = None) -> int:
        now = time.time() if now is None else now
        return int(now // self.dandelion_epoch_seconds)

    def select_stem_peer(self, epoch_index: int, peer_ids: List[str]) -> Optional[str]:
        """Pick ONE stem relay for this epoch — stable within the epoch, rotating
        between epochs, deterministic per (node, epoch). None when no peers."""
        if not peer_ids:
            return None
        ordered = sorted(peer_ids)
        digest = hashlib.sha256(f"{self.node_id}:{epoch_index}".encode()).digest()
        return ordered[int.from_bytes(digest[:8], "big") % len(ordered)]

    def dandelion_decision(self, peer_ids: List[str], now: Optional[float] = None,
                           rng: Optional[random.Random] = None):
        """Pure routing decision: ('fluff', None) or ('stem', stem_peer_id).

        Fluffs when Dandelion is disabled, when there is no eligible stem peer, or
        with probability `dandelion_fluff_probability` per hop (so a tx eventually
        fluffs even if every hop chooses stem).
        """
        if not self.dandelion_enabled:
            return ('fluff', None)
        stem_peer = self.select_stem_peer(self._dandelion_epoch_index(now), list(peer_ids))
        if stem_peer is None:
            return ('fluff', None)
        roll = (rng or self._dandelion_rng).random()
        if roll < self.dandelion_fluff_probability:
            return ('fluff', None)
        return ('stem', stem_peer)

    def _connected_peer_ids(self, exclude: Optional[str] = None) -> List[str]:
        return [pid for pid, p in list(self.peers.items())
                if p.is_connected() and pid != exclude]

    def fluff_transaction(self, tx_data: dict, exclude_peer_id: Optional[str] = None):
        """Fluff phase: announce via inventory to all peers (normal flood)."""
        inv_msg = self.create_inv_message([{
            'type': InventoryType.MSG_TX,
            'hash': tx_data.get('txid', '')
        }])
        self.broadcast_to_peers(inv_msg, exclude_peer_id=exclude_peer_id)

    def _send_stem_transaction(self, peer_id: str, tx_data: dict) -> bool:
        """Relay the full tx to a single stem peer, tagged as stem phase."""
        peer = self.peers.get(peer_id)
        if not peer or not peer.is_connected():
            return False
        payload = dict(tx_data)
        payload['_dandelion_phase'] = 'stem'
        peer.send_raw(self.create_message('tx', json.dumps(payload).encode()))
        return True

    def dandelion_relay_transaction(self, tx_data: dict, from_peer_id: Optional[str] = None):
        """Route a new or stem-received tx through Dandelion++.

        Stem: forward to one relay and hold an embargo (failsafe to fluff later).
        Fluff: announce to all peers now and drop any embargo.
        """
        txid = tx_data.get('txid', '')
        action, stem_peer = self.dandelion_decision(self._connected_peer_ids(exclude=from_peer_id))
        if action == 'stem' and self._send_stem_transaction(stem_peer, tx_data):
            with self._stem_lock:
                self._stem_pool[txid] = (tx_data, time.time() + self.dandelion_embargo_seconds)
            return ('stem', stem_peer)
        # Chosen fluff, or stem relay failed -> fluff now.
        with self._stem_lock:
            self._stem_pool.pop(txid, None)
        self.fluff_transaction(tx_data)
        return ('fluff', None)

    def expired_embargoes(self, now: Optional[float] = None) -> List[tuple]:
        now = time.time() if now is None else now
        with self._stem_lock:
            expired = [(txid, data) for txid, (data, deadline) in self._stem_pool.items()
                       if now >= deadline]
            for txid, _ in expired:
                self._stem_pool.pop(txid, None)
        return expired

    def process_embargoes(self, now: Optional[float] = None):
        """Failsafe: fluff any stem tx not relayed onward before its embargo expired."""
        for _txid, tx_data in self.expired_embargoes(now):
            self.fluff_transaction(tx_data)

    # ===== Outbound SOCKS5 / Tor transport =====

    @staticmethod
    def _parse_socks5_proxy(value: str) -> Optional[tuple]:
        """Parse 'host:port' into a (host, port) tuple, or None if unset/invalid."""
        value = (value or "").strip()
        if not value or ":" not in value:
            return None
        host, port_text = value.rsplit(":", 1)
        try:
            return (host.strip(), int(port_text))
        except ValueError:
            return None

    def _socks5_connect(self, proxy: tuple, host: str, port: int) -> socket.socket:
        """Open a TCP connection to host:port through a SOCKS5 proxy (e.g. Tor).

        No-auth CONNECT with the destination sent as a domain name, so the proxy
        (not this node) performs resolution — required for .onion and to avoid DNS
        leaks. Raises on any SOCKS-level failure.
        """
        proxy_host, proxy_port = proxy
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if not self._track_connecting_socket(sock):
            sock.close()
            raise OSError("P2P node is stopping")
        try:
            sock.settimeout(CONNECTION_TIMEOUT)
            sock.connect((proxy_host, proxy_port))
            # Greeting: version 5, one method, "no authentication".
            sock.sendall(b"\x05\x01\x00")
            greeting = self._recv_exact(sock, 2)
            if greeting[0] != 0x05 or greeting[1] != 0x00:
                raise OSError("SOCKS5 proxy rejected no-auth method")

            # CONNECT request with domain-name address type (0x03).
            host_bytes = host.encode()
            if len(host_bytes) > 255:
                raise OSError("SOCKS5 destination host too long")
            request = b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + struct.pack(">H", port)
            sock.sendall(request)

            reply = self._recv_exact(sock, 4)
            if reply[1] != 0x00:
                raise OSError(f"SOCKS5 CONNECT failed (reply code {reply[1]})")
            # Drain the bound address per the address type in reply[3].
            atyp = reply[3]
            if atyp == 0x01:
                self._recv_exact(sock, 4 + 2)
            elif atyp == 0x03:
                ln = self._recv_exact(sock, 1)[0]
                self._recv_exact(sock, ln + 2)
            elif atyp == 0x04:
                self._recv_exact(sock, 16 + 2)
            return sock
        except Exception:
            sock.close()
            raise
        finally:
            self._untrack_connecting_socket(sock)

    @staticmethod
    def _recv_exact(sock: socket.socket, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise OSError("SOCKS5 proxy closed the connection")
            buf += chunk
        return buf

    def broadcast_block(self, block_data: dict):
        """Broadcast block to network"""
        inv_msg = self.create_inv_message([{
            'type': InventoryType.MSG_BLOCK,
            'hash': block_data.get('hash', '')
        }])
        self.broadcast_to_peers(inv_msg)
    
    def create_inv_message(self, inventory: List[dict]) -> bytes:
        """Create inventory message"""
        if not isinstance(inventory, list) or len(inventory) > MAX_INVENTORY_ITEMS:
            raise ValueError("inventory exceeds protocol limits")
        payload = json.dumps(
            {'inventory': inventory},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return self.create_message('inv', payload)
    
    # Message handlers
    def handle_version(self, peer: 'WepoPeer', payload: bytes):
        """Handle version message"""
        try:
            data = json.loads(payload.decode())
            if (
                not isinstance(data, dict)
                or set(data) != {
                    "version", "services", "timestamp", "addr_recv",
                    "addr_from", "nonce", "user_agent", "start_height",
                    "network_profile", "relay",
                }
            ):
                raise ValueError("version message has an invalid wire schema")
            peer_network_profile = data.get('network_profile')
            if peer_network_profile != self.network_profile:
                print(
                    f"Rejecting {peer.peer_id}: network profile "
                    f"{peer_network_profile!r} does not match {self.network_profile!r}"
                )
                self.penalize_peer(peer, "network profile mismatch")
                return

            if getattr(peer, 'version_received', False):
                print(f"Rejecting {peer.peer_id}: duplicate version message")
                self.penalize_peer(peer, "duplicate version message")
                return

            version = data.get('version')
            services = data.get('services')
            user_agent = data.get('user_agent')
            start_height = data.get('start_height')
            if type(version) is not int or version < MIN_PROTOCOL_VERSION:
                print(f"Rejecting {peer.peer_id}: unsupported protocol version")
                self.penalize_peer(peer, "unsupported protocol version")
                return
            if type(services) is not int or services < 0:
                self.penalize_peer(peer, "invalid services field")
                return
            if (
                not isinstance(user_agent, str)
                or len(user_agent.encode('utf-8')) > MAX_USER_AGENT_BYTES
            ):
                self.penalize_peer(peer, "invalid user agent")
                return
            if (
                type(data["timestamp"]) is not int
                or data["timestamp"] < 0
                or not _is_wire_address(data["addr_recv"])
                or not _is_wire_address(data["addr_from"])
                or type(data["nonce"]) is not int
                or not 0 <= data["nonce"] <= 2**64 - 1
                or type(data["relay"]) is not bool
            ):
                self.penalize_peer(peer, "invalid version metadata")
                return
            if type(start_height) is not int or start_height < -1:
                self.penalize_peer(peer, "invalid start height")
                return

            peer.version = version
            peer.services = services
            peer.user_agent = user_agent
            peer.start_height = start_height
            peer.version_received = True
            
            print(f"Received version from {peer.peer_id}: {peer.user_agent}")
            
            # Send verack
            peer.send_verack()
            
        except Exception as e:
            print(f"Error handling version: {e}")
            self.penalize_peer(peer, "malformed version message")
    
    def handle_verack(self, peer: 'WepoPeer', payload: bytes):
        """Handle version acknowledgment"""
        if payload:
            self.penalize_peer(peer, "malformed verack message")
            return
        if not getattr(peer, 'version_received', False):
            print(f"Rejecting {peer.peer_id}: verack received before version")
            self.penalize_peer(peer, "verack before version")
            return
        peer.handshake_complete = True
        print(f"Handshake complete with {peer.peer_id}")
        self._record_connection_success(peer.peer_id)
        self.request_headers_sync(peer)
    
    def handle_ping(self, peer: 'WepoPeer', payload: bytes):
        """Handle ping message"""
        try:
            data = json.loads(payload.decode())
            if (
                not isinstance(data, dict)
                or set(data) != {"nonce"}
                or type(data["nonce"]) is not int
                or not 0 <= data["nonce"] <= 2**64 - 1
            ):
                raise ValueError("ping has an invalid wire schema")
            nonce = data["nonce"]
            peer.send_pong(nonce)
        except Exception as e:
            print(f"Error handling ping: {e}")
            self.penalize_peer(peer, "malformed ping message")
    
    def handle_pong(self, peer: 'WepoPeer', payload: bytes):
        """Handle pong message"""
        try:
            data = json.loads(payload.decode())
            if (
                not isinstance(data, dict)
                or set(data) != {"nonce"}
                or type(data["nonce"]) is not int
                or not 0 <= data["nonce"] <= 2**64 - 1
            ):
                raise ValueError("pong has an invalid wire schema")
            nonce = data["nonce"]
            if nonce != peer.pending_ping_nonce:
                print(f"Ignoring unmatched pong from {peer.peer_id}")
                return
            peer.pending_ping_nonce = None
            peer.pending_ping_sent_at = None
            peer.last_pong = time.time()
        except Exception as e:
            print(f"Error handling pong: {e}")
            self.penalize_peer(peer, "malformed pong message")
    
    def handle_getaddr(self, peer: 'WepoPeer', payload: bytes):
        """Handle address request"""
        if payload:
            self.penalize_peer(peer, "malformed getaddr message")
            return
        # Send known addresses
        addresses = list(self.known_addresses)[:MAX_ADDR_ITEMS]
        addr_msg = self.create_addr_message(addresses)
        peer.send_raw(addr_msg)
    
    def handle_addr(self, peer: 'WepoPeer', payload: bytes):
        """Handle address message"""
        try:
            data = json.loads(payload.decode())
            if not isinstance(data, dict) or set(data) != {"addresses"}:
                raise ValueError("address message has an invalid wire schema")
            addresses = data["addresses"]
            if not isinstance(addresses, list) or len(addresses) > MAX_ADDR_ITEMS:
                raise ValueError("address message exceeds protocol limits")

            accepted_addresses = []
            for addr in addresses:
                if (
                    not isinstance(addr, dict)
                    or set(addr) != {"ip", "port"}
                    or not isinstance(addr["ip"], str)
                    or not addr["ip"]
                    or len(addr["ip"].encode("utf-8")) > 255
                    or type(addr["port"]) is not int
                    or not 1 <= addr["port"] <= 65535
                ):
                    raise ValueError("address entry has an invalid wire schema")
                if not self._is_self_endpoint(addr["ip"], addr["port"]):
                    accepted_addresses.append((addr["ip"], addr["port"]))
            
            remaining_capacity = max(
                0, MAX_KNOWN_ADDRESSES - len(self.known_addresses)
            )
            self.known_addresses.update(accepted_addresses[:remaining_capacity])

            print(f"Received {len(addresses)} addresses from {peer.peer_id}")
            
        except Exception as e:
            print(f"Error handling addr: {e}")
            self.penalize_peer(peer, "malformed address message")
    
    def handle_inv(self, peer: 'WepoPeer', payload: bytes):
        """Handle inventory message"""
        try:
            data = json.loads(payload.decode())
            if not isinstance(data, dict) or set(data) != {"inventory"}:
                raise ValueError("inventory has an invalid wire schema")
            inventory = data["inventory"]
            if not isinstance(inventory, list) or len(inventory) > MAX_INVENTORY_ITEMS:
                raise ValueError("inventory exceeds protocol limits")
            
            # Request data for items we don't have
            getdata_items = []
            for item in inventory:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"type", "hash"}
                    or type(item["type"]) is not int
                    or item["type"] not in {
                        int(InventoryType.MSG_BLOCK),
                        int(InventoryType.MSG_TX),
                    }
                    or not _is_hash256(item["hash"])
                ):
                    raise ValueError("inventory item has an invalid wire schema")
                item_type = item["type"]
                
                if item_type == InventoryType.MSG_BLOCK:
                    # Check if we have this block
                    getdata_items.append(item)
                elif item_type == InventoryType.MSG_TX:
                    txid = item["hash"]
                    if (
                        self.has_transaction_callback
                        and self.has_transaction_callback(txid)
                    ):
                        continue
                    getdata_items.append(item)
            
            if getdata_items:
                getdata_msg = self.create_getdata_message(getdata_items)
                peer.send_raw(getdata_msg)
                
        except Exception as e:
            print(f"Error handling inv: {e}")
            self.penalize_peer(peer, "malformed inventory message")
    
    def handle_getdata(self, peer: 'WepoPeer', payload: bytes):
        """Handle getdata message"""
        try:
            data = json.loads(payload.decode())
            if not isinstance(data, dict) or set(data) != {"inventory"}:
                raise ValueError("getdata has an invalid wire schema")
            inventory = data["inventory"]
            if not isinstance(inventory, list) or len(inventory) > MAX_INVENTORY_ITEMS:
                raise ValueError("getdata inventory exceeds protocol limits")
            
            for item in inventory:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"type", "hash"}
                    or type(item["type"]) is not int
                    or item["type"] not in {
                        int(InventoryType.MSG_BLOCK),
                        int(InventoryType.MSG_TX),
                    }
                    or not _is_hash256(item["hash"])
                ):
                    raise ValueError("getdata item has an invalid wire schema")
                item_type = item["type"]
                item_hash = item["hash"]
                
                if item_type == InventoryType.MSG_BLOCK and self.get_block_callback:
                    block_data = self.get_block_callback(item_hash)
                    if block_data:
                        block_msg = self.create_block_message(block_data)
                        peer.send_raw(block_msg)
                        
                elif item_type == InventoryType.MSG_TX and self.get_transaction_callback:
                    tx_data = self.get_transaction_callback(item_hash)
                    if tx_data:
                        tx_msg = self.create_transaction_message(tx_data)
                        peer.send_raw(tx_msg)
                    
        except Exception as e:
            print(f"Error handling getdata: {e}")
            self.penalize_peer(peer, "malformed getdata message")
    
    def handle_block(self, peer: 'WepoPeer', payload: bytes):
        """Handle block message"""
        try:
            data = json.loads(payload.decode())
            print(f"Received block from {peer.peer_id}: {data.get('hash', 'unknown')}")
            
            if self.on_new_block:
                accepted = self.on_new_block(data)
                if accepted is False:
                    self.penalize_peer(peer, "invalid block")
                
        except Exception as e:
            print(f"Error handling block: {e}")
            self.penalize_peer(peer, "malformed block message")

    def handle_headers(self, peer: 'WepoPeer', payload: bytes):
        """Handle headers message by requesting the blocks we are missing."""
        try:
            data = json.loads(payload.decode())
            if not isinstance(data, dict) or set(data) != {"headers"}:
                raise ValueError("headers has an invalid wire schema")
            headers = data["headers"]
            if not isinstance(headers, list) or len(headers) > MAX_HEADERS:
                raise ValueError("headers exceeds protocol limits")
            if not headers:
                return

            missing_inventory = []
            for header in headers:
                if (
                    not isinstance(header, dict)
                    or set(header) != {
                        "hash", "prev_hash", "height", "timestamp", "bits",
                        "nonce", "merkle_root", "consensus_type",
                    }
                    or not _is_hash256(header["hash"])
                    or not _is_hash256(header["prev_hash"])
                    or not _is_hash256(header["merkle_root"])
                    or type(header["height"]) is not int
                    or header["height"] < 0
                    or type(header["timestamp"]) is not int
                    or header["timestamp"] < 0
                    or type(header["bits"]) is not int
                    or header["bits"] < 0
                    or type(header["nonce"]) is not int
                    or header["nonce"] < 0
                    or header["consensus_type"] not in {"pow", "pos"}
                ):
                    raise ValueError("header has an invalid wire schema")
                block_hash = header["hash"]
                if self.get_block_callback and self.get_block_callback(block_hash):
                    continue
                missing_inventory.append({
                    'type': InventoryType.MSG_BLOCK,
                    'hash': block_hash,
                })

            if missing_inventory:
                peer.send_raw(self.create_getdata_message(missing_inventory))
        except Exception as e:
            print(f"Error handling headers: {e}")
            self.penalize_peer(peer, "malformed headers message")
    
    def handle_tx(self, peer: 'WepoPeer', payload: bytes):
        """Handle transaction message (including Dandelion++ stem relays)."""
        try:
            data = json.loads(payload.decode())
            if not isinstance(data, dict):
                raise ValueError("transaction envelope must be an object")
            phase = data.pop('_dandelion_phase', None)
            if phase not in (None, "stem") or set(data) != {"txid", "tx_data"}:
                raise ValueError("transaction envelope has an invalid wire schema")
            print(f"Received transaction from {peer.peer_id}: {data.get('txid', 'unknown')}"
                  f"{' [stem]' if phase == 'stem' else ''}")

            # Relaying unvalidated transactions amplifies malformed traffic.
            # The blockchain callback must explicitly accept the complete payload.
            if not self.on_new_transaction or not self.on_new_transaction(data):
                return

            # A stem-phase tx must continue down the Dandelion route from us
            # (forward to our stem peer, or fluff) rather than being flooded here.
            if phase == 'stem':
                self.dandelion_relay_transaction(data, from_peer_id=peer.peer_id)
            else:
                # A requested/full transaction is announced onward only after
                # local consensus acceptance, excluding the peer that supplied it.
                self.fluff_transaction(data, exclude_peer_id=peer.peer_id)

        except Exception as e:
            self.penalize_peer(peer, "malformed transaction message")
            print(f"Error handling tx: {e}")
    
    def handle_getblocks(self, peer: 'WepoPeer', payload: bytes):
        """Handle getblocks message"""
        try:
            data = json.loads(payload.decode())
            if not isinstance(data, dict) or set(data) != {
                "locator_hashes", "stop_hash", "limit"
            }:
                raise ValueError("getblocks has an invalid wire schema")
            locator_hashes = data["locator_hashes"]
            stop_hash = data["stop_hash"]
            limit = data["limit"]
            if (
                not isinstance(locator_hashes, list)
                or len(locator_hashes) > MAX_LOCATOR_HASHES
                or any(not _is_hash256(value) for value in locator_hashes)
                or (stop_hash is not None and not _is_hash256(stop_hash))
                or type(limit) is not int
                or not 1 <= limit <= 500
            ):
                raise ValueError("getblocks exceeds protocol limits")

            if not self.get_block_hashes_callback:
                return

            block_hashes = self.get_block_hashes_callback(locator_hashes, stop_hash=stop_hash, limit=limit)
            if not block_hashes:
                return

            inventory = [
                {'type': InventoryType.MSG_BLOCK, 'hash': block_hash}
                for block_hash in block_hashes
            ]
            peer.send_raw(self.create_inv_message(inventory))
        except Exception as e:
            print(f"Error handling getblocks: {e}")
            self.penalize_peer(peer, "malformed getblocks message")

    def handle_getheaders(self, peer: 'WepoPeer', payload: bytes):
        """Handle getheaders message"""
        try:
            data = json.loads(payload.decode())
            if not isinstance(data, dict) or set(data) != {
                "locator_hashes", "stop_hash", "limit"
            }:
                raise ValueError("getheaders has an invalid wire schema")
            locator_hashes = data["locator_hashes"]
            stop_hash = data["stop_hash"]
            limit = data["limit"]
            if (
                not isinstance(locator_hashes, list)
                or len(locator_hashes) > MAX_LOCATOR_HASHES
                or any(not _is_hash256(value) for value in locator_hashes)
                or (stop_hash is not None and not _is_hash256(stop_hash))
                or type(limit) is not int
                or not 1 <= limit <= MAX_HEADERS
            ):
                raise ValueError("getheaders exceeds protocol limits")

            if not self.get_headers_callback:
                return

            headers = self.get_headers_callback(locator_hashes, stop_hash=stop_hash, limit=limit)
            if headers is None:
                headers = []

            peer.send_raw(self.create_headers_message(headers))
        except Exception as e:
            print(f"Error handling getheaders: {e}")
            self.penalize_peer(peer, "malformed getheaders message")
    
    def create_addr_message(self, addresses: List[tuple]) -> bytes:
        """Create address message"""
        if not isinstance(addresses, list) or len(addresses) > MAX_ADDR_ITEMS:
            raise ValueError("address list exceeds protocol limits")
        addr_list = [{'ip': host, 'port': port} for host, port in addresses]
        payload = json.dumps(
            {'addresses': addr_list},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return self.create_message('addr', payload)
    
    def create_getdata_message(self, inventory: List[dict]) -> bytes:
        """Create getdata message"""
        if not isinstance(inventory, list) or len(inventory) > MAX_INVENTORY_ITEMS:
            raise ValueError("getdata inventory exceeds protocol limits")
        payload = json.dumps(
            {'inventory': inventory},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return self.create_message('getdata', payload)

    def create_getheaders_message(
        self,
        locator_hashes: List[str],
        stop_hash: Optional[str] = None,
        limit: int = 2000,
    ) -> bytes:
        """Create getheaders message with a block locator."""
        payload_data = {
            'locator_hashes': locator_hashes,
            'stop_hash': stop_hash,
            'limit': limit,
        }
        payload = json.dumps(payload_data).encode()
        return self.create_message('getheaders', payload)

    def create_getblocks_message(
        self,
        locator_hashes: List[str],
        stop_hash: Optional[str] = None,
        limit: int = 500,
    ) -> bytes:
        """Create getblocks message with a block locator."""
        payload_data = {
            'locator_hashes': locator_hashes,
            'stop_hash': stop_hash,
            'limit': limit,
        }
        payload = json.dumps(payload_data).encode()
        return self.create_message('getblocks', payload)

    def create_headers_message(self, headers: List[Dict[str, Any]]) -> bytes:
        """Create headers message carrying block header summaries."""
        if not isinstance(headers, list) or len(headers) > MAX_HEADERS:
            raise ValueError("headers exceeds protocol limits")
        payload = json.dumps(
            {'headers': headers},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return self.create_message('headers', payload)
    
    def create_block_message(self, block_data: dict) -> bytes:
        """Create block message"""
        payload = json.dumps(block_data).encode()
        return self.create_message('block', payload)

    def create_transaction_message(self, tx_data: dict) -> bytes:
        """Create a full transaction message for stem relay or getdata response."""
        payload = json.dumps(tx_data, sort_keys=True, separators=(",", ":")).encode()
        return self.create_message('tx', payload)

    def request_headers_sync(self, peer: 'WepoPeer'):
        """Request headers from a peer using the local locator, even for same-height forks."""
        try:
            if not peer.is_connected():
                return
            locator_hashes = self.get_locator_callback() if self.get_locator_callback else []
            if not locator_hashes:
                return
            peer.send_raw(self.create_getheaders_message(locator_hashes))
        except Exception as e:
            print(f"Error requesting headers sync from {peer.peer_id}: {e}")
    
    def get_network_info(self) -> dict:
        """Get network information"""
        self._prune_peer_policy()
        with self._peer_policy_lock:
            policy_metrics = {
                "misbehavior_events_total": self.misbehavior_events_total,
                "connection_failures_total": self.connection_failures_total,
                "banned_hosts_active": len(self.banned_until),
                "outbound_backoffs_active": len(self.connection_backoff),
            }
        return {
            'node_id': self.node_id,
            'version': PROTOCOL_VERSION,
            'peer_count': len(self.peers),
            'connected_peers': [peer.peer_id for peer in list(self.peers.values()) if peer.is_connected()],
            'known_addresses': len(self.known_addresses),
            'port': self.port,
            'operational': {
                'scope': 'process',
                'process_started_at': self.process_started_at,
                'uptime_seconds': max(
                    0, int(time.time()) - self.process_started_at
                ),
                **policy_metrics,
            },
        }

class WepoPeer:
    """Individual peer connection"""
    
    def __init__(self, socket: socket.socket, address: tuple, node: WepoP2PNode, incoming: bool = False):
        self.socket = socket
        self.address = address
        self.node = node
        self.incoming = incoming
        self.peer_id = f"{address[0]}:{address[1]}"
        
        # Peer state
        self.connected = True
        self.handshake_complete = False
        self.version_received = False
        self.version = 0
        self.services = 0
        self.user_agent = ""
        self.start_height = 0
        self.last_ping = time.time()
        self.last_pong = time.time()
        self.pending_ping_nonce: Optional[int] = None
        self.pending_ping_sent_at: Optional[float] = None
        self.connected_at = time.monotonic()
        self.partial_message_started_at: Optional[float] = None
        
        # Message buffer
        self.receive_buffer = b''
        
        print(f"New peer connection: {self.peer_id} ({'incoming' if incoming else 'outgoing'})")
    
    def start(self):
        """Start peer communication"""
        # Add to node's peer list
        self.node.peers[self.peer_id] = self
        
        # Both sides must put version on the wire before a receive thread can
        # answer the remote version with verack. Starting the receiver first
        # creates a race where verack can overtake our version on this socket.
        self.send_version()

        # Start receive processing only after the ordered version send.
        threading.Thread(target=self.receive_loop, daemon=True).start()
    
    def send_raw(self, data: bytes):
        """Send raw data to peer"""
        try:
            if self.connected:
                self.socket.sendall(data)
        except Exception as e:
            print(f"Error sending to {self.peer_id}: {e}")
            self.disconnect()
    
    def send_version(self):
        """Send version message"""
        version_msg = self.node.create_version_message()
        self.send_raw(version_msg)
    
    def send_verack(self):
        """Send version acknowledgment"""
        verack_msg = self.node.create_message('verack')
        self.send_raw(verack_msg)
    
    def send_ping(self):
        """Send ping message"""
        if self.pending_ping_nonce is not None:
            return
        nonce = random.randint(0, 2**32 - 1)
        payload_data = {'nonce': nonce}
        payload = json.dumps(payload_data).encode()
        ping_msg = self.node.create_message('ping', payload)
        self.pending_ping_nonce = nonce
        self.pending_ping_sent_at = time.monotonic()
        self.send_raw(ping_msg)
        self.last_ping = time.time()
    
    def send_pong(self, nonce: int):
        """Send pong message"""
        payload_data = {'nonce': nonce}
        payload = json.dumps(payload_data).encode()
        pong_msg = self.node.create_message('pong', payload)
        self.send_raw(pong_msg)
    
    def send_getaddr(self):
        """Send getaddr message"""
        getaddr_msg = self.node.create_message('getaddr')
        self.send_raw(getaddr_msg)

    def enforce_connection_deadlines(self, now: Optional[float] = None) -> bool:
        """Disconnect peers that hold a slot without completing protocol work."""
        now = time.monotonic() if now is None else now
        if (
            not self.handshake_complete
            and now - self.connected_at > HANDSHAKE_TIMEOUT_SECONDS
        ):
            print(f"Handshake timeout for {self.peer_id}")
            self.receive_buffer = b''
            self.partial_message_started_at = None
            self.node.penalize_peer(self, "handshake timeout")
            return False
        if (
            self.receive_buffer
            and self.partial_message_started_at is not None
            and now - self.partial_message_started_at
            > PARTIAL_MESSAGE_TIMEOUT_SECONDS
        ):
            print(f"Partial message timeout for {self.peer_id}")
            self.receive_buffer = b''
            self.partial_message_started_at = None
            self.node.penalize_peer(self, "partial message timeout")
            return False
        if (
            self.pending_ping_sent_at is not None
            and now - self.pending_ping_sent_at > CONNECTION_TIMEOUT
        ):
            print(f"Ping timeout for {self.peer_id}")
            self.node.penalize_peer(self, "ping timeout")
            return False
        return self.connected
    
    def receive_loop(self):
        """Main receive loop"""
        while self.connected:
            try:
                if not self.enforce_connection_deadlines():
                    break
                # Set socket timeout
                self.socket.settimeout(1.0)
                data = self.socket.recv(4096)
                
                if not data:
                    break
                
                if not self.receive_buffer:
                    self.partial_message_started_at = time.monotonic()
                self.receive_buffer += data
                
                # Process complete messages
                self.process_messages()

                if not self.enforce_connection_deadlines():
                    break
                
            except socket.timeout:
                if not self.enforce_connection_deadlines():
                    break
                continue
            except Exception as e:
                print(f"Receive error from {self.peer_id}: {e}")
                break
        
        self.disconnect()
    
    def process_messages(self):
        """Process messages from receive buffer"""
        while len(self.receive_buffer) >= 24:  # Minimum header size
            try:
                magic, _, declared_length, _ = struct.unpack(
                    '<4s12sI4s', self.receive_buffer[:24]
                )
            except struct.error:
                return

            # Reject the peer as soon as a complete header declares invalid
            # framing. Waiting for the advertised body would otherwise let the
            # receive buffer grow without bound.
            if magic != self.node.network_magic:
                print(f"Disconnecting {self.peer_id}: invalid network magic")
                self.receive_buffer = b''
                self.node.penalize_peer(self, "invalid network magic")
                return
            if declared_length > MAX_MESSAGE_SIZE:
                print(
                    f"Disconnecting {self.peer_id}: declared message size "
                    f"{declared_length} exceeds {MAX_MESSAGE_SIZE}"
                )
                self.receive_buffer = b''
                self.node.penalize_peer(self, "oversized message declaration")
                return
            if len(self.receive_buffer) < 24 + declared_length:
                return

            # Try to parse message
            message = self.node.parse_message(self.receive_buffer)
            if not message:
                self.receive_buffer = b''
                self.node.penalize_peer(self, "invalid message checksum or framing")
                return
            
            # Remove processed data from buffer
            message_size = 24 + message.length
            self.receive_buffer = self.receive_buffer[message_size:]
            self.partial_message_started_at = (
                time.monotonic() if self.receive_buffer else None
            )
            
            if not self.handshake_complete and message.command not in {
                'version',
                'verack',
            }:
                print(
                    f"Disconnecting {self.peer_id}: {message.command} before handshake"
                )
                self.receive_buffer = b''
                self.node.penalize_peer(self, "application message before handshake")
                return
            if self.handshake_complete and message.command in {'version', 'verack'}:
                print(f"Disconnecting {self.peer_id}: duplicate handshake message")
                self.receive_buffer = b''
                self.node.penalize_peer(self, "duplicate handshake message")
                return

            # Handle message
            handler = self.node.message_handlers.get(message.command)
            if handler:
                try:
                    handler(self, message.payload)
                except Exception as e:
                    print(f"Error handling {message.command} from {self.peer_id}: {e}")
                if not self.connected:
                    # A handler may penalize and disconnect the peer. Never
                    # consume frames that were pipelined behind the violation.
                    self.receive_buffer = b''
                    self.partial_message_started_at = None
                    return
            else:
                print(f"Unknown message type: {message.command}")
                self.node.penalize_peer(self, "unknown message command")
                self.receive_buffer = b''
                self.partial_message_started_at = None
                return
    
    def is_connected(self) -> bool:
        """Check if peer is connected"""
        return self.connected and self.handshake_complete
    
    def disconnect(self):
        """Disconnect from peer"""
        if self.connected:
            print(f"Disconnecting from {self.peer_id}")
            self.connected = False
            try:
                self.socket.close()
            except:
                pass
        if self.node.peers.get(self.peer_id) is self:
            self.node.peers.pop(self.peer_id, None)


def main():
    """Test the P2P network"""
    print("=== WEPO P2P Network Test ===")
    
    # Create P2P node
    node = WepoP2PNode()
    
    try:
        # Start server
        node.start_server()
        
        # Wait for connections
        print("P2P node running... Press Ctrl+C to stop")
        while True:
            time.sleep(1)
            
            # Print network info every 30 seconds
            if int(time.time()) % 30 == 0:
                info = node.get_network_info()
                print(f"\nNetwork Info: {info}")
    
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        node.stop_server()

if __name__ == "__main__":
    main()
