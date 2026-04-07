#!/usr/bin/env python3
"""
WEPO Blockchain Final Comprehensive Test
This script performs a complete verification of the WEPO blockchain system
after all fixes have been implemented.
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

def run_final_tests():
    """Run final comprehensive tests for WEPO blockchain"""
    print("\n" + "="*80)
    print("WEPO BLOCKCHAIN FINAL COMPREHENSIVE TEST")
    print("="*80)
    print("Verifying the entire blockchain system after all fixes")
    print("="*80 + "\n")
    
    # 1. System Status Verification
    try:
        print("\n" + "="*60)
        print("1. SYSTEM STATUS VERIFICATION")
        print("="*60)
        
        # Check blockchain status
        network_status = get_network_status()
        if network_status:
            print(f"Network Status: {json.dumps(network_status, indent=2)}")
            
            if "block_height" in network_status:
                print(f"✓ Block height: {network_status['block_height']}")
                if network_status["block_height"] >= 0:
                    print(f"✓ Genesis block exists (height 0 or greater)")
                    blockchain_ready = True
                else:
                    print(f"✗ No genesis block found")
                    blockchain_ready = False
            else:
                print("✗ Block height information missing")
                blockchain_ready = False
            
            # Check mining info for Q1 rewards
            mining_info = get_mining_info()
            if mining_info:
                print(f"Mining Info: {json.dumps(mining_info, indent=2)}")
                
                if "current_reward" in mining_info:
                    print(f"✓ Current mining reward: {mining_info['current_reward']} WEPO")
                    
                    # Check for Q1 rewards (400 WEPO per block)
                    if mining_info["current_reward"] == 400.0:
                        print("✓ Q1 rewards confirmed (400 WEPO per block)")
                        rewards_correct = True
                    else:
                        print(f"✗ Mining reward {mining_info['current_reward']} doesn't match expected Q1 value (400 WEPO)")
                        rewards_correct = False
                else:
                    print("✗ Mining reward information missing")
                    rewards_correct = False
            else:
                print("✗ Failed to get mining info")
                rewards_correct = False
            
            system_status_passed = blockchain_ready and rewards_correct
            log_test("System Status Verification", system_status_passed)
        else:
            log_test("System Status Verification", False, error="Failed to get network status")
    except Exception as e:
        log_test("System Status Verification", False, error=str(e))
        print(f"✗ Exception: {str(e)}")
    
    # 2. Complete Transaction Flow Test
    try:
        print("\n" + "="*60)
        print("2. COMPLETE TRANSACTION FLOW TEST")
        print("="*60)
        
        # Create multiple test wallets
        print("Creating multiple test wallets...")
        wallet_a = create_wallet()
        wallet_b = create_wallet()
        wallet_c = create_wallet()
        
        if wallet_a and wallet_b and wallet_c:
            print(f"✓ Created Wallet A: {wallet_a['address']}")
            print(f"✓ Created Wallet B: {wallet_b['address']}")
            print(f"✓ Created Wallet C: {wallet_c['address']}")
            
            # Fund Wallet A
            print("\nFunding Wallet A...")
            fund_result = fund_wallet(wallet_a['address'], 500.0)
            if fund_result:
                print(f"✓ Funded Wallet A")
                
                # Mine a block to confirm funding
                mine_result = mine_block(wallet_a['address'])
                if mine_result:
                    print(f"✓ Mined block to confirm funding")
                    print(f"✓ Mining reward: {mine_result.get('reward', 'unknown')} WEPO")
                    
                    # Check Wallet A balance
                    balance_a = get_wallet_balance(wallet_a['address'])
                    print(f"✓ Wallet A balance: {balance_a} WEPO")
                    
                    if balance_a > 0:
                        # Send from A to B
                        print("\nSending 50 WEPO from Wallet A to Wallet B...")
                        tx_a_to_b = send_transaction(wallet_a['address'], wallet_b['address'], 50.0)
                        
                        if tx_a_to_b and tx_a_to_b.get("status") != "failed":
                            print(f"✓ Transaction A→B created: {tx_a_to_b.get('transaction_id', 'unknown')}")
                            
                            # Send from A to C
                            print("\nSending 30 WEPO from Wallet A to Wallet C...")
                            tx_a_to_c = send_transaction(wallet_a['address'], wallet_c['address'], 30.0)
                            
                            if tx_a_to_c and tx_a_to_c.get("status") != "failed":
                                print(f"✓ Transaction A→C created: {tx_a_to_c.get('transaction_id', 'unknown')}")
                                
                                # Mine a block to confirm transactions
                                print("\nMining block to confirm transactions...")
                                mine_result = mine_block(wallet_a['address'])
                                
                                if mine_result:
                                    print(f"✓ Mined block with transactions")
                                    print(f"✓ Transactions in block: {mine_result.get('transactions', 'unknown')}")
                                    
                                    # Check all wallet balances
                                    time.sleep(1)  # Give time for balances to update
                                    balance_a_after = get_wallet_balance(wallet_a['address'])
                                    balance_b = get_wallet_balance(wallet_b['address'])
                                    balance_c = get_wallet_balance(wallet_c['address'])
                                    
                                    print(f"✓ Wallet A balance after transfers: {balance_a_after} WEPO")
                                    print(f"✓ Wallet B balance: {balance_b} WEPO")
                                    print(f"✓ Wallet C balance: {balance_c} WEPO")
                                    
                                    # Check transaction history
                                    tx_history_a = get_wallet_transactions(wallet_a['address'])
                                    tx_history_b = get_wallet_transactions(wallet_b['address'])
                                    tx_history_c = get_wallet_transactions(wallet_c['address'])
                                    
                                    print(f"✓ Wallet A transaction count: {len(tx_history_a)}")
                                    print(f"✓ Wallet B transaction count: {len(tx_history_b)}")
                                    print(f"✓ Wallet C transaction count: {len(tx_history_c)}")
                                    
                                    # Verify transaction flow
                                    transaction_flow_passed = (
                                        balance_b > 0 and  # B received funds
                                        balance_c > 0 and  # C received funds
                                        balance_a_after < balance_a  # A sent funds
                                    )
                                    
                                    if transaction_flow_passed:
                                        print("✓ Complete transaction flow verified")
                                    else:
                                        print("✗ Transaction flow verification failed")
                                else:
                                    print("✗ Failed to mine block with transactions")
                                    transaction_flow_passed = False
                            else:
                                print("✗ Failed to create transaction A→C")
                                transaction_flow_passed = False
                        else:
                            print("✗ Failed to create transaction A→B")
                            transaction_flow_passed = False
                    else:
                        print("✗ Wallet A has zero balance after funding")
                        transaction_flow_passed = False
                else:
                    print("✗ Failed to mine block for funding")
                    transaction_flow_passed = False
            else:
                print("✗ Failed to fund Wallet A")
                transaction_flow_passed = False
        else:
            print("✗ Failed to create test wallets")
            transaction_flow_passed = False
            
        log_test("Complete Transaction Flow", transaction_flow_passed)
    except Exception as e:
        log_test("Complete Transaction Flow", False, error=str(e))
        print(f"✗ Exception: {str(e)}")
    
    # 3. Edge Case Validation
    try:
        print("\n" + "="*60)
        print("3. EDGE CASE VALIDATION")
        print("="*60)
        
        # Create test wallets
        sender_wallet = create_wallet()
        recipient_wallet = create_wallet()
        
        if sender_wallet and recipient_wallet:
            print(f"✓ Created sender wallet: {sender_wallet['address']}")
            print(f"✓ Created recipient wallet: {recipient_wallet['address']}")
            
            # Fund sender wallet with small amount
            print("\nFunding sender wallet with small amount...")
            fund_result = fund_wallet(sender_wallet['address'], 10.0)
            if fund_result:
                print(f"✓ Funded sender wallet")
                
                # Mine a block to confirm funding
                mine_result = mine_block(sender_wallet['address'])
                if mine_result:
                    print(f"✓ Mined block to confirm funding")
                    
                    # Check sender wallet balance
                    sender_balance = get_wallet_balance(sender_wallet['address'])
                    print(f"✓ Sender wallet balance: {sender_balance} WEPO")
                    
                    # Test Case 1: Insufficient balance transaction
                    print("\nTest Case 1: Insufficient balance transaction")
                    tx_insufficient = send_transaction(sender_wallet['address'], recipient_wallet['address'], sender_balance + 10.0)
                    
                    if tx_insufficient.get("status") == "failed" or "error" in tx_insufficient:
                        print(f"✓ Insufficient balance transaction correctly rejected")
                        insufficient_test_passed = True
                    else:
                        print(f"✗ Insufficient balance transaction was accepted")
                        insufficient_test_passed = False
                    
                    # Test Case 2: Zero amount transaction
                    print("\nTest Case 2: Zero amount transaction")
                    tx_zero = send_transaction(sender_wallet['address'], recipient_wallet['address'], 0.0)
                    
                    if tx_zero.get("status") == "failed" or "error" in tx_zero:
                        print(f"✓ Zero amount transaction correctly rejected")
                        zero_test_passed = True
                    else:
                        print(f"✗ Zero amount transaction was accepted")
                        zero_test_passed = False
                    
                    # Test Case 3: Invalid recipient address
                    print("\nTest Case 3: Invalid recipient address")
                    tx_invalid = send_transaction(sender_wallet['address'], "invalid_address", 1.0)
                    
                    if tx_invalid.get("status") == "failed" or "error" in tx_invalid:
                        print(f"✓ Invalid recipient address transaction correctly rejected")
                        invalid_test_passed = True
                    else:
                        print(f"✗ Invalid recipient address transaction was accepted")
                        invalid_test_passed = False
                    
                    # Test Case 4: Multiple transactions per block
                    print("\nTest Case 4: Multiple transactions per block")
                    
                    # Create multiple valid transactions
                    valid_txs = []
                    for i in range(3):
                        amount = 1.0
                        if sender_balance >= amount * (i + 1):
                            tx = send_transaction(sender_wallet['address'], recipient_wallet['address'], amount)
                            if tx and tx.get("status") != "failed":
                                print(f"✓ Valid transaction {i+1} created: {tx.get('transaction_id', 'unknown')}")
                                valid_txs.append(tx)
                            else:
                                print(f"✗ Failed to create valid transaction {i+1}")
                    
                    if len(valid_txs) > 1:
                        # Mine a block to confirm multiple transactions
                        mine_result = mine_block(sender_wallet['address'])
                        if mine_result:
                            print(f"✓ Mined block with multiple transactions")
                            print(f"✓ Transactions in block: {mine_result.get('transactions', 'unknown')}")
                            multi_tx_test_passed = True
                        else:
                            print("✗ Failed to mine block with multiple transactions")
                            multi_tx_test_passed = False
                    else:
                        print("✗ Failed to create multiple valid transactions")
                        multi_tx_test_passed = False
                    
                    # Overall edge case test result
                    edge_case_passed = insufficient_test_passed and zero_test_passed and invalid_test_passed and multi_tx_test_passed
                else:
                    print("✗ Failed to mine block for funding")
                    edge_case_passed = False
            else:
                print("✗ Failed to fund sender wallet")
                edge_case_passed = False
        else:
            print("✗ Failed to create test wallets")
            edge_case_passed = False
            
        log_test("Edge Case Validation", edge_case_passed)
    except Exception as e:
        log_test("Edge Case Validation", False, error=str(e))
        print(f"✗ Exception: {str(e)}")
    
    # 4. Mining and Rewards Verification
    try:
        print("\n" + "="*60)
        print("4. MINING AND REWARDS VERIFICATION")
        print("="*60)
        
        # Create a miner wallet
        miner_wallet = create_wallet()
        if miner_wallet:
            print(f"✓ Created miner wallet: {miner_wallet['address']}")
            
            # Get current mining info
            mining_info = get_mining_info()
            if mining_info:
                print(f"Mining Info: {json.dumps(mining_info, indent=2)}")
                
                if "current_reward" in mining_info:
                    print(f"✓ Current mining reward: {mining_info['current_reward']} WEPO")
                    
                    # Check for Q1 rewards (400 WEPO per block)
                    if mining_info["current_reward"] == 400.0:
                        print("✓ Q1 rewards confirmed (400 WEPO per block)")
                        q1_rewards_correct = True
                    else:
                        print(f"✗ Mining reward {mining_info['current_reward']} doesn't match expected Q1 value (400 WEPO)")
                        q1_rewards_correct = False
                else:
                    print("✗ Mining reward information missing")
                    q1_rewards_correct = False
                
                # Mine a block and check reward
                mine_result = mine_block(miner_wallet['address'])
                if mine_result:
                    print(f"✓ Mined block at height {mine_result.get('block_height', 'unknown')}")
                    print(f"✓ Mining reward: {mine_result.get('reward', 'unknown')} WEPO")
                    
                    # Verify reward matches expected value
                    expected_reward = mining_info.get("current_reward", 400.0)
                    actual_reward = mine_result.get('reward', 0)
                    
                    if abs(actual_reward - expected_reward) < 0.1:
                        print(f"✓ Mining reward matches expected value")
                        reward_match = True
                    else:
                        print(f"✗ Mining reward {actual_reward} doesn't match expected value {expected_reward}")
                        reward_match = False
                    
                    # Check mempool operations
                    # Create a transaction to test mempool
                    recipient_wallet = create_wallet()
                    if recipient_wallet:
                        print(f"✓ Created recipient wallet: {recipient_wallet['address']}")
                        
                        # Fund miner wallet to send a transaction
                        fund_result = fund_wallet(miner_wallet['address'], 50.0)
                        if fund_result:
                            print(f"✓ Funded miner wallet")
                            
                            # Mine a block to confirm funding
                            mine_result = mine_block(miner_wallet['address'])
                            if mine_result:
                                print(f"✓ Mined block to confirm funding")
                                
                                # Create a transaction to test mempool
                                tx = send_transaction(miner_wallet['address'], recipient_wallet['address'], 10.0)
                                if tx and tx.get("status") != "failed":
                                    print(f"✓ Transaction created: {tx.get('transaction_id', 'unknown')}")
                                    print(f"✓ Transaction status: {tx.get('status', 'unknown')}")
                                    
                                    # Check if transaction is in mempool
                                    if tx.get("status") == "pending":
                                        print("✓ Transaction is in mempool (pending)")
                                        mempool_working = True
                                    else:
                                        print("✗ Transaction not in mempool")
                                        mempool_working = False
                                    
                                    # Mine a block to confirm transaction
                                    mine_result = mine_block(miner_wallet['address'])
                                    if mine_result:
                                        print(f"✓ Mined block to confirm transaction")
                                        print(f"✓ Transactions in block: {mine_result.get('transactions', 'unknown')}")
                                        
                                        # Check if transaction was confirmed
                                        recipient_balance = get_wallet_balance(recipient_wallet['address'])
                                        print(f"✓ Recipient balance: {recipient_balance} WEPO")
                                        
                                        if recipient_balance > 0:
                                            print("✓ Transaction confirmed and balance updated")
                                            tx_confirmed = True
                                        else:
                                            print("✗ Transaction not confirmed or balance not updated")
                                            tx_confirmed = False
                                    else:
                                        print("✗ Failed to mine block to confirm transaction")
                                        tx_confirmed = False
                                else:
                                    print("✗ Failed to create transaction")
                                    mempool_working = False
                                    tx_confirmed = False
                            else:
                                print("✗ Failed to mine block for funding")
                                mempool_working = False
                                tx_confirmed = False
                        else:
                            print("✗ Failed to fund miner wallet")
                            mempool_working = False
                            tx_confirmed = False
                    else:
                        print("✗ Failed to create recipient wallet")
                        mempool_working = False
                        tx_confirmed = False
                else:
                    print("✗ Failed to mine block")
                    reward_match = False
                    mempool_working = False
                    tx_confirmed = False
            else:
                print("✗ Failed to get mining info")
                q1_rewards_correct = False
                reward_match = False
                mempool_working = False
                tx_confirmed = False
        else:
            print("✗ Failed to create miner wallet")
            q1_rewards_correct = False
            reward_match = False
            mempool_working = False
            tx_confirmed = False
        
        mining_rewards_passed = q1_rewards_correct and reward_match and mempool_working and tx_confirmed
        log_test("Mining and Rewards Verification", mining_rewards_passed)
    except Exception as e:
        log_test("Mining and Rewards Verification", False, error=str(e))
        print(f"✗ Exception: {str(e)}")
    
    # 5. Integration Health Check
    try:
        print("\n" + "="*60)
        print("5. INTEGRATION HEALTH CHECK")
        print("="*60)
        
        # Test API response times
        print("Testing API response times...")
        
        start_time = time.time()
        network_status = get_network_status()
        network_time = time.time() - start_time
        print(f"✓ Network status API response time: {network_time:.4f} seconds")
        
        start_time = time.time()
        mining_info = get_mining_info()
        mining_time = time.time() - start_time
        print(f"✓ Mining info API response time: {mining_time:.4f} seconds")
        
        # Create a test wallet for response time testing
        test_wallet = create_wallet()
        if test_wallet:
            print(f"✓ Created test wallet: {test_wallet['address']}")
            
            start_time = time.time()
            wallet_info = requests.get(f"{API_URL}/wallet/{test_wallet['address']}")
            wallet_time = time.time() - start_time
            print(f"✓ Wallet info API response time: {wallet_time:.4f} seconds")
            
            start_time = time.time()
            tx_history = requests.get(f"{API_URL}/wallet/{test_wallet['address']}/transactions")
            tx_history_time = time.time() - start_time
            print(f"✓ Transaction history API response time: {tx_history_time:.4f} seconds")
            
            # Check error handling
            print("\nTesting error handling...")
            
            # Test invalid wallet address
            response = requests.get(f"{API_URL}/wallet/invalid_address")
            if response.status_code == 404:
                print(f"✓ Invalid wallet address correctly returns 404")
                error_handling_1 = True
            else:
                print(f"✗ Invalid wallet address returns {response.status_code} instead of 404")
                error_handling_1 = False
            
            # Test invalid transaction
            invalid_tx = {
                "from_address": "invalid_address",
                "to_address": test_wallet['address'],
                "amount": 10.0,
                "password_hash": "test_password_hash"
            }
            
            response = requests.post(f"{API_URL}/transaction/send", json=invalid_tx)
            if response.status_code >= 400:
                print(f"✓ Invalid transaction correctly returns error {response.status_code}")
                error_handling_2 = True
            else:
                print(f"✗ Invalid transaction returns {response.status_code} instead of error")
                error_handling_2 = False
            
            # Check system stability
            print("\nTesting system stability...")
            
            # Mine multiple blocks in succession
            success_count = 0
            for i in range(3):
                mine_result = mine_block(test_wallet['address'])
                if mine_result:
                    success_count += 1
                    print(f"✓ Successfully mined block {i+1}")
                else:
                    print(f"✗ Failed to mine block {i+1}")
            
            if success_count == 3:
                print("✓ System stable for multiple mining operations")
                stability_test = True
            else:
                print(f"✗ System unstable, only {success_count}/3 mining operations succeeded")
                stability_test = False
            
            # Overall integration health
            response_times_ok = (
                network_time < 2.0 and
                mining_time < 2.0 and
                wallet_time < 2.0 and
                tx_history_time < 2.0
            )
            
            error_handling_ok = error_handling_1 and error_handling_2
            
            integration_health_passed = response_times_ok and error_handling_ok and stability_test
        else:
            print("✗ Failed to create test wallet")
            integration_health_passed = False
            
        log_test("Integration Health Check", integration_health_passed)
    except Exception as e:
        log_test("Integration Health Check", False, error=str(e))
        print(f"✗ Exception: {str(e)}")
    
    # Print summary
    print("\n" + "="*80)
    print("WEPO BLOCKCHAIN FINAL COMPREHENSIVE TEST SUMMARY")
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
    print("1. System Status: " + ("✅ Blockchain ready and responsive" if any(t["name"] == "System Status Verification" and t["passed"] for t in test_results["tests"]) else "❌ Issues detected"))
    print("2. Transaction Flow: " + ("✅ Complete flow operational" if any(t["name"] == "Complete Transaction Flow" and t["passed"] for t in test_results["tests"]) else "❌ Issues detected"))
    print("3. Edge Case Handling: " + ("✅ Properly rejecting invalid transactions" if any(t["name"] == "Edge Case Validation" and t["passed"] for t in test_results["tests"]) else "❌ Issues detected"))
    print("4. Mining Rewards: " + ("✅ Correctly configured (400 WEPO Q1)" if any(t["name"] == "Mining and Rewards Verification" and t["passed"] for t in test_results["tests"]) else "❌ Issues detected"))
    print("5. System Integration: " + ("✅ Stable and responsive" if any(t["name"] == "Integration Health Check" and t["passed"] for t in test_results["tests"]) else "❌ Issues detected"))
    
    print("\nSYSTEM READINESS:")
    if test_results["failed"] == 0:
        print("✅ WEPO blockchain system is operational in current testing and not approved for production use")
        print("✅ All critical issues from extended testing have been resolved")
        print("✅ System is ready for frontend integration")
    else:
        print("❌ WEPO blockchain system still has issues that need to be addressed")
        print(f"❌ {test_results['failed']} test(s) failed")
    
    print("="*80)
    
    return test_results["failed"] == 0

if __name__ == "__main__":
    success = run_final_tests()
    sys.exit(0 if success else 1)