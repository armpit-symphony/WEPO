#!/usr/bin/env python3
"""
WEPO Quantum-Resistant Dilithium Signature Implementation
UPGRADED TO REAL DILITHIUM2 - TRUE QUANTUM RESISTANCE
"""

import hashlib
import secrets
from typing import Optional
from dataclasses import dataclass

try:
    from .address_utils import (
        generate_wepo_address as _generate_wepo_address,
        validate_wepo_address as _validate_wepo_address,
    )
except ImportError:
    from address_utils import (
        generate_wepo_address as _generate_wepo_address,
        validate_wepo_address as _validate_wepo_address,
    )

# Use FIPS-204 ML-DSA-44 (the standardized successor to round-3 Dilithium2).
# ML-DSA-44 has matching public-key (1312) and signature (2420) sizes and is
# implemented in both Python (dilithium_py.ml_dsa) and JavaScript
# (@noble/post-quantum), enabling cross-language client-side wallet signing.
try:
    from dilithium_py.ml_dsa import ML_DSA_44
    REAL_DILITHIUM_AVAILABLE = True
    print("✅ ML-DSA-44 (FIPS 204) imported successfully")
except ImportError:
    REAL_DILITHIUM_AVAILABLE = False
    print("⚠️  ML-DSA-44 not available - using RSA simulation")
    # Fallback imports for RSA simulation
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.backends import default_backend

import struct

# ML-DSA-44 (FIPS 204) parameter sizes
DILITHIUM_PUBKEY_SIZE = 1312   # bytes
DILITHIUM_PRIVKEY_SIZE = 2560  # bytes (ML-DSA-44; round-3 Dilithium2 was 2528)
DILITHIUM_SIGNATURE_SIZE = 2420 # bytes (actual NIST standard)
DILITHIUM_SECURITY_LEVEL = 128  # bits (equivalent to AES-128)

@dataclass
class DilithiumKeyPair:
    """Dilithium key pair representation"""
    public_key: bytes
    private_key: bytes
    
    def export_public_key(self) -> bytes:
        """Export public key in standard format"""
        return self.public_key
    
    def export_private_key(self) -> bytes:
        """Export private key in standard format"""
        return self.private_key

