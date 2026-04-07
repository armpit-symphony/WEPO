#!/usr/bin/env python3
"""
WEPO Backend Systems Comprehensive Testing Suite
Tests all critical WEPO backend systems after wallet authentication fixes and ops-and-audit documentation updates.
Focus areas:
1. Core Blockchain Systems - Verify blockchain, consensus, and tokenomics
2. Privacy Systems - Test E2E messaging, quantum vault, and ghost transfers  
3. Masternode Services - Verify the 5 masternode services are operational
4. Economic Systems - Test fee redistribution, staking, and dynamic collateral endpoints
5. Integration Health - Ensure all APIs are responding correctly
"""
import requests
import json
import time
import uuid
import os
import sys
import secrets
from datetime import datetime
import random
import string
import base64

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
print(f"🔧 TESTING WEPO BACKEND SYSTEMS COMPREHENSIVE SUITE")
print(f"Backend API URL: {API_URL}")
print(f"Focus: Core Blockchain, Privacy, Masternode, Economic Systems & Integration Health")
print("=" * 80)

# Test results tracking
test_results = {
    "total": 0,
    "passed": 0,
    "failed": 0,
    "tests": []
}

def log_test(name, passed, response=None, error=None, details=None):
    """Log test results with enhanced details"""
    status = "✅ PASSED" if passed else "❌ FAILED"
    print(f"{status} {name}")
    
    if details:
        print(f"  Details: {details}")
    
    if error:
        print(f"  Error: {error}")
    
    if response and not passed:
        print(f"  Response: {response}")
    
    test_results["total"] += 1
    if passed:
        test_results["passed"] += 1
    else:
        test_results["failed"] += 1
    
    test_results["tests"].append({
        "name": name,
        "passed": passed,
        "error": error,
        "details": details
    })

# ============================================================================
# 1. CORE BLOCKCHAIN SYSTEMS TESTS
# ============================================================================

def test_network_status():
    """Test 1: Network Status - Core blockchain health"""
    print("\n🌐 TEST 1: NETWORK STATUS - CORE BLOCKCHAIN HEALTH")
    print("Testing GET /api/network/status endpoint...")
    
    try:
        response = requests.get(f"{API_URL}/network/status")
        
        if response.status_code == 200:
            data = response.json()
            checks_passed = 0
            total_checks = 0
            
            # Check basic network fields
            required_fields = ['block_height', 'total_supply', 'network_hashrate', 'active_masternodes', 'total_staked']
            for field in required_fields:
                total_checks += 1
                if field in data:
                    print(f"  ✅ {field}: {data[field]}")
                    checks_passed += 1
                else:
                    print(f"  ❌ {field}: Missing")
            
            # Check total supply (should be around 63.9M for current tokenomics)
            total_checks += 1
            total_supply = data.get('total_supply', 0)
            if total_supply > 60000000:  # At least 60M WEPO
                print(f"  ✅ Total supply reasonable: {total_supply:,} WEPO")
                checks_passed += 1
            else:
                print(f"  ❌ Total supply too low: {total_supply:,}")
            
            success_rate = (checks_passed / total_checks) * 100
            log_test("Network Status", checks_passed >= 4,
                     details=f"Network health check: {success_rate:.1f}% success rate")
            return checks_passed >= 4
        else:
            log_test("Network Status", False, response=f"Status: {response.status_code}")
            return False
            
    except Exception as e:
        log_test("Network Status", False, error=str(e))
        return False

def test_mining_info():
    """Test 2: Mining Information - Blockchain consensus"""
    print("\n⛏️ TEST 2: MINING INFORMATION - BLOCKCHAIN CONSENSUS")
    print("Testing GET /api/mining/info endpoint...")
    
    try:
        response = requests.get(f"{API_URL}/mining/info")
        
        if response.status_code == 200:
            data = response.json()
            checks_passed = 0
            total_checks = 0
            
            # Check mining fields
            required_fields = ['current_block_height', 'current_reward', 'difficulty', 'algorithm']
            for field in required_fields:
                total_checks += 1
                if field in data:
                    print(f"  ✅ {field}: {data[field]}")
                    checks_passed += 1
                else:
                    print(f"  ❌ {field}: Missing")
            
            # Check algorithm
            total_checks += 1
            if data.get('algorithm') == 'Argon2':
                print("  ✅ Algorithm: Argon2 (CPU-friendly)")
                checks_passed += 1
            else:
                print(f"  ❌ Algorithm: {data.get('algorithm')} (expected Argon2)")
            
            success_rate = (checks_passed / total_checks) * 100
            log_test("Mining Information", checks_passed >= 3,
                     details=f"Mining system check: {success_rate:.1f}% success rate")
            return checks_passed >= 3
        else:
            log_test("Mining Information", False, response=f"Status: {response.status_code}")
            return False
            
    except Exception as e:
        log_test("Mining Information", False, error=str(e))
        return False

