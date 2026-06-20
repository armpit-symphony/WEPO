#!/usr/bin/env python3
"""
WEPO Blockchain Stress Test - Simplified Version

This script performs a simplified stress test of the WEPO blockchain system,
focusing on ensuring wallets are properly funded before running the tests.
"""

import requests
import json
import time
import uuid
import os
import sys
import random
import string
from datetime import datetime

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
    
    print(f"  Creating wallet with username: {username}, address: {address}")
    response = requests.post(f"{API_URL}/wallet/create", json=wallet_data)
    
    if response.status_code == 200:
        data = response.json()
        print(f"  Wallet creation response: {json.dumps(data, indent=2)}")
        
        if data.get("success") == True:
            wallet_data["response"] = data
            print(f"  ✓ Successfully created wallet: {username} with address {address}")
            return wallet_data
    
    print(f"  ✗ Failed to create wallet: {response.status_code} - {response.text}")
    return None

def mine_block(miner_address=None):
    """Mine a block and return the block details"""
    if not miner_address:
        miner_address = "wepo1test000000000000000000000000000"
    
    mine_data = {"miner_address": miner_address}
    
    print(f"  Mining block with miner address: {miner_address}")
    response = requests.post(f"{API_URL}/test/mine-block", json=mine_data)
    
    if response.status_code == 200:
        data = response.json()
        print(f"  Mining response: {json.dumps(data, indent=2)}")
        return data, response
    else:
        print(f"  ✗ Failed to mine block: {response.status_code} - {response.text}")
        return None, response

