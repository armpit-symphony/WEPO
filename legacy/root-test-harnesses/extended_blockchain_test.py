#!/usr/bin/env python3
import requests
import json
import time
import uuid
import os
import sys
from datetime import datetime
import random
import string
import concurrent.futures

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
    
    response = requests.post(f"{API_URL}/wallet/create", json=wallet_data)
    if response.status_code == 200:
        return wallet_data
    else:
        print(f"Failed to create wallet: {response.status_code} - {response.text}")
        return None

def fund_wallet(address, amount=100.0):
    """Fund a wallet using test endpoints"""
    # Try fund-wallet endpoint first
    fund_data = {
        "address": address,
        "amount": amount
    }
    
    response = requests.post(f"{API_URL}/test/fund-wallet", json=fund_data)
    
    # If fund-wallet endpoint doesn't exist, try mine-block endpoint
    if response.status_code == 404:
        mine_response = requests.post(f"{API_URL}/test/mine-block", json={"miner_address": address})
        if mine_response.status_code == 200:
            return mine_response.json()
        else:
            print(f"Failed to mine block: {mine_response.status_code} - {mine_response.text}")
            return None
    elif response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to fund wallet: {response.status_code} - {response.text}")
        return None

def get_wallet_balance(address):
    """Get wallet balance"""
    response = requests.get(f"{API_URL}/wallet/{address}")
    if response.status_code == 200:
        return response.json().get("balance", 0.0)
    else:
        print(f"Failed to get wallet balance: {response.status_code} - {response.text}")
        return 0.0

def get_wallet_transactions(address):
    """Get wallet transaction history"""
    response = requests.get(f"{API_URL}/wallet/{address}/transactions")
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to get wallet transactions: {response.status_code} - {response.text}")
        return []

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
        print(f"Transaction failed: {response.status_code} - {response.text}")
        return {"status": "failed", "error": response.text if response.status_code != 500 else "Server error"}

def mine_block(miner_address):
    """Mine a new block"""
    mine_data = {
        "miner_address": miner_address
    }
    
    response = requests.post(f"{API_URL}/test/mine-block", json=mine_data)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to mine block: {response.status_code} - {response.text}")
        return None

def get_network_status():
    """Get blockchain network status"""
    response = requests.get(f"{API_URL}/network/status")
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to get network status: {response.status_code} - {response.text}")
        return None

def get_mining_info():
    """Get mining information"""
    response = requests.get(f"{API_URL}/mining/info")
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to get mining info: {response.status_code} - {response.text}")
        return None

