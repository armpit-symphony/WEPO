#!/usr/bin/env python3
"""
WEPO Quantum-Resistant Blockchain Implementation
Integrates Dilithium signatures with existing blockchain architecture
"""

import os
import sys
import hashlib
import json
import sqlite3
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

# Import existing blockchain components
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from blockchain import (
    GENESIS_TIME, COIN, REWARD_Q1,
    BlockHeader, Block, WepoArgon2Miner,
    StakeInfo, MasternodeInfo
)

# Import quantum transaction system
from quantum_transaction import (
    QuantumTransaction, QuantumTransactionInput, QuantumTransactionOutput,
    QuantumWallet
)

# Import Dilithium cryptography
from dilithium import (
    generate_dilithium_keypair, generate_wepo_address,
    get_dilithium_info
)

@dataclass
class QuantumBlock:
    """Quantum-resistant WEPO block with Dilithium signatures"""
    header: BlockHeader
    transactions: List[QuantumTransaction]
    height: int = 0
    size: int = 0
    
    def __post_init__(self):
        if self.size == 0:
            self.size = self.calculate_size()
    
    def calculate_size(self) -> int:
        """Calculate block size in bytes"""
        total_size = 200  # Block header overhead
        for tx in self.transactions:
            total_size += tx.get_size()
        return total_size
    
    def calculate_merkle_root(self) -> str:
        """Calculate Merkle root of quantum transactions"""
        if not self.transactions:
            return "0" * 64
        
        txids = [tx.calculate_txid() for tx in self.transactions]
        
        while len(txids) > 1:
            next_level = []
            for i in range(0, len(txids), 2):
                left = txids[i]
                right = txids[i + 1] if i + 1 < len(txids) else left
                combined = left + right
                next_level.append(hashlib.blake2b(combined.encode(), digest_size=32).hexdigest())
            txids = next_level
        
        return txids[0]
    
    def get_block_hash(self) -> str:
        """Get block hash using quantum-resistant hashing"""
        header_data = f"{self.header.version}{self.header.prev_hash}{self.header.merkle_root}{self.header.timestamp}{self.header.bits}{self.header.nonce}{self.header.consensus_type}"
        return hashlib.blake2b(header_data.encode(), digest_size=32).hexdigest()

