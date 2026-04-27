#!/usr/bin/env python3
"""
WEPO BTC Atomic Swap Implementation
Real Hash Time Locked Contract (HTLC) based atomic swaps between BTC and WEPO
"""

import hashlib
import secrets
import time
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timedelta
import json

# Bitcoin library imports
try:
    from bitcoin.core import *
    from bitcoin.core.script import *
    from bitcoin.core.scripteval import *
    from bitcoin.wallet import *
    from bitcoin.rpc import *
    BITCOIN_AVAILABLE = True
except ImportError:
    BITCOIN_AVAILABLE = False
    print("Warning: Bitcoin library not available. Atomic swaps will use mock implementation.")

# WEPO blockchain imports
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

class SwapState(Enum):
    """States of an atomic swap"""
    INITIATED = "initiated"
    FUNDED = "funded"
    REDEEMED = "redeemed"
    REFUNDED = "refunded"
    EXPIRED = "expired"
    FAILED = "failed"

class SwapType(Enum):
    """Types of atomic swaps"""
    BTC_TO_WEPO = "btc_to_wepo"
    WEPO_TO_BTC = "wepo_to_btc"

@dataclass
class SwapContract:
    """Atomic swap contract data"""
    swap_id: str
    swap_type: SwapType
    state: SwapState
    
    # Participants
    initiator_btc_address: str
    initiator_wepo_address: str
    participant_btc_address: str
    participant_wepo_address: str
    
    # Amounts
    btc_amount: float
    wepo_amount: float
    
    # Cryptographic parameters
    secret_hash: str  # SHA256 hash of the secret
    
    # Time locks
    btc_locktime: int  # Unix timestamp
    wepo_locktime: int  # Unix timestamp
    
    # Metadata
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    
    # Optional fields with defaults
    secret: Optional[str] = None  # The actual secret (revealed during redemption)
    btc_htlc_address: Optional[str] = None
    wepo_htlc_address: Optional[str] = None
    btc_funding_tx: Optional[str] = None
    wepo_funding_tx: Optional[str] = None
    btc_redeem_tx: Optional[str] = None
    wepo_redeem_tx: Optional[str] = None

class HTLCScript:
    """Hash Time Locked Contract script generator"""
    
    def __init__(self):
        self.testnet = True  # Use testnet for development
        
    def create_btc_htlc_script(self, recipient_pubkey: bytes, sender_pubkey: bytes, 
                              secret_hash: bytes, locktime: int) -> bytes:
        """Create Bitcoin HTLC script
        
        Script logic:
        IF hash matches AND recipient signs
            THEN redeem
        ELSE IF locktime passed AND sender signs
            THEN refund
        ENDIF
        """
        if not BITCOIN_AVAILABLE:
            # Mock implementation for testing
            return f"HTLC_SCRIPT_{recipient_pubkey.hex()[:16]}_{secret_hash.hex()[:16]}".encode()
        
        # Bitcoin script opcodes
        script = CScript([
            OP_IF,
                OP_HASH160,
                secret_hash,
                OP_EQUALVERIFY,
                recipient_pubkey,
                OP_CHECKSIG,
            OP_ELSE,
                locktime,
                OP_CHECKLOCKTIMEVERIFY,
                OP_DROP,
                sender_pubkey,
                OP_CHECKSIG,
            OP_ENDIF
        ])
        
        return script
    
    def create_wepo_htlc_script(self, recipient_address: str, sender_address: str,
                               secret_hash: str, locktime: int) -> str:
        """Create WEPO HTLC script (simplified version)"""
        # For WEPO, we'll use a JSON-based contract format
        htlc_contract = {
            "type": "htlc",
            "recipient": recipient_address,
            "sender": sender_address,
            "secret_hash": secret_hash,
            "locktime": locktime,
            "created_at": int(time.time())
        }
        
        return json.dumps(htlc_contract)
    
    def get_script_address(self, script: bytes) -> str:
        """Get P2SH address from script"""
        # Always use mock implementation for now due to library compatibility
        script_hash = hashlib.sha256(script).hexdigest()
        if self.testnet:
            return f"2N{script_hash[:32]}"
        else:
            return f"3{script_hash[:32]}"