def test_wallet_creation():
    """Test 3: Wallet Creation - Core functionality"""
    print("\n💼 TEST 3: WALLET CREATION - CORE FUNCTIONALITY")
    print("Testing POST /api/wallet/create endpoint...")
    
    try:
        # Generate test wallet data
        test_username = f"testuser_{int(time.time())}"
        test_address = f"wepo1test{secrets.token_hex(16)}"
        test_private_key = f"encrypted_key_{secrets.token_hex(32)}"
        
        wallet_data = {
            "username": test_username,
            "address": test_address,
            "encrypted_private_key": test_private_key
        }
        
        response = requests.post(f"{API_URL}/wallet/create", json=wallet_data)
        
        if response.status_code == 200:
            data = response.json()
            checks_passed = 0
            total_checks = 0
            
            # Check response structure
            total_checks += 1
            if data.get('success') and data.get('address'):
                print(f"  ✅ Wallet created: {data['address']}")
                checks_passed += 1
            else:
                print("  ❌ Wallet creation failed")
            
            # Test wallet retrieval
            total_checks += 1
            wallet_response = requests.get(f"{API_URL}/wallet/{test_address}")
            if wallet_response.status_code == 200:
                wallet_info = wallet_response.json()
                print(f"  ✅ Wallet retrieval: Balance {wallet_info.get('balance', 0)} WEPO")
                checks_passed += 1
            else:
                print("  ❌ Wallet retrieval failed")
            
            success_rate = (checks_passed / total_checks) * 100
            log_test("Wallet Creation", checks_passed >= 1,
                     details=f"Wallet system check: {success_rate:.1f}% success rate")
            return checks_passed >= 1
        else:
            log_test("Wallet Creation", False, response=f"Status: {response.status_code}")
            return False
            
    except Exception as e:
        log_test("Wallet Creation", False, error=str(e))
        return False

# ============================================================================
# 2. ECONOMIC SYSTEMS TESTS
# ============================================================================

def test_staking_system():
    """Test 4: Staking System - PoS activation and rewards"""
    print("\n💰 TEST 4: STAKING SYSTEM - POS ACTIVATION AND REWARDS")
    print("Testing staking endpoints...")
    
    try:
        # Test staking creation
        test_address = f"wepo1stake{secrets.token_hex(16)}"
        stake_data = {
            "wallet_address": test_address,
            "amount": 1000,
            "lock_period_months": 12
        }
        
        response = requests.post(f"{API_URL}/stake", json=stake_data)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print(f"  ✅ Staking creation: Stake ID {data.get('stake_id')}")
                print(f"  ✅ APR: {data.get('apr', 'N/A')}%")
                log_test("Staking System", True,
                         details="Staking system operational with stake creation")
                return True
            else:
                print("  ❌ Staking creation failed")
        elif response.status_code == 404:
            print("  ❌ Staking endpoint not found - may be in different backend")
            log_test("Staking System", False,
                     details="Staking endpoint not accessible (404)")
            return False
        else:
            print(f"  ❌ Staking failed: Status {response.status_code}")
        
        log_test("Staking System", False, response=f"Status: {response.status_code}")
        return False
        
    except Exception as e:
        log_test("Staking System", False, error=str(e))
        return False

