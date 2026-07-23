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
NETWORK_MAGIC = b'WEPO'
PROTOCOL_VERSION = 70001
DEFAULT_PORT = 22567
MAX_PEERS = 8
CONNECTION_TIMEOUT = 30
PING_INTERVAL = 60
MAX_MESSAGE_SIZE = 32 * 1024 * 1024  # 32MB

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
        self.node_id = hashlib.sha256(f"{host}:{port}:{time.time()}".encode()).hexdigest()[:16]
        
        # Network state
        self.peers: Dict[str, 'WepoPeer'] = {}
        self.known_addresses: Set[tuple] = set()
        self.running = False
        self.server_socket: Optional[socket.socket] = None
        
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
    
    def create_message(self, command: str, payload: bytes = b'') -> bytes:
        """Create a P2P protocol message"""
        # Calculate checksum
        checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        
        # Create header
        header = struct.pack('<4s12sI4s', 
                           NETWORK_MAGIC,
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
            
            if magic != NETWORK_MAGIC:
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
            'relay': True
        }
        
        payload = json.dumps(payload_data).encode()
        return self.create_message('version', payload)
    
    def start_server(self):
        """Start P2P server"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(MAX_PEERS)
            self.running = True
            
            print(f"P2P server started on {self.host}:{self.port}")
            
            # Start accepting connections
            threading.Thread(target=self.accept_connections, daemon=True).start()
            
            # Start periodic tasks
            threading.Thread(target=self.periodic_tasks, daemon=True).start()
            
        except Exception as e:
            print(f"Failed to start P2P server: {e}")
            self.running = False
    
    def stop_server(self):
        """Stop P2P server"""
        print("Stopping P2P server...")
        self.running = False
        
        # Close all peer connections
        for peer in list(self.peers.values()):
            peer.disconnect()
        
        # Close server socket
        if self.server_socket:
            self.server_socket.close()
        
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
        if len(self.peers) >= MAX_PEERS:
            return False

        if self._is_self_endpoint(host, port):
            return False
        
        peer_id = f"{host}:{port}"
        if peer_id in self.peers:
            return False
        
        try:
            if self.socks5_proxy:
                # Route outbound P2P through the SOCKS5 proxy (e.g. Tor).
                sock = self._socks5_connect(self.socks5_proxy, host, port)
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(CONNECTION_TIMEOUT)
                sock.connect((host, port))

            peer = WepoPeer(sock, (host, port), self, incoming=False)
            peer.start()
            return True
            
        except Exception as e:
            print(f"Failed to connect to {host}:{port}: {e}")
            return False
    
    def discover_peers(self):
        """Discover peers through DNS seeds and existing connections"""
        print("Discovering peers...")
        
        if not self.static_seed_addresses and not self.dns_seeds:
            print("No P2P seed peers configured; set WEPO_STATIC_PEERS or WEPO_DNS_SEEDS to bootstrap peers.")

        for host, port in self.static_seed_addresses:
            if len(self.peers) < MAX_PEERS:
                self.connect_to_peer(host, port)

        # Request addresses from existing peers
        for peer in self.peers.values():
            if peer.is_connected():
                peer.send_getaddr()
    
    def periodic_tasks(self):
        """Periodic maintenance tasks"""
        while self.running:
            try:
                # Clean up disconnected peers
                disconnected = [peer_id for peer_id, peer in self.peers.items() 
                              if not peer.is_connected()]
                for peer_id in disconnected:
                    del self.peers[peer_id]
                
                # Send pings to peers
                for peer in self.peers.values():
                    if peer.is_connected():
                        peer.send_ping()
                
                # Try to maintain connections
                if len(self.peers) < MAX_PEERS // 2:
                    self.discover_peers()

                # Dandelion++ failsafe: fluff any stem tx whose embargo expired.
                self.process_embargoes()

                time.sleep(PING_INTERVAL)
                
            except Exception as e:
                print(f"Error in periodic tasks: {e}")
    
    def broadcast_to_peers(self, message: bytes):
        """Broadcast message to all connected peers"""
        for peer in self.peers.values():
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

    def fluff_transaction(self, tx_data: dict):
        """Fluff phase: announce via inventory to all peers (normal flood)."""
        inv_msg = self.create_inv_message([{
            'type': InventoryType.MSG_TX,
            'hash': tx_data.get('txid', '')
        }])
        self.broadcast_to_peers(inv_msg)

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
        sock.settimeout(CONNECTION_TIMEOUT)
        sock.connect((proxy_host, proxy_port))
        try:
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
        payload_data = {
            'count': len(inventory),
            'inventory': inventory
        }
        payload = json.dumps(payload_data).encode()
        return self.create_message('inv', payload)
    
    # Message handlers
    def handle_version(self, peer: 'WepoPeer', payload: bytes):
        """Handle version message"""
        try:
            data = json.loads(payload.decode())
            peer.version = data.get('version', 0)
            peer.services = data.get('services', 0)
            peer.user_agent = data.get('user_agent', '')
            peer.start_height = data.get('start_height', 0)
            
            print(f"Received version from {peer.peer_id}: {peer.user_agent}")
            
            # Send verack
            peer.send_verack()
            
        except Exception as e:
            print(f"Error handling version: {e}")
    
    def handle_verack(self, peer: 'WepoPeer', payload: bytes):
        """Handle version acknowledgment"""
        peer.handshake_complete = True
        print(f"Handshake complete with {peer.peer_id}")
        self.request_headers_sync(peer)
    
    def handle_ping(self, peer: 'WepoPeer', payload: bytes):
        """Handle ping message"""
        try:
            data = json.loads(payload.decode()) if payload else {}
            nonce = data.get('nonce', 0)
            peer.send_pong(nonce)
        except Exception as e:
            print(f"Error handling ping: {e}")
    
    def handle_pong(self, peer: 'WepoPeer', payload: bytes):
        """Handle pong message"""
        peer.last_pong = time.time()
    
    def handle_getaddr(self, peer: 'WepoPeer', payload: bytes):
        """Handle address request"""
        # Send known addresses
        addresses = list(self.known_addresses)[:1000]  # Limit to 1000
        addr_msg = self.create_addr_message(addresses)
        peer.send_raw(addr_msg)
    
    def handle_addr(self, peer: 'WepoPeer', payload: bytes):
        """Handle address message"""
        try:
            data = json.loads(payload.decode())
            addresses = data.get('addresses', [])
            
            for addr in addresses:
                host = addr.get('ip', '')
                port = addr.get('port', 0)
                if host and port:
                    self.known_addresses.add((host, port))
            
            print(f"Received {len(addresses)} addresses from {peer.peer_id}")
            
        except Exception as e:
            print(f"Error handling addr: {e}")
    
    def handle_inv(self, peer: 'WepoPeer', payload: bytes):
        """Handle inventory message"""
        try:
            data = json.loads(payload.decode())
            inventory = data.get('inventory', [])
            
            # Request data for items we don't have
            getdata_items = []
            for item in inventory:
                item_type = item.get('type')
                
                if item_type == InventoryType.MSG_BLOCK:
                    # Check if we have this block
                    getdata_items.append(item)
                elif item_type == InventoryType.MSG_TX:
                    # Check if we have this transaction
                    getdata_items.append(item)
            
            if getdata_items:
                getdata_msg = self.create_getdata_message(getdata_items)
                peer.send_raw(getdata_msg)
                
        except Exception as e:
            print(f"Error handling inv: {e}")
    
    def handle_getdata(self, peer: 'WepoPeer', payload: bytes):
        """Handle getdata message"""
        try:
            data = json.loads(payload.decode())
            inventory = data.get('inventory', [])
            
            for item in inventory:
                item_type = item.get('type')
                item_hash = item.get('hash')
                
                if item_type == InventoryType.MSG_BLOCK and self.get_block_callback:
                    block_data = self.get_block_callback(item_hash)
                    if block_data:
                        block_msg = self.create_block_message(block_data)
                        peer.send_raw(block_msg)
                        
                elif item_type == InventoryType.MSG_TX:
                    # TODO: Get transaction data
                    pass
                    
        except Exception as e:
            print(f"Error handling getdata: {e}")
    
    def handle_block(self, peer: 'WepoPeer', payload: bytes):
        """Handle block message"""
        try:
            data = json.loads(payload.decode())
            print(f"Received block from {peer.peer_id}: {data.get('hash', 'unknown')}")
            
            if self.on_new_block:
                self.on_new_block(data)
                
        except Exception as e:
            print(f"Error handling block: {e}")

    def handle_headers(self, peer: 'WepoPeer', payload: bytes):
        """Handle headers message by requesting the blocks we are missing."""
        try:
            data = json.loads(payload.decode())
            headers = data.get('headers', [])
            if not headers:
                return

            missing_inventory = []
            for header in headers:
                block_hash = header.get('hash')
                if not block_hash:
                    continue
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
    
    def handle_tx(self, peer: 'WepoPeer', payload: bytes):
        """Handle transaction message (including Dandelion++ stem relays)."""
        try:
            data = json.loads(payload.decode())
            phase = data.pop('_dandelion_phase', None)
            print(f"Received transaction from {peer.peer_id}: {data.get('txid', 'unknown')}"
                  f"{' [stem]' if phase == 'stem' else ''}")

            if self.on_new_transaction:
                self.on_new_transaction(data)

            # A stem-phase tx must continue down the Dandelion route from us
            # (forward to our stem peer, or fluff) rather than being flooded here.
            if phase == 'stem':
                self.dandelion_relay_transaction(data, from_peer_id=peer.peer_id)

        except Exception as e:
            print(f"Error handling tx: {e}")
    
    def handle_getblocks(self, peer: 'WepoPeer', payload: bytes):
        """Handle getblocks message"""
        try:
            data = json.loads(payload.decode()) if payload else {}
            locator_hashes = data.get('locator_hashes', [])
            stop_hash = data.get('stop_hash')
            limit = data.get('limit', 500)

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
    
    def handle_getheaders(self, peer: 'WepoPeer', payload: bytes):
        """Handle getheaders message"""
        try:
            data = json.loads(payload.decode()) if payload else {}
            locator_hashes = data.get('locator_hashes', [])
            stop_hash = data.get('stop_hash')
            limit = data.get('limit', 2000)

            if not self.get_headers_callback:
                return

            headers = self.get_headers_callback(locator_hashes, stop_hash=stop_hash, limit=limit)
            if headers is None:
                headers = []

            peer.send_raw(self.create_headers_message(headers))
        except Exception as e:
            print(f"Error handling getheaders: {e}")
    
    def create_addr_message(self, addresses: List[tuple]) -> bytes:
        """Create address message"""
        addr_list = []
        for host, port in addresses:
            addr_list.append({
                'time': int(time.time()),
                'services': 1,
                'ip': host,
                'port': port
            })
        
        payload_data = {
            'count': len(addr_list),
            'addresses': addr_list
        }
        payload = json.dumps(payload_data).encode()
        return self.create_message('addr', payload)
    
    def create_getdata_message(self, inventory: List[dict]) -> bytes:
        """Create getdata message"""
        payload_data = {
            'count': len(inventory),
            'inventory': inventory
        }
        payload = json.dumps(payload_data).encode()
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
        payload_data = {
            'count': len(headers),
            'headers': headers,
        }
        payload = json.dumps(payload_data).encode()
        return self.create_message('headers', payload)
    
    def create_block_message(self, block_data: dict) -> bytes:
        """Create block message"""
        payload = json.dumps(block_data).encode()
        return self.create_message('block', payload)

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
        return {
            'node_id': self.node_id,
            'version': PROTOCOL_VERSION,
            'peer_count': len(self.peers),
            'connected_peers': [peer.peer_id for peer in self.peers.values() if peer.is_connected()],
            'known_addresses': len(self.known_addresses),
            'port': self.port
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
        self.version = 0
        self.services = 0
        self.user_agent = ""
        self.start_height = 0
        self.last_ping = time.time()
        self.last_pong = time.time()
        
        # Message buffer
        self.receive_buffer = b''
        
        print(f"New peer connection: {self.peer_id} ({'incoming' if incoming else 'outgoing'})")
    
    def start(self):
        """Start peer communication"""
        # Add to node's peer list
        self.node.peers[self.peer_id] = self
        
        # Start receive thread
        threading.Thread(target=self.receive_loop, daemon=True).start()

        # Both sides of the connection must advertise version so the handshake can complete.
        self.send_version()
    
    def send_raw(self, data: bytes):
        """Send raw data to peer"""
        try:
            if self.connected:
                self.socket.send(data)
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
        nonce = random.randint(0, 2**32 - 1)
        payload_data = {'nonce': nonce}
        payload = json.dumps(payload_data).encode()
        ping_msg = self.node.create_message('ping', payload)
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
    
    def receive_loop(self):
        """Main receive loop"""
        while self.connected:
            try:
                # Set socket timeout
                self.socket.settimeout(1.0)
                data = self.socket.recv(4096)
                
                if not data:
                    break
                
                self.receive_buffer += data
                
                # Process complete messages
                self.process_messages()
                
            except socket.timeout:
                # Check for ping timeout
                if time.time() - self.last_pong > CONNECTION_TIMEOUT * 2:
                    print(f"Ping timeout for {self.peer_id}")
                    break
                continue
            except Exception as e:
                print(f"Receive error from {self.peer_id}: {e}")
                break
        
        self.disconnect()
    
    def process_messages(self):
        """Process messages from receive buffer"""
        while len(self.receive_buffer) >= 24:  # Minimum header size
            # Try to parse message
            message = self.node.parse_message(self.receive_buffer)
            if not message:
                break
            
            # Remove processed data from buffer
            message_size = 24 + message.length
            self.receive_buffer = self.receive_buffer[message_size:]
            
            # Handle message
            handler = self.node.message_handlers.get(message.command)
            if handler:
                try:
                    handler(self, message.payload)
                except Exception as e:
                    print(f"Error handling {message.command} from {self.peer_id}: {e}")
            else:
                print(f"Unknown message type: {message.command}")
    
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