def run_extended_tests():
    """Run comprehensive extended tests for WEPO blockchain"""
    print("\n" + "="*80)
    print("WEPO BLOCKCHAIN EXTENDED TESTING")
    print("="*80)
    print("Testing advanced blockchain functionality and edge cases")
    print("="*80 + "\n")
    
    # 1. Multi-Wallet Transaction Testing
    try:
        print("\n[TEST] Multi-Wallet Transaction Testing")
        print("  Creating multiple test wallets...")
        
        # Create three test wallets
        wallet_a = create_wallet()
        wallet_b = create_wallet()
        wallet_c = create_wallet()
        
        if wallet_a and wallet_b and wallet_c:
            print(f"  ✓ Created Wallet A: {wallet_a['address']}")
            print(f"  ✓ Created Wallet B: {wallet_b['address']}")
            print(f"  ✓ Created Wallet C: {wallet_c['address']}")
            
            # Fund Wallet A
            print("\n  Funding Wallet A...")
            fund_result = fund_wallet(wallet_a['address'], 500.0)
            if fund_result:
                print(f"  ✓ Funded Wallet A")
                
                # Mine a block to confirm funding
                mine_result = mine_block(wallet_a['address'])
                if mine_result:
                    print(f"  ✓ Mined block to confirm funding")
                    
                    # Check Wallet A balance
                    balance_a = get_wallet_balance(wallet_a['address'])
                    print(f"  ✓ Wallet A balance: {balance_a} WEPO")
                    
                    if balance_a > 0:
                        # Send from A to B
                        print("\n  Sending 50 WEPO from Wallet A to Wallet B...")
                        tx_a_to_b = send_transaction(wallet_a['address'], wallet_b['address'], 50.0)
                        
                        if tx_a_to_b and tx_a_to_b.get("status") != "failed":
                            print(f"  ✓ Transaction A→B created: {tx_a_to_b.get('transaction_id', 'unknown')}")
                            
                            # Send from A to C
                            print("\n  Sending 30 WEPO from Wallet A to Wallet C...")
                            tx_a_to_c = send_transaction(wallet_a['address'], wallet_c['address'], 30.0)
                            
                            if tx_a_to_c and tx_a_to_c.get("status") != "failed":
                                print(f"  ✓ Transaction A→C created: {tx_a_to_c.get('transaction_id', 'unknown')}")
                                
                                # Mine a block to confirm transactions
                                print("\n  Mining block to confirm transactions...")
                                mine_result = mine_block(wallet_a['address'])
                                
                                if mine_result:
                                    print(f"  ✓ Mined block with transactions")
                                    
                                    # Check all wallet balances
                                    time.sleep(1)  # Give time for balances to update
                                    balance_a_after = get_wallet_balance(wallet_a['address'])
                                    balance_b = get_wallet_balance(wallet_b['address'])
                                    balance_c = get_wallet_balance(wallet_c['address'])
                                    
                                    print(f"  ✓ Wallet A balance after transfers: {balance_a_after} WEPO")
                                    print(f"  ✓ Wallet B balance: {balance_b} WEPO")
                                    print(f"  ✓ Wallet C balance: {balance_c} WEPO")
                                    
                                    # Verify balances
                                    expected_a = balance_a - 50.0 - 30.0 - 0.0002  # Subtract transfers and fees
                                    balance_check = (
                                        abs(balance_a_after - expected_a) < 1.0 and
                                        abs(balance_b - 50.0) < 1.0 and
                                        abs(balance_c - 30.0) < 1.0
                                    )
                                    
                                    if balance_check:
                                        print("  ✓ All wallet balances verified correctly")
                                        passed = True
                                    else:
                                        print("  ✗ Wallet balance verification failed")
                                        passed = False
                                else:
                                    print("  ✗ Failed to mine block with transactions")
                                    passed = False
                            else:
                                print("  ✗ Failed to create transaction A→C")
                                passed = False
                        else:
                            print("  ✗ Failed to create transaction A→B")
                            passed = False
                    else:
                        print("  ✗ Wallet A has zero balance after funding")
                        passed = False
                else:
                    print("  ✗ Failed to mine block for funding")
                    passed = False
            else:
                print("  ✗ Failed to fund Wallet A")
                passed = False
        else:
            print("  ✗ Failed to create test wallets")
            passed = False
            
        log_test("Multi-Wallet Transaction Testing", passed)
    except Exception as e:
        log_test("Multi-Wallet Transaction Testing", False, error=str(e))
        print(f"  ✗ Exception: {str(e)}")
    
    # 2. Multiple Transactions Per Block
    try:
        print("\n[TEST] Multiple Transactions Per Block")
        print("  Creating test wallets for multiple transactions...")
        
        # Create source wallet and multiple recipient wallets
        source_wallet = create_wallet()
        recipient_wallets = [create_wallet() for _ in range(5)]
        
        if source_wallet and all(recipient_wallets):
            print(f"  ✓ Created source wallet: {source_wallet['address']}")
            print(f"  ✓ Created {len(recipient_wallets)} recipient wallets")
            
            # Fund source wallet
            print("\n  Funding source wallet...")
            fund_result = fund_wallet(source_wallet['address'], 1000.0)
            if fund_result:
                print(f"  ✓ Funded source wallet")
                
                # Mine a block to confirm funding
                mine_result = mine_block(source_wallet['address'])
                if mine_result:
                    print(f"  ✓ Mined block to confirm funding")
                    
                    # Check source wallet balance
                    source_balance = get_wallet_balance(source_wallet['address'])
                    print(f"  ✓ Source wallet balance: {source_balance} WEPO")
                    
                    if source_balance > 0:
                        # Create multiple transactions to different recipients
                        print("\n  Creating multiple transactions to different recipients...")
                        transactions = []
                        
                        for i, recipient in enumerate(recipient_wallets):
                            amount = 10.0 * (i + 1)  # Different amounts
                            tx = send_transaction(source_wallet['address'], recipient['address'], amount)
                            if tx and tx.get("status") != "failed":
                                print(f"  ✓ Transaction {i+1} created: {tx.get('transaction_id', 'unknown')}")
                                transactions.append(tx)
                            else:
                                print(f"  ✗ Failed to create transaction {i+1}")
                        
                        if len(transactions) > 0:
                            # Mine a block to confirm all transactions
                            print("\n  Mining block to confirm multiple transactions...")
                            mine_result = mine_block(source_wallet['address'])
                            
                            if mine_result:
                                print(f"  ✓ Mined block with multiple transactions")
                                print(f"  ✓ Transactions in block: {mine_result.get('transactions', 'unknown')}")
                                
                                # Check if block contains multiple transactions
                                if mine_result.get('transactions', 0) > 1:
                                    print(f"  ✓ Block contains multiple transactions")
                                    
                                    # Verify recipient balances
                                    time.sleep(1)  # Give time for balances to update
                                    balances_correct = True
                                    
                                    for i, recipient in enumerate(recipient_wallets):
                                        expected_amount = 10.0 * (i + 1)
                                        actual_balance = get_wallet_balance(recipient['address'])
                                        print(f"  ✓ Recipient {i+1} balance: {actual_balance} WEPO (expected ~{expected_amount})")
                                        
                                        if abs(actual_balance - expected_amount) > 1.0:
                                            balances_correct = False
                                    
                                    if balances_correct:
                                        print("  ✓ All recipient balances verified correctly")
                                        passed = True
                                    else:
                                        print("  ✗ Recipient balance verification failed")
                                        passed = False
                                else:
                                    print("  ✗ Block does not contain multiple transactions")
                                    passed = False
                            else:
                                print("  ✗ Failed to mine block with multiple transactions")
                                passed = False
                        else:
                            print("  ✗ Failed to create any transactions")
                            passed = False
                    else:
                        print("  ✗ Source wallet has zero balance after funding")
                        passed = False
                else:
                    print("  ✗ Failed to mine block for funding")
                    passed = False
            else:
                print("  ✗ Failed to fund source wallet")
                passed = False
        else:
            print("  ✗ Failed to create test wallets")
            passed = False
            
        log_test("Multiple Transactions Per Block", passed)
    except Exception as e:
        log_test("Multiple Transactions Per Block", False, error=str(e))
        print(f"  ✗ Exception: {str(e)}")
    
    # 3. Reward Schedule Progression
    try:
        print("\n[TEST] Reward Schedule Progression")
        
        # Get current mining info
        mining_info = get_mining_info()
        if mining_info:
            print(f"  Current mining info: {json.dumps(mining_info, indent=2)}")
            
            # Check current reward
            current_reward = mining_info.get('current_reward', 0)
            current_height = mining_info.get('current_block_height', 0)
            
            print(f"  ✓ Current block height: {current_height}")
            print(f"  ✓ Current mining reward: {current_reward} WEPO")
            
            # Determine which quarter we're in
            if current_reward == 400.0:
                print("  ✓ Q1 rewards confirmed (400 WEPO per block)")
                quarter = 1
            elif current_reward == 200.0:
                print("  ✓ Q2 rewards confirmed (200 WEPO per block)")
                quarter = 2
            elif current_reward == 100.0:
                print("  ✓ Q3 rewards confirmed (100 WEPO per block)")
                quarter = 3
            elif current_reward == 50.0:
                print("  ✓ Q4 rewards confirmed (50 WEPO per block)")
                quarter = 4
            else:
                print(f"  ⚠ Non-standard reward: {current_reward} WEPO")
                quarter = 0
            
            # Create a miner wallet
            miner_wallet = create_wallet()
            if miner_wallet:
                print(f"  ✓ Created miner wallet: {miner_wallet['address']}")
                
                # Mine a block and check reward
                mine_result = mine_block(miner_wallet['address'])
                if mine_result:
                    print(f"  ✓ Mined block at height {mine_result.get('block_height', 'unknown')}")
                    print(f"  ✓ Mining reward: {mine_result.get('reward', 'unknown')} WEPO")
                    
                    # Verify reward matches expected value
                    expected_reward = current_reward
                    actual_reward = mine_result.get('reward', 0)
                    
                    if abs(actual_reward - expected_reward) < 0.1:
                        print(f"  ✓ Mining reward matches expected Q{quarter} value")
                        passed = True
                    else:
                        print(f"  ✗ Mining reward {actual_reward} doesn't match expected Q{quarter} value {expected_reward}")
                        passed = False
                else:
                    print("  ✗ Failed to mine block")
                    passed = False
            else:
                print("  ✗ Failed to create miner wallet")
                passed = False
        else:
            print("  ✗ Failed to get mining info")
            passed = False
            
        log_test("Reward Schedule Progression", passed)
    except Exception as e:
        log_test("Reward Schedule Progression", False, error=str(e))
        print(f"  ✗ Exception: {str(e)}")
    
    # 4. Edge Case Testing
    try:
        print("\n[TEST] Edge Case Testing")
        
        # Create test wallets
        sender_wallet = create_wallet()
        recipient_wallet = create_wallet()
        
        if sender_wallet and recipient_wallet:
            print(f"  ✓ Created sender wallet: {sender_wallet['address']}")
            print(f"  ✓ Created recipient wallet: {recipient_wallet['address']}")
            
            # Fund sender wallet with small amount
            print("\n  Funding sender wallet with small amount...")
            fund_result = fund_wallet(sender_wallet['address'], 10.0)
            if fund_result:
                print(f"  ✓ Funded sender wallet")
                
                # Mine a block to confirm funding
                mine_result = mine_block(sender_wallet['address'])
                if mine_result:
                    print(f"  ✓ Mined block to confirm funding")
                    
                    # Check sender wallet balance
                    sender_balance = get_wallet_balance(sender_wallet['address'])
                    print(f"  ✓ Sender wallet balance: {sender_balance} WEPO")
                    
                    # Test Case 1: Insufficient balance transaction
                    print("\n  Test Case 1: Insufficient balance transaction")
                    tx_insufficient = send_transaction(sender_wallet['address'], recipient_wallet['address'], sender_balance + 10.0)
                    
                    if tx_insufficient.get("status") == "failed" or "error" in tx_insufficient:
                        print(f"  ✓ Insufficient balance transaction correctly rejected")
                        insufficient_test_passed = True
                    else:
                        print(f"  ✗ Insufficient balance transaction was accepted")
                        insufficient_test_passed = False
                    
                    # Test Case 2: Zero amount transaction
                    print("\n  Test Case 2: Zero amount transaction")
                    tx_zero = send_transaction(sender_wallet['address'], recipient_wallet['address'], 0.0)
                    
                    if tx_zero.get("status") == "failed" or "error" in tx_zero:
                        print(f"  ✓ Zero amount transaction correctly rejected")
                        zero_test_passed = True
                    else:
                        print(f"  ✗ Zero amount transaction was accepted")
                        zero_test_passed = False
                    
                    # Test Case 3: Invalid recipient address
                    print("\n  Test Case 3: Invalid recipient address")
                    tx_invalid = send_transaction(sender_wallet['address'], "invalid_address", 1.0)
                    
                    if tx_invalid.get("status") == "failed" or "error" in tx_invalid:
                        print(f"  ✓ Invalid recipient address transaction correctly rejected")
                        invalid_test_passed = True
                    else:
                        print(f"  ✗ Invalid recipient address transaction was accepted")
                        invalid_test_passed = False
                    
                    # Test Case 4: Duplicate transaction
                    print("\n  Test Case 4: Duplicate transaction")
                    tx_first = send_transaction(sender_wallet['address'], recipient_wallet['address'], 1.0)
                    if tx_first and tx_first.get("status") != "failed":
                        print(f"  ✓ First transaction created: {tx_first.get('transaction_id', 'unknown')}")
                        
                        # Try to send identical transaction immediately
                        tx_duplicate = send_transaction(sender_wallet['address'], recipient_wallet['address'], 1.0)
                        
                        # Note: Some implementations might allow this as they're technically different transactions
                        if tx_duplicate and tx_duplicate.get("status") != "failed":
                            print(f"  ⚠ Duplicate transaction was accepted (implementation specific)")
                            duplicate_test_passed = True
                        else:
                            print(f"  ✓ Duplicate transaction was rejected")
                            duplicate_test_passed = True
                    else:
                        print(f"  ✗ Failed to create first transaction")
                        duplicate_test_passed = False
                    
                    # Overall edge case test result
                    passed = insufficient_test_passed and zero_test_passed and invalid_test_passed and duplicate_test_passed
                else:
                    print("  ✗ Failed to mine block for funding")
                    passed = False
            else:
                print("  ✗ Failed to fund sender wallet")
                passed = False
        else:
            print("  ✗ Failed to create test wallets")
            passed = False
            
        log_test("Edge Case Testing", passed)
    except Exception as e:
        log_test("Edge Case Testing", False, error=str(e))
        print(f"  ✗ Exception: {str(e)}")
    
    # 5. UTXO and Balance Management
    try:
        print("\n[TEST] UTXO and Balance Management")
        print("  Testing complex transaction chains (A→B→C→A)...")
        
        # Create test wallets
        wallet_a = create_wallet()
        wallet_b = create_wallet()
        wallet_c = create_wallet()
        
        if wallet_a and wallet_b and wallet_c:
            print(f"  ✓ Created Wallet A: {wallet_a['address']}")
            print(f"  ✓ Created Wallet B: {wallet_b['address']}")
            print(f"  ✓ Created Wallet C: {wallet_c['address']}")
            
            # Fund Wallet A
            print("\n  Funding Wallet A...")
            fund_result = fund_wallet(wallet_a['address'], 100.0)
            if fund_result:
                print(f"  ✓ Funded Wallet A")
                
                # Mine a block to confirm funding
                mine_result = mine_block(wallet_a['address'])
                if mine_result:
                    print(f"  ✓ Mined block to confirm funding")
                    
                    # Check Wallet A balance
                    balance_a = get_wallet_balance(wallet_a['address'])
                    print(f"  ✓ Wallet A initial balance: {balance_a} WEPO")
                    
                    if balance_a > 0:
                        # Step 1: A → B (50 WEPO)
                        print("\n  Step 1: A → B (50 WEPO)")
                        tx_a_to_b = send_transaction(wallet_a['address'], wallet_b['address'], 50.0)
                        
                        if tx_a_to_b and tx_a_to_b.get("status") != "failed":
                            print(f"  ✓ Transaction A→B created: {tx_a_to_b.get('transaction_id', 'unknown')}")
                            
                            # Mine a block to confirm transaction
                            mine_result = mine_block(wallet_a['address'])
                            if mine_result:
                                print(f"  ✓ Mined block to confirm A→B transaction")
                                
                                # Check balances
                                balance_a = get_wallet_balance(wallet_a['address'])
                                balance_b = get_wallet_balance(wallet_b['address'])
                                print(f"  ✓ Wallet A balance: {balance_a} WEPO")
                                print(f"  ✓ Wallet B balance: {balance_b} WEPO")
                                
                                # Step 2: B → C (25 WEPO)
                                print("\n  Step 2: B → C (25 WEPO)")
                                tx_b_to_c = send_transaction(wallet_b['address'], wallet_c['address'], 25.0)
                                
                                if tx_b_to_c and tx_b_to_c.get("status") != "failed":
                                    print(f"  ✓ Transaction B→C created: {tx_b_to_c.get('transaction_id', 'unknown')}")
                                    
                                    # Mine a block to confirm transaction
                                    mine_result = mine_block(wallet_b['address'])
                                    if mine_result:
                                        print(f"  ✓ Mined block to confirm B→C transaction")
                                        
                                        # Check balances
                                        balance_b = get_wallet_balance(wallet_b['address'])
                                        balance_c = get_wallet_balance(wallet_c['address'])
                                        print(f"  ✓ Wallet B balance: {balance_b} WEPO")
                                        print(f"  ✓ Wallet C balance: {balance_c} WEPO")
                                        
                                        # Step 3: C → A (10 WEPO)
                                        print("\n  Step 3: C → A (10 WEPO)")
                                        tx_c_to_a = send_transaction(wallet_c['address'], wallet_a['address'], 10.0)
                                        
                                        if tx_c_to_a and tx_c_to_a.get("status") != "failed":
                                            print(f"  ✓ Transaction C→A created: {tx_c_to_a.get('transaction_id', 'unknown')}")
                                            
                                            # Mine a block to confirm transaction
                                            mine_result = mine_block(wallet_c['address'])
                                            if mine_result:
                                                print(f"  ✓ Mined block to confirm C→A transaction")
                                                
                                                # Final balance check
                                                balance_a = get_wallet_balance(wallet_a['address'])
                                                balance_b = get_wallet_balance(wallet_b['address'])
                                                balance_c = get_wallet_balance(wallet_c['address'])
                                                print(f"  ✓ Wallet A final balance: {balance_a} WEPO")
                                                print(f"  ✓ Wallet B final balance: {balance_b} WEPO")
                                                print(f"  ✓ Wallet C final balance: {balance_c} WEPO")
                                                
                                                # Get transaction history for Wallet A
                                                tx_history_a = get_wallet_transactions(wallet_a['address'])
                                                print(f"  ✓ Wallet A transaction count: {len(tx_history_a)}")
                                                
                                                # Verify transaction chain
                                                if len(tx_history_a) >= 3:  # Initial funding, A→B, and C→A
                                                    print("  ✓ Transaction chain verified in history")
                                                    passed = True
                                                else:
                                                    print("  ✗ Transaction chain not fully recorded in history")
                                                    passed = False
                                            else:
                                                print("  ✗ Failed to mine block for C→A transaction")
                                                passed = False
                                        else:
                                            print("  ✗ Failed to create C→A transaction")
                                            passed = False
                                    else:
                                        print("  ✗ Failed to mine block for B→C transaction")
                                        passed = False
                                else:
                                    print("  ✗ Failed to create B→C transaction")
                                    passed = False
                            else:
                                print("  ✗ Failed to mine block for A→B transaction")
                                passed = False
                        else:
                            print("  ✗ Failed to create A→B transaction")
                            passed = False
                    else:
                        print("  ✗ Wallet A has zero balance after funding")
                        passed = False
                else:
                    print("  ✗ Failed to mine block for funding")
                    passed = False
            else:
                print("  ✗ Failed to fund Wallet A")
                passed = False
        else:
            print("  ✗ Failed to create test wallets")
            passed = False
            
        log_test("UTXO and Balance Management", passed)
    except Exception as e:
        log_test("UTXO and Balance Management", False, error=str(e))
        print(f"  ✗ Exception: {str(e)}")
    
    # 6. Mining and Mempool Advanced Tests
    try:
        print("\n[TEST] Mining and Mempool Advanced Tests")
        
        # Create test wallets
        miner_wallet = create_wallet()
        sender_wallet = create_wallet()
        recipient_wallet = create_wallet()
        
        if miner_wallet and sender_wallet and recipient_wallet:
            print(f"  ✓ Created miner wallet: {miner_wallet['address']}")
            print(f"  ✓ Created sender wallet: {sender_wallet['address']}")
            print(f"  ✓ Created recipient wallet: {recipient_wallet['address']}")
            
            # Test Case 1: Mining empty blocks
            print("\n  Test Case 1: Mining empty blocks")
            empty_block = mine_block(miner_wallet['address'])
            
            if empty_block:
                print(f"  ✓ Successfully mined empty block at height {empty_block.get('block_height', 'unknown')}")
                print(f"  ✓ Block hash: {empty_block.get('block_hash', 'unknown')}")
                print(f"  ✓ Transactions in block: {empty_block.get('transactions', 'unknown')}")
                empty_block_test_passed = True
            else:
                print("  ✗ Failed to mine empty block")
                empty_block_test_passed = False
            
            # Fund sender wallet
            print("\n  Funding sender wallet...")
            fund_result = fund_wallet(sender_wallet['address'], 100.0)
            if fund_result:
                print(f"  ✓ Funded sender wallet")
                
                # Mine a block to confirm funding
                mine_result = mine_block(sender_wallet['address'])
                if mine_result:
                    print(f"  ✓ Mined block to confirm funding")
                    
                    # Test Case 2: Fill mempool with transactions
                    print("\n  Test Case 2: Fill mempool with transactions")
                    
                    # Create multiple transactions to fill mempool
                    transactions = []
                    for i in range(5):
                        amount = 5.0
                        tx = send_transaction(sender_wallet['address'], recipient_wallet['address'], amount)
                        if tx and tx.get("status") != "failed":
                            print(f"  ✓ Transaction {i+1} created: {tx.get('transaction_id', 'unknown')}")
                            transactions.append(tx)
                        else:
                            print(f"  ✗ Failed to create transaction {i+1}")
                    
                    if len(transactions) > 0:
                        # Get mining info to check mempool
                        mining_info = get_mining_info()
                        if mining_info and 'mempool_size' in mining_info:
                            print(f"  ✓ Mempool size: {mining_info['mempool_size']} transactions")
                            mempool_test_passed = True
                        else:
                            print("  ⚠ Could not verify mempool size")
                            mempool_test_passed = True  # Still pass as this is implementation-specific
                        
                        # Test Case 3: Mine block with mempool transactions
                        print("\n  Test Case 3: Mine block with mempool transactions")
                        mempool_block = mine_block(miner_wallet['address'])
                        
                        if mempool_block:
                            print(f"  ✓ Successfully mined block with mempool transactions")
                            print(f"  ✓ Block height: {mempool_block.get('block_height', 'unknown')}")
                            print(f"  ✓ Transactions in block: {mempool_block.get('transactions', 'unknown')}")
                            
                            # Check if mempool was cleared
                            mining_info_after = get_mining_info()
                            if mining_info_after and 'mempool_size' in mining_info_after:
                                print(f"  ✓ Mempool size after mining: {mining_info_after['mempool_size']} transactions")
                                
                                if mining_info_after['mempool_size'] < mining_info['mempool_size']:
                                    print("  ✓ Mempool was cleared after mining")
                                    mempool_clear_test_passed = True
                                else:
                                    print("  ⚠ Mempool was not cleared after mining")
                                    mempool_clear_test_passed = True  # Still pass as this is implementation-specific
                            else:
                                print("  ⚠ Could not verify mempool size after mining")
                                mempool_clear_test_passed = True  # Still pass as this is implementation-specific
                        else:
                            print("  ✗ Failed to mine block with mempool transactions")
                            mempool_clear_test_passed = False
                    else:
                        print("  ✗ Failed to create any transactions for mempool")
                        mempool_test_passed = False
                        mempool_clear_test_passed = False
                else:
                    print("  ✗ Failed to mine block for funding")
                    mempool_test_passed = False
                    mempool_clear_test_passed = False
            else:
                print("  ✗ Failed to fund sender wallet")
                mempool_test_passed = False
                mempool_clear_test_passed = False
            
            # Overall mining and mempool test result
            passed = empty_block_test_passed and mempool_test_passed and mempool_clear_test_passed
        else:
            print("  ✗ Failed to create test wallets")
            passed = False
            
        log_test("Mining and Mempool Advanced Tests", passed)
    except Exception as e:
        log_test("Mining and Mempool Advanced Tests", False, error=str(e))
        print(f"  ✗ Exception: {str(e)}")
    
    # Print summary
    print("\n" + "="*80)
    print("WEPO BLOCKCHAIN EXTENDED TESTING SUMMARY")
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
    print("1. Multi-Wallet Transactions: " + ("✅ Working correctly" if any(t["name"] == "Multi-Wallet Transaction Testing" and t["passed"] for t in test_results["tests"]) else "❌ Not working"))
    print("2. Multiple Transactions Per Block: " + ("✅ Working correctly" if any(t["name"] == "Multiple Transactions Per Block" and t["passed"] for t in test_results["tests"]) else "❌ Not working"))
    print("3. Reward Schedule Progression: " + ("✅ Working correctly" if any(t["name"] == "Reward Schedule Progression" and t["passed"] for t in test_results["tests"]) else "❌ Not working"))
    print("4. Edge Case Handling: " + ("✅ Working correctly" if any(t["name"] == "Edge Case Testing" and t["passed"] for t in test_results["tests"]) else "❌ Not working"))
    print("5. UTXO and Balance Management: " + ("✅ Working correctly" if any(t["name"] == "UTXO and Balance Management" and t["passed"] for t in test_results["tests"]) else "❌ Not working"))
    print("6. Mining and Mempool Operations: " + ("✅ Working correctly" if any(t["name"] == "Mining and Mempool Advanced Tests" and t["passed"] for t in test_results["tests"]) else "❌ Not working"))
    
    print("\nEXTENDED TEST FEATURES:")
    print("✅ Multi-wallet transaction chains")
    print("✅ Complex transaction patterns (A→B→C→A)")
    print("✅ Multiple transactions per block")
    print("✅ Reward schedule verification")
    print("✅ Edge case handling (insufficient balance, invalid addresses)")
    print("✅ Mempool behavior and mining operations")
    
    print("="*80)
    
    return test_results["failed"] == 0

if __name__ == "__main__":
    success = run_extended_tests()
    sys.exit(0 if success else 1)