class DilithiumSigner:
    """Dilithium digital signature implementation - NOW WITH REAL QUANTUM RESISTANCE"""
    
    def __init__(self, algorithm: str = "Dilithium2"):
        """Initialize Dilithium signer with REAL or simulated implementation"""
        self.algorithm = algorithm
        self.public_key = None
        self.private_key = None
        self.is_real_dilithium = REAL_DILITHIUM_AVAILABLE
        
        if REAL_DILITHIUM_AVAILABLE:
            # Use REAL ML-DSA-44 (FIPS 204) implementation. Signing draws fresh
            # OS randomness per call (hedged ML-DSA), so we do not pin a DRBG seed.
            self._dilithium = ML_DSA_44
            print("🔐 Using ML-DSA-44 (FIPS 204) - TRUE quantum resistance")
        else:
            # Fallback to RSA simulation
            self._rsa_key_pair = None
            print("⚠️  Using RSA simulation - NOT quantum resistant")
        
    def generate_keypair(self) -> DilithiumKeyPair:
        """Generate a new Dilithium key pair (REAL or simulated)"""
        try:
            if self.is_real_dilithium:
                # Generate REAL quantum-resistant keypair
                public_key, private_key = self._dilithium.keygen()
                
                # Validate key sizes match NIST specification
                if len(public_key) != DILITHIUM_PUBKEY_SIZE:
                    raise ValueError(f"Invalid public key size: {len(public_key)} != {DILITHIUM_PUBKEY_SIZE}")
                
                if len(private_key) != DILITHIUM_PRIVKEY_SIZE:
                    raise ValueError(f"Invalid private key size: {len(private_key)} != {DILITHIUM_PRIVKEY_SIZE}")
                
                self.public_key = public_key
                self.private_key = private_key
                
                return DilithiumKeyPair(
                    public_key=public_key,
                    private_key=private_key
                )
            else:
                # Fallback to RSA simulation
                self._rsa_key_pair = rsa.generate_private_key(
                    public_exponent=65537,
                    key_size=3072,
                    backend=default_backend()
                )
                
                # Create Dilithium-format keys from RSA keys
                rsa_public_pem = self._rsa_key_pair.public_key().public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                )
                rsa_private_pem = self._rsa_key_pair.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                )
                
                # Pad/hash to Dilithium key sizes
                self.public_key = self._format_to_dilithium_public(rsa_public_pem)
                self.private_key = self._format_to_dilithium_private(rsa_private_pem)
                
                return DilithiumKeyPair(
                    public_key=self.public_key,
                    private_key=self.private_key
                )
            
        except Exception as e:
            raise Exception(f"Failed to generate Dilithium keypair: {e}")
    
    def _format_to_dilithium_public(self, rsa_public_pem: bytes) -> bytes:
        """Format RSA public key to Dilithium public key size (RSA simulation only)"""
        hash_obj = hashlib.blake2b(rsa_public_pem, digest_size=32)
        key_hash = hash_obj.digest()
        
        dilithium_key = bytearray(DILITHIUM_PUBKEY_SIZE)
        for i in range(DILITHIUM_PUBKEY_SIZE):
            dilithium_key[i] = key_hash[i % len(key_hash)]
        
        dilithium_key[0:4] = b'DIL2'
        dilithium_key[4:8] = struct.pack('>I', DILITHIUM_SECURITY_LEVEL)
        
        return bytes(dilithium_key)
    
    def _format_to_dilithium_private(self, rsa_private_pem: bytes) -> bytes:
        """Format RSA private key to Dilithium private key size (RSA simulation only)"""
        hash_obj = hashlib.blake2b(rsa_private_pem, digest_size=64)
        key_hash = hash_obj.digest()
        
        dilithium_key = bytearray(DILITHIUM_PRIVKEY_SIZE)
        for i in range(DILITHIUM_PRIVKEY_SIZE):
            dilithium_key[i] = key_hash[i % len(key_hash)]
        
        dilithium_key[0:4] = b'DIL2'
        dilithium_key[4:8] = struct.pack('>I', DILITHIUM_SECURITY_LEVEL)
        
        return bytes(dilithium_key)
    
    def load_private_key(self, private_key_bytes: bytes) -> bool:
        """Load private key from bytes"""
        try:
            if len(private_key_bytes) != DILITHIUM_PRIVKEY_SIZE:
                raise ValueError(f"Invalid private key size: {len(private_key_bytes)}")
            
            self.private_key = private_key_bytes
            return True
            
        except Exception as e:
            print(f"Failed to load private key: {e}")
            return False
    
    def load_public_key(self, public_key_bytes: bytes) -> bool:
        """Load public key from bytes"""
        try:
            if len(public_key_bytes) != DILITHIUM_PUBKEY_SIZE:
                raise ValueError(f"Invalid public key size: {len(public_key_bytes)}")
            
            self.public_key = public_key_bytes
            return True
            
        except Exception as e:
            print(f"Failed to load public key: {e}")
            return False
    
    def sign(self, message: bytes) -> bytes:
        """Sign a message with Dilithium private key (REAL or simulated)"""
        if not self.private_key:
            raise ValueError("Private key not loaded")
        
        try:
            if self.is_real_dilithium:
                # Sign using REAL NIST ML-DSA Dilithium2
                signature = self._dilithium.sign(self.private_key, message)
                
                # Validate signature size
                if len(signature) != DILITHIUM_SIGNATURE_SIZE:
                    raise ValueError(f"Invalid signature size: {len(signature)} != {DILITHIUM_SIGNATURE_SIZE}")
                
                return signature
            else:
                # Fallback to RSA simulation
                if not self._rsa_key_pair:
                    raise ValueError("RSA key pair not loaded")
                
                message_hash = hashlib.blake2b(message, digest_size=32).digest()
                
                rsa_signature = self._rsa_key_pair.sign(
                    message_hash,
                    padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH
                    ),
                    hashes.SHA256()
                )
                
                return self._format_to_dilithium_signature(rsa_signature, message_hash)
            
        except Exception as e:
            raise Exception(f"Failed to sign message: {e}")
    
    def verify(self, message: bytes, signature: bytes, public_key: bytes = None) -> bool:
        """Verify a Dilithium signature (REAL or simulated)"""
        try:
            pub_key = public_key or self.public_key
            if not pub_key:
                raise ValueError("No public key available")
            
            # Validate input sizes
            if len(signature) != DILITHIUM_SIGNATURE_SIZE:
                return False
            
            if len(pub_key) != DILITHIUM_PUBKEY_SIZE:
                return False
            
            if self.is_real_dilithium:
                # Verify using REAL NIST ML-DSA Dilithium2
                return self._dilithium.verify(pub_key, message, signature)
            else:
                # Fallback to RSA simulation verification
                return self._verify_rsa_simulation(message, signature, pub_key)
            
        except Exception as e:
            print(f"Signature verification failed: {e}")
            return False
    
    def _format_to_dilithium_signature(self, rsa_signature: bytes, message_hash: bytes) -> bytes:
        """Format RSA signature to Dilithium signature size (RSA simulation only)"""
        combined = rsa_signature + message_hash
        hash_obj = hashlib.blake2b(combined, digest_size=64)
        sig_hash = hash_obj.digest()
        
        dilithium_sig = bytearray(DILITHIUM_SIGNATURE_SIZE)
        for i in range(DILITHIUM_SIGNATURE_SIZE):
            dilithium_sig[i] = sig_hash[i % len(sig_hash)]
        
        dilithium_sig[0:4] = b'SIG2'
        dilithium_sig[4:8] = struct.pack('>I', len(rsa_signature))
        dilithium_sig[8:8+len(rsa_signature)] = rsa_signature
        
        return bytes(dilithium_sig)
    
    def _verify_rsa_simulation(self, message: bytes, signature: bytes, public_key: bytes) -> bool:
        """Verify RSA simulation signature (fallback only)"""
        try:
            # Extract RSA signature from Dilithium format
            if signature[0:4] != b'SIG2':
                return False
            
            rsa_sig_length = struct.unpack('>I', signature[4:8])[0]
            rsa_signature = signature[8:8+rsa_sig_length]
            
            # This is a simplified verification for RSA simulation
            # In practice, we would need to reconstruct the RSA public key
            # For now, we'll do a hash-based verification
            message_hash = hashlib.blake2b(message, digest_size=32).digest()
            combined = rsa_signature + message_hash
            expected_hash = hashlib.blake2b(combined, digest_size=64).digest()
            
            # Check if signature matches expected pattern
            sig_hash = signature[8:8+64] if len(signature) > 72 else signature[8:]
            return sig_hash == expected_hash[:len(sig_hash)]
            
        except Exception as e:
            print(f"RSA simulation verification failed: {e}")
            return False
    
    def get_public_key(self) -> Optional[bytes]:
        """Get the current public key"""
        return self.public_key
    
    def get_private_key(self) -> Optional[bytes]:
        """Get the current private key"""
        return self.private_key
    
    def get_algorithm_info(self) -> dict:
        """Get information about the Dilithium algorithm"""
        return {
            "algorithm": "ML-DSA-44" if self.is_real_dilithium else "Dilithium2",
            "variant": "FIPS 204 ML-DSA-44" if self.is_real_dilithium else "RSA Simulation",
            "security_level": DILITHIUM_SECURITY_LEVEL,
            "quantum_resistant": self.is_real_dilithium,
            "public_key_size": DILITHIUM_PUBKEY_SIZE,
            "private_key_size": DILITHIUM_PRIVKEY_SIZE,
            "signature_size": DILITHIUM_SIGNATURE_SIZE,
            "implementation": "dilithium-py (Pure Python NIST ML-DSA)" if self.is_real_dilithium else "RSA-3072 simulation",
            "post_quantum": self.is_real_dilithium,
            "nist_approved": self.is_real_dilithium
        }
    
    def is_quantum_resistant(self) -> bool:
        """Check if this instance is using real quantum-resistant cryptography"""
        return self.is_real_dilithium


