#!/usr/bin/env python3
"""
WEPO Blockchain Critical Fixes Test
This script tests the critical fixes implemented for WEPO blockchain:
1. UTXO Balance Calculation - Fixed balance management and transaction flow
2. Multi-wallet Transaction Flow - Improved transaction reliability between wallets
3. API Error Handling - Enhanced error responses and validation
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

# Test results tracking
test_results = {
    "total": 0,
    "passed": 0,
    "failed": 0,
    "tests": []
}

def log_test(name, passed, response=None, error=None):
    """Log test results"""
    status = "PASSED" if passed else "FAILED"
    print(f"[{status}] {name}")
    
    if not passed and response:
        print(f"  Response: {response.status_code} - {response.text}")
    if not passed and error:
        print(f"  Error: {error}")
    
    test_results["total"] += 1
    if passed:
        test_results["passed"] += 1
    else:
        test_results["failed"] += 1
    
    test_results["tests"].append({
        "name": name,
        "passed": passed,
        "timestamp": datetime.now().isoformat()
    })

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
    
    print(f"Creating wallet with username: {username}, address: {address}")
    response = requests.post(f"{API_URL}/wallet/create", json=wallet_data)
    
    if response.status_code == 200:
        print(f"Successfully created wallet: {username} with address {address}")
        return wallet_data
    else:
        print(f"Failed to create wallet: {response.status_code} - {response.text}")
        return None

def fund_wallet(address, amount=100.0):
    """Fund a wallet using test mining endpoint"""
    print(f"Funding wallet {address} with mining reward")
    response = requests.post(f"{API_URL}/test/mine-block", json={"miner_address": address})
    
    if response.status_code == 200:
        data = response.json()
        print(f"Successfully mined block with reward to {address}")
        print(f"Mining reward: {data.get('reward', 'unknown')} WEPO")
        return True
    else:
        print(f"Failed to fund wallet: {response.status_code} - {response.text}")
        return False

def get_wallet_balance(address):
    """Get wallet balance"""
    print(f"Getting balance for wallet: {address}")
    response = requests.get(f"{API_URL}/wallet/{address}")
    
    if response.status_code == 200:
        data = response.json()
        balance = data.get("balance", 0.0)
        print(f"Wallet balance: {balance} WEPO")
        return balance
    else:
        print(f"Failed to get wallet balance: {response.status_code} - {response.text}")
        return None

def send_transaction(from_address, to_address, amount):
    """Send a transaction"""
    tx_data = {
        "from_address": from_address,
        "to_address": to_address,
        "amount": amount,
        "password_hash": "test_password_hash"  # Simplified for testing
    }
    
    print(f"Sending {amount} WEPO from {from_address} to {to_address}")
    response = requests.post(f"{API_URL}/transaction/send", json=tx_data)
    
    if response.status_code == 200:
        data = response.json()
        print(f"Transaction submitted with ID: {data.get('transaction_id', 'unknown')}")
        return data
    else:
        print(f"Transaction failed: {response.status_code} - {response.text}")
        return {"status_code": response.status_code, "error": response.text}

def mine_block():
    """Mine a block to confirm transactions"""
    print("Mining a block to confirm transactions")
    response = requests.post(f"{API_URL}/test/mine-block", json={"miner_address": "wepo1test000000000000000000000000000"})
    
    if response.status_code == 200:
        data = response.json()
        print(f"Successfully mined block at height: {data.get('block_height', 'unknown')}")
        return True
    else:
        print(f"Failed to mine block: {response.status_code} - {response.text}")
        return False

def test_utxo_balance_management():
    """Test UTXO Balance Management"""
    print("\n" + "="*80)
    print("TEST 1: UTXO BALANCE MANAGEMENT")
    print("="*80)
    
    # 1. Create two wallets
    print("\nStep 1: Creating wallets")
    wallet1 = create_wallet()
    wallet2 = create_wallet()
    
    if not wallet1 or not wallet2:
        log_test("UTXO Balance Management - Wallet Creation", False, error="Failed to create wallets")
        return False
    
    log_test("UTXO Balance Management - Wallet Creation", True)
    
    # 2. Fund wallet1
    print("\nStep 2: Funding wallet1")
    if not fund_wallet(wallet1["address"]):
        log_test("UTXO Balance Management - Wallet Funding", False, error="Failed to fund wallet")
        return False
    
    # Wait for blockchain to process
    time.sleep(1)
    
    # 3. Verify wallet1 balance
    print("\nStep 3: Verifying wallet1 balance")
    balance1 = get_wallet_balance(wallet1["address"])
    
    if balance1 is None or balance1 <= 0:
        log_test("UTXO Balance Management - Initial Balance", False, error=f"Expected positive balance, got {balance1}")
        return False
    
    log_test("UTXO Balance Management - Initial Balance", True)
    
    # 4. Send transaction from wallet1 to wallet2
    print("\nStep 4: Sending transaction from wallet1 to wallet2")
    send_amount = balance1 / 2  # Send half the balance
    tx_result = send_transaction(wallet1["address"], wallet2["address"], send_amount)
    
    if "status_code" in tx_result and tx_result["status_code"] != 200:
        log_test("UTXO Balance Management - Transaction Sending", False, error=f"Transaction failed: {tx_result.get('error', 'Unknown error')}")
        return False
    
    log_test("UTXO Balance Management - Transaction Sending", True)
    
    # 5. Verify wallet1 still has balance (change)
    print("\nStep 5: Verifying wallet1 still has balance (change)")
    new_balance1 = get_wallet_balance(wallet1["address"])
    
    # The key test: balance should not be 0 after sending
    if new_balance1 is None:
        log_test("UTXO Balance Management - Change Verification", False, error="Failed to get updated balance")
        return False
    
    if new_balance1 == 0:
        log_test("UTXO Balance Management - Change Verification", False, error="Balance went to 0 after transaction (UTXO management issue)")
        return False
    
    expected_balance = balance1 - send_amount
    balance_diff = abs(new_balance1 - expected_balance)
    
    # Allow for small difference due to fees
    if balance_diff > 1.0:
        log_test("UTXO Balance Management - Change Verification", False, error=f"Expected ~{expected_balance} WEPO, got {new_balance1} WEPO")
        return False
    
    log_test("UTXO Balance Management - Change Verification", True)
    
    # 6. Mine block to confirm transaction
    print("\nStep 6: Mining block to confirm transaction")
    if not mine_block():
        log_test("UTXO Balance Management - Block Mining", False, error="Failed to mine block")
        return False
    
    log_test("UTXO Balance Management - Block Mining", True)
    
    # Wait for blockchain to process
    time.sleep(1)
    
    # 7. Verify both balances after confirmation
    print("\nStep 7: Verifying both balances after confirmation")
    final_balance1 = get_wallet_balance(wallet1["address"])
    final_balance2 = get_wallet_balance(wallet2["address"])
    
    if final_balance1 is None or final_balance2 is None:
        log_test("UTXO Balance Management - Final Balance Check", False, error="Failed to get final balances")
        return False
    
    # Verify wallet1 balance is still correct (not 0)
    if final_balance1 == 0:
        log_test("UTXO Balance Management - Final Balance Check", False, error="Wallet1 balance went to 0 after confirmation")
        return False
    
    # Verify wallet2 received the funds
    if final_balance2 < send_amount - 1.0:  # Allow for fees
        log_test("UTXO Balance Management - Final Balance Check", False, error=f"Wallet2 balance ({final_balance2}) is less than expected ({send_amount})")
        return False
    
    log_test("UTXO Balance Management - Final Balance Check", True)
    
    print("\nUTXO Balance Management Test Summary:")
    print(f"- Wallet1 initial balance: {balance1} WEPO")
    print(f"- Sent {send_amount} WEPO to Wallet2")
    print(f"- Wallet1 balance after sending: {new_balance1} WEPO")
    print(f"- Wallet1 final balance after confirmation: {final_balance1} WEPO")
    print(f"- Wallet2 final balance after confirmation: {final_balance2} WEPO")
    
    return True

def test_multi_wallet_transaction_chain():
    """Test Multi-wallet Transaction Chain"""
    print("\n" + "="*80)
    print("TEST 2: MULTI-WALLET TRANSACTION CHAIN")
    print("="*80)
    
    # 1. Create 3 wallets (A, B, C)
    print("\nStep 1: Creating 3 wallets (A, B, C)")
    wallet_a = create_wallet()
    wallet_b = create_wallet()
    wallet_c = create_wallet()
    
    if not wallet_a or not wallet_b or not wallet_c:
        log_test("Multi-wallet Transaction Chain - Wallet Creation", False, error="Failed to create wallets")
        return False
    
    log_test("Multi-wallet Transaction Chain - Wallet Creation", True)
    
    # 2. Fund wallet A
    print("\nStep 2: Funding wallet A")
    if not fund_wallet(wallet_a["address"]):
        log_test("Multi-wallet Transaction Chain - Wallet Funding", False, error="Failed to fund wallet A")
        return False
    
    # Mine another block to ensure sufficient funds
    mine_block()
    
    # Wait for blockchain to process
    time.sleep(1)
    
    # 3. Check wallet A balance
    print("\nStep 3: Checking wallet A balance")
    balance_a = get_wallet_balance(wallet_a["address"])
    
    if balance_a is None or balance_a <= 0:
        log_test("Multi-wallet Transaction Chain - Initial Balance", False, error=f"Expected positive balance for wallet A, got {balance_a}")
        return False
    
    log_test("Multi-wallet Transaction Chain - Initial Balance", True)
    
    # 4. Send A→B (25 WEPO)
    print("\nStep 4: Sending A→B (25 WEPO)")
    tx_result_ab = send_transaction(wallet_a["address"], wallet_b["address"], 25.0)
    
    if "status_code" in tx_result_ab and tx_result_ab["status_code"] != 200:
        log_test("Multi-wallet Transaction Chain - A→B Transaction", False, error=f"Transaction failed: {tx_result_ab.get('error', 'Unknown error')}")
        return False
    
    log_test("Multi-wallet Transaction Chain - A→B Transaction", True)
    
    # 5. Check A has 75 remaining (approximately)
    print("\nStep 5: Checking A has ~75 WEPO remaining")
    new_balance_a = get_wallet_balance(wallet_a["address"])
    
    if new_balance_a is None:
        log_test("Multi-wallet Transaction Chain - A Balance After First Tx", False, error="Failed to get updated balance for wallet A")
        return False
    
    expected_balance = balance_a - 25.0
    balance_diff = abs(new_balance_a - expected_balance)
    
    # Allow for small difference due to fees
    if balance_diff > 1.0:
        log_test("Multi-wallet Transaction Chain - A Balance After First Tx", False, error=f"Expected ~{expected_balance} WEPO, got {new_balance_a} WEPO")
        return False
    
    log_test("Multi-wallet Transaction Chain - A Balance After First Tx", True)
    
    # 6. Send A→C (25 WEPO)
    print("\nStep 6: Sending A→C (25 WEPO)")
    tx_result_ac = send_transaction(wallet_a["address"], wallet_c["address"], 25.0)
    
    if "status_code" in tx_result_ac and tx_result_ac["status_code"] != 200:
        log_test("Multi-wallet Transaction Chain - A→C Transaction", False, error=f"Transaction failed: {tx_result_ac.get('error', 'Unknown error')}")
        return False
    
    log_test("Multi-wallet Transaction Chain - A→C Transaction", True)
    
    # 7. Check A has 50 remaining (approximately)
    print("\nStep 7: Checking A has ~50 WEPO remaining")
    new_balance_a2 = get_wallet_balance(wallet_a["address"])
    
    if new_balance_a2 is None:
        log_test("Multi-wallet Transaction Chain - A Balance After Second Tx", False, error="Failed to get updated balance for wallet A")
        return False
    
    expected_balance2 = new_balance_a - 25.0
    balance_diff2 = abs(new_balance_a2 - expected_balance2)
    
    # Allow for small difference due to fees
    if balance_diff2 > 1.0:
        log_test("Multi-wallet Transaction Chain - A Balance After Second Tx", False, error=f"Expected ~{expected_balance2} WEPO, got {new_balance_a2} WEPO")
        return False
    
    log_test("Multi-wallet Transaction Chain - A Balance After Second Tx", True)
    
    # 8. Mine block and verify all balances
    print("\nStep 8: Mining block and verifying all balances")
    if not mine_block():
        log_test("Multi-wallet Transaction Chain - Block Mining", False, error="Failed to mine block")
        return False
    
    # Wait for blockchain to process
    time.sleep(1)
    
    # Check all balances
    final_balance_a = get_wallet_balance(wallet_a["address"])
    final_balance_b = get_wallet_balance(wallet_b["address"])
    final_balance_c = get_wallet_balance(wallet_c["address"])
    
    if final_balance_a is None or final_balance_b is None or final_balance_c is None:
        log_test("Multi-wallet Transaction Chain - Final Balances", False, error="Failed to get final balances")
        return False
    
    # Verify wallet B received funds
    if final_balance_b < 24.0:  # Allow for fees
        log_test("Multi-wallet Transaction Chain - Final Balances", False, error=f"Wallet B balance ({final_balance_b}) is less than expected (~25)")
        return False
    
    # Verify wallet C received funds
    if final_balance_c < 24.0:  # Allow for fees
        log_test("Multi-wallet Transaction Chain - Final Balances", False, error=f"Wallet C balance ({final_balance_c}) is less than expected (~25)")
        return False
    
    log_test("Multi-wallet Transaction Chain - Final Balances", True)
    
    # 9. Send B→C (10 WEPO) to test transaction chains
    print("\nStep 9: Sending B→C (10 WEPO) to test transaction chains")
    tx_result_bc = send_transaction(wallet_b["address"], wallet_c["address"], 10.0)
    
    if "status_code" in tx_result_bc and tx_result_bc["status_code"] != 200:
        log_test("Multi-wallet Transaction Chain - B→C Transaction", False, error=f"Transaction failed: {tx_result_bc.get('error', 'Unknown error')}")
        return False
    
    log_test("Multi-wallet Transaction Chain - B→C Transaction", True)
    
    # 10. Mine block and verify final balances
    print("\nStep 10: Mining block and verifying final balances")
    if not mine_block():
        log_test("Multi-wallet Transaction Chain - Final Block Mining", False, error="Failed to mine final block")
        return False
    
    # Wait for blockchain to process
    time.sleep(1)
    
    # Check final balances
    final_balance_b2 = get_wallet_balance(wallet_b["address"])
    final_balance_c2 = get_wallet_balance(wallet_c["address"])
    
    if final_balance_b2 is None or final_balance_c2 is None:
        log_test("Multi-wallet Transaction Chain - Chain Completion", False, error="Failed to get final balances after B→C transaction")
        return False
    
    # Verify wallet B sent funds
    expected_b_balance = final_balance_b - 10.0
    if abs(final_balance_b2 - expected_b_balance) > 1.0:
        log_test("Multi-wallet Transaction Chain - Chain Completion", False, error=f"Wallet B balance ({final_balance_b2}) doesn't reflect B→C transaction")
        return False
    
    # Verify wallet C received additional funds
    expected_c_balance = final_balance_c + 10.0
    if abs(final_balance_c2 - expected_c_balance) > 1.0:
        log_test("Multi-wallet Transaction Chain - Chain Completion", False, error=f"Wallet C balance ({final_balance_c2}) doesn't reflect B→C transaction")
        return False
    
    log_test("Multi-wallet Transaction Chain - Chain Completion", True)
    
    print("\nMulti-wallet Transaction Chain Test Summary:")
    print(f"- Wallet A initial balance: {balance_a} WEPO")
    print(f"- After A→B (25 WEPO): A={final_balance_a} WEPO, B={final_balance_b} WEPO")
    print(f"- After A→C (25 WEPO): C={final_balance_c} WEPO")
    print(f"- After B→C (10 WEPO): B={final_balance_b2} WEPO, C={final_balance_c2} WEPO")
    
    return True

def test_error_handling():
    """Test Error Handling Validation"""
    print("\n" + "="*80)
    print("TEST 3: ERROR HANDLING VALIDATION")
    print("="*80)
    
    # Create a test wallet for error handling tests
    print("\nCreating test wallet for error handling tests")
    test_wallet = create_wallet()
    
    if not test_wallet:
        log_test("Error Handling - Setup", False, error="Failed to create test wallet")
        return False
    
    # Fund the wallet
    if not fund_wallet(test_wallet["address"]):
        log_test("Error Handling - Setup", False, error="Failed to fund test wallet")
        return False
    
    # Mine a block to ensure funds are available
    mine_block()
    time.sleep(1)
    
    # Get wallet balance
    balance = get_wallet_balance(test_wallet["address"])
    if balance is None or balance <= 0:
        log_test("Error Handling - Setup", False, error="Failed to get test wallet balance or balance is 0")
        return False
    
    log_test("Error Handling - Setup", True)
    
    # 1. Test invalid wallet address (should return 404)
    print("\nTest 1: Invalid wallet address (should return 404)")
    invalid_address = "wepo1invalid000000000000000000000000"
    
    # Try to get wallet info
    response = requests.get(f"{API_URL}/wallet/{invalid_address}")
    
    if response.status_code == 404:
        log_test("Error Handling - Invalid Address", True)
        print(f"  ✓ Correctly returned 404 for invalid wallet address")
    else:
        log_test("Error Handling - Invalid Address", False, response)
        print(f"  ✗ Expected 404, got {response.status_code}")
    
    # 2. Test insufficient balance (should return 400)
    print("\nTest 2: Insufficient balance (should return 400)")
    
    # Try to send more than available
    tx_data = {
        "from_address": test_wallet["address"],
        "to_address": generate_random_address(),
        "amount": balance + 100.0,  # More than available
        "password_hash": "test_password_hash"
    }
    
    response = requests.post(f"{API_URL}/transaction/send", json=tx_data)
    
    if response.status_code == 400 and "insufficient" in response.text.lower():
        log_test("Error Handling - Insufficient Balance", True)
        print(f"  ✓ Correctly returned 400 for insufficient balance")
    else:
        log_test("Error Handling - Insufficient Balance", False, response)
        print(f"  ✗ Expected 400 with 'insufficient balance' message, got {response.status_code}")
    
    # 3. Test zero amount (should return 400)
    print("\nTest 3: Zero amount (should return 400)")
    
    # Try to send zero amount
    tx_data = {
        "from_address": test_wallet["address"],
        "to_address": generate_random_address(),
        "amount": 0.0,
        "password_hash": "test_password_hash"
    }
    
    response = requests.post(f"{API_URL}/transaction/send", json=tx_data)
    
    if response.status_code == 400:
        log_test("Error Handling - Zero Amount", True)
        print(f"  ✓ Correctly returned 400 for zero amount")
    else:
        log_test("Error Handling - Zero Amount", False, response)
        print(f"  ✗ Expected 400, got {response.status_code}")
    
    # 4. Test invalid address format (should return 400)
    print("\nTest 4: Invalid address format (should return 400)")
    
    # Try to send to invalid address format
    tx_data = {
        "from_address": test_wallet["address"],
        "to_address": "invalid-address-format",
        "amount": 1.0,
        "password_hash": "test_password_hash"
    }
    
    response = requests.post(f"{API_URL}/transaction/send", json=tx_data)
    
    if response.status_code == 400:
        log_test("Error Handling - Invalid Address Format", True)
        print(f"  ✓ Correctly returned 400 for invalid address format")
    else:
        log_test("Error Handling - Invalid Address Format", False, response)
        print(f"  ✗ Expected 400, got {response.status_code}")
    
    return True

def run_tests():
    """Run all tests for critical fixes"""
    print("\n" + "="*80)
    print("WEPO BLOCKCHAIN CRITICAL FIXES ASSESSMENT")
    print("="*80)
    print("Testing fixes for UTXO balance calculation, multi-wallet transaction flow, and error handling")
    print("="*80 + "\n")
    
    # Test 1: UTXO Balance Management
    test_utxo_balance_management()
    
    # Test 2: Multi-wallet Transaction Chain
    test_multi_wallet_transaction_chain()
    
    # Test 3: Error Handling Validation
    test_error_handling()
    
    # Print summary
    print("\n" + "="*80)
    print("WEPO BLOCKCHAIN CRITICAL FIXES ASSESSMENT SUMMARY")
    print("="*80)
    print(f"Total tests:    {test_results['total']}")
    print(f"Passed:         {test_results['passed']}")
    print(f"Failed:         {test_results['failed']}")
    print(f"Success rate:   {(test_results['passed'] / test_results['total'] * 100):.1f}%")
    
    if test_results["failed"] > 0:
        print("\nFailed tests:")
        for test in test_results["tests"]:
            if not test["passed"]:
                print(f"- {test['name']}")
    
    print("\nKEY FINDINGS:")
    print("1. UTXO Balance Calculation: " + 
          ("✅ Fixed" if all(t["name"].startswith("UTXO Balance Management") and t["passed"] for t in test_results["tests"]) 
           else "❌ Issues remain"))
    
    print("2. Multi-wallet Transaction Flow: " + 
          ("✅ Reliable" if all(t["name"].startswith("Multi-wallet Transaction Chain") and t["passed"] for t in test_results["tests"]) 
           else "❌ Issues remain"))
    
    print("3. Error Handling: " + 
          ("✅ Proper validation" if all(t["name"].startswith("Error Handling") and t["passed"] for t in test_results["tests"]) 
           else "❌ Issues remain"))
    
    print("\nCRITICAL FIXES STATUS:")
    print("✅ Balance no longer goes to 0 after transactions" if any(t["name"] == "UTXO Balance Management - Change Verification" and t["passed"] for t in test_results["tests"]) else "❌ Balance still goes to 0 after transactions")
    print("✅ Multi-wallet transactions work end-to-end" if any(t["name"] == "Multi-wallet Transaction Chain - Chain Completion" and t["passed"] for t in test_results["tests"]) else "❌ Multi-wallet transaction chains still have issues")
    print("✅ Proper error responses for invalid requests" if all(t["name"].startswith("Error Handling -") and t["name"] != "Error Handling - Setup" and t["passed"] for t in test_results["tests"]) else "❌ Error handling still needs improvement")
    
    print("="*80)
    
    return test_results["failed"] == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)