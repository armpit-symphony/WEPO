#!/usr/bin/env python3
"""
WEPO Core Blockchain Implementation
Revolutionary cryptocurrency with hybrid PoW/PoS consensus and privacy features
"""
try:
    from .dilithium import dilithium_system
    from .quantum_transaction import QuantumTransaction
except ImportError:
    # Fallback for direct execution
    from dilithium import dilithium_system
    from quantum_transaction import QuantumTransaction


import hashlib
import json
import time
import struct
import socket
import threading
from typing import List, Dict, Optional, Union
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import secrets
import argon2
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
import sqlite3
import os
try:
    from .address_utils import generate_wepo_address, validate_wepo_address, is_quantum_address, is_regular_address
except ImportError:
    from address_utils import generate_wepo_address, validate_wepo_address, is_quantum_address, is_regular_address
try:
    from .network_profile import (
        format_block_time,
        MAINNET_GENESIS_TIMESTAMP as PROFILE_MAINNET_GENESIS_TIMESTAMP,
        PRE_POS_REWARD as PROFILE_PRE_POS_REWARD,
        PHASE_2A_REWARD as PROFILE_PHASE_2A_REWARD,
        PHASE_2B_REWARD as PROFILE_PHASE_2B_REWARD,
        PHASE_2C_REWARD as PROFILE_PHASE_2C_REWARD,
        PHASE_2D_REWARD as PROFILE_PHASE_2D_REWARD,
        get_network_profile,
    )
except ImportError:
    from network_profile import (
        format_block_time,
        MAINNET_GENESIS_TIMESTAMP as PROFILE_MAINNET_GENESIS_TIMESTAMP,
        PRE_POS_REWARD as PROFILE_PRE_POS_REWARD,
        PHASE_2A_REWARD as PROFILE_PHASE_2A_REWARD,
        PHASE_2B_REWARD as PROFILE_PHASE_2B_REWARD,
        PHASE_2C_REWARD as PROFILE_PHASE_2C_REWARD,
        PHASE_2D_REWARD as PROFILE_PHASE_2D_REWARD,
        get_network_profile,
    )

# WEPO Network Constants
WEPO_VERSION = 70001
NETWORK_MAGIC = b'WEPO'
DEFAULT_PORT = 22567
COIN = 100000000  # 1 WEPO = 100,000,000 satoshis
MAX_BLOCK_SIZE = 2 * 1024 * 1024  # 2MB
MAX_FUTURE_BLOCK_TIME_DRIFT = 2 * 60 * 60  # 2 hours

# WEPO 20-YEAR MINING SCHEDULE - SUSTAINABLE LONG-TERM POW
# Genesis timing is controlled by the configured mainnet timestamp.
GENESIS_TIME = PROFILE_MAINNET_GENESIS_TIMESTAMP  # configured genesis timestamp

# Total Supply - DEFINITIVE VALUE
TOTAL_SUPPLY = 69000003  # 69,000,003 WEPO total supply

# Block Time Configuration
BLOCK_TIME_TARGET = BLOCK_TIME_INITIAL_18_MONTHS = 360  # 6 minutes per block (first 18 months)
BLOCK_TIME_YEAR1 = BLOCK_TIME_INITIAL_18_MONTHS  # For backward compatibility
BLOCK_TIME_LONGTERM = 540           # 9 minutes per block (post-18 months)

# HYBRID PoW/PoS BLOCK TIMING (after PoS activation)
BLOCK_TIME_POS = 180               # 3 minutes per PoS block
BLOCK_TIME_POW_HYBRID = 540        # 9 minutes per PoW block (in hybrid mode)

# PHASE 1: Pre-PoS Mining (Months 1-18) - 10% of total supply
PRE_POS_DURATION_BLOCKS = 131400    # 18 months in 6-minute blocks
PRE_POS_REWARD = PROFILE_PRE_POS_REWARD  # 52.51 WEPO per block
PRE_POS_TOTAL_SUPPLY = 6900000 * COIN  # 6.9M WEPO (10% of total)

# Long-term PoW phases (alongside PoS/Masternodes) - 20% of total supply
BLOCKS_PER_YEAR_LONGTERM = int(365.25 * 24 * 60 / 9)  # 58,400 blocks per year (9-min blocks)

# PHASE 2A: Post-PoS Years 1-3 (Months 19-54)
PHASE_2A_BLOCKS = 3 * BLOCKS_PER_YEAR_LONGTERM  # 175,200 blocks
PHASE_2A_REWARD = PROFILE_PHASE_2A_REWARD  # 33.17 WEPO per block
PHASE_2A_END_HEIGHT = PRE_POS_DURATION_BLOCKS + PHASE_2A_BLOCKS

# PHASE 2B: Post-PoS Years 4-9 (Months 55-126) - First Halving
PHASE_2B_BLOCKS = 6 * BLOCKS_PER_YEAR_LONGTERM  # 350,400 blocks
PHASE_2B_REWARD = PROFILE_PHASE_2B_REWARD  # 16.58 WEPO per block (halved)
PHASE_2B_END_HEIGHT = PHASE_2A_END_HEIGHT + PHASE_2B_BLOCKS

# PHASE 2C: Post-PoS Years 10-12 (Months 127-162) - Second Halving
PHASE_2C_BLOCKS = 3 * BLOCKS_PER_YEAR_LONGTERM  # 175,200 blocks
PHASE_2C_REWARD = PROFILE_PHASE_2C_REWARD  # 8.29 WEPO per block (halved)
PHASE_2C_END_HEIGHT = PHASE_2B_END_HEIGHT + PHASE_2C_BLOCKS

# PHASE 2D: Post-PoS Years 13-15 (Months 163-198) - Final Halving
PHASE_2D_BLOCKS = 3 * BLOCKS_PER_YEAR_LONGTERM  # 175,200 blocks
PHASE_2D_REWARD = PROFILE_PHASE_2D_REWARD  # 4.15 WEPO per block (final halving)
PHASE_2D_END_HEIGHT = PHASE_2C_END_HEIGHT + PHASE_2D_BLOCKS

# Total PoW ends at block 1,007,400 (16.5 years after PoS activation)
POW_END_HEIGHT = PHASE_2D_END_HEIGHT

# Total mining allocation: 20,702,037 WEPO over 198 months (30% of total supply)
TOTAL_POW_SUPPLY = 20702037 * COIN

# Explicit genesis bootstrap allocation
GENESIS_BOOTSTRAP_REWARD = 400 * COIN

# Legacy constants - kept for backward compatibility
TOTAL_INITIAL_BLOCKS = PRE_POS_DURATION_BLOCKS  # For PoS activation timing
POW_BLOCKS_YEAR1 = 52560      # OLD: 10-min blocks for 1 year (not used in new schedule)
REWARD_Q1 = GENESIS_BOOTSTRAP_REWARD  # Legacy alias for genesis bootstrap allocation
REWARD_Q2 = 200 * COIN        # OLD: 200 WEPO per block Q2 (not used in new schedule)
REWARD_Q3 = 100 * COIN        # OLD: 100 WEPO per block Q3 (not used in new schedule)
REWARD_Q4 = 50 * COIN         # OLD: 50 WEPO per block Q4 (not used in new schedule)
REWARD_YEAR2_BASE = 12.4 * COIN # OLD: 12.4 WEPO per block year 2+ (not used in new schedule)
HALVING_INTERVAL = 1051200    # OLD: Blocks between halvings (not used in new schedule)

# NETWORK PROFILE CONFIGURATION
MAINNET_GENESIS_TIMESTAMP = PROFILE_MAINNET_GENESIS_TIMESTAMP
STAKING_ACTIVATION_DELAY = 18 * 30 * 24 * 60 * 60
PRODUCTION_MODE = False
NETWORK_PROFILE_NAME = "mainnet"
NETWORK_NAME = "mainnet"
MIN_STAKE_AMOUNT = 1000 * COIN
DYNAMIC_MASTERNODE_COLLATERAL_SCHEDULE = {}
DYNAMIC_POS_COLLATERAL_SCHEDULE = {}
MIN_MASTERNODE_COLLATERAL = 1000 * COIN
MIN_POS_COLLATERAL = 100 * COIN
MASTERNODE_COLLATERAL = 10000 * COIN
POS_ACTIVATION_HEIGHT = TOTAL_INITIAL_BLOCKS


def apply_network_profile(profile_name: str = "mainnet") -> None:
    """Apply a shared chain profile to module-level schedule constants."""
    global BLOCK_TIME_TARGET, BLOCK_TIME_INITIAL_18_MONTHS, BLOCK_TIME_YEAR1
    global BLOCK_TIME_LONGTERM, BLOCK_TIME_POS, BLOCK_TIME_POW_HYBRID
    global PRE_POS_DURATION_BLOCKS, TOTAL_INITIAL_BLOCKS, POS_ACTIVATION_HEIGHT
    global BLOCKS_PER_YEAR_LONGTERM, PHASE_2A_BLOCKS, PHASE_2A_END_HEIGHT
    global PHASE_2B_BLOCKS, PHASE_2B_END_HEIGHT, PHASE_2C_BLOCKS, PHASE_2C_END_HEIGHT
    global PHASE_2D_BLOCKS, PHASE_2D_END_HEIGHT, POW_END_HEIGHT
    global MAINNET_GENESIS_TIMESTAMP, GENESIS_TIME, STAKING_ACTIVATION_DELAY
    global MIN_STAKE_AMOUNT, MIN_MASTERNODE_COLLATERAL, MIN_POS_COLLATERAL
    global DYNAMIC_MASTERNODE_COLLATERAL_SCHEDULE, DYNAMIC_POS_COLLATERAL_SCHEDULE
    global MASTERNODE_COLLATERAL, NETWORK_PROFILE_NAME, NETWORK_NAME

    profile = get_network_profile(profile_name)
    NETWORK_PROFILE_NAME = profile.name
    NETWORK_NAME = profile.network_label

    BLOCK_TIME_TARGET = BLOCK_TIME_INITIAL_18_MONTHS = profile.block_time_initial
    BLOCK_TIME_YEAR1 = BLOCK_TIME_INITIAL_18_MONTHS
    BLOCK_TIME_LONGTERM = profile.block_time_longterm
    BLOCK_TIME_POS = profile.block_time_pos
    BLOCK_TIME_POW_HYBRID = profile.block_time_pow_hybrid
    PRE_POS_DURATION_BLOCKS = profile.pre_pos_duration_blocks
    TOTAL_INITIAL_BLOCKS = profile.total_initial_blocks
    POS_ACTIVATION_HEIGHT = profile.pos_activation_height
    BLOCKS_PER_YEAR_LONGTERM = max(1, profile.phase_2b_blocks)
    PHASE_2A_BLOCKS = profile.phase_2a_blocks
    PHASE_2A_END_HEIGHT = profile.phase_2a_end_height
    PHASE_2B_BLOCKS = profile.phase_2b_blocks
    PHASE_2B_END_HEIGHT = profile.phase_2b_end_height
    PHASE_2C_BLOCKS = profile.phase_2c_blocks
    PHASE_2C_END_HEIGHT = profile.phase_2c_end_height
    PHASE_2D_BLOCKS = profile.phase_2d_blocks
    PHASE_2D_END_HEIGHT = profile.phase_2d_end_height
    POW_END_HEIGHT = profile.pow_end_height
    MAINNET_GENESIS_TIMESTAMP = profile.genesis_timestamp
    GENESIS_TIME = profile.genesis_timestamp
    STAKING_ACTIVATION_DELAY = profile.staking_activation_delay
    MIN_STAKE_AMOUNT = profile.min_stake_amount
    MIN_MASTERNODE_COLLATERAL = profile.min_masternode_collateral
    MIN_POS_COLLATERAL = profile.min_pos_collateral
    DYNAMIC_MASTERNODE_COLLATERAL_SCHEDULE = profile.masternode_schedule
    DYNAMIC_POS_COLLATERAL_SCHEDULE = profile.pos_schedule
    MASTERNODE_COLLATERAL = profile.masternode_collateral_initial

    if profile.name == "test":
        print(
            f"🧪 TEST MODE CONFIGURED: PoS activates at block {POS_ACTIVATION_HEIGHT} "
            f"on accelerated '{NETWORK_NAME}' profile"
        )
    else:
        print(f"MAINNET CONFIGURED: Staking activates at block {POS_ACTIVATION_HEIGHT} (18 months post-genesis)")
        print("🔄 PoW CONTINUES: Mining continues for 198 months total alongside PoS/Masternodes")


