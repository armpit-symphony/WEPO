#!/usr/bin/env python3
"""
WEPO Transaction Validation Fixes Test
This script tests the specific fixes implemented for transaction validation:
1. Insufficient balance rejection
2. Zero amount rejection
3. Invalid address rejection
"""

import requests
import json
import time
import uuid
import os
import sys
from datetime import datetime
import random
import string

# Get the backend URL from the frontend .env file
def get_backend_url():
    with open('/app/frontend/.env', 'r') as f:
        for line in f:
            if line.startswith('REACT_APP_BACKEND_URL='):
                return line.strip().split('=')[1].strip('"\'')
    return None

BACKEND_URL = get_backend_url()
if not BACKEND_URL:
    print("Error: Could not find REACT_APP_BACKEND_URL in frontend/.env")
    sys.exit(1)

API_URL = f"{BACKEND_URL}/api"
print(f"Testing backend API at: {API_URL}")

def generate_random_username():
    """Generate a random username for testing"""
    return f"test_user_{uuid.uuid4().hex[:8]}"

def generate_random_address():
    """Generate a random WEPO address for testing"""
    address_hash = ''.join(random.choices(string.hexdigits, k=32)).lower()
    return f"wepo1{address_hash}"

def generate_encrypted_key():
    """Generate a mock encrypted private key"""
    return f"encrypted_{uuid.uuid4().hex}"

def create_wallet():
    """Create a new wallet and return its details"""
    username = generate_random_username()
    address = generate_random_address()
    encrypted_private_key = generate_encrypted_key()
    
    wallet_data = {
        "username": username,
        "address": address,
        "encrypted_private_key": encrypted_private_key
    }
    
    response = requests.post(f"{API_URL}/wallet/create", json=wallet_data)
    if response.status_code == 200:
        return wallet_data
    else:
        print(f"Failed to create wallet: {response.status_code} - {response.text}")
        return None

def send_transaction(from_address, to_address, amount):
    """Send a transaction"""
    tx_data = {
        "from_address": from_address,
        "to_address": to_address,
        "amount": amount,
        "password_hash": "test_password_hash"  # Simplified for testing
    }
    
    response = requests.post(f"{API_URL}/transaction/send", json=tx_data)
    if response.status_code == 200:
        return response.json()
    else:
        return {"status": "failed", "error": response.text if response.status_code != 500 else "Server error", "response_code": response.status_code}

def test_transaction_validation():
    """Test transaction validation fixes"""
    print("\n[TEST] Transaction Validation Fixes")
    print("  Testing validation for insufficient balance, zero amounts, and invalid addresses")
    
    # Create test wallets
    sender_wallet = create_wallet()
    recipient_wallet = create_wallet()
    
    if not sender_wallet or not recipient_wallet:
        print("  ✗ Failed to create test wallets")
        return False
    
    print(f"  ✓ Created sender wallet: {sender_wallet['address']}")
    print(f"  ✓ Created recipient wallet: {recipient_wallet['address']}")
    
    # Test Case 1: Insufficient balance transaction
    print("\n  Test Case 1: Insufficient balance transaction")
    tx_insufficient = send_transaction(sender_wallet['address'], recipient_wallet['address'], 100.0)
    
    if tx_insufficient.get("status") == "failed" or "error" in tx_insufficient:
        print(f"  ✓ Insufficient balance transaction correctly rejected")
        print(f"  ✓ Error message: {tx_insufficient.get('error', 'Unknown error')}")
        insufficient_test_passed = True
    else:
        print(f"  ✗ Insufficient balance transaction was accepted")
        insufficient_test_passed = False
    
    # Test Case 2: Zero amount transaction
    print("\n  Test Case 2: Zero amount transaction")
    tx_zero = send_transaction(sender_wallet['address'], recipient_wallet['address'], 0.0)
    
    if tx_zero.get("status") == "failed" or "error" in tx_zero:
        print(f"  ✓ Zero amount transaction correctly rejected")
        print(f"  ✓ Error message: {tx_zero.get('error', 'Unknown error')}")
        zero_test_passed = True
    else:
        print(f"  ✗ Zero amount transaction was accepted")
        zero_test_passed = False
    
    # Test Case 3: Invalid recipient address
    print("\n  Test Case 3: Invalid recipient address")
    tx_invalid = send_transaction(sender_wallet['address'], "invalid_address", 1.0)
    
    if tx_invalid.get("status") == "failed" or "error" in tx_invalid:
        print(f"  ✓ Invalid recipient address transaction correctly rejected")
        print(f"  ✓ Error message: {tx_invalid.get('error', 'Unknown error')}")
        invalid_test_passed = True
    else:
        print(f"  ✗ Invalid recipient address transaction was accepted")
        invalid_test_passed = False
    
    # Overall transaction validation test result
    passed = insufficient_test_passed and zero_test_passed and invalid_test_passed
    
    if passed:
        print("\n✅ Transaction Validation Fixes: PASSED")
        print("  All transaction validation tests passed successfully.")
        print("  The system correctly rejects:")
        print("  - Transactions with insufficient balance")
        print("  - Transactions with zero amount")
        print("  - Transactions with invalid addresses")
    else:
        print("\n❌ Transaction Validation Fixes: FAILED")
        print("  Some transaction validation tests failed.")
        if not insufficient_test_passed:
            print("  - System does not reject transactions with insufficient balance")
        if not zero_test_passed:
            print("  - System does not reject transactions with zero amount")
        if not invalid_test_passed:
            print("  - System does not reject transactions with invalid addresses")
    
    return passed

if __name__ == "__main__":
    success = test_transaction_validation()
    sys.exit(0 if success else 1)