def get_wallet_balance(address):
    """Get wallet balance"""
    print(f"  Getting balance for wallet: {address}")
    response = requests.get(f"{API_URL}/wallet/{address}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"  Wallet info: {json.dumps(data, indent=2)}")
        return data.get("balance", 0.0)
    else:
        print(f"  ✗ Failed to get wallet balance: {response.status_code} - {response.text}")
        return 0.0

def send_transaction(from_address, to_address, amount):
    """Send a transaction and return the transaction ID"""
    tx_data = {
        "from_address": from_address,
        "to_address": to_address,
        "amount": amount,
        "password_hash": "test_password_hash"  # Simplified for testing
    }
    
    print(f"  Sending {amount} WEPO from {from_address} to {to_address}")
    response = requests.post(f"{API_URL}/transaction/send", json=tx_data)
    
    if response.status_code == 200:
        data = response.json()
        print(f"  Transaction response: {json.dumps(data, indent=2)}")
        return data.get("transaction_id"), response
    else:
        print(f"  ✗ Failed to send transaction: {response.status_code} - {response.text}")
        return None, response

def get_network_status():
    """Get network status"""
    response = requests.get(f"{API_URL}/network/status")
    
    if response.status_code == 200:
        data = response.json()
        print(f"  Network status: {json.dumps(data, indent=2)}")
        return data
    else:
        print(f"  ✗ Failed to get network status: {response.status_code} - {response.text}")
        return None

def get_mining_info():
    """Get mining information"""
    response = requests.get(f"{API_URL}/mining/info")
    
    if response.status_code == 200:
        data = response.json()
        print(f"  Mining info: {json.dumps(data, indent=2)}")
        return data
    else:
        print(f"  ✗ Failed to get mining info: {response.status_code} - {response.text}")
        return None

def test_mempool_stress():
    """Test mempool with concurrent transactions"""
    print("\n" + "="*80)
    print("MEMPOOL STRESS TESTING")
    print("="*80)
    
    # 1. Create test wallets
    print("\n[TEST] Creating test wallets")
    wallets = []
    for i in range(5):
        wallet = create_wallet()
        if wallet:
            wallets.append(wallet)
    
    if len(wallets) < 2:
        print("  ✗ Failed to create enough test wallets")
        log_test("Mempool Stress - Wallet Creation", False, error="Failed to create enough test wallets")
        return False
    
    print(f"  ✓ Created {len(wallets)} test wallets")
    log_test("Mempool Stress - Wallet Creation", True)
    
    # 2. Mine blocks to fund wallets
    print("\n[TEST] Mining blocks to fund wallets")
    for i, wallet in enumerate(wallets):
        print(f"  Mining block {i+1} for wallet: {wallet['address']}")
        block_data, response = mine_block(wallet['address'])
        
        if block_data and block_data.get("success") == True:
            print(f"  ✓ Successfully mined block at height: {block_data.get('block_height')}")
            print(f"  ✓ Mining reward: {block_data.get('reward')} WEPO")
        else:
            print(f"  ✗ Failed to mine block for wallet: {wallet['address']}")
    
    # Wait for mining rewards to be processed
    print("  Waiting for mining rewards to be processed...")
    time.sleep(2)
    
    # 3. Check wallet balances
    print("\n[TEST] Checking wallet balances")
    funded_wallets = []
    for wallet in wallets:
        balance = get_wallet_balance(wallet['address'])
        if balance > 0:
            print(f"  ✓ Wallet {wallet['address']} has balance: {balance} WEPO")
            funded_wallets.append(wallet)
        else:
            print(f"  ✗ Wallet {wallet['address']} has zero balance")
    
    if len(funded_wallets) < 2:
        print("  ✗ Not enough funded wallets for testing")
        log_test("Mempool Stress - Wallet Funding", False, error="Not enough funded wallets")
        return False
    
    print(f"  ✓ {len(funded_wallets)}/{len(wallets)} wallets successfully funded")
    log_test("Mempool Stress - Wallet Funding", True)
    
    # 4. Generate transactions
    print("\n[TEST] Generating transactions")
    transaction_count = 10
    successful_txs = 0
    
    # Use first wallet as sender
    sender = funded_wallets[0]
    # Use second wallet as recipient
    recipient = funded_wallets[1] if len(funded_wallets) > 1 else wallets[1]
    
    for i in range(transaction_count):
        # Random amount between 0.1 and 1.0 WEPO
        amount = round(random.uniform(0.1, 1.0), 2)
        
        tx_id, response = send_transaction(sender['address'], recipient['address'], amount)
        
        if tx_id:
            successful_txs += 1
            print(f"  ✓ Transaction {i+1} successful: {tx_id}")
        else:
            print(f"  ✗ Transaction {i+1} failed")
    
    if successful_txs > 0:
        print(f"  ✓ Successfully created {successful_txs}/{transaction_count} transactions")
        log_test("Mempool Stress - Transaction Generation", True)
    else:
        print(f"  ✗ Failed to create any transactions")
        log_test("Mempool Stress - Transaction Generation", False, error="Failed to create any transactions")
        return False
    
    # 5. Check mempool
    print("\n[TEST] Checking mempool")
    mining_info = get_mining_info()
    
    if mining_info and "mempool_size" in mining_info:
        mempool_size = mining_info["mempool_size"]
        print(f"  ✓ Current mempool size: {mempool_size} transactions")
        
        if mempool_size > 0:
            print(f"  ✓ Mempool contains transactions")
            log_test("Mempool Stress - Mempool Check", True)
        else:
            print(f"  ✗ Mempool is empty despite sending transactions")
            log_test("Mempool Stress - Mempool Check", False, error="Mempool is empty")
    else:
        print(f"  ✗ Could not determine mempool size")
        log_test("Mempool Stress - Mempool Check", False, error="Could not determine mempool size")
    
    # 6. Mine a block to process transactions
    print("\n[TEST] Mining block to process transactions")
    block_data, response = mine_block(funded_wallets[0]['address'])
    
    if block_data and block_data.get("success") == True:
        print(f"  ✓ Successfully mined block at height: {block_data.get('block_height')}")
        print(f"  ✓ Transactions in block: {block_data.get('transactions', 0)}")
        log_test("Mempool Stress - Block Mining", True)
    else:
        print(f"  ✗ Failed to mine block")
        log_test("Mempool Stress - Block Mining", False, error="Failed to mine block")
    
    # 7. Check mempool after mining
    print("\n[TEST] Checking mempool after mining")
    mining_info_after = get_mining_info()
    
    if mining_info_after and "mempool_size" in mining_info_after:
        mempool_size_after = mining_info_after["mempool_size"]
        print(f"  ✓ Mempool size after mining: {mempool_size_after} transactions")
        
        if mempool_size_after < mempool_size:
            print(f"  ✓ Mempool was cleaned up after mining")
            log_test("Mempool Stress - Mempool Cleanup", True)
        else:
            print(f"  ✗ Mempool was not cleaned up after mining")
            log_test("Mempool Stress - Mempool Cleanup", False, error="Mempool was not cleaned up")
    else:
        print(f"  ✗ Could not determine mempool size after mining")
        log_test("Mempool Stress - Mempool Cleanup", False, error="Could not determine mempool size")
    
    return True

def test_utxo_management():
    """Test UTXO management with transaction chains"""
    print("\n" + "="*80)
    print("UTXO MANAGEMENT TESTING")
    print("="*80)
    
    # 1. Create test wallets
    print("\n[TEST] Creating test wallets for UTXO testing")
    wallets = []
    for i in range(4):  # A, B, C, D
        wallet = create_wallet()
        if wallet:
            wallets.append(wallet)
    
    if len(wallets) < 4:
        print("  ✗ Failed to create enough test wallets")
        log_test("UTXO Management - Wallet Creation", False, error="Failed to create enough test wallets")
        return False
    
    print(f"  ✓ Created {len(wallets)} test wallets")
    log_test("UTXO Management - Wallet Creation", True)
    
    # 2. Mine blocks to fund wallets
    print("\n[TEST] Mining blocks to fund wallets")
    for i, wallet in enumerate(wallets):
        print(f"  Mining block {i+1} for wallet: {wallet['address']}")
        block_data, response = mine_block(wallet['address'])
        
        if block_data and block_data.get("success") == True:
            print(f"  ✓ Successfully mined block at height: {block_data.get('block_height')}")
            print(f"  ✓ Mining reward: {block_data.get('reward')} WEPO")
        else:
            print(f"  ✗ Failed to mine block for wallet: {wallet['address']}")
    
    # Wait for mining rewards to be processed
    print("  Waiting for mining rewards to be processed...")
    time.sleep(2)
    
    # 3. Check wallet balances
    print("\n[TEST] Checking wallet balances")
    funded_wallets = []
    for i, wallet in enumerate(wallets):
        label = chr(65 + i)  # A, B, C, D
        balance = get_wallet_balance(wallet['address'])
        if balance > 0:
            print(f"  ✓ Wallet {label} ({wallet['address']}) has balance: {balance} WEPO")
            funded_wallets.append((label, wallet))
        else:
            print(f"  ✗ Wallet {label} ({wallet['address']}) has zero balance")
    
    if len(funded_wallets) < 4:
        print("  ✗ Not enough funded wallets for UTXO testing")
        log_test("UTXO Management - Wallet Funding", False, error="Not enough funded wallets")
        return False
    
    print(f"  ✓ {len(funded_wallets)}/{len(wallets)} wallets successfully funded")
    log_test("UTXO Management - Wallet Funding", True)
    
    # 4. Create A→B→C→D→A transaction chain
    print("\n[TEST] Creating A→B→C→D→A transaction chain")
    
    # A→B transaction
    a_wallet = funded_wallets[0][1]
    b_wallet = funded_wallets[1][1]
    amount_ab = 1.0
    
    print(f"  Creating A→B transaction: {amount_ab} WEPO")
    tx_id_ab, response_ab = send_transaction(a_wallet['address'], b_wallet['address'], amount_ab)
    
    if not tx_id_ab:
        print("  ✗ Failed to create A→B transaction")
        log_test("UTXO Management - Transaction Chain", False, error="Failed to create A→B transaction")
        return False
    
    print(f"  ✓ Created A→B transaction: {tx_id_ab}")
    
    # Mine a block to confirm A→B
    print("  Mining block to confirm A→B transaction")
    mine_block()
    
    # Wait for confirmation
    print("  Waiting for transaction to be confirmed...")
    time.sleep(2)
    
    # Check B's balance
    b_balance = get_wallet_balance(b_wallet['address'])
    print(f"  ✓ B's balance after A→B: {b_balance} WEPO")
    
    # B→C transaction
    c_wallet = funded_wallets[2][1]
    amount_bc = 0.5
    
    print(f"  Creating B→C transaction: {amount_bc} WEPO")
    tx_id_bc, response_bc = send_transaction(b_wallet['address'], c_wallet['address'], amount_bc)
    
    if not tx_id_bc:
        print("  ✗ Failed to create B→C transaction")
        log_test("UTXO Management - Transaction Chain", False, error="Failed to create B→C transaction")
        return False
    
    print(f"  ✓ Created B→C transaction: {tx_id_bc}")
    
    # Mine a block to confirm B→C
    print("  Mining block to confirm B→C transaction")
    mine_block()
    
    # Wait for confirmation
    print("  Waiting for transaction to be confirmed...")
    time.sleep(2)
    
    # Check C's balance
    c_balance = get_wallet_balance(c_wallet['address'])
    print(f"  ✓ C's balance after B→C: {c_balance} WEPO")
    
    # C→D transaction
    d_wallet = funded_wallets[3][1]
    amount_cd = 0.25
    
    print(f"  Creating C→D transaction: {amount_cd} WEPO")
    tx_id_cd, response_cd = send_transaction(c_wallet['address'], d_wallet['address'], amount_cd)
    
    if not tx_id_cd:
        print("  ✗ Failed to create C→D transaction")
        log_test("UTXO Management - Transaction Chain", False, error="Failed to create C→D transaction")
        return False
    
    print(f"  ✓ Created C→D transaction: {tx_id_cd}")
    
    # Mine a block to confirm C→D
    print("  Mining block to confirm C→D transaction")
    mine_block()
    
    # Wait for confirmation
    print("  Waiting for transaction to be confirmed...")
    time.sleep(2)
    
    # Check D's balance
    d_balance = get_wallet_balance(d_wallet['address'])
    print(f"  ✓ D's balance after C→D: {d_balance} WEPO")
    
    # D→A transaction
    amount_da = 0.1
    
    print(f"  Creating D→A transaction: {amount_da} WEPO")
    tx_id_da, response_da = send_transaction(d_wallet['address'], a_wallet['address'], amount_da)
    
    if not tx_id_da:
        print("  ✗ Failed to create D→A transaction")
        log_test("UTXO Management - Transaction Chain", False, error="Failed to create D→A transaction")
        return False
    
    print(f"  ✓ Created D→A transaction: {tx_id_da}")
    
    # Mine a block to confirm D→A
    print("  Mining block to confirm D→A transaction")
    mine_block()
    
    # Wait for confirmation
    print("  Waiting for transaction to be confirmed...")
    time.sleep(2)
    
    # Check A's balance
    a_balance = get_wallet_balance(a_wallet['address'])
    print(f"  ✓ A's balance after D→A: {a_balance} WEPO")
    
    print(f"  ✓ Successfully created A→B→C→D→A transaction chain")
    log_test("UTXO Management - Transaction Chain", True)
    
    return True

def test_failure_scenarios():
    """Test failure scenarios"""
    print("\n" + "="*80)
    print("FAILURE SCENARIO TESTING")
    print("="*80)
    
    # 1. Create test wallet
    print("\n[TEST] Creating test wallet for failure testing")
    wallet = create_wallet()
    
    if not wallet:
        print("  ✗ Failed to create test wallet")
        log_test("Failure Scenarios - Wallet Creation", False, error="Failed to create test wallet")
        return False
    
    print(f"  ✓ Created test wallet: {wallet['address']}")
    log_test("Failure Scenarios - Wallet Creation", True)
    
    # 2. Mine block to fund wallet
    print("\n[TEST] Mining block to fund wallet")
    block_data, response = mine_block(wallet['address'])
    
    if block_data and block_data.get("success") == True:
        print(f"  ✓ Successfully mined block at height: {block_data.get('block_height')}")
        print(f"  ✓ Mining reward: {block_data.get('reward')} WEPO")
    else:
        print(f"  ✗ Failed to mine block for wallet: {wallet['address']}")
    
    # Wait for mining rewards to be processed
    print("  Waiting for mining rewards to be processed...")
    time.sleep(2)
    
    # 3. Check wallet balance
    print("\n[TEST] Checking wallet balance")
    balance = get_wallet_balance(wallet['address'])
    
    if balance > 0:
        print(f"  ✓ Wallet has balance: {balance} WEPO")
    else:
        print(f"  ✗ Wallet has zero balance")
    
    # 4. Test invalid address format
    print("\n[TEST] Testing invalid address format")
    invalid_address = "invalid_address_format"
    
    tx_data = {
        "from_address": wallet['address'],
        "to_address": invalid_address,
        "amount": 1.0,
        "password_hash": "test_password_hash"
    }
    
    print(f"  Sending transaction to invalid address: {invalid_address}")
    response = requests.post(f"{API_URL}/transaction/send", json=tx_data)
    
    if response.status_code != 200:
        print(f"  ✓ Transaction with invalid address format was rejected")
        print(f"  ✓ Response: {response.status_code} - {response.text}")
        log_test("Failure Scenarios - Invalid Address", True)
    else:
        print(f"  ✗ Transaction with invalid address format was accepted")
        log_test("Failure Scenarios - Invalid Address", False, error="Transaction with invalid address format was accepted")
    
    # 5. Test negative amount
    print("\n[TEST] Testing negative amount")
    recipient = create_wallet()
    
    if not recipient:
        print("  ✗ Failed to create recipient wallet")
        log_test("Failure Scenarios - Negative Amount", False, error="Failed to create recipient wallet")
    else:
        tx_data = {
            "from_address": wallet['address'],
            "to_address": recipient['address'],
            "amount": -1.0,
            "password_hash": "test_password_hash"
        }
        
        print(f"  Sending transaction with negative amount: -1.0 WEPO")
        response = requests.post(f"{API_URL}/transaction/send", json=tx_data)
        
        if response.status_code != 200:
            print(f"  ✓ Transaction with negative amount was rejected")
            print(f"  ✓ Response: {response.status_code} - {response.text}")
            log_test("Failure Scenarios - Negative Amount", True)
        else:
            print(f"  ✗ Transaction with negative amount was accepted")
            log_test("Failure Scenarios - Negative Amount", False, error="Transaction with negative amount was accepted")
    
    # 6. Test zero amount
    print("\n[TEST] Testing zero amount")
    tx_data = {
        "from_address": wallet['address'],
        "to_address": recipient['address'],
        "amount": 0.0,
        "password_hash": "test_password_hash"
    }
    
    print(f"  Sending transaction with zero amount: 0.0 WEPO")
    response = requests.post(f"{API_URL}/transaction/send", json=tx_data)
    
    if response.status_code != 200:
        print(f"  ✓ Transaction with zero amount was rejected")
        print(f"  ✓ Response: {response.status_code} - {response.text}")
        log_test("Failure Scenarios - Zero Amount", True)
    else:
        print(f"  ✗ Transaction with zero amount was accepted")
        log_test("Failure Scenarios - Zero Amount", False, error="Transaction with zero amount was accepted")
    
    # 7. Test extremely large amount
    print("\n[TEST] Testing extremely large amount")
    tx_data = {
        "from_address": wallet['address'],
        "to_address": recipient['address'],
        "amount": 1000000000.0,  # 1 billion WEPO
        "password_hash": "test_password_hash"
    }
    
    print(f"  Sending transaction with extremely large amount: 1,000,000,000.0 WEPO")
    response = requests.post(f"{API_URL}/transaction/send", json=tx_data)
    
    if response.status_code != 200:
        print(f"  ✓ Transaction with extremely large amount was rejected")
        print(f"  ✓ Response: {response.status_code} - {response.text}")
        log_test("Failure Scenarios - Large Amount", True)
    else:
        print(f"  ✗ Transaction with extremely large amount was accepted")
        log_test("Failure Scenarios - Large Amount", False, error="Transaction with extremely large amount was accepted")
    
    return True

def print_summary():
    """Print test summary"""
    print("\n" + "="*80)
    print("WEPO BLOCKCHAIN STRESS TEST SUMMARY")
    print("="*80)
    
    # Calculate success rate
    success_rate = (test_results["passed"] / test_results["total"] * 100) if test_results["total"] > 0 else 0
    
    print(f"Total tests:    {test_results['total']}")
    print(f"Passed:         {test_results['passed']}")
    print(f"Failed:         {test_results['failed']}")
    print(f"Success rate:   {success_rate:.1f}%")
    
    if test_results["failed"] > 0:
        print("\nFailed tests:")
        for test in test_results["tests"]:
            if not test["passed"]:
                print(f"- {test['name']}")
    
    print("\nSTRESS TEST RESULTS:")
    print("1. Mempool Stress: " + ("✅ PASSED" if all(t["name"].startswith("Mempool Stress") and t["passed"] for t in test_results["tests"] if t["name"].startswith("Mempool Stress")) else "❌ FAILED"))
    print("2. UTXO Management: " + ("✅ PASSED" if all(t["name"].startswith("UTXO Management") and t["passed"] for t in test_results["tests"] if t["name"].startswith("UTXO Management")) else "❌ FAILED"))
    print("3. Failure Scenarios: " + ("✅ PASSED" if all(t["name"].startswith("Failure Scenarios") and t["passed"] for t in test_results["tests"] if t["name"].startswith("Failure Scenarios")) else "❌ FAILED"))
    
    print("\nPRODUCTION READINESS ASSESSMENT:")
    if success_rate >= 90:
        print("✅ READY FOR PRODUCTION - System passed stress tests with high success rate")
    elif success_rate >= 75:
        print("⚠️ NEEDS MINOR FIXES - System generally stable but requires some improvements")
    else:
        print("❌ NOT PRODUCTION READY - System failed critical stress tests")
    
    print("="*80)

def main():
    """Main function"""
    print("\n" + "="*80)
    print("WEPO BLOCKCHAIN SIMPLIFIED STRESS TEST")
    print("="*80)
    print("Testing WEPO blockchain system for production readiness")
    print("="*80 + "\n")
    
    # 1. Check network status
    print("\n[TEST] Checking network status")
    network_status = get_network_status()
    
    if network_status:
        print(f"  ✓ Network status retrieved successfully")
        log_test("Network Status", True)
    else:
        print(f"  ✗ Failed to retrieve network status")
        log_test("Network Status", False, error="Failed to retrieve network status")
    
    # 2. Check mining info
    print("\n[TEST] Checking mining info")
    mining_info = get_mining_info()
    
    if mining_info:
        print(f"  ✓ Mining info retrieved successfully")
        log_test("Mining Info", True)
    else:
        print(f"  ✗ Failed to retrieve mining info")
        log_test("Mining Info", False, error="Failed to retrieve mining info")
    
    # Run tests
    test_mempool_stress()
    test_utxo_management()
    test_failure_scenarios()
    
    # Print summary
    print_summary()
    
    return test_results["failed"] == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)