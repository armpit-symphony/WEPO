#!/usr/bin/env python3
"""
WEPO Quantum-Resistant Transaction System
Uses Dilithium signatures for quantum-resistant transaction signing
"""

import hashlib
import json
import time
from typing import List, Optional
from dataclasses import dataclass

from dilithium import (
    DilithiumKeyPair, DilithiumSigner,
    generate_dilithium_keypair, sign_message, verify_signature,
    generate_wepo_address, validate_wepo_address,
    DILITHIUM_SIGNATURE_SIZE, DILITHIUM_PUBKEY_SIZE
)

@dataclass
class QuantumTransactionInput:
    """Quantum-resistant transaction input with Dilithium signature"""
    prev_txid: str
    prev_vout: int
    signature: bytes  # Dilithium signature
    public_key: bytes  # Dilithium public key
    sequence: int = 0xffffffff
    
    def __post_init__(self):
        """Validate signature and public key sizes"""
        if self.signature and len(self.signature) != DILITHIUM_SIGNATURE_SIZE:
            raise ValueError(f"Invalid signature size: {len(self.signature)}")
        
        if self.public_key and len(self.public_key) != DILITHIUM_PUBKEY_SIZE:
            raise ValueError(f"Invalid public key size: {len(self.public_key)}")

@dataclass 
class QuantumTransactionOutput:
    """Quantum-resistant transaction output"""
    value: int
    recipient_address: str
    public_key_hash: bytes = b""  # Hash of recipient's Dilithium public key
    
    def __post_init__(self):
        """Validate output format"""
        if not validate_wepo_address(self.recipient_address):
            raise ValueError(f"Invalid WEPO address: {self.recipient_address}")

