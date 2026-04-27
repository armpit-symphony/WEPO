#!/usr/bin/env python3
"""
WEPO RWA Token System
Real World Asset tokenization with quantum-resistant security
"""

import hashlib
import time
import base64
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

@dataclass
class RWAAsset:
    """Real World Asset information"""
    asset_id: str
    name: str
    description: str
    asset_type: str  # 'document', 'image', 'property', 'vehicle', 'artwork', 'other'
    owner_address: str
    creator_address: str
    creation_timestamp: int
    
    # File data (base64 encoded) - defaults
    file_data: Optional[str] = None
    file_name: Optional[str] = None
    file_size: int = 0
    file_type: Optional[str] = None  # MIME type
    
    # Asset metadata - defaults
    metadata: Optional[Dict] = None
    valuation: Optional[float] = None  # In USD
    verification_status: str = "pending"  # pending, verified, rejected
    
    # Tokenization info - defaults
    token_symbol: str = ""
    total_supply: int = 1000000000000  # 10,000 tokens with 8 decimal places
    divisible: bool = True
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if not self.token_symbol:
            self.token_symbol = f"RWA{self.asset_id[:8].upper()}"

@dataclass
class RWAToken:
    """RWA Token on blockchain"""
    token_id: str
    asset_id: str
    symbol: str
    name: str
    total_supply: int
    creator_address: str
    creation_block: int
    creation_timestamp: int
    
    # Defaults
    decimals: int = 8
    current_supply: int = 0
    holders: Optional[Dict[str, int]] = None  # address -> balance
    is_tradeable: bool = True
    last_price: Optional[float] = None  # Last traded price in WEPO
    market_cap: Optional[float] = None
    
    def __post_init__(self):
        if self.holders is None:
            self.holders = {}

@dataclass
class RWATransaction:
    """RWA Token transaction"""
    tx_id: str
    token_id: str
    from_address: str
    to_address: str
    amount: int  # Token amount in smallest units
    tx_type: str  # 'mint', 'transfer', 'burn', 'trade'
    
    # Defaults
    wepo_amount: Optional[int] = None  # For trades, WEPO amount
    timestamp: int = 0
    block_height: int = 0
    
    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = int(time.time())

@dataclass
class FeeRedistributionPool:
    """Pool for collecting and redistributing RWA fees"""
    total_collected: float = 0.0
    last_distribution: int = 0  # Block height of last distribution
    distribution_history: List = None
    
    def __post_init__(self):
        if self.distribution_history is None:
            self.distribution_history = []

