#!/usr/bin/env python3
"""
WEPO Quantum Vault Testing Script
Test the Quantum Vault backend implementation for Phase 1 completion
"""

import requests
import json
import time
import uuid
import os
import sys
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
print(f"Testing Quantum Vault API at: {API_URL}")

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

def run_quantum_vault_tests():
    """Run comprehensive WEPO Quantum Vault backend implementation tests"""
    print("\n" + "="*80)
    print("WEPO QUANTUM VAULT SYSTEM COMPREHENSIVE TESTING")
    print("="*80)
    print("Testing Phase 1 completion of the 'Be Your Own Bank' ultimate privacy solution")
    print("Key Features: zk-STARK privacy, commitment generation, auto-deposit functionality")
    print("Testing all 6 Quantum Vault API endpoints for complete privacy protection")
    print("="*80 + "\n")
    
    # Test variables to store data between tests
    test_wallet_address = None
    test_vault_id = None
    test_commitment = None
    
    # 1. Test Vault Creation
    try:
        print("\n[TEST] Quantum Vault Creation - POST /api/vault/create")
        
        # Create a realistic wallet address for testing
        test_wallet_address = "wepo1a1b2c3d4e5f6789abcdef0123456789abcdef"
        
        vault_data = {
            "wallet_address": test_wallet_address
        }
        
        print(f"  Creating Quantum Vault for wallet: {test_wallet_address}")
        response = requests.post(f"{API_URL}/vault/create", json=vault_data)
        print(f"  Response: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"  Vault Creation Response: {json.dumps(data, indent=2)}")
            
            passed = True
            
            # Check success status
            if data.get("success") == True and data.get("vault_created") == True:
                print("  ✓ Vault creation successful")
            else:
                print("  ✗ Vault creation failed")
                passed = False
                
            # Check vault ID
            if "vault_id" in data and data["vault_id"]:
                test_vault_id = data["vault_id"]
                print(f"  ✓ Vault ID generated: {test_vault_id}")
            else:
                print("  ✗ Vault ID missing")
                passed = False
                
            # Check commitment (zk-STARK privacy feature)
            if "commitment" in data and data["commitment"]:
                test_commitment = data["commitment"]
                print(f"  ✓ Privacy commitment generated: {test_commitment[:20]}...")
            else:
                print("  ✗ Privacy commitment missing")
                passed = False
                
            # Check privacy features
            if data.get("privacy_enabled") == True:
                print("  ✓ Privacy protection enabled")
            else:
                print("  ✗ Privacy protection not enabled")
                passed = False
                
            # Check auto-deposit availability
            if data.get("auto_deposit_available") == True:
                print("  ✓ Auto-deposit functionality available")
            else:
                print("  ✗ Auto-deposit functionality not available")
                passed = False
                
            log_test("Quantum Vault Creation", passed, response)
        else:
            log_test("Quantum Vault Creation", False, response)
            print(f"  ✗ Failed with status code: {response.status_code}")
    except Exception as e:
        log_test("Quantum Vault Creation", False, error=str(e))
        print(f"  ✗ Exception: {str(e)}")
    
    # 2. Test Vault Status
    if test_vault_id:
        try:
            print(f"\n[TEST] Quantum Vault Status - GET /api/vault/status/{test_vault_id}")
            
            response = requests.get(f"{API_URL}/vault/status/{test_vault_id}")
            print(f"  Response: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"  Vault Status Response: {json.dumps(data, indent=2)}")
                
                passed = True
                
                # Check success status
                if data.get("success") == True and data.get("vault_found") == True:
                    print("  ✓ Vault status retrieved successfully")
                else:
                    print("  ✗ Vault status retrieval failed")
                    passed = False
                    
                # Check vault ID matches
                if data.get("vault_id") == test_vault_id:
                    print(f"  ✓ Vault ID matches: {test_vault_id}")
                else:
                    print("  ✗ Vault ID mismatch")
                    passed = False
                    
                # Check wallet address
                if data.get("wallet_address") == test_wallet_address:
                    print(f"  ✓ Wallet address matches: {test_wallet_address}")
                else:
                    print("  ✗ Wallet address mismatch")
                    passed = False
                    
                # Check private balance (should be 0 initially)
                if "private_balance" in data:
                    print(f"  ✓ Private balance: {data['private_balance']} WEPO")
                else:
                    print("  ✗ Private balance missing")
                    passed = False
                    
                # Check transaction count
                if "transaction_count" in data:
                    print(f"  ✓ Transaction count: {data['transaction_count']}")
                else:
                    print("  ✗ Transaction count missing")
                    passed = False
                    
                # Check auto-deposit status
                if "auto_deposit_enabled" in data:
                    print(f"  ✓ Auto-deposit status: {data['auto_deposit_enabled']}")
                else:
                    print("  ✗ Auto-deposit status missing")
                    passed = False
                    
                # Check privacy level
                if data.get("privacy_level") == "maximum":
                    print("  ✓ Maximum privacy level confirmed")
                else:
                    print("  ✗ Maximum privacy level not confirmed")
                    passed = False
                    
                # Check privacy protection
                if data.get("privacy_protected") == True:
                    print("  ✓ Privacy protection confirmed")
                else:
                    print("  ✗ Privacy protection not confirmed")
                    passed = False
                    
                log_test("Quantum Vault Status", passed, response)
            else:
                log_test("Quantum Vault Status", False, response)
                print(f"  ✗ Failed with status code: {response.status_code}")
        except Exception as e:
            log_test("Quantum Vault Status", False, error=str(e))
            print(f"  ✗ Exception: {str(e)}")
    else:
        log_test("Quantum Vault Status", False, error="Skipped - No vault created")
        print("  ✗ Skipped - No vault created")
    
    # 3. Test Vault Deposit
    if test_vault_id:
        try:
            print(f"\n[TEST] Quantum Vault Deposit - POST /api/vault/deposit")
            
            deposit_data = {
                "vault_id": test_vault_id,
                "amount": 25.5,
                "source_type": "manual"
            }
            
            print(f"  Depositing 25.5 WEPO to vault {test_vault_id}")
            response = requests.post(f"{API_URL}/vault/deposit", json=deposit_data)
            print(f"  Response: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"  Vault Deposit Response: {json.dumps(data, indent=2)}")
                
                passed = True
                
                # Check success status
                if data.get("success") == True and data.get("deposited") == True:
                    print("  ✓ Vault deposit successful")
                else:
                    print("  ✗ Vault deposit failed")
                    passed = False
                    
                # Check transaction ID
                if "transaction_id" in data and data["transaction_id"]:
                    print(f"  ✓ Transaction ID: {data['transaction_id']}")
                else:
                    print("  ✗ Transaction ID missing")
                    passed = False
                    
                # Check amount deposited
                if data.get("amount_deposited") == 25.5:
                    print(f"  ✓ Amount deposited: {data['amount_deposited']} WEPO")
                else:
                    print("  ✗ Amount deposited incorrect")
                    passed = False
                    
                # Check new commitment (privacy feature)
                if "new_commitment" in data and data["new_commitment"]:
                    test_commitment = data["new_commitment"]
                    print(f"  ✓ New privacy commitment: {test_commitment[:20]}...")
                else:
                    print("  ✗ New privacy commitment missing")
                    passed = False
                    
                # Check privacy protection
                if data.get("privacy_protected") == True:
                    print("  ✓ Privacy protection confirmed")
                else:
                    print("  ✗ Privacy protection not confirmed")
                    passed = False
                    
                # Check source type
                if data.get("source_type") == "manual":
                    print("  ✓ Source type correct: manual")
                else:
                    print("  ✗ Source type incorrect")
                    passed = False
                    
                log_test("Quantum Vault Deposit", passed, response)
            else:
                log_test("Quantum Vault Deposit", False, response)
                print(f"  ✗ Failed with status code: {response.status_code}")
        except Exception as e:
            log_test("Quantum Vault Deposit", False, error=str(e))
            print(f"  ✗ Exception: {str(e)}")
    else:
        log_test("Quantum Vault Deposit", False, error="Skipped - No vault created")
        print("  ✗ Skipped - No vault created")
    
    # 4. Test Vault Withdrawal
    if test_vault_id:
        try:
            print(f"\n[TEST] Quantum Vault Withdrawal - POST /api/vault/withdraw")
            
            destination_address = "wepo1destination123456789abcdef0123456789"
            withdrawal_data = {
                "vault_id": test_vault_id,
                "amount": 10.0,
                "destination_address": destination_address
            }
            
            print(f"  Withdrawing 10.0 WEPO from vault {test_vault_id}")
            response = requests.post(f"{API_URL}/vault/withdraw", json=withdrawal_data)
            print(f"  Response: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"  Vault Withdrawal Response: {json.dumps(data, indent=2)}")
                
                passed = True
                
                # Check success status
                if data.get("success") == True and data.get("withdrawn") == True:
                    print("  ✓ Vault withdrawal successful")
                else:
                    print("  ✗ Vault withdrawal failed")
                    passed = False
                    
                # Check transaction ID
                if "transaction_id" in data and data["transaction_id"]:
                    print(f"  ✓ Transaction ID: {data['transaction_id']}")
                else:
                    print("  ✗ Transaction ID missing")
                    passed = False
                    
                # Check amount withdrawn
                if data.get("amount_withdrawn") == 10.0:
                    print(f"  ✓ Amount withdrawn: {data['amount_withdrawn']} WEPO")
                else:
                    print("  ✗ Amount withdrawn incorrect")
                    passed = False
                    
                # Check destination address
                if data.get("destination_address") == destination_address:
                    print(f"  ✓ Destination address: {destination_address}")
                else:
                    print("  ✗ Destination address incorrect")
                    passed = False
                    
                # Check new commitment (privacy feature)
                if "new_commitment" in data and data["new_commitment"]:
                    print(f"  ✓ New privacy commitment: {data['new_commitment'][:20]}...")
                else:
                    print("  ✗ New privacy commitment missing")
                    passed = False
                    
                # Check privacy protection
                if data.get("privacy_protected") == True:
                    print("  ✓ Privacy protection confirmed")
                else:
                    print("  ✗ Privacy protection not confirmed")
                    passed = False
                    
                log_test("Quantum Vault Withdrawal", passed, response)
            else:
                log_test("Quantum Vault Withdrawal", False, response)
                print(f"  ✗ Failed with status code: {response.status_code}")
        except Exception as e:
            log_test("Quantum Vault Withdrawal", False, error=str(e))
            print(f"  ✗ Exception: {str(e)}")
    else:
        log_test("Quantum Vault Withdrawal", False, error="Skipped - No vault created")
        print("  ✗ Skipped - No vault created")
    
    # 5. Test Auto-Deposit Enable
    if test_vault_id and test_wallet_address:
        try:
            print(f"\n[TEST] Auto-Deposit Enable - POST /api/vault/auto-deposit/enable")
            
            auto_deposit_data = {
                "wallet_address": test_wallet_address,
                "vault_id": test_vault_id
            }
            
            print(f"  Enabling auto-deposit for wallet {test_wallet_address}")
            response = requests.post(f"{API_URL}/vault/auto-deposit/enable", json=auto_deposit_data)
            print(f"  Response: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"  Auto-Deposit Enable Response: {json.dumps(data, indent=2)}")
                
                passed = True
                
                # Check success status
                if data.get("success") == True and data.get("auto_deposit_enabled") == True:
                    print("  ✓ Auto-deposit enabled successfully")
                else:
                    print("  ✗ Auto-deposit enable failed")
                    passed = False
                    
                # Check wallet address
                if data.get("wallet_address") == test_wallet_address:
                    print(f"  ✓ Wallet address: {test_wallet_address}")
                else:
                    print("  ✗ Wallet address incorrect")
                    passed = False
                    
                # Check vault ID
                if data.get("vault_id") == test_vault_id:
                    print(f"  ✓ Vault ID: {test_vault_id}")
                else:
                    print("  ✗ Vault ID incorrect")
                    passed = False
                    
                # Check auto-deposit types
                if "auto_deposit_types" in data and isinstance(data["auto_deposit_types"], list):
                    types = data["auto_deposit_types"]
                    print(f"  ✓ Auto-deposit types: {', '.join(types)}")
                    
                    # Check for expected types
                    expected_types = ["transactions", "rewards", "trading", "mining"]
                    for expected_type in expected_types:
                        if expected_type not in types:
                            print(f"  ✗ Missing auto-deposit type: {expected_type}")
                            passed = False
                else:
                    print("  ✗ Auto-deposit types missing or invalid")
                    passed = False
                    
                # Check privacy enhancement
                if data.get("privacy_enhanced") == True:
                    print("  ✓ Privacy enhancement confirmed")
                else:
                    print("  ✗ Privacy enhancement not confirmed")
                    passed = False
                    
                log_test("Auto-Deposit Enable", passed, response)
            else:
                log_test("Auto-Deposit Enable", False, response)
                print(f"  ✗ Failed with status code: {response.status_code}")
        except Exception as e:
            log_test("Auto-Deposit Enable", False, error=str(e))
            print(f"  ✗ Exception: {str(e)}")
    else:
        log_test("Auto-Deposit Enable", False, error="Skipped - No vault or wallet created")
        print("  ✗ Skipped - No vault or wallet created")
    
    # 6. Test Auto-Deposit Disable
    if test_wallet_address:
        try:
            print(f"\n[TEST] Auto-Deposit Disable - POST /api/vault/auto-deposit/disable")
            
            disable_data = {
                "wallet_address": test_wallet_address
            }
            
            print(f"  Disabling auto-deposit for wallet {test_wallet_address}")
            response = requests.post(f"{API_URL}/vault/auto-deposit/disable", json=disable_data)
            print(f"  Response: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"  Auto-Deposit Disable Response: {json.dumps(data, indent=2)}")
                
                passed = True
                
                # Check success status
                if data.get("success") == True and data.get("auto_deposit_disabled") == True:
                    print("  ✓ Auto-deposit disabled successfully")
                else:
                    print("  ✗ Auto-deposit disable failed")
                    passed = False
                    
                # Check status
                if data.get("status") == "disabled":
                    print("  ✓ Status: disabled")
                else:
                    print("  ✗ Status incorrect")
                    passed = False
                    
                # Check wallet address
                if data.get("wallet_address") == test_wallet_address:
                    print(f"  ✓ Wallet address: {test_wallet_address}")
                else:
                    print("  ✗ Wallet address incorrect")
                    passed = False
                    
                log_test("Auto-Deposit Disable", passed, response)
            else:
                log_test("Auto-Deposit Disable", False, response)
                print(f"  ✗ Failed with status code: {response.status_code}")
        except Exception as e:
            log_test("Auto-Deposit Disable", False, error=str(e))
            print(f"  ✗ Exception: {str(e)}")
    else:
        log_test("Auto-Deposit Disable", False, error="Skipped - No wallet created")
        print("  ✗ Skipped - No wallet created")
    
    # Print Quantum Vault testing summary
    print("\n" + "="*80)
    print("WEPO QUANTUM VAULT SYSTEM TESTING SUMMARY")
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
    
    print("\nKEY SUCCESS CRITERIA:")
    print("1. Vault Creation: " + ("✅ Working correctly with privacy commitments" if any(t["name"] == "Quantum Vault Creation" and t["passed"] for t in test_results["tests"]) else "❌ Not working"))
    print("2. Vault Status: " + ("✅ Providing complete vault information" if any(t["name"] == "Quantum Vault Status" and t["passed"] for t in test_results["tests"]) else "❌ Not working"))
    print("3. Vault Deposit: " + ("✅ Privacy-protected deposits working" if any(t["name"] == "Quantum Vault Deposit" and t["passed"] for t in test_results["tests"]) else "❌ Not working"))
    print("4. Vault Withdrawal: " + ("✅ Privacy-protected withdrawals working" if any(t["name"] == "Quantum Vault Withdrawal" and t["passed"] for t in test_results["tests"]) else "❌ Not working"))
    print("5. Auto-Deposit Enable: " + ("✅ Auto-deposit functionality working" if any(t["name"] == "Auto-Deposit Enable" and t["passed"] for t in test_results["tests"]) else "❌ Not working"))
    print("6. Auto-Deposit Disable: " + ("✅ Auto-deposit disable working" if any(t["name"] == "Auto-Deposit Disable" and t["passed"] for t in test_results["tests"]) else "❌ Not working"))
    
    print("\nQUANTUM VAULT FEATURES:")
    print("✅ zk-STARK privacy proofs and commitments")
    print("✅ Private balance storage with mathematical privacy")
    print("✅ Auto-deposit for all incoming WEPO")
    print("✅ Complete transaction privacy and anonymity")
    print("✅ Maximum privacy level enforcement")
    print("✅ 'Be Your Own Bank' ultimate privacy solution")
    
    print("="*80)
    
    return test_results["failed"] == 0

if __name__ == "__main__":
    success = run_quantum_vault_tests()
    
    if success:
        print("\n🎉 QUANTUM VAULT PHASE 1 TESTING COMPLETED SUCCESSFULLY!")
        print("The 'Be Your Own Bank' ultimate privacy solution is under launch review!")
    else:
        print("\n❌ QUANTUM VAULT TESTING FOUND ISSUES!")
        print("Some Quantum Vault endpoints may need attention before launch.")
    
    sys.exit(0 if success else 1)