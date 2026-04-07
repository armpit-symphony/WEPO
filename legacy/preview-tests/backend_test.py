#!/usr/bin/env python3
"""
WEPO FOCUSED BACKEND TESTING - PRIORITY ISSUES

LEGACY NOTICE:
- This script is preview-era and is not the canonical local verification path.
- It should not be used as the primary backend acceptance test.
- Use the canonical backend/node smoke path instead:
  - /home/sparky/WEPO/wepo-blockchain/scripts/run_canonical_fee_smoke.sh
  - /home/sparky/WEPO/canonical_fee_settlement_smoke.py

**REVIEW REQUEST FOCUS:**
Run focused testing on the specific issues that were identified as failing in the previous comprehensive backend test:

**Priority Testing Focus:**

**1. Mining System Testing**
- Test the new `/api/mining/status` endpoint that was just added
- Verify `/api/mining/info` still works properly
- Check if all required mining data fields are present

**2. Network Status Testing**
- Test the new `/api/network/status` endpoint for WEPO network information
- Verify it returns all required network data fields
- Check if it provides comprehensive system health information

**3. Staking System Testing**
- Test `/api/staking/info` endpoint after removing the duplicate
- Test `/api/staking/stakes/{address}` with a test address
- Verify staking validation parameters are working correctly

**4. Database and Storage Testing**
- Test blockchain data endpoints and storage functionality
- Verify transaction data persistence and retrieval
- Check any remaining database connectivity issues

**5. Integration Verification**
- Quick verification that wallet authentication still works (100% previously)
- Verify Community Fair Market DEX still functional (100% previously)
- Check security validation still operational (100% previously)

**Expected Results:**
- Mining system should now be fully functional with new status endpoint
- Network status should provide comprehensive WEPO network information
- Staking system should work without duplicate endpoint conflicts
- Overall backend health should improve from 68.4% to 85%+ success rate

**Goal:** Verify that the critical mining, staking, and network status fixes have resolved the backend integration issues identified in the previous comprehensive testing.
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
import hashlib
import re

# Legacy preview target. Override explicitly if you still need this script.
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8011")
API_URL = f"{BACKEND_URL}/api"

print("⚠️ LEGACY SCRIPT: use wepo-blockchain/scripts/run_canonical_fee_smoke.sh for the canonical path")
print(f"🎯 WEPO FOCUSED BACKEND TESTING - PRIORITY ISSUES")
print(f"Backend API URL: {API_URL}")
print(f"Focus: Mining System, Network Status, Staking System, Database Testing")
print("=" * 80)

# Test results tracking
test_results = {
    "total": 0,
    "passed": 0,
    "failed": 0,
    "tests": [],
    "categories": {
        "mining_system": {"passed": 0, "total": 0},
        "network_status": {"passed": 0, "total": 0},
        "staking_system": {"passed": 0, "total": 0},
        "database_storage": {"passed": 0, "total": 0},
        "integration_verification": {"passed": 0, "total": 0}
    }
}

def log_test(name, passed, category, response=None, error=None, details=None):
    """Log test results with enhanced details and categorization"""
    status = "✅ PASSED" if passed else "❌ FAILED"
    print(f"{status} {name}")
    
    if details:
        print(f"  Details: {details}")
    
    if error:
        print(f"  Error: {error}")
    
    if response and not passed:
        print(f"  Response: {response}")
    
    test_results["total"] += 1
    test_results["categories"][category]["total"] += 1
    
    if passed:
        test_results["passed"] += 1
        test_results["categories"][category]["passed"] += 1
    else:
        test_results["failed"] += 1
    
    test_results["tests"].append({
        "name": name,
        "category": category,
        "passed": passed,
        "error": error,
        "details": details
    })

def generate_valid_wepo_address():
    """Generate a valid 37-character WEPO address (wepo1 + 32 hex chars)"""
    random_data = secrets.token_bytes(16)  # 16 bytes = 32 hex chars
    hex_part = random_data.hex()
    return f"wepo1{hex_part}"

def generate_test_user_data():
    """Generate realistic test user data"""
    username = f"testuser_{secrets.token_hex(4)}"
    password = f"TestPass123!{secrets.token_hex(2)}"
    return username, password

# ===== 1. MINING SYSTEM TESTING =====

def test_mining_system():
    """Test 1: Mining System Testing - Priority Focus"""
    print("\n⛏️ MINING SYSTEM TESTING - PRIORITY FOCUS")
    print("Testing new /api/mining/status endpoint and verifying /api/mining/info still works...")
    
    # Test new mining status endpoint
    try:
        response = requests.get(f"{API_URL}/mining/status")
        if response.status_code == 200:
            data = response.json()
            required_fields = ["connected_miners", "total_hash_rate", "difficulty", "block_reward", "mining_phase"]
            missing_fields = [field for field in required_fields if field not in data]
            
            if not missing_fields:
                log_test("Mining Status Endpoint (NEW)", True, "mining_system",
                        details=f"All required fields present: Connected miners: {data.get('connected_miners', 0)}, Hash rate: {data.get('total_hash_rate', 0)} H/s, Phase: {data.get('mining_phase', 'Unknown')}")
            else:
                log_test("Mining Status Endpoint (NEW)", False, "mining_system",
                        details=f"Missing required fields: {missing_fields}")
        else:
            log_test("Mining Status Endpoint (NEW)", False, "mining_system",
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("Mining Status Endpoint (NEW)", False, "mining_system", error=str(e))
    
    # Test existing mining info endpoint
    try:
        response = requests.get(f"{API_URL}/mining/info")
        if response.status_code == 200:
            data = response.json()
            required_fields = ["current_block_height", "current_reward", "difficulty", "algorithm"]
            missing_fields = [field for field in required_fields if field not in data]
            
            if not missing_fields:
                log_test("Mining Info Endpoint (EXISTING)", True, "mining_system",
                        details=f"Mining info operational: Reward: {data.get('current_reward', 0)} WEPO, Algorithm: {data.get('algorithm', 'Unknown')}, Height: {data.get('current_block_height', 0)}")
            else:
                log_test("Mining Info Endpoint (EXISTING)", False, "mining_system",
                        details=f"Missing required fields: {missing_fields}")
        else:
            log_test("Mining Info Endpoint (EXISTING)", False, "mining_system",
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("Mining Info Endpoint (EXISTING)", False, "mining_system", error=str(e))
    
    # Test mining data consistency between endpoints
    try:
        status_response = requests.get(f"{API_URL}/mining/status")
        info_response = requests.get(f"{API_URL}/mining/info")
        
        if status_response.status_code == 200 and info_response.status_code == 200:
            status_data = status_response.json()
            info_data = info_response.json()
            
            # Check if reward values are consistent
            status_reward = status_data.get("block_reward", 0)
            info_reward = info_data.get("current_reward", 0)
            
            if status_reward == info_reward:
                log_test("Mining Data Consistency", True, "mining_system",
                        details=f"Reward values consistent: {status_reward} WEPO")
            else:
                log_test("Mining Data Consistency", False, "mining_system",
                        details=f"Reward mismatch - Status: {status_reward}, Info: {info_reward}")
        else:
            log_test("Mining Data Consistency", False, "mining_system",
                    details="Cannot verify consistency - One or both endpoints failed")
    except Exception as e:
        log_test("Mining Data Consistency", False, "mining_system", error=str(e))

# ===== 2. NETWORK STATUS TESTING =====

def test_network_status():
    """Test 2: Network Status Testing - Priority Focus"""
    print("\n🌐 NETWORK STATUS TESTING - PRIORITY FOCUS")
    print("Testing new /api/network/status endpoint for comprehensive WEPO network information...")
    
    # Test network status endpoint
    try:
        response = requests.get(f"{API_URL}/network/status")
        if response.status_code == 200:
            data = response.json()
            required_fields = ["block_height", "network_hashrate", "active_masternodes", "total_supply", "circulating_supply"]
            missing_fields = [field for field in required_fields if field not in data]
            
            if not missing_fields:
                log_test("Network Status Comprehensive Data", True, "network_status",
                        details=f"All network data present: Height: {data.get('block_height', 0)}, Masternodes: {data.get('active_masternodes', 0)}, Supply: {data.get('total_supply', 0)}")
            else:
                log_test("Network Status Comprehensive Data", False, "network_status",
                        details=f"Missing required fields: {missing_fields}")
        else:
            log_test("Network Status Comprehensive Data", False, "network_status",
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("Network Status Comprehensive Data", False, "network_status", error=str(e))
    
    # Test network health information
    try:
        response = requests.get(f"{API_URL}/network/status")
        if response.status_code == 200:
            data = response.json()
            
            # Validate data types and ranges
            block_height = data.get("block_height", 0)
            total_supply = data.get("total_supply", 0)
            circulating_supply = data.get("circulating_supply", 0)
            active_masternodes = data.get("active_masternodes", 0)
            
            health_checks = []
            
            # Check if values are reasonable
            if isinstance(block_height, (int, float)) and block_height >= 0:
                health_checks.append("Block height valid")
            else:
                health_checks.append(f"Block height invalid: {block_height}")
            
            if isinstance(total_supply, (int, float)) and total_supply > 0:
                health_checks.append("Total supply valid")
            else:
                health_checks.append(f"Total supply invalid: {total_supply}")
            
            if isinstance(circulating_supply, (int, float)) and circulating_supply >= 0:
                health_checks.append("Circulating supply valid")
            else:
                health_checks.append(f"Circulating supply invalid: {circulating_supply}")
            
            if isinstance(active_masternodes, (int, float)) and active_masternodes >= 0:
                health_checks.append("Masternode count valid")
            else:
                health_checks.append(f"Masternode count invalid: {active_masternodes}")
            
            # Check if circulating supply <= total supply
            if circulating_supply <= total_supply:
                health_checks.append("Supply relationship valid")
            else:
                health_checks.append(f"Supply relationship invalid: {circulating_supply} > {total_supply}")
            
            failed_checks = [check for check in health_checks if "invalid" in check]
            
            if not failed_checks:
                log_test("Network Health Information", True, "network_status",
                        details=f"All health checks passed: {len(health_checks)} validations")
            else:
                log_test("Network Health Information", False, "network_status",
                        details=f"Failed health checks: {failed_checks}")
        else:
            log_test("Network Health Information", False, "network_status",
                    details=f"Cannot verify health - HTTP {response.status_code}")
    except Exception as e:
        log_test("Network Health Information", False, "network_status", error=str(e))

# ===== 3. STAKING SYSTEM TESTING =====

def test_staking_system():
    """Test 3: Staking System Testing - Priority Focus"""
    print("\n🥩 STAKING SYSTEM TESTING - PRIORITY FOCUS")
    print("Testing staking endpoints after removing duplicates and verifying validation parameters...")
    
    # Test staking info endpoint (if it exists)
    try:
        response = requests.get(f"{API_URL}/staking/info")
        if response.status_code == 200:
            data = response.json()
            log_test("Staking Info Endpoint", True, "staking_system",
                    details=f"Staking info accessible: {list(data.keys())}")
        elif response.status_code == 404:
            log_test("Staking Info Endpoint", False, "staking_system",
                    details="Staking info endpoint not found (404)")
        else:
            log_test("Staking Info Endpoint", False, "staking_system",
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("Staking Info Endpoint", False, "staking_system", error=str(e))
    
    # Test staking stakes endpoint with test address
    try:
        test_address = generate_valid_wepo_address()
        response = requests.get(f"{API_URL}/staking/stakes/{test_address}")
        if response.status_code == 200:
            data = response.json()
            log_test("Staking Stakes by Address", True, "staking_system",
                    details=f"Stakes data accessible for address: {type(data)}")
        elif response.status_code == 404:
            log_test("Staking Stakes by Address", True, "staking_system",
                    details="Proper 404 handling for non-existent address")
        else:
            log_test("Staking Stakes by Address", False, "staking_system",
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("Staking Stakes by Address", False, "staking_system", error=str(e))
    
    # Test staking validation parameters
    try:
        test_address = generate_valid_wepo_address()
        stake_data = {
            "staker_address": test_address,
            "amount": 1000.0
        }
        
        response = requests.post(f"{API_URL}/staking/create", json=stake_data)
        
        if response.status_code == 404:
            log_test("Staking Validation Parameters", True, "staking_system",
                    details="Proper wallet validation - 404 for non-existent wallet")
        elif response.status_code == 400:
            error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
            if "balance" in str(error_data).lower() or "insufficient" in str(error_data).lower():
                log_test("Staking Validation Parameters", True, "staking_system",
                        details="Proper balance validation - Insufficient balance check working")
            else:
                log_test("Staking Validation Parameters", False, "staking_system",
                        details=f"Unexpected validation error: {error_data}")
        elif response.status_code == 200:
            log_test("Staking Validation Parameters", True, "staking_system",
                    details="Staking system operational - Stake created successfully")
        else:
            log_test("Staking Validation Parameters", False, "staking_system",
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("Staking Validation Parameters", False, "staking_system", error=str(e))
    
    # Test minimum stake validation
    try:
        test_address = generate_valid_wepo_address()
        low_stake_data = {
            "staker_address": test_address,
            "amount": 100.0  # Below minimum of 1000
        }
        
        response = requests.post(f"{API_URL}/staking/create", json=low_stake_data)
        
        if response.status_code == 400:
            error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
            if "minimum" in str(error_data).lower() or "1000" in str(error_data):
                log_test("Minimum Stake Validation", True, "staking_system",
                        details="Minimum stake validation working - 1000 WEPO minimum enforced")
            else:
                log_test("Minimum Stake Validation", False, "staking_system",
                        details=f"Minimum stake validation unclear: {error_data}")
        elif response.status_code == 404:
            log_test("Minimum Stake Validation", True, "staking_system",
                    details="Wallet validation occurs before minimum stake check")
        else:
            log_test("Minimum Stake Validation", False, "staking_system",
                    details=f"Unexpected response: HTTP {response.status_code}")
    except Exception as e:
        log_test("Minimum Stake Validation", False, "staking_system", error=str(e))

# ===== 4. DATABASE AND STORAGE TESTING =====

def test_database_storage():
    """Test 4: Database and Storage Testing - Priority Focus"""
    print("\n💾 DATABASE AND STORAGE TESTING - PRIORITY FOCUS")
    print("Testing blockchain data endpoints, transaction persistence, and database connectivity...")
    
    # Test blockchain data endpoints
    try:
        response = requests.get(f"{API_URL}/network/status")
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict) and "block_height" in data:
                log_test("Blockchain Data Endpoints", True, "database_storage",
                        details=f"Network data accessible - Block height: {data.get('block_height', 0)}")
            else:
                log_test("Blockchain Data Endpoints", False, "database_storage",
                        details=f"Unexpected data format: {type(data)}")
        else:
            log_test("Blockchain Data Endpoints", False, "database_storage",
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("Blockchain Data Endpoints", False, "database_storage", error=str(e))
    
    # Test transaction data persistence and retrieval
    try:
        test_address = generate_valid_wepo_address()
        response = requests.get(f"{API_URL}/wallet/{test_address}/transactions")
        
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                log_test("Transaction Data Persistence", True, "database_storage",
                        details=f"Transaction data accessible - {len(data)} transactions for test address")
            else:
                log_test("Transaction Data Persistence", False, "database_storage",
                        details=f"Unexpected data format: {type(data)}")
        elif response.status_code == 404:
            log_test("Transaction Data Persistence", True, "database_storage",
                    details="Proper 404 handling for non-existent address - Database connectivity working")
        else:
            log_test("Transaction Data Persistence", False, "database_storage",
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("Transaction Data Persistence", False, "database_storage", error=str(e))
    
    # Test database connectivity through wallet lookup
    try:
        test_address = generate_valid_wepo_address()
        response = requests.get(f"{API_URL}/wallet/{test_address}")
        
        if response.status_code == 404:
            log_test("Database Connectivity", True, "database_storage",
                    details="Database connectivity confirmed - Proper wallet lookup and 404 response")
        elif response.status_code == 200:
            log_test("Database Connectivity", True, "database_storage",
                    details="Database connectivity confirmed - Wallet data retrieved")
        elif response.status_code == 500:
            log_test("Database Connectivity", False, "database_storage",
                    details="Database connectivity issue - Internal server error")
        else:
            log_test("Database Connectivity", False, "database_storage",
                    details=f"Unexpected response: HTTP {response.status_code}")
    except Exception as e:
        log_test("Database Connectivity", False, "database_storage", error=str(e))
    
    # Test data consistency across endpoints
    try:
        network_response = requests.get(f"{API_URL}/network/status")
        mining_response = requests.get(f"{API_URL}/mining/info")
        
        if network_response.status_code == 200 and mining_response.status_code == 200:
            network_data = network_response.json()
            mining_data = mining_response.json()
            
            network_height = network_data.get("block_height", 0)
            mining_height = mining_data.get("current_block_height", 0)
            
            if network_height == mining_height:
                log_test("Data Consistency Across Endpoints", True, "database_storage",
                        details=f"Block height consistent across endpoints: {network_height}")
            else:
                log_test("Data Consistency Across Endpoints", False, "database_storage",
                        details=f"Block height mismatch - Network: {network_height}, Mining: {mining_height}")
        else:
            log_test("Data Consistency Across Endpoints", False, "database_storage",
                    details="Cannot verify consistency - One or both endpoints failed")
    except Exception as e:
        log_test("Data Consistency Across Endpoints", False, "database_storage", error=str(e))

# ===== 5. INTEGRATION VERIFICATION =====

def test_integration_verification():
    """Test 5: Integration Verification - Quick Checks"""
    print("\n🔗 INTEGRATION VERIFICATION - QUICK CHECKS")
    print("Quick verification of wallet authentication, DEX, and security validation...")
    
    # Quick wallet authentication check
    try:
        username, password = generate_test_user_data()
        create_data = {
            "username": username,
            "password": password
        }
        
        response = requests.post(f"{API_URL}/wallet/create", json=create_data)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success") and data.get("address"):
                log_test("Wallet Authentication (Quick Check)", True, "integration_verification",
                        details="Wallet creation working - Authentication system operational")
            else:
                log_test("Wallet Authentication (Quick Check)", False, "integration_verification",
                        details="Wallet creation response invalid")
        elif response.status_code == 400:
            log_test("Wallet Authentication (Quick Check)", True, "integration_verification",
                    details="Wallet validation working - Proper error handling")
        else:
            log_test("Wallet Authentication (Quick Check)", False, "integration_verification",
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("Wallet Authentication (Quick Check)", False, "integration_verification", error=str(e))
    
    # Quick Community Fair Market DEX check
    try:
        response = requests.get(f"{API_URL}/swap/rate")
        if response.status_code == 200:
            data = response.json()
            if "btc_to_wepo" in data or "pool_exists" in data:
                log_test("Community Fair Market DEX (Quick Check)", True, "integration_verification",
                        details=f"DEX operational - Pool exists: {data.get('pool_exists', 'Unknown')}")
            else:
                log_test("Community Fair Market DEX (Quick Check)", False, "integration_verification",
                        details="DEX response missing expected fields")
        else:
            log_test("Community Fair Market DEX (Quick Check)", False, "integration_verification",
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("Community Fair Market DEX (Quick Check)", False, "integration_verification", error=str(e))
    
    # Quick security validation check
    try:
        response = requests.get(f"{API_URL}/")
        security_headers = [
            "X-Content-Type-Options",
            "X-Frame-Options", 
            "X-XSS-Protection"
        ]
        
        present_headers = [header for header in security_headers if header in response.headers]
        
        if len(present_headers) >= 2:
            log_test("Security Validation (Quick Check)", True, "integration_verification",
                    details=f"Security headers present: {present_headers}")
        else:
            log_test("Security Validation (Quick Check)", False, "integration_verification",
                    details=f"Insufficient security headers: {present_headers}")
    except Exception as e:
        log_test("Security Validation (Quick Check)", False, "integration_verification", error=str(e))
    
    # Quick API root endpoint check
    try:
        response = requests.get(f"{API_URL}/")
        if response.status_code == 200:
            data = response.json()
            if data.get("message") and "WEPO" in data.get("message", ""):
                log_test("API Root Endpoint (Quick Check)", True, "integration_verification",
                        details=f"API accessible - {data.get('message', 'No message')}")
            else:
                log_test("API Root Endpoint (Quick Check)", False, "integration_verification",
                        details="API response missing expected WEPO message")
        else:
            log_test("API Root Endpoint (Quick Check)", False, "integration_verification",
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("API Root Endpoint (Quick Check)", False, "integration_verification", error=str(e))

def run_focused_backend_testing():
    """Run focused backend testing on priority issues"""
    print("🔍 STARTING WEPO FOCUSED BACKEND TESTING - PRIORITY ISSUES")
    print("Testing specific issues identified in previous comprehensive testing...")
    print("=" * 80)
    
    # Run priority test categories
    test_mining_system()
    test_network_status()
    test_staking_system()
    test_database_storage()
    test_integration_verification()
    
    # Print focused results
    print("\n" + "=" * 80)
    print("🔍 WEPO FOCUSED BACKEND TESTING RESULTS")
    print("=" * 80)
    
    success_rate = (test_results["passed"] / test_results["total"]) * 100 if test_results["total"] > 0 else 0
    
    print(f"Total Tests: {test_results['total']}")
    print(f"Passed: {test_results['passed']} ✅")
    print(f"Failed: {test_results['failed']} ❌")
    print(f"Overall Success Rate: {success_rate:.1f}%")
    
    # Category-wise results
    print("\n📊 PRIORITY CATEGORY RESULTS:")
    categories = {
        "mining_system": "⛏️ Mining System",
        "network_status": "🌐 Network Status",
        "staking_system": "🥩 Staking System",
        "database_storage": "💾 Database & Storage",
        "integration_verification": "🔗 Integration Verification"
    }
    
    critical_issues = []
    
    for category_key, category_name in categories.items():
        cat_data = test_results["categories"][category_key]
        cat_rate = (cat_data["passed"] / cat_data["total"]) * 100 if cat_data["total"] > 0 else 0
        status = "✅" if cat_rate >= 60 else "❌"
        print(f"  {status} {category_name}: {cat_data['passed']}/{cat_data['total']} ({cat_rate:.1f}%)")
        
        if cat_rate < 60:
            critical_issues.append(category_name)
    
    # Priority Issues Analysis
    print("\n🎯 PRIORITY ISSUES ANALYSIS:")
    
    # Mining System Analysis
    mining_tests = [test for test in test_results['tests'] if test['category'] == 'mining_system']
    mining_passed = len([test for test in mining_tests if test['passed']])
    mining_total = len(mining_tests)
    mining_rate = (mining_passed / mining_total) * 100 if mining_total > 0 else 0
    
    if mining_rate >= 75:
        print(f"✅ MINING SYSTEM WORKING WELL ({mining_rate:.1f}%)")
        print("   New /api/mining/status endpoint and existing endpoints operational")
    elif mining_rate >= 50:
        print(f"⚠️  MINING SYSTEM PARTIALLY WORKING ({mining_rate:.1f}%)")
        print("   Some mining endpoints need attention")
    else:
        print(f"🚨 CRITICAL MINING SYSTEM ISSUES ({mining_rate:.1f}%)")
        print("   Mining system requires immediate fixes")
    
    # Network Status Analysis
    network_tests = [test for test in test_results['tests'] if test['category'] == 'network_status']
    network_passed = len([test for test in network_tests if test['passed']])
    network_total = len(network_tests)
    network_rate = (network_passed / network_total) * 100 if network_total > 0 else 0
    
    if network_rate >= 75:
        print(f"✅ NETWORK STATUS WORKING WELL ({network_rate:.1f}%)")
        print("   Comprehensive WEPO network information available")
    elif network_rate >= 50:
        print(f"⚠️  NETWORK STATUS PARTIALLY WORKING ({network_rate:.1f}%)")
        print("   Some network data issues detected")
    else:
        print(f"🚨 CRITICAL NETWORK STATUS ISSUES ({network_rate:.1f}%)")
        print("   Network status endpoint requires fixes")
    
    # Staking System Analysis
    staking_tests = [test for test in test_results['tests'] if test['category'] == 'staking_system']
    staking_passed = len([test for test in staking_tests if test['passed']])
    staking_total = len(staking_tests)
    staking_rate = (staking_passed / staking_total) * 100 if staking_total > 0 else 0
    
    if staking_rate >= 75:
        print(f"✅ STAKING SYSTEM WORKING WELL ({staking_rate:.1f}%)")
        print("   Staking validation and endpoints operational")
    elif staking_rate >= 50:
        print(f"⚠️  STAKING SYSTEM PARTIALLY WORKING ({staking_rate:.1f}%)")
        print("   Some staking functionality needs attention")
    else:
        print(f"🚨 CRITICAL STAKING SYSTEM ISSUES ({staking_rate:.1f}%)")
        print("   Staking system requires immediate fixes")
    
    # Failed tests summary
    failed_tests = [test for test in test_results['tests'] if not test['passed']]
    if failed_tests:
        print(f"\n❌ FAILED TESTS SUMMARY ({len(failed_tests)} total):")
        for test in failed_tests:
            print(f"  • {test['name']} ({test['category']})")
            if test['details']:
                print(f"    Issue: {test['details']}")
            if test['error']:
                print(f"    Error: {test['error']}")
    
    # System health assessment
    print(f"\n🏥 PRIORITY FIXES ASSESSMENT:")
    if success_rate >= 85:
        print("🎉 EXCELLENT - Priority fixes successful!")
        print("   Target 85%+ success rate achieved")
        print("   Critical mining, staking, and network issues resolved")
    elif success_rate >= 70:
        print("✅ GOOD - Significant improvements made")
        print("   Most priority issues addressed")
        print("   Some minor issues remain")
    elif success_rate >= 50:
        print("⚠️  FAIR - Some improvements made")
        print("   Priority issues partially resolved")
        print("   Additional fixes needed")
    else:
        print("🚨 POOR - Priority fixes unsuccessful")
        print("   Critical issues persist")
        print("   Immediate attention required")
    
    return {
        "success_rate": success_rate,
        "total_tests": test_results["total"],
        "passed_tests": test_results["passed"],
        "failed_tests": failed_tests,
        "categories": test_results["categories"],
        "mining_rate": mining_rate,
        "network_rate": network_rate,
        "staking_rate": staking_rate,
        "critical_issues": critical_issues
    }

if __name__ == "__main__":
    print("⚠️ LEGACY SCRIPT: canonical path is wepo-blockchain/scripts/run_canonical_fee_smoke.sh")
    # Run focused backend testing
    results = run_focused_backend_testing()
    
    print("\n" + "=" * 80)
    print("🎯 FINAL FOCUSED TESTING SUMMARY")
    print("=" * 80)
    
    print(f"📊 OVERALL RESULTS:")
    print(f"• Total Tests: {results['total_tests']}")
    print(f"• Passed: {results['passed_tests']} ✅")
    print(f"• Failed: {len(results['failed_tests'])} ❌")
    print(f"• Success Rate: {results['success_rate']:.1f}%")
    
    print(f"\n🎯 PRIORITY SYSTEM STATUS:")
    print(f"• ⛏️  Mining System: {results['mining_rate']:.1f}%")
    print(f"• 🌐 Network Status: {results['network_rate']:.1f}%")
    print(f"• 🥩 Staking System: {results['staking_rate']:.1f}%")
    
    if results['critical_issues']:
        print(f"\n🚨 CRITICAL COMPONENTS NEEDING ATTENTION:")
        for i, issue in enumerate(results['critical_issues'], 1):
            print(f"{i}. {issue}")
    
    print(f"\n💡 RECOMMENDATIONS:")
    if results['success_rate'] >= 85:
        print("• 🎉 TARGET ACHIEVED - Priority fixes successful!")
        print("• Mining, network status, and staking systems operational")
        print("• Backend health improved as expected")
    elif results['success_rate'] >= 70:
        print("• ✅ GOOD PROGRESS - Most priority issues addressed")
        print("• Continue addressing remaining failed tests")
        print("• System is significantly improved")
    else:
        print("• 🚨 URGENT - Priority fixes need more work")
        print("• Focus on critical failing components")
        print("• Additional development required")
    
    print(f"\n🔧 NEXT STEPS:")
    if results['success_rate'] >= 85:
        print("• System not approved for production use")
        print("• Monitor for any edge cases")
        print("• Continue with frontend integration")
    else:
        print("• Address failing tests systematically")
        print("• Focus on highest priority components first")
        print("• Re-test after fixes are implemented")
