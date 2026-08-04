#!/usr/bin/env python3
"""
WEPO Core Blockchain Implementation
Revolutionary cryptocurrency with hybrid PoW/PoS consensus and privacy features
"""
import hashlib
import json
import time
import struct
import threading
from functools import wraps
from typing import Any, List, Dict, Optional, Set, Tuple, Union
from dataclasses import dataclass, asdict
from datetime import datetime
import argon2
import sqlite3
import os
try:
    from .address_utils import generate_wepo_address, validate_wepo_address, is_quantum_address, addresses_equal
except ImportError:
    from address_utils import generate_wepo_address, validate_wepo_address, is_quantum_address, addresses_equal
try:
    from .dilithium import (
        DILITHIUM_PUBKEY_SIZE,
        DILITHIUM_SIGNATURE_SIZE,
        verify_dilithium_signature,
    )
except ImportError:
    from dilithium import (
        DILITHIUM_PUBKEY_SIZE,
        DILITHIUM_SIGNATURE_SIZE,
        verify_dilithium_signature,
    )
try:
    from .validator_signer import PosSigningContext, ValidatorSigner
except ImportError:
    from validator_signer import PosSigningContext, ValidatorSigner
try:
    from .network_profile import (
        format_block_time,
        MAINNET_GENESIS_TIMESTAMP as PROFILE_MAINNET_GENESIS_TIMESTAMP,
        PRE_POS_REWARD as PROFILE_PRE_POS_REWARD,
        PHASE_2A_REWARD as PROFILE_PHASE_2A_REWARD,
        PHASE_2B_REWARD as PROFILE_PHASE_2B_REWARD,
        PHASE_2C_REWARD as PROFILE_PHASE_2C_REWARD,
        PHASE_2D_REWARD as PROFILE_PHASE_2D_REWARD,
        MAINNET_GHOST_CONSENSUS_READY as PROFILE_MAINNET_GHOST_CONSENSUS_READY,
        MAINNET_GHOST_ACTIVATION_HEIGHT as PROFILE_MAINNET_GHOST_ACTIVATION_HEIGHT,
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
        MAINNET_GHOST_CONSENSUS_READY as PROFILE_MAINNET_GHOST_CONSENSUS_READY,
        MAINNET_GHOST_ACTIVATION_HEIGHT as PROFILE_MAINNET_GHOST_ACTIVATION_HEIGHT,
        get_network_profile,
    )

# WEPO Network Constants
WEPO_VERSION = 70001
NETWORK_MAGIC = b'WEPO'
DEFAULT_PORT = 22567
COIN = 100000000  # 1 WEPO = 100,000,000 satoshis
DEFAULT_TRANSACTION_FEE = 10000
MAX_BLOCK_SIZE = 2 * 1024 * 1024  # 2MB
MAX_BLOCK_TRANSACTIONS = 4096
MAX_PENDING_BLOCKS = 2048
MAX_PENDING_CHILDREN_PER_PARENT = 16
MAX_ORPHAN_HEIGHT_AHEAD = 2048
MAX_MEMPOOL_TRANSACTIONS = 10000
MAX_MEMPOOL_BYTES = 64 * 1024 * 1024
MAX_TRANSACTION_WIRE_SIZE = 1024 * 1024
MAX_TRANSACTION_INPUTS = 32
MAX_TRANSACTION_OUTPUTS = 256
MAX_TRANSACTION_EXTRA_DATA_BYTES = 64 * 1024
MAX_TRANSACTION_SCRIPT_BYTES = 4096
MAX_FUTURE_BLOCK_TIME_DRIFT = 2 * 60 * 60  # 2 hours


def _chain_state_locked(method):
    """Serialize canonical-chain mutations across P2P and node threads."""
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self.chain_lock:
            return method(self, *args, **kwargs)
    return locked
TRANSACTION_VERSION = 1
MAX_LOCK_TIME = 0xFFFFFFFF
MAX_SEQUENCE = 0xFFFFFFFF
MAX_OUTPUT_INDEX = 0xFFFFFFFF
MAX_SAFE_JSON_INTEGER = (1 << 53) - 1

# WEPO 20-YEAR MINING SCHEDULE - SUSTAINABLE LONG-TERM POW
# Genesis timing is controlled by the configured mainnet timestamp.
GENESIS_TIME = PROFILE_MAINNET_GENESIS_TIMESTAMP  # configured genesis timestamp

# Total Supply - DEFINITIVE VALUE
TOTAL_SUPPLY = 69000003  # 69,000,003 WEPO total supply
# HARD SUPPLY CAP (consensus-enforced). The 400 WEPO genesis bootstrap is counted
# INSIDE this cap (owner decision D1, 2026-06-20). Cumulative base-reward issuance
# (genesis + PoW + PoS) is clamped so the network total can never exceed this.
# Transaction-fee redistribution is NOT new issuance and is excluded from the cap.
SUPPLY_CAP = TOTAL_SUPPLY * COIN  # 69,000,003 WEPO in base units

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
PRE_POS_TOTAL_SUPPLY = PRE_POS_REWARD * PRE_POS_DURATION_BLOCKS

# Long-term PoW phases (alongside PoS/Masternodes) - 20% of total supply
BLOCKS_PER_YEAR_LONGTERM = 36_525 * 24 * 60 // (100 * 9)  # 58,440 blocks/year
# NOTE (owner decision D2, 2026-06-20): emission phases are bounded by BLOCK HEIGHT,
# not wall-clock time. With hybrid PoW/PoS the real calendar duration of each phase
# differs from the "3yr/6yr" labels below (PoS blocks arrive faster than PoW), so
# those year labels are nominal targets used only to size per-block rewards. The
# exact total is guaranteed by SUPPLY_CAP, not by the phase math summing precisely.

# PHASE 2A: Post-PoS Years 1-3 (Months 19-54)
PHASE_2A_BLOCKS = 3 * BLOCKS_PER_YEAR_LONGTERM  # 175,320 blocks
PHASE_2A_REWARD = PROFILE_PHASE_2A_REWARD  # 33.17 WEPO per block
PHASE_2A_END_HEIGHT = PRE_POS_DURATION_BLOCKS + PHASE_2A_BLOCKS

# PHASE 2B: Post-PoS Years 4-9 (Months 55-126) - First Halving
PHASE_2B_BLOCKS = 6 * BLOCKS_PER_YEAR_LONGTERM  # 350,640 blocks
PHASE_2B_REWARD = PROFILE_PHASE_2B_REWARD  # 16.58 WEPO per block (halved)
PHASE_2B_END_HEIGHT = PHASE_2A_END_HEIGHT + PHASE_2B_BLOCKS

# PHASE 2C: Post-PoS Years 10-12 (Months 127-162) - Second Halving
PHASE_2C_BLOCKS = 3 * BLOCKS_PER_YEAR_LONGTERM  # 175,320 blocks
PHASE_2C_REWARD = PROFILE_PHASE_2C_REWARD  # 8.29 WEPO per block (halved)
PHASE_2C_END_HEIGHT = PHASE_2B_END_HEIGHT + PHASE_2C_BLOCKS

# PHASE 2D: Post-PoS Years 13-15 (Months 163-198) - Final Halving
PHASE_2D_BLOCKS = 3 * BLOCKS_PER_YEAR_LONGTERM  # 175,320 blocks
PHASE_2D_REWARD = PROFILE_PHASE_2D_REWARD  # 4.15 WEPO per block (final halving)
PHASE_2D_END_HEIGHT = PHASE_2C_END_HEIGHT + PHASE_2D_BLOCKS

# Total PoW ends at block 1,008,000 (16.5 nominal years after PoS activation)
POW_END_HEIGHT = PHASE_2D_END_HEIGHT

# Exact scheduled PoW subsidies, excluding the separate genesis bootstrap.
TOTAL_POW_SUPPLY = (
    PRE_POS_TOTAL_SUPPLY
    + PHASE_2A_REWARD * PHASE_2A_BLOCKS
    + PHASE_2B_REWARD * PHASE_2B_BLOCKS
    + PHASE_2C_REWARD * PHASE_2C_BLOCKS
    + PHASE_2D_REWARD * PHASE_2D_BLOCKS
)

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
PRODUCTION_MODE = True
NETWORK_PROFILE_NAME = "mainnet"
NETWORK_NAME = "mainnet"
MIN_STAKE_AMOUNT = 1000 * COIN
DYNAMIC_MASTERNODE_COLLATERAL_SCHEDULE = {}
DYNAMIC_POS_COLLATERAL_SCHEDULE = {}
MIN_MASTERNODE_COLLATERAL = 1000 * COIN
MIN_POS_COLLATERAL = 100 * COIN
MASTERNODE_COLLATERAL = 10000 * COIN
POS_ACTIVATION_HEIGHT = TOTAL_INITIAL_BLOCKS

TX_TYPE_TRANSFER = "transfer"
TX_TYPE_STAKE_CREATE = "stake_create"
TX_TYPE_STAKE_DEACTIVATE = "stake_deactivate"
TX_TYPE_MASTERNODE_CREATE = "masternode_create"
TX_TYPE_MASTERNODE_DEACTIVATE = "masternode_deactivate"
TX_TYPE_RWA_CREATE = "rwa_create"

# Ghost is activated only by a reviewed consensus height in released code.
# Environment flags may gate services, but they must never change consensus.
SHIELDED_ACTIVATION_HEIGHT: Optional[int] = PROFILE_MAINNET_GHOST_ACTIVATION_HEIGHT
PRIVACY_CONSENSUS_ENABLED = PROFILE_MAINNET_GHOST_CONSENSUS_READY


def _shielded_active_at(height: int) -> bool:
    return (
        PRIVACY_CONSENSUS_ENABLED
        and SHIELDED_ACTIVATION_HEIGHT is not None
        and height >= SHIELDED_ACTIVATION_HEIGHT
    )


def _shielded_bundle_to_dict(bundle: Any, *, include_proof: bool = True) -> Optional[Dict[str, Any]]:
    if bundle is None:
        return None
    result = {
        "spends": [
            {"anchor": spend.anchor.hex(), "nullifier": spend.nullifier.hex()}
            for spend in bundle.spends
        ],
        "outputs": [
            {
                "commitment": output.commitment.hex(),
                "enc_note": bytes(output.enc_note).hex(),
            }
            for output in bundle.outputs
        ],
        "value_balance": bundle.value_balance,
    }
    if include_proof:
        result["proof"] = bytes(bundle.proof).hex()
    return result


def _shielded_bundle_from_dict(data: Optional[Dict[str, Any]]) -> Any:
    if data is None:
        return None
    if not isinstance(data, dict) or set(data) - {
        "spends",
        "outputs",
        "value_balance",
        "proof",
    }:
        raise ValueError("Shielded bundle has an invalid wire schema")
    try:
        from .shielded import (
            MAX_SHIELDED_OUTPUTS,
            MAX_SHIELDED_PROOF_BYTES,
            MAX_SHIELDED_SPENDS,
            OutputDescription,
            ShieldedBundle,
            SpendDescription,
        )
    except ImportError:
        from shielded import (
            MAX_SHIELDED_OUTPUTS,
            MAX_SHIELDED_PROOF_BYTES,
            MAX_SHIELDED_SPENDS,
            OutputDescription,
            ShieldedBundle,
            SpendDescription,
        )

    spends = data.get("spends", [])
    outputs = data.get("outputs", [])
    proof = data.get("proof", "")
    if (
        not isinstance(spends, list)
        or len(spends) > MAX_SHIELDED_SPENDS
        or not isinstance(outputs, list)
        or len(outputs) > MAX_SHIELDED_OUTPUTS
        or not isinstance(proof, str)
        or len(proof) > MAX_SHIELDED_PROOF_BYTES * 2
        or type(data.get("value_balance", 0)) is not int
    ):
        raise ValueError("Shielded bundle exceeds wire resource limits")

    for item in spends:
        if (
            not isinstance(item, dict)
            or set(item) != {"anchor", "nullifier"}
            or not all(isinstance(item[field], str) for field in item)
        ):
            raise ValueError("Shielded spend has an invalid wire schema")
    for item in outputs:
        if (
            not isinstance(item, dict)
            or set(item) - {"commitment", "enc_note"}
            or "commitment" not in item
            or not all(isinstance(item[field], str) for field in item)
        ):
            raise ValueError("Shielded output has an invalid wire schema")

    return ShieldedBundle(
        spends=[
            SpendDescription(
                anchor=bytes.fromhex(item["anchor"]),
                nullifier=bytes.fromhex(item["nullifier"]),
            )
            for item in spends
        ],
        outputs=[
            OutputDescription(
                commitment=bytes.fromhex(item["commitment"]),
                enc_note=bytes.fromhex(item.get("enc_note", "")),
            )
            for item in outputs
        ],
        value_balance=int(data.get("value_balance", 0)),
        proof=bytes.fromhex(proof),
    )

# Real-world-asset on-chain issuance. An rwa_create tx is an ordinary
# self-custody (Dilithium-signed) transaction that pays an anti-spam fee and
# anchors an asset commitment in extra_data: the asset_hash (sha256 of the
# off-chain asset definition/document) bound to the owner address. Ownership and
# authenticity are proven by the on-chain, signed commitment — not a backend DB.
RWA_CREATION_MIN_FEE = 10000  # 0.0001 WEPO anti-spam minimum (atomic units)
RWA_ASSET_HASH_HEX_LEN = 64   # sha256 hex digest length

TX_TYPE_KEY_REGISTER = "key_register"
# On-chain anchoring of a user's messaging public keys, so key discovery is
# trustless (no reliance on the relay registry). A key_register tx is an ordinary
# self-custody (Dilithium-signed) transaction that pays an anti-spam fee and
# anchors the owner's ML-KEM-768 + ML-DSA-44 messaging public keys in extra_data,
# bound to the owner address (inputs must belong to the owner). Latest wins.
MSG_KEY_REGISTER_MIN_FEE = 10000        # 0.0001 WEPO anti-spam minimum
ML_KEM768_PUB_HEX_LEN = 1184 * 2        # 2368 hex chars
ML_DSA44_PUB_HEX_LEN = 1312 * 2         # 2624 hex chars

PROTOCOL_LIFECYCLE_TX_TYPES = {
    TX_TYPE_STAKE_CREATE,
    TX_TYPE_STAKE_DEACTIVATE,
    TX_TYPE_MASTERNODE_CREATE,
    TX_TYPE_MASTERNODE_DEACTIVATE,
}
VALID_TRANSACTION_TYPES = {
    TX_TYPE_TRANSFER,
    TX_TYPE_STAKE_CREATE,
    TX_TYPE_STAKE_DEACTIVATE,
    TX_TYPE_MASTERNODE_CREATE,
    TX_TYPE_MASTERNODE_DEACTIVATE,
    TX_TYPE_RWA_CREATE,
    TX_TYPE_KEY_REGISTER,
}
# These metadata-only transactions may spend an exact-fee input and therefore
# legitimately have no transparent outputs. Their fees are still canonically
# redistributed through the block coinbase; they are not burned.
FEE_ONLY_METADATA_TX_TYPES = {
    TX_TYPE_RWA_CREATE,
    TX_TYPE_KEY_REGISTER,
}
MAX_CONSENSUS_JSON_DEPTH = 16