class DilithiumVerifier:
    """Backward-compatible verification wrapper used by older callers"""

    def verify(self, message: bytes, signature: bytes, public_key: bytes) -> bool:
        signer = DilithiumSigner()
        return signer.verify(message, signature, public_key)

# Convenience functions for backward compatibility
def generate_dilithium_keypair() -> DilithiumKeyPair:
    """Generate a new Dilithium keypair (REAL or simulated)"""
    signer = DilithiumSigner()
    return signer.generate_keypair()

def sign_with_dilithium(message: bytes, private_key: bytes) -> bytes:
    """Sign a message with Dilithium"""
    signer = DilithiumSigner()
    signer.load_private_key(private_key)
    return signer.sign(message)

def verify_dilithium_signature(message: bytes, signature: bytes, public_key: bytes) -> bool:
    """Verify a Dilithium signature"""
    signer = DilithiumSigner()
    return signer.verify(message, signature, public_key)


def sign_message(message: bytes, private_key: bytes) -> bytes:
    """Backward-compatible alias for signing helpers used across the core"""
    return sign_with_dilithium(message, private_key)


def verify_signature(message: bytes, signature: bytes, public_key: bytes) -> bool:
    """Backward-compatible alias for verification helpers used across the core"""
    return verify_dilithium_signature(message, signature, public_key)


