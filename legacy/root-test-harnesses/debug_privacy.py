#!/usr/bin/env python3
"""
Debug script for privacy implementation verification issues
"""

import sys
import os
import struct
sys.path.append('/app/wepo-blockchain')

from core.privacy import ZKStarkProver, RingSignature, ConfidentialTransactions
from ecdsa import SigningKey, SECP256k1
from Crypto.Random import get_random_bytes
import traceback

def debug_zk_stark():
    """Debug zk-STARK verification"""
    print("=== Debugging zk-STARK ===")
    
    prover = ZKStarkProver()
    secret_input = get_random_bytes(32)
    public_statement = b"test"
    
    # Generate proof
    proof = prover.generate_stark_proof(secret_input, public_statement)
    print(f"Generated proof with commitment: {proof.public_parameters['commitment'][:16]}...")
    
    # Debug verification step by step
    print("\nStep-by-step verification:")
    
    # Check proof type
    print(f"1. Proof type check: {proof.proof_type == 'zk-stark'}")
    
    # Check field prime
    print(f"2. Field prime check: {proof.public_parameters['field_prime'] == prover.field_prime}")
    
    # Check proof size
    from core.privacy import ZK_STARK_PROOF_SIZE
    print(f"3. Proof size check: {len(proof.proof_data)} == {ZK_STARK_PROOF_SIZE}")
    
    # Check commitment
    commitment = bytes.fromhex(proof.public_parameters['commitment'])
    proof_commitment = proof.proof_data[:32]
    print(f"4. Commitment check: {proof_commitment == commitment}")
    
    # Check verification key
    expected_verification_key = prover.hash_function.new(digest_bits=256).update(
        commitment + public_statement + proof.proof_data
    ).digest()
    print(f"5. Verification key check: {expected_verification_key == proof.verification_key}")
    
    # Check FRI proof structure
    fri_proof = proof.proof_data[32:]
    print(f"6. FRI proof length: {len(fri_proof)} bytes")
    
    if len(fri_proof) >= 32:
        merkle_root = fri_proof[-32:]
        evaluations_data = fri_proof[:-32]
        print(f"7. Evaluations data length: {len(evaluations_data)} bytes")
        print(f"8. Merkle root: {merkle_root.hex()[:16]}...")
        
        # Try to reconstruct
        evaluation_points = proof.public_parameters['evaluation_points']
        print(f"9. Evaluation points count: {len(evaluation_points)}")
        
        if len(evaluations_data) >= 8:
            eval_hashes = []
            for i in range(min(len(evaluation_points), len(evaluations_data) // 8)):
                eval_bytes = evaluations_data[i*8:(i+1)*8]
                if len(eval_bytes) == 8:
                    eval_hash = prover.hash_function.new(digest_bits=256).update(eval_bytes).digest()
                    eval_hashes.append(eval_hash)
            
            print(f"10. Evaluation hashes count: {len(eval_hashes)}")
            
            if eval_hashes:
                reconstructed_root = eval_hashes[0]
                for hash_val in eval_hashes[1:]:
                    reconstructed_root = prover.hash_function.new(digest_bits=256).update(
                        reconstructed_root + hash_val
                    ).digest()
                
                print(f"11. Reconstructed root: {reconstructed_root.hex()[:16]}...")
                print(f"12. Merkle root match: {reconstructed_root == merkle_root}")
    
    return prover.verify_stark_proof(proof, public_statement)

def debug_ring_signature():
    """Debug ring signature verification"""
    print("\n=== Debugging Ring Signature ===")
    
    ring_sig = RingSignature()
    
    # Generate keys
    signer_private = SigningKey.generate(curve=SECP256k1).to_string()
    signer_public = SigningKey.from_string(signer_private, curve=SECP256k1).get_verifying_key().to_string()
    
    decoy_keys = []
    for i in range(4):
        decoy_private = SigningKey.generate(curve=SECP256k1)
        decoy_public = decoy_private.get_verifying_key().to_string()
        decoy_keys.append(decoy_public)
    
    all_public_keys = [signer_public] + decoy_keys
    message = b"test"
    
    # Generate signature
    proof = ring_sig.generate_ring_signature(message, signer_private, all_public_keys)
    print(f"Generated signature with ring size: {proof.public_parameters['ring_size']}")
    
    # Debug verification
    print("\nStep-by-step verification:")
    
    # Check proof type
    print(f"1. Proof type check: {proof.proof_type == 'ring-signature'}")
    
    # Check ring size
    ring_size = proof.public_parameters['ring_size']
    public_keys = [bytes.fromhex(pk) for pk in proof.public_parameters['public_keys']]
    print(f"2. Ring size check: {len(public_keys) == ring_size}")
    
    # Check proof data structure
    print(f"3. Proof data length: {len(proof.proof_data)} bytes")
    
    if len(proof.proof_data) >= 64:
        key_image = bytes.fromhex(proof.public_parameters['key_image'])
        extracted_key_image = proof.proof_data[:32]
        print(f"4. Key image check: {extracted_key_image == key_image}")
        
        challenge = int.from_bytes(bytes.fromhex(proof.public_parameters['challenge']), 'big')
        extracted_challenge = proof.proof_data[32:64]
        print(f"5. Challenge check: {extracted_challenge == challenge.to_bytes(32, 'big')}")
        
        # Check if we have enough data for responses and commitments
        min_size = 64 + (ring_size * 64)
        print(f"6. Minimum size check: {len(proof.proof_data)} >= {min_size}")
        
        if len(proof.proof_data) >= min_size:
            # Extract responses and commitments
            responses = []
            commitments = []
            pos = 64
            
            for i in range(ring_size):
                response = int.from_bytes(proof.proof_data[pos:pos+32], 'big')
                commitment = proof.proof_data[pos+32:pos+64]
                responses.append(response)
                commitments.append(commitment)
                pos += 64
            
            print(f"7. Extracted {len(responses)} responses and {len(commitments)} commitments")
            
            # Check commitment verification
            valid_commitments = 0
            for i in range(ring_size):
                expected_commitment = ring_sig.hash_function.new(
                    responses[i].to_bytes(32, 'big') + public_keys[i]
                ).digest()
                if expected_commitment == commitments[i]:
                    valid_commitments += 1
            
            print(f"8. Valid commitments: {valid_commitments}/{ring_size}")
    
    return ring_sig.verify_ring_signature(proof, message)

def debug_confidential_tx():
    """Debug confidential transaction verification"""
    print("\n=== Debugging Confidential Transaction ===")
    
    conf_tx = ConfidentialTransactions()
    amount = 100000000
    blinding_factor = get_random_bytes(32)
    
    # Generate proof
    proof = conf_tx.generate_range_proof(amount, blinding_factor)
    print(f"Generated proof with commitment: {proof.public_parameters['commitment'][:16]}...")
    
    # Debug verification
    print("\nStep-by-step verification:")
    
    # Check proof type
    print(f"1. Proof type check: {proof.proof_type == 'confidential'}")
    
    # Check proof size
    from core.privacy import CONFIDENTIAL_PROOF_SIZE
    print(f"2. Proof size check: {len(proof.proof_data)} == {CONFIDENTIAL_PROOF_SIZE}")
    
    # Check verification key
    commitment = bytes.fromhex(proof.public_parameters['commitment'])
    min_value = proof.public_parameters['min_value']
    max_value = proof.public_parameters['max_value']
    
    expected_verification_key = conf_tx.hash_function.new(
        commitment + proof.proof_data + struct.pack('<QQ', min_value, max_value)
    ).digest()
    
    print(f"3. Verification key check: {expected_verification_key == proof.verification_key}")
    
    # Check bulletproof structure
    if len(proof.proof_data) >= 64:
        proof_commitment = proof.proof_data[:32]
        print(f"4. Bulletproof commitment check: {proof_commitment == commitment}")
        
        # Check proof hash
        if len(proof.proof_data) >= 32:
            expected_hash = conf_tx.hash_function.new(proof.proof_data[:-32]).digest()
            actual_hash = proof.proof_data[-32:]
            print(f"5. Proof hash check: {expected_hash == actual_hash}")
    
    return conf_tx.verify_range_proof(proof)

def main():
    """Run debug tests"""
    print("Privacy Implementation Debug")
    print("=" * 30)
    
    try:
        print("zk-STARK result:", debug_zk_stark())
        print("Ring signature result:", debug_ring_signature())
        print("Confidential transaction result:", debug_confidential_tx())
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()