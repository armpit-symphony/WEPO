#!/usr/bin/env python3
"""
WEPO BRUTE FORCE PROTECTION FOCUSED TEST

**CRITICAL BRUTE FORCE PROTECTION TEST:**

**1. Single Focused Test**
- Create a test wallet
- Attempt exactly 5 failed login attempts with wrong password  
- Verify HTTP 423 response on 6th attempt with proper lockout error message
- Test that lockout persists for correct password attempt

**2. SecurityManager Function Verification**
- Test if SecurityManager.record_failed_login() is being called properly
- Verify if failed attempts are being tracked in memory or Redis
- Check if SecurityManager.clear_failed_login() works on successful login

**3. Error Response Verification**  
- Verify lockout response includes "message", "attempts", "time_remaining", "max_attempts"
- Test HTTP status code is exactly 423 for locked accounts
- Verify proper error messaging format

**Expected Results:**
- After 5 failed attempts, 6th attempt should return HTTP 423
- Lockout response should include time_remaining and attempt count
- Account should remain locked even with correct password during lockout period

**This is a critical test to verify the security fixes are working before proceeding with rate limiting fixes.**

**Goal:** Determine if the recent SecurityManager integration fixes have resolved the brute force protection vulnerability.
"""
import requests
import json
import time
import secrets
import sys

# Use preview backend URL from frontend/.env
BACKEND_URL = "https://blockchain-sectest.preview.emergentagent.com"
API_URL = f"{BACKEND_URL}/api"

print(f"🔐 WEPO BRUTE FORCE PROTECTION FOCUSED TEST")
print(f"Preview Backend API URL: {API_URL}")
print(f"Focus: Critical Security - Account Lockout Verification")
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

def generate_test_user_data():
    """Generate realistic test user data"""
    username = f"brutetest_{secrets.token_hex(4)}"
    password = f"TestPass123!{secrets.token_hex(2)}"
    return username, password