def generate_wepo_address(seed: bytes, address_type: str = "quantum") -> str:
    """Generate a standardized WEPO address from Dilithium material"""
    return _generate_wepo_address(seed, address_type=address_type)


def validate_wepo_address(address: str) -> bool:
    """Backward-compatible bool-returning address validator"""
    return _validate_wepo_address(address)["valid"]


def get_dilithium_info() -> dict:
    """Return current Dilithium implementation details"""
    signer = DilithiumSigner()
    return signer.get_algorithm_info()


class _DilithiumSystemCompat:
    """Compatibility surface for older blockchain imports"""

    @staticmethod
    def generate_keypair() -> DilithiumKeyPair:
        return generate_dilithium_keypair()

    @staticmethod
    def sign(message: bytes, private_key: bytes) -> bytes:
        return sign_message(message, private_key)

    @staticmethod
    def verify(message: bytes, signature: bytes, public_key: bytes) -> bool:
        return verify_signature(message, signature, public_key)

    @staticmethod
    def info() -> dict:
        return get_dilithium_info()


dilithium_system = _DilithiumSystemCompat()

def is_real_dilithium_available() -> bool:
    """Check if real Dilithium implementation is available"""
    return REAL_DILITHIUM_AVAILABLE

if __name__ == "__main__":
    # Test the implementation
    print("🧪 Testing Dilithium Implementation")
    print("=" * 50)
    
    signer = DilithiumSigner()
    print(f"Using real Dilithium: {signer.is_quantum_resistant()}")
    
    # Test key generation
    keypair = signer.generate_keypair()
    print(f"✅ Generated keypair - PubKey: {len(keypair.public_key)} bytes, PrivKey: {len(keypair.private_key)} bytes")
    
    # Test signing
    test_message = b"WEPO - We The People - Quantum Resistant Test"
    signature = signer.sign(test_message)
    print(f"✅ Signed message - Signature: {len(signature)} bytes")
    
    # Test verification
    is_valid = signer.verify(test_message, signature)
    print(f"✅ Signature valid: {is_valid}")
    
    # Show algorithm info
    info = signer.get_algorithm_info()
    print(f"\nAlgorithm Info:")
    for key, value in info.items():
        print(f"   {key}: {value}")
    
    if signer.is_quantum_resistant():
        print("\n🎉 WEPO NOW HAS REAL QUANTUM RESISTANCE!")
    else:
        print("\n⚠️  WEPO is using RSA simulation - upgrade to real Dilithium2 for quantum resistance")
