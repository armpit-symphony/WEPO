#!/usr/bin/env python3
"""
Test script for real cryptographic privacy implementation
"""

import sys
import os
sys.path.append('/app/wepo-blockchain')

from core.privacy import (
    WepoPrivacyEngine, 
    ZKStarkProver, 
    RingSignature, 
    ConfidentialTransactions,
    create_privacy_proof,
    verify_privacy_proof,
    generate_real_private_key,
    create_ring_signature_proof,
    verify_ring_signature_proof
)

from ecdsa import SigningKey, SECP256k1
from Crypto.Random import get_random_bytes
import json
import time

def test_zk_stark_proofs():
    """Test real zk-STARK proof generation and verification"""
    print("=== Testing zk-STARK Proofs ===")
    
    try:
        prover = ZKStarkProver()
        
        # Generate test data
        secret_input = generate_real_private_key()
        public_statement = b"test_transaction_12345"
        
        # Generate proof
        print("Generating zk-STARK proof...")
        proof = prover.generate_stark_proof(secret_input, public_statement)
        
        print(f"Proof type: {proof.proof_type}")
        print(f"Proof data size: {len(proof.proof_data)} bytes")
        print(f"Field prime: {proof.public_parameters['field_prime']}")
        print(f"Polynomial degree: {proof.public_parameters['polynomial_degree']}")
        
        # Verify proof
        print("Verifying zk-STARK proof...")
        is_valid = prover.verify_stark_proof(proof, public_statement)
        
        print(f"Proof verification: {'PASS' if is_valid else 'FAIL'}")
        
        # Test with wrong public statement
        print("Testing with wrong public statement...")
        wrong_statement = b"wrong_transaction_12345"
        is_invalid = prover.verify_stark_proof(proof, wrong_statement)
        
        print(f"Wrong statement rejection: {'PASS' if not is_invalid else 'FAIL'}")
        
        return is_valid and not is_invalid
        
    except Exception as e:
        print(f"zk-STARK test failed: {e}")
        return False

def test_ring_signatures():
    """Test real ring signature generation and verification"""
    print("\n=== Testing Ring Signatures ===")
    
    try:
        ring_sig = RingSignature()
        
        # Generate test keys
        signer_private = generate_real_private_key()
        signer_public = SigningKey.from_string(signer_private, curve=SECP256k1).get_verifying_key().to_string()
        
        # Generate decoy keys
        decoy_keys = []
        for i in range(4):
            decoy_private = SigningKey.generate(curve=SECP256k1)
            decoy_public = decoy_private.get_verifying_key().to_string()
            decoy_keys.append(decoy_public)
        
        all_public_keys = [signer_public] + decoy_keys
        message = b"test_ring_signature_message"
        
        # Generate ring signature
        print("Generating ring signature...")
        proof = ring_sig.generate_ring_signature(message, signer_private, all_public_keys)
        
        print(f"Ring size: {proof.public_parameters['ring_size']}")
        print(f"Key image: {proof.public_parameters['key_image'][:16]}...")
        print(f"Signature data size: {len(proof.proof_data)} bytes")
        
        # Verify ring signature
        print("Verifying ring signature...")
        is_valid = ring_sig.verify_ring_signature(proof, message)
        
        print(f"Ring signature verification: {'PASS' if is_valid else 'FAIL'}")
        
        # Test with wrong message
        print("Testing with wrong message...")
        wrong_message = b"wrong_ring_signature_message"
        is_invalid = ring_sig.verify_ring_signature(proof, wrong_message)
        
        print(f"Wrong message rejection: {'PASS' if not is_invalid else 'FAIL'}")
        
        return is_valid and not is_invalid
        
    except Exception as e:
        print(f"Ring signature test failed: {e}")
        return False

def test_confidential_transactions():
    """Test real confidential transaction generation and verification"""
    print("\n=== Testing Confidential Transactions ===")
    
    try:
        conf_tx = ConfidentialTransactions()
        
        # Test parameters
        amount = 100000000  # 1 WEPO in satoshis
        blinding_factor = get_random_bytes(32)
        
        # Generate range proof
        print("Generating range proof...")
        proof = conf_tx.generate_range_proof(amount, blinding_factor)
        
        print(f"Commitment: {proof.public_parameters['commitment'][:32]}...")
        print(f"Range: {proof.public_parameters['min_value']} - {proof.public_parameters['max_value']}")
        print(f"Proof size: {proof.public_parameters['proof_size']} bytes")
        
        # Verify range proof
        print("Verifying range proof...")
        is_valid = conf_tx.verify_range_proof(proof)
        
        print(f"Range proof verification: {'PASS' if is_valid else 'FAIL'}")
        
        # Test commitment
        print("Testing commitment...")
        commitment = conf_tx.commit_amount(amount, blinding_factor)
        print(f"Commitment created: {commitment.hex()[:32]}...")
        
        # Test with amount outside range
        print("Testing with amount outside range...")
        try:
            invalid_proof = conf_tx.generate_range_proof(2**33, blinding_factor)  # Outside range
            print("ERROR: Should have failed for amount outside range")
            return False
        except ValueError:
            print("Correctly rejected amount outside range")
        
        return is_valid
        
    except Exception as e:
        print(f"Confidential transaction test failed: {e}")
        return False