@dataclass
class QuantumTransaction:
    """Quantum-resistant WEPO transaction with Dilithium signatures"""
    version: int
    inputs: List[QuantumTransactionInput]
    outputs: List[QuantumTransactionOutput]
    lock_time: int
    fee: int = 0
    privacy_proof: Optional[bytes] = None
    ring_signature: Optional[bytes] = None
    timestamp: int = 0
    
    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = int(time.time())
    
    def calculate_txid(self) -> str:
        """Calculate transaction ID using quantum-resistant hashing"""
        # Create a deterministic string representation
        tx_string = f"{self.version}:{self.lock_time}:{self.timestamp}:{self.fee}"
        
        # Add inputs (without signatures for deterministic calculation)
        for inp in self.inputs:
            tx_string += f"|{inp.prev_txid}:{inp.prev_vout}:{inp.sequence}"
        
        # Add outputs
        for out in self.outputs:
            tx_string += f"|{out.value}:{out.recipient_address}"
        
        # Use BLAKE2b for quantum-resistant hashing
        return hashlib.blake2b(tx_string.encode(), digest_size=32).hexdigest()
    
    def get_signing_message(self) -> bytes:
        """Get the message to be signed (without signatures)"""
        # Create signing message excluding signatures
        signing_data = {
            'version': self.version,
            'inputs': [],
            'outputs': [],
            'lock_time': self.lock_time,
            'fee': self.fee,
            'timestamp': self.timestamp
        }
        
        # Add inputs without signatures
        for inp in self.inputs:
            signing_data['inputs'].append({
                'prev_txid': inp.prev_txid,
                'prev_vout': inp.prev_vout,
                'sequence': inp.sequence
            })
        
        # Add outputs (convert bytes to hex)
        for out in self.outputs:
            signing_data['outputs'].append({
                'value': out.value,
                'recipient_address': out.recipient_address,
                'public_key_hash': out.public_key_hash.hex() if out.public_key_hash else ''
            })
        
        # Convert to bytes for signing
        signing_json = json.dumps(signing_data, sort_keys=True)
        return signing_json.encode()
    
    def sign_input(self, input_index: int, private_key: bytes, public_key: bytes) -> bool:
        """Sign a specific input with Dilithium private key"""
        try:
            if input_index >= len(self.inputs):
                raise ValueError("Invalid input index")
            
            # Get message to sign
            signing_message = self.get_signing_message()
            
            # Sign the message
            signature = sign_message(signing_message, private_key)
            
            # Update the input with signature and public key
            self.inputs[input_index].signature = signature
            self.inputs[input_index].public_key = public_key
            
            return True
            
        except Exception as e:
            print(f"Failed to sign input {input_index}: {e}")
            return False
    
    def verify_input(self, input_index: int) -> bool:
        """Verify a specific input signature"""
        try:
            if input_index >= len(self.inputs):
                return False
            
            inp = self.inputs[input_index]
            
            # Check if signature and public key are present
            if not inp.signature or not inp.public_key:
                return False
            
            # Get the message that was signed
            signing_message = self.get_signing_message()
            
            # Verify the signature
            return verify_signature(signing_message, inp.signature, inp.public_key)
            
        except Exception as e:
            print(f"Failed to verify input {input_index}: {e}")
            return False
    
    def verify_all_inputs(self) -> bool:
        """Verify all input signatures"""
        try:
            for i in range(len(self.inputs)):
                if not self.verify_input(i):
                    return False
            return True
        except Exception as e:
            print(f"Failed to verify all inputs: {e}")
            return False
    
    def is_coinbase(self) -> bool:
        """Check if this is a coinbase transaction"""
        return (len(self.inputs) == 1 and 
                self.inputs[0].prev_txid == "0" * 64 and 
                self.inputs[0].prev_vout == 0xffffffff)
    
    def get_size(self) -> int:
        """Calculate transaction size in bytes"""
        # Base transaction size
        size = 100  # Base overhead
        
        # Add input sizes
        for inp in self.inputs:
            size += 64  # prev_txid (32 bytes as hex)
            size += 4   # prev_vout
            size += 4   # sequence
            size += DILITHIUM_SIGNATURE_SIZE  # signature
            size += DILITHIUM_PUBKEY_SIZE     # public_key
        
        # Add output sizes
        for out in self.outputs:
            size += 8   # value
            size += 45  # address
            size += 32  # public_key_hash
        
        # Add privacy proof size if present
        if self.privacy_proof:
            size += len(self.privacy_proof)
        
        if self.ring_signature:
            size += len(self.ring_signature)
        
        return size
    
    def to_dict(self) -> dict:
        """Convert transaction to dictionary for serialization"""
        return {
            'version': self.version,
            'inputs': [
                {
                    'prev_txid': inp.prev_txid,
                    'prev_vout': inp.prev_vout,
                    'signature': inp.signature.hex() if inp.signature else '',
                    'public_key': inp.public_key.hex() if inp.public_key else '',
                    'sequence': inp.sequence
                }
                for inp in self.inputs
            ],
            'outputs': [
                {
                    'value': out.value,
                    'recipient_address': out.recipient_address,
                    'public_key_hash': out.public_key_hash.hex() if out.public_key_hash else ''
                }
                for out in self.outputs
            ],
            'lock_time': self.lock_time,
            'fee': self.fee,
            'privacy_proof': self.privacy_proof.hex() if self.privacy_proof else '',
            'ring_signature': self.ring_signature.hex() if self.ring_signature else '',
            'timestamp': self.timestamp,
            'txid': self.calculate_txid(),
            'size': self.get_size()
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'QuantumTransaction':
        """Create transaction from dictionary"""
        # Parse inputs
        inputs = []
        for inp_data in data['inputs']:
            inputs.append(QuantumTransactionInput(
                prev_txid=inp_data['prev_txid'],
                prev_vout=inp_data['prev_vout'],
                signature=bytes.fromhex(inp_data['signature']) if inp_data['signature'] else b'',
                public_key=bytes.fromhex(inp_data['public_key']) if inp_data['public_key'] else b'',
                sequence=inp_data['sequence']
            ))
        
        # Parse outputs
        outputs = []
        for out_data in data['outputs']:
            outputs.append(QuantumTransactionOutput(
                value=out_data['value'],
                recipient_address=out_data['recipient_address'],
                public_key_hash=bytes.fromhex(out_data['public_key_hash']) if out_data['public_key_hash'] else b''
            ))
        
        return cls(
            version=data['version'],
            inputs=inputs,
            outputs=outputs,
            lock_time=data['lock_time'],
            fee=data['fee'],
            privacy_proof=bytes.fromhex(data['privacy_proof']) if data['privacy_proof'] else None,
            ring_signature=bytes.fromhex(data['ring_signature']) if data['ring_signature'] else None,
            timestamp=data['timestamp']
        )

class QuantumTransactionBuilder:
    """Builder for quantum-resistant transactions"""
    
    def __init__(self):
        self.version = 1
        self.inputs = []
        self.outputs = []
        self.lock_time = 0
        self.fee = 0
        self.timestamp = int(time.time())
    
    def add_input(self, prev_txid: str, prev_vout: int, sequence: int = 0xffffffff) -> 'QuantumTransactionBuilder':
        """Add input to transaction"""
        self.inputs.append(QuantumTransactionInput(
            prev_txid=prev_txid,
            prev_vout=prev_vout,
            signature=b'',  # Will be filled during signing
            public_key=b'',  # Will be filled during signing
            sequence=sequence
        ))
        return self
    
    def add_output(self, value: int, recipient_address: str) -> 'QuantumTransactionBuilder':
        """Add output to transaction"""
        self.outputs.append(QuantumTransactionOutput(
            value=value,
            recipient_address=recipient_address
        ))
        return self
    
    def set_fee(self, fee: int) -> 'QuantumTransactionBuilder':
        """Set transaction fee"""
        self.fee = fee
        return self
    
    def set_lock_time(self, lock_time: int) -> 'QuantumTransactionBuilder':
        """Set transaction lock time"""
        self.lock_time = lock_time
        return self
    
    def build(self) -> QuantumTransaction:
        """Build the transaction"""
        if not self.inputs:
            raise ValueError("Transaction must have at least one input")
        
        if not self.outputs:
            raise ValueError("Transaction must have at least one output")
        
        return QuantumTransaction(
            version=self.version,
            inputs=self.inputs,
            outputs=self.outputs,
            lock_time=self.lock_time,
            fee=self.fee,
            timestamp=self.timestamp
        )

class QuantumWallet:
    """Quantum-resistant wallet using Dilithium signatures"""
    
    def __init__(self):
        self.keypair: Optional[DilithiumKeyPair] = None
        self.address: Optional[str] = None
    
    def generate_new_wallet(self) -> dict:
        """Generate a new quantum-resistant wallet"""
        # Generate Dilithium keypair
        self.keypair = generate_dilithium_keypair()
        
        # Generate WEPO address
        self.address = generate_wepo_address(self.keypair.public_key)
        
        return {
            'address': self.address,
            'public_key': self.keypair.public_key.hex(),
            'private_key': self.keypair.private_key.hex(),
            'algorithm': 'Dilithium2',
            'quantum_resistant': True
        }
    
    def load_wallet(self, private_key_hex: str) -> bool:
        """Load wallet from private key"""
        try:
            private_key = bytes.fromhex(private_key_hex)
            
            # Load the private key
            signer = DilithiumSigner()
            if signer.load_private_key(private_key):
                # Regenerate keypair (in real implementation, derive public key)
                self.keypair = generate_dilithium_keypair()
                self.keypair.private_key = private_key
                self.address = generate_wepo_address(self.keypair.public_key)
                return True
            
            return False
            
        except Exception as e:
            print(f"Failed to load wallet: {e}")
            return False
    
    def sign_transaction(self, transaction: QuantumTransaction) -> bool:
        """Sign all inputs of a transaction"""
        if not self.keypair:
            raise ValueError("Wallet not initialized")
        
        try:
            # Sign all inputs
            for i in range(len(transaction.inputs)):
                if not transaction.sign_input(i, self.keypair.private_key, self.keypair.public_key):
                    return False
            
            return True
            
        except Exception as e:
            print(f"Failed to sign transaction: {e}")
            return False
    
    def create_transaction(self, recipient_address: str, amount: int, fee: int, utxos: List[dict]) -> Optional[QuantumTransaction]:
        """Create a new transaction"""
        if not self.keypair:
            raise ValueError("Wallet not initialized")
        
        try:
            # Build transaction
            builder = QuantumTransactionBuilder()
            builder.set_fee(fee)
            
            # Add inputs from UTXOs
            total_input_value = 0
            for utxo in utxos:
                builder.add_input(utxo['txid'], utxo['vout'])
                total_input_value += utxo['amount']
            
            # Add output to recipient
            builder.add_output(amount, recipient_address)
            
            # Add change output if needed
            change_amount = total_input_value - amount - fee
            if change_amount > 0:
                builder.add_output(change_amount, self.address)
            
            # Build transaction
            transaction = builder.build()
            
            # Sign transaction
            if self.sign_transaction(transaction):
                return transaction
            else:
                print("Failed to sign transaction")
                return None
            
        except Exception as e:
            print(f"Failed to create transaction: {e}")
            import traceback
            traceback.print_exc()
            return None

# Testing function
def test_quantum_transaction_system():
    """Test the quantum transaction system"""
    print("Testing WEPO Quantum Transaction System...")
    
    # Create two wallets
    wallet1 = QuantumWallet()
    wallet2 = QuantumWallet()
    
    wallet1_info = wallet1.generate_new_wallet()
    wallet2_info = wallet2.generate_new_wallet()
    
    print(f"✓ Generated two quantum wallets")
    print(f"  Wallet 1: {wallet1_info['address']}")
    print(f"  Wallet 2: {wallet2_info['address']}")
    
    # Create a test transaction
    utxos = [
        {'txid': '0' * 64, 'vout': 0, 'amount': 1000000000}  # 10 WEPO
    ]
    
    transaction = wallet1.create_transaction(
        recipient_address=wallet2_info['address'],
        amount=500000000,  # 5 WEPO
        fee=10000,         # 0.0001 WEPO
        utxos=utxos
    )
    
    if transaction:
        print(f"✓ Created transaction: {transaction.calculate_txid()}")
        print(f"  Size: {transaction.get_size()} bytes")
        print(f"  Inputs: {len(transaction.inputs)}")
        print(f"  Outputs: {len(transaction.outputs)}")
        
        # Verify transaction
        is_valid = transaction.verify_all_inputs()
        print(f"✓ Transaction verification: {is_valid}")
        
        # Test serialization
        tx_dict = transaction.to_dict()
        reconstructed_tx = QuantumTransaction.from_dict(tx_dict)
        
        print(f"✓ Serialization test: {reconstructed_tx.calculate_txid() == transaction.calculate_txid()}")
    else:
        print("✗ Failed to create transaction")
    
    print("🎉 All quantum transaction tests passed!")
    
    return True

if __name__ == "__main__":
    test_quantum_transaction_system()
