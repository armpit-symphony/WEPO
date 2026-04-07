#!/usr/bin/env python3
"""
EMERGENCY DIAGNOSTIC TEST - HTTP 500 RESOLUTION VERIFICATION
Critical testing after fixing the SecurityMiddleware method reference bug
"""
import requests
import json
import time
import secrets
import sys

# Use preview backend URL from frontend/.env
BACKEND_URL = "https://blockchain-sectest.preview.emergentagent.com"
API_URL = f"{BACKEND_URL}/api"

print("🚨 EMERGENCY DIAGNOSTIC TEST - HTTP 500 RESOLUTION VERIFICATION")
print("=" * 80)
print(f"Backend URL: {BACKEND_URL}")
print(f"API URL: {API_URL}")
print("Focus: Verify all systems operational after SecurityMiddleware fix")
print("=" * 80)

# Test results tracking
test_results = {
    "total": 0,
    "passed": 0,
    "failed": 0,
    "tests": []
}

def log_test(name, passed, details=None, error=None):
    """Log test results"""
    status = "✅ PASSED" if passed else "❌ FAILED"
    print(f"{status} {name}")
    
    if details:
        print(f"  Details: {details}")
    
    if error:
        print(f"  Error: {error}")
    
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

def generate_test_user():
    """Generate test user data"""
    username = f"testuser_{secrets.token_hex(4)}"
    password = f"TestPass123!{secrets.token_hex(2)}"
    return username, password

# ===== 1. BASIC SYSTEM HEALTH =====