apply_network_profile(os.getenv("WEPO_NETWORK_PROFILE", "mainnet"))

@dataclass
class StakeInfo:
    """Staking information"""
    stake_id: str
    staker_address: str
    amount: int  # In satoshis
    start_height: int
    start_time: int
    last_reward_height: int = 0
    total_rewards: int = 0
    status: str = 'active'
    unlock_height: Optional[int] = None

@dataclass
class MasternodeInfo:
    """Masternode information"""
    masternode_id: str
    operator_address: str
    collateral_txid: str
    collateral_vout: int
    ip_address: Optional[str] = None
    port: int = 22567
    start_height: int = 0
    start_time: int = 0
    last_ping: int = 0
    status: str = 'active'
    total_rewards: int = 0

@dataclass
class TransactionInput:
    """Transaction input with support for both ECDSA and Dilithium signatures"""
    prev_txid: str
    prev_vout: int
    script_sig: Optional[bytes] = None
    sequence: int = 0xffffffff
    
    # Quantum signature support
    quantum_signature: Optional[bytes] = None
    quantum_public_key: Optional[bytes] = None
    signature_type: str = "ecdsa"  # "ecdsa" or "dilithium"
    
    def __post_init__(self):
        # Validate quantum signature sizes if present
        if self.quantum_signature and len(self.quantum_signature) != 2420:
            raise ValueError(f"Invalid Dilithium signature size: {len(self.quantum_signature)}")
        
        if self.quantum_public_key and len(self.quantum_public_key) != 1312:
            raise ValueError(f"Invalid Dilithium public key size: {len(self.quantum_public_key)}")

@dataclass
class TransactionOutput:
    """Transaction output with quantum address support"""
    value: int
    script_pubkey: Optional[bytes] = None
    address: str = ""
    
    def __post_init__(self):
        # Validate address format (supports both regular and quantum addresses)
        if not self.is_valid_address():
            raise ValueError(f"Invalid address format: {self.address}")
    
    def is_valid_address(self):
        """Validate address using standardized system"""
        validation = validate_wepo_address(self.address)
        return validation["valid"]
    
    def get_address_type(self):
        """Get address type using standardized system"""
        validation = validate_wepo_address(self.address)
        return validation["type"] if validation["valid"] else None
        
    def is_quantum_resistant(self):
        """Check if address is quantum-resistant"""
        return is_quantum_address(self.address)

@dataclass
class Transaction:
    """WEPO Transaction with privacy features and quantum signature support"""
    version: int
    inputs: List[TransactionInput]
    outputs: List[TransactionOutput]
    lock_time: int
    fee: int = 0
    privacy_proof: Optional[bytes] = None
    ring_signature: Optional[bytes] = None
    timestamp: int = 0
    
    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = int(time.time())
    
    def has_quantum_signatures(self) -> bool:
        """Check if transaction contains quantum signatures"""
        return any(inp.signature_type == "dilithium" for inp in self.inputs)
    
    def is_mixed_signature_transaction(self) -> bool:
        """Check if transaction has mixed signature types"""
        signature_types = set(inp.signature_type for inp in self.inputs)
        return len(signature_types) > 1
    
    def verify_quantum_signature(self, input_index: int) -> bool:
        """Verify quantum signature for specific input"""
        if input_index >= len(self.inputs):
            return False
        
        inp = self.inputs[input_index]
        
        if inp.signature_type != "dilithium":
            return False
        
        if not inp.quantum_signature or not inp.quantum_public_key:
            return False
        
        try:
            # Import quantum signature verification
            from dilithium import verify_signature
            
            # Create signing message
            signing_message = self.get_signing_message_for_input(input_index)
            
            # Verify quantum signature
            return verify_signature(signing_message, inp.quantum_signature, inp.quantum_public_key)
        except Exception as e:
            print(f"Quantum signature verification failed: {e}")
            return False
    
    def get_signing_message_for_input(self, input_index: int) -> bytes:
        """Get message to be signed for specific input"""
        # Create deterministic message for signing
        message_parts = [
            str(self.version),
            str(self.lock_time),
            str(self.fee),
            str(input_index)
        ]
        
        # Add outputs
        for out in self.outputs:
            message_parts.extend([str(out.value), out.address])
        
        # Add other inputs (without signatures)
        for i, inp in enumerate(self.inputs):
            if i != input_index:
                message_parts.extend([inp.prev_txid, str(inp.prev_vout)])
        
        message = "|".join(message_parts)
        return message.encode('utf-8')
    
    def calculate_txid(self) -> str:
        """Calculate transaction hash"""
        # Create a string representation for hashing that avoids bytes serialization
        tx_string = f"{self.version}"
        
        # Add inputs
        for inp in self.inputs:
            tx_string += f"{inp.prev_txid}{inp.prev_vout}{inp.sequence}"
            if inp.script_sig:
                tx_string += inp.script_sig.hex()
        
        # Add outputs
        for out in self.outputs:
            tx_string += f"{out.value}{out.address}"
            if out.script_pubkey:
                tx_string += out.script_pubkey.hex()
        
        tx_string += f"{self.lock_time}{self.timestamp}"
        
        return hashlib.sha256(tx_string.encode()).hexdigest()
    
    def is_coinbase(self) -> bool:
        """Check if this is a coinbase transaction"""
        return (len(self.inputs) == 1 and 
                self.inputs[0].prev_txid == "0" * 64 and 
                self.inputs[0].prev_vout == 0xffffffff)

@dataclass
class BlockHeader:
    """WEPO Block Header with Hybrid PoW/PoS Support"""
    version: int
    prev_hash: str
    merkle_root: str
    timestamp: int
    bits: int
    nonce: int
    consensus_type: str  # 'pow', 'pos', or 'hybrid'
    validator_address: Optional[str] = None  # For PoS blocks
    validator_signature: Optional[bytes] = None  # For PoS blocks
    
    def calculate_hash(self) -> str:
        """Calculate block hash"""
        header_data = struct.pack('<I32s32sIII', 
                                self.version,
                                bytes.fromhex(self.prev_hash),
                                bytes.fromhex(self.merkle_root),
                                self.timestamp,
                                self.bits,
                                self.nonce)
        return hashlib.sha256(header_data).hexdigest()
    
    def is_pos_block(self) -> bool:
        """Check if this is a PoS block"""
        return self.consensus_type == 'pos'
    
    def is_pow_block(self) -> bool:
        """Check if this is a PoW block"""
        return self.consensus_type == 'pow'

@dataclass
class Block:
    """WEPO Block"""
    header: BlockHeader
    transactions: List[Transaction]
    height: int = 0
    size: int = 0
    
    def __post_init__(self):
        if self.size == 0:
            self.size = self.calculate_size()
    
    def calculate_size(self) -> int:
        """Calculate block size in bytes"""
        # Simplified size calculation avoiding JSON serialization of bytes
        total_size = 0
        for tx in self.transactions:
            # Count transaction components
            total_size += 100  # Base transaction overhead
            total_size += len(tx.inputs) * 50  # Input overhead
            total_size += len(tx.outputs) * 50  # Output overhead
            for inp in tx.inputs:
                total_size += len(inp.script_sig) if inp.script_sig else 0
            for out in tx.outputs:
                total_size += len(out.script_pubkey) if out.script_pubkey else 0
        return total_size
    
    def calculate_merkle_root(self) -> str:
        """Calculate Merkle root of transactions"""
        if not self.transactions:
            return "0" * 64
        
        txids = [tx.calculate_txid() for tx in self.transactions]
        
        while len(txids) > 1:
            next_level = []
            for i in range(0, len(txids), 2):
                left = txids[i]
                right = txids[i + 1] if i + 1 < len(txids) else left
                combined = left + right
                next_level.append(hashlib.sha256(combined.encode()).hexdigest())
            txids = next_level
        
        return txids[0]
    
    def get_block_hash(self) -> str:
        """Get block hash"""
        return self.header.calculate_hash()

class WepoArgon2Miner:
    """Argon2 Proof of Work Miner"""
    
    def __init__(self):
        self.time_cost = 3
        self.memory_cost = 4096  # 4MB
        self.parallelism = 1
        self.hash_len = 32
        self.salt_len = 16

    def _build_pow_input(self, header: BlockHeader) -> bytes:
        """Build deterministic PoW input bytes for a block header."""
        return struct.pack(
            '<I32s32sIII',
            header.version,
            bytes.fromhex(header.prev_hash),
            bytes.fromhex(header.merkle_root),
            header.timestamp,
            header.bits,
            header.nonce,
        ) + header.consensus_type.encode()

    def calculate_pow_hash(self, header: BlockHeader) -> str:
        """Calculate a deterministic Argon2-based PoW hash for a block header."""
        pow_input = self._build_pow_input(header)
        salt = hashlib.sha256(b"WEPO_POW_SALT" + pow_input).digest()[:self.salt_len]
        pow_bytes = argon2.low_level.hash_secret_raw(
            secret=pow_input,
            salt=salt,
            time_cost=self.time_cost,
            memory_cost=self.memory_cost,
            parallelism=self.parallelism,
            hash_len=self.hash_len,
            type=argon2.low_level.Type.ID,
        )
        return hashlib.sha256(pow_bytes).hexdigest()
    
    def mine_block(self, block: Block, target_difficulty: int) -> Optional[Block]:
        """Mine a block using Argon2 PoW"""
        print(f"Mining block {block.height} with target difficulty {target_difficulty}")
        
        start_time = time.time()
        nonce = 0
        max_nonce = 2**32
        
        while nonce < max_nonce:
            # Update nonce in header
            block.header.nonce = nonce

            try:
                block_hash = self.calculate_pow_hash(block.header)
                
                # Check if hash meets difficulty target
                if self.check_difficulty(block_hash, target_difficulty):
                    mining_time = time.time() - start_time
                    hashrate = nonce / mining_time if mining_time > 0 else 0
                    print(f"Block mined! Hash: {block_hash}")
                    print(f"Nonce: {nonce}, Time: {mining_time:.2f}s, Hashrate: {hashrate:.2f} H/s")
                    return block
                    
            except Exception as e:
                # Argon2 error, continue with next nonce
                pass
            
            nonce += 1
            
            # Progress update every 1000 nonces
            if nonce % 1000 == 0:
                elapsed = time.time() - start_time
                if elapsed > 0:
                    hashrate = nonce / elapsed
                    print(f"Mining progress: {nonce} nonces, {hashrate:.2f} H/s")
        
        print("Mining failed - max nonce reached")
        return None
    
    def check_difficulty(self, block_hash: str, difficulty: int) -> bool:
        """Check if block hash meets difficulty target"""
        # Simplified difficulty check - count leading zeros
        leading_zeros = 0
        for char in block_hash:
            if char == '0':
                leading_zeros += 1
            else:
                break
        return leading_zeros >= difficulty

