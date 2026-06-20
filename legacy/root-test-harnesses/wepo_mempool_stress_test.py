#!/usr/bin/env python3
"""
WEPO Blockchain Mempool Stress Test

This script focuses on testing the mempool and transaction handling capabilities
of the WEPO blockchain system, using a pre-funded test wallet.
"""

import requests
import json
import time
import uuid
import os
import sys
import random
import string
import concurrent.futures
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

def get_wallet_transactions(address):
    """Get wallet transaction history"""
    response = requests.get(f"{API_URL}/wallet/{address}/transactions")
    
    if response.status_code == 200:
        data = response.json()
        print(f"  Transaction history: {json.dumps(data, indent=2)}")
        return data
    else:
        print(f"  ✗ Failed to get transaction history: {response.status_code} - {response.text}")
        return []

def test_mempool_capacity():
    """Test mempool capacity with multiple transactions"""
    print("\n" + "="*80)
    print("MEMPOOL CAPACITY TESTING")
    print("="*80)
    
    # 1. Create test wallets
    print("\n[TEST] Creating test wallets")
    source_wallet = create_wallet()
    if not source_wallet:
        print("  ✗ Failed to create source wallet")
        log_test("Mempool Capacity - Source Wallet Creation", False, error="Failed to create source wallet")
        return False
    
    # Create recipient wallets
    recipient_wallets = []
    for i in range(5):
        wallet = create_wallet()
        if wallet:
            recipient_wallets.append(wallet)
    
    if len(recipient_wallets) == 0:
        print("  ✗ Failed to create any recipient wallets")
        log_test("Mempool Capacity - Recipient Wallet Creation", False, error="Failed to create recipient wallets")
        return False
    
    print(f"  ✓ Created 1 source wallet and {len(recipient_wallets)} recipient wallets")
    log_test("Mempool Capacity - Wallet Creation", True)
    
    # 2. Mine blocks to fund source wallet
    print("\n[TEST] Mining blocks to fund source wallet")
    for i in range(5):  # Mine multiple blocks to ensure sufficient funding
        print(f"  Mining block {i+1} for source wallet")
        block_data, response = mine_block(source_wallet['address'])
        
        if block_data and block_data.get("success") == True:
            print(f"  ✓ Successfully mined block at height: {block_data.get('block_height')}")
            print(f"  ✓ Mining reward: {block_data.get('reward')} WEPO")
        else:
            print(f"  ✗ Failed to mine block for source wallet")
    
    # Wait for mining rewards to be processed
    print("  Waiting for mining rewards to be processed...")
    time.sleep(2)
    
    # 3. Check source wallet balance
    print("\n[TEST] Checking source wallet balance")
    balance = get_wallet_balance(source_wallet['address'])
    
    if balance > 0:
        print(f"  ✓ Source wallet has balance: {balance} WEPO")
        log_test("Mempool Capacity - Source Wallet Funding", True)
    else:
        print(f"  ✗ Source wallet has zero balance despite mining")
        log_test("Mempool Capacity - Source Wallet Funding", False, error="Source wallet has zero balance")
        
        # Try direct funding through debug endpoint if available
        print("  Attempting to use debug funding endpoint...")
        try:
            debug_fund_data = {
                "address": source_wallet['address'],
                "amount": 1000.0
            }
            response = requests.post(f"{API_URL}/debug/fund-wallet", json=debug_fund_data)
            if response.status_code == 200:
                print(f"  ✓ Successfully used debug funding endpoint")
                # Check balance again
                balance = get_wallet_balance(source_wallet['address'])
                if balance > 0:
                    print(f"  ✓ Source wallet now has balance: {balance} WEPO")
                    log_test("Mempool Capacity - Debug Wallet Funding", True)
                else:
                    print(f"  ✗ Source wallet still has zero balance after debug funding")
                    log_test("Mempool Capacity - Debug Wallet Funding", False, error="Debug funding failed")
                    return False
            else:
                print(f"  ✗ Debug funding endpoint failed or not available: {response.status_code}")
                return False
        except Exception as e:
            print(f"  ✗ Exception during debug funding: {str(e)}")
            return False
    
    # 4. Get initial mempool size
    print("\n[TEST] Checking initial mempool size")
    mining_info = get_mining_info()
    
    if mining_info and "mempool_size" in mining_info:
        initial_mempool_size = mining_info["mempool_size"]
        print(f"  ✓ Initial mempool size: {initial_mempool_size} transactions")
    else:
        print(f"  ✗ Could not determine initial mempool size")
        initial_mempool_size = 0
    
    # 5. Generate multiple transactions to fill mempool
    print("\n[TEST] Generating transactions to fill mempool")
    transaction_count = 20  # Try to create 20 transactions
    successful_txs = 0
    failed_txs = 0
    
    for i in range(transaction_count):
        # Select recipient (round-robin from recipient wallets)
        recipient = recipient_wallets[i % len(recipient_wallets)]
        
        # Random amount between 0.1 and 1.0 WEPO
        amount = round(random.uniform(0.1, 1.0), 2)
        
        tx_id, response = send_transaction(source_wallet['address'], recipient['address'], amount)
        
        if tx_id:
            successful_txs += 1
            print(f"  ✓ Transaction {i+1} successful: {tx_id}")
        else:
            failed_txs += 1
            print(f"  ✗ Transaction {i+1} failed")
    
    if successful_txs > 0:
        print(f"  ✓ Successfully created {successful_txs}/{transaction_count} transactions")
        log_test("Mempool Capacity - Transaction Generation", True)
    else:
        print(f"  ✗ Failed to create any transactions")
        log_test("Mempool Capacity - Transaction Generation", False, error="Failed to create any transactions")
        return False
    
    # 6. Check mempool after transactions
    print("\n[TEST] Checking mempool after transactions")
    mining_info_after = get_mining_info()
    
    if mining_info_after and "mempool_size" in mining_info_after:
        mempool_size_after = mining_info_after["mempool_size"]
        print(f"  ✓ Mempool size after transactions: {mempool_size_after} transactions")
        
        if mempool_size_after > initial_mempool_size:
            print(f"  ✓ Mempool size increased by {mempool_size_after - initial_mempool_size} transactions")
            log_test("Mempool Capacity - Mempool Size", True)
        else:
            print(f"  ✗ Mempool size did not increase despite sending transactions")
            log_test("Mempool Capacity - Mempool Size", False, error="Mempool size did not increase")
    else:
        print(f"  ✗ Could not determine mempool size after transactions")
        log_test("Mempool Capacity - Mempool Size", False, error="Could not determine mempool size")
    
    # 7. Mine a block to process transactions
    print("\n[TEST] Mining block to process transactions")
    block_data, response = mine_block(source_wallet['address'])
    
    if block_data and block_data.get("success") == True:
        print(f"  ✓ Successfully mined block at height: {block_data.get('block_height')}")
        print(f"  ✓ Transactions in block: {block_data.get('transactions', 0)}")
        log_test("Mempool Capacity - Block Mining", True)
    else:
        print(f"  ✗ Failed to mine block")
        log_test("Mempool Capacity - Block Mining", False, error="Failed to mine block")
    
    # 8. Check mempool after mining
    print("\n[TEST] Checking mempool after mining")
    mining_info_final = get_mining_info()
    
    if mining_info_final and "mempool_size" in mining_info_final:
        mempool_size_final = mining_info_final["mempool_size"]
        print(f"  ✓ Mempool size after mining: {mempool_size_final} transactions")
        
        if mempool_size_final < mempool_size_after:
            print(f"  ✓ Mempool size decreased by {mempool_size_after - mempool_size_final} transactions after mining")
            log_test("Mempool Capacity - Mempool Cleanup", True)
        else:
            print(f"  ✗ Mempool size did not decrease after mining")
            log_test("Mempool Capacity - Mempool Cleanup", False, error="Mempool size did not decrease")
    else:
        print(f"  ✗ Could not determine mempool size after mining")
        log_test("Mempool Capacity - Mempool Cleanup", False, error="Could not determine mempool size")
    
    # 9. Check transaction history
    print("\n[TEST] Checking transaction history")
    transactions = get_wallet_transactions(source_wallet['address'])
    
    if transactions and len(transactions) > 0:
        print(f"  ✓ Found {len(transactions)} transactions in history")
        log_test("Mempool Capacity - Transaction History", True)
    else:
        print(f"  ✗ No transactions found in history")
        log_test("Mempool Capacity - Transaction History", False, error="No transactions found")
    
    return True

