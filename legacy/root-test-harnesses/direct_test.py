#!/usr/bin/env python3
"""
WEPO Blockchain Critical Fixes Test - Direct Approach
This script tests the critical fixes implemented for WEPO blockchain using direct API calls
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

def generate_random_address():
    """Generate a random WEPO address for testing"""
    address_hash = ''.join(random.choices(string.hexdigits, k=32)).lower()
    return f"wepo1{address_hash}"

def test_utxo_balance_management():
    """Test UTXO Balance Management"""
    print("\n" + "="*80)
    print("TEST 1: UTXO BALANCE MANAGEMENT")
    print("="*80)
    
    # 1. Create a test transaction from sender to recipient
    sender_address = generate_random_address()
    recipient_address = generate_random_address()
    
    print(f"Sender address: {sender_address}")
    print(f"Recipient address: {recipient_address}")
    
    # 2. Try to fund the sender using the test/fund-wallet endpoint
    print("\nTrying to fund sender using test/fund-wallet endpoint")
    fund_data = {
        "address": sender_address,
        "amount": 100.0
    }
    
    try:
        fund_response = requests.post(f"{API_URL}/test/fund-wallet", json=fund_data)
        print(f"Fund response: {fund_response.status_code}")
        if fund_response.status_code == 200:
            print(f"Fund response data: {fund_response.json()}")
    except Exception as e:
        print(f"Error funding wallet: {str(e)}")
    
    # 3. Check sender balance
    print("\nChecking sender balance")
    try:
        balance_response = requests.get(f"{API_URL}/wallet/{sender_address}")
        print(f"Balance response: {balance_response.status_code}")
        if balance_response.status_code == 200:
            balance_data = balance_response.json()
            print(f"Sender balance: {balance_data.get('balance', 0.0)} WEPO")
    except Exception as e:
        print(f"Error checking balance: {str(e)}")
    
    # 4. Try to send a transaction
    print("\nTrying to send a transaction")
    tx_data = {
        "from_address": sender_address,
        "to_address": recipient_address,
        "amount": 25.0,
        "password_hash": "test_password_hash"
    }
    
    try:
        tx_response = requests.post(f"{API_URL}/transaction/send", json=tx_data)
        print(f"Transaction response: {tx_response.status_code}")
        if tx_response.status_code == 200:
            print(f"Transaction response data: {tx_response.json()}")
    except Exception as e:
        print(f"Error sending transaction: {str(e)}")
    
    # 5. Check sender balance again
    print("\nChecking sender balance after transaction")
    try:
        balance_response = requests.get(f"{API_URL}/wallet/{sender_address}")
        print(f"Balance response: {balance_response.status_code}")
        if balance_response.status_code == 200:
            balance_data = balance_response.json()
            print(f"Sender balance after transaction: {balance_data.get('balance', 0.0)} WEPO")
    except Exception as e:
        print(f"Error checking balance: {str(e)}")
    
    # 6. Mine a block
    print("\nMining a block")
    try:
        mine_response = requests.post(f"{API_URL}/test/mine-block", json={"miner_address": "wepo1test000000000000000000000000000"})
        print(f"Mine response: {mine_response.status_code}")
        if mine_response.status_code == 200:
            print(f"Mine response data: {mine_response.json()}")
    except Exception as e:
        print(f"Error mining block: {str(e)}")
    
    # 7. Check both balances
    print("\nChecking both balances after mining")
    try:
        sender_balance_response = requests.get(f"{API_URL}/wallet/{sender_address}")
        print(f"Sender balance response: {sender_balance_response.status_code}")
        if sender_balance_response.status_code == 200:
            sender_balance_data = sender_balance_response.json()
            print(f"Sender final balance: {sender_balance_data.get('balance', 0.0)} WEPO")
        
        recipient_balance_response = requests.get(f"{API_URL}/wallet/{recipient_address}")
        print(f"Recipient balance response: {recipient_balance_response.status_code}")
        if recipient_balance_response.status_code == 200:
            recipient_balance_data = recipient_balance_response.json()
            print(f"Recipient final balance: {recipient_balance_data.get('balance', 0.0)} WEPO")
    except Exception as e:
        print(f"Error checking final balances: {str(e)}")

def test_error_handling():
    """Test Error Handling Validation"""
    print("\n" + "="*80)
    print("TEST 2: ERROR HANDLING VALIDATION")
    print("="*80)
    
    # 1. Test invalid wallet address
    print("\nTest 1: Invalid wallet address (should return 404)")
    invalid_address = "invalid_address_format"
    
    try:
        response = requests.get(f"{API_URL}/wallet/{invalid_address}")
        print(f"Response: {response.status_code}")
        print(f"Response text: {response.text}")
        
        if response.status_code == 404 or response.status_code == 400:
            print("✅ Correctly returned error for invalid wallet address")
        else:
            print("❌ Expected 404 or 400 error")
    except Exception as e:
        print(f"Error testing invalid address: {str(e)}")
    
    # 2. Test insufficient balance
    print("\nTest 2: Insufficient balance (should return 400)")
    sender_address = generate_random_address()
    recipient_address = generate_random_address()
    
    tx_data = {
        "from_address": sender_address,
        "to_address": recipient_address,
        "amount": 1000.0,  # Large amount with no funds
        "password_hash": "test_password_hash"
    }
    
    try:
        response = requests.post(f"{API_URL}/transaction/send", json=tx_data)
        print(f"Response: {response.status_code}")
        print(f"Response text: {response.text}")
        
        if response.status_code == 400 and "insufficient" in response.text.lower():
            print("✅ Correctly returned 400 for insufficient balance")
        else:
            print("❌ Expected 400 with 'insufficient balance' message")
    except Exception as e:
        print(f"Error testing insufficient balance: {str(e)}")
    
    # 3. Test zero amount
    print("\nTest 3: Zero amount (should return 400)")
    
    tx_data = {
        "from_address": sender_address,
        "to_address": recipient_address,
        "amount": 0.0,
        "password_hash": "test_password_hash"
    }
    
    try:
        response = requests.post(f"{API_URL}/transaction/send", json=tx_data)
        print(f"Response: {response.status_code}")
        print(f"Response text: {response.text}")
        
        if response.status_code == 400:
            print("✅ Correctly returned 400 for zero amount")
        else:
            print("❌ Expected 400 error")
    except Exception as e:
        print(f"Error testing zero amount: {str(e)}")
    
    # 4. Test invalid address format
    print("\nTest 4: Invalid address format (should return 400)")
    
    tx_data = {
        "from_address": sender_address,
        "to_address": "invalid-address-format",
        "amount": 1.0,
        "password_hash": "test_password_hash"
    }
    
    try:
        response = requests.post(f"{API_URL}/transaction/send", json=tx_data)
        print(f"Response: {response.status_code}")
        print(f"Response text: {response.text}")
        
        if response.status_code == 400:
            print("✅ Correctly returned 400 for invalid address format")
        else:
            print("❌ Expected 400 error")
    except Exception as e:
        print(f"Error testing invalid address format: {str(e)}")

def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("WEPO BLOCKCHAIN CRITICAL FIXES DIRECT TEST")
    print("="*80)
    
    # Test 1: UTXO Balance Management
    test_utxo_balance_management()
    
    # Test 2: Error Handling Validation
    test_error_handling()
    
    print("\n" + "="*80)
    print("DIRECT TEST COMPLETE")
    print("="*80)

if __name__ == "__main__":
    main()