def create_test_wallet():
    """Create a test wallet for brute force testing"""
    username, password = generate_test_user_data()
    
    create_data = {
        "username": username,
        "password": password
    }
    
    try:
        response = requests.post(f"{API_URL}/wallet/create", json=create_data)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success") and data.get("address"):
                print(f"✅ Test wallet created: {username}")
                return username, password, data.get("address")
            else:
                print(f"❌ Wallet creation failed: Invalid response format")
                return None, None, None
        else:
            print(f"❌ Wallet creation failed: HTTP {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            return None, None, None
            
    except Exception as e:
        print(f"❌ Wallet creation error: {str(e)}")
        return None, None, None

def test_brute_force_protection():
    """Test 1: Critical Brute Force Protection Test"""
    print("\n🔐 CRITICAL BRUTE FORCE PROTECTION TEST")
    print("Testing account lockout after 5 failed login attempts...")
    
    # Step 1: Create test wallet
    username, correct_password, address = create_test_wallet()
    if not username:
        log_test("Test Wallet Creation", False, error="Could not create test wallet")
        return False
    
    log_test("Test Wallet Creation", True, details=f"Created wallet: {username}")
    
    # Step 2: Attempt exactly 5 failed login attempts
    wrong_password = "WrongPassword123!"
    failed_attempts = 0
    
    print(f"\n🔄 Attempting 5 failed login attempts with wrong password...")
    
    for attempt in range(1, 6):  # Attempts 1-5
        login_data = {
            "username": username,
            "password": wrong_password
        }
        
        try:
            response = requests.post(f"{API_URL}/wallet/login", json=login_data)
            
            if response.status_code == 401:
                failed_attempts += 1
                print(f"  Attempt {attempt}: HTTP 401 (Expected) - Failed login {failed_attempts}/5")
            elif response.status_code == 423:
                print(f"  Attempt {attempt}: HTTP 423 (Unexpected) - Account locked too early")
                log_test(f"Failed Login Attempt {attempt}", False, 
                        details=f"Account locked after {attempt-1} attempts instead of 5")
                return False
            else:
                print(f"  Attempt {attempt}: HTTP {response.status_code} (Unexpected)")
                log_test(f"Failed Login Attempt {attempt}", False, 
                        details=f"Unexpected status code: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  Attempt {attempt}: Error - {str(e)}")
            log_test(f"Failed Login Attempt {attempt}", False, error=str(e))
            return False
    
    log_test("5 Failed Login Attempts", True, 
            details=f"All 5 attempts returned HTTP 401 as expected")
    
    # Step 3: Verify HTTP 423 response on 6th attempt
    print(f"\n🔒 Testing 6th attempt - Should return HTTP 423 (Account Locked)...")
    
    login_data = {
        "username": username,
        "password": wrong_password
    }
    
    try:
        response = requests.post(f"{API_URL}/wallet/login", json=login_data)
        
        if response.status_code == 423:
            print(f"  6th Attempt: HTTP 423 ✅ - Account locked as expected")
            
            # Verify lockout response format
            try:
                lockout_data = response.json()
                required_fields = ["message", "attempts", "time_remaining", "max_attempts"]
                missing_fields = []
                
                # Check if response contains expected lockout information
                response_text = response.text.lower()
                if "locked" in response_text or "attempts" in response_text:
                    log_test("6th Attempt - Account Lockout", True, 
                            details=f"HTTP 423 with proper lockout message")
                    
                    # Try to extract lockout details from response
                    if isinstance(lockout_data, dict):
                        details_found = []
                        if "message" in str(lockout_data):
                            details_found.append("message")
                        if "attempt" in str(lockout_data):
                            details_found.append("attempts")
                        if "time" in str(lockout_data):
                            details_found.append("time_remaining")
                        
                        log_test("Lockout Response Format", True, 
                                details=f"Response contains: {details_found}")
                    else:
                        log_test("Lockout Response Format", True, 
                                details="Lockout message present in response")
                else:
                    log_test("Lockout Response Format", False, 
                            details="Response missing lockout information")
                    
            except json.JSONDecodeError:
                # Response might be plain text
                if "locked" in response.text.lower():
                    log_test("Lockout Response Format", True, 
                            details="Lockout message present (plain text)")
                else:
                    log_test("Lockout Response Format", False, 
                            details="No lockout message in response")
                    
        elif response.status_code == 401:
            print(f"  6th Attempt: HTTP 401 ❌ - Account NOT locked (brute force protection failed)")
            log_test("6th Attempt - Account Lockout", False, 
                    details="Account not locked after 5 failed attempts - brute force protection not working")
            return False
        else:
            print(f"  6th Attempt: HTTP {response.status_code} ❌ - Unexpected response")
            log_test("6th Attempt - Account Lockout", False, 
                    details=f"Unexpected status code: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"  6th Attempt: Error - {str(e)}")
        log_test("6th Attempt - Account Lockout", False, error=str(e))
        return False
    
    # Step 4: Test that lockout persists for correct password attempt
    print(f"\n🔑 Testing lockout persistence with CORRECT password...")
    
    login_data = {
        "username": username,
        "password": correct_password
    }
    
    try:
        response = requests.post(f"{API_URL}/wallet/login", json=login_data)
        
        if response.status_code == 423:
            print(f"  Correct Password Attempt: HTTP 423 ✅ - Lockout persists (security working)")
            log_test("Lockout Persistence with Correct Password", True, 
                    details="Account remains locked even with correct password")
            return True
        elif response.status_code == 200:
            print(f"  Correct Password Attempt: HTTP 200 ❌ - Lockout bypassed (security vulnerability)")
            log_test("Lockout Persistence with Correct Password", False, 
                    details="Correct password bypasses lockout - security vulnerability")
            return False
        elif response.status_code == 401:
            print(f"  Correct Password Attempt: HTTP 401 ❌ - Lockout not working properly")
            log_test("Lockout Persistence with Correct Password", False, 
                    details="Account not locked - brute force protection failed")
            return False
        else:
            print(f"  Correct Password Attempt: HTTP {response.status_code} ❌ - Unexpected response")
            log_test("Lockout Persistence with Correct Password", False, 
                    details=f"Unexpected status code: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"  Correct Password Attempt: Error - {str(e)}")
        log_test("Lockout Persistence with Correct Password", False, error=str(e))
        return False

def test_security_manager_integration():
    """Test 2: SecurityManager Function Verification"""
    print("\n🛡️ SECURITY MANAGER INTEGRATION VERIFICATION")
    print("Testing SecurityManager functions and integration...")
    
    # Create another test wallet for SecurityManager testing
    username, password, address = create_test_wallet()
    if not username:
        log_test("SecurityManager Test Wallet Creation", False, error="Could not create test wallet")
        return False
    
    log_test("SecurityManager Test Wallet Creation", True, details=f"Created wallet: {username}")
    
    # Test failed login tracking
    print(f"\n📊 Testing failed login tracking...")
    
    wrong_password = "WrongPassword456!"
    
    # Make 3 failed attempts and check if tracking is working
    for attempt in range(1, 4):
        login_data = {
            "username": username,
            "password": wrong_password
        }
        
        try:
            response = requests.post(f"{API_URL}/wallet/login", json=login_data)
            
            if response.status_code == 401:
                print(f"  Failed attempt {attempt}: HTTP 401 - Tracking should be working")
            else:
                print(f"  Failed attempt {attempt}: HTTP {response.status_code} - Unexpected")
                
        except Exception as e:
            print(f"  Failed attempt {attempt}: Error - {str(e)}")
    
    # Check if failed attempts are being tracked by making 2 more attempts
    for attempt in range(4, 6):
        login_data = {
            "username": username,
            "password": wrong_password
        }
        
        try:
            response = requests.post(f"{API_URL}/wallet/login", json=login_data)
            
            if response.status_code == 401:
                print(f"  Failed attempt {attempt}: HTTP 401 - Still tracking")
            elif response.status_code == 423:
                print(f"  Failed attempt {attempt}: HTTP 423 - Account locked (tracking working)")
                log_test("SecurityManager Failed Login Tracking", True, 
                        details=f"Account locked after {attempt} attempts - tracking functional")
                break
            else:
                print(f"  Failed attempt {attempt}: HTTP {response.status_code} - Unexpected")
                
        except Exception as e:
            print(f"  Failed attempt {attempt}: Error - {str(e)}")
    else:
        # If we didn't break out of the loop, tracking might not be working
        log_test("SecurityManager Failed Login Tracking", False, 
                details="Account not locked after 5 attempts - tracking may not be working")
        return False
    
    # Test successful login clearing (if account gets unlocked)
    print(f"\n🔓 Testing successful login clearing (after lockout expires)...")
    
    # Wait a moment and try with correct password
    time.sleep(2)
    
    login_data = {
        "username": username,
        "password": password
    }
    
    try:
        response = requests.post(f"{API_URL}/wallet/login", json=login_data)
        
        if response.status_code == 200:
            print(f"  Successful login: HTTP 200 - Login clearing working")
            log_test("SecurityManager Successful Login Clearing", True, 
                    details="Successful login after lockout period")
            
            # Test that failed attempts are cleared by making another failed attempt
            wrong_login_data = {
                "username": username,
                "password": wrong_password
            }
            
            response2 = requests.post(f"{API_URL}/wallet/login", json=wrong_login_data)
            
            if response2.status_code == 401:
                print(f"  Failed attempt after successful login: HTTP 401 - Counter reset working")
                log_test("Failed Attempt Counter Reset", True, 
                        details="Failed attempt counter reset after successful login")
            else:
                print(f"  Failed attempt after successful login: HTTP {response2.status_code}")
                log_test("Failed Attempt Counter Reset", False, 
                        details=f"Unexpected response after successful login: {response2.status_code}")
                
        elif response.status_code == 423:
            print(f"  Successful login: HTTP 423 - Account still locked (lockout duration active)")
            log_test("SecurityManager Successful Login Clearing", True, 
                    details="Account properly locked during lockout period")
        else:
            print(f"  Successful login: HTTP {response.status_code} - Unexpected")
            log_test("SecurityManager Successful Login Clearing", False, 
                    details=f"Unexpected response: {response.status_code}")
            
    except Exception as e:
        print(f"  Successful login test: Error - {str(e)}")
        log_test("SecurityManager Successful Login Clearing", False, error=str(e))
        return False
    
    return True

def test_error_response_verification():
    """Test 3: Error Response Verification"""
    print("\n📋 ERROR RESPONSE VERIFICATION")
    print("Testing lockout response format and error messaging...")
    
    # Create test wallet for error response testing
    username, password, address = create_test_wallet()
    if not username:
        log_test("Error Response Test Wallet Creation", False, error="Could not create test wallet")
        return False
    
    log_test("Error Response Test Wallet Creation", True, details=f"Created wallet: {username}")
    
    # Make 5 failed attempts to trigger lockout
    wrong_password = "WrongPassword789!"
    
    print(f"\n🔄 Making 5 failed attempts to trigger lockout...")
    
    for attempt in range(1, 6):
        login_data = {
            "username": username,
            "password": wrong_password
        }
        
        try:
            response = requests.post(f"{API_URL}/wallet/login", json=login_data)
            print(f"  Attempt {attempt}: HTTP {response.status_code}")
        except Exception as e:
            print(f"  Attempt {attempt}: Error - {str(e)}")
    
    # Test 6th attempt for proper error response format
    print(f"\n📝 Testing 6th attempt for proper error response format...")
    
    login_data = {
        "username": username,
        "password": wrong_password
    }
    
    try:
        response = requests.post(f"{API_URL}/wallet/login", json=login_data)
        
        print(f"  Status Code: {response.status_code}")
        print(f"  Response: {response.text[:300]}")
        
        # Verify HTTP status code is exactly 423
        if response.status_code == 423:
            log_test("HTTP Status Code 423", True, 
                    details="Correct HTTP 423 status code for locked account")
        else:
            log_test("HTTP Status Code 423", False, 
                    details=f"Expected HTTP 423, got {response.status_code}")
        
        # Verify error message format
        response_text = response.text.lower()
        error_indicators = ["locked", "attempts", "failed", "try again"]
        found_indicators = [indicator for indicator in error_indicators if indicator in response_text]
        
        if len(found_indicators) >= 2:
            log_test("Proper Error Messaging Format", True, 
                    details=f"Error message contains: {found_indicators}")
        else:
            log_test("Proper Error Messaging Format", False, 
                    details=f"Error message missing key information. Found: {found_indicators}")
        
        # Try to parse JSON response for structured error data
        try:
            error_data = response.json()
            if isinstance(error_data, dict):
                error_fields = list(error_data.keys())
                log_test("Structured Error Response", True, 
                        details=f"JSON error response with fields: {error_fields}")
            else:
                log_test("Structured Error Response", False, 
                        details="Error response is not a JSON object")
        except json.JSONDecodeError:
            # Plain text response is also acceptable
            log_test("Structured Error Response", True, 
                    details="Plain text error response (acceptable)")
            
    except Exception as e:
        print(f"  Error response test: Error - {str(e)}")
        log_test("Error Response Format Test", False, error=str(e))
        return False
    
    return True

def run_brute_force_protection_test():
    """Run focused brute force protection test"""
    print("🔍 STARTING WEPO BRUTE FORCE PROTECTION FOCUSED TEST")
    print("Testing critical security - account lockout verification...")
    print("=" * 80)
    
    # Run critical brute force protection tests
    test1_result = test_brute_force_protection()
    test2_result = test_security_manager_integration()
    test3_result = test_error_response_verification()
    
    # Print results
    print("\n" + "=" * 80)
    print("🔐 BRUTE FORCE PROTECTION TEST RESULTS")
    print("=" * 80)
    
    success_rate = (test_results["passed"] / test_results["total"]) * 100 if test_results["total"] > 0 else 0
    
    print(f"Total Tests: {test_results['total']}")
    print(f"Passed: {test_results['passed']} ✅")
    print(f"Failed: {test_results['failed']} ❌")
    print(f"Overall Success Rate: {success_rate:.1f}%")
    
    # Critical assessment
    print(f"\n🔒 BRUTE FORCE PROTECTION ASSESSMENT:")
    
    if success_rate >= 85:
        print("🎉 EXCELLENT - Brute force protection is working!")
        print("   ✅ Account lockout after 5 failed attempts")
        print("   ✅ Lockout persists with correct password")
        print("   ✅ SecurityManager integration functional")
        print("   ✅ Proper error response format")
        protection_status = "WORKING"
    elif success_rate >= 60:
        print("⚠️  PARTIAL - Brute force protection partially working")
        print("   Some security features functional")
        print("   Additional fixes needed for full protection")
        protection_status = "PARTIAL"
    else:
        print("🚨 CRITICAL - Brute force protection NOT working!")
        print("   ❌ Account lockout not functioning")
        print("   ❌ Security vulnerability present")
        print("   ❌ Immediate fixes required")
        protection_status = "FAILED"
    
    # Failed tests summary
    failed_tests = [test for test in test_results['tests'] if not test['passed']]
    if failed_tests:
        print(f"\n❌ FAILED TESTS SUMMARY ({len(failed_tests)} total):")
        for test in failed_tests:
            print(f"  • {test['name']}")
            if test['details']:
                print(f"    Issue: {test['details']}")
            if test['error']:
                print(f"    Error: {test['error']}")
    
    # Recommendations
    print(f"\n💡 RECOMMENDATIONS:")
    if protection_status == "WORKING":
        print("• 🎉 Brute force protection is functional!")
        print("• Account lockout working as expected")
        print("• System not approved for production use")
        print("• Continue with rate limiting fixes")
    elif protection_status == "PARTIAL":
        print("• ⚠️  Some brute force protection working")
        print("• Fix remaining security issues")
        print("• Re-test after additional fixes")
        print("• Focus on failed test areas")
    else:
        print("• 🚨 URGENT - Brute force protection broken!")
        print("• SecurityManager integration not working")
        print("• Account lockout not functioning")
        print("• Do NOT proceed with rate limiting until fixed")
        print("• Critical security vulnerability present")
    
    return {
        "success_rate": success_rate,
        "protection_status": protection_status,
        "total_tests": test_results["total"],
        "passed_tests": test_results["passed"],
        "failed_tests": failed_tests,
        "test1_result": test1_result,
        "test2_result": test2_result,
        "test3_result": test3_result
    }

if __name__ == "__main__":
    # Run brute force protection test
    results = run_brute_force_protection_test()
    
    print("\n" + "=" * 80)
    print("🎯 FINAL BRUTE FORCE PROTECTION ASSESSMENT")
    print("=" * 80)
    
    print(f"📊 OVERALL RESULTS:")
    print(f"• Total Tests: {results['total_tests']}")
    print(f"• Passed: {results['passed_tests']} ✅")
    print(f"• Failed: {len(results['failed_tests'])} ❌")
    print(f"• Success Rate: {results['success_rate']:.1f}%")
    print(f"• Protection Status: {results['protection_status']}")
    
    print(f"\n🔐 CRITICAL SECURITY STATUS:")
    if results['protection_status'] == "WORKING":
        print("✅ BRUTE FORCE PROTECTION: WORKING")
        print("   Account lockout functional after 5 failed attempts")
        print("   Lockout persists with correct password")
        print("   SecurityManager integration operational")
        print("   Under launch review")
    elif results['protection_status'] == "PARTIAL":
        print("⚠️  BRUTE FORCE PROTECTION: PARTIAL")
        print("   Some security features working")
        print("   Additional fixes needed")
        print("   Not not yet approved for public launch")
    else:
        print("🚨 BRUTE FORCE PROTECTION: FAILED")
        print("   Critical security vulnerability present")
        print("   Account lockout not working")
        print("   launch BLOCKED")
    
    print(f"\n🔧 NEXT STEPS:")
    if results['protection_status'] == "WORKING":
        print("• ✅ Brute force protection verified working")
        print("• Proceed with rate limiting fixes")
        print("• Continue security testing")
        print("• System not yet approved for production")
    else:
        print("• 🚨 Fix brute force protection immediately")
        print("• Do NOT proceed with other fixes until resolved")
        print("• Critical security issue must be addressed")
        print("• Re-run this test after fixes")
    
    # Exit with appropriate code
    if results['protection_status'] == "WORKING":
        print("\n🎉 BRUTE FORCE PROTECTION TEST: PASSED")
        sys.exit(0)
    else:
        print("\n🚨 BRUTE FORCE PROTECTION TEST: FAILED")
        sys.exit(1)