class QuantumWepoBlockchain:
    """Quantum-resistant WEPO blockchain using Dilithium signatures"""
    
    def __init__(self, data_dir: str = "/tmp/wepo_quantum"):
        self.data_dir = data_dir
        self.db_path = os.path.join(data_dir, "quantum_blockchain.db")
        self.chain: List[QuantumBlock] = []
        self.mempool: Dict[str, QuantumTransaction] = {}
        self.utxo_set: Dict[str, Dict] = {}  # txid:vout -> utxo_info
        self.stakes: Dict[str, StakeInfo] = {}
        self.masternodes: Dict[str, MasternodeInfo] = {}
        self.current_difficulty = 4
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
        """Initialize quantum-resistant database schema"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        
        # Blocks table
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS quantum_blocks (
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
        
        # Quantum transactions table
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS quantum_transactions (
                txid TEXT PRIMARY KEY,
                block_height INTEGER,
                block_hash TEXT,
                version INTEGER NOT NULL,
                lock_time INTEGER NOT NULL,
                fee INTEGER NOT NULL,
                privacy_proof BLOB,
                ring_signature BLOB,
                timestamp INTEGER NOT NULL,
                tx_data TEXT NOT NULL,
                FOREIGN KEY(block_height) REFERENCES quantum_blocks(height)
            )
        ''')
        
        # Quantum UTXOs table
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS quantum_utxos (
                txid TEXT NOT NULL,
                vout INTEGER NOT NULL,
                address TEXT NOT NULL,
                amount INTEGER NOT NULL,
                public_key_hash BLOB,
                spent BOOLEAN DEFAULT FALSE,
                spent_txid TEXT,
                spent_height INTEGER,
                PRIMARY KEY(txid, vout)
            )
        ''')
        
        # Quantum addresses table (for Dilithium key management)
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS quantum_addresses (
                address TEXT PRIMARY KEY,
                public_key BLOB NOT NULL,
                algorithm TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        ''')
        
        self.conn.commit()
    
    def create_genesis_block(self):
        """Create quantum-resistant genesis block"""
        print("Creating WEPO Quantum Genesis Block...")
        genesis_difficulty = 1
        
        # Generate genesis keypair
        genesis_keypair = generate_dilithium_keypair()
        genesis_address = generate_wepo_address(genesis_keypair.public_key)
        
        # Create genesis coinbase transaction
        genesis_tx = QuantumTransaction(
            version=1,
            inputs=[QuantumTransactionInput(
                prev_txid="0" * 64,
                prev_vout=0xffffffff,
                signature=b"WEPO Quantum Genesis".ljust(2420, b'\x00'),  # Padded to signature size
                public_key=genesis_keypair.public_key,
                sequence=0xffffffff
            )],
            outputs=[QuantumTransactionOutput(
                value=REWARD_Q1,
                recipient_address=genesis_address,
                public_key_hash=hashlib.blake2b(genesis_keypair.public_key, digest_size=20).digest()
            )],
            lock_time=0,
            timestamp=GENESIS_TIME
        )
        
        # Store genesis address
        self.conn.execute('''
            INSERT INTO quantum_addresses (address, public_key, algorithm, created_at)
            VALUES (?, ?, ?, ?)
        ''', (genesis_address, genesis_keypair.public_key, 'Dilithium2', GENESIS_TIME))
        
        # Genesis block header
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
        genesis_block = QuantumBlock(
            header=genesis_header,
            transactions=[genesis_tx],
            height=0
        )
        
        # Calculate merkle root
        genesis_block.header.merkle_root = genesis_block.calculate_merkle_root()
        
        # Mine genesis block
        print("Mining quantum genesis block...")
        mined_genesis = self.mine_block(genesis_block, difficulty=genesis_difficulty)
        
        if mined_genesis:
            self.add_block(mined_genesis, validate=False)
            print(f"✓ Quantum genesis block created: {mined_genesis.get_block_hash()}")
            print(f"✓ Genesis address: {genesis_address}")
            print(f"✓ Genesis reward: {REWARD_Q1 / COIN} WEPO")
        else:
            raise Exception("Failed to mine quantum genesis block")
    
    def mine_block(self, block: QuantumBlock, difficulty: Optional[int] = None) -> Optional[QuantumBlock]:
        """Mine a quantum block using Argon2 PoW"""
        print(f"Mining quantum block {block.height}...")
        target_difficulty = difficulty if difficulty is not None else self.current_difficulty
        
        # Convert to legacy block for mining
        legacy_block = Block(
            header=block.header,
            transactions=[],  # Empty for mining
            height=block.height,
            size=block.size
        )
        
        # Mine the block
        mined_legacy = self.miner.mine_block(legacy_block, target_difficulty)
        
        if mined_legacy:
            # Update quantum block with mined nonce
            block.header.nonce = mined_legacy.header.nonce
            return block
        
        return None
    
    def add_block(self, block: QuantumBlock, validate: bool = True) -> bool:
        """Add quantum block to blockchain"""
        if validate and not self.validate_block(block):
            return False
        
        try:
            # Add to chain
            self.chain.append(block)
            
            # Process transactions and update UTXOs
            for tx in block.transactions:
                txid = tx.calculate_txid()
                
                # Mark input UTXOs as spent (except coinbase)
                if not tx.is_coinbase():
                    for inp in tx.inputs:
                        self.conn.execute('''
                            UPDATE quantum_utxos 
                            SET spent = TRUE, spent_txid = ?, spent_height = ?
                            WHERE txid = ? AND vout = ?
                        ''', (txid, block.height, inp.prev_txid, inp.prev_vout))
                
                # Create new UTXOs from outputs
                for vout, output in enumerate(tx.outputs):
                    self.conn.execute('''
                        INSERT INTO quantum_utxos (txid, vout, address, amount, public_key_hash, spent)
                        VALUES (?, ?, ?, ?, ?, FALSE)
                    ''', (txid, vout, output.recipient_address, output.value, output.public_key_hash))
            
            # Save block to database
            self.conn.execute('''
                INSERT INTO quantum_blocks (
                    height, hash, prev_hash, merkle_root, timestamp, bits, nonce,
                    version, size, tx_count, consensus_type, block_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(self.serialize_block(block))
            ))
            
            # Save quantum transactions
            for tx in block.transactions:
                txid = tx.calculate_txid()
                self.conn.execute('''
                    INSERT INTO quantum_transactions (
                        txid, block_height, block_hash, version, lock_time, fee,
                        privacy_proof, ring_signature, timestamp, tx_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    txid,
                    block.height,
                    block.get_block_hash(),
                    tx.version,
                    tx.lock_time,
                    tx.fee,
                    tx.privacy_proof,
                    tx.ring_signature,
                    tx.timestamp,
                    json.dumps(tx.to_dict())
                ))
            
            self.conn.commit()
            
            print(f"✓ Quantum block {block.height} added: {block.get_block_hash()}")
            return True
            
        except Exception as e:
            print(f"Error adding quantum block: {e}")
            self.conn.rollback()
            return False
    
    def validate_block(self, block: QuantumBlock) -> bool:
        """Validate quantum block"""
        try:
            # Basic validation
            if block.height != self.get_block_height() + 1:
                print(f"Invalid block height: {block.height}")
                return False
            
            # Validate all transactions
            for tx in block.transactions:
                if not tx.is_coinbase() and not tx.verify_all_inputs():
                    print(f"Invalid transaction signature: {tx.calculate_txid()}")
                    return False
            
            # Validate merkle root
            calculated_merkle = block.calculate_merkle_root()
            if block.header.merkle_root != calculated_merkle:
                print(f"Invalid merkle root")
                return False
            
            print(f"✓ Quantum block {block.height} validation passed")
            return True
            
        except Exception as e:
            print(f"Block validation error: {e}")
            return False
    
    def serialize_block(self, block: QuantumBlock) -> dict:
        """Serialize quantum block to dictionary"""
        return {
            'header': asdict(block.header),
            'transactions': [tx.to_dict() for tx in block.transactions],
            'height': block.height,
            'size': block.size
        }
    
    def get_block_height(self) -> int:
        """Get current block height"""
        return len(self.chain) - 1 if self.chain else -1
    
    def get_balance(self, address: str) -> int:
        """Get balance for quantum address"""
        cursor = self.conn.execute('''
            SELECT SUM(amount) FROM quantum_utxos 
            WHERE address = ? AND spent = FALSE
        ''', (address,))
        
        result = cursor.fetchone()
        return result[0] if result[0] else 0
    
    def get_balance_wepo(self, address: str) -> float:
        """Get balance in WEPO units"""
        return self.get_balance(address) / COIN
    
    def add_transaction_to_mempool(self, transaction: QuantumTransaction) -> bool:
        """Add quantum transaction to mempool"""
        txid = transaction.calculate_txid()
        
        # Validate transaction
        if self.validate_transaction(transaction):
            self.mempool[txid] = transaction
            print(f"✓ Quantum transaction added to mempool: {txid[:16]}...")
            return True
        else:
            print(f"✗ Invalid quantum transaction rejected: {txid[:16]}...")
            return False
    
    def validate_transaction(self, transaction: QuantumTransaction) -> bool:
        """Validate quantum transaction"""
        try:
            # Skip validation for coinbase
            if transaction.is_coinbase():
                return True
            
            # Verify all input signatures
            if not transaction.verify_all_inputs():
                print("Transaction signature verification failed")
                return False
            
            # Check UTXO availability
            total_input_value = 0
            for inp in transaction.inputs:
                cursor = self.conn.execute('''
                    SELECT amount, spent FROM quantum_utxos 
                    WHERE txid = ? AND vout = ?
                ''', (inp.prev_txid, inp.prev_vout))
                
                utxo = cursor.fetchone()
                if not utxo:
                    print(f"UTXO not found: {inp.prev_txid}:{inp.prev_vout}")
                    return False
                
                if utxo[1]:  # spent flag
                    print(f"UTXO already spent: {inp.prev_txid}:{inp.prev_vout}")
                    return False
                
                total_input_value += utxo[0]
            
            # Check sufficient funds
            total_output_value = sum(out.value for out in transaction.outputs)
            if total_input_value < total_output_value + transaction.fee:
                print(f"Insufficient funds: {total_input_value} < {total_output_value + transaction.fee}")
                return False
            
            return True
            
        except Exception as e:
            print(f"Transaction validation error: {e}")
            return False
    
    def load_chain(self):
        """Load quantum blockchain from database"""
        cursor = self.conn.execute('''
            SELECT block_data FROM quantum_blocks ORDER BY height ASC
        ''')
        
        for row in cursor.fetchall():
            block_data = json.loads(row[0])
            block = self.deserialize_block(block_data)
            self.chain.append(block)
        
        print(f"✓ Loaded {len(self.chain)} quantum blocks from database")
    
    def deserialize_block(self, data: dict) -> QuantumBlock:
        """Deserialize quantum block from dictionary"""
        header = BlockHeader(**data['header'])
        
        transactions = []
        for tx_data in data['transactions']:
            tx = QuantumTransaction.from_dict(tx_data)
            transactions.append(tx)
        
        return QuantumBlock(
            header=header,
            transactions=transactions,
            height=data['height'],
            size=data['size']
        )
    
    def get_quantum_info(self) -> dict:
        """Get quantum blockchain information"""
        return {
            'blockchain_type': 'quantum_resistant',
            'signature_algorithm': 'Dilithium2',
            'hash_algorithm': 'BLAKE2b',
            'current_height': self.get_block_height(),
            'total_transactions': len(self.mempool) + sum(len(block.transactions) for block in self.chain),
            'mempool_size': len(self.mempool),
            'dilithium_info': get_dilithium_info(),
            'quantum_ready': True
        }

def test_quantum_blockchain():
    """Test quantum blockchain implementation"""
    print("Testing WEPO Quantum Blockchain...")
    
    # Create quantum blockchain
    blockchain = QuantumWepoBlockchain("/tmp/test_quantum_wepo")
    
    print(f"✓ Genesis block height: {blockchain.get_block_height()}")
    print(f"✓ Genesis block hash: {blockchain.chain[0].get_block_hash()}")
    
    # Create quantum wallet
    wallet = QuantumWallet()
    wallet_info = wallet.generate_new_wallet()
    print(f"✓ Created quantum wallet: {wallet_info['address']}")
    
    # Get blockchain info
    info = blockchain.get_quantum_info()
    print(f"✓ Quantum blockchain info: {info}")
    
    print("🎉 Quantum blockchain test completed!")
    
    return True

if __name__ == "__main__":
    test_quantum_blockchain()