def test_privacy_engine():
    """Test complete privacy engine integration"""
    print("\n=== Testing Privacy Engine Integration ===")
    
    try:
        engine = WepoPrivacyEngine()
        
        # Test parameters
        sender_private = generate_real_private_key()
        recipient_address = "wepo1test123456789abcdef"
        amount = 50000000  # 0.5 WEPO
        
        # Create private transaction
        print("Creating private transaction...")
        private_tx = engine.create_private_transaction(
            sender_private, recipient_address, amount
        )
        
        print(f"Privacy level: {private_tx['privacy_level']}")
        print(f"Ring size: {private_tx['ring_size']}")
        print(f"Commitment: {private_tx['commitment'][:32]}...")
        
        # Check individual proof validations
        proof_verifications = private_tx['proof_verification']
        print(f"Confidential proof valid: {proof_verifications['confidential_valid']}")
        print(f"Ring signature valid: {proof_verifications['ring_valid']}")
        print(f"zk-STARK proof valid: {proof_verifications['stark_valid']}")
        
        # Test overall verification using built-in unified message
        print("Verifying complete private transaction...")
        is_valid = engine.verify_private_transaction(private_tx)
        
        print(f"Complete transaction verification: {'PASS' if is_valid else 'FAIL'}")
        
        return (proof_verifications['confidential_valid'] and 
                proof_verifications['ring_valid'] and 
                proof_verifications['stark_valid'] and
                is_valid)
        
    except Exception as e:
        print(f"Privacy engine test failed: {e}")
        return False

def test_stealth_addresses():
    """Test stealth address generation"""
    print("\n=== Testing Stealth Addresses ===")
    
    try:
        engine = WepoPrivacyEngine()
        
        # Generate recipient key pair
        recipient_private = generate_real_private_key()
        recipient_public = engine.derive_public_key(recipient_private)
        
        # Generate stealth address
        print("Generating stealth address...")
        stealth_addr, ephemeral_public = engine.generate_stealth_address(recipient_public)
        
        print(f"Stealth address: {stealth_addr}")
        print(f"Ephemeral public key: {ephemeral_public.hex()[:32]}...")
        
        # Verify stealth address format
        is_valid_format = stealth_addr.startswith('wepo1') and len(stealth_addr) == 38
        print(f"Stealth address format: {'PASS' if is_valid_format else 'FAIL'}")
        
        return is_valid_format
        
    except Exception as e:
        print(f"Stealth address test failed: {e}")
        return False

def test_utility_functions():
    """Test utility functions"""
    print("\n=== Testing Utility Functions ===")
    
    try:
        # Test privacy proof creation
        print("Testing privacy proof creation...")
        transaction_data = {
            'recipient_address': 'wepo1test123456789abcdef',
            'amount': 25000000
        }
        
        proof_data = create_privacy_proof(transaction_data)
        print(f"Privacy proof created: {len(proof_data)} bytes")
        
        # Test verification
        print("Testing privacy proof verification...")
        message = b"test_verification_message"
        is_valid = verify_privacy_proof(proof_data, message)
        
        print(f"Privacy proof verification: {'PASS' if is_valid else 'FAIL'}")
        
        # Test ring signature utility
        print("Testing ring signature utility...")
        private_key = generate_real_private_key()
        ring_proof = create_ring_signature_proof(message, private_key)
        
        ring_valid = verify_ring_signature_proof(ring_proof, message)
        print(f"Ring signature utility: {'PASS' if ring_valid else 'FAIL'}")
        
        return is_valid and ring_valid
        
    except Exception as e:
        print(f"Utility function test failed: {e}")
        return False

def main():
    """Run all privacy tests"""
    print("WEPO Real Cryptographic Privacy Implementation Test")
    print("=" * 50)
    
    tests = [
        test_zk_stark_proofs,
        test_ring_signatures,
        test_confidential_transactions,
        test_privacy_engine,
        test_stealth_addresses,
        test_utility_functions
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
                print("✓ PASSED")
            else:
                print("✗ FAILED")
        except Exception as e:
            print(f"✗ ERROR: {e}")
    
    print(f"\nTest Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED - Real cryptographic privacy implementation is working!")
    else:
        print("❌ Some tests failed - Need to fix implementation")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)