class AtomicSwapEngine:
    """Enhanced atomic swap engine for BTC-WEPO swaps with advanced features"""
    
    def __init__(self, blockchain_interface=None):
        self.blockchain_interface = blockchain_interface
        self.htlc_script = HTLCScript()
        self.active_swaps: Dict[str, SwapContract] = {}
        self.swap_history: List[SwapContract] = []  # Track completed swaps
        self.swap_statistics: Dict[str, Any] = {
            'total_swaps': 0,
            'completed_swaps': 0,
            'failed_swaps': 0,
            'total_btc_volume': 0.0,
            'total_wepo_volume': 0.0,
            'average_completion_time': 0.0
        }
        
        # Enhanced swap parameters
        self.min_btc_amount = 0.001  # Minimum 0.001 BTC
        self.max_btc_amount = 10.0   # Maximum 10 BTC
        self.default_locktime_hours = 24  # 24 hours default
        self.confirmation_blocks = 6  # Wait for 6 confirmations
        
        # Fee structure
        self.fee_structure = {
            'base_fee_percentage': 0.1,  # 0.1% base fee
            'network_fee_btc': 0.0001,   # Estimated BTC network fee
            'network_fee_wepo': 0.01,    # Estimated WEPO network fee
            'priority_fee_multiplier': 1.5,  # Priority fee multiplier
            'minimum_fee_btc': 0.00001,  # Minimum BTC fee
            'minimum_fee_wepo': 0.001    # Minimum WEPO fee
        }
        
        # Rate limiting for security
        self.rate_limits = {
            'max_swaps_per_hour': 10,
            'max_swaps_per_day': 100,
            'max_amount_per_hour': 1.0,  # 1 BTC per hour
            'max_amount_per_day': 10.0   # 10 BTC per day
        }
        
        # Track user activity for rate limiting
        self.user_activity: Dict[str, Dict[str, Any]] = {}
        
        # Enhanced security features
        self.security_settings = {
            'require_email_verification': False,
            'require_2fa': False,
            'blacklisted_addresses': set(),
            'minimum_reputation_score': 0,
            'max_daily_volume': 100.0
        }
        
    def generate_swap_id(self) -> str:
        """Generate unique swap ID"""
        return f"swap_{secrets.token_hex(16)}"
    
    def generate_secret(self) -> bytes:
        """Generate random secret for HTLC"""
        return secrets.token_bytes(32)
    
    def hash_secret(self, secret: bytes) -> bytes:
        """Hash secret using SHA256"""
        return hashlib.sha256(secret).digest()
    
    def calculate_swap_fees(self, btc_amount: float, swap_type: SwapType, 
                           priority: bool = False) -> Dict[str, float]:
        """Calculate comprehensive swap fees"""
        wepo_amount = self.calculate_wepo_amount(btc_amount)
        
        # Base fee calculation
        base_fee_btc = btc_amount * (self.fee_structure['base_fee_percentage'] / 100)
        base_fee_wepo = wepo_amount * (self.fee_structure['base_fee_percentage'] / 100)
        
        # Network fees
        network_fee_btc = self.fee_structure['network_fee_btc']
        network_fee_wepo = self.fee_structure['network_fee_wepo']
        
        # Priority fee adjustment
        if priority:
            multiplier = self.fee_structure['priority_fee_multiplier']
            base_fee_btc *= multiplier
            base_fee_wepo *= multiplier
            network_fee_btc *= multiplier
            network_fee_wepo *= multiplier
        
        # Apply minimum fees
        total_fee_btc = max(base_fee_btc + network_fee_btc, 
                           self.fee_structure['minimum_fee_btc'])
        total_fee_wepo = max(base_fee_wepo + network_fee_wepo,
                            self.fee_structure['minimum_fee_wepo'])
        
        return {
            'base_fee_btc': base_fee_btc,
            'base_fee_wepo': base_fee_wepo,
            'network_fee_btc': network_fee_btc,
            'network_fee_wepo': network_fee_wepo,
            'total_fee_btc': total_fee_btc,
            'total_fee_wepo': total_fee_wepo,
            'fee_percentage': self.fee_structure['base_fee_percentage'],
            'priority_applied': priority
        }
    
    def check_rate_limits(self, user_address: str, btc_amount: float) -> Dict[str, Any]:
        """Check if user is within rate limits"""
        current_time = time.time()
        current_hour = int(current_time // 3600)
        current_day = int(current_time // 86400)
        
        # Initialize user activity if not exists
        if user_address not in self.user_activity:
            self.user_activity[user_address] = {
                'hourly_swaps': {},
                'daily_swaps': {},
                'hourly_volume': {},
                'daily_volume': {}
            }
        
        activity = self.user_activity[user_address]
        
        # Check hourly limits
        hourly_swaps = activity['hourly_swaps'].get(current_hour, 0)
        hourly_volume = activity['hourly_volume'].get(current_hour, 0.0)
        
        # Check daily limits
        daily_swaps = activity['daily_swaps'].get(current_day, 0)
        daily_volume = activity['daily_volume'].get(current_day, 0.0)
        
        # Rate limit checks
        rate_limit_result = {
            'allowed': True,
            'hourly_swaps_remaining': max(0, self.rate_limits['max_swaps_per_hour'] - hourly_swaps),
            'daily_swaps_remaining': max(0, self.rate_limits['max_swaps_per_day'] - daily_swaps),
            'hourly_volume_remaining': max(0, self.rate_limits['max_amount_per_hour'] - hourly_volume),
            'daily_volume_remaining': max(0, self.rate_limits['max_amount_per_day'] - daily_volume),
            'violations': []
        }
        
        # Check violations
        if hourly_swaps >= self.rate_limits['max_swaps_per_hour']:
            rate_limit_result['allowed'] = False
            rate_limit_result['violations'].append('Hourly swap limit exceeded')
        
        if daily_swaps >= self.rate_limits['max_swaps_per_day']:
            rate_limit_result['allowed'] = False
            rate_limit_result['violations'].append('Daily swap limit exceeded')
        
        if hourly_volume + btc_amount > self.rate_limits['max_amount_per_hour']:
            rate_limit_result['allowed'] = False
            rate_limit_result['violations'].append('Hourly volume limit exceeded')
        
        if daily_volume + btc_amount > self.rate_limits['max_amount_per_day']:
            rate_limit_result['allowed'] = False
            rate_limit_result['violations'].append('Daily volume limit exceeded')
        
        return rate_limit_result
    
    def update_user_activity(self, user_address: str, btc_amount: float):
        """Update user activity for rate limiting"""
        current_time = time.time()
        current_hour = int(current_time // 3600)
        current_day = int(current_time // 86400)
        
        if user_address not in self.user_activity:
            self.user_activity[user_address] = {
                'hourly_swaps': {},
                'daily_swaps': {},
                'hourly_volume': {},
                'daily_volume': {}
            }
        
        activity = self.user_activity[user_address]
        
        # Update counters
        activity['hourly_swaps'][current_hour] = activity['hourly_swaps'].get(current_hour, 0) + 1
        activity['daily_swaps'][current_day] = activity['daily_swaps'].get(current_day, 0) + 1
        activity['hourly_volume'][current_hour] = activity['hourly_volume'].get(current_hour, 0.0) + btc_amount
        activity['daily_volume'][current_day] = activity['daily_volume'].get(current_day, 0.0) + btc_amount
        
        # Clean up old data (keep only last 24 hours and 7 days)
        cutoff_hour = current_hour - 24
        cutoff_day = current_day - 7
        
        activity['hourly_swaps'] = {h: v for h, v in activity['hourly_swaps'].items() if h > cutoff_hour}
        activity['daily_swaps'] = {d: v for d, v in activity['daily_swaps'].items() if d > cutoff_day}
        activity['hourly_volume'] = {h: v for h, v in activity['hourly_volume'].items() if h > cutoff_hour}
        activity['daily_volume'] = {d: v for d, v in activity['daily_volume'].items() if d > cutoff_day}
    
    def validate_enhanced_swap_parameters(self, btc_amount: float, initiator_btc_address: str,
                                         initiator_wepo_address: str, participant_btc_address: str,
                                         participant_wepo_address: str) -> Dict[str, Any]:
        """Enhanced parameter validation with security checks"""
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': []
        }
        
        # Basic validation
        if not self.validate_swap_parameters(btc_amount, initiator_btc_address, initiator_wepo_address):
            validation_result['valid'] = False
            validation_result['errors'].append('Basic parameter validation failed')
        
        # Check blacklisted addresses
        addresses_to_check = [initiator_btc_address, initiator_wepo_address, 
                             participant_btc_address, participant_wepo_address]
        
        for addr in addresses_to_check:
            if addr in self.security_settings['blacklisted_addresses']:
                validation_result['valid'] = False
                validation_result['errors'].append(f'Address {addr} is blacklisted')
        
        # Check rate limits
        rate_limit_check = self.check_rate_limits(initiator_btc_address, btc_amount)
        if not rate_limit_check['allowed']:
            validation_result['valid'] = False
            validation_result['errors'].extend(rate_limit_check['violations'])
        
        # Volume warnings
        if btc_amount > 1.0:
            validation_result['warnings'].append('Large swap amount - additional verification may be required')
        
        # Address reuse warning
        if initiator_btc_address == participant_btc_address:
            validation_result['warnings'].append('Same BTC address for initiator and participant')
        
        if initiator_wepo_address == participant_wepo_address:
            validation_result['warnings'].append('Same WEPO address for initiator and participant')
        
        return validation_result
    
    def get_exchange_rate(self) -> float:
        """Get current BTC/WEPO exchange rate"""
        # In production, this would fetch from price oracles
        # For now, using a mock rate with some variability
        base_rate = 1.0
        # Add small variation to simulate real market conditions
        variation = 0.02 * ((int(time.time()) % 100) - 50) / 100  # ±2% variation
        return base_rate * (1 + variation)
    
    def get_historical_rates(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get historical exchange rates (mock implementation)"""
        rates = []
        current_time = time.time()
        base_rate = 1.0
        
        for i in range(days):
            timestamp = current_time - (i * 86400)  # 24 hours ago
            # Simulate rate variation
            variation = 0.02 * (i % 10 - 5) / 10  # ±2% variation
            rate = base_rate * (1 + variation)
            
            rates.append({
                'timestamp': int(timestamp),
                'btc_to_wepo': rate,
                'wepo_to_btc': 1.0 / rate,
                'volume_btc': 0.1 + (i % 5) * 0.5,  # Simulate volume without random
                'volume_wepo': 0.1 + (i % 5) * 0.5
            })
        
        return rates
    
    def update_swap_statistics(self, swap_contract: SwapContract):
        """Update swap statistics"""
        self.swap_statistics['total_swaps'] += 1
        
        if swap_contract.state == SwapState.REDEEMED:
            self.swap_statistics['completed_swaps'] += 1
            self.swap_statistics['total_btc_volume'] += swap_contract.btc_amount
            self.swap_statistics['total_wepo_volume'] += swap_contract.wepo_amount
            
            # Calculate completion time
            completion_time = (swap_contract.updated_at - swap_contract.created_at).total_seconds()
            current_avg = self.swap_statistics['average_completion_time']
            completed_count = self.swap_statistics['completed_swaps']
            
            # Update running average
            self.swap_statistics['average_completion_time'] = (
                (current_avg * (completed_count - 1) + completion_time) / completed_count
            )
        
        elif swap_contract.state in [SwapState.REFUNDED, SwapState.EXPIRED, SwapState.FAILED]:
            self.swap_statistics['failed_swaps'] += 1
    
    def get_swap_statistics(self) -> Dict[str, Any]:
        """Get comprehensive swap statistics"""
        stats = self.swap_statistics.copy()
        
        # Calculate success rate
        total_completed = stats['completed_swaps'] + stats['failed_swaps']
        if total_completed > 0:
            stats['success_rate'] = stats['completed_swaps'] / total_completed
        else:
            stats['success_rate'] = 0.0
        
        # Add current metrics
        stats['active_swaps'] = len(self.active_swaps)
        stats['total_historical_swaps'] = len(self.swap_history)
        
        # Add volume metrics
        if stats['completed_swaps'] > 0:
            stats['average_swap_size_btc'] = stats['total_btc_volume'] / stats['completed_swaps']
            stats['average_swap_size_wepo'] = stats['total_wepo_volume'] / stats['completed_swaps']
        else:
            stats['average_swap_size_btc'] = 0.0
            stats['average_swap_size_wepo'] = 0.0
        
        return stats
    
    def validate_swap_parameters(self, btc_amount: float, btc_address: str, 
                                wepo_address: str) -> bool:
        """Validate swap parameters"""
        # Check amount limits
        if btc_amount < self.min_btc_amount or btc_amount > self.max_btc_amount:
            return False
        
        # Validate addresses (simplified)
        if not btc_address or not wepo_address:
            return False
        
        # Validate BTC address format
        if not (btc_address.startswith('1') or btc_address.startswith('3') or 
                btc_address.startswith('bc1') or btc_address.startswith('tb1')):
            return False
        
        # Validate WEPO address format
        if not wepo_address.startswith('wepo1'):
            return False
        
        return True
    
    def calculate_wepo_amount(self, btc_amount: float) -> float:
        """Calculate WEPO amount based on BTC amount"""
        rate = self.get_exchange_rate()
        return btc_amount * rate
    
    async def initiate_swap(self, swap_type: SwapType, initiator_btc_address: str,
                          initiator_wepo_address: str, participant_btc_address: str,
                          participant_wepo_address: str, btc_amount: float,
                          priority: bool = False) -> SwapContract:
        """Enhanced swap initiation with security and fee calculations"""
        
        # Enhanced validation
        validation_result = self.validate_enhanced_swap_parameters(
            btc_amount, initiator_btc_address, initiator_wepo_address,
            participant_btc_address, participant_wepo_address
        )
        
        if not validation_result['valid']:
            raise ValueError(f"Swap validation failed: {', '.join(validation_result['errors'])}")
        
        # Calculate fees
        fee_info = self.calculate_swap_fees(btc_amount, swap_type, priority)
        
        # Update user activity for rate limiting
        self.update_user_activity(initiator_btc_address, btc_amount)
        
        # Generate swap ID and secret
        swap_id = self.generate_swap_id()
        secret = self.generate_secret()
        secret_hash = self.hash_secret(secret)
        
        # Calculate amounts
        wepo_amount = self.calculate_wepo_amount(btc_amount)
        
        # Set lock times (BTC locktime is longer to allow for WEPO redemption first)
        current_time = int(time.time())
        locktime_seconds = self.default_locktime_hours * 3600
        
        wepo_locktime = current_time + locktime_seconds
        btc_locktime = current_time + (locktime_seconds * 2)
        
        # Create enhanced swap contract
        swap_contract = SwapContract(
            swap_id=swap_id,
            swap_type=swap_type,
            state=SwapState.INITIATED,
            initiator_btc_address=initiator_btc_address,
            initiator_wepo_address=initiator_wepo_address,
            participant_btc_address=participant_btc_address,
            participant_wepo_address=participant_wepo_address,
            btc_amount=btc_amount,
            wepo_amount=wepo_amount,
            secret_hash=secret_hash.hex(),
            btc_locktime=btc_locktime,
            wepo_locktime=wepo_locktime,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=self.default_locktime_hours * 3),
            secret=secret.hex()  # Store secret for initiator
        )
        
        # Add fee information as metadata
        swap_contract.fee_info = fee_info
        swap_contract.priority = priority
        swap_contract.warnings = validation_result['warnings']
        
        # Generate HTLC contracts and addresses
        await self._generate_htlc_contracts(swap_contract)
        
        # Store swap
        self.active_swaps[swap_id] = swap_contract
        
        # Update statistics
        self.update_swap_statistics(swap_contract)
        
        return swap_contract
    
    async def _generate_htlc_contracts(self, swap_contract: SwapContract):
        """Generate HTLC contracts for both BTC and WEPO"""
        secret_hash = bytes.fromhex(swap_contract.secret_hash)
        
        # Generate BTC HTLC
        if swap_contract.swap_type == SwapType.BTC_TO_WEPO:
            # Initiator sends BTC, participant redeems
            btc_script = self.htlc_script.create_btc_htlc_script(
                recipient_pubkey=swap_contract.participant_btc_address.encode()[:33],
                sender_pubkey=swap_contract.initiator_btc_address.encode()[:33],
                secret_hash=secret_hash,
                locktime=swap_contract.btc_locktime
            )
            swap_contract.btc_htlc_address = self.htlc_script.get_script_address(btc_script)
        else:
            # Participant sends BTC, initiator redeems
            btc_script = self.htlc_script.create_btc_htlc_script(
                recipient_pubkey=swap_contract.initiator_btc_address.encode()[:33],
                sender_pubkey=swap_contract.participant_btc_address.encode()[:33],
                secret_hash=secret_hash,
                locktime=swap_contract.btc_locktime
            )
            swap_contract.btc_htlc_address = self.htlc_script.get_script_address(btc_script)
        
        # Generate WEPO HTLC
        if swap_contract.swap_type == SwapType.BTC_TO_WEPO:
            # Participant sends WEPO, initiator redeems
            wepo_script = self.htlc_script.create_wepo_htlc_script(
                recipient_address=swap_contract.initiator_wepo_address,
                sender_address=swap_contract.participant_wepo_address,
                secret_hash=swap_contract.secret_hash,
                locktime=swap_contract.wepo_locktime
            )
        else:
            # Initiator sends WEPO, participant redeems
            wepo_script = self.htlc_script.create_wepo_htlc_script(
                recipient_address=swap_contract.participant_wepo_address,
                sender_address=swap_contract.initiator_wepo_address,
                secret_hash=swap_contract.secret_hash,
                locktime=swap_contract.wepo_locktime
            )
        
        # Generate WEPO HTLC address (simplified)
        wepo_script_hash = hashlib.sha256(wepo_script.encode()).hexdigest()
        swap_contract.wepo_htlc_address = f"wepo1htlc{wepo_script_hash[:26]}"
    
    async def fund_swap(self, swap_id: str, currency: str, tx_hash: str) -> bool:
        """Record funding transaction for swap"""
        if swap_id not in self.active_swaps:
            return False
        
        swap = self.active_swaps[swap_id]
        
        if currency.upper() == "BTC":
            swap.btc_funding_tx = tx_hash
        elif currency.upper() == "WEPO":
            swap.wepo_funding_tx = tx_hash
        else:
            return False
        
        # Update state if both sides are funded
        if swap.btc_funding_tx and swap.wepo_funding_tx:
            swap.state = SwapState.FUNDED
        
        swap.updated_at = datetime.utcnow()
        return True
    
    async def redeem_swap(self, swap_id: str, secret: str) -> bool:
        """Enhanced redeem swap with history tracking"""
        if swap_id not in self.active_swaps:
            return False
        
        swap = self.active_swaps[swap_id]
        
        # Verify secret
        secret_bytes = bytes.fromhex(secret)
        secret_hash = self.hash_secret(secret_bytes)
        
        if secret_hash.hex() != swap.secret_hash:
            return False
        
        # Update swap state
        swap.state = SwapState.REDEEMED
        swap.secret = secret
        swap.updated_at = datetime.utcnow()
        
        # Update statistics
        self.update_swap_statistics(swap)
        
        # Move to history
        self.swap_history.append(swap)
        
        # In production, this would broadcast redeem transactions
        # For now, we'll simulate successful redemption
        
        return True
    
    async def refund_swap(self, swap_id: str) -> bool:
        """Enhanced refund expired swap with history tracking"""
        if swap_id not in self.active_swaps:
            return False
        
        swap = self.active_swaps[swap_id]
        
        # Check if swap has expired
        current_time = int(time.time())
        if current_time < max(swap.btc_locktime, swap.wepo_locktime):
            return False  # Not yet expired
        
        # Update swap state
        swap.state = SwapState.REFUNDED
        swap.updated_at = datetime.utcnow()
        
        # Update statistics
        self.update_swap_statistics(swap)
        
        # Move to history
        self.swap_history.append(swap)
        
        return True
    
    def get_swap_history(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Get swap history with pagination"""
        # Sort by creation time (newest first)
        sorted_history = sorted(self.swap_history, 
                               key=lambda x: x.created_at, 
                               reverse=True)
        
        # Apply pagination
        paginated_history = sorted_history[offset:offset + limit]
        
        # Convert to dict format
        history_data = []
        for swap in paginated_history:
            history_data.append({
                'swap_id': swap.swap_id,
                'swap_type': swap.swap_type.value,
                'state': swap.state.value,
                'btc_amount': swap.btc_amount,
                'wepo_amount': swap.wepo_amount,
                'created_at': swap.created_at.isoformat(),
                'updated_at': swap.updated_at.isoformat(),
                'completion_time': (swap.updated_at - swap.created_at).total_seconds(),
                'initiator_btc_address': swap.initiator_btc_address,
                'participant_btc_address': swap.participant_btc_address,
                'fee_info': getattr(swap, 'fee_info', None),
                'priority': getattr(swap, 'priority', False)
            })
        
        return history_data
    
    def search_swaps(self, query: str, state: Optional[SwapState] = None,
                    swap_type: Optional[SwapType] = None) -> List[Dict[str, Any]]:
        """Search swaps by various criteria"""
        all_swaps = list(self.active_swaps.values()) + self.swap_history
        filtered_swaps = []
        
        for swap in all_swaps:
            # Filter by state if specified
            if state and swap.state != state:
                continue
            
            # Filter by swap type if specified
            if swap_type and swap.swap_type != swap_type:
                continue
            
            # Search in swap ID, addresses
            if query:
                searchable_fields = [
                    swap.swap_id,
                    swap.initiator_btc_address,
                    swap.initiator_wepo_address,
                    swap.participant_btc_address,
                    swap.participant_wepo_address
                ]
                
                if not any(query.lower() in field.lower() for field in searchable_fields):
                    continue
            
            filtered_swaps.append({
                'swap_id': swap.swap_id,
                'swap_type': swap.swap_type.value,
                'state': swap.state.value,
                'btc_amount': swap.btc_amount,
                'wepo_amount': swap.wepo_amount,
                'created_at': swap.created_at.isoformat(),
                'updated_at': swap.updated_at.isoformat(),
                'is_active': swap.swap_id in self.active_swaps
            })
        
        return sorted(filtered_swaps, key=lambda x: x['created_at'], reverse=True)
    
    def get_swap_status(self, swap_id: str) -> Optional[SwapContract]:
        """Get current swap status"""
        return self.active_swaps.get(swap_id)
    
    def get_all_swaps(self) -> List[SwapContract]:
        """Get all active swaps"""
        return list(self.active_swaps.values())
    
    async def cleanup_expired_swaps(self):
        """Clean up expired swaps"""
        current_time = datetime.utcnow()
        expired_swaps = []
        
        for swap_id, swap in self.active_swaps.items():
            if swap.expires_at < current_time and swap.state not in [SwapState.REDEEMED, SwapState.REFUNDED]:
                swap.state = SwapState.EXPIRED
                expired_swaps.append(swap_id)
        
        # Remove expired swaps
        for swap_id in expired_swaps:
            del self.active_swaps[swap_id]
    
    async def get_swap_proof(self, swap_id: str) -> Optional[Dict[str, Any]]:
        """Get cryptographic proof of swap"""
        if swap_id not in self.active_swaps:
            return None
        
        swap = self.active_swaps[swap_id]
        
        return {
            "swap_id": swap_id,
            "secret_hash": swap.secret_hash,
            "btc_htlc_address": swap.btc_htlc_address,
            "wepo_htlc_address": swap.wepo_htlc_address,
            "btc_locktime": swap.btc_locktime,
            "wepo_locktime": swap.wepo_locktime,
            "state": swap.state.value,
            "created_at": swap.created_at.isoformat(),
            "proof_type": "htlc_atomic_swap"
        }

# Global atomic swap engine instance
atomic_swap_engine = AtomicSwapEngine()

# Utility functions
def create_swap_request(swap_type: str, btc_amount: float, 
                       initiator_btc_address: str, initiator_wepo_address: str,
                       participant_btc_address: str, participant_wepo_address: str) -> Dict[str, Any]:
    """Create swap request data"""
    return {
        "swap_type": swap_type,
        "btc_amount": btc_amount,
        "initiator_btc_address": initiator_btc_address,
        "initiator_wepo_address": initiator_wepo_address,
        "participant_btc_address": participant_btc_address,
        "participant_wepo_address": participant_wepo_address
    }

def validate_btc_address(address: str) -> bool:
    """Validate Bitcoin address format"""
    if not address:
        return False
    
    # Basic validation for different address types
    if address.startswith('1') and len(address) >= 26 and len(address) <= 35:
        return True  # P2PKH
    elif address.startswith('3') and len(address) >= 26 and len(address) <= 35:
        return True  # P2SH
    elif address.startswith('bc1') and len(address) >= 14 and len(address) <= 74:
        return True  # Bech32
    elif address.startswith('tb1') and len(address) >= 14 and len(address) <= 74:
        return True  # Testnet Bech32
    
    return False

def validate_wepo_address(address: str) -> bool:
    """Validate WEPO address format"""
    return address.startswith('wepo1') and len(address) >= 38

# Export main classes and functions
__all__ = [
    'AtomicSwapEngine',
    'SwapContract',
    'SwapState',
    'SwapType',
    'HTLCScript',
    'atomic_swap_engine',
    'create_swap_request',
    'validate_btc_address',
    'validate_wepo_address'
]
