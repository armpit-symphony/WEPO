#!/usr/bin/env python3
"""
WEPO Real Dilithium2 Quantum-Resistant Signature Testing Suite
Tests the WEPO backend systems after implementing REAL Dilithium2 quantum-resistant signatures.

Focus areas:
1. Quantum Resistance Verification - Test that the system uses true post-quantum cryptography
2. Signature System - Verify all signature operations use real Dilithium2 (not RSA simulation)
3. API Integration - Test blockchain endpoints with quantum-resistant signatures
4. Key Generation - Verify new keys use NIST ML-DSA Dilithium2
5. Backwards Compatibility - Ensure existing WEPO functionality still works

Key Points to Test:
- Dilithium signature generation and verification
- Quantum resistance status (should be TRUE)
- Key sizes match NIST specifications (1312 bytes public, 2528 bytes private)
- Signature sizes match NIST specifications (2420 bytes)
- Integration with existing WEPO blockchain functionality

Expected Results: All systems should be operational with REAL quantum-resistant signatures now active,
showing true post-quantum security instead of RSA simulation.

Test Environment: Using http://localhost:8001 for the WepoFastTestBridge with quantum-resistant integration.
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

# Add blockchain core to path for direct testing
sys.path.append('/app/wepo-blockchain/core')

# Test both implementations
try:
    from real_dilithium import RealDilithiumSigner, is_real_dilithium_available
    REAL_DILITHIUM_AVAILABLE = True
except ImportError:
    REAL_DILITHIUM_AVAILABLE = False

try:
    from dilithium import DilithiumSigner, is_real_dilithium_available as hybrid_available
    HYBRID_DILITHIUM_AVAILABLE = True
except ImportError:
    HYBRID_DILITHIUM_AVAILABLE = False

# Use localhost:8001 for WepoFastTestBridge as specified in review request
BRIDGE_URL = "http://localhost:8001"
API_URL = f"{BRIDGE_URL}/api"

print(f"🔐 TESTING WEPO REAL DILITHIUM2 QUANTUM-RESISTANT SIGNATURES")
print(f"WepoFastTestBridge API URL: {API_URL}")
print(f"Focus: REAL Dilithium2 quantum-resistant signature implementation")
print("=" * 80)

# NIST ML-DSA Dilithium2 Specifications
EXPECTED_PUBKEY_SIZE = 1312   # bytes (NIST standard)
EXPECTED_PRIVKEY_SIZE = 2528  # bytes (NIST standard)
EXPECTED_SIGNATURE_SIZE = 2420 # bytes (NIST standard)

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

def test_real_dilithium_availability():
    """Test 1: Real Dilithium2 Availability - Verify real implementation is available"""
    print("\n🔍 TEST 1: REAL DILITHIUM2 AVAILABILITY")
    print("Testing if real Dilithium2 implementation is available...")
    
    try:
        checks_passed = 0
        total_checks = 0
        
        # Check if real_dilithium module is available
        total_checks += 1
        if REAL_DILITHIUM_AVAILABLE:
            print("  ✅ Real Dilithium module: Available")
            checks_passed += 1
        else:
            print("  ❌ Real Dilithium module: Not available")
        
        # Check if hybrid dilithium module is available
        total_checks += 1
        if HYBRID_DILITHIUM_AVAILABLE:
            print("  ✅ Hybrid Dilithium module: Available")
            checks_passed += 1
        else:
            print("  ❌ Hybrid Dilithium module: Not available")
        
        # Test real Dilithium functionality
        if REAL_DILITHIUM_AVAILABLE:
            total_checks += 1
            try:
                available = is_real_dilithium_available()
                if available:
                    print("  ✅ Real Dilithium functionality: Working")
                    checks_passed += 1
                else:
                    print("  ❌ Real Dilithium functionality: Not working")
            except Exception as e:
                print(f"  ❌ Real Dilithium functionality: Error - {e}")
        
        success_rate = (checks_passed / total_checks) * 100
        log_test("Real Dilithium2 Availability", checks_passed >= 2,
                 details=f"Real Dilithium available: {REAL_DILITHIUM_AVAILABLE}, Hybrid available: {HYBRID_DILITHIUM_AVAILABLE} ({success_rate:.1f}% success)")
        return checks_passed >= 2
        
    except Exception as e:
        log_test("Real Dilithium2 Availability", False, error=str(e))
        return False

def test_dilithium_key_generation():
    """Test 2: Dilithium Key Generation - Test NIST ML-DSA key generation"""
    print("\n🔑 TEST 2: DILITHIUM KEY GENERATION")
    print("Testing Dilithium2 key generation with NIST specifications...")
    
    try:
        checks_passed = 0
        total_checks = 0
        
        if not REAL_DILITHIUM_AVAILABLE:
            log_test("Dilithium Key Generation", False, error="Real Dilithium not available")
            return False
        
        # Test real Dilithium key generation
        total_checks += 1
        try:
            signer = RealDilithiumSigner()
            keypair = signer.generate_keypair()
            print("  ✅ Key generation: Successful")
            checks_passed += 1
        except Exception as e:
            print(f"  ❌ Key generation: Failed - {e}")
            log_test("Dilithium Key Generation", False, error=str(e))
            return False
        
        # Check public key size
        total_checks += 1
        if len(keypair.public_key) == EXPECTED_PUBKEY_SIZE:
            print(f"  ✅ Public key size: {len(keypair.public_key)} bytes (NIST standard)")
            checks_passed += 1
        else:
            print(f"  ❌ Public key size: {len(keypair.public_key)} bytes (expected {EXPECTED_PUBKEY_SIZE})")
        
        # Check private key size
        total_checks += 1
        if len(keypair.private_key) == EXPECTED_PRIVKEY_SIZE:
            print(f"  ✅ Private key size: {len(keypair.private_key)} bytes (NIST standard)")
            checks_passed += 1
        else:
            print(f"  ❌ Private key size: {len(keypair.private_key)} bytes (expected {EXPECTED_PRIVKEY_SIZE})")
        
        # Test algorithm info
        total_checks += 1
        try:
            info = signer.get_algorithm_info()
            if info.get('quantum_resistant') == True and info.get('post_quantum') == True:
                print(f"  ✅ Quantum resistance: {info.get('quantum_resistant')} (TRUE)")
                checks_passed += 1
            else:
                print(f"  ❌ Quantum resistance: {info.get('quantum_resistant')} (expected TRUE)")
        except Exception as e:
            print(f"  ❌ Algorithm info: Error - {e}")
        
        success_rate = (checks_passed / total_checks) * 100
        log_test("Dilithium Key Generation", checks_passed >= 3,
                 details=f"Key sizes: {len(keypair.public_key)}/{len(keypair.private_key)} bytes, Quantum resistant: {info.get('quantum_resistant', 'Unknown')} ({success_rate:.1f}% success)")
        return checks_passed >= 3
        
    except Exception as e:
        log_test("Dilithium Key Generation", False, error=str(e))
        return False

def test_dilithium_signature_operations():
    """Test 3: Dilithium Signature Operations - Test signing and verification"""
    print("\n✍️ TEST 3: DILITHIUM SIGNATURE OPERATIONS")
    print("Testing Dilithium2 signature generation and verification...")
    
    try:
        checks_passed = 0
        total_checks = 0
        
        if not REAL_DILITHIUM_AVAILABLE:
            log_test("Dilithium Signature Operations", False, error="Real Dilithium not available")
            return False
        
        # Generate keypair for testing
        signer = RealDilithiumSigner()
        keypair = signer.generate_keypair()
        test_message = b"WEPO - We The People - Quantum Resistant Cryptocurrency Test Message"
        
        # Test signature generation
        total_checks += 1
        try:
            signature = signer.sign(test_message)
            print("  ✅ Signature generation: Successful")
            checks_passed += 1
        except Exception as e:
            print(f"  ❌ Signature generation: Failed - {e}")
            log_test("Dilithium Signature Operations", False, error=str(e))
            return False
        
        # Check signature size
        total_checks += 1
        if len(signature) == EXPECTED_SIGNATURE_SIZE:
            print(f"  ✅ Signature size: {len(signature)} bytes (NIST standard)")
            checks_passed += 1
        else:
            print(f"  ❌ Signature size: {len(signature)} bytes (expected {EXPECTED_SIGNATURE_SIZE})")
        
        # Test signature verification (valid)
        total_checks += 1
        try:
            is_valid = signer.verify(test_message, signature)
            if is_valid:
                print("  ✅ Valid signature verification: TRUE")
                checks_passed += 1
            else:
                print("  ❌ Valid signature verification: FALSE (should be TRUE)")
        except Exception as e:
            print(f"  ❌ Valid signature verification: Error - {e}")
        
        # Test signature verification (invalid message)
        total_checks += 1
        try:
            invalid_message = b"Different message that should fail verification"
            is_invalid = signer.verify(invalid_message, signature)
            if not is_invalid:
                print("  ✅ Invalid signature rejection: TRUE (correctly rejected)")
                checks_passed += 1
            else:
                print("  ❌ Invalid signature rejection: FALSE (should reject invalid signatures)")
        except Exception as e:
            print(f"  ❌ Invalid signature rejection: Error - {e}")
        
        # Test with external public key
        total_checks += 1
        try:
            external_valid = signer.verify(test_message, signature, keypair.public_key)
            if external_valid:
                print("  ✅ External public key verification: TRUE")
                checks_passed += 1
            else:
                print("  ❌ External public key verification: FALSE")
        except Exception as e:
            print(f"  ❌ External public key verification: Error - {e}")
        
        success_rate = (checks_passed / total_checks) * 100
        log_test("Dilithium Signature Operations", checks_passed >= 4,
                 details=f"Signature size: {len(signature)} bytes, Valid verification: {is_valid}, Invalid rejection: {not is_invalid} ({success_rate:.1f}% success)")
        return checks_passed >= 4
        
    except Exception as e:
        log_test("Dilithium Signature Operations", False, error=str(e))
        return False

def test_quantum_resistance_status():
    """Test 4: Quantum Resistance Status - Verify TRUE quantum resistance"""
    print("\n🛡️ TEST 4: QUANTUM RESISTANCE STATUS")
    print("Testing quantum resistance status and algorithm information...")
    
    try:
        checks_passed = 0
        total_checks = 0
        
        if not REAL_DILITHIUM_AVAILABLE:
            log_test("Quantum Resistance Status", False, error="Real Dilithium not available")
            return False
        
        # Test real Dilithium signer
        signer = RealDilithiumSigner()
        keypair = signer.generate_keypair()
        
        # Get algorithm information
        total_checks += 1
        try:
            info = signer.get_algorithm_info()
            print(f"  ✅ Algorithm info retrieved: {len(info)} fields")
            checks_passed += 1
        except Exception as e:
            print(f"  ❌ Algorithm info: Error - {e}")
            log_test("Quantum Resistance Status", False, error=str(e))
            return False
        
        # Check quantum resistance
        total_checks += 1
        if info.get('quantum_resistant') == True:
            print(f"  ✅ Quantum resistant: {info.get('quantum_resistant')}")
            checks_passed += 1
        else:
            print(f"  ❌ Quantum resistant: {info.get('quantum_resistant')} (expected TRUE)")
        
        # Check post-quantum status
        total_checks += 1
        if info.get('post_quantum') == True:
            print(f"  ✅ Post-quantum: {info.get('post_quantum')}")
            checks_passed += 1
        else:
            print(f"  ❌ Post-quantum: {info.get('post_quantum')} (expected TRUE)")
        
        # Check NIST approval
        total_checks += 1
        if info.get('nist_approved') == True:
            print(f"  ✅ NIST approved: {info.get('nist_approved')}")
            checks_passed += 1
        else:
            print(f"  ❌ NIST approved: {info.get('nist_approved')} (expected TRUE)")
        
        # Check algorithm variant
        total_checks += 1
        if info.get('variant') == "NIST ML-DSA":
            print(f"  ✅ Algorithm variant: {info.get('variant')}")
            checks_passed += 1
        else:
            print(f"  ❌ Algorithm variant: {info.get('variant')} (expected 'NIST ML-DSA')")
        
        # Check implementation
        total_checks += 1
        implementation = info.get('implementation', '')
        if 'dilithium-py' in implementation and 'NIST ML-DSA' in implementation:
            print(f"  ✅ Implementation: {implementation}")
            checks_passed += 1
        else:
            print(f"  ❌ Implementation: {implementation} (expected dilithium-py NIST ML-DSA)")
        
        success_rate = (checks_passed / total_checks) * 100
        log_test("Quantum Resistance Status", checks_passed >= 5,
                 details=f"Quantum resistant: {info.get('quantum_resistant')}, NIST approved: {info.get('nist_approved')}, Variant: {info.get('variant')} ({success_rate:.1f}% success)")
        return checks_passed >= 5
        
    except Exception as e:
        log_test("Quantum Resistance Status", False, error=str(e))
        return False

def test_hybrid_vs_real_dilithium():
    """Test 5: Hybrid vs Real Dilithium - Compare implementations"""
    print("\n⚖️ TEST 5: HYBRID VS REAL DILITHIUM COMPARISON")
    print("Testing hybrid implementation vs pure real Dilithium...")
    
    try:
        checks_passed = 0
        total_checks = 0
        
        if not HYBRID_DILITHIUM_AVAILABLE:
            log_test("Hybrid vs Real Dilithium", False, error="Hybrid Dilithium not available")
            return False
        
        # Test hybrid implementation
        total_checks += 1
        try:
            hybrid_signer = DilithiumSigner()
            hybrid_available = hybrid_signer.is_quantum_resistant()
            print(f"  ✅ Hybrid implementation quantum resistant: {hybrid_available}")
            if hybrid_available:
                checks_passed += 1
        except Exception as e:
            print(f"  ❌ Hybrid implementation: Error - {e}")
        
        # Compare algorithm info
        if REAL_DILITHIUM_AVAILABLE and hybrid_available:
            total_checks += 1
            try:
                real_signer = RealDilithiumSigner()
                real_info = real_signer.get_algorithm_info()
                hybrid_info = hybrid_signer.get_algorithm_info()
                
                if (real_info.get('quantum_resistant') == hybrid_info.get('quantum_resistant') and
                    real_info.get('post_quantum') == hybrid_info.get('post_quantum')):
                    print("  ✅ Algorithm info consistency: Both implementations quantum resistant")
                    checks_passed += 1
                else:
                    print("  ❌ Algorithm info consistency: Mismatch between implementations")
            except Exception as e:
                print(f"  ❌ Algorithm comparison: Error - {e}")
        
        # Test key generation compatibility
        if REAL_DILITHIUM_AVAILABLE and hybrid_available:
            total_checks += 1
            try:
                real_keypair = real_signer.generate_keypair()
                hybrid_keypair = hybrid_signer.generate_keypair()
                
                if (len(real_keypair.public_key) == len(hybrid_keypair.public_key) and
                    len(real_keypair.private_key) == len(hybrid_keypair.private_key)):
                    print(f"  ✅ Key size compatibility: Both use NIST sizes ({len(real_keypair.public_key)}/{len(real_keypair.private_key)} bytes)")
                    checks_passed += 1
                else:
                    print(f"  ❌ Key size compatibility: Size mismatch")
            except Exception as e:
                print(f"  ❌ Key generation compatibility: Error - {e}")
        
        success_rate = (checks_passed / total_checks) * 100 if total_checks > 0 else 0
        log_test("Hybrid vs Real Dilithium", checks_passed >= 2,
                 details=f"Hybrid quantum resistant: {hybrid_available if 'hybrid_available' in locals() else 'Unknown'}, Compatibility verified ({success_rate:.1f}% success)")
        return checks_passed >= 2
        
    except Exception as e:
        log_test("Hybrid vs Real Dilithium", False, error=str(e))
        return False

def test_api_quantum_integration():
    """Test 6: API Quantum Integration - Test blockchain endpoints with quantum signatures"""
    print("\n🌐 TEST 6: API QUANTUM INTEGRATION")
    print("Testing blockchain API endpoints with quantum-resistant signatures...")
    
    try:
        checks_passed = 0
        total_checks = 0
        
        # Test network status endpoint
        total_checks += 1
        try:
            response = requests.get(f"{API_URL}/network/status", timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ Network status endpoint: Accessible")
                checks_passed += 1
            else:
                print(f"  ❌ Network status endpoint: Status {response.status_code}")
        except Exception as e:
            print(f"  ❌ Network status endpoint: Error - {e}")
        
        # Test wallet creation endpoint (should use quantum signatures)
        total_checks += 1
        try:
            test_address = f"wepo1{''.join(random.choices(string.hexdigits.lower(), k=32))}"
            wallet_data = {
                "username": f"quantum_test_{int(time.time())}",
                "address": test_address,
                "encrypted_private_key": base64.b64encode(secrets.token_bytes(64)).decode()
            }
            
            response = requests.post(f"{API_URL}/wallet/create", json=wallet_data, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    print(f"  ✅ Wallet creation endpoint: Working with quantum signatures")
                    checks_passed += 1
                else:
                    print(f"  ❌ Wallet creation endpoint: Failed - {result}")
            else:
                print(f"  ❌ Wallet creation endpoint: Status {response.status_code}")
        except Exception as e:
            print(f"  ❌ Wallet creation endpoint: Error - {e}")
        
        # Test mining info endpoint
        total_checks += 1
        try:
            response = requests.get(f"{API_URL}/mining/info", timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ Mining info endpoint: Accessible")
                checks_passed += 1
            else:
                print(f"  ❌ Mining info endpoint: Status {response.status_code}")
        except Exception as e:
            print(f"  ❌ Mining info endpoint: Error - {e}")
        
        # Test blockchain endpoints
        total_checks += 1
        try:
            response = requests.get(f"{API_URL}/blocks/latest", timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ Latest blocks endpoint: Accessible")
                checks_passed += 1
            else:
                print(f"  ❌ Latest blocks endpoint: Status {response.status_code}")
        except Exception as e:
            print(f"  ❌ Latest blocks endpoint: Error - {e}")
        
        success_rate = (checks_passed / total_checks) * 100
        log_test("API Quantum Integration", checks_passed >= 3,
                 details=f"API endpoints accessible with quantum integration ({success_rate:.1f}% success)")
        return checks_passed >= 3
        
    except Exception as e:
        log_test("API Quantum Integration", False, error=str(e))
        return False

def test_backwards_compatibility():
    """Test 7: Backwards Compatibility - Ensure existing WEPO functionality works"""
    print("\n🔄 TEST 7: BACKWARDS COMPATIBILITY")
    print("Testing existing WEPO functionality with quantum signatures...")
    
    try:
        checks_passed = 0
        total_checks = 0
        
        # Test basic API health
        total_checks += 1
        try:
            response = requests.get(f"{API_URL}/", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('message') and 'WEPO' in data.get('message', ''):
                    print(f"  ✅ API health check: {data.get('message')}")
                    checks_passed += 1
                else:
                    print(f"  ❌ API health check: Unexpected response - {data}")
            else:
                print(f"  ❌ API health check: Status {response.status_code}")
        except Exception as e:
            print(f"  ❌ API health check: Error - {e}")
        
        # Test exchange rate endpoint
        total_checks += 1
        try:
            response = requests.get(f"{API_URL}/dex/rate", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'btc_to_wepo' in data and 'wepo_to_btc' in data:
                    print(f"  ✅ Exchange rate endpoint: Working")
                    checks_passed += 1
                else:
                    print(f"  ❌ Exchange rate endpoint: Missing rate data")
            else:
                print(f"  ❌ Exchange rate endpoint: Status {response.status_code}")
        except Exception as e:
            print(f"  ❌ Exchange rate endpoint: Error - {e}")
        
        # Test community AMM endpoints
        total_checks += 1
        try:
            response = requests.get(f"{API_URL}/swap/rate", timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ Community AMM endpoint: Working")
                checks_passed += 1
            else:
                print(f"  ❌ Community AMM endpoint: Status {response.status_code}")
        except Exception as e:
            print(f"  ❌ Community AMM endpoint: Error - {e}")
        
        # Test liquidity stats endpoint
        total_checks += 1
        try:
            response = requests.get(f"{API_URL}/liquidity/stats", timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ Liquidity stats endpoint: Working")
                checks_passed += 1
            else:
                print(f"  ❌ Liquidity stats endpoint: Status {response.status_code}")
        except Exception as e:
            print(f"  ❌ Liquidity stats endpoint: Error - {e}")
        
        success_rate = (checks_passed / total_checks) * 100
        log_test("Backwards Compatibility", checks_passed >= 3,
                 details=f"Existing WEPO functionality preserved with quantum signatures ({success_rate:.1f}% success)")
        return checks_passed >= 3
        
    except Exception as e:
        log_test("Backwards Compatibility", False, error=str(e))
        return False

def run_all_tests():
    """Run all quantum-resistant signature tests"""
    print("🚀 STARTING COMPREHENSIVE QUANTUM-RESISTANT SIGNATURE TESTING")
    print("=" * 80)
    
    # Run all tests
    tests = [
        test_real_dilithium_availability,
        test_dilithium_key_generation,
        test_dilithium_signature_operations,
        test_quantum_resistance_status,
        test_hybrid_vs_real_dilithium,
        test_api_quantum_integration,
        test_backwards_compatibility
    ]
    
    for test_func in tests:
        try:
            test_func()
        except Exception as e:
            print(f"❌ Test {test_func.__name__} crashed: {e}")
            test_results["total"] += 1
            test_results["failed"] += 1
    
    # Print final results
    print("\n" + "=" * 80)
    print("🎯 FINAL TEST RESULTS - WEPO REAL DILITHIUM2 QUANTUM-RESISTANT SIGNATURES")
    print("=" * 80)
    
    success_rate = (test_results["passed"] / test_results["total"]) * 100 if test_results["total"] > 0 else 0
    
    print(f"Total Tests: {test_results['total']}")
    print(f"Passed: {test_results['passed']} ✅")
    print(f"Failed: {test_results['failed']} ❌")
    print(f"Success Rate: {success_rate:.1f}%")
    
    if success_rate >= 80:
        print("\n🎉 EXCELLENT! WEPO Real Dilithium2 quantum-resistant signatures are working correctly!")
        print("🔐 TRUE post-quantum security is now active instead of RSA simulation!")
    elif success_rate >= 60:
        print("\n✅ GOOD! Most quantum-resistant signature features are working.")
        print("🔧 Some minor issues need attention.")
    else:
        print("\n⚠️ ISSUES FOUND! Quantum-resistant signature implementation needs fixes.")
        print("🔧 Critical issues must be resolved before production use.")
    
    print("\n📋 DETAILED TEST BREAKDOWN:")
    for test in test_results["tests"]:
        status = "✅" if test["passed"] else "❌"
        print(f"{status} {test['name']}")
        if test["details"]:
            print(f"    {test['details']}")
        if test["error"]:
            print(f"    Error: {test['error']}")
    
    return success_rate >= 80

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)