class WepoBlockchain:
    """WEPO Blockchain Core"""
    
    def __init__(self, data_dir: str = "/tmp/wepo", network_profile: Optional[str] = None):
        self.network_profile_name = (network_profile or os.getenv("WEPO_NETWORK_PROFILE", NETWORK_PROFILE_NAME)).strip().lower()
        apply_network_profile(self.network_profile_name)
        self.data_dir = data_dir
        self.db_path = os.path.join(data_dir, "blockchain.db")
        self.chain: List[Block] = []
        self.mempool: Dict[str, Transaction] = {}
        self.utxo_set: Dict[str, TransactionOutput] = {}
        self.stakes: Dict[str, dict] = {}
        self.masternodes: Dict[str, dict] = {}
        self.current_difficulty = 4  # Start with 4 leading zeros
        self.fixed_difficulty: Optional[int] = None
        self.miner = WepoArgon2Miner()
        
        # Ensure data directory exists
        os.makedirs(data_dir, exist_ok=True)
        
        # Initialize database
        self.init_database()
        
        # Load existing chain or create genesis
        self.load_chain()
        if not self.chain:
            self.create_genesis_block()
    
    def init_database(self):
        """Initialize SQLite database"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS blocks (
                height INTEGER PRIMARY KEY,
                hash TEXT UNIQUE NOT NULL,
                prev_hash TEXT NOT NULL,
                merkle_root TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                bits INTEGER NOT NULL,
                nonce INTEGER NOT NULL,
                version INTEGER NOT NULL,
                size INTEGER NOT NULL,
                tx_count INTEGER NOT NULL,
                consensus_type TEXT NOT NULL,
                block_data TEXT NOT NULL
            )
        ''')
        
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                txid TEXT PRIMARY KEY,
                block_height INTEGER,
                block_hash TEXT,
                version INTEGER NOT NULL,
                lock_time INTEGER NOT NULL,
                fee INTEGER NOT NULL,
                privacy_proof BLOB,
                ring_signature BLOB,
                tx_data TEXT NOT NULL,
                FOREIGN KEY(block_height) REFERENCES blocks(height)
            )
        ''')
        
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS utxos (
                txid TEXT NOT NULL,
                vout INTEGER NOT NULL,
                address TEXT NOT NULL,
                amount INTEGER NOT NULL,
                script_pubkey BLOB NOT NULL,
                spent BOOLEAN DEFAULT FALSE,
                spent_txid TEXT,
                spent_height INTEGER,
                PRIMARY KEY(txid, vout)
            )
        ''')
        
        # Staking tables
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS stakes (
                stake_id TEXT PRIMARY KEY,
                staker_address TEXT NOT NULL,
                amount INTEGER NOT NULL,
                start_height INTEGER NOT NULL,
                start_time INTEGER NOT NULL,
                last_reward_height INTEGER DEFAULT 0,
                total_rewards INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                unlock_height INTEGER,
                FOREIGN KEY(start_height) REFERENCES blocks(height)
            )
        ''')
        
        # Masternode tables
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS masternodes (
                masternode_id TEXT PRIMARY KEY,
                operator_address TEXT NOT NULL,
                collateral_txid TEXT NOT NULL,
                collateral_vout INTEGER NOT NULL,
                ip_address TEXT,
                port INTEGER DEFAULT 22567,
                start_height INTEGER NOT NULL,
                start_time INTEGER NOT NULL,
                last_ping INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                total_rewards INTEGER DEFAULT 0,
                FOREIGN KEY(start_height) REFERENCES blocks(height),
                FOREIGN KEY(collateral_txid) REFERENCES transactions(txid)
            )
        ''')
        
        # Staking rewards history
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS staking_rewards (
                reward_id TEXT PRIMARY KEY,
                recipient_address TEXT NOT NULL,
                recipient_type TEXT NOT NULL, -- 'staker' or 'masternode'
                amount INTEGER NOT NULL,
                block_height INTEGER NOT NULL,
                block_hash TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                FOREIGN KEY(block_height) REFERENCES blocks(height)
            )
        ''')
        
        self.conn.commit()
    
    def create_genesis_block(self):
        """Create the genesis block"""
        print("Creating WEPO genesis block...")
        genesis_address = generate_wepo_address("wepo-mainnet-genesis", address_type="regular")
        
        # Genesis coinbase transaction
        genesis_tx = Transaction(
            version=1,
            inputs=[TransactionInput(
                prev_txid="0" * 64,
                prev_vout=0xffffffff,
                script_sig=b"WEPO Genesis - We The People",
                sequence=0xffffffff
            )],
            outputs=[TransactionOutput(
                value=GENESIS_BOOTSTRAP_REWARD,
                script_pubkey=b"genesis_output",
                address=genesis_address
            )],
            lock_time=0,
            timestamp=GENESIS_TIME
        )
        
        # Genesis block header
        genesis_difficulty = 1
        genesis_header = BlockHeader(
            version=1,
            prev_hash="0" * 64,
            merkle_root="",
            timestamp=GENESIS_TIME,
            bits=genesis_difficulty,
            nonce=0,
            consensus_type="pow"
        )
        
        # Create genesis block
        genesis_block = Block(
            header=genesis_header,
            transactions=[genesis_tx],
            height=0
        )
        
        # Calculate merkle root
        genesis_block.header.merkle_root = genesis_block.calculate_merkle_root()
        
        # Mine genesis block at minimal bootstrap difficulty so a fresh node can initialize quickly.
        mined_genesis = self.miner.mine_block(genesis_block, genesis_difficulty)
        if mined_genesis:
            self.add_block(mined_genesis, validate=False)  # Skip validation for genesis

            print(f"Genesis block created: {mined_genesis.get_block_hash()}")
            print(f"Genesis address: {genesis_address}")
            print(f"Genesis bootstrap UTXO created: {GENESIS_BOOTSTRAP_REWARD / COIN} WEPO")
        else:
            raise Exception("Failed to mine genesis block")
    
    def load_chain(self):
        """Load blockchain from database"""
        cursor = self.conn.execute('''
            SELECT block_data FROM blocks ORDER BY height ASC
        ''')
        
        for row in cursor.fetchall():
            block_data = json.loads(row[0])
            block = self.deserialize_block(block_data)
            self.chain.append(block)
        
        self.current_difficulty = self.calculate_expected_difficulty()
        print(f"Loaded {len(self.chain)} blocks from database")
    
    def serialize_block(self, block: Block) -> str:
        """Serialize block to JSON"""
        # Convert bytes to hex strings for JSON serialization
        def bytes_to_hex(obj):
            if isinstance(obj, bytes):
                return obj.hex()
            elif isinstance(obj, dict):
                return {k: bytes_to_hex(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [bytes_to_hex(item) for item in obj]
            else:
                return obj
        
        block_dict = {
            'header': asdict(block.header),
            'transactions': [],
            'height': block.height,
            'size': block.size
        }
        
        # Serialize transactions with bytes conversion
        for tx in block.transactions:
            tx_dict = asdict(tx)
            tx_dict = bytes_to_hex(tx_dict)
            block_dict['transactions'].append(tx_dict)
        
        return json.dumps(block_dict)
    
    def deserialize_block(self, data: dict) -> Block:
        """Deserialize block from JSON"""
        # Convert hex strings back to bytes
        def hex_to_bytes(obj):
            if isinstance(obj, str) and len(obj) % 2 == 0:
                try:
                    return bytes.fromhex(obj)
                except ValueError:
                    return obj
            elif isinstance(obj, dict):
                return {k: hex_to_bytes(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [hex_to_bytes(item) for item in obj]
            else:
                return obj
        
        header = BlockHeader(**data['header'])
        transactions = []
        for tx_data in data['transactions']:
            # Convert hex back to bytes where needed
            if 'script_sig' in str(tx_data):
                tx_data = hex_to_bytes(tx_data)
            
            inputs = []
            for inp_data in tx_data['inputs']:
                script_sig = inp_data.get('script_sig', b'')
                if isinstance(script_sig, str):
                    script_sig = script_sig.encode() if script_sig else b''
                
                # Handle quantum signature fields
                quantum_signature = inp_data.get('quantum_signature')
                if isinstance(quantum_signature, str) and quantum_signature:
                    quantum_signature = bytes.fromhex(quantum_signature)
                
                quantum_public_key = inp_data.get('quantum_public_key')
                if isinstance(quantum_public_key, str) and quantum_public_key:
                    quantum_public_key = bytes.fromhex(quantum_public_key)
                
                inputs.append(TransactionInput(
                    prev_txid=inp_data['prev_txid'],
                    prev_vout=inp_data['prev_vout'],
                    script_sig=script_sig,
                    sequence=inp_data.get('sequence', 0xffffffff),
                    quantum_signature=quantum_signature,
                    quantum_public_key=quantum_public_key,
                    signature_type=inp_data.get('signature_type', 'ecdsa')
                ))
            
            outputs = []
            for out_data in tx_data['outputs']:
                script_pubkey = out_data.get('script_pubkey', b'')
                if isinstance(script_pubkey, str):
                    script_pubkey = script_pubkey.encode() if script_pubkey else b''
                outputs.append(TransactionOutput(
                    value=out_data['value'],
                    script_pubkey=script_pubkey,
                    address=out_data.get('address', '')
                ))
            
            privacy_proof = tx_data.get('privacy_proof')
            if isinstance(privacy_proof, str):
                privacy_proof = privacy_proof.encode() if privacy_proof else None
                
            ring_signature = tx_data.get('ring_signature')
            if isinstance(ring_signature, str):
                ring_signature = ring_signature.encode() if ring_signature else None
            
            tx = Transaction(
                version=tx_data['version'],
                inputs=inputs,
                outputs=outputs,
                lock_time=tx_data['lock_time'],
                fee=tx_data.get('fee', 0),
                privacy_proof=privacy_proof,
                ring_signature=ring_signature,
                timestamp=tx_data.get('timestamp', 0)
            )
            transactions.append(tx)
        
        return Block(
            header=header,
            transactions=transactions,
            height=data['height'],
            size=data['size']
        )
    
    def get_latest_block(self) -> Optional[Block]:
        """Get the latest block in the chain"""
        return self.chain[-1] if self.chain else None
    
    def get_block_height(self) -> int:
        """Get current block height"""
        return len(self.chain) - 1 if self.chain else -1
    
    def calculate_block_reward(self, height: int) -> int:
        """Calculate block reward based on new 20-year sustainable mining schedule"""
        if height == 0:
            # Genesis is an explicit bootstrap allocation, not a normal mining-era block.
            return GENESIS_BOOTSTRAP_REWARD
        
        # PHASE 1: Pre-PoS Mining (Months 1-18) - 10% of supply
        if height <= PRE_POS_DURATION_BLOCKS:
            # Months 1-18: 52.51 WEPO per block (6-minute blocks)
            return PRE_POS_REWARD
        
        # PHASE 2A: Post-PoS Years 1-3 (Months 19-54)
        elif height <= PHASE_2A_END_HEIGHT:
            # Years 1-3: 33.17 WEPO per block (9-minute blocks)
            return PHASE_2A_REWARD
        
        # PHASE 2B: Post-PoS Years 4-9 (Months 55-126) - First Halving
        elif height <= PHASE_2B_END_HEIGHT:
            # Years 4-9: 16.58 WEPO per block (9-minute blocks)
            return PHASE_2B_REWARD
        
        # PHASE 2C: Post-PoS Years 10-12 (Months 127-162) - Second Halving  
        elif height <= PHASE_2C_END_HEIGHT:
            # Years 10-12: 8.29 WEPO per block (9-minute blocks)
            return PHASE_2C_REWARD
        
        # PHASE 2D: Post-PoS Years 13-15 (Months 163-198) - Final Halving
        elif height <= PHASE_2D_END_HEIGHT:
            # Years 13-15: 4.15 WEPO per block (9-minute blocks)
            return PHASE_2D_REWARD
        
        else:
            # PoW ENDS at block 1,007,400 (Month 198)
            # Miners continue earning through 25% fee redistribution
            return 0
        
        # TOTAL MINING TIMELINE:
        # - Phase 1 (18 months): 6.9M WEPO (10% of supply)
        # - Phase 2A-2D (16.5 years): 13.8M WEPO (20% of supply)
        # - Total PoW: 20.7M WEPO over 198 months (30% of supply)
        # - PoS/Masternodes: 48.3M WEPO (70% of supply)
        # - Post-PoW: Miners earn via 25% transaction fee redistribution
    
    def calculate_pos_reward(self, height: int) -> int:
        """Calculate PoS block reward based on height"""
        if height <= POS_ACTIVATION_HEIGHT:
            return 0
        
        # PoS rewards are smaller than PoW since they occur more frequently
        # PoS blocks every 3 minutes vs PoW every 9 minutes = 3x more frequent
        # So PoS rewards should be ~1/3 of PoW rewards for same total distribution
        
        # PHASE 2A: Post-PoS Years 1-3 (Months 19-54)
        if height <= PHASE_2A_END_HEIGHT:
            # PoS gets 1/3 of PoW reward since 3x more frequent
            return int(PHASE_2A_REWARD * 0.33)  # ~11 WEPO per PoS block
        
        # PHASE 2B: Post-PoS Years 4-9 (Months 55-126) - First Halving
        elif height <= PHASE_2B_END_HEIGHT:
            return int(PHASE_2B_REWARD * 0.33)  # ~5.5 WEPO per PoS block
        
        # PHASE 2C: Post-PoS Years 10-12 (Months 127-162) - Second Halving  
        elif height <= PHASE_2C_END_HEIGHT:
            return int(PHASE_2C_REWARD * 0.33)  # ~2.75 WEPO per PoS block
        
        # PHASE 2D: Post-PoS Years 13-15 (Months 163-198) - Final Halving
        elif height <= PHASE_2D_END_HEIGHT:
            return int(PHASE_2D_REWARD * 0.33)  # ~1.38 WEPO per PoS block
        
        else:
            # After PoW ends, PoS continues with fee redistribution only
            return 0
    
    def create_coinbase_transaction(
        self,
        height: int,
        recipient_address: str,
        consensus_type: str = "pow",
        candidate_transactions: Optional[List[Transaction]] = None,
    ) -> Transaction:
        """Create coinbase transaction for new block with canonical fee redistribution."""
        # Get appropriate reward based on consensus type
        if consensus_type == "pow":
            base_reward = self.calculate_block_reward(height)
            print(f"PoW Block {height}: Base reward {base_reward / COIN:.8f} WEPO")
        elif consensus_type == "pos":
            base_reward = self.calculate_pos_reward(height)
            print(f"PoS Block {height}: Base reward {base_reward / COIN:.8f} WEPO")
        else:
            base_reward = 0
        
        # Calculate total transaction fees from the transactions actually selected for the block.
        total_transaction_fees = 0
        for tx in candidate_transactions or []:
            if hasattr(tx, 'fee') and tx.fee:
                total_transaction_fees += tx.fee
        
        fee_outputs = []
        if total_transaction_fees > 0:
            distributed_masternode_fees = 0
            distributed_staker_fees = 0

            active_masternodes = self.get_active_masternodes()
            pre_pos_fee_policy = height <= POS_ACTIVATION_HEIGHT
            if pre_pos_fee_policy:
                # Before PoS activation, all fees go to the miner unless active masternodes
                # already exist. If they do, keep the masternode share and route the
                # non-staker remainder to the miner.
                staker_fees = 0
                if active_masternodes:
                    masternode_fees = int(total_transaction_fees * 0.60)
                    miner_fees = total_transaction_fees - masternode_fees
                else:
                    masternode_fees = 0
                    miner_fees = total_transaction_fees
            else:
                # Post-PoS: 60% masternodes, 25% miner/validator, 15% stakers.
                masternode_fees = int(total_transaction_fees * 0.60)
                miner_fees = int(total_transaction_fees * 0.25)
                staker_fees = total_transaction_fees - masternode_fees - miner_fees

            if active_masternodes and masternode_fees > 0:
                fee_per_masternode = masternode_fees // len(active_masternodes)
                fee_remainder = masternode_fees % len(active_masternodes)
                for index, masternode in enumerate(active_masternodes):
                    fee_amount = fee_per_masternode + (1 if index < fee_remainder else 0)
                    if fee_amount <= 0:
                        continue
                    distributed_masternode_fees += fee_amount
                    fee_outputs.append(TransactionOutput(
                        value=fee_amount,
                        script_pubkey=f"masternode_fee_output:{masternode.masternode_id}".encode(),
                        address=masternode.operator_address
                    ))
                    print(
                        f"Masternode {masternode.operator_address} receives "
                        f"{fee_amount / COIN:.8f} WEPO in fees"
                    )

            active_stakers = [] if pre_pos_fee_policy else self.get_active_stakes()
            total_stake = sum(staker.amount for staker in active_stakers)
            if active_stakers and total_stake > 0 and staker_fees > 0:
                remaining_fees = staker_fees
                for index, staker in enumerate(active_stakers):
                    if index == len(active_stakers) - 1:
                        staker_reward = remaining_fees
                    else:
                        staker_reward = int(staker_fees * (staker.amount / total_stake))
                        staker_reward = min(staker_reward, remaining_fees)
                    if staker_reward <= 0:
                        continue
                    remaining_fees -= staker_reward
                    distributed_staker_fees += staker_reward
                    fee_outputs.append(TransactionOutput(
                        value=staker_reward,
                        script_pubkey=f"staker_fee_output:{staker.stake_id}".encode(),
                        address=staker.staker_address
                    ))
                    print(
                        f"Staker {staker.staker_address} receives "
                        f"{staker_reward / COIN:.8f} WEPO in fees"
                    )

            recipient_fee_share = (
                miner_fees
                + (masternode_fees - distributed_masternode_fees)
                + (staker_fees - distributed_staker_fees)
            )

            print(f"Fee Distribution Summary:")
            print(f"  Total Fees: {total_transaction_fees / COIN:.8f} WEPO")
            print(f"  Masternodes (60%): {masternode_fees / COIN:.8f} WEPO")
            print(
                f"  Miner/Validator ({'100%' if pre_pos_fee_policy and not active_masternodes else '40%' if pre_pos_fee_policy else '25%'}): "
                f"{miner_fees / COIN:.8f} WEPO"
            )
            print(f"  Stakers ({'0%' if pre_pos_fee_policy else '15%'}): {staker_fees / COIN:.8f} WEPO")
        else:
            recipient_fee_share = 0

        total_recipient_reward = base_reward + recipient_fee_share
        
        print(f"Coinbase for {consensus_type.upper()} block {height}:")
        print(f"  Base reward: {base_reward / COIN:.8f} WEPO")
        print(f"  Fee share: {recipient_fee_share / COIN:.8f} WEPO")
        print(f"  Total reward: {total_recipient_reward / COIN:.8f} WEPO")
        
        return Transaction(
            version=1,
            inputs=[TransactionInput(
                prev_txid="0" * 64,
                prev_vout=0xffffffff,
                script_sig=f"Block {height} {consensus_type.upper()} fees:{total_transaction_fees} 3-way-distribution".encode(),
                sequence=0xffffffff
            )],
            outputs=[
                TransactionOutput(
                    value=total_recipient_reward,
                    script_pubkey=b"coinbase_output",
                    address=recipient_address
                ),
                *fee_outputs,
            ],
            lock_time=0
        )
    
    def create_new_block(self, miner_address: str) -> Block:
        """Create a new block with transactions from mempool"""
        height = self.get_block_height() + 1
        latest_block = self.get_latest_block()
        prev_hash = latest_block.get_block_hash() if latest_block else "0" * 64

        selected_transactions = []
        selected_txids = []
        provisional_coinbase = self.create_coinbase_transaction(
            height,
            miner_address,
            consensus_type="pow",
            candidate_transactions=[],
        )
        current_size = self._estimate_transaction_size(provisional_coinbase)

        for txid, tx in list(self.mempool.items()):
            if not self.validate_transaction(tx):
                continue

            tx_size = self._estimate_transaction_size(tx)
            if current_size + tx_size <= MAX_BLOCK_SIZE:
                selected_transactions.append(tx)
                selected_txids.append(txid)
                current_size += tx_size
            else:
                break

        coinbase_tx = self.create_coinbase_transaction(
            height,
            miner_address,
            consensus_type="pow",
            candidate_transactions=selected_transactions,
        )
        transactions = [coinbase_tx, *selected_transactions]

        for txid in selected_txids:
            del self.mempool[txid]
        
        # Determine block time target
        if height <= TOTAL_INITIAL_BLOCKS:
            block_time = BLOCK_TIME_INITIAL_18_MONTHS  # 6 minutes per block for first 18 months
        else:
            block_time = BLOCK_TIME_LONGTERM  # 9 minutes per block after 18 months
        
        # Create block header
        header = BlockHeader(
            version=1,
            prev_hash=prev_hash,
            merkle_root="",
            timestamp=int(time.time()),
            bits=self.current_difficulty,
            nonce=0,
            consensus_type="pow"  # TODO: Implement PoS after activation height
        )
        
        # Create block
        block = Block(
            header=header,
            transactions=transactions,
            height=height
        )
        
        # Calculate merkle root
        block.header.merkle_root = block.calculate_merkle_root()
        
        return block

    def _estimate_transaction_size(self, tx: Transaction) -> int:
        """Estimate transaction payload size while handling bytes fields safely."""
        return len(json.dumps(asdict(tx), default=self._json_default))

    @staticmethod
    def _json_default(value):
        """JSON serializer fallback for blockchain dataclasses with bytes content."""
        if isinstance(value, (bytes, bytearray)):
            return value.hex()
        return str(value)
    
    def mine_block(self, miner_address: str) -> Optional[Block]:
        """Mine a new block"""
        block = self.create_new_block(miner_address)
        
        # Adjust difficulty if needed
        self.adjust_difficulty()
        
        # Mine the block
        mined_block = self.miner.mine_block(block, self.current_difficulty)
        
        if mined_block:
            # Add block to chain
            if self.add_block(mined_block):
                return mined_block
        
        return None
    
    def create_pos_block(self, validator_address: str) -> Optional[Block]:
        """Create a PoS block (no mining required)"""
        next_height = self.get_block_height() + 1
        if not self.is_valid_pos_validator(validator_address, next_height):
            return None
        
        # Create block with PoS consensus
        height = next_height
        prev_hash = self.chain[-1].get_block_hash() if self.chain else "0" * 64
        
        # Create coinbase transaction for PoS rewards
        selected_transactions = []
        provisional_coinbase = self.create_coinbase_transaction(
            height,
            validator_address,
            consensus_type="pos",
            candidate_transactions=[],
        )
        current_size = self._estimate_transaction_size(provisional_coinbase)
        selected_txids = []
        
        # Add transactions from mempool
        for txid, tx in list(self.mempool.items()):
            if not self.validate_transaction(tx):
                continue

            tx_size = self._estimate_transaction_size(tx)
            if current_size + tx_size > MAX_BLOCK_SIZE:
                continue

            selected_transactions.append(tx)
            current_size += tx_size
            selected_txids.append(txid)

        coinbase_tx = self.create_coinbase_transaction(
            height,
            validator_address,
            consensus_type="pos",
            candidate_transactions=selected_transactions,
        )
        transactions = [coinbase_tx, *selected_transactions]

        for txid in selected_txids:
            self.mempool.pop(txid, None)
        
        # Set appropriate block time for PoS
        if height <= PRE_POS_DURATION_BLOCKS:
            block_time = BLOCK_TIME_INITIAL_18_MONTHS  # 6 minutes per block for first 18 months
        else:
            block_time = BLOCK_TIME_POS  # 3 minutes per PoS block
        
        # Create PoS block header
        header = BlockHeader(
            version=1,
            prev_hash=prev_hash,
            merkle_root="",
            timestamp=int(time.time()),
            bits=0,  # No difficulty for PoS
            nonce=0,  # No nonce for PoS
            consensus_type="pos",
            validator_address=validator_address
        )
        
        # Create PoS block
        pos_block = Block(
            header=header,
            transactions=transactions,
            height=height
        )
        
        # Calculate merkle root
        pos_block.header.merkle_root = pos_block.calculate_merkle_root()
        
        # Sign the block with validator's key (simplified for now)
        # In production, this would use the validator's private key
        header.validator_signature = self.sign_pos_block(pos_block, validator_address)
        
        return pos_block
    
    def sign_pos_block(self, block: Block, validator_address: str) -> bytes:
        """Sign PoS block with validator's key (simplified implementation)"""
        # For now, create a simple signature based on block hash and validator
        import hashlib
        block_hash = block.get_block_hash()
        signature_data = f"{block_hash}:{validator_address}".encode()
        return hashlib.sha256(signature_data).digest()
    
    def validate_pos_block(self, block: Block) -> bool:
        """Validate PoS block"""
        if not block.header.is_pos_block():
            return False
        
        # Check validator eligibility
        if not self.is_valid_pos_validator(block.header.validator_address, block.height):
            return False
        
        # Verify block signature (simplified)
        expected_signature = self.sign_pos_block(block, block.header.validator_address)
        if block.header.validator_signature != expected_signature:
            return False
        
        return True
    
    def add_block(self, block: Block, validate: bool = True) -> bool:
        """Add a block to the blockchain"""
        if validate and not self.validate_block(block):
            return False
        
        # Add to chain
        self.chain.append(block)
        
        # Process transactions and update UTXOs
        self.process_block_transactions(block)
        
        # Save to database
        self.save_block(block)
        self.current_difficulty = self.calculate_expected_difficulty()
        self.record_fee_distribution_rewards(block)
        
        # Distribute staking rewards if PoS is active
        if block.height > POS_ACTIVATION_HEIGHT:
            self.distribute_staking_rewards(block.height, block.get_block_hash())
        
        print(f"Block {block.height} added to chain: {block.get_block_hash()}")
        return True
    
    def add_block_with_priority(self, new_block: Block) -> bool:
        """Add block with timestamp-based priority (first valid block wins)"""
        # Check if block at this height already exists
        if new_block.height <= len(self.chain):
            existing_block = self.chain[new_block.height - 1]
            
            # If new block has earlier timestamp, it wins
            if new_block.header.timestamp < existing_block.header.timestamp:
                print(f"Replacing block {new_block.height} - newer timestamp wins")
                # Replace the block
                self.chain[new_block.height - 1] = new_block
                self.save_block(new_block)
                return True
            else:
                print(f"Rejecting block {new_block.height} - later timestamp loses")
                return False
        else:
            # No existing block, add normally
            return self.add_block(new_block)
    
    def get_consensus_type(self, height: int) -> str:
        """Get the consensus type for a given height"""
        if height <= POS_ACTIVATION_HEIGHT:
            return "pow"
        else:
            return "hybrid"  # Both PoW and PoS active
    
    def process_hybrid_blocks(self, height: int):
        """Process both PoW and PoS blocks for hybrid consensus"""
        if height <= POS_ACTIVATION_HEIGHT:
            return
        
        # Time-based block production
        current_time = int(time.time())
        
        # Check if it's time for a PoS block (every 3 minutes)
        if current_time % BLOCK_TIME_POS == 0:
            # Select validator for PoS block
            validator = self.select_pos_validator(height)
            if validator:
                pos_block = self.create_pos_block(validator)
                if pos_block and self.validate_block(pos_block):
                    self.add_block_with_priority(pos_block)
        
        # Check if it's time for a PoW block (every 9 minutes)
        if current_time % BLOCK_TIME_POW_HYBRID == 0:
            # PoW mining continues in parallel
            print(f"PoW mining opportunity at height {height}")
            # This would trigger miners to start mining
            pass
    
    def validate_block(self, block: Block) -> bool:
        """Validate a block (supports both PoW and PoS)"""
        # Basic validation
        if not block.transactions:
            return False

        if block.size > MAX_BLOCK_SIZE:
            return False

        latest_block = self.get_latest_block()
        expected_height = self.get_block_height() + 1
        if self.chain:
            if block.height != expected_height:
                return False
            if block.header.prev_hash != latest_block.get_block_hash():
                return False
        elif block.height != 0:
            return False

        if block.header.timestamp > int(time.time()) + MAX_FUTURE_BLOCK_TIME_DRIFT:
            return False

        if block.header.merkle_root != block.calculate_merkle_root():
            return False
        
        # Check coinbase transaction
        if not block.transactions[0].is_coinbase():
            return False
        
        # Validate based on consensus type
        if block.header.is_pos_block():
            # PoS block validation
            if not self.validate_pos_block(block):
                return False
        elif block.header.is_pow_block():
            if not self.validate_pow_block(block):
                return False
        else:
            return False
        
        # Validate all transactions
        for tx in block.transactions:
            if not self.validate_transaction(tx):
                return False
        
        return True

    def validate_pow_block(self, block: Block) -> bool:
        """Validate deterministic PoW and expected difficulty for a block."""
        expected_difficulty = self.calculate_expected_difficulty()
        if block.header.bits != expected_difficulty:
            print(
                f"Invalid PoW difficulty bits: got {block.header.bits}, "
                f"expected {expected_difficulty}"
            )
            return False

        if not isinstance(block.header.nonce, int) or block.header.nonce < 0:
            print(f"Invalid nonce: {block.header.nonce}")
            return False

        pow_hash = self.miner.calculate_pow_hash(block.header)
        if not self.miner.check_difficulty(pow_hash, expected_difficulty):
            print(
                f"Invalid proof of work for block {block.height}: "
                f"pow_hash={pow_hash}, difficulty={expected_difficulty}"
            )
            return False

        return True
    
    def process_block_transactions(self, block: Block):
        """Process all transactions in a block and update UTXOs"""
        for tx in block.transactions:
            # Process transaction inputs (spend UTXOs)
            if not tx.is_coinbase():
                for inp in tx.inputs:
                    # Mark UTXO as spent
                    self.conn.execute('''
                        UPDATE utxos SET spent = TRUE, spent_txid = ?, spent_height = ?
                        WHERE txid = ? AND vout = ?
                    ''', (tx.calculate_txid(), block.height, inp.prev_txid, inp.prev_vout))
            
            # Process transaction outputs (create new UTXOs)
            for i, out in enumerate(tx.outputs):
                self.conn.execute('''
                    INSERT INTO utxos (txid, vout, address, amount, script_pubkey, spent)
                    VALUES (?, ?, ?, ?, ?, FALSE)
                ''', (tx.calculate_txid(), i, out.address, out.value, out.script_pubkey))
        
        self.conn.commit()
    
    def save_block(self, block: Block):
        """Save block to database"""
        # Save block
        self.conn.execute('''
            INSERT INTO blocks (height, hash, prev_hash, merkle_root, timestamp, bits, nonce, version, size, tx_count, consensus_type, block_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            block.height,
            block.get_block_hash(),
            block.header.prev_hash,
            block.header.merkle_root,
            block.header.timestamp,
            block.header.bits,
            block.header.nonce,
            block.header.version,
            block.size,
            len(block.transactions),
            block.header.consensus_type,
            self.serialize_block(block)
        ))
        
        # Save transactions
        for tx in block.transactions:
            self.conn.execute('''
                INSERT INTO transactions (txid, block_height, block_hash, version, lock_time, fee, privacy_proof, ring_signature, tx_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                tx.calculate_txid(),
                block.height,
                block.get_block_hash(),
                tx.version,
                tx.lock_time,
                tx.fee,
                tx.privacy_proof,
                tx.ring_signature,
                json.dumps(asdict(tx), default=str)
            ))
        
        self.conn.commit()
    
    def adjust_difficulty(self):
        """Adjust mining difficulty based on block time"""
        previous_difficulty = self.current_difficulty
        self.current_difficulty = self.calculate_expected_difficulty()
        if self.current_difficulty > previous_difficulty:
            print(f"Difficulty increased to {self.current_difficulty}")
        elif self.current_difficulty < previous_difficulty:
            print(f"Difficulty decreased to {self.current_difficulty}")

    def calculate_expected_difficulty(self) -> int:
        """Calculate the expected difficulty for the next PoW block."""
        if self.fixed_difficulty is not None:
            return max(1, int(self.fixed_difficulty))

        if not self.chain:
            return max(1, self.current_difficulty)

        base_difficulty = max(1, int(self.chain[-1].header.bits))
        if len(self.chain) < 10:
            return base_difficulty

        recent_blocks = self.chain[-10:]
        time_diffs = []
        for i in range(1, len(recent_blocks)):
            diff = recent_blocks[i].header.timestamp - recent_blocks[i - 1].header.timestamp
            time_diffs.append(diff)

        if not time_diffs:
            return base_difficulty

        avg_time = sum(time_diffs) / len(time_diffs)
        current_height = self.get_block_height()
        target_time = (
            BLOCK_TIME_INITIAL_18_MONTHS
            if current_height <= TOTAL_INITIAL_BLOCKS
            else BLOCK_TIME_LONGTERM
        )

        if avg_time < target_time * 0.75:
            return base_difficulty + 1
        if avg_time > target_time * 1.25:
            return max(1, base_difficulty - 1)
        return base_difficulty
    
    def add_transaction_to_mempool(self, transaction: Transaction) -> bool:
        """Add transaction to mempool"""
        txid = transaction.calculate_txid()
        
        # Basic validation
        if self.validate_transaction(transaction):
            self.mempool[txid] = transaction
            
            print(f"Transaction added to mempool: {txid}")
            return True
        else:
            print(f"Invalid transaction rejected: {txid}")
            return False
    
    def validate_transaction(self, transaction: Transaction) -> bool:
        """Validate a transaction with proper UTXO checking and quantum signature support"""
        try:
            # Skip validation for coinbase transactions
            if transaction.is_coinbase():
                return True
            
            # Check inputs exist and are unspent
            total_input_value = 0
            for inp in transaction.inputs:
                # Check if UTXO exists and is unspent
                cursor = self.conn.execute('''
                    SELECT amount, spent FROM utxos WHERE txid = ? AND vout = ?
                ''', (inp.prev_txid, inp.prev_vout))
                
                utxo = cursor.fetchone()
                if not utxo:
                    print(f"UTXO not found: {inp.prev_txid}:{inp.prev_vout}")
                    return False
                
                if utxo[1]:  # spent flag
                    print(f"UTXO already spent: {inp.prev_txid}:{inp.prev_vout}")
                    return False
                
                total_input_value += utxo[0]
            
            # Check outputs
            total_output_value = sum(out.value for out in transaction.outputs)
            
            # Calculate fee
            fee = total_input_value - total_output_value
            if fee < 0:
                print(f"Transaction outputs exceed inputs: {total_output_value} > {total_input_value}")
                return False
            
            # Set fee on transaction
            transaction.fee = fee
            
            # Validate quantum signatures if present
            for i, inp in enumerate(transaction.inputs):
                if inp.signature_type == "dilithium":
                    if not transaction.verify_quantum_signature(i):
                        print(f"Invalid quantum signature for input {i}")
                        return False
            
            return True
            
        except Exception as e:
            print(f"Transaction validation error: {e}")
            return False
    
    def get_balance(self, address: str) -> int:
        """Get balance for an address"""
        cursor = self.conn.execute('''
            SELECT SUM(amount)
            FROM utxos
            WHERE address = ?
              AND spent = FALSE
              AND NOT EXISTS (
                  SELECT 1
                  FROM masternodes
                  WHERE status = 'active'
                    AND collateral_txid = utxos.txid
                    AND collateral_vout = utxos.vout
              )
        ''', (address,))
        result = cursor.fetchone()
        return result[0] if result[0] else 0

    def get_balance_wepo(self, address: str) -> float:
        """Get balance for an address in WEPO units."""
        return self.get_balance(address) / COIN
    
    def get_utxos_for_address(self, address: str) -> List[dict]:
        """Get all unspent UTXOs for an address"""
        cursor = self.conn.execute('''
            SELECT txid, vout, amount, script_pubkey
            FROM utxos 
            WHERE address = ?
              AND spent = FALSE
              AND NOT EXISTS (
                  SELECT 1
                  FROM masternodes
                  WHERE status = 'active'
                    AND collateral_txid = utxos.txid
                    AND collateral_vout = utxos.vout
              )
        ''', (address,))
        
        utxos = []
        for row in cursor.fetchall():
            utxos.append({
                'txid': row[0],
                'vout': row[1],
                'amount': row[2],
                'script_pubkey': row[3]
            })
        
        return utxos
    
    def create_transaction(
        self,
        from_address: str,
        to_address: str,
        amount: int,
        fee: int = 10000,
        allow_fee_only: bool = False,
    ) -> Optional[Transaction]:
        """Create a transaction."""
        if amount < 0:
            print(f"Invalid transaction amount: {amount}")
            return None

        if fee < 0:
            print(f"Invalid transaction fee: {fee}")
            return None

        if amount == 0 and not allow_fee_only:
            print("Zero-amount transfer rejected without fee-only mode")
            return None

        # Get UTXOs for sender
        utxos = self.get_utxos_for_address(from_address)
        
        if not utxos:
            print(f"No UTXOs found for address {from_address}")
            return None
        
        # Calculate total available
        total_available = sum(utxo['amount'] for utxo in utxos)
        
        if total_available < amount + fee:
            print(f"Insufficient balance: {total_available} < {amount + fee}")
            return None
        
        # Create inputs
        inputs = []
        input_total = 0
        
        for utxo in utxos:
            inputs.append(TransactionInput(
                prev_txid=utxo['txid'],
                prev_vout=utxo['vout'],
                script_sig=b"signature_placeholder",
                sequence=0xffffffff
            ))
            input_total += utxo['amount']
            
            if input_total >= amount + fee:
                break
        
        # Create outputs
        outputs = []
        if amount > 0:
            outputs.append(TransactionOutput(
                value=amount,
                script_pubkey=b"output_script",
                address=to_address
            ))
        
        # Add change output if needed
        change = input_total - amount - fee
        if change > 0:
            outputs.append(TransactionOutput(
                value=change,
                script_pubkey=b"change_script", 
                address=from_address
            ))

        if not outputs:
            print("Transaction creation produced no outputs")
            return None
        
        # Create transaction
        transaction = Transaction(
            version=1,
            inputs=inputs,
            outputs=outputs,
            lock_time=0,
            fee=fee
        )
        
        return transaction
    
    # ===== STAKING SYSTEM =====
    
    def create_stake(self, staker_address: str, amount: int) -> str:
        """Create a new stake"""
        if self.get_block_height() <= POS_ACTIVATION_HEIGHT:
            raise ValueError(f"Staking is not active until block {POS_ACTIVATION_HEIGHT + 1}")

        if amount < MIN_STAKE_AMOUNT:
            raise ValueError(f"Minimum stake amount is {MIN_STAKE_AMOUNT / COIN} WEPO")
        
        # Check if user has sufficient balance
        balance = self.get_balance(staker_address)
        if balance < amount:
            raise ValueError(f"Insufficient balance: {balance / COIN} WEPO")

        selected_utxos = []
        locked_total = 0
        for utxo in self.get_utxos_for_address(staker_address):
            selected_utxos.append(utxo)
            locked_total += utxo['amount']
            if locked_total >= amount:
                break

        if locked_total < amount:
            raise ValueError(f"Insufficient spendable balance: {locked_total / COIN} WEPO")

        # Create stake
        stake_id = f"stake_{staker_address}_{int(time.time())}"
        stake_lock_txid = f"{stake_id}_lock"
        current_height = self.get_block_height()
        
        stake = StakeInfo(
            stake_id=stake_id,
            staker_address=staker_address,
            amount=amount,
            start_height=current_height,
            start_time=int(time.time())
        )
        
        # Save to database
        self.conn.execute('''
            INSERT INTO stakes (stake_id, staker_address, amount, start_height, start_time)
            VALUES (?, ?, ?, ?, ?)
        ''', (stake_id, staker_address, amount, current_height, int(time.time())))

        for utxo in selected_utxos:
            self.conn.execute('''
                UPDATE utxos
                SET spent = TRUE, spent_txid = ?, spent_height = ?
                WHERE txid = ? AND vout = ?
            ''', (stake_lock_txid, current_height, utxo['txid'], utxo['vout']))

        change_amount = locked_total - amount
        if change_amount > 0:
            self.conn.execute('''
                INSERT INTO utxos (txid, vout, address, amount, script_pubkey, spent)
                VALUES (?, ?, ?, ?, ?, FALSE)
            ''', (stake_lock_txid, 0, staker_address, change_amount, b"stake_change"))

        self.conn.commit()
        
        # Store in memory
        self.stakes[stake_id] = asdict(stake)
        
        print(f"Created stake: {stake_id} for {amount / COIN} WEPO")
        return stake_id

    def deactivate_stake(self, stake_id: str, staker_address: str) -> dict:
        """Deactivate an active stake and release the principal back to spendable balance."""
        cursor = self.conn.execute('''
            SELECT stake_id, staker_address, amount, status, total_rewards
            FROM stakes
            WHERE stake_id = ?
        ''', (stake_id,))

        row = cursor.fetchone()
        if not row:
            raise ValueError("Stake not found")

        if row[1] != staker_address:
            raise ValueError("Stake does not belong to staker")

        if row[3] != 'active':
            raise ValueError("Stake is not active")

        current_height = self.get_block_height()
        unlock_txid = f"{stake_id}_unlock_{int(time.time())}"

        self.conn.execute('''
            UPDATE stakes
            SET status = 'inactive', unlock_height = ?
            WHERE stake_id = ?
        ''', (current_height, stake_id))

        self.conn.execute('''
            INSERT INTO utxos (txid, vout, address, amount, script_pubkey, spent)
            VALUES (?, ?, ?, ?, ?, FALSE)
        ''', (unlock_txid, 0, staker_address, row[2], b"stake_unlock"))

        self.conn.commit()

        if stake_id in self.stakes:
            self.stakes[stake_id]['status'] = 'inactive'
            self.stakes[stake_id]['unlock_height'] = current_height

        return {
            'stake_id': row[0],
            'staker_address': row[1],
            'amount': row[2],
            'total_rewards': row[4],
            'status': 'inactive',
            'unlock_height': current_height,
            'unlock_txid': unlock_txid,
        }
    
    def create_masternode(
        self,
        operator_address: str,
        collateral_txid: str,
        collateral_vout: int,
        ip_address: str = None,
        port: int = 22567,
    ) -> str:
        """Create a new masternode"""
        current_height = self.get_block_height()
        required_collateral = self.get_masternode_collateral_for_height(current_height)
        
        # Verify collateral UTXO exists and has correct amount
        cursor = self.conn.execute('''
            SELECT amount, spent FROM utxos WHERE txid = ? AND vout = ?
        ''', (collateral_txid, collateral_vout))
        
        utxo = cursor.fetchone()
        if not utxo or utxo[1] or utxo[0] < required_collateral:
            raise ValueError(f"Invalid collateral UTXO or insufficient amount")

        existing_cursor = self.conn.execute('''
            SELECT masternode_id
            FROM masternodes
            WHERE status = 'active' AND collateral_txid = ? AND collateral_vout = ?
        ''', (collateral_txid, collateral_vout))
        if existing_cursor.fetchone():
            raise ValueError("Collateral UTXO is already assigned to an active masternode")
        
        # Create masternode
        masternode_id = f"mn_{operator_address}_{int(time.time())}"
        
        masternode = MasternodeInfo(
            masternode_id=masternode_id,
            operator_address=operator_address,
            collateral_txid=collateral_txid,
            collateral_vout=collateral_vout,
            ip_address=ip_address,
            port=port,
            start_height=current_height,
            start_time=int(time.time())
        )
        
        # Save to database
        self.conn.execute('''
            INSERT INTO masternodes (masternode_id, operator_address, collateral_txid, collateral_vout, ip_address, port, start_height, start_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (masternode_id, operator_address, collateral_txid, collateral_vout, ip_address, port, current_height, int(time.time())))
        
        self.conn.commit()
        
        # Store in memory
        self.masternodes[masternode_id] = asdict(masternode)
        
        print(f"Created masternode: {masternode_id}")
        return masternode_id

    def deactivate_masternode(self, masternode_id: str, operator_address: str) -> dict:
        """Deactivate an active masternode and release its collateral back to spendable balance."""
        self.get_active_masternodes()

        cursor = self.conn.execute('''
            SELECT masternode_id, operator_address, collateral_txid, collateral_vout, status
            FROM masternodes
            WHERE masternode_id = ?
        ''', (masternode_id,))

        row = cursor.fetchone()
        if not row:
            raise ValueError("Masternode not found")

        if row[1] != operator_address:
            raise ValueError("Masternode does not belong to operator")

        if row[4] != 'active':
            raise ValueError("Masternode is not active")

        self.conn.execute('''
            UPDATE masternodes
            SET status = 'inactive'
            WHERE masternode_id = ?
        ''', (masternode_id,))
        self.conn.commit()

        if masternode_id in self.masternodes:
            self.masternodes[masternode_id]['status'] = 'inactive'

        return {
            'masternode_id': row[0],
            'operator_address': row[1],
            'collateral_txid': row[2],
            'collateral_vout': row[3],
            'status': 'inactive',
        }
    
    def get_masternode_collateral_for_height(self, height: int) -> int:
        """Get required masternode collateral for a specific height (tied to PoW halvings)"""
        # Find the appropriate collateral requirement for this height
        for trigger_height in sorted(DYNAMIC_MASTERNODE_COLLATERAL_SCHEDULE.keys(), reverse=True):
            if height >= trigger_height:
                collateral = DYNAMIC_MASTERNODE_COLLATERAL_SCHEDULE[trigger_height]
                # Apply minimum floor protection
                return max(MIN_MASTERNODE_COLLATERAL, collateral)
        
        # Fallback to initial requirement
        return DYNAMIC_MASTERNODE_COLLATERAL_SCHEDULE[0]
    
    def get_pos_collateral_for_height(self, height: int) -> int:
        """Get required PoS staking collateral for a specific height (tied to PoW halvings)"""
        # PoS is not available before activation height
        if height <= POS_ACTIVATION_HEIGHT:
            return 0
            
        # Find the appropriate collateral requirement for this height
        for trigger_height in sorted(DYNAMIC_POS_COLLATERAL_SCHEDULE.keys(), reverse=True):
            if height >= trigger_height:
                collateral = DYNAMIC_POS_COLLATERAL_SCHEDULE[trigger_height]
                # Apply minimum floor protection
                return max(MIN_POS_COLLATERAL, collateral)
        
        # Fallback to initial PoS requirement
        return DYNAMIC_POS_COLLATERAL_SCHEDULE[POS_ACTIVATION_HEIGHT]
    
    def get_collateral_info(self, height: int = None) -> dict:
        """Get comprehensive collateral information for a specific height"""
        if height is None:
            height = self.get_block_height()
        
        masternode_collateral = self.get_masternode_collateral_for_height(height)
        pos_collateral = self.get_pos_collateral_for_height(height)
        
        # Determine current phase
        phase_info = self.get_current_phase_info(height)
        
        return {
            'block_height': height,
            'masternode_collateral': masternode_collateral,
            'masternode_collateral_wepo': masternode_collateral / COIN,
            'pos_collateral': pos_collateral,
            'pos_collateral_wepo': pos_collateral / COIN,
            'pos_available': height > POS_ACTIVATION_HEIGHT,
            'phase': phase_info['phase'],
            'phase_description': phase_info['description'],
            'pow_reward': phase_info['pow_reward'],
            'next_adjustment': self.get_next_collateral_adjustment(height),
            'adjustment_reason': 'Tied to PoW halving schedule for network accessibility'
        }
    
    def get_current_phase_info(self, height: int) -> dict:
        """Get current mining phase information"""
        if height == 0:
            return {
                'phase': 'Genesis',
                'description': 'Genesis Bootstrap Block',
                'pow_reward': GENESIS_BOOTSTRAP_REWARD / COIN
            }
        elif height <= PRE_POS_DURATION_BLOCKS:
            return {
                'phase': 'Phase 1',
                'description': 'Pre-PoS Mining (Genesis)',
                'pow_reward': PRE_POS_REWARD / COIN
            }
        elif height <= PHASE_2A_END_HEIGHT:
            return {
                'phase': 'Phase 2A',
                'description': 'PoS Active, First Long-term Phase',
                'pow_reward': PHASE_2A_REWARD / COIN
            }
        elif height <= PHASE_2B_END_HEIGHT:
            return {
                'phase': 'Phase 2B',
                'description': 'Second Halving Phase',
                'pow_reward': PHASE_2B_REWARD / COIN
            }
        elif height <= PHASE_2C_END_HEIGHT:
            return {
                'phase': 'Phase 2C',
                'description': 'Third Halving Phase',
                'pow_reward': PHASE_2C_REWARD / COIN
            }
        elif height <= PHASE_2D_END_HEIGHT:
            return {
                'phase': 'Phase 2D',
                'description': 'Fourth Halving Phase',
                'pow_reward': PHASE_2D_REWARD / COIN
            }
        else:
            return {
                'phase': 'Phase 3',
                'description': 'Post-PoW (Fees Only)',
                'pow_reward': 0
            }
    
    def get_next_collateral_adjustment(self, height: int) -> dict:
        """Get information about the next collateral adjustment"""
        adjustment_heights = sorted(DYNAMIC_MASTERNODE_COLLATERAL_SCHEDULE.keys())
        
        for adj_height in adjustment_heights:
            if height < adj_height:
                blocks_remaining = adj_height - height
                
                # Calculate time remaining (approximate)
                if adj_height <= PRE_POS_DURATION_BLOCKS:
                    time_per_block = 6 * 60  # 6 minutes
                else:
                    time_per_block = 9 * 60  # 9 minutes
                
                days_remaining = (blocks_remaining * time_per_block) / (24 * 60 * 60)
                
                next_mn_collateral = DYNAMIC_MASTERNODE_COLLATERAL_SCHEDULE[adj_height]
                next_pos_collateral = DYNAMIC_POS_COLLATERAL_SCHEDULE.get(adj_height, 0)
                
                return {
                    'next_adjustment_height': adj_height,
                    'blocks_remaining': blocks_remaining,
                    'days_remaining': int(days_remaining),
                    'next_masternode_collateral': next_mn_collateral / COIN,
                    'next_pos_collateral': next_pos_collateral / COIN if next_pos_collateral > 0 else 0,
                    'adjustment_type': 'PoW Halving Event'
                }
        
        # No more adjustments
        return {
            'next_adjustment_height': None,
            'blocks_remaining': 0,
            'days_remaining': 0,
            'next_masternode_collateral': MIN_MASTERNODE_COLLATERAL / COIN,
            'next_pos_collateral': MIN_POS_COLLATERAL / COIN,
            'adjustment_type': 'Final (Floor Minimum)'
        }
    
    def get_active_stakes(self) -> List[StakeInfo]:
        """Get all active stakes"""
        cursor = self.conn.execute('''
            SELECT stake_id, staker_address, amount, start_height, start_time, last_reward_height, total_rewards, status, unlock_height
            FROM stakes WHERE status = 'active'
        ''')
        
        stakes = []
        for row in cursor.fetchall():
            stakes.append(StakeInfo(
                stake_id=row[0],
                staker_address=row[1],
                amount=row[2],
                start_height=row[3],
                start_time=row[4],
                last_reward_height=row[5],
                total_rewards=row[6],
                status=row[7],
                unlock_height=row[8]
            ))
        
        return stakes
    
    def get_active_masternodes(self) -> List[MasternodeInfo]:
        """Get all active masternodes"""
        self.conn.execute('''
            UPDATE masternodes
            SET status = 'inactive'
            WHERE status = 'active'
              AND NOT EXISTS (
                  SELECT 1
                  FROM utxos
                  WHERE utxos.txid = masternodes.collateral_txid
                    AND utxos.vout = masternodes.collateral_vout
                    AND utxos.spent = FALSE
              )
        ''')

        duplicate_cursor = self.conn.execute('''
            SELECT masternode_id, collateral_txid, collateral_vout
            FROM masternodes
            WHERE status = 'active'
            ORDER BY start_height ASC, start_time ASC, masternode_id ASC
        ''')
        seen_collateral = set()
        duplicate_ids = []
        for row in duplicate_cursor.fetchall():
            collateral_key = (row[1], row[2])
            if collateral_key in seen_collateral:
                duplicate_ids.append(row[0])
            else:
                seen_collateral.add(collateral_key)

        if duplicate_ids:
            placeholders = ",".join("?" for _ in duplicate_ids)
            self.conn.execute(
                f"UPDATE masternodes SET status = 'inactive' WHERE masternode_id IN ({placeholders})",
                tuple(duplicate_ids),
            )
        self.conn.commit()

        cursor = self.conn.execute('''
            SELECT masternode_id, operator_address, collateral_txid, collateral_vout, ip_address, port, start_height, start_time, last_ping, status, total_rewards
            FROM masternodes WHERE status = 'active'
        ''')
        
        masternodes = []
        for row in cursor.fetchall():
            masternodes.append(MasternodeInfo(
                masternode_id=row[0],
                operator_address=row[1],
                collateral_txid=row[2],
                collateral_vout=row[3],
                ip_address=row[4],
                port=row[5],
                start_height=row[6],
                start_time=row[7],
                last_ping=row[8],
                status=row[9],
                total_rewards=row[10]
            ))
        
        return masternodes

    def get_masternodes_for_operator(self, operator_address: str) -> List[MasternodeInfo]:
        """Get masternodes for a specific operator, newest first."""
        self.get_active_masternodes()

        cursor = self.conn.execute('''
            SELECT masternode_id, operator_address, collateral_txid, collateral_vout, ip_address, port, start_height, start_time, last_ping, status, total_rewards
            FROM masternodes
            WHERE operator_address = ?
            ORDER BY start_time DESC, masternode_id DESC
        ''', (operator_address,))

        masternodes = []
        for row in cursor.fetchall():
            masternodes.append(MasternodeInfo(
                masternode_id=row[0],
                operator_address=row[1],
                collateral_txid=row[2],
                collateral_vout=row[3],
                ip_address=row[4],
                port=row[5],
                start_height=row[6],
                start_time=row[7],
                last_ping=row[8],
                status=row[9],
                total_rewards=row[10]
            ))

        return masternodes

    def calculate_staking_reward_entries(self, block_height: int) -> List[Dict[str, Union[str, int]]]:
        """Calculate detailed PoS reward entries for active stakes and masternodes."""
        reward_entries = []

        if block_height <= POS_ACTIVATION_HEIGHT:
            return reward_entries

        active_stakes = self.get_active_stakes()
        active_masternodes = self.get_active_masternodes()

        if not active_stakes and not active_masternodes:
            return reward_entries

        total_pos_reward = self.calculate_pos_reward(block_height)
        if total_pos_reward <= 0:
            return reward_entries

        staking_reward_pool = int(total_pos_reward * 0.6)
        masternode_reward_pool = int(total_pos_reward * 0.4)

        if active_stakes and staking_reward_pool > 0:
            total_stake_amount = sum(stake.amount for stake in active_stakes)
            remaining_rewards = staking_reward_pool

            for index, stake in enumerate(active_stakes):
                if index == len(active_stakes) - 1:
                    reward_amount = remaining_rewards
                else:
                    reward_amount = int(staking_reward_pool * (stake.amount / total_stake_amount))
                    reward_amount = min(reward_amount, remaining_rewards)

                if reward_amount <= 0:
                    continue

                remaining_rewards -= reward_amount
                reward_entries.append({
                    'reward_id': f"reward_staker_{block_height}_{stake.stake_id}",
                    'recipient_address': stake.staker_address,
                    'recipient_type': 'staker',
                    'recipient_reference': stake.stake_id,
                    'amount': reward_amount,
                })

        if active_masternodes and masternode_reward_pool > 0:
            reward_per_masternode = masternode_reward_pool // len(active_masternodes)
            reward_remainder = masternode_reward_pool % len(active_masternodes)

            for index, masternode in enumerate(active_masternodes):
                reward_amount = reward_per_masternode + (1 if index < reward_remainder else 0)
                if reward_amount <= 0:
                    continue

                reward_entries.append({
                    'reward_id': f"reward_masternode_{block_height}_{masternode.masternode_id}",
                    'recipient_address': masternode.operator_address,
                    'recipient_type': 'masternode',
                    'recipient_reference': masternode.masternode_id,
                    'amount': reward_amount,
                })

        return reward_entries
    
    def calculate_staking_rewards(self, block_height: int) -> Dict[str, int]:
        """Calculate staking rewards for a block"""
        rewards = {}
        for reward_entry in self.calculate_staking_reward_entries(block_height):
            address = reward_entry['recipient_address']
            rewards[address] = rewards.get(address, 0) + reward_entry['amount']
        return rewards
    
    def calculate_pos_reward(self, block_height: int) -> int:
        """Calculate PoS reward for a block height"""
        if block_height <= POS_ACTIVATION_HEIGHT:
            return 0
        
        # After PoS activation, use a decreasing reward schedule
        # This is separate from PoW rewards and represents newly minted coins for PoS
        years_since_pos = (block_height - POS_ACTIVATION_HEIGHT) // BLOCKS_PER_YEAR_LONGTERM
        
        if years_since_pos < 2:
            base_reward = 25 * COIN  # 25 WEPO per block for first 2 years
        elif years_since_pos < 5:
            base_reward = 12.5 * COIN  # 12.5 WEPO per block for years 2-5
        elif years_since_pos < 10:
            base_reward = 6.25 * COIN  # 6.25 WEPO per block for years 5-10
        else:
            # Continue halving every 5 years
            halvings = (years_since_pos - 10) // 5
            base_reward = 6.25 * COIN
            for _ in range(halvings):
                base_reward //= 2

        # The returned value is the total PoS reward pool for the block.
        # Downstream distribution splits it between stakers and masternodes.
        return int(base_reward * 0.5)
    
    def distribute_staking_rewards(self, block_height: int, block_hash: str):
        """Distribute staking rewards for a block"""
        try:
            reward_entries = self.calculate_staking_reward_entries(block_height)
            
            for reward_entry in reward_entries:
                address = reward_entry['recipient_address']
                reward_amount = reward_entry['amount']
                # Create reward UTXO
                reward_txid = f"pos_reward_{reward_entry['reward_id']}"
                
                self.conn.execute('''
                    INSERT INTO utxos (txid, vout, address, amount, script_pubkey, spent)
                    VALUES (?, ?, ?, ?, ?, FALSE)
                ''', (reward_txid, 0, address, reward_amount, b"pos_reward"))

                if reward_entry['recipient_type'] == 'staker':
                    self.conn.execute('''
                        UPDATE stakes
                        SET total_rewards = total_rewards + ?, last_reward_height = ?
                        WHERE stake_id = ?
                    ''', (reward_amount, block_height, reward_entry['recipient_reference']))
                elif reward_entry['recipient_type'] == 'masternode':
                    self.conn.execute('''
                        UPDATE masternodes
                        SET total_rewards = total_rewards + ?, last_ping = ?
                        WHERE masternode_id = ?
                    ''', (reward_amount, int(time.time()), reward_entry['recipient_reference']))
                
                # Record reward in history
                self.conn.execute('''
                    INSERT INTO staking_rewards (reward_id, recipient_address, recipient_type, amount, block_height, block_hash, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    reward_entry['reward_id'],
                    address,
                    reward_entry['recipient_type'],
                    reward_amount,
                    block_height,
                    block_hash,
                    int(time.time()),
                ))
            
            self.conn.commit()
            
        except Exception as e:
            print(f"Error distributing staking rewards: {e}")

    def record_fee_distribution_rewards(self, block: Block):
        """Record staking and masternode fee distributions from a block coinbase."""
        try:
            if not block.transactions:
                return

            coinbase_tx = block.transactions[0]
            if not coinbase_tx.is_coinbase():
                return

            for output_index, output in enumerate(coinbase_tx.outputs[1:], start=1):
                script_marker = output.script_pubkey.decode(errors='ignore') if output.script_pubkey else ''
                reward_timestamp = int(time.time())

                if script_marker.startswith("staker_fee_output:"):
                    stake_id = script_marker.split(":", 1)[1]
                    reward_id = f"fee_reward_staker_{block.height}_{output_index}_{stake_id}"
                    self.conn.execute('''
                        UPDATE stakes
                        SET total_rewards = total_rewards + ?, last_reward_height = ?
                        WHERE stake_id = ?
                    ''', (output.value, block.height, stake_id))
                    self.conn.execute('''
                        INSERT OR IGNORE INTO staking_rewards (reward_id, recipient_address, recipient_type, amount, block_height, block_hash, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        reward_id,
                        output.address,
                        'staker',
                        output.value,
                        block.height,
                        block.get_block_hash(),
                        reward_timestamp,
                    ))
                elif script_marker.startswith("masternode_fee_output:"):
                    masternode_id = script_marker.split(":", 1)[1]
                    reward_id = f"fee_reward_masternode_{block.height}_{output_index}_{masternode_id}"
                    self.conn.execute('''
                        UPDATE masternodes
                        SET total_rewards = total_rewards + ?, last_ping = ?
                        WHERE masternode_id = ?
                    ''', (output.value, reward_timestamp, masternode_id))
                    self.conn.execute('''
                        INSERT OR IGNORE INTO staking_rewards (reward_id, recipient_address, recipient_type, amount, block_height, block_hash, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        reward_id,
                        output.address,
                        'masternode',
                        output.value,
                        block.height,
                        block.get_block_hash(),
                        reward_timestamp,
                    ))

            self.conn.commit()
        except Exception as e:
            print(f"Error recording fee distribution rewards: {e}")
    
    def get_staking_info(self) -> dict:
        """Get staking system information"""
        try:
            current_height = self.get_block_height()
            active_stakes = self.get_active_stakes()
            total_staked = sum(stake.amount for stake in active_stakes)
            
            # Calculate activation info
            activation_info = self.get_pos_activation_info()
            
            return {
                "staking_enabled": current_height > POS_ACTIVATION_HEIGHT,
                "pos_activation_height": POS_ACTIVATION_HEIGHT,
                "pos_first_active_height": POS_ACTIVATION_HEIGHT + 1,
                "current_height": current_height,
                "blocks_until_activation": max(0, (POS_ACTIVATION_HEIGHT + 1) - current_height),
                "production_mode": PRODUCTION_MODE,
                "network_profile": NETWORK_PROFILE_NAME,
                "network": NETWORK_NAME,
                "genesis_launch": datetime.fromtimestamp(MAINNET_GENESIS_TIMESTAMP).isoformat(),
                "staking_activation_date": activation_info["activation_date"],
                "days_until_staking": activation_info["days_until_activation"],
                "min_stake_amount": MIN_STAKE_AMOUNT / COIN,
                "min_masternode_collateral": self.get_masternode_collateral_for_height(current_height) / COIN,
                "total_staked": total_staked / COIN,
                "active_stakes_count": len(active_stakes),
                "total_stakers": len(set(stake.staker_address for stake in active_stakes)),
                "staking_apy": self.calculate_staking_apy(),
                "fee_distribution": {
                    "masternodes": "60%",
                    "miners": "25%", 
                    "stakers": "15%"
                }
            }
            
        except Exception as e:
            print(f"Error getting staking info: {e}")
            return {"error": str(e)}

    def get_reward_summary_for_address(self, address: str) -> dict:
        """Get credited reward totals and recent reward history for a wallet."""
        totals_cursor = self.conn.execute('''
            SELECT recipient_type, COALESCE(SUM(amount), 0)
            FROM staking_rewards
            WHERE recipient_address = ?
            GROUP BY recipient_type
        ''', (address,))

        staker_total = 0
        masternode_total = 0
        for recipient_type, total_amount in totals_cursor.fetchall():
            if recipient_type == 'staker':
                staker_total = total_amount or 0
            elif recipient_type == 'masternode':
                masternode_total = total_amount or 0

        rewards_cursor = self.conn.execute('''
            SELECT reward_id, recipient_type, amount, block_height, block_hash, timestamp
            FROM staking_rewards
            WHERE recipient_address = ?
            ORDER BY block_height DESC, timestamp DESC
            LIMIT 25
        ''', (address,))

        recent_rewards = []
        for row in rewards_cursor.fetchall():
            recent_rewards.append({
                'reward_id': row[0],
                'recipient_type': row[1],
                'amount': row[2] / COIN,
                'amount_atomic': row[2],
                'block_height': row[3],
                'block_hash': row[4],
                'timestamp': row[5],
            })

        total_rewards = staker_total + masternode_total
        return {
            'address': address,
            'total_rewards': total_rewards / COIN,
            'total_rewards_atomic': total_rewards,
            'staker_rewards': staker_total / COIN,
            'masternode_rewards': masternode_total / COIN,
            'reward_events': len(recent_rewards),
            'recent_rewards': recent_rewards,
        }
    
    def get_pos_activation_info(self) -> dict:
        """Get PoS activation timing information"""
        try:
            if NETWORK_PROFILE_NAME == "test":
                activation_timestamp = MAINNET_GENESIS_TIMESTAMP + STAKING_ACTIVATION_DELAY
                activation_date = datetime.fromtimestamp(activation_timestamp).isoformat()
                return {
                    "activation_date": activation_date,
                    "days_until_activation": 0,
                    "activation_timestamp": activation_timestamp,
                    "mode": "accelerated_test_profile",
                }
            if PRODUCTION_MODE:
                return {
                    "activation_date": "Immediately (Production Mode)",
                    "days_until_activation": 0,
                    "activation_timestamp": 0
                }
            else:
                # Calculate 18 months from the configured genesis timestamp
                activation_timestamp = MAINNET_GENESIS_TIMESTAMP + STAKING_ACTIVATION_DELAY
                activation_date = datetime.fromtimestamp(activation_timestamp).isoformat()
                
                # Calculate days until activation
                current_time = int(time.time())
                days_until = max(0, (activation_timestamp - current_time) // (24 * 60 * 60))
                
                return {
                    "activation_date": activation_date,
                    "days_until_activation": days_until,
                    "activation_timestamp": activation_timestamp
                }
        except Exception as e:
            return {
                "activation_date": "Error calculating",
                "days_until_activation": 0,
                "activation_timestamp": 0
            }
    
    def calculate_staking_apy(self) -> float:
        """Calculate estimated annual percentage yield for staking"""
        try:
            # Simplified APY calculation based on 15% of all fees
            # This would be more sophisticated in production with historical data
            total_staked = self.get_total_staked()
            if total_staked == 0:
                return 0.0
            
            # Estimate based on network activity and fee generation
            # Assumption: Network generates fees worth 1% of total supply annually
            estimated_annual_fees = TOTAL_SUPPLY * 0.01  # 1% of total supply
            staker_share = estimated_annual_fees * 0.15  # 15% goes to stakers
            
            if total_staked > 0:
                apy = (staker_share / total_staked) * 100
                return min(apy, 25.0)  # Cap at 25% APY for display
            
            return 0.0
            
        except Exception as e:
            print(f"Error calculating staking APY: {e}")
            return 0.0
    
    def activate_production_staking(self) -> dict:
        """Activate staking for production testing"""
        try:
            global PRODUCTION_MODE, POS_ACTIVATION_HEIGHT
            
            if not PRODUCTION_MODE:
                PRODUCTION_MODE = True
                POS_ACTIVATION_HEIGHT = max(1, self.get_block_height())
                
                return {
                    "success": True,
                    "message": "Production staking activates from the next block",
                    "pos_activation_height": POS_ACTIVATION_HEIGHT,
                    "pos_first_active_height": POS_ACTIVATION_HEIGHT + 1,
                    "staking_enabled": self.get_block_height() > POS_ACTIVATION_HEIGHT,
                    "min_stake_amount": MIN_STAKE_AMOUNT / COIN,
                    "fee_distribution_active": True
                }
            else:
                return {
                    "success": True,
                    "message": "Production staking already active",
                    "pos_activation_height": POS_ACTIVATION_HEIGHT,
                    "pos_first_active_height": POS_ACTIVATION_HEIGHT + 1,
                    "staking_enabled": self.get_block_height() > POS_ACTIVATION_HEIGHT
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_total_staked(self) -> int:
        """Get total amount staked in the network"""
        cursor = self.conn.execute('''
            SELECT SUM(amount) FROM stakes WHERE status = 'active'
        ''')
        result = cursor.fetchone()
        return result[0] if result[0] else 0
    
    def select_pos_validator(self, block_height: int) -> Optional[str]:
        """Select PoS validator using stake-weighted random selection"""
        if block_height <= POS_ACTIVATION_HEIGHT:
            return None
            
        # Get active stakes
        active_stakes = self.get_active_stakes()
        if not active_stakes:
            return None
            
        # Calculate total stake
        total_stake = sum(stake.amount for stake in active_stakes)
        if total_stake == 0:
            return None
            
        # Generate random point in stake range
        import random
        random.seed(block_height)  # Deterministic seed for consensus
        random_point = random.randint(0, total_stake - 1)
        
        # Find validator at random point
        cumulative_stake = 0
        for stake in active_stakes:
            cumulative_stake += stake.amount
            if cumulative_stake > random_point:
                return stake.staker_address
                
        # Fallback to first validator
        return active_stakes[0].staker_address if active_stakes else None
    
    def is_valid_pos_validator(self, validator_address: str, block_height: int) -> bool:
        """Check if address is a valid PoS validator"""
        if block_height <= POS_ACTIVATION_HEIGHT:
            return False
            
        # Check if validator has active stake
        active_stakes = self.get_active_stakes()
        validator_stakes = [stake for stake in active_stakes if stake.staker_address == validator_address]
        
        return len(validator_stakes) > 0 and sum(stake.amount for stake in validator_stakes) >= MIN_STAKE_AMOUNT
    
    def get_network_info(self) -> dict:
        """Get network information"""
        current_height = self.get_block_height()
        consensus_type = self.get_consensus_type(current_height)
        
        network_info = {
            'height': current_height,
            'best_block_hash': self.get_latest_block().get_block_hash() if self.chain else None,
            'difficulty': self.current_difficulty,
            'mempool_size': len(self.mempool),
            'total_supply': sum(self.calculate_block_reward(i) for i in range(len(self.chain))),
            'network': NETWORK_NAME,
            'network_profile': NETWORK_PROFILE_NAME,
            'version': WEPO_VERSION,
            'consensus_type': consensus_type
        }
        
        # Add hybrid consensus info if active
        if consensus_type == "hybrid":
            network_info.update({
                'hybrid_consensus': {
                    'pow_block_time': format_block_time(BLOCK_TIME_POW_HYBRID),
                    'pos_block_time': format_block_time(BLOCK_TIME_POS),
                    'pos_activated': True,
                    'pos_activation_height': POS_ACTIVATION_HEIGHT,
                    'total_staked': self.get_total_staked(),
                    'active_validators': len(self.get_active_stakes())
                }
            })
        
        return network_info

    def get_blockchain_info(self) -> dict:
        """Backward-compatible node-facing blockchain status wrapper"""
        info = self.get_network_info()
        info.update({
            "chain_height": info["height"],
            "latest_block_hash": info["best_block_hash"],
        })
        return info

    def get_last_block_timestamp(self, consensus_type: Optional[str] = None) -> Optional[int]:
        """Return the latest block timestamp, optionally filtered by consensus type."""
        for block in reversed(self.chain):
            if consensus_type is None or block.header.consensus_type == consensus_type:
                return block.header.timestamp
        return None

    def mine_next_block(self, miner_address: str) -> Optional[Block]:
        """Mine or validate the next due block for the active consensus schedule."""
        current_height = self.get_block_height()
        if current_height < POS_ACTIVATION_HEIGHT:
            return self.mine_block(miner_address)

        latest_block = self.get_latest_block()
        if latest_block is None:
            return self.mine_block(miner_address)

        now = int(time.time())
        next_height = current_height + 1
        last_pow_timestamp = self.get_last_block_timestamp("pow")
        last_pos_timestamp = self.get_last_block_timestamp("pos")
        fallback_timestamp = latest_block.header.timestamp

        pow_due_at = (last_pow_timestamp if last_pow_timestamp is not None else fallback_timestamp) + BLOCK_TIME_POW_HYBRID

        pos_due_at = None
        active_stakes = self.get_active_stakes()
        if active_stakes:
            pos_anchor = last_pos_timestamp if last_pos_timestamp is not None else fallback_timestamp
            pos_due_at = pos_anchor + BLOCK_TIME_POS

        pos_ready = pos_due_at is not None and now >= pos_due_at
        pow_ready = now >= pow_due_at

        if pos_ready and (not pow_ready or pos_due_at <= pow_due_at):
            validator = self.select_pos_validator(next_height)
            if validator:
                pos_block = self.create_pos_block(validator)
                if pos_block and self.add_block(pos_block):
                    return pos_block

        if pow_ready:
            return self.mine_block(miner_address)

        if pos_ready:
            validator = self.select_pos_validator(next_height)
            if validator:
                pos_block = self.create_pos_block(validator)
                if pos_block and self.add_block(pos_block):
                    return pos_block

        return None

def main():
    """Main function for testing"""
    blockchain = WepoBlockchain()
    
    # Test mining a few blocks
    test_address = "wepo1test00000000000000000000000000000"
    
    for i in range(5):
        print(f"\n--- Mining block {i+1} ---")
        block = blockchain.mine_block(test_address)
        if block:
            print(f"Block {block.height} mined successfully!")
            print(f"Reward: {blockchain.calculate_block_reward(block.height) / COIN} WEPO")
        else:
            print("Mining failed")
            break
    
    # Display network info
    print("\n--- Network Info ---")
    info = blockchain.get_network_info()
    for key, value in info.items():
        print(f"{key}: {value}")

if __name__ == "__main__":
    main()
