#!/usr/bin/env python3
"""
WEPO Quantum-Resistant Dilithium Signature Implementation
UPGRADED TO REAL DILITHIUM2 - TRUE QUANTUM RESISTANCE
"""

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
_MLDSA_IMPORT_ERROR = None
try:
    from dilithium_py.ml_dsa import ML_DSA_44
    REAL_DILITHIUM_AVAILABLE = True
    # ASCII-only (no emoji): emoji crashes Python on Windows under the default
    # cp1252 console codec. This is a one-time module-load notice.
    print("[ML-DSA-44] FIPS 204 imported successfully")
except ImportError as exc:
    ML_DSA_44 = None
    REAL_DILITHIUM_AVAILABLE = False
    _MLDSA_IMPORT_ERROR = exc
    print("[ML-DSA-44] unavailable - cryptographic operations disabled")

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
    """FIPS 204 ML-DSA-44 signer with no simulation or fallback path."""

    def __init__(self, algorithm: str = "ML-DSA-44"):
        """Initialize only when the real FIPS 204 implementation is present."""
        if not REAL_DILITHIUM_AVAILABLE or ML_DSA_44 is None:
            raise RuntimeError(
                "FIPS 204 ML-DSA-44 is unavailable; cryptographic operations "
                "are disabled"
            ) from _MLDSA_IMPORT_ERROR
        self.algorithm = algorithm
        self.public_key = None
        self.private_key = None
        self.is_real_dilithium = True
        self._dilithium = ML_DSA_44
        
    def generate_keypair(self) -> DilithiumKeyPair:
        """Generate a FIPS 204 ML-DSA-44 key pair."""
        try:
            public_key, private_key = self._dilithium.keygen()
            if len(public_key) != DILITHIUM_PUBKEY_SIZE:
                raise ValueError(
                    f"Invalid public key size: {len(public_key)} != "
                    f"{DILITHIUM_PUBKEY_SIZE}"
                )
            if len(private_key) != DILITHIUM_PRIVKEY_SIZE:
                raise ValueError(
                    f"Invalid private key size: {len(private_key)} != "
                    f"{DILITHIUM_PRIVKEY_SIZE}"
                )
            self.public_key = public_key
            self.private_key = private_key
            return DilithiumKeyPair(
                public_key=public_key,
                private_key=private_key,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to generate ML-DSA keypair: {exc}") from exc
    
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
        """Sign a message with a loaded FIPS 204 ML-DSA-44 private key."""
        if not self.private_key:
            raise ValueError("Private key not loaded")
        try:
            signature = self._dilithium.sign(self.private_key, message)
            if len(signature) != DILITHIUM_SIGNATURE_SIZE:
                raise ValueError(
                    f"Invalid signature size: {len(signature)} != "
                    f"{DILITHIUM_SIGNATURE_SIZE}"
                )
            return signature
        except Exception as exc:
            raise RuntimeError(f"Failed to sign message: {exc}") from exc
    
    def verify(self, message: bytes, signature: bytes, public_key: bytes = None) -> bool:
        """Verify a FIPS 204 ML-DSA-44 signature, failing closed on errors."""
        try:
            pub_key = public_key or self.public_key
            if not pub_key:
                return False
            if len(signature) != DILITHIUM_SIGNATURE_SIZE:
                return False
            if len(pub_key) != DILITHIUM_PUBKEY_SIZE:
                return False
            return bool(self._dilithium.verify(pub_key, message, signature))
        except Exception as exc:
            print(f"Signature verification failed: {exc}")
            return False
    
    def get_public_key(self) -> Optional[bytes]:
        """Get the current public key"""
        return self.public_key
    
    def get_private_key(self) -> Optional[bytes]:
        """Get the current private key"""
        return self.private_key
    
    def get_algorithm_info(self) -> dict:
        """Get information about the active FIPS 204 implementation."""
        return {
            "algorithm": "ML-DSA-44",
            "variant": "FIPS 204 ML-DSA-44",
            "security_level": DILITHIUM_SECURITY_LEVEL,
            "quantum_resistant": True,
            "public_key_size": DILITHIUM_PUBKEY_SIZE,
            "private_key_size": DILITHIUM_PRIVKEY_SIZE,
            "signature_size": DILITHIUM_SIGNATURE_SIZE,
            "implementation": "dilithium-py (Pure Python NIST ML-DSA)",
            "post_quantum": True,
            "nist_approved": True,
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
    """Generate a FIPS 204 ML-DSA-44 keypair."""
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

def require_real_mldsa() -> None:
    """Fail closed when the FIPS 204 implementation is unavailable."""
    if not REAL_DILITHIUM_AVAILABLE or ML_DSA_44 is None:
        raise RuntimeError(
            "Mainnet requires the real FIPS 204 ML-DSA-44 implementation; "
            "cryptographic operations are disabled"
        )


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
    
    # Signer construction already proved the real implementation is present.
    if signer.is_quantum_resistant():
        print("\n🎉 WEPO NOW HAS REAL QUANTUM RESISTANCE!")
    else:
        print("\n⚠️  WEPO is using RSA simulation - upgrade to real Dilithium2 for quantum resistance")