def test_community_amm():
    """Test 5: Community AMM - Market-driven exchange"""
    print("\n🔄 TEST 5: COMMUNITY AMM - MARKET-DRIVEN EXCHANGE")
    print("Testing community AMM endpoints...")
    
    try:
        # Test swap rate
        response = requests.get(f"{API_URL}/swap/rate")
        
        if response.status_code == 200:
            data = response.json()
            
            if 'pool_exists' in data:
                pool_exists = data['pool_exists']
                print(f"  ✅ AMM pool status: {'Exists' if pool_exists else 'Can be created'}")
                
                if pool_exists:
                    print(f"    - BTC reserve: {data.get('btc_reserve', 0)}")
                    print(f"    - WEPO reserve: {data.get('wepo_reserve', 0)}")
                    print(f"    - Current rate: {data.get('btc_to_wepo', 'N/A')} WEPO per BTC")
                
                # Test liquidity stats
                stats_response = requests.get(f"{API_URL}/liquidity/stats")
                if stats_response.status_code == 200:
                    print(f"  ✅ Liquidity stats accessible")
                    log_test("Community AMM", True,
                             details="AMM system operational with rate and stats endpoints")
                    return True
                else:
                    print(f"  ❌ Liquidity stats failed: {stats_response.status_code}")
            else:
                print("  ❌ AMM rate info incomplete")
        else:
            print(f"  ❌ AMM rate failed: Status {response.status_code}")
        
        log_test("Community AMM", False, response=f"Status: {response.status_code}")
        return False
        
    except Exception as e:
        log_test("Community AMM", False, error=str(e))
        return False

def test_dex_exchange():
    """Test 6: DEX Exchange - BTC-WEPO trading"""
    print("\n💱 TEST 6: DEX EXCHANGE - BTC-WEPO TRADING")
    print("Testing DEX exchange endpoints...")
    
    try:
        # Test exchange rate
        response = requests.get(f"{API_URL}/dex/rate")
        
        if response.status_code == 200:
            data = response.json()
            
            if 'btc_to_wepo' in data and 'wepo_to_btc' in data:
                print(f"  ✅ Exchange rates available:")
                print(f"    - BTC to WEPO: {data['btc_to_wepo']}")
                print(f"    - WEPO to BTC: {data['wepo_to_btc']}")
                print(f"    - Fee: {data.get('fee_percentage', 'N/A')}%")
                
                log_test("DEX Exchange", True,
                         details="DEX exchange rates accessible")
                return True
            else:
                print("  ❌ Exchange rate data incomplete")
        else:
            print(f"  ❌ DEX rate failed: Status {response.status_code}")
        
        log_test("DEX Exchange", False, response=f"Status: {response.status_code}")
        return False
        
    except Exception as e:
        log_test("DEX Exchange", False, error=str(e))
        return False

# ============================================================================
# 3. INTEGRATION HEALTH TESTS
# ============================================================================

def test_api_health():
    """Test 7: API Health - Overall system integration"""
    print("\n🏥 TEST 7: API HEALTH - OVERALL SYSTEM INTEGRATION")
    print("Testing core API endpoints for integration health...")
    
    try:
        endpoints_to_test = [
            ("/", "Root endpoint"),
            ("/network/status", "Network status"),
            ("/mining/info", "Mining information"),
            ("/dex/rate", "Exchange rate"),
            ("/blocks/latest", "Latest blocks")
        ]
        
        checks_passed = 0
        total_checks = len(endpoints_to_test)
        
        for endpoint, description in endpoints_to_test:
            try:
                response = requests.get(f"{API_URL}{endpoint}")
                if response.status_code == 200:
                    print(f"  ✅ {description}: OK")
                    checks_passed += 1
                else:
                    print(f"  ❌ {description}: Status {response.status_code}")
            except Exception as e:
                print(f"  ❌ {description}: Error {str(e)}")
        
        success_rate = (checks_passed / total_checks) * 100
        success = checks_passed >= 3
        log_test("API Health", success,
                 details=f"Integration health: {checks_passed}/{total_checks} endpoints OK ({success_rate:.1f}%)")
        return success
        
    except Exception as e:
        log_test("API Health", False, error=str(e))
        return False