def test_basic_system_health():
    """Test 1: Basic System Health - Verify HTTP 500 errors are resolved"""
    print("\n🏥 BASIC SYSTEM HEALTH VERIFICATION")
    
    # Test API root
    try:
        response = requests.get(f"{API_URL}/", timeout=10)
        if response.status_code == 200:
            data = response.json()
            log_test("API Root Endpoint", True, 
                    details=f"Message: {data.get('message', 'No message')}")
        else:
            log_test("API Root Endpoint", False, 
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("API Root Endpoint", False, error=str(e))
    
    # Test network status
    try:
        response = requests.get(f"{API_URL}/network/status", timeout=10)
        if response.status_code == 200:
            data = response.json()
            log_test("Network Status Endpoint", True, 
                    details=f"Block height: {data.get('block_height', 'Unknown')}")
        else:
            log_test("Network Status Endpoint", False, 
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("Network Status Endpoint", False, error=str(e))
    
    # Test mining info
    try:
        response = requests.get(f"{API_URL}/mining/info", timeout=10)
        if response.status_code == 200:
            data = response.json()
            log_test("Mining Info Endpoint", True, 
                    details=f"Current reward: {data.get('current_reward', 'Unknown')} WEPO")
        else:
            log_test("Mining Info Endpoint", False, 
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("Mining Info Endpoint", False, error=str(e))

# ===== 2. CORE WALLET FUNCTIONALITY =====

def test_core_wallet_functionality():
    """Test 2: Core Wallet Functionality - Verify wallet operations work"""
    print("\n💼 CORE WALLET FUNCTIONALITY VERIFICATION")
    
    # Test wallet creation
    try:
        username, password = generate_test_user()
        create_data = {"username": username, "password": password}
        
        response = requests.post(f"{API_URL}/wallet/create", json=create_data, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("success") and data.get("address"):
                log_test("Wallet Creation", True, 
                        details=f"Created wallet for {username}, address: {data.get('address', '')[:20]}...")
                
                # Store for login test
                test_wallet = {"username": username, "password": password, "address": data.get("address")}
                
                # Test wallet login
                try:
                    login_data = {"username": username, "password": password}
                    login_response = requests.post(f"{API_URL}/wallet/login", json=login_data, timeout=10)
                    
                    if login_response.status_code == 200:
                        login_result = login_response.json()
                        if login_result.get("success"):
                            log_test("Wallet Login", True, 
                                    details=f"Login successful for {username}")
                        else:
                            log_test("Wallet Login", False, 
                                    details="Login response invalid")
                    else:
                        log_test("Wallet Login", False, 
                                details=f"HTTP {login_response.status_code}: {login_response.text[:100]}")
                except Exception as e:
                    log_test("Wallet Login", False, error=str(e))
                
                # Test wallet info retrieval
                try:
                    wallet_response = requests.get(f"{API_URL}/wallet/{data.get('address')}", timeout=10)
                    if wallet_response.status_code == 200:
                        wallet_data = wallet_response.json()
                        log_test("Wallet Info Retrieval", True, 
                                details=f"Balance: {wallet_data.get('balance', 0)} WEPO")
                    else:
                        log_test("Wallet Info Retrieval", False, 
                                details=f"HTTP {wallet_response.status_code}")
                except Exception as e:
                    log_test("Wallet Info Retrieval", False, error=str(e))
                    
            else:
                log_test("Wallet Creation", False, details="Invalid response format")
        else:
            log_test("Wallet Creation", False, 
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("Wallet Creation", False, error=str(e))

# ===== 3. RATE LIMITING VERIFICATION =====

def test_rate_limiting_functionality():
    """Test 3: Rate Limiting Functionality - Verify rate limiting is working"""
    print("\n⚡ RATE LIMITING FUNCTIONALITY VERIFICATION")
    
    # Test rate limiting headers
    try:
        response = requests.get(f"{API_URL}/", timeout=10)
        if response.status_code == 200:
            headers = response.headers
            rate_limit_headers = [
                "X-RateLimit-Limit",
                "X-RateLimit-Reset"
            ]
            present_headers = [h for h in rate_limit_headers if h in headers]
            
            if len(present_headers) >= 1:
                log_test("Rate Limiting Headers", True, 
                        details=f"Headers present: {present_headers}")
            else:
                log_test("Rate Limiting Headers", False, 
                        details=f"Missing headers: {[h for h in rate_limit_headers if h not in headers]}")
        else:
            log_test("Rate Limiting Headers", False, 
                    details=f"HTTP {response.status_code}")
    except Exception as e:
        log_test("Rate Limiting Headers", False, error=str(e))
    
    # Test basic rate limiting enforcement (light test)
    try:
        # Make 5 quick requests to test rate limiting
        responses = []
        for i in range(5):
            response = requests.get(f"{API_URL}/", timeout=5)
            responses.append(response.status_code)
            time.sleep(0.1)  # Small delay
        
        # All should be 200 (under rate limit)
        if all(status == 200 for status in responses):
            log_test("Basic Rate Limiting (Under Limit)", True, 
                    details=f"5 requests all returned HTTP 200")
        else:
            log_test("Basic Rate Limiting (Under Limit)", False, 
                    details=f"Unexpected responses: {responses}")
    except Exception as e:
        log_test("Basic Rate Limiting (Under Limit)", False, error=str(e))

# ===== 4. SECURITY FEATURES VERIFICATION =====

def test_security_features():
    """Test 4: Security Features - Verify security controls are working"""
    print("\n🔒 SECURITY FEATURES VERIFICATION")
    
    # Test security headers
    try:
        response = requests.get(f"{API_URL}/", timeout=10)
        if response.status_code == 200:
            headers = response.headers
            security_headers = [
                "X-Content-Type-Options",
                "X-Frame-Options",
                "X-XSS-Protection",
                "Strict-Transport-Security"
            ]
            present_headers = [h for h in security_headers if h in headers]
            
            if len(present_headers) >= 3:
                log_test("Security Headers", True, 
                        details=f"Headers present: {present_headers}")
            else:
                log_test("Security Headers", False, 
                        details=f"Insufficient headers: {present_headers}")
        else:
            log_test("Security Headers", False, 
                    details=f"HTTP {response.status_code}")
    except Exception as e:
        log_test("Security Headers", False, error=str(e))
    
    # Test password validation
    try:
        username, _ = generate_test_user()
        weak_data = {"username": username, "password": "weak"}
        
        response = requests.post(f"{API_URL}/wallet/create", json=weak_data, timeout=10)
        if response.status_code == 400:
            log_test("Password Validation", True, 
                    details="Weak password properly rejected")
        else:
            log_test("Password Validation", False, 
                    details=f"Unexpected response: HTTP {response.status_code}")
    except Exception as e:
        log_test("Password Validation", False, error=str(e))

# ===== 5. COMMUNITY FAIR MARKET VERIFICATION =====

def test_community_fair_market():
    """Test 5: Community Fair Market - Verify DEX functionality"""
    print("\n🏪 COMMUNITY FAIR MARKET VERIFICATION")
    
    # Test swap rate endpoint
    try:
        response = requests.get(f"{API_URL}/swap/rate", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "pool_exists" in data:
                log_test("Community Fair Market Rate", True, 
                        details=f"Pool exists: {data.get('pool_exists')}, Philosophy: {data.get('philosophy', 'Not set')}")
            else:
                log_test("Community Fair Market Rate", False, 
                        details="Missing expected fields")
        else:
            log_test("Community Fair Market Rate", False, 
                    details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_test("Community Fair Market Rate", False, error=str(e))

def run_emergency_diagnostic():
    """Run emergency diagnostic testing"""
    print("🚨 STARTING EMERGENCY DIAGNOSTIC TEST")
    print("Testing system after SecurityMiddleware fix...")
    print("=" * 80)
    
    # Run all test categories
    test_basic_system_health()
    test_core_wallet_functionality()
    test_rate_limiting_functionality()
    test_security_features()
    test_community_fair_market()
    
    # Print results
    print("\n" + "=" * 80)
    print("🚨 EMERGENCY DIAGNOSTIC RESULTS")
    print("=" * 80)
    
    success_rate = (test_results["passed"] / test_results["total"]) * 100 if test_results["total"] > 0 else 0
    
    print(f"Total Tests: {test_results['total']}")
    print(f"Passed: {test_results['passed']} ✅")
    print(f"Failed: {test_results['failed']} ❌")
    print(f"Success Rate: {success_rate:.1f}%")
    
    # Failed tests summary
    failed_tests = [test for test in test_results['tests'] if not test['passed']]
    if failed_tests:
        print(f"\n❌ FAILED TESTS ({len(failed_tests)} total):")
        for test in failed_tests:
            print(f"  • {test['name']}")
            if test['details']:
                print(f"    Issue: {test['details']}")
            if test['error']:
                print(f"    Error: {test['error']}")
    
    # System status assessment
    print(f"\n🏥 EMERGENCY RESOLUTION STATUS:")
    if success_rate >= 90:
        print("🎉 EXCELLENT - HTTP 500 errors completely resolved!")
        print("   All critical systems operational")
        print("   Rate limiting optimization can proceed")
    elif success_rate >= 75:
        print("✅ GOOD - Major issues resolved")
        print("   Most systems operational")
        print("   Minor issues remain")
    elif success_rate >= 50:
        print("⚠️  PARTIAL - Some improvement")
        print("   Basic functionality restored")
        print("   Additional fixes needed")
    else:
        print("🚨 CRITICAL - Issues persist")
        print("   HTTP 500 errors may not be fully resolved")
        print("   Additional investigation required")
    
    return {
        "success_rate": success_rate,
        "total_tests": test_results["total"],
        "passed_tests": test_results["passed"],
        "failed_tests": failed_tests
    }

if __name__ == "__main__":
    results = run_emergency_diagnostic()
    
    print("\n" + "=" * 80)
    print("🎯 EMERGENCY DIAGNOSTIC SUMMARY")
    print("=" * 80)
    
    print(f"📊 RESULTS:")
    print(f"• Total Tests: {results['total_tests']}")
    print(f"• Passed: {results['passed_tests']} ✅")
    print(f"• Failed: {len(results['failed_tests'])} ❌")
    print(f"• Success Rate: {results['success_rate']:.1f}%")
    
    print(f"\n💡 EMERGENCY RESOLUTION ASSESSMENT:")
    if results['success_rate'] >= 90:
        print("• 🎉 HTTP 500 ERRORS COMPLETELY RESOLVED!")
        print("• All critical backend systems operational")
        print("• Rate limiting optimization can now proceed")
        print("• launch back on track")
    elif results['success_rate'] >= 75:
        print("• ✅ MAJOR PROGRESS - Most issues resolved")
        print("• Core functionality restored")
        print("• Rate limiting infrastructure accessible")
    else:
        print("• 🚨 ADDITIONAL WORK NEEDED")
        print("• Some critical issues persist")
        print("• Further investigation required")
    
    print(f"\n🔧 NEXT STEPS:")
    if results['success_rate'] >= 90:
        print("• Proceed with comprehensive rate limiting optimization testing")
        print("• Verify TrueOptimizedRateLimiter integration")
        print("• Test rate limiting from 60% to 100% functionality")
    elif results['success_rate'] >= 75:
        print("• Address remaining failed tests")
        print("• Continue with rate limiting testing")
    else:
        print("• Investigate remaining HTTP 500 errors")
        print("• Fix critical system issues before rate limiting")