def test_concurrent_transactions():
    """Test concurrent transaction processing"""
    print("\n" + "="*80)
    print("CONCURRENT TRANSACTION TESTING")
    print("="*80)
    
    # 1. Create test wallets
    print("\n[TEST] Creating test wallets")
    source_wallet = create_wallet()
    if not source_wallet:
        print("  ✗ Failed to create source wallet")
        log_test("Concurrent Transactions - Source Wallet Creation", False, error="Failed to create source wallet")
        return False
    
    # Create recipient wallets
    recipient_wallets = []
    for i in range(10):
        wallet = create_wallet()
        if wallet:
            recipient_wallets.append(wallet)
    
    if len(recipient_wallets) == 0:
        print("  ✗ Failed to create any recipient wallets")
        log_test("Concurrent Transactions - Recipient Wallet Creation", False, error="Failed to create recipient wallets")
        return False
    
    print(f"  ✓ Created 1 source wallet and {len(recipient_wallets)} recipient wallets")
    log_test("Concurrent Transactions - Wallet Creation", True)
    
    # 2. Mine blocks to fund source wallet
    print("\n[TEST] Mining blocks to fund source wallet")
    for i in range(5):  # Mine multiple blocks to ensure sufficient funding
        print(f"  Mining block {i+1} for source wallet")
        block_data, response = mine_block(source_wallet['address'])
        
        if block_data and block_data.get("success") == True:
            print(f"  ✓ Successfully mined block at height: {block_data.get('block_height')}")
            print(f"  ✓ Mining reward: {block_data.get('reward')} WEPO")
        else:
            print(f"  ✗ Failed to mine block for source wallet")
    
    # Wait for mining rewards to be processed
    print("  Waiting for mining rewards to be processed...")
    time.sleep(2)
    
    # 3. Check source wallet balance
    print("\n[TEST] Checking source wallet balance")
    balance = get_wallet_balance(source_wallet['address'])
    
    if balance > 0:
        print(f"  ✓ Source wallet has balance: {balance} WEPO")
        log_test("Concurrent Transactions - Source Wallet Funding", True)
    else:
        print(f"  ✗ Source wallet has zero balance despite mining")
        log_test("Concurrent Transactions - Source Wallet Funding", False, error="Source wallet has zero balance")
        
        # Try direct funding through debug endpoint if available
        print("  Attempting to use debug funding endpoint...")
        try:
            debug_fund_data = {
                "address": source_wallet['address'],
                "amount": 1000.0
            }
            response = requests.post(f"{API_URL}/debug/fund-wallet", json=debug_fund_data)
            if response.status_code == 200:
                print(f"  ✓ Successfully used debug funding endpoint")
                # Check balance again
                balance = get_wallet_balance(source_wallet['address'])
                if balance > 0:
                    print(f"  ✓ Source wallet now has balance: {balance} WEPO")
                    log_test("Concurrent Transactions - Debug Wallet Funding", True)
                else:
                    print(f"  ✗ Source wallet still has zero balance after debug funding")
                    log_test("Concurrent Transactions - Debug Wallet Funding", False, error="Debug funding failed")
                    return False
            else:
                print(f"  ✗ Debug funding endpoint failed or not available: {response.status_code}")
                return False
        except Exception as e:
            print(f"  ✗ Exception during debug funding: {str(e)}")
            return False
    
    # 4. Send concurrent transactions
    print("\n[TEST] Sending concurrent transactions")
    transaction_count = 10
    successful_txs = 0
    failed_txs = 0
    
    def send_concurrent_tx(i):
        # Select recipient
        recipient = recipient_wallets[i % len(recipient_wallets)]
        
        # Small amount to allow multiple transactions
        amount = 0.1
        
        tx_id, response = send_transaction(source_wallet['address'], recipient['address'], amount)
        
        return {
            "index": i,
            "tx_id": tx_id,
            "response": response,
            "success": tx_id is not None
        }
    
    # Use ThreadPoolExecutor for parallel execution
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_tx = {executor.submit(send_concurrent_tx, i): i for i in range(transaction_count)}
        
        for future in concurrent.futures.as_completed(future_to_tx):
            result = future.result()
            
            if result["success"]:
                successful_txs += 1
                print(f"  ✓ Concurrent transaction {result['index']} successful: {result['tx_id']}")
            else:
                failed_txs += 1
                print(f"  ✗ Concurrent transaction {result['index']} failed")
    
    if successful_txs > 0:
        print(f"  ✓ Successfully created {successful_txs}/{transaction_count} concurrent transactions")
        log_test("Concurrent Transactions - Transaction Generation", True)
    else:
        print(f"  ✗ Failed to create any concurrent transactions")
        log_test("Concurrent Transactions - Transaction Generation", False, error="Failed to create concurrent transactions")
        return False
    
    # 5. Check mempool
    print("\n[TEST] Checking mempool after concurrent transactions")
    mining_info = get_mining_info()
    
    if mining_info and "mempool_size" in mining_info:
        mempool_size = mining_info["mempool_size"]
        print(f"  ✓ Mempool size after concurrent transactions: {mempool_size} transactions")
        
        if mempool_size > 0:
            print(f"  ✓ Mempool contains transactions")
            log_test("Concurrent Transactions - Mempool Check", True)
        else:
            print(f"  ✗ Mempool is empty despite sending concurrent transactions")
            log_test("Concurrent Transactions - Mempool Check", False, error="Mempool is empty")
    else:
        print(f"  ✗ Could not determine mempool size")
        log_test("Concurrent Transactions - Mempool Check", False, error="Could not determine mempool size")
    
    # 6. Mine a block to process transactions
    print("\n[TEST] Mining block to process concurrent transactions")
    block_data, response = mine_block(source_wallet['address'])
    
    if block_data and block_data.get("success") == True:
        print(f"  ✓ Successfully mined block at height: {block_data.get('block_height')}")
        print(f"  ✓ Transactions in block: {block_data.get('transactions', 0)}")
        log_test("Concurrent Transactions - Block Mining", True)
    else:
        print(f"  ✗ Failed to mine block")
        log_test("Concurrent Transactions - Block Mining", False, error="Failed to mine block")
    
    # 7. Check transaction history
    print("\n[TEST] Checking transaction history after concurrent transactions")
    transactions = get_wallet_transactions(source_wallet['address'])
    
    if transactions and len(transactions) > 0:
        print(f"  ✓ Found {len(transactions)} transactions in history")
        log_test("Concurrent Transactions - Transaction History", True)
    else:
        print(f"  ✗ No transactions found in history")
        log_test("Concurrent Transactions - Transaction History", False, error="No transactions found")
    
    return True