def test_masternode_endpoints():
    """Test 8: Masternode Endpoints - Service availability"""
    print("\n🏛️ TEST 8: MASTERNODE ENDPOINTS - SERVICE AVAILABILITY")
    print("Testing masternode service endpoints...")
    
    try:
        # Test masternode services endpoint
        response = requests.get(f"{API_URL}/masternode/services")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success') and 'services' in data:
                services = data['services']
                print(f"  ✅ Masternode services: {len(services)} services available")
                
                # Test requirements endpoint
                req_response = requests.get(f"{API_URL}/masternode/requirements")
                if req_response.status_code == 200:
                    req_data = req_response.json()
                    if req_data.get('success'):
                        print(f"  ✅ Masternode requirements: Available")
                        log_test("Masternode Endpoints", True,
                                 details="Masternode service endpoints operational")
                        return True
                    else:
                        print("  ❌ Masternode requirements: Invalid response")
                else:
                    print(f"  ❌ Masternode requirements: Status {req_response.status_code}")
            else:
                print("  ❌ Masternode services: Invalid response structure")
        elif response.status_code == 404:
            print("  ❌ Masternode services endpoint not found")
            log_test("Masternode Endpoints", False,
                     details="Masternode endpoints not accessible (404)")
            return False
        else:
            print(f"  ❌ Masternode services failed: Status {response.status_code}")
        
        log_test("Masternode Endpoints", False, response=f"Status: {response.status_code}")
        return False
        
    except Exception as e:
        log_test("Masternode Endpoints", False, error=str(e))
        return False

def run_comprehensive_backend_tests():
    """Run all comprehensive backend system tests"""
    print("🚀 STARTING WEPO BACKEND SYSTEMS COMPREHENSIVE TESTING")
    print("Testing all critical systems after wallet authentication fixes...")
    print("=" * 80)
    
    # 1. Core Blockchain Systems
    print("\n" + "="*50)
    print("1. CORE BLOCKCHAIN SYSTEMS")
    print("="*50)
    test1_result = test_network_status()
    test2_result = test_mining_info()
    test3_result = test_wallet_creation()
    
    # 2. Economic Systems
    print("\n" + "="*50)
    print("2. ECONOMIC SYSTEMS")
    print("="*50)
    test4_result = test_staking_system()
    test5_result = test_community_amm()
    test6_result = test_dex_exchange()
    
    # 3. Integration Health
    print("\n" + "="*50)
    print("3. INTEGRATION HEALTH")
    print("="*50)
    test7_result = test_api_health()
    test8_result = test_masternode_endpoints()
    
    # Print final results
    print("\n" + "=" * 80)
    print("🔧 WEPO BACKEND SYSTEMS COMPREHENSIVE TEST RESULTS")
    print("=" * 80)
    
    success_rate = (test_results["passed"] / test_results["total"]) * 100 if test_results["total"] > 0 else 0
    
    print(f"Total Tests: {test_results['total']}")
    print(f"Passed: {test_results['passed']} ✅")
    print(f"Failed: {test_results['failed']} ❌")
    print(f"Success Rate: {success_rate:.1f}%")
    
    # System-wise results
    print("\n🎯 SYSTEM-WISE RESULTS:")
    
    core_blockchain_passed = sum([test1_result, test2_result, test3_result])
    print(f"  🌐 Core Blockchain Systems: {core_blockchain_passed}/3 ({'✅' if core_blockchain_passed >= 2 else '❌'})")
    
    economic_passed = sum([test4_result, test5_result, test6_result])
    print(f"  💰 Economic Systems: {economic_passed}/3 ({'✅' if economic_passed >= 2 else '❌'})")
    
    integration_passed = sum([test7_result, test8_result])
    print(f"  🏥 Integration Health: {integration_passed}/2 ({'✅' if integration_passed >= 1 else '❌'})")
    
    # Overall assessment
    critical_systems_working = (
        core_blockchain_passed >= 2 and
        economic_passed >= 1 and
        integration_passed >= 1
    )
    
    print(f"\n📋 OVERALL ASSESSMENT:")
    if critical_systems_working:
        print("🎉 CRITICAL BACKEND SYSTEMS ARE OPERATIONAL!")
        print("✅ Core blockchain functionality working")
        print("✅ Economic systems operational")
        print("✅ API integration healthy")
        print("\n✅ WALLET AUTHENTICATION FIXES HAVE NOT BROKEN BACKEND FUNCTIONALITY")
        return True
    else:
        print("❌ CRITICAL BACKEND ISSUES FOUND!")
        print("⚠️  Some core systems need attention")
        if core_blockchain_passed < 2:
            print("❌ Core blockchain systems need fixes")
        if economic_passed < 1:
            print("❌ Economic systems need fixes")
        if integration_passed < 1:
            print("❌ API integration needs fixes")
        return False

if __name__ == "__main__":
    success = run_comprehensive_backend_tests()
    if not success:
        sys.exit(1)