def _is_consensus_json_value(value: Any, depth: int = 0) -> bool:
    """Accept only JSON values with deterministic Python/JavaScript encoding.

    Floats and integers outside JavaScript's exact range are excluded because
    the browser wallet must reproduce the node's canonical sighash byte-for-byte.
    Lone Unicode surrogates are excluded because they have no valid UTF-8 encoding.
    """
    if depth > MAX_CONSENSUS_JSON_DEPTH:
        return False
    if value is None or type(value) is bool:
        return True
    if type(value) is int:
        return -MAX_SAFE_JSON_INTEGER <= value <= MAX_SAFE_JSON_INTEGER
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return False
        return True
    if isinstance(value, list):
        return all(_is_consensus_json_value(item, depth + 1) for item in value)
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not _is_consensus_json_value(
                key, depth + 1
            ):
                return False
            if not _is_consensus_json_value(item, depth + 1):
                return False
        return True
    return False


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
            f"TEST MODE CONFIGURED: PoS activates at block {POS_ACTIVATION_HEIGHT} "
            f"on accelerated '{NETWORK_NAME}' profile"
        )
    else:
        print(f"MAINNET CONFIGURED: Staking activates at block {POS_ACTIVATION_HEIGHT} (18 months post-genesis)")
        print("PoW CONTINUES: Mining continues for 198 months total alongside PoS/Masternodes")


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
        if type(self.value) is not int:
            raise ValueError(f"Invalid output value type: {type(self.value).__name__}")
        if self.value < 0:
            raise ValueError(f"Output value cannot be negative: {self.value}")
        if self.value > SUPPLY_CAP:
            raise ValueError(f"Output value exceeds supply cap: {self.value}")

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
    shielded_bundle: Optional[Any] = None
    tx_type: str = TX_TYPE_TRANSFER
    extra_data: Optional[Dict[str, Any]] = None
    timestamp: int = 0
    
    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = int(time.time())
        if self.extra_data is None:
            self.extra_data = {}
        else:
            self.extra_data = dict(self.extra_data)
    
    def has_quantum_signatures(self) -> bool:
        """Check if transaction contains quantum signatures"""
        return any(inp.signature_type == "dilithium" for inp in self.inputs)
    
    def is_mixed_signature_transaction(self) -> bool:
        """Check if transaction has mixed signature types"""
        signature_types = set(inp.signature_type for inp in self.inputs)
        return len(signature_types) > 1
    
    def get_canonical_sighash(self, network: str = NETWORK_NAME) -> bytes:
        """Return a network-bound digest committing to the unsigned transaction.

        Every input signs this same digest (SIGHASH_ALL style). It commits to
        the version, lock_time, timestamp, fee, tx_type, every input outpoint
        (and sequence), every output (value, address, script marker), and the
        canonicalized extra_data. Signature fields themselves are excluded so
        the digest is stable before and after signing. The versioned,
        length-prefixed canonical JSON encoding avoids delimiter and field-
        boundary collisions.
        The network domain is consensus-critical. It prevents a signature made
        for a test chain from authorizing the same outpoint and value flow on
        mainnet (or any other WEPO network).
        """
        if not isinstance(network, str) or not network or len(network) > 32:
            raise ValueError("Transaction signing network is invalid")
        try:
            network_bytes = network.encode("ascii", errors="strict")
        except UnicodeError as exc:
            raise ValueError("Transaction signing network is invalid") from exc
        unsigned = {
            "version": self.version,
            "lock_time": self.lock_time,
            "timestamp": self.timestamp,
            "fee": self.fee,
            "tx_type": self.tx_type,
            "inputs": [
                {
                    "prev_txid": inp.prev_txid,
                    "prev_vout": inp.prev_vout,
                    "sequence": inp.sequence,
                }
                for inp in self.inputs
            ],
            "outputs": [
                {
                    "value": out.value,
                    "address": out.address,
                    "script_pubkey": bytes(out.script_pubkey or b"").hex(),
                }
                for out in self.outputs
            ],
            "shielded_bundle": _shielded_bundle_to_dict(
                self.shielded_bundle, include_proof=False
            ),
            "extra_data": self.extra_data or {},
        }
        payload = json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        preimage = (
            b"WEPO_SIGHASH_V3\x00"
            + struct.pack("<I", len(network_bytes))
            + network_bytes
            + struct.pack("<I", len(payload))
            + payload
        )
        return hashlib.sha256(preimage).digest()

    def sign_input(self, input_index: int, private_key: bytes, public_key: bytes, network: str = NETWORK_NAME) -> bool:
        """Attach a Dilithium signature authorizing one input.

        The caller must supply the keypair whose public key hashes to the
        address that owns the UTXO referenced by this input; consensus will
        reject the spend otherwise (see validate_transaction).
        """
        if input_index < 0 or input_index >= len(self.inputs):
            return False
        try:
            from dilithium import sign_with_dilithium
        except ImportError:
            from .dilithium import sign_with_dilithium
        sighash = self.get_canonical_sighash(network)
        signature = sign_with_dilithium(sighash, private_key)
        inp = self.inputs[input_index]
        inp.signature_type = "dilithium"
        inp.quantum_public_key = bytes(public_key)
        inp.quantum_signature = bytes(signature)
        inp.script_sig = b""
        return True

    def sign_all_inputs(self, private_key: bytes, public_key: bytes, network: str = NETWORK_NAME) -> bool:
        """Convenience: sign every input with a single keypair (single-owner spend)."""
        if not self.inputs:
            return False
        ok = True
        for i in range(len(self.inputs)):
            ok = self.sign_input(i, private_key, public_key, network) and ok
        return ok

    def verify_quantum_signature(self, input_index: int, expected_address: Optional[str] = None, network: str = NETWORK_NAME) -> bool:
        """Verify the Dilithium signature authorizing one input.

        When expected_address is provided (the address that owns the spent
        UTXO), this ALSO enforces the binding that the signing public key hashes
        to that address. Without the binding check, a valid signature made with
        an attacker's own key would pass while spending someone else's coins, so
        consensus always passes the UTXO's owning address here.
        """
        if input_index < 0 or input_index >= len(self.inputs):
            return False

        inp = self.inputs[input_index]

        if inp.signature_type != "dilithium":
            return False

        if not inp.quantum_signature or not inp.quantum_public_key:
            return False

        # Defense in depth: enforce NIST ML-DSA sizes before doing crypto work.
        if len(inp.quantum_public_key) != 1312 or len(inp.quantum_signature) != 2420:
            return False

        # Owner binding: public key must hash to the UTXO's address.
        if expected_address is not None:
            try:
                derived_address = generate_wepo_address(inp.quantum_public_key, address_type="quantum")
            except Exception as e:
                print(f"Failed to derive address from public key for input {input_index}: {e}")
                return False
            if not addresses_equal(derived_address, expected_address):
                print(f"Public key does not own UTXO for input {input_index}")
                return False

        try:
            from dilithium import verify_signature
        except ImportError:
            from .dilithium import verify_signature
        sighash = self.get_canonical_sighash(network)
        try:
            return bool(verify_signature(sighash, inp.quantum_signature, inp.quantum_public_key))
        except Exception as e:
            print(f"Quantum signature verification failed: {e}")
            return False

    def get_signing_message_for_input(self, input_index: int) -> bytes:
        """Backward-compatible signing message; now the canonical whole-tx sighash."""
        return self.get_canonical_sighash()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dict (bytes encoded as hex)."""
        def enc(b):
            return b.hex() if isinstance(b, (bytes, bytearray)) else b
        return {
            'version': self.version,
            'lock_time': self.lock_time,
            'fee': self.fee,
            'tx_type': self.tx_type,
            'timestamp': self.timestamp,
            'extra_data': self.extra_data or {},
            'privacy_proof': enc(self.privacy_proof),
            'ring_signature': enc(self.ring_signature),
            'shielded_bundle': _shielded_bundle_to_dict(self.shielded_bundle),
            'inputs': [
                {
                    'prev_txid': inp.prev_txid,
                    'prev_vout': inp.prev_vout,
                    'sequence': inp.sequence,
                    'script_sig': enc(inp.script_sig) if inp.script_sig else '',
                    'signature_type': inp.signature_type,
                    'quantum_signature': enc(inp.quantum_signature),
                    'quantum_public_key': enc(inp.quantum_public_key),
                }
                for inp in self.inputs
            ],
            'outputs': [
                {
                    'value': out.value,
                    'address': out.address,
                    'script_pubkey': enc(out.script_pubkey) if out.script_pubkey else '',
                }
                for out in self.outputs
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Transaction':
        """Reconstruct a Transaction from a client-supplied dict (e.g. a signed tx).

        Hex-encoded byte fields are decoded back to bytes. TransactionInput
        __post_init__ enforces Dilithium key/signature sizes, so malformed
        signed transactions raise here rather than reaching consensus.
        """
        if not isinstance(data, dict) or set(data) - {
            "version",
            "lock_time",
            "fee",
            "tx_type",
            "timestamp",
            "extra_data",
            "privacy_proof",
            "ring_signature",
            "shielded_bundle",
            "inputs",
            "outputs",
        }:
            raise ValueError("Transaction has an invalid wire schema")
        input_data = data.get("inputs", [])
        output_data = data.get("outputs", [])
        if (
            any(
                field in data and type(data[field]) is not int
                for field in ("version", "lock_time", "fee", "timestamp")
            )
            or ("tx_type" in data and not isinstance(data["tx_type"], str))
            or ("extra_data" in data and not isinstance(data["extra_data"], dict))
            or not isinstance(input_data, list)
            or len(input_data) > MAX_TRANSACTION_INPUTS
            or not isinstance(output_data, list)
            or len(output_data) > MAX_TRANSACTION_OUTPUTS
        ):
            raise ValueError("Transaction exceeds wire resource limits")

        def dec(v):
            if v is None or v == '':
                return None
            if isinstance(v, (bytes, bytearray)):
                return bytes(v)
            if not isinstance(v, str):
                raise ValueError("Transaction byte field must use hexadecimal text")
            return bytes.fromhex(v)

        inputs = []
        for i in input_data:
            if (
                not isinstance(i, dict)
                or set(i) - {
                    "prev_txid",
                    "prev_vout",
                    "script_sig",
                    "sequence",
                    "quantum_signature",
                    "quantum_public_key",
                    "signature_type",
                }
                or "prev_txid" not in i
                or "prev_vout" not in i
                or not isinstance(i["prev_txid"], str)
                or type(i["prev_vout"]) is not int
                or ("sequence" in i and type(i["sequence"]) is not int)
                or (
                    "signature_type" in i
                    and not isinstance(i["signature_type"], str)
                )
            ):
                raise ValueError("Transaction input has an invalid wire schema")
            inputs.append(TransactionInput(
                prev_txid=i['prev_txid'],
                prev_vout=i['prev_vout'],
                script_sig=dec(i.get('script_sig')) or b'',
                sequence=i.get('sequence', 0xffffffff),
                quantum_signature=dec(i.get('quantum_signature')),
                quantum_public_key=dec(i.get('quantum_public_key')),
                signature_type=i.get('signature_type', 'ecdsa'),
            ))

        outputs = []
        for o in output_data:
            if (
                not isinstance(o, dict)
                or set(o) - {
                    "value",
                    "script_pubkey",
                    "address",
                }
                or "value" not in o
                or type(o["value"]) is not int
                or ("address" in o and not isinstance(o["address"], str))
            ):
                raise ValueError("Transaction output has an invalid wire schema")
            outputs.append(TransactionOutput(
                value=o['value'],
                script_pubkey=dec(o.get('script_pubkey')) or b'',
                address=o.get('address', ''),
            ))

        timestamp = data.get('timestamp', 0)
        tx = cls(
            version=data.get('version', 1),
            inputs=inputs,
            outputs=outputs,
            lock_time=data.get('lock_time', 0),
            fee=data.get('fee', 0),
            privacy_proof=dec(data.get('privacy_proof')),
            ring_signature=dec(data.get('ring_signature')),
            shielded_bundle=_shielded_bundle_from_dict(data.get('shielded_bundle')),
            tx_type=data.get('tx_type', TX_TYPE_TRANSFER),
            extra_data=data.get('extra_data') or {},
            timestamp=timestamp,
        )
        # __post_init__ timestamps locally constructed transactions. Wire data
        # must preserve an explicit/missing zero so every node rejects it identically.
        tx.timestamp = timestamp
        return tx

    def canonical_wire_size(self) -> int:
        """Return the deterministic JSON-wire size used for resource accounting."""
        return len(
            json.dumps(
                self.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )

    def calculate_txid(self) -> str:
        """Return the unambiguous hash of the complete serialized transaction."""
        payload = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        preimage = b"WEPO_TXID_V2\x00" + struct.pack("<I", len(payload)) + payload
        return hashlib.sha256(preimage).hexdigest()
    
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
    validator_public_key: Optional[bytes] = None  # ML-DSA-44 public key for PoS
    validator_signature: Optional[bytes] = None  # For PoS blocks
    
    @staticmethod
    def _length_prefixed(value: bytes) -> bytes:
        return struct.pack("<I", len(value)) + value

    def canonical_bytes(self, include_validator_signature: bool = True) -> bytes:
        """Return unambiguous, versioned bytes for the consensus block header."""
        consensus = self.consensus_type.encode("ascii")
        validator_address = (self.validator_address or "").encode("ascii")
        validator_public_key = bytes(self.validator_public_key or b"")
        validator_signature = (
            bytes(self.validator_signature or b"")
            if include_validator_signature
            else b""
        )

        return (
            b"WEPO_BLOCK_HEADER_V2\x00"
            + struct.pack(
                "<I32s32sQII",
                self.version,
                bytes.fromhex(self.prev_hash),
                bytes.fromhex(self.merkle_root),
                self.timestamp,
                self.bits,
                self.nonce,
            )
            + self._length_prefixed(consensus)
            + self._length_prefixed(validator_address)
            + self._length_prefixed(validator_public_key)
            + self._length_prefixed(validator_signature)
        )

    def calculate_hash(self) -> str:
        """Calculate the consensus block id over every header field."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()
    
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
    
    @staticmethod
    def _size_json_default(value):
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).hex()
        raise TypeError(f"Unsupported consensus size value: {type(value).__name__}")

    def calculate_size(self) -> int:
        """Calculate deterministic JSON-wire size enforced by consensus."""
        transaction_bytes = json.dumps(
            [tx.to_dict() for tx in self.transactions],
            sort_keys=True,
            separators=(",", ":"),
            default=self._size_json_default,
        ).encode("utf-8")
        return (
            8  # block height
            + 4  # transaction count
            + len(self.header.canonical_bytes())
            + len(transaction_bytes)
        )
    
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
            '<I32s32sQII',
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
                    
            except Exception:
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
    
    def __init__(
        self,
        data_dir: str = "/tmp/wepo",
        network_profile: Optional[str] = None,
        fixed_difficulty: Optional[int] = None,
    ):
        self.network_profile_name = (network_profile or os.getenv("WEPO_NETWORK_PROFILE", NETWORK_PROFILE_NAME)).strip().lower()
        self.network_profile = get_network_profile(self.network_profile_name)
        if fixed_difficulty is not None:
            if self.network_profile.name == "mainnet":
                raise RuntimeError("A fixed difficulty is not permitted on mainnet")
            if type(fixed_difficulty) is not int or fixed_difficulty < 1:
                raise ValueError("fixed difficulty must be a positive integer")

        self.coinbase_maturity = self.network_profile.coinbase_maturity
        if (
            self.coinbase_maturity is not None
            and (type(self.coinbase_maturity) is not int or self.coinbase_maturity < 1)
        ):
            raise RuntimeError("coinbase maturity must be a positive integer or unset")
        self.minimum_relay_fee_per_kb = (
            self.network_profile.minimum_relay_fee_per_kb
        )
        if (
            self.minimum_relay_fee_per_kb is not None
            and (type(self.minimum_relay_fee_per_kb) is not int
                 or self.minimum_relay_fee_per_kb < 0)
        ):
            raise RuntimeError("minimum relay fee rate must be a nonnegative integer or unset")
        apply_network_profile(self.network_profile_name)
        if PRIVACY_CONSENSUS_ENABLED:
            if (
                SHIELDED_ACTIVATION_HEIGHT is None
                or type(SHIELDED_ACTIVATION_HEIGHT) is not int
                or SHIELDED_ACTIVATION_HEIGHT < 1
            ):
                raise RuntimeError(
                    "shielded consensus is enabled without a valid activation height"
                )
            try:
                from .shielded import verifier_is_audited
            except ImportError:
                from shielded import verifier_is_audited
            if not verifier_is_audited():
                raise RuntimeError(
                    "shielded consensus is enabled without the pinned, "
                    "audit-approved verifier"
                )
        self.data_dir = data_dir
        self.db_path = os.path.join(data_dir, "blockchain.db")
        self.chain: List[Block] = []
        self.mempool: Dict[str, Transaction] = {}
        self.mempool_bytes = 0
        self.mempool_lock = threading.RLock()
        self.chain_lock = threading.RLock()
        # Process-scoped operational counters. External monitoring retains and
        # compares them across restarts; consensus state never depends on them.
        self.process_started_at = int(time.time())
        self.accepted_blocks_total = 0
        self.block_validation_rejections_total = 0
        self.reorgs_total = 0
        self.reorg_failures_total = 0
        self.last_reorg: Optional[Dict[str, Any]] = None
        self.utxo_set: Dict[str, TransactionOutput] = {}
        self.stakes: Dict[str, dict] = {}
        self.masternodes: Dict[str, dict] = {}
        self.block_index: Dict[str, Block] = {}
        self.main_chain_hashes: Set[str] = set()
        self.pending_blocks_by_prev_hash: Dict[str, Set[str]] = {}
        self.pending_block_order: Dict[str, str] = {}
        self.issued_supply_by_height: Dict[int, int] = {}
        self.fixed_difficulty = fixed_difficulty
        self.current_difficulty = fixed_difficulty or 4
        self.miner = WepoArgon2Miner()
        self.shielded_tree = None
        self.shielded_anchors = None
        self.shielded_nullifiers = None
        
        # Ensure data directory exists
        os.makedirs(data_dir, exist_ok=True)
        
        # Initialize database
        self.init_database()
        
        # Load existing chain or create genesis
        self.load_chain()
        self._refresh_main_chain_index()
        if self.chain:
            canonical_blocks = list(self.chain)
            self._rebuild_canonical_state_from_blocks(canonical_blocks)
            self.conn.commit()
        if not self.chain:
            self.create_genesis_block()
        self._rebuild_issued_supply_cache()
        self.backfill_wallet_activity_ledger()
    
        if _shielded_active_at(self.get_block_height() + 1):
            self._ensure_shielded_state()
    @staticmethod
    def _configure_database_connection(
        connection: sqlite3.Connection,
    ) -> None:
        """Apply the durable, bounded SQLite policy required by a full node."""
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        journal_mode = connection.execute(
            "PRAGMA journal_mode = WAL"
        ).fetchone()
        if not journal_mode or str(journal_mode[0]).lower() != "wal":
            raise RuntimeError("blockchain database could not enable WAL mode")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA wal_autocheckpoint = 1000")
        connection.execute("PRAGMA journal_size_limit = 67108864")

    @staticmethod
    def _assert_database_integrity(
        connection: sqlite3.Connection,
    ) -> None:
        """Fail closed instead of starting from a structurally corrupt database."""
        try:
            row = connection.execute("PRAGMA quick_check").fetchone()
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(
                "blockchain database integrity check failed"
            ) from exc
        if not row or row[0] != "ok":
            detail = row[0] if row else "no result"
            raise RuntimeError(
                f"blockchain database integrity check failed: {detail}"
            )

    def init_database(self):
        """Initialize SQLite database"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._configure_database_connection(self.conn)
        self._assert_database_integrity(self.conn)
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
                created_height INTEGER NOT NULL DEFAULT 0,
                is_coinbase BOOLEAN NOT NULL DEFAULT FALSE,
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

        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS shielded_commitments (
                position INTEGER PRIMARY KEY,
                commitment BLOB NOT NULL,
                block_height INTEGER NOT NULL,
                txid TEXT NOT NULL,
                output_index INTEGER NOT NULL,
                UNIQUE(txid, output_index)
            )
        ''')

        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS shielded_nullifiers (
                nullifier BLOB PRIMARY KEY,
                block_height INTEGER NOT NULL,
                txid TEXT NOT NULL,
                spend_index INTEGER NOT NULL,
                UNIQUE(txid, spend_index)
            )
        ''')

        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS shielded_anchors (
                anchor BLOB PRIMARY KEY,
                block_height INTEGER NOT NULL
            )
        ''')

        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS wallet_activity (
                activity_id TEXT PRIMARY KEY,
                address TEXT NOT NULL,
                txid TEXT NOT NULL,
                activity_type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                counterparty_address TEXT,
                block_height INTEGER NOT NULL,
                block_hash TEXT NOT NULL,
                timestamp INTEGER NOT NULL
            )
        ''')

        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS rwa_assets (
                asset_id TEXT PRIMARY KEY,
                owner_address TEXT NOT NULL,
                asset_hash TEXT NOT NULL,
                name TEXT,
                asset_type TEXT,
                create_txid TEXT NOT NULL,
                create_height INTEGER NOT NULL,
                created_time INTEGER NOT NULL,
                metadata_json TEXT
            )
        ''')

        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS messaging_keys (
                address TEXT PRIMARY KEY,
                kem_pub TEXT NOT NULL,
                sig_pub TEXT NOT NULL,
                register_txid TEXT NOT NULL,
                register_height INTEGER NOT NULL,
                registered_time INTEGER NOT NULL
            )
        ''')

        self.conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_utxos_address_spent
            ON utxos(address, spent)
        ''')
        self.conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_rwa_assets_owner
            ON rwa_assets(owner_address, create_height DESC)
        ''')
        self.conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_masternodes_status_collateral
            ON masternodes(status, collateral_txid, collateral_vout)
        ''')
        self.conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_staking_rewards_recipient_height
            ON staking_rewards(recipient_address, block_height DESC, timestamp DESC)
        ''')
        self.conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_staking_rewards_height_id
            ON staking_rewards(block_height, reward_id)
        ''')
        self.conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_wallet_activity_address_height
            ON wallet_activity(address, block_height DESC, timestamp DESC)
        ''')
        self.conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_wallet_activity_address_type_height
            ON wallet_activity(address, activity_type, block_height DESC, timestamp DESC)
        ''')

        self._ensure_table_column("stakes", "lock_txid", "TEXT")
        self._ensure_table_column("stakes", "lock_vout", "INTEGER")
        self._ensure_table_column("stakes", "deactivation_txid", "TEXT")
        self._ensure_table_column("masternodes", "deactivation_txid", "TEXT")
        self._ensure_table_column("utxos", "created_height", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_table_column("utxos", "is_coinbase", "BOOLEAN NOT NULL DEFAULT FALSE")
        
        self.conn.commit()

    def _ensure_table_column(self, table_name: str, column_name: str, column_type_sql: str) -> None:
        """Add a missing SQLite column in-place for forward-compatible local migrations."""
        cursor = self.conn.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if column_name in existing_columns:
            return
        self.conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type_sql}")

    @staticmethod
    def _protocol_tx_type(transaction: Transaction) -> str:
        """Normalize transaction type access for legacy and upgraded transactions."""
        tx_type = getattr(transaction, "tx_type", TX_TYPE_TRANSFER) or TX_TYPE_TRANSFER
        return str(tx_type)
    @staticmethod
    def _transaction_state_claims(
        transaction: Transaction,
    ) -> Set[Tuple[str, str]]:
        """Return logical state identifiers that must be unique at admission."""
        tx_type = WepoBlockchain._protocol_tx_type(transaction)
        metadata = transaction.extra_data or {}
        field_by_type = {
            TX_TYPE_STAKE_CREATE: ("stake", "stake_id"),
            TX_TYPE_MASTERNODE_CREATE: ("masternode", "masternode_id"),
            TX_TYPE_RWA_CREATE: ("rwa", "asset_id"),
        }
        claim_spec = field_by_type.get(tx_type)
        if claim_spec is None or not isinstance(metadata, dict):
            return set()
        namespace, field = claim_spec
        identifier = metadata.get(field)
        return {(namespace, identifier)} if isinstance(identifier, str) and identifier else set()


    @staticmethod
    def _decode_script_marker(script_pubkey: Optional[bytes]) -> str:
        """Decode a script marker used for synthetic protocol outputs."""
        if not script_pubkey:
            return ""
        if isinstance(script_pubkey, (bytes, bytearray)):
            return bytes(script_pubkey).decode(errors="ignore")
        return str(script_pubkey)

    def _find_protocol_output(self, transaction: Transaction, marker_prefix: str) -> Optional[tuple]:
        """Return the first output matching a protocol marker prefix."""
        for output_index, output in enumerate(transaction.outputs):
            if self._decode_script_marker(output.script_pubkey).startswith(marker_prefix):
                return output_index, output
        return None

    def _parse_reward_reference(self, reward_id: str) -> Optional[tuple]:
        """Recover a stake or masternode reference from persisted reward IDs."""
        if reward_id.startswith("reward_staker_"):
            parts = reward_id.split("_", 3)
            if len(parts) == 4:
                return "staker", parts[3]
        elif reward_id.startswith("reward_masternode_"):
            parts = reward_id.split("_", 3)
            if len(parts) == 4:
                return "masternode", parts[3]
        elif reward_id.startswith("fee_reward_staker_"):
            parts = reward_id.split("_", 5)
            if len(parts) == 6:
                return "staker", parts[5]
        elif reward_id.startswith("fee_reward_masternode_"):
            parts = reward_id.split("_", 5)
            if len(parts) == 6:
                return "masternode", parts[5]
        return None

    def _replay_protocol_reward_totals(self) -> None:
        """Reapply persisted reward history onto rebuilt stake and masternode state."""
        self.conn.execute("UPDATE stakes SET total_rewards = 0, last_reward_height = 0")
        self.conn.execute("UPDATE masternodes SET total_rewards = 0, last_ping = 0")

        reward_cursor = self.conn.execute('''
            SELECT reward_id, amount, block_height, timestamp
            FROM staking_rewards
            ORDER BY block_height ASC, timestamp ASC
        ''')
        for reward_id, amount, block_height, timestamp in reward_cursor.fetchall():
            parsed = self._parse_reward_reference(reward_id)
            if not parsed:
                continue

            recipient_type, reference_id = parsed
            if recipient_type == "staker":
                self.conn.execute('''
                    UPDATE stakes
                    SET total_rewards = total_rewards + ?,
                        last_reward_height = CASE
                            WHEN last_reward_height < ? THEN ?
                            ELSE last_reward_height
                        END
                    WHERE stake_id = ?
                ''', (amount, block_height, block_height, reference_id))
            elif recipient_type == "masternode":
                self.conn.execute('''
                    UPDATE masternodes
                    SET total_rewards = total_rewards + ?,
                        last_ping = CASE
                            WHEN last_ping < ? THEN ?
                            ELSE last_ping
                        END
                    WHERE masternode_id = ?
                ''', (amount, timestamp, timestamp, reference_id))

    def _apply_protocol_state_transition(self, transaction: Transaction, block: Block) -> None:
        """Apply one confirmed protocol lifecycle transaction to canonical stake/MN state."""
        tx_type = self._protocol_tx_type(transaction)
        if tx_type not in PROTOCOL_LIFECYCLE_TX_TYPES:
            return

        txid = transaction.calculate_txid()
        metadata = dict(transaction.extra_data or {})
        timestamp = transaction.timestamp or block.header.timestamp

        if tx_type == TX_TYPE_STAKE_CREATE:
            stake_id = metadata.get("stake_id")
            staker_address = metadata.get("staker_address")
            amount = int(metadata.get("amount", 0) or 0)
            locked_output = self._find_protocol_output(transaction, f"stake_lock:{stake_id}")
            if not stake_id or not staker_address or not locked_output or amount <= 0:
                raise ValueError(f"Invalid canonical stake_create transaction {txid}")

            lock_vout, _ = locked_output
            self.conn.execute('''
                INSERT OR REPLACE INTO stakes (
                    stake_id,
                    staker_address,
                    amount,
                    start_height,
                    start_time,
                    last_reward_height,
                    total_rewards,
                    status,
                    unlock_height,
                    lock_txid,
                    lock_vout,
                    deactivation_txid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                stake_id,
                staker_address,
                amount,
                block.height,
                timestamp,
                0,
                0,
                'active',
                None,
                txid,
                lock_vout,
                None,
            ))

            self.stakes[stake_id] = {
                'stake_id': stake_id,
                'staker_address': staker_address,
                'amount': amount,
                'start_height': block.height,
                'start_time': timestamp,
                'last_reward_height': 0,
                'total_rewards': 0,
                'status': 'active',
                'unlock_height': None,
                'lock_txid': txid,
                'lock_vout': lock_vout,
                'deactivation_txid': None,
            }
        elif tx_type == TX_TYPE_STAKE_DEACTIVATE:
            stake_id = metadata.get("stake_id")
            if not stake_id:
                raise ValueError(f"Invalid canonical stake_deactivate transaction {txid}")

            self.conn.execute('''
                UPDATE stakes
                SET status = 'inactive',
                    unlock_height = ?,
                    deactivation_txid = ?
                WHERE stake_id = ?
            ''', (block.height, txid, stake_id))

            if stake_id in self.stakes:
                self.stakes[stake_id]['status'] = 'inactive'
                self.stakes[stake_id]['unlock_height'] = block.height
                self.stakes[stake_id]['deactivation_txid'] = txid
        elif tx_type == TX_TYPE_MASTERNODE_CREATE:
            masternode_id = metadata.get("masternode_id")
            operator_address = metadata.get("operator_address")
            ip_address = metadata.get("ip_address")
            port = int(metadata.get("port", 22567) or 22567)
            locked_output = self._find_protocol_output(transaction, f"masternode_lock:{masternode_id}")
            if not masternode_id or not operator_address or not locked_output:
                raise ValueError(f"Invalid canonical masternode_create transaction {txid}")

            collateral_vout, _ = locked_output
            self.conn.execute('''
                INSERT OR REPLACE INTO masternodes (
                    masternode_id,
                    operator_address,
                    collateral_txid,
                    collateral_vout,
                    ip_address,
                    port,
                    start_height,
                    start_time,
                    last_ping,
                    status,
                    total_rewards,
                    deactivation_txid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                masternode_id,
                operator_address,
                txid,
                collateral_vout,
                ip_address,
                port,
                block.height,
                timestamp,
                0,
                'active',
                0,
                None,
            ))

            self.masternodes[masternode_id] = {
                'masternode_id': masternode_id,
                'operator_address': operator_address,
                'collateral_txid': txid,
                'collateral_vout': collateral_vout,
                'ip_address': ip_address,
                'port': port,
                'start_height': block.height,
                'start_time': timestamp,
                'last_ping': 0,
                'status': 'active',
                'total_rewards': 0,
                'deactivation_txid': None,
            }
        elif tx_type == TX_TYPE_MASTERNODE_DEACTIVATE:
            masternode_id = metadata.get("masternode_id")
            if not masternode_id:
                raise ValueError(f"Invalid canonical masternode_deactivate transaction {txid}")

            self.conn.execute('''
                UPDATE masternodes
                SET status = 'inactive',
                    deactivation_txid = ?
                WHERE masternode_id = ?
            ''', (txid, masternode_id))

            if masternode_id in self.masternodes:
                self.masternodes[masternode_id]['status'] = 'inactive'
                self.masternodes[masternode_id]['deactivation_txid'] = txid

    def _apply_protocol_state_transitions(self, block: Block) -> None:
        """Apply all protocol lifecycle state transitions confirmed in a block."""
        for transaction in block.transactions:
            self._apply_protocol_state_transition(transaction, block)

    def _index_rwa_transactions(self, block: Block) -> None:
        """Index confirmed on-chain RWA creations into the derived rwa_assets table.

        Deterministic and reorg-safe: rwa_assets is cleared in
        _reset_derived_chain_tables and rebuilt by replaying confirmed blocks, so
        this is the single source of truth for asset existence/ownership (no DB of
        record off-chain). Idempotent via INSERT OR REPLACE.
        """
        for transaction in block.transactions:
            if getattr(transaction, "tx_type", TX_TYPE_TRANSFER) != TX_TYPE_RWA_CREATE:
                continue
            metadata = dict(transaction.extra_data or {})
            asset_id = metadata.get("asset_id")
            owner_address = metadata.get("owner_address")
            asset_hash = metadata.get("asset_hash")
            if not asset_id or not owner_address or not asset_hash:
                # validate_transaction rejects these, so a confirmed block should
                # never carry one; skip defensively rather than corrupt the index.
                continue
            txid = transaction.calculate_txid()
            timestamp = transaction.timestamp or block.header.timestamp
            reserved = {"asset_id", "owner_address", "asset_hash", "name", "asset_type"}
            extra_meta = {k: v for k, v in metadata.items() if k not in reserved}
            self.conn.execute('''
                INSERT OR REPLACE INTO rwa_assets (
                    asset_id, owner_address, asset_hash, name, asset_type,
                    create_txid, create_height, created_time, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                asset_id,
                owner_address,
                asset_hash,
                metadata.get("name"),
                metadata.get("asset_type"),
                txid,
                block.height,
                timestamp,
                json.dumps(extra_meta, sort_keys=True, separators=(",", ":")) if extra_meta else None,
            ))

    @staticmethod
    def _rwa_row_to_dict(row) -> Dict[str, Any]:
        return {
            "asset_id": row[0],
            "owner_address": row[1],
            "asset_hash": row[2],
            "name": row[3],
            "asset_type": row[4],
            "create_txid": row[5],
            "create_height": row[6],
            "created_time": row[7],
            "metadata": json.loads(row[8]) if row[8] else {},
        }

    def get_rwa_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """Return one on-chain RWA asset by id, or None."""
        cursor = self.conn.execute(
            "SELECT asset_id, owner_address, asset_hash, name, asset_type, "
            "create_txid, create_height, created_time, metadata_json "
            "FROM rwa_assets WHERE asset_id = ?",
            (asset_id,),
        )
        row = cursor.fetchone()
        return self._rwa_row_to_dict(row) if row else None

    def get_rwa_assets_for_owner(self, owner_address: str) -> List[Dict[str, Any]]:
        """Return all on-chain RWA assets owned by an address (newest first)."""
        cursor = self.conn.execute(
            "SELECT asset_id, owner_address, asset_hash, name, asset_type, "
            "create_txid, create_height, created_time, metadata_json "
            "FROM rwa_assets WHERE owner_address = ? ORDER BY create_height DESC",
            (owner_address,),
        )
        return [self._rwa_row_to_dict(r) for r in cursor.fetchall()]

    def _index_messaging_key_registrations(self, block: Block) -> None:
        """Index confirmed on-chain messaging-key registrations (trustless discovery).

        Deterministic and reorg-safe: messaging_keys is cleared in
        _reset_derived_chain_tables and rebuilt by replaying blocks. Latest
        registration per address wins (INSERT OR REPLACE).
        """
        for transaction in block.transactions:
            if getattr(transaction, "tx_type", TX_TYPE_TRANSFER) != TX_TYPE_KEY_REGISTER:
                continue
            metadata = dict(transaction.extra_data or {})
            owner_address = metadata.get("owner_address")
            kem_pub = metadata.get("kem_pub")
            sig_pub = metadata.get("sig_pub")
            if not owner_address or not kem_pub or not sig_pub:
                continue
            self.conn.execute('''
                INSERT OR REPLACE INTO messaging_keys (
                    address, kem_pub, sig_pub, register_txid, register_height, registered_time
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                owner_address, kem_pub, sig_pub,
                transaction.calculate_txid(), block.height,
                transaction.timestamp or block.header.timestamp,
            ))

    def get_messaging_keys(self, address: str) -> Optional[Dict[str, Any]]:
        """Return an address's on-chain-anchored messaging public keys, or None."""
        cursor = self.conn.execute(
            "SELECT address, kem_pub, sig_pub, register_txid, register_height, registered_time "
            "FROM messaging_keys WHERE address = ?",
            (address,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "address": row[0], "kem_pub": row[1], "sig_pub": row[2],
            "register_txid": row[3], "register_height": row[4], "registered_time": row[5],
        }

    def rebuild_protocol_state_from_chain(self) -> None:
        """Reconstruct stake and masternode state from canonical lifecycle transactions."""
        has_canonical_lifecycle = any(
            self._protocol_tx_type(transaction) in PROTOCOL_LIFECYCLE_TX_TYPES
            for block in self.chain
            for transaction in block.transactions
        )
        if not has_canonical_lifecycle:
            return

        self.conn.execute("DELETE FROM stakes")
        self.conn.execute("DELETE FROM masternodes")
        self.stakes.clear()
        self.masternodes.clear()

        for block in self.chain:
            for transaction in block.transactions:
                self._apply_protocol_state_transition(transaction, block)

        self._replay_protocol_reward_totals()
        self.conn.commit()

    def _refresh_main_chain_index(self) -> None:
        """Refresh in-memory indexes for main-chain and side-chain block lookups."""
        self.main_chain_hashes = set()
        for block in self.chain:
            block_hash = block.get_block_hash()
            self.block_index[block_hash] = block
            self.main_chain_hashes.add(block_hash)

    def _drop_pending_block_hash(self, block_hash: str, prev_hash: str) -> None:
        """Remove one pending block from every bounded in-memory index."""
        self.pending_block_order.pop(block_hash, None)
        children = self.pending_blocks_by_prev_hash.get(prev_hash)
        if children:
            children.discard(block_hash)
            if not children:
                self.pending_blocks_by_prev_hash.pop(prev_hash, None)
        if block_hash not in self.main_chain_hashes:
            self.block_index.pop(block_hash, None)

    def _validate_pending_block_envelope(self, block: Block) -> bool:
        """Reject context-free invalid branch data before it consumes cache."""
        if type(block.height) is not int or block.height <= 0:
            return False
        header = block.header
        if (
            header.version != 1
            or header.consensus_type not in {"pow", "pos"}
            or type(header.timestamp) is not int
            or not 0 <= header.timestamp <= 0xFFFFFFFFFFFFFFFF
            or type(header.bits) is not int
            or not 0 <= header.bits <= 0xFFFFFFFF
            or type(header.nonce) is not int
            or not 0 <= header.nonce <= 0xFFFFFFFF
        ):
            return False
        for hash_value in (header.prev_hash, header.merkle_root):
            if not isinstance(hash_value, str) or len(hash_value) != 64:
                return False
            try:
                if len(bytes.fromhex(hash_value)) != 32:
                    return False
            except ValueError:
                return False
        if header.timestamp > int(time.time()) + MAX_FUTURE_BLOCK_TIME_DRIFT:
            return False
        if not block.transactions or len(block.transactions) > MAX_BLOCK_TRANSACTIONS:
            return False
        if block.calculate_size() > MAX_BLOCK_SIZE:
            return False
        if header.merkle_root != block.calculate_merkle_root():
            return False
        if not block.transactions[0].is_coinbase():
            return False
        for tx_index, transaction in enumerate(block.transactions):
            if tx_index > 0 and transaction.is_coinbase():
                return False
            if not self._validate_transaction_consensus_shape(
                transaction,
                block.height,
                allow_coinbase=(tx_index == 0),
                context=f"pending block {block.height} transaction {tx_index}",
            ):
                return False

        parent = self.block_index.get(header.prev_hash)
        if parent is not None and (
            block.height != parent.height + 1
            or header.timestamp <= parent.header.timestamp
        ):
            return False

        if header.is_pow_block():
            if (
                header.bits < 1
                or header.validator_address is not None
                or header.validator_public_key is not None
                or header.validator_signature is not None
            ):
                return False
            pow_hash = self.miner.calculate_pow_hash(header)
            if not self.miner.check_difficulty(pow_hash, header.bits):
                return False
        elif header.is_pos_block():
            if (
                header.bits != 0
                or not is_quantum_address(header.validator_address or "")
                or not isinstance(header.validator_public_key, bytes)
                or len(header.validator_public_key) != DILITHIUM_PUBKEY_SIZE
                or not isinstance(header.validator_signature, bytes)
                or len(header.validator_signature) != DILITHIUM_SIGNATURE_SIZE
            ):
                return False
        else:
            return False

        return True

    def _remember_noncanonical_block(self, block: Block) -> bool:
        """Store a side-branch or orphan block within bounded memory limits."""
        block_hash = block.get_block_hash()
        if block_hash in self.main_chain_hashes or block_hash in self.pending_block_order:
            return True

        prev_hash = block.header.prev_hash
        siblings = self.pending_blocks_by_prev_hash.get(prev_hash, set())
        if len(siblings) >= MAX_PENDING_CHILDREN_PER_PARENT:
            print(
                f"Rejected pending block {block_hash}: parent {prev_hash} already "
                f"has {MAX_PENDING_CHILDREN_PER_PARENT} pending children"
            )
            return False

        while len(self.pending_block_order) >= MAX_PENDING_BLOCKS:
            oldest_hash, oldest_prev = next(iter(self.pending_block_order.items()))
            self._drop_pending_block_hash(oldest_hash, oldest_prev)

        self.block_index[block_hash] = block
        self.pending_blocks_by_prev_hash.setdefault(prev_hash, set()).add(block_hash)
        self.pending_block_order[block_hash] = prev_hash
        return True

    def _forget_pending_block(self, block: Block) -> None:
        """Remove a block from pending-branch bookkeeping once it is adopted."""
        block_hash = block.get_block_hash()
        self._drop_pending_block_hash(block_hash, block.header.prev_hash)
        self.block_index[block_hash] = block

    @staticmethod
    def _block_chainwork(block: Block) -> int:
        """Return work represented by a block under the leading-hex-zero target."""
        if block.header.is_pow_block():
            difficulty = max(0, int(block.header.bits))
            return 1 << (4 * difficulty)
        # PoS never manufactures proof-of-work. Valid paced PoS blocks are a
        # tie-breaker only after branches have equal cumulative PoW.
        return 0

    def _chain_score(self, blocks: List[Block]) -> Tuple[int, int]:
        """Rank branches by PoW first, then valid PoS progress.

        Lexicographic ordering prevents any number of zero-work PoS blocks from
        replacing a branch with more cumulative PoW. PoS only resolves branches
        whose cumulative PoW is exactly equal.
        """
        pow_work = sum(self._block_chainwork(block) for block in blocks)
        pos_blocks = sum(1 for block in blocks if not block.header.is_pow_block())
        return pow_work, pos_blocks

    def _reset_shielded_memory_state(self) -> None:
        self.shielded_tree = None
        self.shielded_anchors = None
        self.shielded_nullifiers = None

    def _ensure_shielded_state(self) -> None:
        if self.shielded_tree is not None:
            return
        try:
            from .shielded import AnchorSet, NoteCommitmentTree, NullifierSet
        except ImportError:
            from shielded import AnchorSet, NoteCommitmentTree, NullifierSet

        tree = NoteCommitmentTree()
        commitments = self.conn.execute(
            "SELECT position, commitment FROM shielded_commitments ORDER BY position"
        ).fetchall()
        for expected, (position, commitment) in enumerate(commitments):
            if position != expected:
                raise RuntimeError("shielded commitment positions are not contiguous")
            tree.append(bytes(commitment))

        nullifiers = NullifierSet()
        for nullifier, height in self.conn.execute(
            "SELECT nullifier, block_height FROM shielded_nullifiers"
        ).fetchall():
            nullifiers.add(bytes(nullifier), int(height))

        anchors = AnchorSet()
        for anchor, height in self.conn.execute(
            "SELECT anchor, block_height FROM shielded_anchors ORDER BY block_height"
        ).fetchall():
            anchors.add(bytes(anchor), int(height))

        latest = self.conn.execute(
            "SELECT anchor FROM shielded_anchors ORDER BY block_height DESC LIMIT 1"
        ).fetchone()
        if latest is not None and bytes(latest[0]) != tree.root():
            raise RuntimeError("persisted shielded anchor does not match commitment tree")

        self.shielded_tree = tree
        self.shielded_anchors = anchors
        self.shielded_nullifiers = nullifiers

    def _validate_shielded_bundle(self, transaction: Transaction, height: int) -> bool:
        bundle = transaction.shielded_bundle
        if bundle is None:
            return True
        if not _shielded_active_at(height):
            return False
        self._ensure_shielded_state()
        try:
            from .shielded import verify_bundle
        except ImportError:
            from shielded import verify_bundle
        ok, reason = verify_bundle(
            bundle,
            transaction.get_canonical_sighash(self.network_profile.network_label),
            self.shielded_anchors,
            self.shielded_nullifiers,
        )
        if not ok:
            print(f"Invalid shielded bundle: {reason}")
        return ok

    def _apply_shielded_state(self, block: Block) -> None:
        if not _shielded_active_at(block.height):
            return
        self._ensure_shielded_state()
        for transaction in block.transactions:
            bundle = transaction.shielded_bundle
            if bundle is None:
                continue
            txid = transaction.calculate_txid()
            for spend_index, nullifier in enumerate(bundle.nullifiers()):
                self.conn.execute(
                    "INSERT INTO shielded_nullifiers "
                    "(nullifier, block_height, txid, spend_index) VALUES (?, ?, ?, ?)",
                    (nullifier, block.height, txid, spend_index),
                )
                self.shielded_nullifiers.add(nullifier, block.height)
            for output_index, commitment in enumerate(bundle.commitments()):
                position = self.shielded_tree.append(commitment)
                self.conn.execute(
                    "INSERT INTO shielded_commitments "
                    "(position, commitment, block_height, txid, output_index) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (position, commitment, block.height, txid, output_index),
                )

        root = self.shielded_tree.root()
        self.shielded_anchors.add(root, block.height)
        self.conn.execute(
            "INSERT OR REPLACE INTO shielded_anchors (anchor, block_height) VALUES (?, ?)",
            (root, block.height),
        )
        self.conn.execute(
            "DELETE FROM shielded_anchors WHERE block_height < ?",
            (block.height - self.shielded_anchors.window,),
        )

    def _reset_derived_chain_tables(self) -> None:
        """Clear canonical chain-derived tables before a deterministic replay."""
        for table_name in (
            "shielded_anchors",
            "shielded_nullifiers",
            "shielded_commitments",
            "wallet_activity",
            "staking_rewards",
            "stakes",
            "masternodes",
            "rwa_assets",
            "messaging_keys",
            "utxos",
            "transactions",
            "blocks",
        ):
            self.conn.execute(f"DELETE FROM {table_name}")
        self.stakes.clear()
        self.masternodes.clear()
        self.issued_supply_by_height.clear()
        self._reset_shielded_memory_state()

    def _persist_confirmed_block(self, block: Block) -> None:
        """Persist one confirmed block into the canonical derived state tables."""
        self.process_block_transactions(block)
        self.save_block(block)
        self._record_block_wallet_activity(block)
        self.record_fee_distribution_rewards(block)

        if block.height > POS_ACTIVATION_HEIGHT:
            self.distribute_staking_rewards(block.height, block.get_block_hash(), block)

        self._apply_protocol_state_transitions(block)
        self._index_rwa_transactions(block)
        self._index_messaging_key_registrations(block)
        self._apply_shielded_state(block)
        self._record_issued_supply_for_block(block)

    @_chain_state_locked
    def _rebuild_canonical_state_from_blocks(self, canonical_blocks: List[Block]) -> None:
        """Rebuild all chain-derived state from an explicit canonical block list."""
        self._reset_derived_chain_tables()
        self.chain = []
        for block in canonical_blocks:
            if self.chain or block.height != 0:
                if not self.validate_block(block):
                    raise ValueError(f"Candidate branch contains invalid block at height {block.height}")
            self.chain.append(block)
            self._persist_confirmed_block(block)
        self.current_difficulty = self.calculate_expected_difficulty()
        self._refresh_main_chain_index()

    def _build_branch_to_tip(self, tip_hash: str) -> Optional[Tuple[int, List[Block]]]:
        """Build a candidate suffix from a side-branch tip back to the main-chain ancestor."""
        candidate_suffix: List[Block] = []
        current_hash = tip_hash
        visited: Set[str] = set()

        while current_hash:
            if current_hash in visited:
                return None
            visited.add(current_hash)

            current_block = self.block_index.get(current_hash)
            if current_block is None:
                return None

            candidate_suffix.append(current_block)
            ancestor_hash = current_block.header.prev_hash
            if ancestor_hash in self.main_chain_hashes:
                ancestor_block = self.block_index[ancestor_hash]
                candidate_suffix.reverse()
                return ancestor_block.height, candidate_suffix

            current_hash = ancestor_hash

        return None

    def _restore_database_from_backup(self, backup_conn: sqlite3.Connection) -> None:
        """Restore the live SQLite database from an in-memory backup."""
        try:
            self.conn.close()
        except Exception:
            pass
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._configure_database_connection(self.conn)
        backup_conn.backup(self.conn)
        self._assert_database_integrity(self.conn)

    @_chain_state_locked
    def _try_adopt_branch_from_tip(self, tip_hash: str) -> bool:
        """Attempt to adopt a competing branch if it outranks the current main chain."""
        branch_info = self._build_branch_to_tip(tip_hash)
        if not branch_info:
            return False

        ancestor_height, candidate_suffix = branch_info
        if not candidate_suffix:
            return False

        candidate_chain = self.chain[:ancestor_height + 1] + candidate_suffix
        current_score = self._chain_score(self.chain)
        candidate_score = self._chain_score(candidate_chain)

        if candidate_score <= current_score:
            return False

        backup_conn = sqlite3.connect(":memory:")
        self.conn.backup(backup_conn)
        original_chain = list(self.chain)
        original_main_hashes = set(self.main_chain_hashes)
        original_stakes = {key: dict(value) for key, value in self.stakes.items()}
        original_masternodes = {key: dict(value) for key, value in self.masternodes.items()}
        original_issued_supply = dict(self.issued_supply_by_height)

        try:
            self._rebuild_canonical_state_from_blocks(candidate_chain)
            self.conn.commit()
            for disconnected_block in original_chain[ancestor_height + 1:]:
                self._remember_noncanonical_block(disconnected_block)
            for adopted_block in candidate_suffix:
                self._forget_pending_block(adopted_block)
            disconnected_depth = len(original_chain) - ancestor_height - 1
            if disconnected_depth > 0:
                self.reorgs_total += 1
                self.last_reorg = {
                    "observed_at": int(time.time()),
                    "ancestor_height": ancestor_height,
                    "disconnected_depth": disconnected_depth,
                    "old_tip": original_chain[-1].get_block_hash(),
                    "new_tip": candidate_chain[-1].get_block_hash(),
                    "new_height": candidate_chain[-1].height,
                }

            print(
                f"Adopted new canonical branch at height {candidate_chain[-1].height}: "
                f"old_score={current_score} new_score={candidate_score}"
            )
            return True
        except Exception as e:
            self.conn.rollback()
            self._restore_database_from_backup(backup_conn)
            self._reset_shielded_memory_state()
            self.chain = original_chain
            self.main_chain_hashes = original_main_hashes
            self.stakes = original_stakes
            self.masternodes = original_masternodes
            self.issued_supply_by_height = original_issued_supply
            self.current_difficulty = self.calculate_expected_difficulty()
            self.reorg_failures_total += 1
            print(f"Failed to adopt competing branch ending {tip_hash}: {e}")
            return False
        finally:
            backup_conn.close()

    def _process_pending_descendants(self, parent_hash: str) -> None:
        """Try to advance any stored side-chain descendants after a new block is accepted."""
        pending_children = list(self.pending_blocks_by_prev_hash.get(parent_hash, set()))
        for child_hash in pending_children:
            child_block = self.block_index.get(child_hash)
            if child_block is not None:
                self.add_block_with_priority(child_block)

    def _record_wallet_activity_entry(
        self,
        activity_id: str,
        address: str,
        txid: str,
        activity_type: str,
        amount: int,
        counterparty_address: Optional[str],
        block_height: int,
        block_hash: str,
        timestamp: int,
    ) -> None:
        """Persist one wallet-facing activity row."""
        if not address or amount <= 0:
            return

        self.conn.execute('''
            INSERT OR REPLACE INTO wallet_activity (
                activity_id,
                address,
                txid,
                activity_type,
                amount,
                counterparty_address,
                block_height,
                block_hash,
                timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            activity_id,
            address,
            txid,
            activity_type,
            amount,
            counterparty_address,
            block_height,
            block_hash,
            timestamp,
        ))

    def _record_block_wallet_activity(self, block: Block) -> None:
        """Index wallet activity for the transactions in a confirmed block."""
        block_hash = block.get_block_hash()

        for tx in block.transactions:
            txid = tx.calculate_txid()
            timestamp = tx.timestamp
            tx_type = self._protocol_tx_type(tx)

            if tx_type == TX_TYPE_STAKE_CREATE:
                metadata = dict(tx.extra_data or {})
                stake_id = metadata.get('stake_id')
                staker_address = metadata.get('staker_address')
                locked_output = self._find_protocol_output(tx, f"stake_lock:{stake_id}")
                locked_amount = locked_output[1].value if locked_output else int(metadata.get('amount', 0) or 0)
                self._record_wallet_activity_entry(
                    activity_id=f"stake_lock:{stake_id}",
                    address=staker_address,
                    txid=txid,
                    activity_type='stake_lock',
                    amount=locked_amount,
                    counterparty_address='staking',
                    block_height=block.height,
                    block_hash=block_hash,
                    timestamp=timestamp,
                )
                continue
            elif tx_type == TX_TYPE_STAKE_DEACTIVATE:
                metadata = dict(tx.extra_data or {})
                stake_id = metadata.get('stake_id')
                staker_address = metadata.get('staker_address')
                unlocked_amount = tx.outputs[0].value if tx.outputs else int(metadata.get('amount', 0) or 0)
                self._record_wallet_activity_entry(
                    activity_id=f"stake_unlock:{stake_id}",
                    address=staker_address,
                    txid=txid,
                    activity_type='stake_unlock',
                    amount=unlocked_amount,
                    counterparty_address='staking',
                    block_height=block.height,
                    block_hash=block_hash,
                    timestamp=timestamp,
                )
                continue
            elif tx_type == TX_TYPE_MASTERNODE_CREATE:
                metadata = dict(tx.extra_data or {})
                masternode_id = metadata.get('masternode_id')
                operator_address = metadata.get('operator_address')
                locked_output = self._find_protocol_output(tx, f"masternode_lock:{masternode_id}")
                locked_amount = locked_output[1].value if locked_output else 0
                self._record_wallet_activity_entry(
                    activity_id=f"masternode_lock:{masternode_id}",
                    address=operator_address,
                    txid=txid,
                    activity_type='masternode_lock',
                    amount=locked_amount,
                    counterparty_address='masternode',
                    block_height=block.height,
                    block_hash=block_hash,
                    timestamp=timestamp,
                )
                continue
            elif tx_type == TX_TYPE_MASTERNODE_DEACTIVATE:
                metadata = dict(tx.extra_data or {})
                masternode_id = metadata.get('masternode_id')
                operator_address = metadata.get('operator_address')
                unlocked_amount = tx.outputs[0].value if tx.outputs else 0
                self._record_wallet_activity_entry(
                    activity_id=f"masternode_unlock:{masternode_id}",
                    address=operator_address,
                    txid=txid,
                    activity_type='masternode_unlock',
                    amount=unlocked_amount,
                    counterparty_address='masternode',
                    block_height=block.height,
                    block_hash=block_hash,
                    timestamp=timestamp,
                )
                continue

            sender_addresses: List[str] = []
            sender_input_totals: Dict[str, int] = {}

            if not tx.is_coinbase():
                for inp in tx.inputs:
                    cursor = self.conn.execute('''
                        SELECT address, amount FROM utxos WHERE txid = ? AND vout = ?
                    ''', (inp.prev_txid, inp.prev_vout))
                    row = cursor.fetchone()
                    if row and row[0]:
                        sender_addresses.append(row[0])
                        sender_input_totals[row[0]] = sender_input_totals.get(row[0], 0) + (row[1] or 0)
                sender_addresses = list(dict.fromkeys(sender_addresses))

                for sender_address in sender_addresses:
                    returned_to_sender = sum(
                        output.value
                        for output in tx.outputs
                        if output.address == sender_address
                    )
                    sent_amount = (sender_input_totals.get(sender_address, 0) or 0) - returned_to_sender
                    if sent_amount <= 0:
                        continue

                    counterparty_address = next(
                        (output.address for output in tx.outputs if output.address != sender_address),
                        None,
                    )
                    self._record_wallet_activity_entry(
                        activity_id=f"tx:{txid}:send:{sender_address}",
                        address=sender_address,
                        txid=txid,
                        activity_type='send',
                        amount=sent_amount,
                        counterparty_address=counterparty_address,
                        block_height=block.height,
                        block_hash=block_hash,
                        timestamp=timestamp,
                    )

            receive_entries: Dict[tuple, int] = {}
            for output in tx.outputs:
                if output.value <= 0 or not output.address:
                    continue

                if not tx.is_coinbase() and output.address in sender_addresses:
                    continue

                marker = output.script_pubkey.decode(errors='ignore') if output.script_pubkey else ''
                if marker.startswith("staker_fee_output:") or marker.startswith("masternode_fee_output:"):
                    continue

                if block.header.is_pos_block() and tx.is_coinbase() and output.script_pubkey == b"coinbase_output":
                    activity_type = 'validator_reward'
                    counterparty_address = 'protocol'
                else:
                    activity_type = 'receive'
                    counterparty_address = sender_addresses[0] if sender_addresses else 'coinbase'

                key = (output.address, activity_type, counterparty_address)
                receive_entries[key] = receive_entries.get(key, 0) + output.value

            for (address, activity_type, counterparty_address), amount in receive_entries.items():
                if activity_type == 'validator_reward':
                    activity_id = f"validator_reward_{txid}_{address}"
                else:
                    activity_id = f"tx:{txid}:{activity_type}:{address}"

                self._record_wallet_activity_entry(
                    activity_id=activity_id,
                    address=address,
                    txid=txid,
                    activity_type=activity_type,
                    amount=amount,
                    counterparty_address=counterparty_address,
                    block_height=block.height,
                    block_hash=block_hash,
                    timestamp=timestamp,
                )

    def _record_reward_wallet_activity(
        self,
        reward_id: str,
        recipient_address: str,
        recipient_type: str,
        amount: int,
        block_height: int,
        block_hash: str,
        timestamp: int,
    ) -> None:
        """Index synthetic staking and masternode reward events."""
        self._record_wallet_activity_entry(
            activity_id=reward_id,
            address=recipient_address,
            txid=reward_id,
            activity_type=f"{recipient_type}_reward",
            amount=amount,
            counterparty_address='protocol',
            block_height=block_height,
            block_hash=block_hash,
            timestamp=timestamp,
        )

    def backfill_wallet_activity_ledger(self) -> None:
        """Populate the wallet activity ledger for existing chains once."""
        cursor = self.conn.execute('SELECT COUNT(1) FROM wallet_activity')
        row_count = cursor.fetchone()[0] or 0
        if row_count > 0 or not self.chain:
            return

        print("Backfilling wallet activity ledger from existing chain data...")
        for block in self.chain:
            self._record_block_wallet_activity(block)

        reward_cursor = self.conn.execute('''
            SELECT reward_id, recipient_address, recipient_type, amount, block_height, block_hash, timestamp
            FROM staking_rewards
            ORDER BY block_height ASC, timestamp ASC
        ''')
        for reward_id, recipient_address, recipient_type, amount, block_height, block_hash, timestamp in reward_cursor.fetchall():
            self._record_reward_wallet_activity(
                reward_id=reward_id,
                recipient_address=recipient_address,
                recipient_type=recipient_type,
                amount=amount,
                block_height=block_height,
                block_hash=block_hash,
                timestamp=timestamp,
            )

        self.conn.commit()

    def _validate_configured_genesis(self, block: Block) -> bool:
        """Require the unique deterministic genesis for the active profile."""
        try:
            expected_transaction = Transaction(
                version=1,
                inputs=[
                    TransactionInput(
                        prev_txid="0" * 64,
                        prev_vout=0xFFFFFFFF,
                        script_sig=b"WEPO Genesis - We The People",
                        sequence=0xFFFFFFFF,
                    )
                ],
                outputs=[
                    TransactionOutput(
                        value=GENESIS_BOOTSTRAP_REWARD,
                        script_pubkey=b"genesis_output",
                        address=self.network_profile.genesis_address,
                    )
                ],
                lock_time=0,
                timestamp=GENESIS_TIME,
            )
            expected_header = BlockHeader(
                version=1,
                prev_hash="0" * 64,
                merkle_root="",
                timestamp=GENESIS_TIME,
                bits=1,
                nonce=0,
                consensus_type="pow",
            )
            expected = Block(
                header=expected_header,
                transactions=[expected_transaction],
                height=0,
            )
            expected.header.merkle_root = expected.calculate_merkle_root()
            while not self.miner.check_difficulty(
                self.miner.calculate_pow_hash(expected.header),
                expected.header.bits,
            ):
                if expected.header.nonce == 0xFFFFFFFF:
                    return False
                expected.header.nonce += 1
            expected.size = expected.calculate_size()
            return (
                block.height == 0
                and len(block.transactions) == 1
                and block.header.canonical_bytes()
                == expected.header.canonical_bytes()
                and block.transactions[0].to_dict()
                == expected.transactions[0].to_dict()
                and block.size == expected.size
                and block.get_block_hash() == expected.get_block_hash()
            )
        except (TypeError, ValueError, OverflowError):
            return False

    def create_genesis_block(self):
        """Create the deterministic genesis block for this network profile."""
        print("Creating WEPO genesis block...")
        genesis_address = self.network_profile.genesis_address
        if not is_quantum_address(genesis_address):
            raise RuntimeError(
                f"{self.network_profile.name} genesis address must be a quantum "
                "wepo1q address bound to an ML-DSA public key"
            )
        
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
        """Load canonical block payloads and reject denormalized-row drift."""
        cursor = self.conn.execute(
            """
            SELECT height, hash, prev_hash, merkle_root, timestamp, bits, nonce,
                   version, size, tx_count, consensus_type, block_data
            FROM blocks
            ORDER BY height ASC
            """
        )

        for expected_height, row in enumerate(cursor.fetchall()):
            (
                stored_height,
                stored_hash,
                stored_prev_hash,
                stored_merkle_root,
                stored_timestamp,
                stored_bits,
                stored_nonce,
                stored_version,
                stored_size,
                stored_tx_count,
                stored_consensus_type,
                stored_block_data,
            ) = row
            if stored_height != expected_height:
                raise RuntimeError(
                    "block database heights are not contiguous from genesis"
                )
            try:
                block_data = json.loads(stored_block_data)
            except (TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"block {stored_height} has invalid canonical payload JSON"
                ) from exc
            block = self.deserialize_block(block_data)
            expected_row = (
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
                self.serialize_block(block),
            )
            if row != expected_row:
                raise RuntimeError(
                    f"block {stored_height} metadata does not match its "
                    "canonical payload"
                )
            if stored_height == 0 and not self._validate_configured_genesis(block):
                raise RuntimeError(
                    "stored genesis does not match the configured network genesis"
                )
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
            'header': bytes_to_hex(asdict(block.header)),
            'transactions': [],
            'height': block.height,
            'size': block.size
        }
        
        block_dict['transactions'] = [tx.to_dict() for tx in block.transactions]
        
        return json.dumps(block_dict, sort_keys=True, separators=(",", ":"))
    
    def _deserialize_block_legacy_unreachable(self, data: dict) -> Block:
        """Removed legacy decoder; retained temporarily only to make old calls fail closed."""
        raise RuntimeError("Legacy permissive block decoding has been removed")
        def decode_bytes_field(value):
            if value in (None, b'', ''):
                return None if value is None else b''
            if isinstance(value, (bytes, bytearray)):
                return bytes(value)
            if isinstance(value, str):
                try:
                    return bytes.fromhex(value)
                except ValueError:
                    return value.encode()
            return value

        header_data = dict(data['header'])
        if 'validator_public_key' in header_data:
            header_data['validator_public_key'] = decode_bytes_field(header_data.get('validator_public_key'))
        if 'validator_signature' in header_data:
            header_data['validator_signature'] = decode_bytes_field(header_data.get('validator_signature'))
        header = BlockHeader(**header_data)
        transactions = []
        for tx_data in data['transactions']:
            inputs = []
            for inp_data in tx_data['inputs']:
                script_sig = decode_bytes_field(inp_data.get('script_sig', b'')) or b''
                quantum_signature = decode_bytes_field(inp_data.get('quantum_signature'))
                quantum_public_key = decode_bytes_field(inp_data.get('quantum_public_key'))

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
                script_pubkey = decode_bytes_field(out_data.get('script_pubkey', b'')) or b''
                outputs.append(TransactionOutput(
                    value=out_data['value'],
                    script_pubkey=script_pubkey,
                    address=out_data.get('address', '')
                ))
            
            privacy_proof = decode_bytes_field(tx_data.get('privacy_proof'))
            ring_signature = decode_bytes_field(tx_data.get('ring_signature'))
            shielded_bundle = _shielded_bundle_from_dict(tx_data.get('shielded_bundle'))
            
            tx = Transaction(
                version=tx_data['version'],
                inputs=inputs,
                outputs=outputs,
                lock_time=tx_data['lock_time'],
                fee=tx_data.get('fee', 0),
                privacy_proof=privacy_proof,
                ring_signature=ring_signature,
                shielded_bundle=shielded_bundle,
                tx_type=tx_data.get('tx_type', TX_TYPE_TRANSFER),
                extra_data=tx_data.get('extra_data') or {},
                timestamp=tx_data.get('timestamp', 0)
            )
            transactions.append(tx)
        
        return Block(
            header=header,
            transactions=transactions,
            height=data['height'],
            size=data['size']
        )
    
    def deserialize_block(self, data: dict) -> Block:
        """Deserialize one canonical, resource-bounded block wire envelope."""
        if not isinstance(data, dict) or set(data) != {
            "header",
            "transactions",
            "height",
            "size",
        }:
            raise ValueError("Block has an invalid wire schema")
        if type(data["height"]) is not int or type(data["size"]) is not int:
            raise ValueError("Block height and size must be canonical integers")
        tx_data = data["transactions"]
        if (
            not isinstance(tx_data, list)
            or not tx_data
            or len(tx_data) > MAX_BLOCK_TRANSACTIONS
        ):
            raise ValueError("Block transaction count exceeds wire resource limits")

        def decode_bytes_field(value):
            if value in (None, b'', ''):
                return None if value is None else b''
            if isinstance(value, (bytes, bytearray)):
                return bytes(value)
            if not isinstance(value, str):
                raise ValueError("Block byte field must use hexadecimal text")
            return bytes.fromhex(value)

        header_data = data["header"]
        if not isinstance(header_data, dict) or set(header_data) != {
            "version",
            "prev_hash",
            "merkle_root",
            "timestamp",
            "bits",
            "nonce",
            "consensus_type",
            "validator_address",
            "validator_public_key",
            "validator_signature",
        }:
            raise ValueError("Block header has an invalid wire schema")
        if (
            any(
                type(header_data[field]) is not int
                for field in ("version", "timestamp", "bits", "nonce")
            )
            or any(
                not isinstance(header_data[field], str)
                for field in ("prev_hash", "merkle_root", "consensus_type")
            )
            or (
                header_data["validator_address"] is not None
                and not isinstance(header_data["validator_address"], str)
            )
        ):
            raise ValueError("Block header has non-canonical wire field types")

        decoded_header = dict(header_data)
        decoded_header['validator_public_key'] = decode_bytes_field(
            header_data['validator_public_key']
        )
        decoded_header['validator_signature'] = decode_bytes_field(
            header_data['validator_signature']
        )
        block = Block(
            header=BlockHeader(**decoded_header),
            transactions=[Transaction.from_dict(item) for item in tx_data],
            height=data["height"],
            size=0,
        )
        if data["size"] != block.size:
            raise ValueError("Block declared size does not match its canonical payload")
        if block.size > MAX_BLOCK_SIZE:
            raise ValueError("Block exceeds the consensus byte limit")
        return block

    def get_latest_block(self) -> Optional[Block]:
        """Get the latest block in the chain"""
        return self.chain[-1] if self.chain else None

    def get_latest_blocks_summary(self, limit: int = 10) -> List[dict]:
        """Get recent block summaries from the indexed blocks table."""
        cursor = self.conn.execute('''
            SELECT height, hash, timestamp, tx_count, size, consensus_type
            FROM blocks
            ORDER BY height DESC
            LIMIT ?
        ''', (max(0, limit),))
        return [
            {
                'height': row[0],
                'hash': row[1],
                'timestamp': row[2],
                'tx_count': row[3],
                'size': row[4],
                'consensus_type': row[5],
            }
            for row in cursor.fetchall()
        ]

    def get_block_summary(self, *, block_hash: Optional[str] = None, height: Optional[int] = None) -> Optional[dict]:
        """Get one block summary from the indexed blocks table."""
        if block_hash is not None:
            cursor = self.conn.execute('''
                SELECT height, hash, prev_hash, merkle_root, timestamp, bits, nonce, consensus_type, size
                FROM blocks
                WHERE hash = ?
            ''', (block_hash,))
        elif height is not None:
            cursor = self.conn.execute('''
                SELECT height, hash, prev_hash, merkle_root, timestamp, bits, nonce, consensus_type, size
                FROM blocks
                WHERE height = ?
            ''', (height,))
        else:
            return None

        row = cursor.fetchone()
        if not row:
            return None

        tx_cursor = self.conn.execute('''
            SELECT txid
            FROM transactions
            WHERE block_hash = ?
            ORDER BY rowid ASC
        ''', (row[1],))
        return {
            'height': row[0],
            'hash': row[1],
            'prev_hash': row[2],
            'merkle_root': row[3],
            'timestamp': row[4],
            'bits': row[5],
            'nonce': row[6],
            'consensus_type': row[7],
            'size': row[8],
            'transactions': [tx_row[0] for tx_row in tx_cursor.fetchall()],
        }

    def get_block_payload(self, block_hash: str) -> Optional[dict]:
        """Get the full serialized block payload for P2P transport or replay."""
        cursor = self.conn.execute('''
            SELECT block_data
            FROM blocks
            WHERE hash = ?
        ''', (block_hash,))
        row = cursor.fetchone()
        if row:
            return json.loads(row[0])

        block = self.block_index.get(block_hash)
        if block is None:
            return None
        return json.loads(self.serialize_block(block))

    def get_block_locator_hashes(self, max_entries: int = 32) -> List[str]:
        """Build a compact block locator from the current canonical tip backwards."""
        if not self.chain:
            return []

        locator_hashes: List[str] = []
        step = 1
        height = self.get_block_height()

        while height >= 0 and len(locator_hashes) < max_entries:
            locator_hashes.append(self.chain[height].get_block_hash())
            if len(locator_hashes) >= 10:
                step *= 2
            height -= step

        genesis_hash = self.chain[0].get_block_hash()
        if genesis_hash not in locator_hashes:
            locator_hashes.append(genesis_hash)

        return locator_hashes

    def _locator_start_height(self, locator_hashes: Optional[List[str]]) -> int:
        """Find the first canonical block height after a peer locator match."""
        if not locator_hashes:
            return 0

        for locator_hash in locator_hashes:
            if locator_hash not in self.main_chain_hashes:
                continue
            matched_block = self.block_index.get(locator_hash)
            if matched_block is None:
                continue
            return matched_block.height + 1
        return 0

    def get_headers_after_locator(
        self,
        locator_hashes: Optional[List[str]],
        *,
        stop_hash: Optional[str] = None,
        limit: int = 2000,
    ) -> List[dict]:
        """Return canonical header summaries after the best locator match."""
        start_height = self._locator_start_height(locator_hashes)
        headers: List[dict] = []

        for block in self.chain[start_height:]:
            headers.append({
                'hash': block.get_block_hash(),
                'prev_hash': block.header.prev_hash,
                'height': block.height,
                'timestamp': block.header.timestamp,
                'bits': block.header.bits,
                'nonce': block.header.nonce,
                'merkle_root': block.header.merkle_root,
                'consensus_type': block.header.consensus_type,
            })
            if stop_hash and block.get_block_hash() == stop_hash:
                break
            if len(headers) >= max(0, limit):
                break

        return headers

    def get_block_hashes_after_locator(
        self,
        locator_hashes: Optional[List[str]],
        *,
        stop_hash: Optional[str] = None,
        limit: int = 500,
    ) -> List[str]:
        """Return canonical block hashes after the best locator match."""
        headers = self.get_headers_after_locator(locator_hashes, stop_hash=stop_hash, limit=limit)
        return [header['hash'] for header in headers]

    def get_transaction_summary(self, txid: str) -> Optional[dict]:
        """Get one confirmed transaction summary from the indexed transactions table."""
        cursor = self.conn.execute('''
            SELECT txid, block_height, fee, privacy_proof, ring_signature, tx_data
            FROM transactions
            WHERE txid = ?
        ''', (txid,))
        row = cursor.fetchone()
        if not row:
            return None

        tx_data = json.loads(row[5])
        block_height = row[1]
        confirmations = 0
        if block_height is not None:
            confirmations = max(0, self.get_block_height() - block_height + 1)

        return {
            'txid': row[0],
            'version': tx_data.get('version', 1),
            'tx_type': tx_data.get('tx_type', TX_TYPE_TRANSFER),
            'extra_data': tx_data.get('extra_data') or {},
            'lock_time': tx_data.get('lock_time', 0),
            'fee': row[2],
            'timestamp': tx_data.get('timestamp', 0),
            'block_height': block_height,
            'confirmations': confirmations,
            'inputs': [
                {
                    'prev_txid': inp.get('prev_txid'),
                    'prev_vout': inp.get('prev_vout'),
                }
                for inp in tx_data.get('inputs', [])
            ],
            'outputs': [
                {
                    'value': out.get('value'),
                    'address': out.get('address'),
                }
                for out in tx_data.get('outputs', [])
            ],
            'privacy_proof': bool(row[3]),
            'ring_signature': bool(row[4]),
        }

    def has_transaction(self, txid: str) -> bool:
        """Return whether a transaction is in the mempool or confirmed index."""
        if not isinstance(txid, str) or len(txid) != 64:
            return False
        if txid in self.mempool:
            return True
        return self.conn.execute(
            "SELECT 1 FROM transactions WHERE txid = ? LIMIT 1",
            (txid,),
        ).fetchone() is not None

    def get_transaction_payload(self, txid: str) -> Optional[dict]:
        """Return the canonical full transaction envelope used by P2P getdata."""
        if not isinstance(txid, str) or len(txid) != 64:
            return None
        transaction = self.mempool.get(txid)
        if transaction is not None:
            return {"txid": txid, "tx_data": transaction.to_dict()}

        row = self.conn.execute(
            "SELECT tx_data FROM transactions WHERE txid = ? LIMIT 1",
            (txid,),
        ).fetchone()
        if row is None:
            return None
        try:
            tx_data = json.loads(row[0])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return {"txid": txid, "tx_data": tx_data}

    def get_block_height(self) -> int:
        """Get current block height"""
        return len(self.chain) - 1 if self.chain else -1

    # === Issuance model (owner decision 2026-06-20, "distribution-only") =========
    # Every block can mint coins via at most TWO newly-minted paths, processed in
    # this order so the hard cap is applied identically in production and on replay:
    #   1. coinbase base reward  -> genesis bootstrap, or the PoW block subsidy.
    #      PoS blocks mint NO coinbase base reward (the forger earns through the
    #      staking/masternode distribution, not the coinbase).
    #   2. PoS reward pool       -> minted via distribute_staking_rewards() to
    #      stakers + masternodes, once per block above PoS activation (both PoW and
    #      PoS blocks in the hybrid era).
    # Transaction fees are redistribution, not new issuance, and are excluded here.

    def scheduled_coinbase_base(self, height: int, consensus_type: str) -> int:
        """Unclamped newly-minted reward paid through the block's coinbase.

        Pure function of (height, consensus_type), branch-independent. PoS blocks
        return 0 (distribution-only model). The cap is applied via
        clamped_coinbase_base().
        """
        if height == 0:
            return GENESIS_BOOTSTRAP_REWARD
        if consensus_type == "pow":
            return self.calculate_block_reward(height)
        return 0  # PoS coinbase mints no base reward

    def scheduled_pos_pool(self, height: int) -> int:
        """Unclamped newly-minted PoS reward pool for stakers + masternodes.

        Minted once per block above PoS activation (PoW and PoS blocks alike) via
        distribute_staking_rewards(). The cap is applied via clamped_pos_pool().
        """
        if height <= POS_ACTIVATION_HEIGHT:
            return 0
        return self.calculate_pos_reward(height)

    def get_issued_supply(self, up_to_height: Optional[int] = None) -> int:
        """Return cached canonical issuance through a requested height.

        The prefix is rebuilt once on startup/reorg and extended once per
        accepted block. Normal validation therefore reads prior issuance in O(1).
        """
        if not self.chain:
            return 0
        requested_height = (
            self.chain[-1].height if up_to_height is None else up_to_height
        )
        effective_height = min(requested_height, self.chain[-1].height)
        if effective_height < 0:
            return 0
        if effective_height not in self.issued_supply_by_height:
            self._rebuild_issued_supply_cache()
        return self.issued_supply_by_height.get(effective_height, 0)

    def _actual_pos_issuance_by_height(
        self, maximum_height: int
    ) -> Dict[int, int]:
        cursor = self.conn.execute(
            """
            SELECT block_height, COALESCE(SUM(amount), 0)
            FROM staking_rewards
            WHERE block_height <= ?
              AND (
                  reward_id GLOB 'reward_staker_*'
                  OR reward_id GLOB 'reward_masternode_*'
              )
            GROUP BY block_height
            """,
            (maximum_height,),
        )
        return {
            int(height): int(amount) for height, amount in cursor.fetchall()
        }

    def _actual_pos_issuance_at_height(self, height: int) -> int:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM staking_rewards
            WHERE block_height = ?
              AND (
                  reward_id GLOB 'reward_staker_*'
                  OR reward_id GLOB 'reward_masternode_*'
              )
            """,
            (height,),
        ).fetchone()
        return int(row[0]) if row else 0

    def _extend_issued_supply_prefix(
        self, block: Block, actual_pos_pool: int
    ) -> None:
        previous_issued = (
            0
            if block.height == 0
            else self.issued_supply_by_height.get(block.height - 1)
        )
        if previous_issued is None:
            raise RuntimeError("issued-supply cache is missing the prior height")
        scheduled_base = self.scheduled_coinbase_base(
            block.height,
            "pos" if block.header.is_pos_block() else "pow",
        )
        base = min(scheduled_base, max(0, SUPPLY_CAP - previous_issued))
        remaining = SUPPLY_CAP - previous_issued - base
        if (
            actual_pos_pool < 0
            or actual_pos_pool > self.scheduled_pos_pool(block.height)
            or actual_pos_pool > remaining
        ):
            raise RuntimeError(
                f"invalid persisted PoS issuance at height {block.height}"
            )
        self.issued_supply_by_height[block.height] = (
            previous_issued + base + actual_pos_pool
        )

    def _rebuild_issued_supply_cache(self) -> None:
        self.issued_supply_by_height.clear()
        if not self.chain:
            return
        actual_pos_issuance = self._actual_pos_issuance_by_height(
            self.chain[-1].height
        )
        for block in self.chain:
            self._extend_issued_supply_prefix(
                block, actual_pos_issuance.get(block.height, 0)
            )

    def _record_issued_supply_for_block(self, block: Block) -> None:
        actual = self._actual_pos_issuance_at_height(block.height)
        self._extend_issued_supply_prefix(block, actual)

    def clamped_coinbase_base(self, height: int, consensus_type: str) -> int:
        """Coinbase base reward clamped so cumulative issuance never exceeds SUPPLY_CAP.

        Issuance of all prior canonical blocks (height-1 and below) is the clamp
        baseline. Once the cap is reached this returns 0 and only fees are paid.
        """
        scheduled = self.scheduled_coinbase_base(height, consensus_type)
        issued_before = self.get_issued_supply(up_to_height=height - 1)
        return min(scheduled, max(0, SUPPLY_CAP - issued_before))

    def clamped_pos_pool(self, height: int, consensus_type: str) -> int:
        """PoS reward pool clamped to remaining cap headroom AFTER this block's
        coinbase base reward (which is minted first). Guarantees the distribution
        path can never push cumulative issuance past SUPPLY_CAP.
        """
        scheduled = self.scheduled_pos_pool(height)
        issued_before = self.get_issued_supply(up_to_height=height - 1)
        base = self.clamped_coinbase_base(height, consensus_type)
        return min(scheduled, max(0, SUPPLY_CAP - issued_before - base))

    # Backward-compatible aliases (pre-2026-06-20 callers referenced these names).
    def scheduled_base_reward(self, height: int, consensus_type: str) -> int:
        return self.scheduled_coinbase_base(height, consensus_type)

    def clamped_base_reward(self, height: int, consensus_type: str) -> int:
        return self.clamped_coinbase_base(height, consensus_type)

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
            # PoW ENDS at block 1,008,000 (nominal Month 198)
            # Miners continue earning through 25% fee redistribution
            return 0
        
        # TOTAL MINING TIMELINE:
        # - Phase 1 (18 months): 6.9M WEPO (10% of supply)
        # - Phase 2A-2D (16.5 years): 13.8M WEPO (20% of supply)
        # - Total PoW: 20.7M WEPO over 198 months (30% of supply)
        # - PoS/Masternodes: 48.3M WEPO (70% of supply)
        # - Post-PoW: Miners earn via 25% transaction fee redistribution
    
    # NOTE: the canonical PoS reward schedule is calculate_pos_reward() defined
    # later in this class. An earlier duplicate (with a "* 0.33" approximation) was
    # removed 2026-06-20 — it was shadowed/dead and never executed.

    def create_coinbase_transaction(
        self,
        height: int,
        recipient_address: str,
        consensus_type: str = "pow",
        candidate_transactions: Optional[List[Transaction]] = None,
    ) -> Transaction:
        """Create coinbase transaction for new block with canonical fee redistribution."""
        # Coinbase base reward, clamped to the hard cap so cumulative issuance can
        # never exceed SUPPLY_CAP (final rewards truncate; once the cap is hit only
        # fees are paid). PoS blocks mint NO coinbase base reward in the
        # distribution-only model — the forger earns via distribute_staking_rewards;
        # its coinbase carries only the fee share.
        if consensus_type in ("pow", "pos"):
            scheduled = self.scheduled_coinbase_base(height, consensus_type)
            base_reward = self.clamped_coinbase_base(height, consensus_type)
            if base_reward < scheduled:
                print(
                    f"{consensus_type.upper()} Block {height}: coinbase base clamped to cap "
                    f"{base_reward / COIN:.8f} WEPO (scheduled {scheduled / COIN:.8f})"
                )
            else:
                print(f"{consensus_type.upper()} Block {height}: coinbase base reward {base_reward / COIN:.8f} WEPO")
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

            active_masternodes = sorted(
                self.get_active_masternodes(), key=lambda item: item.masternode_id
            )
            pre_pos_fee_policy = height <= POS_ACTIVATION_HEIGHT
            if pre_pos_fee_policy:
                # Before PoS activation, all fees go to the miner unless active masternodes
                # already exist. If they do, keep the masternode share and route the
                # non-staker remainder to the miner.
                staker_fees = 0
                if active_masternodes:
                    masternode_fees = total_transaction_fees * 60 // 100
                    miner_fees = total_transaction_fees - masternode_fees
                else:
                    masternode_fees = 0
                    miner_fees = total_transaction_fees
            else:
                # Post-PoS: 60% masternodes, 25% miner/validator, 15% stakers.
                masternode_fees = total_transaction_fees * 60 // 100
                miner_fees = total_transaction_fees * 25 // 100
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

            active_stakers = [] if pre_pos_fee_policy else sorted(
                self.get_active_stakes(),
                key=lambda item: (item.staker_address, item.stake_id),
            )
            total_stake = sum(staker.amount for staker in active_stakers)
            if active_stakers and total_stake > 0 and staker_fees > 0:
                remaining_fees = staker_fees
                for index, staker in enumerate(active_stakers):
                    if index == len(active_stakers) - 1:
                        staker_reward = remaining_fees
                    else:
                        staker_reward = staker_fees * staker.amount // total_stake
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
    
    def _next_block_timestamp(self) -> int:
        """Choose a locally valid, monotonic timestamp for the next block."""
        now = int(time.time())
        latest_block = self.get_latest_block()
        minimum = (latest_block.header.timestamp + 1) if latest_block else GENESIS_TIME
        if self.get_block_height() + 1 == 1:
            minimum = max(minimum, GENESIS_TIME)
        candidate = max(now, minimum)
        if candidate > now + MAX_FUTURE_BLOCK_TIME_DRIFT:
            raise RuntimeError(
                "Block production is not active yet: the finalized genesis time "
                "is still outside the allowed future-time window"
            )
        return candidate

    def create_new_block(self, miner_address: str) -> Block:
        """Create a new block with transactions from mempool"""
        height = self.get_block_height() + 1
        latest_block = self.get_latest_block()
        prev_hash = latest_block.get_block_hash() if latest_block else "0" * 64

        selected_transactions = []
        selected_outpoints = set()
        provisional_coinbase = self.create_coinbase_transaction(
            height,
            miner_address,
            consensus_type="pow",
            candidate_transactions=[],
        )
        current_size = self._estimate_transaction_size(provisional_coinbase)

        with self.mempool_lock:
            mempool_items = list(self.mempool.items())
        for txid, tx in mempool_items:
            if not self.validate_transaction(tx):
                continue

            # Never pack two transactions that spend the same outpoint into one
            # block — that would be an intra-block double-spend (rejected by
            # validate_block). Skip a candidate conflicting with an already
            # selected transaction.
            tx_outpoints = {(inp.prev_txid, inp.prev_vout) for inp in tx.inputs}
            if tx_outpoints & selected_outpoints:
                continue

            tx_size = self._estimate_transaction_size(tx)
            if current_size + tx_size <= MAX_BLOCK_SIZE:
                selected_transactions.append(tx)
                selected_outpoints |= tx_outpoints
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

        # Create block header
        header = BlockHeader(
            version=1,
            prev_hash=prev_hash,
            merkle_root="",
            timestamp=self._next_block_timestamp(),
            bits=self.current_difficulty,
            nonce=0,
            consensus_type="pow"  # PoS templates use _produce_pos_block().
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
    
    def create_pos_block_template(
        self,
        validator_address: str,
        validator_public_key: bytes,
    ) -> Optional[Block]:
        """Build an unsigned PoS block without accepting validator private keys."""
        if not self.network_profile.pos_consensus_ready:
            return None

        if (
            not isinstance(validator_public_key, (bytes, bytearray))
            or len(validator_public_key) != DILITHIUM_PUBKEY_SIZE
        ):
            return None
        validator_public_key = bytes(validator_public_key)
        if not addresses_equal(
            generate_wepo_address(validator_public_key, address_type="quantum"),
            validator_address,
        ):
            return None

        next_height = self.get_block_height() + 1
        prev_hash = self.chain[-1].get_block_hash() if self.chain else "0" * 64
        if self.select_pos_validator(next_height, parent_hash=prev_hash) != validator_address:
            return None
        if not self.is_valid_pos_validator(validator_address, next_height):
            return None
        
        # Create block with PoS consensus
        height = next_height
        
        # Create coinbase transaction for PoS rewards
        selected_transactions = []
        provisional_coinbase = self.create_coinbase_transaction(
            height,
            validator_address,
            consensus_type="pos",
            candidate_transactions=[],
        )
        current_size = self._estimate_transaction_size(provisional_coinbase)
        
        # Add transactions from mempool
        with self.mempool_lock:
            mempool_items = list(self.mempool.items())
        for txid, tx in mempool_items:
            if not self.validate_transaction(tx):
                continue

            tx_size = self._estimate_transaction_size(tx)
            if current_size + tx_size > MAX_BLOCK_SIZE:
                continue

            selected_transactions.append(tx)
            current_size += tx_size

        coinbase_tx = self.create_coinbase_transaction(
            height,
            validator_address,
            consensus_type="pos",
            candidate_transactions=selected_transactions,
        )
        transactions = [coinbase_tx, *selected_transactions]

        # Create PoS block header
        header = BlockHeader(
            version=1,
            prev_hash=prev_hash,
            merkle_root="",
            timestamp=self._next_block_timestamp(),
            bits=0,  # No difficulty for PoS
            nonce=0,  # No nonce for PoS
            consensus_type="pos",
            validator_address=validator_address,
            validator_public_key=validator_public_key,
        )
        
        # Create PoS block
        pos_block = Block(
            header=header,
            transactions=transactions,
            height=height
        )

        # Calculate merkle root
        pos_block.header.merkle_root = pos_block.calculate_merkle_root()

        return pos_block

    def get_pos_signing_payload(self, block: Block) -> bytes:
        """Return the complete domain-separated payload a PoS signer authorizes."""
        network_name = self.network_profile.name.encode("ascii")
        payload = (
            b"WEPO_POS_BLOCK_SIGNATURE_V1\x00"
            + BlockHeader._length_prefixed(network_name)
            + struct.pack("<Q", block.height)
            + block.header.canonical_bytes(include_validator_signature=False)
        )
        return payload

    def get_pos_signing_message(self, block: Block) -> bytes:
        """Return the digest committed by the validator's ML-DSA signature."""
        return hashlib.sha3_256(self.get_pos_signing_payload(block)).digest()

    def finalize_pos_block(self, block: Block, validator_signature: bytes) -> Optional[Block]:
        """Attach an external signature only when the complete PoS block validates."""
        if (
            not isinstance(validator_signature, (bytes, bytearray))
            or len(validator_signature) != DILITHIUM_SIGNATURE_SIZE
            or not block.header.is_pos_block()
            or block.header.validator_signature
        ):
            return None

        block.header.validator_signature = bytes(validator_signature)
        block.size = block.calculate_size()
        if not self.validate_pos_block(block):
            block.header.validator_signature = b""
            block.size = block.calculate_size()
            return None
        return block

    def validate_pos_block(self, block: Block) -> bool:
        """Validate deterministic selection, key ownership, and ML-DSA signature."""
        if not self.network_profile.pos_consensus_ready:
            return False

        if not block.header.is_pos_block():
            return False
        if block.header.bits != 0 or block.header.nonce != 0:
            return False

        latest_block = self.get_latest_block()
        if latest_block is None:
            return False
        last_pos_timestamp = self.get_last_block_timestamp("pos")
        slot_anchor = (
            last_pos_timestamp
            if last_pos_timestamp is not None
            else latest_block.header.timestamp
        )
        if block.header.timestamp < slot_anchor + BLOCK_TIME_POS:
            return False

        validator_address = block.header.validator_address
        public_key = block.header.validator_public_key
        signature = block.header.validator_signature
        if (
            not isinstance(validator_address, str)
            or not isinstance(public_key, (bytes, bytearray))
            or len(public_key) != DILITHIUM_PUBKEY_SIZE
            or not isinstance(signature, (bytes, bytearray))
            or len(signature) != DILITHIUM_SIGNATURE_SIZE
        ):
            return False
        public_key = bytes(public_key)
        signature = bytes(signature)

        selected_validator = self.select_pos_validator(
            block.height,
            parent_hash=block.header.prev_hash,
        )
        if selected_validator != validator_address:
            return False
        
        # Check validator eligibility
        if not self.is_valid_pos_validator(validator_address, block.height):
            return False

        derived_address = generate_wepo_address(public_key, address_type="quantum")
        if not addresses_equal(derived_address, validator_address):
            return False

        return verify_dilithium_signature(
            self.get_pos_signing_message(block),
            signature,
            public_key,
        )
    
    def _produce_pos_block(
        self,
        validator_address: str,
        pos_signer: Optional[ValidatorSigner],
    ) -> Optional[Block]:
        """Build and sign one PoS block through the private-key-free boundary."""
        if pos_signer is None:
            return None
        try:
            public_key = pos_signer.get_public_key(validator_address)
            block = self.create_pos_block_template(validator_address, public_key)
            if block is None:
                return None
            signing_payload = self.get_pos_signing_payload(block)
            signature = pos_signer.sign(
                validator_address,
                hashlib.sha3_256(signing_payload).digest(),
                context=PosSigningContext(
                    network=self.network_profile.name,
                    block_height=block.height,
                    previous_block_hash=block.header.prev_hash,
                    signing_payload=signing_payload,
                ),
            )
            return self.finalize_pos_block(block, signature)
        except Exception as exc:
            print(f"PoS signer operation failed closed: {type(exc).__name__}")
            return None

    @_chain_state_locked
    def add_block(self, block: Block, validate: bool = True) -> bool:
        """Add a block to the blockchain"""
        original_issued_supply = dict(self.issued_supply_by_height)
        if validate and not self.validate_block(block):
            self.block_validation_rejections_total += 1
            return False
        
        block.size = block.calculate_size()
        # Add to chain
        self.chain.append(block)
        block_hash = block.get_block_hash()
        self.block_index[block_hash] = block
        self.main_chain_hashes.add(block_hash)
        self._forget_pending_block(block)

        try:
            # Process transactions and persist atomically so a failed save
            # cannot leave canonical state partially applied.
            self._persist_confirmed_block(block)
            self.conn.commit()
            with self.mempool_lock:
                for transaction in block.transactions:
                    if transaction.is_coinbase():
                        continue
                    removed = self.mempool.pop(transaction.calculate_txid(), None)
                    if removed is not None:
                        self.mempool_bytes = max(
                            0, self.mempool_bytes - removed.canonical_wire_size()
                        )
            self.current_difficulty = self.calculate_expected_difficulty()
            self._process_pending_descendants(block_hash)
            print(f"Block {block.height} added to chain: {block_hash}")
            self.accepted_blocks_total += 1
            return True
        except Exception as e:
            self.conn.rollback()
            self._reset_shielded_memory_state()
            self.chain.pop()
            self.main_chain_hashes.discard(block_hash)
            self.issued_supply_by_height = original_issued_supply
            self.current_difficulty = self.calculate_expected_difficulty()
            print(f"Failed to add block {block.height}: {e}")
            self.block_validation_rejections_total += 1
            return False
    
    @_chain_state_locked
    def add_block_with_priority(self, new_block: Block) -> bool:
        """Add a block while retaining side branches and adopting a better canonical tip when possible."""
        new_hash = new_block.get_block_hash()
        current_length = len(self.chain)
        current_tip_hash = self.chain[-1].get_block_hash() if self.chain else None

        if new_hash in self.main_chain_hashes:
            print(f"Ignoring duplicate canonical block at height {new_block.height}: {new_hash}")
            return True

        # Normal append case: no block exists at this height yet.
        if new_block.height == current_length and (
            current_tip_hash is None or new_block.header.prev_hash == current_tip_hash
        ):
            return self.add_block(new_block)

        if new_block.height > current_length + MAX_ORPHAN_HEIGHT_AHEAD:
            self.block_validation_rejections_total += 1
            print(
                f"Rejected orphan block {new_hash}: height {new_block.height} is "
                f"more than {MAX_ORPHAN_HEIGHT_AHEAD} blocks beyond the local chain"
            )
            return False

        if not self._validate_pending_block_envelope(new_block):
            print(f"Rejected invalid pending block envelope {new_hash}")
            self.block_validation_rejections_total += 1
            return False

        if not self._remember_noncanonical_block(new_block):
            return False

        if new_block.header.prev_hash not in self.block_index and new_block.header.prev_hash not in self.main_chain_hashes:
            print(
                f"Stored orphan block {new_hash} at height {new_block.height}; "
                f"waiting for parent {new_block.header.prev_hash}"
            )
            return False

        if self._try_adopt_branch_from_tip(new_hash):
            return True

        if new_block.height > current_length:
            print(
                f"Stored future branch block {new_hash} at height {new_block.height}; "
                f"canonical tip remains at height {current_length - 1}"
            )
            return False

        existing_hash = self.chain[new_block.height].get_block_hash() if 0 <= new_block.height < current_length else "unknown"
        print(
            f"Stored competing block at height {new_block.height}: "
            f"existing={existing_hash} candidate={new_hash}. Canonical tip unchanged."
        )
        return False
    
    def get_consensus_type(self, height: int) -> str:
        """Get the consensus type for a given height"""
        if height <= POS_ACTIVATION_HEIGHT:
            return "pow"
        else:
            return "hybrid"  # Both PoW and PoS active
    
    def process_hybrid_blocks(self, height: int, pos_signer: Optional[ValidatorSigner] = None):
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
                pos_block = self._produce_pos_block(validator, pos_signer)
                if pos_block and self.validate_block(pos_block):
                    self.add_block_with_priority(pos_block)
        
        # Check if it's time for a PoW block (every 9 minutes)
        if current_time % BLOCK_TIME_POW_HYBRID == 0:
            # PoW mining continues in parallel
            print(f"PoW mining opportunity at height {height}")
            # This would trigger miners to start mining
            pass
    
    def _transaction_type_consensus_ready(self, tx_type: str) -> bool:
        """Return whether this network profile admits the transaction type."""
        if tx_type in PROTOCOL_LIFECYCLE_TX_TYPES:
            return self.network_profile.pos_consensus_ready
        if tx_type == TX_TYPE_RWA_CREATE:
            return self.network_profile.rwa_consensus_ready
        if tx_type == TX_TYPE_KEY_REGISTER:
            return self.network_profile.messaging_consensus_ready
        return True

    def _require_transaction_type_consensus_ready(self, tx_type: str) -> None:
        """Fail before building a transaction disabled by the network profile."""
        if not self._transaction_type_consensus_ready(tx_type):
            raise ValueError(
                f"{tx_type} is not consensus-enabled on "
                f"the {self.network_profile.name} network profile"
            )

    def _validate_transaction_consensus_shape(
        self,
        transaction: Transaction,
        height: int,
        *,
        allow_coinbase: bool,
        context: str = "transaction",
    ) -> bool:
        """Validate consensus-critical transaction fields before value math."""
        if type(transaction.version) is not int or transaction.version != TRANSACTION_VERSION:
            print(f"Invalid {context}: unsupported transaction version")
            return False
        if (
            type(transaction.lock_time) is not int
            or transaction.lock_time != 0
        ):
            print(
                f"Invalid {context}: v1 lock_time is unsupported and must be zero"
            )
            return False
        if (
            type(transaction.timestamp) is not int
            or not 0 < transaction.timestamp <= MAX_SAFE_JSON_INTEGER
        ):
            print(f"Invalid {context}: timestamp is outside the canonical range")
            return False
        if (
            not isinstance(transaction.tx_type, str)
            or transaction.tx_type not in VALID_TRANSACTION_TYPES
        ):
            print(f"Invalid {context}: unsupported transaction type")
            return False
        if not self._transaction_type_consensus_ready(transaction.tx_type):
            print(
                f"Invalid {context}: {transaction.tx_type} is not "
                f"consensus-enabled on the {self.network_profile.name} network profile"
            )
            return False
        if not isinstance(transaction.inputs, list) or not isinstance(
            transaction.outputs, list
        ):
            print(f"Invalid {context}: inputs and outputs must be canonical lists")
            return False
        # Reject count-based work before constructing or hashing a transaction
        # serialization. This is intentionally ahead of UTXO and signature work.
        if len(transaction.inputs) > MAX_TRANSACTION_INPUTS:
            print(f"Invalid {context}: input count exceeds the consensus limit")
            return False
        if len(transaction.outputs) > MAX_TRANSACTION_OUTPUTS:
            print(f"Invalid {context}: output count exceeds the consensus limit")
            return False
        if not isinstance(transaction.extra_data, dict) or not _is_consensus_json_value(
            transaction.extra_data
        ):
            print(f"Invalid {context}: extra_data is not canonical consensus JSON")
            return False
        try:
            extra_data_size = len(
                json.dumps(
                    transaction.extra_data,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            transaction_size = transaction.canonical_wire_size()
        except (TypeError, ValueError, OverflowError, UnicodeError):
            print(f"Invalid {context}: transaction is not canonically serializable")
            return False
        if extra_data_size > MAX_TRANSACTION_EXTRA_DATA_BYTES:
            print(f"Invalid {context}: extra_data exceeds the consensus byte limit")
            return False
        if transaction_size > MAX_TRANSACTION_WIRE_SIZE:
            print(f"Invalid {context}: transaction exceeds the consensus byte limit")
            return False
        if type(transaction.fee) is not int or not 0 <= transaction.fee <= SUPPLY_CAP:
            print(f"Invalid {context}: fee is outside the canonical range")
            return False
        if transaction.privacy_proof is not None or transaction.ring_signature is not None:
            print(f"Invalid {context}: legacy privacy fields are never active consensus")
            return False
        if transaction.shielded_bundle is not None:
            if not _shielded_active_at(height):
                print(f"Invalid {context}: shielded consensus is not active")
                return False
            if transaction.is_coinbase():
                print(f"Invalid {context}: coinbase cannot carry a shielded bundle")
                return False
            try:
                transaction.shielded_bundle.check_shape()
            except Exception as exc:
                print(f"Invalid {context}: malformed shielded bundle ({exc})")
                return False

        if not transaction.inputs and transaction.shielded_bundle is None:
            print(f"Invalid {context}: transaction must contain at least one input")
            return False
        if (
            not transaction.outputs
            and transaction.shielded_bundle is None
            and transaction.tx_type not in FEE_ONLY_METADATA_TX_TYPES
        ):
            print(f"Invalid {context}: transaction must contain at least one output")
            return False

        if transaction.is_coinbase() and not allow_coinbase:
            print(f"Invalid {context}: coinbase transaction is not allowed here")
            return False

        seen_outpoints = set()
        for idx, inp in enumerate(transaction.inputs):
            if (
                not isinstance(inp.prev_txid, str)
                or len(inp.prev_txid) != 64
                or any(char not in "0123456789abcdef" for char in inp.prev_txid)
            ):
                print(f"Invalid {context}: input {idx} has malformed prev_txid")
                return False
            if (
                type(inp.prev_vout) is not int
                or not 0 <= inp.prev_vout <= MAX_OUTPUT_INDEX
            ):
                print(f"Invalid {context}: input {idx} has malformed prev_vout")
                return False
            if (
                type(inp.sequence) is not int
                or inp.sequence != MAX_SEQUENCE
            ):
                print(f"Invalid {context}: v1 input {idx} sequence must be final")
                return False
            if not isinstance(inp.script_sig, (bytes, bytearray)):
                print(f"Invalid {context}: input {idx} script_sig must be bytes")
                return False
            if len(inp.script_sig) > MAX_TRANSACTION_SCRIPT_BYTES:
                print(f"Invalid {context}: input {idx} script_sig exceeds the byte limit")
                return False
            if not transaction.is_coinbase() and inp.script_sig:
                print(f"Invalid {context}: v1 input {idx} script_sig must be empty")
                return False
            if not isinstance(inp.signature_type, str):
                print(f"Invalid {context}: input {idx} signature type is malformed")
                return False
            outpoint = (inp.prev_txid, inp.prev_vout)
            if outpoint in seen_outpoints:
                print(f"Invalid {context}: input {idx} duplicates an outpoint")
                return False
            seen_outpoints.add(outpoint)

        for idx, out in enumerate(transaction.outputs):
            if type(out.value) is not int:
                print(f"Invalid {context}: output {idx} value must be an integer")
                return False
            if out.value < 0:
                print(f"Invalid {context}: output {idx} value cannot be negative")
                return False
            if out.value > SUPPLY_CAP:
                print(f"Invalid {context}: output {idx} exceeds the supply cap")
                return False
            if not isinstance(out.script_pubkey, (bytes, bytearray)):
                print(f"Invalid {context}: output {idx} script_pubkey must be bytes")
                return False
            if (
                len(out.script_pubkey) > MAX_TRANSACTION_SCRIPT_BYTES
            ):
                print(f"Invalid {context}: output {idx} script_pubkey exceeds the byte limit")
                return False
            if not out.is_valid_address():
                print(f"Invalid {context}: output {idx} has an invalid address")
                return False

        return True

    def validate_block(self, block: Block) -> bool:
        """Validate a block (supports both PoW and PoS)"""
        if type(block.height) is not int or block.height < 0:
            return False
        if block.header.version != 1:
            return False
        if block.header.consensus_type not in {"pow", "pos"}:
            return False

        for field_name, hash_value in (
            ("prev_hash", block.header.prev_hash),
            ("merkle_root", block.header.merkle_root),
        ):
            if not isinstance(hash_value, str) or len(hash_value) != 64:
                print(f"Invalid block {block.height}: malformed {field_name}")
                return False
            try:
                decoded_hash = bytes.fromhex(hash_value)
            except ValueError:
                print(f"Invalid block {block.height}: malformed {field_name}")
                return False
            if len(decoded_hash) != 32:
                return False

        if (
            type(block.header.timestamp) is not int
            or block.header.timestamp < 0
            or block.header.timestamp > 0xFFFFFFFFFFFFFFFF
            or type(block.header.bits) is not int
            or block.header.bits < 0
            or block.header.bits > 0xFFFFFFFF
            or type(block.header.nonce) is not int
            or block.header.nonce < 0
            or block.header.nonce > 0xFFFFFFFF
        ):
            print(f"Invalid block {block.height}: malformed numeric header field")
            return False

        if not block.transactions:
            return False
        if len(block.transactions) > MAX_BLOCK_TRANSACTIONS:
            return False

        try:
            calculated_size = block.calculate_size()
        except (TypeError, ValueError, OverflowError, struct.error):
            return False
        if calculated_size > MAX_BLOCK_SIZE:
            return False

        latest_block = self.get_latest_block()
        expected_height = self.get_block_height() + 1
        if self.chain:
            if block.height != expected_height:
                return False
            if block.header.prev_hash != latest_block.get_block_hash():
                return False
            if block.header.timestamp <= latest_block.header.timestamp:
                print(
                    f"Invalid block {block.height}: timestamp "
                    f"{block.header.timestamp} must be greater than previous "
                    f"timestamp {latest_block.header.timestamp}"
                )
                return False
            if block.height == 1 and block.header.timestamp < GENESIS_TIME:
                print(f"Invalid block 1: timestamp precedes genesis time {GENESIS_TIME}")
                return False
        elif block.height != 0:
            return False

        if block.header.timestamp > int(time.time()) + MAX_FUTURE_BLOCK_TIME_DRIFT:
            return False

        if block.header.merkle_root != block.calculate_merkle_root():
            return False

        coinbase = block.transactions[0]
        if not coinbase.is_coinbase():
            return False

        for tx_index, tx in enumerate(block.transactions):
            if tx_index > 0 and tx.is_coinbase():
                print(
                    f"Invalid block {block.height}: only transaction 0 may be coinbase "
                    f"(found coinbase at index {tx_index})"
                )
                return False
            if not self._validate_transaction_consensus_shape(
                tx,
                block.height,
                allow_coinbase=(tx_index == 0),
                context=f"block {block.height} transaction {tx_index}",
            ):
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

        block_nullifiers = set()
        for tx in block.transactions[1:]:
            if tx.shielded_bundle is None:
                continue
            for nullifier in tx.shielded_bundle.nullifiers():
                if nullifier in block_nullifiers:
                    print(f"Invalid block {block.height}: duplicate shielded nullifier")
                    return False
                block_nullifiers.add(nullifier)

        # Reject intra-block transparent double-spends: no two transactions may
        # spend the same outpoint. validate_transaction only checks each tx
        # against COMMITTED UTXO state (the block is not applied yet), so without
        # this cross-transaction check two conflicting spends of a single UTXO
        # could both land in a block and both mint outputs, breaking value
        # conservation and the supply cap.
        block_spent_outpoints = set()
        for tx in block.transactions[1:]:
            for inp in tx.inputs:
                outpoint = (inp.prev_txid, inp.prev_vout)
                if outpoint in block_spent_outpoints:
                    print(
                        f"Invalid block {block.height}: outpoint "
                        f"{inp.prev_txid}:{inp.prev_vout} is spent by more than one "
                        f"transaction in the same block (double-spend)"
                    )
                    return False
                block_spent_outpoints.add(outpoint)

        # Logical protocol records are keyed independently from transaction
        # outpoints. Two otherwise valid transactions must not replace the same
        # stake, masternode, or RWA record within one block.
        block_state_claims: Set[Tuple[str, str]] = set()
        for tx in block.transactions[1:]:
            claims = self._transaction_state_claims(tx)
            duplicate_claims = block_state_claims & claims
            if duplicate_claims:
                claim = sorted(duplicate_claims)[0]
                print(
                    f"Invalid block {block.height}: duplicate protocol state "
                    f"claim {claim[0]}:{claim[1]}"
                )
                return False
            block_state_claims.update(claims)

        for tx in block.transactions[1:]:
            if not self.validate_transaction(tx, validation_height=block.height):
                return False

        # Reconstruct the canonical payout list from validated fees and the
        # pre-block protocol state. A total-only check would let a producer
        # redirect masternode/staker shares while preserving the supply cap.
        consensus_type = "pos" if block.header.is_pos_block() else "pow"
        recipient_address = coinbase.outputs[0].address
        expected_coinbase = self.create_coinbase_transaction(
            block.height,
            recipient_address,
            consensus_type,
            block.transactions[1:],
        )
        actual_input = coinbase.inputs[0]
        expected_input = expected_coinbase.inputs[0]
        actual_outputs = [
            (output.value, bytes(output.script_pubkey or b""), output.address)
            for output in coinbase.outputs
        ]
        expected_outputs = [
            (output.value, bytes(output.script_pubkey or b""), output.address)
            for output in expected_coinbase.outputs
        ]
        canonical_input = (
            actual_input.prev_txid == expected_input.prev_txid
            and actual_input.prev_vout == expected_input.prev_vout
            and bytes(actual_input.script_sig or b"")
            == bytes(expected_input.script_sig or b"")
            and actual_input.sequence == expected_input.sequence
            and actual_input.signature_type == expected_input.signature_type
            and actual_input.quantum_signature is None
            and actual_input.quantum_public_key is None
        )
        if (
            not canonical_input
            or coinbase.fee != 0
            or coinbase.tx_type != TX_TYPE_TRANSFER
            or coinbase.extra_data
            or actual_outputs != expected_outputs
        ):
            print(
                f"Invalid coinbase at height {block.height}: payout or input "
                "does not match canonical reward and fee distribution"
            )
            return False

        return True

    def validate_pow_block(self, block: Block) -> bool:
        """Validate deterministic PoW and expected difficulty for a block."""
        if (
            block.header.validator_address is not None
            or block.header.validator_public_key is not None
            or block.header.validator_signature is not None
        ):
            print("Invalid PoW block: validator fields must be empty")
            return False

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
                    INSERT INTO utxos (
                        txid, vout, address, amount, script_pubkey,
                        created_height, is_coinbase, spent
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, FALSE)
                ''', (tx.calculate_txid(), i, out.address, out.value, out.script_pubkey,
                      block.height, tx.is_coinbase()))
    
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
                json.dumps(asdict(tx), default=self._json_default)
            ))
    
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

        # PoS headers deliberately carry bits=0 and arrive on a different
        # cadence. Only PoW headers may drive the next PoW target.
        pow_blocks = [
            block for block in self.chain if block.header.consensus_type == "pow"
        ]
        if not pow_blocks:
            return max(1, self.current_difficulty)
        base_difficulty = max(1, int(pow_blocks[-1].header.bits))
        if len(pow_blocks) < 10:
            return base_difficulty

        recent_pow_blocks = pow_blocks[-10:]
        time_diffs = [
            recent_pow_blocks[index].header.timestamp
            - recent_pow_blocks[index - 1].header.timestamp
            for index in range(1, len(recent_pow_blocks))
        ]

        elapsed = sum(time_diffs)
        interval_count = len(time_diffs)
        next_height = self.get_block_height() + 1
        target_time = (
            BLOCK_TIME_INITIAL_18_MONTHS
            if next_height <= TOTAL_INITIAL_BLOCKS
            else BLOCK_TIME_POW_HYBRID
        )

        # Compare exact integer ratios: average < 3/4 target or > 5/4
        # target. Consensus must not depend on floating-point rounding.
        scaled_elapsed = elapsed * 4
        if scaled_elapsed < target_time * 3 * interval_count:
            return base_difficulty + 1
        if scaled_elapsed > target_time * 5 * interval_count:
            return max(1, base_difficulty - 1)
        return base_difficulty

    def required_relay_fee(self, transaction_size: int) -> Optional[int]:
        """Return node-local admission fee for canonical bytes, or None if unset."""
        if type(transaction_size) is not int or transaction_size < 0:
            raise ValueError("transaction size must be a nonnegative integer")
        if self.minimum_relay_fee_per_kb is None:
            return None
        return (
            self.minimum_relay_fee_per_kb * transaction_size + 999
        ) // 1000

    @staticmethod
    def estimated_signed_wire_size(transaction: Transaction) -> int:
        """Return exact canonical size for the fixed-size ML-DSA signed shape."""
        candidate = Transaction.from_dict(transaction.to_dict())
        for tx_input in candidate.inputs:
            tx_input.script_sig = b""
            tx_input.signature_type = "dilithium"
            tx_input.quantum_public_key = b"\x00" * DILITHIUM_PUBKEY_SIZE
            tx_input.quantum_signature = b"\x00" * DILITHIUM_SIGNATURE_SIZE
        return candidate.canonical_wire_size()

    def create_relay_fee_transaction(
        self,
        from_address: str,
        to_address: str,
        amount: int,
    ) -> tuple[Transaction, int]:
        """Build a deterministic fee-bearing transaction without private keys.

        Fee iteration is monotonic and bounded. The returned fee is the exact
        amount the wallet will sign and is never below either the wallet baseline
        or this node's canonical-byte relay requirement.
        """
        if self.minimum_relay_fee_per_kb is None:
            raise ValueError("minimum relay fee policy is not finalized")

        fee = DEFAULT_TRANSACTION_FEE
        for _ in range(64):
            transaction = self.create_transaction(
                from_address, to_address, amount, fee
            )
            if transaction is None:
                raise ValueError(
                    "failed to build transaction (insufficient funds or no UTXOs)"
                )
            if len(transaction.inputs) > 32:
                raise ValueError("standard wallet transaction requires more than 32 inputs")
            signed_size = self.estimated_signed_wire_size(transaction)
            required = self.required_relay_fee(signed_size)
            next_fee = max(fee, DEFAULT_TRANSACTION_FEE, required or 0)
            if next_fee == fee:
                return transaction, signed_size
            fee = next_fee
        raise RuntimeError("relay-fee transaction quote did not converge")

    def add_transaction_to_mempool(self, transaction: Transaction) -> bool:
        """Add transaction to mempool"""
        # Coinbase transactions are minted by block production only. validate_transaction
        # exempts coinbase from UTXO/signature checks, so accepting one here (or over the
        # P2P relay path) would let a forged "coinbase" mint coins from nothing.
        if transaction.is_coinbase():
            print("Rejected coinbase transaction submitted to mempool")
            return False

        validation_height = self.get_block_height() + 1
        if not self._validate_transaction_consensus_shape(
            transaction,
            validation_height,
            allow_coinbase=False,
            context="mempool transaction",
        ):
            return False
        try:
            txid = transaction.calculate_txid()
            transaction_size = transaction.canonical_wire_size()
        except (TypeError, ValueError, OverflowError, UnicodeError):
            print("Rejected transaction with a non-canonical identity")
            return False

        required_relay_fee = self.required_relay_fee(transaction_size)
        if required_relay_fee is None:
            print(
                f"Rejected transaction: {self.network_profile_name} minimum "
                "relay fee policy is not finalized"
            )
            return False
        if transaction.fee < required_relay_fee:
            print(
                f"Rejected transaction: fee {transaction.fee} is below "
                f"the local relay requirement {required_relay_fee} for "
                f"{transaction_size} canonical bytes"
            )
            return False

        # Reject excess load before doing signature/proof work, then repeat the
        # check under the admission lock after validation to close races.
        with self.mempool_lock:
            if txid in self.mempool:
                return False
            if len(self.mempool) >= MAX_MEMPOOL_TRANSACTIONS:
                print("Rejected transaction: mempool transaction limit reached")
                return False
            if self.mempool_bytes + transaction_size > MAX_MEMPOOL_BYTES:
                print("Rejected transaction: mempool byte limit reached")
                return False

        # Full UTXO, value, protocol, proof, and signature validation.
        if not self.validate_transaction(
            transaction, validation_height=validation_height
        ):
            print(f"Invalid transaction rejected: {txid}")
            return False

        with self.mempool_lock:
            if txid in self.mempool:
                return False
            if len(self.mempool) >= MAX_MEMPOOL_TRANSACTIONS:
                return False
            if self.mempool_bytes + transaction_size > MAX_MEMPOOL_BYTES:
                return False

            # First-seen wins for transparent outpoints and shielded nullifiers.
            new_outpoints = {(inp.prev_txid, inp.prev_vout) for inp in transaction.inputs}
            for existing in self.mempool.values():
                existing_outpoints = {(i.prev_txid, i.prev_vout) for i in existing.inputs}
                if new_outpoints & existing_outpoints:
                    print(
                        f"Rejected transaction {txid}: conflicts with an existing "
                        f"mempool transaction (double-spend of a claimed outpoint)"
                    )
                    return False

            new_state_claims = self._transaction_state_claims(transaction)
            for existing in self.mempool.values():
                duplicate_claims = (
                    new_state_claims & self._transaction_state_claims(existing)
                )
                if duplicate_claims:
                    claim = sorted(duplicate_claims)[0]
                    print(
                        f"Rejected transaction {txid}: protocol state claim "
                        f"{claim[0]}:{claim[1]} is already pending"
                    )
                    return False

            if transaction.shielded_bundle is not None:
                new_nullifiers = set(transaction.shielded_bundle.nullifiers())
                for existing in self.mempool.values():
                    if (
                        existing.shielded_bundle is not None
                        and new_nullifiers & set(existing.shielded_bundle.nullifiers())
                    ):
                        print(
                            f"Rejected transaction {txid}: conflicts with an existing "
                            "mempool shielded nullifier"
                        )
                        return False

            self.mempool[txid] = transaction
            self.mempool_bytes += transaction_size

        print(f"Transaction added to mempool: {txid}")
        return True
    
    def validate_transaction(
        self, transaction: Transaction, validation_height: Optional[int] = None
    ) -> bool:
        """Validate a transaction with proper UTXO checking and quantum signature support"""
        try:
            height = validation_height if validation_height is not None else self.get_block_height() + 1
            if not self._validate_transaction_consensus_shape(
                transaction,
                height,
                allow_coinbase=True,
                context="transaction",
            ):
                return False

            # Skip UTXO/signature checks for the single block coinbase path only.
            # Block and mempool validation decide whether coinbase is allowed in
            # that context.
            if transaction.is_coinbase():
                return True

            # Check inputs exist and are unspent
            total_input_value = 0
            input_rows = []
            input_addresses = set()
            for inp in transaction.inputs:
                # Check if UTXO exists and is unspent
                cursor = self.conn.execute('''
                    SELECT amount, spent, address, script_pubkey,
                           created_height, is_coinbase FROM utxos
                    WHERE txid = ? AND vout = ?
                ''', (inp.prev_txid, inp.prev_vout))
                
                utxo = cursor.fetchone()
                if not utxo:
                    print(f"UTXO not found: {inp.prev_txid}:{inp.prev_vout}")
                    return False
                
                if utxo[1]:  # spent flag
                    print(f"UTXO already spent: {inp.prev_txid}:{inp.prev_vout}")
                    return False
                
                if bool(utxo[5]):
                    if self.coinbase_maturity is None:
                        print(
                            "Block-issued value cannot be spent until the "
                            f"{self.network_profile_name} coinbase maturity is finalized"
                        )
                        return False
                    confirmations_before_spend = height - utxo[4]
                    if confirmations_before_spend < self.coinbase_maturity:
                        print(
                            f"Immature coinbase UTXO: {inp.prev_txid}:{inp.prev_vout} "
                            f"has depth {confirmations_before_spend}, requires "
                            f"{self.coinbase_maturity}"
                        )
                        return False

                total_input_value += utxo[0]
                input_rows.append({
                    'txid': inp.prev_txid,
                    'vout': inp.prev_vout,
                    'amount': utxo[0],
                    'address': utxo[2],
                    'script_pubkey': utxo[3],
                })
                if utxo[2]:
                    input_addresses.add(utxo[2])
            
            # Check outputs
            total_output_value = sum(out.value for out in transaction.outputs)

            if transaction.shielded_bundle is None:
                fee = total_input_value - total_output_value
            else:
                # Positive value_balance moves transparent value into the pool;
                # negative value_balance moves pool value to transparent outputs
                # or pays a fee directly from the shielded pool.
                fee = (
                    total_input_value
                    - total_output_value
                    - transaction.shielded_bundle.value_balance
                )
            if fee < 0:
                print("Transaction spends more value than its transparent and shielded inputs")
                return False
            if transaction.fee != fee:
                print(
                    f"Transaction declares fee {transaction.fee}, "
                    f"but value conservation requires {fee}"
                )
                return False

            if not self._validate_shielded_bundle(transaction, height):
                return False

            tx_type = self._protocol_tx_type(transaction)
            metadata = dict(transaction.extra_data or {})
            next_height = self.get_block_height() + 1

            if tx_type == TX_TYPE_STAKE_CREATE:
                stake_id = metadata.get('stake_id')
                staker_address = metadata.get('staker_address')
                locked_amount = int(metadata.get('amount', 0) or 0)
                if next_height <= POS_ACTIVATION_HEIGHT:
                    print("Staking is not active yet")
                    return False
                if not stake_id or not staker_address or locked_amount < MIN_STAKE_AMOUNT:
                    print("Stake create transaction missing required metadata")
                    return False
                if input_addresses != {staker_address}:
                    print("Stake create transaction inputs do not belong to staker")
                    return False
                lock_marker = f"stake_lock:{stake_id}"
                lock_outputs = [
                    (index, output)
                    for index, output in enumerate(transaction.outputs)
                    if self._decode_script_marker(output.script_pubkey) == lock_marker
                ]
                if len(lock_outputs) != 1:
                    print("Stake create transaction requires exactly one canonical lock output")
                    return False
                lock_index, lock_tx_output = lock_outputs[0]
                if lock_tx_output.address != staker_address or lock_tx_output.value != locked_amount:
                    print("Stake create transaction lock output does not match metadata")
                    return False
                if len(transaction.outputs) not in (1, 2):
                    print("Stake create transaction has a non-canonical output count")
                    return False
                for index, output in enumerate(transaction.outputs):
                    if index == lock_index:
                        continue
                    if (
                        output.address != staker_address
                        or output.script_pubkey != b"change_script"
                    ):
                        print("Stake create change must use the canonical owner output")
                        return False
                existing_cursor = self.conn.execute(
                    'SELECT 1 FROM stakes WHERE stake_id = ?',
                    (stake_id,),
                )
                if existing_cursor.fetchone():
                    print(f"Stake already exists: {stake_id}")
                    return False
            elif tx_type == TX_TYPE_STAKE_DEACTIVATE:
                stake_id = metadata.get('stake_id')
                staker_address = metadata.get('staker_address')
                stake_cursor = self.conn.execute('''
                    SELECT amount, status, lock_txid, lock_vout
                    FROM stakes
                    WHERE stake_id = ?
                ''', (stake_id,))
                stake_row = stake_cursor.fetchone()
                if not stake_row:
                    print(f"Stake not found: {stake_id}")
                    return False
                if stake_row[1] != 'active':
                    print(f"Stake is not active: {stake_id}")
                    return False
                if not stake_row[2] or stake_row[3] is None:
                    print(f"Stake {stake_id} is legacy side-state and cannot be canonically deactivated")
                    return False
                if len(transaction.inputs) != 1:
                    print("Stake deactivation must spend exactly one locked stake UTXO")
                    return False
                if transaction.inputs[0].prev_txid != stake_row[2] or transaction.inputs[0].prev_vout != stake_row[3]:
                    print("Stake deactivation does not spend the active locked stake UTXO")
                    return False
                if input_addresses != {staker_address}:
                    print("Stake deactivation inputs do not belong to staker")
                    return False
                if len(transaction.outputs) != 1:
                    print("Stake deactivation must return a single unlocked output")
                    return False
                unlock_output = transaction.outputs[0]
                if (
                    unlock_output.address != staker_address
                    or unlock_output.script_pubkey != b"stake_unlock"
                    or unlock_output.value <= 0
                    or unlock_output.value + fee != stake_row[0]
                ):
                    print(
                        "Stake deactivation must return locked principal minus "
                        "the declared fee in one canonical owner output"
                    )
                    return False
            elif tx_type == TX_TYPE_MASTERNODE_CREATE:
                masternode_id = metadata.get('masternode_id')
                operator_address = metadata.get('operator_address')
                ip_address = metadata.get('ip_address')
                port = metadata.get('port', 22567)
                required_collateral = self.get_masternode_collateral_for_height(height)
                if (
                    not isinstance(masternode_id, str)
                    or not masternode_id
                    or not isinstance(operator_address, str)
                    or not operator_address
                ):
                    print("Masternode create transaction missing metadata")
                    return False
                if (
                    (ip_address is not None and not isinstance(ip_address, str))
                    or type(port) is not int
                    or not 1 <= port <= 65535
                ):
                    print("Masternode endpoint metadata is malformed")
                    return False
                existing_id_cursor = self.conn.execute(
                    'SELECT 1 FROM masternodes WHERE masternode_id = ?',
                    (masternode_id,),
                )
                if existing_id_cursor.fetchone():
                    print(f"Masternode ID already exists: {masternode_id}")
                    return False
                if not transaction.inputs:
                    print("Masternode create transaction requires a collateral UTXO")
                    return False
                if input_addresses != {operator_address}:
                    print("Masternode collateral and fee inputs must belong to operator")
                    return False
                lock_marker = f"masternode_lock:{masternode_id}"
                lock_outputs = [
                    (index, output)
                    for index, output in enumerate(transaction.outputs)
                    if self._decode_script_marker(output.script_pubkey) == lock_marker
                ]
                if len(lock_outputs) != 1:
                    print("Masternode create requires exactly one collateral output")
                    return False
                lock_index, collateral_output = lock_outputs[0]
                collateral_input_value = input_rows[0]['amount']
                fee_funding_value = total_input_value - collateral_input_value
                expected_change = fee_funding_value - fee
                if (
                    collateral_output.address != operator_address
                    or collateral_output.value != collateral_input_value
                    or collateral_output.value < required_collateral
                    or expected_change < 0
                ):
                    print(
                        "Masternode create must preserve the complete collateral "
                        "UTXO and fund its fee separately"
                    )
                    return False
                expected_output_count = 2 if expected_change else 1
                if len(transaction.outputs) != expected_output_count:
                    print("Masternode create has a non-canonical output count")
                    return False
                for index, output in enumerate(transaction.outputs):
                    if index == lock_index:
                        continue
                    if (
                        output.address != operator_address
                        or output.script_pubkey != b"change_script"
                        or output.value != expected_change
                    ):
                        print("Masternode fee change must use the canonical owner output")
                        return False
                duplicate_cursor = self.conn.execute('''
                    SELECT 1
                    FROM masternodes
                    WHERE status = 'active' AND collateral_txid = ? AND collateral_vout = ?
                ''', (transaction.inputs[0].prev_txid, transaction.inputs[0].prev_vout))
                if duplicate_cursor.fetchone():
                    print("Collateral UTXO is already bound to an active masternode")
                    return False
            elif tx_type == TX_TYPE_MASTERNODE_DEACTIVATE:
                masternode_id = metadata.get('masternode_id')
                operator_address = metadata.get('operator_address')
                mn_cursor = self.conn.execute('''
                    SELECT operator_address, collateral_txid, collateral_vout, status
                    FROM masternodes
                    WHERE masternode_id = ?
                ''', (masternode_id,))
                mn_row = mn_cursor.fetchone()
                if not mn_row:
                    print(f"Masternode not found: {masternode_id}")
                    return False
                if mn_row[3] != 'active':
                    print(f"Masternode is not active: {masternode_id}")
                    return False
                if mn_row[0] != operator_address:
                    print("Masternode operator does not match deactivation metadata")
                    return False
                if len(transaction.inputs) != 1:
                    print("Masternode deactivation must spend exactly one collateral UTXO")
                    return False
                if transaction.inputs[0].prev_txid != mn_row[1] or transaction.inputs[0].prev_vout != mn_row[2]:
                    print("Masternode deactivation does not spend the active collateral UTXO")
                    return False
                if input_addresses != {operator_address}:
                    print("Masternode deactivation inputs do not belong to operator")
                    return False
                if len(transaction.outputs) != 1:
                    print("Masternode deactivation must return a single unlocked output")
                    return False
                unlock_output = transaction.outputs[0]
                if (
                    unlock_output.address != operator_address
                    or unlock_output.script_pubkey != b"masternode_unlock"
                    or unlock_output.value <= 0
                    or unlock_output.value + fee != total_input_value
                ):
                    print(
                        "Masternode deactivation must return collateral minus "
                        "the declared fee in one canonical owner output"
                    )
                    return False
            elif tx_type == TX_TYPE_RWA_CREATE:
                asset_id = metadata.get('asset_id')
                owner_address = metadata.get('owner_address')
                asset_hash = (metadata.get('asset_hash') or '')
                if not asset_id or not owner_address or not asset_hash:
                    print("RWA create transaction missing asset_id/owner_address/asset_hash")
                    return False
                # asset_hash must be a sha256 hex digest (the off-chain asset
                # definition's commitment) so the anchor is well-formed.
                if len(asset_hash) != RWA_ASSET_HASH_HEX_LEN or any(
                    c not in "0123456789abcdef" for c in asset_hash.lower()
                ):
                    print("RWA create asset_hash must be a 64-char sha256 hex digest")
                    return False
                # The creator must own the inputs being spent (signature is checked
                # below); this binds asset ownership to a key the user controls.
                if input_addresses != {owner_address}:
                    print("RWA create inputs do not belong to the declared owner")
                    return False
                if fee < RWA_CREATION_MIN_FEE:
                    print(f"RWA create fee below anti-spam minimum {RWA_CREATION_MIN_FEE}")
                    return False
                # Outputs may only return change to the owner (no value is created;
                # the asset itself is an extra_data commitment, not a UTXO).
                for out in transaction.outputs:
                    if out.address != owner_address:
                        print("RWA create outputs may only return change to the owner")
                        return False
                existing_cursor = self.conn.execute(
                    'SELECT 1 FROM rwa_assets WHERE asset_id = ?', (asset_id,)
                )
                if existing_cursor.fetchone():
                    print(f"RWA asset already exists: {asset_id}")
                    return False
            elif tx_type == TX_TYPE_KEY_REGISTER:
                owner_address = metadata.get('owner_address')
                kem_pub = (metadata.get('kem_pub') or '')
                sig_pub = (metadata.get('sig_pub') or '')
                if not owner_address or not kem_pub or not sig_pub:
                    print("Key register transaction missing owner_address/kem_pub/sig_pub")
                    return False
                # Public keys must be the correct post-quantum sizes (hex).
                hexset = set("0123456789abcdef")
                if (len(kem_pub) != ML_KEM768_PUB_HEX_LEN
                        or any(c not in hexset for c in kem_pub.lower())):
                    print("Key register kem_pub must be a 1184-byte ML-KEM-768 hex pubkey")
                    return False
                if (len(sig_pub) != ML_DSA44_PUB_HEX_LEN
                        or any(c not in hexset for c in sig_pub.lower())):
                    print("Key register sig_pub must be a 1312-byte ML-DSA-44 hex pubkey")
                    return False
                # Binds the messaging keys to a key the owner controls.
                if input_addresses != {owner_address}:
                    print("Key register inputs do not belong to the declared owner")
                    return False
                if fee < MSG_KEY_REGISTER_MIN_FEE:
                    print(f"Key register fee below anti-spam minimum {MSG_KEY_REGISTER_MIN_FEE}")
                    return False
                for out in transaction.outputs:
                    if out.address != owner_address:
                        print("Key register outputs may only return change to the owner")
                        return False

            # Enforce spend authorization for EVERY non-coinbase input.
            #
            # Each input must carry a Dilithium signature whose public key hashes
            # to the address that owns the spent UTXO (input_rows[i]['address']),
            # and that signature must verify over the canonical transaction
            # sighash. This is the consensus-level proof that the spender owns
            # the coins. Without it, value conservation alone would let anyone
            # spend any UTXO they merely reference.
            for i, inp in enumerate(transaction.inputs):
                utxo_address = input_rows[i]['address']
                if inp.signature_type != "dilithium":
                    print(f"Input {i} is not authorized: Dilithium signature required "
                          f"(got signature_type={inp.signature_type!r})")
                    return False
                if not transaction.verify_quantum_signature(
                    i,
                    expected_address=utxo_address,
                    network=self.network_profile.network_label,
                ):
                    print(f"Input {i} failed spend authorization (signature/owner binding)")
                    return False

            return True
            
        except Exception as e:
            print(f"Transaction validation error: {e}")
            return False
    
    def get_balance(self, address: str) -> int:
        """Get the address balance that is spendable in the next block."""
        spend_height = self.get_block_height() + 1
        maturity_cutoff = (
            spend_height - self.coinbase_maturity
            if self.coinbase_maturity is not None else -1
        )
        cursor = self.conn.execute('''
            SELECT SUM(amount)
            FROM utxos
            WHERE address = ?
              AND spent = FALSE
              AND (is_coinbase = FALSE OR (? IS NOT NULL AND created_height <= ?))
              AND NOT EXISTS (
                  SELECT 1
                  FROM masternodes
                  WHERE status = 'active'
                    AND collateral_txid = utxos.txid
                    AND collateral_vout = utxos.vout
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM stakes
                  WHERE status = 'active'
                    AND lock_txid = utxos.txid
                    AND lock_vout = utxos.vout
              )
        ''', (address, self.coinbase_maturity, maturity_cutoff))
        result = cursor.fetchone()
        return result[0] if result[0] else 0

    def get_immature_balance(self, address: str) -> int:
        """Get unspent block-issued value that cannot enter the next block."""
        spend_height = self.get_block_height() + 1
        maturity_cutoff = (
            spend_height - self.coinbase_maturity
            if self.coinbase_maturity is not None else -1
        )
        cursor = self.conn.execute('''
            SELECT SUM(amount)
            FROM utxos
            WHERE address = ?
              AND spent = FALSE
              AND is_coinbase = TRUE
              AND (? IS NULL OR created_height > ?)
              AND NOT EXISTS (
                  SELECT 1
                  FROM masternodes
                  WHERE status = 'active'
                    AND collateral_txid = utxos.txid
                    AND collateral_vout = utxos.vout
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM stakes
                  WHERE status = 'active'
                    AND lock_txid = utxos.txid
                    AND lock_vout = utxos.vout
              )
        ''', (address, self.coinbase_maturity, maturity_cutoff))
        result = cursor.fetchone()
        return result[0] if result[0] else 0

    def get_total_unlocked_balance(self, address: str) -> int:
        """Get spendable plus immature value, excluding active collateral."""
        return self.get_balance(address) + self.get_immature_balance(address)

    def get_balance_wepo(self, address: str) -> float:
        """Get balance for an address in WEPO units."""
        return self.get_balance(address) / COIN

    def get_immature_balance_wepo(self, address: str) -> float:
        """Get immature block-issued balance in WEPO units."""
        return self.get_immature_balance(address) / COIN
    
    def get_utxos_for_address(self, address: str) -> List[dict]:
        """Get UTXOs that are spendable in the next block."""
        spend_height = self.get_block_height() + 1
        maturity_cutoff = (
            spend_height - self.coinbase_maturity
            if self.coinbase_maturity is not None else -1
        )
        cursor = self.conn.execute('''
            SELECT txid, vout, amount, script_pubkey
            FROM utxos 
            WHERE address = ?
              AND spent = FALSE
              AND (is_coinbase = FALSE OR (? IS NOT NULL AND created_height <= ?))
              AND NOT EXISTS (
                  SELECT 1
                  FROM masternodes
                  WHERE status = 'active'
                    AND collateral_txid = utxos.txid
                    AND collateral_vout = utxos.vout
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM stakes
                  WHERE status = 'active'
                    AND lock_txid = utxos.txid
                    AND lock_vout = utxos.vout
              )
        ''', (address, self.coinbase_maturity, maturity_cutoff))
        
        utxos = []
        for row in cursor.fetchall():
            utxos.append({
                'txid': row[0],
                'vout': row[1],
                'amount': row[2],
                'script_pubkey': row[3]
            })
        
        return utxos

    def get_wallet_activity_totals(self, address: str) -> dict:
        """Get indexed wallet receive/send totals."""
    def get_transaction_input_utxo_context(
        self,
        transaction: Transaction,
        expected_address: str,
    ) -> List[dict]:
        """Return exact public UTXO data for an isolated signing policy.

        The signer treats this context as untrusted and protects value by
        enforcing owner-only outputs, value conservation, a fee ceiling, and
        persistent outpoint fencing. Consensus still proves existence,
        unspent status, and the same amounts when the signed tx is submitted.
        """
        contexts = []
        for transaction_input in transaction.inputs:
            row = self.conn.execute(
                """SELECT amount, address, script_pubkey, spent
                   FROM utxos WHERE txid = ? AND vout = ?""",
                (transaction_input.prev_txid, transaction_input.prev_vout),
            ).fetchone()
            if row is None or bool(row[3]):
                raise ValueError("Unsigned transaction references a missing or spent UTXO")
            if row[1] != expected_address:
                raise ValueError("Unsigned transaction input is not owned by the expected address")
            contexts.append({
                "prev_txid": transaction_input.prev_txid,
                "prev_vout": transaction_input.prev_vout,
                "amount": row[0],
                "address": row[1],
                "script_pubkey": bytes(row[2] or b"").hex(),
            })
        return contexts

        cursor = self.conn.execute('''
            SELECT
                COALESCE(SUM(CASE
                    WHEN activity_type IN (
                        'receive',
                        'stake_unlock',
                        'masternode_unlock',
                        'staker_reward',
                        'masternode_reward',
                        'validator_reward'
                    )
                    THEN amount ELSE 0 END), 0) AS total_received_atomic,
                COALESCE(SUM(CASE
                    WHEN activity_type IN ('send', 'stake_lock', 'masternode_lock')
                    THEN amount ELSE 0 END), 0) AS total_sent_atomic
            FROM wallet_activity
            WHERE address = ?
        ''', (address,))
        total_received_atomic, total_sent_atomic = cursor.fetchone() or (0, 0)
        total_received_atomic = total_received_atomic or 0
        total_sent_atomic = total_sent_atomic or 0
        return {
            'total_received_atomic': total_received_atomic,
            'total_sent_atomic': total_sent_atomic,
            'total_received': total_received_atomic / COIN,
            'total_sent': total_sent_atomic / COIN,
        }

    def get_wallet_activity_for_address(self, address: str, limit: Optional[int] = 50) -> List[dict]:
        """Get indexed wallet activity ordered newest-first."""
        query = '''
            SELECT activity_id, txid, activity_type, amount, counterparty_address, block_height, block_hash, timestamp
            FROM wallet_activity
            WHERE address = ?
            ORDER BY block_height DESC, timestamp DESC, activity_id DESC
        '''
        params: List[Union[str, int]] = [address]
        if limit is not None:
            query += ' LIMIT ?'
            params.append(limit)

        cursor = self.conn.execute(query, tuple(params))
        chain_height = self.get_block_height()
        activities = []
        for activity_id, txid, activity_type, amount_atomic, counterparty_address, block_height, block_hash, timestamp in cursor.fetchall():
            if activity_type in ('send', 'stake_lock', 'masternode_lock'):
                from_address = address
                to_address = counterparty_address or address
            else:
                from_address = counterparty_address or ('protocol' if activity_type.endswith('_reward') else 'coinbase')
                to_address = address

            activities.append({
                'activity_id': activity_id,
                'txid': txid,
                'type': activity_type,
                'amount': amount_atomic / COIN,
                'amount_atomic': amount_atomic,
                'from_address': from_address,
                'to_address': to_address,
                'timestamp': timestamp,
                'status': 'confirmed',
                'confirmations': max(0, chain_height - block_height + 1),
                'block_height': block_height,
                'block_hash': block_hash,
            })

        return activities

    def create_transaction(
        self,
        from_address: str,
        to_address: str,
        amount: int,
        fee: int = DEFAULT_TRANSACTION_FEE,
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
    
    def create_rwa_creation(self, owner_address: str, asset_hash: str, name: Optional[str] = None,
                            asset_type: Optional[str] = None, fee: int = RWA_CREATION_MIN_FEE,
                            metadata: Optional[Dict[str, Any]] = None, asset_id: Optional[str] = None,
                            return_unsigned: bool = False):
        """Build an on-chain RWA creation transaction (self-custody, client-signed).

        Spends the owner's UTXOs to cover the anti-spam fee, returns change to the
        owner, and anchors {asset_id, owner_address, asset_hash, ...} in extra_data
        (signed via the canonical sighash). With return_unsigned=True, returns the
        deterministic UNSIGNED Transaction for client-side Dilithium signing.
        """
        self._require_transaction_type_consensus_ready(TX_TYPE_RWA_CREATE)
        asset_hash = (asset_hash or "").lower()
        if len(asset_hash) != RWA_ASSET_HASH_HEX_LEN or any(c not in "0123456789abcdef" for c in asset_hash):
            raise ValueError("asset_hash must be a 64-char sha256 hex digest of the asset definition")
        fee = int(fee)
        if fee < RWA_CREATION_MIN_FEE:
            raise ValueError(f"RWA creation fee must be at least {RWA_CREATION_MIN_FEE} atomic units")

        balance = self.get_balance(owner_address)
        if balance < fee:
            raise ValueError(f"Insufficient balance for RWA creation fee: {balance / COIN} WEPO")

        selected_utxos = []
        input_total = 0
        for utxo in self.get_utxos_for_address(owner_address):
            selected_utxos.append(utxo)
            input_total += utxo['amount']
            if input_total >= fee:
                break
        if input_total < fee:
            raise ValueError("Insufficient spendable balance to cover the RWA creation fee")

        if asset_id is None:
            asset_id = f"rwa_{owner_address}_{int(time.time())}_{asset_hash[:8]}"

        inputs = [
            TransactionInput(prev_txid=u['txid'], prev_vout=u['vout'],
                             script_sig=b"signature_placeholder", sequence=0xffffffff)
            for u in selected_utxos
        ]
        outputs = []
        change_amount = input_total - fee
        if change_amount > 0:
            outputs.append(TransactionOutput(value=change_amount, script_pubkey=b"change_script",
                                             address=owner_address))

        extra: Dict[str, Any] = {
            'asset_id': asset_id,
            'owner_address': owner_address,
            'asset_hash': asset_hash,
        }
        if name:
            extra['name'] = name
        if asset_type:
            extra['asset_type'] = asset_type
        for k, v in dict(metadata or {}).items():
            if k not in extra:
                extra[k] = v

        transaction = Transaction(version=1, inputs=inputs, outputs=outputs, lock_time=0,
                                  fee=fee, tx_type=TX_TYPE_RWA_CREATE, extra_data=extra)
        if return_unsigned:
            return transaction
        if not self.add_transaction_to_mempool(transaction):
            raise ValueError("Failed to submit RWA creation transaction")
        return asset_id

    def create_key_registration(self, owner_address: str, kem_pub: str, sig_pub: str,
                                fee: int = MSG_KEY_REGISTER_MIN_FEE,
                                return_unsigned: bool = False):
        """Build an on-chain messaging-key registration transaction (self-custody).

        Anchors the owner's ML-KEM-768 + ML-DSA-44 messaging public keys on-chain,
        bound to the owner address, so peers can discover them trustlessly. Spends
        the owner's UTXOs for the anti-spam fee and returns change. With
        return_unsigned=True returns the deterministic UNSIGNED Transaction.
        """
        self._require_transaction_type_consensus_ready(TX_TYPE_KEY_REGISTER)
        kem_pub = (kem_pub or "").lower()
        sig_pub = (sig_pub or "").lower()
        hexset = set("0123456789abcdef")
        if len(kem_pub) != ML_KEM768_PUB_HEX_LEN or any(c not in hexset for c in kem_pub):
            raise ValueError("kem_pub must be a 1184-byte ML-KEM-768 hex public key")
        if len(sig_pub) != ML_DSA44_PUB_HEX_LEN or any(c not in hexset for c in sig_pub):
            raise ValueError("sig_pub must be a 1312-byte ML-DSA-44 hex public key")
        fee = int(fee)
        if fee < MSG_KEY_REGISTER_MIN_FEE:
            raise ValueError(f"Key registration fee must be at least {MSG_KEY_REGISTER_MIN_FEE} atomic units")

        balance = self.get_balance(owner_address)
        if balance < fee:
            raise ValueError(f"Insufficient balance for key registration fee: {balance / COIN} WEPO")

        selected_utxos = []
        input_total = 0
        for utxo in self.get_utxos_for_address(owner_address):
            selected_utxos.append(utxo)
            input_total += utxo['amount']
            if input_total >= fee:
                break
        if input_total < fee:
            raise ValueError("Insufficient spendable balance to cover the key registration fee")

        inputs = [
            TransactionInput(prev_txid=u['txid'], prev_vout=u['vout'],
                             script_sig=b"signature_placeholder", sequence=0xffffffff)
            for u in selected_utxos
        ]
        outputs = []
        change_amount = input_total - fee
        if change_amount > 0:
            outputs.append(TransactionOutput(value=change_amount, script_pubkey=b"change_script",
                                             address=owner_address))

        transaction = Transaction(version=1, inputs=inputs, outputs=outputs, lock_time=0,
                                  fee=fee, tx_type=TX_TYPE_KEY_REGISTER,
                                  extra_data={'owner_address': owner_address,
                                              'kem_pub': kem_pub, 'sig_pub': sig_pub})
        if return_unsigned:
            return transaction
        if not self.add_transaction_to_mempool(transaction):
            raise ValueError("Failed to submit key registration transaction")
        return owner_address

    def create_stake(
        self,
        staker_address: str,
        amount: int,
        return_unsigned: bool = False,
        fee: int = DEFAULT_TRANSACTION_FEE,
    ):
        """Create a new stake.

        With return_unsigned=True, returns the deterministic UNSIGNED stake
        Transaction (for client-side Dilithium signing) instead of submitting it.
        The staker spends their own UTXOs into the canonical stake-lock output, so
        consensus now requires the staker's signature on every input.
        """
        self._require_transaction_type_consensus_ready(TX_TYPE_STAKE_CREATE)
        if self.get_block_height() <= POS_ACTIVATION_HEIGHT:
            raise ValueError(f"Staking is not active until block {POS_ACTIVATION_HEIGHT + 1}")

        if amount < MIN_STAKE_AMOUNT:
            raise ValueError(f"Minimum stake amount is {MIN_STAKE_AMOUNT / COIN} WEPO")

        if type(fee) is not int or fee < 0:
            raise ValueError("Stake fee must be a nonnegative integer")
        required_total = amount + fee

        # Check if user has sufficient balance
        balance = self.get_balance(staker_address)
        if balance < required_total:
            raise ValueError(f"Insufficient balance: {balance / COIN} WEPO")

        selected_utxos = []
        locked_total = 0
        for utxo in self.get_utxos_for_address(staker_address):
            selected_utxos.append(utxo)
            locked_total += utxo['amount']
            if locked_total >= required_total:
                break

        if locked_total < required_total:
            raise ValueError(f"Insufficient spendable balance: {locked_total / COIN} WEPO")

        stake_id = f"stake_{staker_address}_{int(time.time())}"
        inputs = [
            TransactionInput(
                prev_txid=utxo['txid'],
                prev_vout=utxo['vout'],
                script_sig=b"signature_placeholder",
                sequence=0xffffffff,
            )
            for utxo in selected_utxos
        ]
        outputs = [
            TransactionOutput(
                value=amount,
                script_pubkey=f"stake_lock:{stake_id}".encode(),
                address=staker_address,
            )
        ]

        change_amount = locked_total - required_total
        if change_amount > 0:
            outputs.append(TransactionOutput(
                value=change_amount,
                script_pubkey=b"change_script",
                address=staker_address,
            ))

        transaction = Transaction(
            version=1,
            inputs=inputs,
            outputs=outputs,
            lock_time=0,
            fee=fee,
            tx_type=TX_TYPE_STAKE_CREATE,
            extra_data={
                'stake_id': stake_id,
                'staker_address': staker_address,
                'amount': amount,
            },
        )
        if return_unsigned:
            return transaction
        if not self.add_transaction_to_mempool(transaction):
            raise ValueError("Failed to submit canonical stake transaction")

        print(f"Submitted canonical stake transaction: {stake_id} for {amount / COIN} WEPO")
        return stake_id

    def deactivate_stake(
        self,
        stake_id: str,
        staker_address: str,
        return_unsigned: bool = False,
        fee: int = DEFAULT_TRANSACTION_FEE,
    ):
        """Deactivate an active stake and release the principal back to spendable balance.

        With return_unsigned=True the canonical path returns the UNSIGNED
        deactivation Transaction (the staker must sign to spend the stake-lock
        UTXO). The legacy side-state path has no real UTXO to spend and still
        completes server-side, returning its result dict unchanged.
        """
        self._require_transaction_type_consensus_ready(TX_TYPE_STAKE_DEACTIVATE)
        cursor = self.conn.execute('''
            SELECT stake_id, staker_address, amount, status, total_rewards, lock_txid, lock_vout
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

        if not row[5] or row[6] is None:
            raise ValueError(
                "Legacy side-state stake has no canonical lock UTXO; "
                "automatic value synthesis is disabled"
            )

        if type(fee) is not int or fee < 0:
            raise ValueError("Stake deactivation fee must be a nonnegative integer")
        if fee >= row[2]:
            raise ValueError("Stake deactivation fee must be below locked principal")

        transaction = Transaction(
            version=1,
            inputs=[TransactionInput(
                prev_txid=row[5],
                prev_vout=row[6],
                script_sig=b"signature_placeholder",
                sequence=0xffffffff,
            )],
            outputs=[TransactionOutput(
                value=row[2] - fee,
                script_pubkey=b"stake_unlock",
                address=staker_address,
            )],
            lock_time=0,
            fee=fee,
            tx_type=TX_TYPE_STAKE_DEACTIVATE,
            extra_data={
                'stake_id': stake_id,
                'staker_address': staker_address,
                'amount': row[2],
            },
        )
        if return_unsigned:
            return transaction
        if not self.add_transaction_to_mempool(transaction):
            raise ValueError("Failed to submit canonical stake deactivation transaction")

        txid = transaction.calculate_txid()
        return {
            'stake_id': row[0],
            'staker_address': row[1],
            'amount': row[2],
            'total_rewards': row[4],
            'status': 'pending',
            'unlock_txid': txid,
            'txid': txid,
            'source': 'canonical_transaction',
        }
    
    def create_masternode(
        self,
        operator_address: str,
        collateral_txid: str,
        collateral_vout: int,
        ip_address: str = None,
        port: int = 22567,
        return_unsigned: bool = False,
        fee: int = DEFAULT_TRANSACTION_FEE,
    ):
        """Create a new masternode.

        With return_unsigned=True, returns the deterministic UNSIGNED masternode
        registration Transaction for client-side signing. The operator spends
        their collateral UTXO into the masternode-lock output, so consensus now
        requires the operator's signature.
        """
        self._require_transaction_type_consensus_ready(TX_TYPE_MASTERNODE_CREATE)
        candidate_height = self.get_block_height() + 1
        required_collateral = self.get_masternode_collateral_for_height(candidate_height)
        
        # Verify collateral UTXO exists, belongs to the operator, and has correct amount.
        cursor = self.conn.execute('''
            SELECT address, amount, spent FROM utxos WHERE txid = ? AND vout = ?
        ''', (collateral_txid, collateral_vout))
        
        utxo = cursor.fetchone()
        if not utxo:
            raise ValueError("Invalid collateral UTXO or insufficient amount")

        utxo_address, utxo_amount, utxo_spent = utxo
        if utxo_address != operator_address:
            raise ValueError("Collateral UTXO does not belong to operator")

        if type(fee) is not int or fee < 0:
            raise ValueError("Masternode registration fee must be a nonnegative integer")

        if utxo_spent or utxo_amount < required_collateral:
            raise ValueError(f"Invalid collateral UTXO or insufficient amount")

        existing_cursor = self.conn.execute('''
            SELECT masternode_id
            FROM masternodes
            WHERE status = 'active' AND collateral_txid = ? AND collateral_vout = ?
        ''', (collateral_txid, collateral_vout))
        if existing_cursor.fetchone():
            raise ValueError("Collateral UTXO is already assigned to an active masternode")

        fee_utxos = []
        fee_funding_total = 0
        for candidate in self.get_utxos_for_address(operator_address):
            if (
                candidate['txid'] == collateral_txid
                and candidate['vout'] == collateral_vout
            ):
                continue
            fee_utxos.append(candidate)
            fee_funding_total += candidate['amount']
            if fee_funding_total >= fee:
                break
        if fee_funding_total < fee:
            raise ValueError("Insufficient separate spendable balance for masternode fee")

        masternode_id = f"mn_{operator_address}_{int(time.time())}"
        inputs = [
            TransactionInput(
                prev_txid=collateral_txid,
                prev_vout=collateral_vout,
                script_sig=b"signature_placeholder",
                sequence=0xffffffff,
            )
        ]
        inputs.extend(
            TransactionInput(
                prev_txid=fee_utxo['txid'],
                prev_vout=fee_utxo['vout'],
                script_sig=b"signature_placeholder",
                sequence=0xffffffff,
            )
            for fee_utxo in fee_utxos
        )
        outputs = [TransactionOutput(
            value=utxo_amount,
            script_pubkey=f"masternode_lock:{masternode_id}".encode(),
            address=operator_address,
)]
        fee_change = fee_funding_total - fee
        if fee_change:
            outputs.append(TransactionOutput(
                value=fee_change,
                script_pubkey=b"change_script",
                address=operator_address,
            ))

        transaction = Transaction(
            version=1,
            inputs=inputs,
            outputs=outputs,
            lock_time=0,
            fee=fee,
            tx_type=TX_TYPE_MASTERNODE_CREATE,
            extra_data={
                'masternode_id': masternode_id,
                'operator_address': operator_address,
                'ip_address': ip_address,
                'port': port,
            },
        )
        if return_unsigned:
            return transaction
        if not self.add_transaction_to_mempool(transaction):
            raise ValueError("Failed to submit canonical masternode registration transaction")

        print(f"Submitted canonical masternode registration: {masternode_id}")
        return masternode_id

    def deactivate_masternode(
        self,
        masternode_id: str,
        operator_address: str,
        return_unsigned: bool = False,
        fee: int = DEFAULT_TRANSACTION_FEE,
    ):
        """Deactivate an active masternode and release its collateral back to spendable balance.

        With return_unsigned=True, returns the UNSIGNED deactivation Transaction
        (the operator must sign to spend the masternode-lock collateral UTXO).
        """
        self._require_transaction_type_consensus_ready(TX_TYPE_MASTERNODE_DEACTIVATE)
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

        collateral_cursor = self.conn.execute('''
            SELECT amount
            FROM utxos
            WHERE txid = ? AND vout = ?
        ''', (row[2], row[3]))
        collateral_row = collateral_cursor.fetchone()
        collateral_amount = collateral_row[0] if collateral_row else 0

        if type(fee) is not int or fee < 0:
            raise ValueError("Masternode deactivation fee must be a nonnegative integer")
        if fee >= collateral_amount:
            raise ValueError("Masternode deactivation fee must be below collateral")

        transaction = Transaction(
            version=1,
            inputs=[TransactionInput(
                prev_txid=row[2],
                prev_vout=row[3],
                script_sig=b"signature_placeholder",
                sequence=0xffffffff,
            )],
            outputs=[TransactionOutput(
                value=collateral_amount - fee,
                script_pubkey=b"masternode_unlock",
                address=operator_address,
            )],
            lock_time=0,
            fee=fee,
            tx_type=TX_TYPE_MASTERNODE_DEACTIVATE,
            extra_data={
                'masternode_id': masternode_id,
                'operator_address': operator_address,
            },
        )
        if return_unsigned:
            return transaction
        if not self.add_transaction_to_mempool(transaction):
            raise ValueError("Failed to submit canonical masternode deactivation transaction")

        txid = transaction.calculate_txid()

        return {
            'masternode_id': row[0],
            'operator_address': row[1],
            'collateral_txid': row[2],
            'collateral_vout': row[3],
            'status': 'pending',
            'txid': txid,
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
        """Get stakes active in the currently replayed canonical branch state."""
        cursor = self.conn.execute('''
            SELECT stake_id, staker_address, amount, start_height, start_time, last_reward_height, total_rewards, status, unlock_height
            FROM stakes
            WHERE status = 'active'
              AND (
                  lock_txid IS NULL
                  OR lock_vout IS NULL
                  OR EXISTS (
                  SELECT 1
                  FROM utxos
                  WHERE utxos.txid = stakes.lock_txid
                    AND utxos.vout = stakes.lock_vout
                    AND utxos.spent = FALSE
              )
              )
            ORDER BY staker_address ASC, stake_id ASC
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
        """Get masternodes active in the currently replayed branch state."""
        cursor = self.conn.execute('''
            SELECT masternode_id, operator_address, collateral_txid, collateral_vout, ip_address, port, start_height, start_time, last_ping, status, total_rewards
            FROM masternodes
            WHERE status = 'active'
              AND EXISTS (
                  SELECT 1
                  FROM utxos
                  WHERE utxos.txid = masternodes.collateral_txid
                    AND utxos.vout = masternodes.collateral_vout
                    AND utxos.spent = FALSE
              )
            ORDER BY masternode_id ASC
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

    def calculate_staking_reward_entries(self, block_height: int, block: Optional[Block] = None) -> List[Dict[str, Union[str, int]]]:
        """Calculate detailed PoS reward entries for active stakes and masternodes.

        The total pool is the hard-cap-clamped PoS pool (clamped_pos_pool), so this
        distribution path can never push cumulative issuance past SUPPLY_CAP. The
        pool is split 60% stakers / 40% masternodes; the split conserves every
        satoshi (no rounding loss), and if one side has no active members its share
        rolls to the other side so the full clamped pool is always paid out to the
        workers that exist (no dead coins). If neither side exists, nothing is
        minted (issuance simply pauses, staying under the cap).
        """
        reward_entries = []

        if block_height <= POS_ACTIVATION_HEIGHT:
            return reward_entries

        active_stakes = sorted(
            self.get_active_stakes(),
            key=lambda item: (item.staker_address, item.stake_id),
        )
        active_masternodes = sorted(
            self.get_active_masternodes(),
            key=lambda item: item.masternode_id,
        )

        if not active_stakes and not active_masternodes:
            return reward_entries

        consensus_type = "pos" if (block is not None and block.header.is_pos_block()) else "pow"
        total_pos_reward = self.clamped_pos_pool(block_height, consensus_type)
        if total_pos_reward <= 0:
            return reward_entries

        # Conserve every satoshi and roll an empty side's share to the other side.
        if active_stakes and active_masternodes:
            staking_reward_pool = total_pos_reward * 60 // 100
            masternode_reward_pool = total_pos_reward - staking_reward_pool
        elif active_stakes:
            staking_reward_pool = total_pos_reward
            masternode_reward_pool = 0
        else:  # masternodes only
            staking_reward_pool = 0
            masternode_reward_pool = total_pos_reward

        if active_stakes and staking_reward_pool > 0:
            total_stake_amount = sum(stake.amount for stake in active_stakes)
            remaining_rewards = staking_reward_pool

            for index, stake in enumerate(active_stakes):
                if index == len(active_stakes) - 1:
                    reward_amount = remaining_rewards
                else:
                    reward_amount = staking_reward_pool * stake.amount // total_stake_amount
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
            base_reward = (25 * COIN) // 2  # 12.5 WEPO per block for years 2-5
        elif years_since_pos < 10:
            base_reward = (25 * COIN) // 4  # 6.25 WEPO per block for years 5-10
        else:
            # Continue halving every 5 years
            halvings = (years_since_pos - 10) // 5
            base_reward = (25 * COIN) // 4
            for _ in range(halvings):
                base_reward //= 2

        # The returned value is the total PoS reward pool for the block.
        # Downstream distribution splits it between stakers and masternodes.
        # (integer half — exact, no float rounding)
        return base_reward // 2
    
    def distribute_staking_rewards(self, block_height: int, block_hash: str, block: Optional[Block] = None):
        """Distribute the hard-cap-clamped PoS reward pool for a block to stakers
        and masternodes (the single PoS issuance path, distribution-only model)."""
        reward_entries = self.calculate_staking_reward_entries(block_height, block)
        if block is None:
            raise ValueError("PoS reward persistence requires the canonical block")
        reward_timestamp = block.header.timestamp
        if not reward_entries:
            return
        
        for reward_entry in reward_entries:
            address = reward_entry['recipient_address']
            reward_amount = reward_entry['amount']
            reward_txid = f"pos_reward_{reward_entry['reward_id']}"
            
            self.conn.execute('''
                INSERT INTO utxos (
                    txid, vout, address, amount, script_pubkey,
                    created_height, is_coinbase, spent
                ) VALUES (?, ?, ?, ?, ?, ?, TRUE, FALSE)
            ''', (reward_txid, 0, address, reward_amount, b"pos_reward", block_height))

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
                ''', (reward_amount, reward_timestamp, reward_entry['recipient_reference']))
            
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
                reward_timestamp,
            ))
            self._record_reward_wallet_activity(
                reward_id=reward_entry['reward_id'],
                recipient_address=address,
                recipient_type=reward_entry['recipient_type'],
                amount=reward_amount,
                block_height=block_height,
                block_hash=block_hash,
                timestamp=reward_timestamp,
            )

    def record_fee_distribution_rewards(self, block: Block):
        """Record staking and masternode fee distributions from a block coinbase."""
        if not block.transactions:
            return

        coinbase_tx = block.transactions[0]
        if not coinbase_tx.is_coinbase():
            return

        for output_index, output in enumerate(coinbase_tx.outputs[1:], start=1):
            script_marker = output.script_pubkey.decode(errors='ignore') if output.script_pubkey else ''
            reward_timestamp = block.header.timestamp

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
                self._record_reward_wallet_activity(
                    reward_id=reward_id,
                    recipient_address=output.address,
                    recipient_type='staker',
                    amount=output.value,
                    block_height=block.height,
                    block_hash=block.get_block_hash(),
                    timestamp=reward_timestamp,
                )
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
                self._record_reward_wallet_activity(
                    reward_id=reward_id,
                    recipient_address=output.address,
                    recipient_type='masternode',
                    amount=output.value,
                    block_height=block.height,
                    block_hash=block.get_block_hash(),
                    timestamp=reward_timestamp,
                )
    
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
            SELECT activity_type, COALESCE(SUM(amount), 0)
            FROM wallet_activity
            WHERE address = ?
              AND activity_type IN ('staker_reward', 'masternode_reward', 'validator_reward')
            GROUP BY activity_type
        ''', (address,))

        staker_total = 0
        masternode_total = 0
        validator_total = 0
        for activity_type, total_amount in totals_cursor.fetchall():
            if activity_type == 'staker_reward':
                staker_total = total_amount or 0
            elif activity_type == 'masternode_reward':
                masternode_total = total_amount or 0
            elif activity_type == 'validator_reward':
                validator_total = total_amount or 0

        rewards_cursor = self.conn.execute('''
            SELECT activity_id, txid, activity_type, amount, block_height, block_hash, timestamp
            FROM wallet_activity
            WHERE address = ?
              AND activity_type IN ('staker_reward', 'masternode_reward', 'validator_reward')
            ORDER BY block_height DESC, timestamp DESC, activity_id DESC
            LIMIT 25
        ''', (address,))

        recent_rewards = []
        for row in rewards_cursor.fetchall():
            recipient_type = row[2].replace('_reward', '')
            recent_rewards.append({
                'reward_id': row[0],
                'txid': row[1],
                'recipient_type': recipient_type,
                'amount': row[3] / COIN,
                'amount_atomic': row[3],
                'block_height': row[4],
                'block_hash': row[5],
                'timestamp': row[6],
            })

        total_rewards = staker_total + masternode_total + validator_total
        return {
            'address': address,
            'total_rewards': total_rewards / COIN,
            'total_rewards_atomic': total_rewards,
            'staker_rewards': staker_total / COIN,
            'masternode_rewards': masternode_total / COIN,
            'validator_rewards': validator_total / COIN,
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
        except Exception:
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
        """Get total active stake in the currently replayed branch state."""
        return sum(stake.amount for stake in self.get_active_stakes())
    
    def select_pos_validator(
        self,
        block_height: int,
        parent_hash: Optional[str] = None,
    ) -> Optional[str]:
        """Select one validator deterministically from parent hash and stake."""
        if block_height <= POS_ACTIVATION_HEIGHT:
            return None
            
        active_stakes = sorted(
            self.get_active_stakes(),
            key=lambda stake: (stake.staker_address, stake.stake_id),
        )
        if not active_stakes:
            return None
            
        total_stake = sum(stake.amount for stake in active_stakes)
        if total_stake <= 0:
            return None

        if parent_hash is None:
            latest = self.get_latest_block()
            parent_hash = latest.get_block_hash() if latest else "0" * 64
        try:
            parent_bytes = bytes.fromhex(parent_hash)
        except (TypeError, ValueError):
            return None
        if len(parent_bytes) != 32:
            return None

        selection_digest = hashlib.sha3_256(
            b"WEPO_POS_VALIDATOR_SELECTION_V1\x00"
            + struct.pack("<Q", block_height)
            + parent_bytes
            + struct.pack("<Q", total_stake)
        ).digest()
        random_point = int.from_bytes(selection_digest, "big") % total_stake
        
        cumulative_stake = 0
        for stake in active_stakes:
            cumulative_stake += stake.amount
            if cumulative_stake > random_point:
                return stake.staker_address
        return None
    
    def is_valid_pos_validator(self, validator_address: str, block_height: int) -> bool:
        """Check if address is a valid PoS validator"""
        if block_height <= POS_ACTIVATION_HEIGHT:
            return False
            
        # Check if validator has active stake
        active_stakes = self.get_active_stakes()
        validator_stakes = [stake for stake in active_stakes if stake.staker_address == validator_address]
        
        return len(validator_stakes) > 0 and sum(stake.amount for stake in validator_stakes) >= MIN_STAKE_AMOUNT
    
    def get_operational_metrics(self) -> dict:
        """Return bounded, process-scoped monitoring counters."""
        with self.chain_lock:
            return {
                "scope": "process",
                "process_started_at": self.process_started_at,
                "uptime_seconds": max(0, int(time.time()) - self.process_started_at),
                "accepted_blocks_total": self.accepted_blocks_total,
                "block_validation_rejections_total": (
                    self.block_validation_rejections_total
                ),
                "reorgs_total": self.reorgs_total,
                "reorg_failures_total": self.reorg_failures_total,
                "last_reorg": (
                    dict(self.last_reorg) if self.last_reorg is not None else None
                ),
            }

    def get_network_info(self) -> dict:
        """Get network information"""
        current_height = self.get_block_height()
        consensus_type = self.get_consensus_type(current_height)
        
        network_info = {
            'height': current_height,
            'best_block_hash': self.get_latest_block().get_block_hash() if self.chain else None,
            'difficulty': self.current_difficulty,
            'mempool_size': len(self.mempool),
            'mempool_bytes': self.mempool_bytes,
            'mempool_max_transactions': MAX_MEMPOOL_TRANSACTIONS,
            'mempool_max_bytes': MAX_MEMPOOL_BYTES,
            'coinbase_maturity': self.coinbase_maturity,
            'minimum_relay_fee_per_kb': self.minimum_relay_fee_per_kb,
            'total_supply': self.get_issued_supply(),
            'supply_cap': SUPPLY_CAP,
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

    def mine_next_block(
        self,
        miner_address: str,
        pos_signer: Optional[ValidatorSigner] = None,
    ) -> Optional[Block]:
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
        if self.network_profile.pos_consensus_ready:
            active_stakes = self.get_active_stakes()
            if active_stakes:
                pos_anchor = last_pos_timestamp if last_pos_timestamp is not None else fallback_timestamp
                pos_due_at = pos_anchor + BLOCK_TIME_POS

        pos_ready = pos_due_at is not None and now >= pos_due_at
        pow_ready = now >= pow_due_at

        if pos_ready and (not pow_ready or pos_due_at <= pow_due_at):
            validator = self.select_pos_validator(next_height)
            if validator:
                pos_block = self._produce_pos_block(validator, pos_signer)
                if pos_block and self.add_block(pos_block):
                    return pos_block

        if pow_ready:
            return self.mine_block(miner_address)

        if pos_ready:
            validator = self.select_pos_validator(next_height)
            if validator:
                pos_block = self._produce_pos_block(validator, pos_signer)
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