class RWATokenSystem:
    """RWA Token management system"""
    
    def __init__(self):
        self.assets: Dict[str, RWAAsset] = {}
        self.tokens: Dict[str, RWAToken] = {}
        self.transactions: List[RWATransaction] = []
        self.fee_redistribution_pool = FeeRedistributionPool()
        self.supported_file_types = {
            'image/jpeg', 'image/png', 'image/gif', 'image/bmp',
            'application/pdf', 'application/msword', 
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'text/plain', 'text/csv'
        }
    
    def validate_file_upload(self, file_data: str, file_type: str, file_name: str) -> bool:
        """Validate file upload"""
        try:
            # Check file type
            if file_type not in self.supported_file_types:
                return False
            
            # Validate base64 encoding
            base64.b64decode(file_data)
            
            # Check file size (max 10MB when decoded)
            file_size = len(base64.b64decode(file_data))
            if file_size > 10 * 1024 * 1024:  # 10MB limit
                return False
            
            return True
            
        except Exception:
            return False
    
    def create_rwa_asset(self, name: str, description: str, asset_type: str, 
                        owner_address: str, file_data: str = None, 
                        file_name: str = None, file_type: str = None,
                        metadata: Dict = None, valuation: float = None,
                        blockchain=None) -> str:
        """Create a new RWA asset with WEPO balance check and fee deduction"""
        
        # Validate file if provided
        if file_data and not self.validate_file_upload(file_data, file_type, file_name):
            raise ValueError("Invalid file upload")
        
        # Check WEPO balance requirement (if blockchain is provided)
        if blockchain:
            user_balance = blockchain.get_balance(owner_address)
            rwa_creation_fee = 0.0002  # Double normal transaction fee
            
            if user_balance < rwa_creation_fee:
                raise ValueError(f"Insufficient WEPO balance. RWA creation requires {rwa_creation_fee} WEPO (current balance: {user_balance} WEPO)")
            
            # Create transaction that will be distributed via 3-way fee system
            try:
                # Create transaction - fees will be automatically distributed by blockchain
                blockchain.create_transaction(owner_address, "wepo1feecollection00000000000000000000", rwa_creation_fee)
                
                # Note: Fee distribution (60% MN, 25% Miners, 15% Stakers) happens automatically in coinbase
                print(f"RWA creation fee of {rwa_creation_fee} WEPO will be distributed via 3-way system")
                
                # Mine the fee transaction immediately in test mode
                if hasattr(blockchain, 'mine_block'):
                    blockchain.mine_block()
                    
            except Exception as e:
                raise ValueError(f"Failed to process RWA creation fee: {str(e)}")
        
        # Generate unique asset ID
        asset_id = hashlib.sha256(
            f"{name}{description}{owner_address}{time.time()}".encode()
        ).hexdigest()[:16]
        
        # Calculate file size
        file_size = len(base64.b64decode(file_data)) if file_data else 0
        
        # Create asset
        asset = RWAAsset(
            asset_id=asset_id,
            name=name,
            description=description,
            asset_type=asset_type,
            owner_address=owner_address,
            creator_address=owner_address,
            creation_timestamp=int(time.time()),
            file_data=file_data,
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
            metadata=metadata or {},
            valuation=valuation
        )
        
        self.assets[asset_id] = asset
        return asset_id
    
    def tokenize_asset(self, asset_id: str, token_name: str = None, 
                      token_symbol: str = None, total_supply: int = None,
                      block_height: int = 0) -> str:
        """Tokenize an RWA asset"""
        
        if asset_id not in self.assets:
            raise ValueError(f"Asset {asset_id} not found")
        
        asset = self.assets[asset_id]
        
        # Generate token ID
        token_id = hashlib.sha256(
            f"token_{asset_id}_{time.time()}".encode()
        ).hexdigest()[:16]
        
        # Create token
        token = RWAToken(
            token_id=token_id,
            asset_id=asset_id,
            symbol=token_symbol or asset.token_symbol,
            name=token_name or f"{asset.name} Token",
            total_supply=total_supply or asset.total_supply,
            creator_address=asset.creator_address,
            creation_block=block_height,
            creation_timestamp=int(time.time())
        )
        
        # Initial mint to creator
        token.current_supply = token.total_supply
        token.holders[asset.creator_address] = token.total_supply
        
        self.tokens[token_id] = token
        
        # Create mint transaction
        mint_tx = RWATransaction(
            tx_id=f"mint_{token_id}_{time.time()}",
            token_id=token_id,
            from_address="system",
            to_address=asset.creator_address,
            amount=token.total_supply,
            tx_type="mint",
            timestamp=int(time.time()),
            block_height=block_height
        )
        
        self.transactions.append(mint_tx)
        
        return token_id
    
    def transfer_tokens(self, token_id: str, from_address: str, to_address: str, 
                       amount: int, block_height: int = 0) -> str:
        """Transfer RWA tokens"""
        
        if token_id not in self.tokens:
            raise ValueError(f"Token {token_id} not found")
        
        token = self.tokens[token_id]
        
        # Check balance
        if from_address not in token.holders or token.holders[from_address] < amount:
            raise ValueError("Insufficient token balance")
        
        # Validate addresses
        if not self.is_valid_address(from_address) or not self.is_valid_address(to_address):
            raise ValueError("Invalid address format")
        
        # Generate transaction ID
        tx_id = hashlib.sha256(
            f"transfer_{token_id}_{from_address}_{to_address}_{amount}_{time.time()}".encode()
        ).hexdigest()[:16]
        
        # Update balances
        token.holders[from_address] -= amount
        if from_address in token.holders and token.holders[from_address] == 0:
            del token.holders[from_address]
        
        token.holders[to_address] = token.holders.get(to_address, 0) + amount
        
        # Create transfer transaction
        transfer_tx = RWATransaction(
            tx_id=tx_id,
            token_id=token_id,
            from_address=from_address,
            to_address=to_address,
            amount=amount,
            tx_type="transfer",
            timestamp=int(time.time()),
            block_height=block_height
        )
        
        self.transactions.append(transfer_tx)
        
        return tx_id
    
    def trade_tokens_for_wepo(self, token_id: str, seller_address: str, 
                             buyer_address: str, token_amount: int, 
                             wepo_amount: int, block_height: int = 0) -> str:
        """Trade RWA tokens for WEPO"""
        
        if token_id not in self.tokens:
            raise ValueError(f"Token {token_id} not found")
        
        token = self.tokens[token_id]
        
        # Check token balance
        if seller_address not in token.holders or token.holders[seller_address] < token_amount:
            raise ValueError("Insufficient token balance")
        
        # Generate transaction ID
        tx_id = hashlib.sha256(
            f"trade_{token_id}_{seller_address}_{buyer_address}_{token_amount}_{wepo_amount}_{time.time()}".encode()
        ).hexdigest()[:16]
        
        # Update token balances
        token.holders[seller_address] -= token_amount
        if seller_address in token.holders and token.holders[seller_address] == 0:
            del token.holders[seller_address]
        
        token.holders[buyer_address] = token.holders.get(buyer_address, 0) + token_amount
        
        # Update last price
        token.last_price = wepo_amount / token_amount * (10 ** token.decimals)  # Price per token
        
        # Create trade transaction
        trade_tx = RWATransaction(
            tx_id=tx_id,
            token_id=token_id,
            from_address=seller_address,
            to_address=buyer_address,
            amount=token_amount,
            wepo_amount=wepo_amount,
            tx_type="trade",
            timestamp=int(time.time()),
            block_height=block_height
        )
        
        self.transactions.append(trade_tx)
        
        return tx_id
    
    def get_asset_info(self, asset_id: str) -> Optional[Dict]:
        """Get asset information"""
        if asset_id not in self.assets:
            return None
        
        asset = self.assets[asset_id]
        
        # Don't return file data in info (too large)
        asset_info = asdict(asset)
        asset_info['file_data'] = None  # Remove file data for info response
        asset_info['has_file'] = bool(asset.file_data)
        
        return asset_info
    
    def get_token_info(self, token_id: str) -> Optional[Dict]:
        """Get token information"""
        if token_id not in self.tokens:
            return None
        
        token = self.tokens[token_id]
        token_info = asdict(token)
        
        # Add calculated fields
        token_info['holder_count'] = len(token.holders)
        token_info['circulating_supply'] = token.current_supply
        
        return token_info
    
    def get_user_rwa_portfolio(self, address: str) -> Dict:
        """Get user's RWA portfolio"""
        portfolio = {
            'assets_created': [],
            'assets_owned': [],
            'tokens_held': [],
            'total_value_wepo': 0
        }
        
        # Assets created
        for asset_id, asset in self.assets.items():
            if asset.creator_address == address:
                portfolio['assets_created'].append(self.get_asset_info(asset_id))
        
        # Assets owned (different from created)
        for asset_id, asset in self.assets.items():
            if asset.owner_address == address and asset.creator_address != address:
                portfolio['assets_owned'].append(self.get_asset_info(asset_id))
        
        # Tokens held
        for token_id, token in self.tokens.items():
            if address in token.holders and token.holders[address] > 0:
                token_info = self.get_token_info(token_id)
                token_info['balance'] = token.holders[address]
                token_info['balance_formatted'] = token.holders[address] / (10 ** token.decimals)
                
                # Calculate value
                if token.last_price:
                    value = token.holders[address] * token.last_price / (10 ** token.decimals)
                    token_info['value_wepo'] = value
                    portfolio['total_value_wepo'] += value
                
                portfolio['tokens_held'].append(token_info)
        
        return portfolio
    
    def get_tradeable_tokens(self) -> List[Dict]:
        """Get all tradeable tokens"""
        tradeable = []
        
        for token_id, token in self.tokens.items():
            if token.is_tradeable:
                token_info = self.get_token_info(token_id)
                
                # Add asset info
                if token.asset_id in self.assets:
                    asset = self.assets[token.asset_id]
                    token_info['asset_name'] = asset.name
                    token_info['asset_type'] = asset.asset_type
                    token_info['asset_description'] = asset.description
                
                tradeable.append(token_info)
        
        return tradeable
    
    def get_rwa_statistics(self) -> Dict:
        """Get RWA system statistics"""
        total_assets = len(self.assets)
        total_tokens = len(self.tokens)
        total_transactions = len(self.transactions)
        
        # Calculate total value
        total_value = 0
        for asset in self.assets.values():
            if asset.valuation:
                total_value += asset.valuation
        
        # Asset type distribution
        asset_types = {}
        for asset in self.assets.values():
            asset_types[asset.asset_type] = asset_types.get(asset.asset_type, 0) + 1
        
        # Token holders
        total_holders = set()
        for token in self.tokens.values():
            total_holders.update(token.holders.keys())
        
        return {
            'total_assets': total_assets,
            'total_tokens': total_tokens,
            'total_transactions': total_transactions,
            'total_asset_value_usd': total_value,
            'total_holders': len(total_holders),
            'asset_types': asset_types,
            'tokens_by_type': {
                'tradeable': sum(1 for t in self.tokens.values() if t.is_tradeable),
                'non_tradeable': sum(1 for t in self.tokens.values() if not t.is_tradeable)
            }
        }
    
    def get_rwa_creation_fee_info(self) -> Dict:
        """Get RWA creation fee information with new 3-way distribution"""
        return {
            'rwa_creation_fee': 0.0002,  # Double normal transaction fee
            'normal_transaction_fee': 0.0001,
            'fee_multiplier': 2,
            'currency': 'WEPO',
            'description': 'RWA token creation fee (2x normal transaction fee)',
            'redistribution_info': {
                'masternodes': 'Receive 60% of all network fees (split equally among active nodes)',
                'miners': 'Receive 25% of all network fees (goes to current block miner)',
                'stakers': 'Receive 15% of all network fees (proportional to stake amount)',
                'policy': 'No fees are burned - all fees support network participants',
                'distribution_method': 'Real-time per-block distribution'
            },
            'fee_distribution_weights': {
                'masternode_share': 60,
                'miner_share': 25, 
                'staker_share': 15
            }
        }
    
    def add_fee_to_redistribution_pool(self, amount: float, block_height: int, fee_type: str = "transaction"):
        """Legacy fee telemetry hook kept for backward compatibility."""
        self.fee_redistribution_pool.total_collected += amount
        print(
            f"Recorded legacy fee telemetry: {amount} WEPO {fee_type}. "
            f"Total tracked: {self.fee_redistribution_pool.total_collected}"
        )
    
    def add_transaction_fees_to_pool(self, total_fees_satoshis: int, block_height: int):
        """Legacy transaction-fee telemetry hook kept for backward compatibility."""
        if total_fees_satoshis > 0:
            fee_amount_wepo = total_fees_satoshis / 100000000  # Convert from satoshis
            self.add_fee_to_redistribution_pool(fee_amount_wepo, block_height, "transaction")
    
    def get_redistribution_pool_info(self) -> Dict:
        """Get legacy fee telemetry information."""
        return {
            'total_collected': self.fee_redistribution_pool.total_collected,
            'last_distribution_block': self.fee_redistribution_pool.last_distribution,
            'pending_for_distribution': 0,
            'distribution_history': self.fee_redistribution_pool.distribution_history,
            'distribution_policy': {
                'canonical_fee_path': 'Blockchain coinbase outputs settle canonical fee redistribution',
                'telemetry_scope': 'Legacy RWA/accounting tracking only',
                'distribution_frequency': 'Not used for canonical settlement',
                'fee_types_included': [
                    'Legacy RWA/application fee telemetry'
                ]
            },
            'fee_redistribution_philosophy': 'Canonical fee redistribution lives in the blockchain consensus path'
        }

    def distribute_fees_to_miners(self, miner_address: str, block_height: int) -> float:
        """Legacy helper retained for compatibility; not used by canonical settlement."""
        if self.fee_redistribution_pool.total_collected > 0:
            # For demo, distribute all collected fees to the miner
            amount_to_distribute = self.fee_redistribution_pool.total_collected
            self.fee_redistribution_pool.total_collected = 0
            self.fee_redistribution_pool.last_distribution = block_height
            
            # Record distribution
            distribution_record = {
                'block_height': block_height,
                'recipient': miner_address,
                'amount': amount_to_distribute,
                'type': 'miner_reward',
                'timestamp': int(time.time())
            }
            self.fee_redistribution_pool.distribution_history.append(distribution_record)
            
            print(f"Distributed {amount_to_distribute} WEPO to miner {miner_address} at block {block_height}")
            return amount_to_distribute
        return 0.0
    
    def distribute_fees_to_masternodes(self, masternode_addresses: List[str], block_height: int) -> Dict:
        """Legacy helper retained for compatibility; not used by canonical settlement."""
        if self.fee_redistribution_pool.total_collected > 0 and masternode_addresses:
            # Distribute equally among masternodes
            total_amount = self.fee_redistribution_pool.total_collected
            amount_per_node = total_amount / len(masternode_addresses)
            
            self.fee_redistribution_pool.total_collected = 0
            self.fee_redistribution_pool.last_distribution = block_height
            
            distributions = {}
            for address in masternode_addresses:
                distributions[address] = amount_per_node
                
                # Record distribution
                distribution_record = {
                    'block_height': block_height,
                    'recipient': address,
                    'amount': amount_per_node,
                    'type': 'masternode_reward',
                    'timestamp': int(time.time())
                }
                self.fee_redistribution_pool.distribution_history.append(distribution_record)
            
            print(f"Distributed {total_amount} WEPO to {len(masternode_addresses)} masternodes at block {block_height}")
            return distributions
        return {}
    
    def is_valid_address(self, address: str) -> bool:
        """Validate WEPO address format"""
        if not address or not isinstance(address, str):
            return False
        
        # Support both regular and quantum addresses
        if address.startswith("wepo1"):
            return len(address) in [37, 45]  # Regular or quantum
        
        return False
    
    def get_asset_file(self, asset_id: str) -> Optional[Dict]:
        """Get asset file data"""
        if asset_id not in self.assets:
            return None
        
        asset = self.assets[asset_id]
        
        if not asset.file_data:
            return None
        
        return {
            'file_data': asset.file_data,
            'file_name': asset.file_name,
            'file_type': asset.file_type,
            'file_size': asset.file_size
        }

# Global RWA system instance
rwa_system = RWATokenSystem()