def test_transaction_validation():
    """Test transaction validation under load"""
    print("\n" + "="*80)
    print("TRANSACTION VALIDATION TESTING")
    print("="*80)
    
    # 1. Create test wallets
    print("\n[TEST] Creating test wallets")
    source_wallet = create_wallet()
    if not source_wallet:
        print("  ✗ Failed to create source wallet")
        log_test("Transaction Validation - Source Wallet Creation", False, error="Failed to create source wallet")
        return False
    
    recipient_wallet = create_wallet()
    if not recipient_wallet:
        print("  ✗ Failed to create recipient wallet")
        log_test("Transaction Validation - Recipient Wallet Creation", False, error="Failed to create recipient wallet")
        return False
    
    print(f"  ✓ Created source and recipient wallets")
    log_test("Transaction Validation - Wallet Creation", True)
    
    # 2. Mine blocks to fund source wallet
    print("\n[TEST] Mining blocks to fund source wallet")
    for i in range(3):  # Mine multiple blocks to ensure sufficient funding
        print(f"  Mining block {i+1} for source wallet")
        block_data, response = mine_block(source_wallet['address'])
        
        if block_data and block_data.get("success") == True:
            print(f"  ✓ Successfully mined block at height: {block_data.get('block_height')}")
            print(f"  ✓ Mining reward: {block_data.get('reward')} WEPO")
        else:
            print(f"  ✗ Failed to mine block for source wallet")
    
    # Wait for mining rewards to be processed
    print("  Waiting for mining rewards to be processed...")
    time.sleep(2)
    
    # 3. Check source wallet balance
    print("\n[TEST] Checking source wallet balance")
    balance = get_wallet_balance(source_wallet['address'])
    
    if balance > 0:
        print(f"  ✓ Source wallet has balance: {balance} WEPO")
        log_test("Transaction Validation - Source Wallet Funding", True)
    else:
        print(f"  ✗ Source wallet has zero balance despite mining")
        log_test("Transaction Validation - Source Wallet Funding", False, error="Source wallet has zero balance")
        
        # Try direct funding through debug endpoint if available
        print("  Attempting to use debug funding endpoint...")
        try:
            debug_fund_data = {
                "address": source_wallet['address'],
                "amount": 1000.0
            }
            response = requests.post(f"{API_URL}/debug/fund-wallet", json=debug_fund_data)
            if response.status_code == 200:
                print(f"  ✓ Successfully used debug funding endpoint")
                # Check balance again
                balance = get_wallet_balance(source_wallet['address'])
                if balance > 0:
                    print(f"  ✓ Source wallet now has balance: {balance} WEPO")
                    log_test("Transaction Validation - Debug Wallet Funding", True)
                else:
                    print(f"  ✗ Source wallet still has zero balance after debug funding")
                    log_test("Transaction Validation - Debug Wallet Funding", False, error="Debug funding failed")
                    return False
            else:
                print(f"  ✗ Debug funding endpoint failed or not available: {response.status_code}")
                return False
        except Exception as e:
            print(f"  ✗ Exception during debug funding: {str(e)}")
            return False
    
    # 4. Test valid transaction
    print("\n[TEST] Testing valid transaction")
    valid_amount = min(balance / 2, 10.0)  # Use half of balance or 10 WEPO, whichever is smaller
    
    tx_id, response = send_transaction(source_wallet['address'], recipient_wallet['address'], valid_amount)
    
    if tx_id:
        print(f"  ✓ Valid transaction successful: {tx_id}")
        log_test("Transaction Validation - Valid Transaction", True)
    else:
        print(f"  ✗ Valid transaction failed")
        log_test("Transaction Validation - Valid Transaction", False, error="Valid transaction failed")
    
    # 5. Test transaction with amount exceeding balance
    print("\n[TEST] Testing transaction with amount exceeding balance")
    excessive_amount = balance * 2  # Double the balance
    
    tx_id, response = send_transaction(source_wallet['address'], recipient_wallet['address'], excessive_amount)
    
    if tx_id is None and response.status_code != 200:
        print(f"  ✓ Transaction with excessive amount was rejected")
        print(f"  ✓ Response: {response.status_code} - {response.text}")
        log_test("Transaction Validation - Excessive Amount", True)
    else:
        print(f"  ✗ Transaction with excessive amount was accepted")
        log_test("Transaction Validation - Excessive Amount", False, error="Transaction with excessive amount was accepted")
    
    # 6. Test transaction with negative amount
    print("\n[TEST] Testing transaction with negative amount")
    
    tx_id, response = send_transaction(source_wallet['address'], recipient_wallet['address'], -1.0)
    
    if tx_id is None and response.status_code != 200:
        print(f"  ✓ Transaction with negative amount was rejected")
        print(f"  ✓ Response: {response.status_code} - {response.text}")
        log_test("Transaction Validation - Negative Amount", True)
    else:
        print(f"  ✗ Transaction with negative amount was accepted")
        log_test("Transaction Validation - Negative Amount", False, error="Transaction with negative amount was accepted")
    
    # 7. Test transaction with zero amount
    print("\n[TEST] Testing transaction with zero amount")
    
    tx_id, response = send_transaction(source_wallet['address'], recipient_wallet['address'], 0.0)
    
    if tx_id is None and response.status_code != 200:
        print(f"  ✓ Transaction with zero amount was rejected")
        print(f"  ✓ Response: {response.status_code} - {response.text}")
        log_test("Transaction Validation - Zero Amount", True)
    else:
        print(f"  ✗ Transaction with zero amount was accepted")
        log_test("Transaction Validation - Zero Amount", False, error="Transaction with zero amount was accepted")
    
    # 8. Test transaction with invalid recipient address
    print("\n[TEST] Testing transaction with invalid recipient address")
    
    tx_id, response = send_transaction(source_wallet['address'], "invalid_address", 1.0)
    
    if tx_id is None and response.status_code != 200:
        print(f"  ✓ Transaction with invalid recipient address was rejected")
        print(f"  ✓ Response: {response.status_code} - {response.text}")
        log_test("Transaction Validation - Invalid Address", True)
    else:
        print(f"  ✗ Transaction with invalid recipient address was accepted")
        log_test("Transaction Validation - Invalid Address", False, error="Transaction with invalid address was accepted")
    
    # 9. Mine a block to process valid transaction
    print("\n[TEST] Mining block to process valid transaction")
    block_data, response = mine_block(source_wallet['address'])
    
    if block_data and block_data.get("success") == True:
        print(f"  ✓ Successfully mined block at height: {block_data.get('block_height')}")
        print(f"  ✓ Transactions in block: {block_data.get('transactions', 0)}")
        log_test("Transaction Validation - Block Mining", True)
    else:
        print(f"  ✗ Failed to mine block")
        log_test("Transaction Validation - Block Mining", False, error="Failed to mine block")
    
    # 10. Check recipient wallet balance
    print("\n[TEST] Checking recipient wallet balance")
    recipient_balance = get_wallet_balance(recipient_wallet['address'])
    
    if recipient_balance > 0:
        print(f"  ✓ Recipient wallet received funds: {recipient_balance} WEPO")
        log_test("Transaction Validation - Recipient Balance", True)
    else:
        print(f"  ✗ Recipient wallet has zero balance after transaction")
        log_test("Transaction Validation - Recipient Balance", False, error="Recipient wallet has zero balance")
    
    return True

def print_summary():
    """Print test summary"""
    print("\n" + "="*80)
    print("WEPO BLOCKCHAIN MEMPOOL STRESS TEST SUMMARY")
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
    print("1. Mempool Capacity: " + ("✅ PASSED" if all(t["name"].startswith("Mempool Capacity") and t["passed"] for t in test_results["tests"] if t["name"].startswith("Mempool Capacity")) else "❌ FAILED"))
    print("2. Concurrent Transactions: " + ("✅ PASSED" if all(t["name"].startswith("Concurrent Transactions") and t["passed"] for t in test_results["tests"] if t["name"].startswith("Concurrent Transactions")) else "❌ FAILED"))
    print("3. Transaction Validation: " + ("✅ PASSED" if all(t["name"].startswith("Transaction Validation") and t["passed"] for t in test_results["tests"] if t["name"].startswith("Transaction Validation")) else "❌ FAILED"))
    
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
    print("WEPO BLOCKCHAIN MEMPOOL STRESS TEST")
    print("="*80)
    print("Testing WEPO blockchain mempool and transaction handling")
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
    test_mempool_capacity()
    test_concurrent_transactions()
    test_transaction_validation()
    
    # Print summary
    print_summary()
    
    return test_results["failed"] == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)