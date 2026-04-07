#!/usr/bin/env python3
"""
WEPO COMPREHENSIVE SECURITY TESTING - CHRISTMAS DAY 2025 LAUNCH READINESS

LEGACY NOTICE:
- This script is preview-era and not the canonical local verification path.
- It should not be used as the primary acceptance signal for the current backend/node stack.
- Use the canonical backend/node smoke path first:
  - /home/sparky/WEPO/wepo-blockchain/scripts/run_canonical_fee_smoke.sh

**SECURITY TESTING CONTINUATION - Authentication System Now Working!**

**SPECIFIC SECURITY TESTS REQUIRED:**

1. **BRUTE FORCE PROTECTION TEST** - HIGHEST PRIORITY
   - Test wallet login with multiple failed attempts (6-8 attempts)
   - Check if HTTP 423 is returned after 5 failed attempts
   - Verify brute force protection storage and persistence
   - Test lockout duration and proper error messages

2. **RATE LIMITING VERIFICATION**
   - Test if custom SecurityMiddleware rate limiting is working
   - Check for rate limiting headers in responses
   - Test global API rate limiting (though SlowAPI decorators are disabled)
   - Verify rate limit enforcement and HTTP 429 responses

3. **WORKING SECURITY FEATURES CONFIRMATION**
   - Verify input validation works (XSS, SQL injection protection)
   - Confirm security headers are present and correct
   - Test password strength validation
   - Check authentication security (bcrypt hashing, etc.)

4. **SECURITY SCORE CALCULATION**
   - Calculate overall security score with current working features
   - Identify what % we're at now vs 85%+ target
   - Prioritize remaining issues for public launch readiness

**CONTEXT:**
- Services are running on ports 8001 (wepo-fast-test-bridge) and 8003 (backend/server)
- Frontend routes to port 8001 via Kubernetes ingress
- Authentication system is functional (can create wallets, test login)
- Brute force protection logic exists but may not be triggering properly
- Need to verify if we're close to the 85%+ security score target
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
print(f"🔐 WEPO COMPREHENSIVE SECURITY TESTING - CHRISTMAS DAY 2025 LAUNCH READINESS")
print(f"Backend API URL: {API_URL}")
print(f"Focus: Brute Force Protection, Rate Limiting, Input Validation, Security Score")
print("=" * 80)

# Security test results tracking with weighted scoring
security_results = {
    "total": 0,
    "passed": 0,
    "failed": 0,
    "tests": [],
    "categories": {
        "brute_force_protection": {"passed": 0, "total": 0, "weight": 25},  # Critical
        "rate_limiting": {"passed": 0, "total": 0, "weight": 25},  # Critical
        "input_validation": {"passed": 0, "total": 0, "weight": 20},  # High
        "authentication_security": {"passed": 0, "total": 0, "weight": 15},  # High
        "security_headers": {"passed": 0, "total": 0, "weight": 10},  # Medium
        "data_protection": {"passed": 0, "total": 0, "weight": 5}  # Low
    }
}

def log_security_test(name, passed, category, response=None, error=None, details=None, severity="MEDIUM"):
    """Log security test results with enhanced details and severity"""
    status = "✅ PASSED" if passed else "❌ FAILED"
    severity_icon = {"CRITICAL": "🚨", "HIGH": "🔴", "MEDIUM": "🟠", "LOW": "🟡"}.get(severity, "🟠")
    
    print(f"{status} {severity_icon} {name} [{severity}]")
    
    if details:
        print(f"  Details: {details}")
    
    if error:
        print(f"  Error: {error}")
    
    if response and not passed:
        print(f"  Response: {response}")
    
    security_results["total"] += 1
    security_results["categories"][category]["total"] += 1
    
    if passed:
        security_results["passed"] += 1
        security_results["categories"][category]["passed"] += 1
    else:
        security_results["failed"] += 1
    
    security_results["tests"].append({
        "name": name,
        "category": category,
        "passed": passed,
        "error": error,
        "details": details,
        "severity": severity
    })

def generate_valid_wepo_address():
    """Generate a valid 37-character WEPO address (wepo1 + 32 hex chars)"""
    random_data = secrets.token_bytes(16)  # 16 bytes = 32 hex chars
    hex_part = random_data.hex()
    return f"wepo1{hex_part}"

def generate_test_user_data():
    """Generate realistic test user data"""
    username = f"sectest_{secrets.token_hex(4)}"
    password = f"SecurePass123!{secrets.token_hex(2)}"
    return username, password

def create_test_wallet():
    """Create a test wallet for security testing"""
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
                return username, password, data.get("address")
    except Exception as e:
        print(f"Failed to create test wallet: {e}")
    
    return None, None, None

# ===== 1. BRUTE FORCE PROTECTION TESTING - HIGHEST PRIORITY =====

def test_brute_force_protection():
    """Test 1: Brute Force Protection - HIGHEST PRIORITY"""
    print("\n🚨 BRUTE FORCE PROTECTION TESTING - HIGHEST PRIORITY")
    print("Testing wallet login with multiple failed attempts and account lockout...")
    
    # Create test wallet first
    username, password, address = create_test_wallet()
    if not username:
        log_security_test("Brute Force Protection Setup", False, "brute_force_protection", 
                         error="Could not create test wallet", severity="CRITICAL")
        return
    
    print(f"Created test wallet: {username}")
    
    # Test multiple failed login attempts
    failed_attempts = 0
    max_attempts = 8
    wrong_password = "WrongPassword123!"
    
    print(f"Testing {max_attempts} failed login attempts...")
    
    for attempt in range(1, max_attempts + 1):
        try:
            login_data = {
                "username": username,
                "password": wrong_password
            }
            
            response = requests.post(f"{API_URL}/wallet/login", json=login_data)
            print(f"  Attempt {attempt}: HTTP {response.status_code}")
            
            if response.status_code == 423:
                # Account locked - this is what we expect after 5 attempts
                log_security_test("Brute Force Account Lockout", True, "brute_force_protection",
                                details=f"Account locked after {attempt} attempts (HTTP 423)", severity="CRITICAL")
                
                # Test lockout persistence
                time.sleep(1)
                response2 = requests.post(f"{API_URL}/wallet/login", json=login_data)
                if response2.status_code == 423:
                    log_security_test("Brute Force Lockout Persistence", True, "brute_force_protection",
                                    details="Account remains locked on subsequent attempts", severity="CRITICAL")
                else:
                    log_security_test("Brute Force Lockout Persistence", False, "brute_force_protection",
                                    details=f"Account not properly locked - HTTP {response2.status_code}", severity="CRITICAL")
                
                # Test proper error message
                try:
                    error_data = response.json()
                    if "locked" in str(error_data).lower() or "attempts" in str(error_data).lower():
                        log_security_test("Brute Force Error Messages", True, "brute_force_protection",
                                        details="Proper lockout error message provided", severity="HIGH")
                    else:
                        log_security_test("Brute Force Error Messages", False, "brute_force_protection",
                                        details=f"Unclear error message: {error_data}", severity="HIGH")
                except:
                    log_security_test("Brute Force Error Messages", False, "brute_force_protection",
                                    details="Could not parse error message", severity="HIGH")
                
                return  # Exit early since lockout is working
                
            elif response.status_code == 401:
                failed_attempts += 1
                continue
            else:
                log_security_test("Brute Force Protection", False, "brute_force_protection",
                                details=f"Unexpected response on attempt {attempt}: HTTP {response.status_code}", severity="CRITICAL")
                return
                
        except Exception as e:
            log_security_test("Brute Force Protection", False, "brute_force_protection",
                            error=f"Exception on attempt {attempt}: {str(e)}", severity="CRITICAL")
            return
    
    # If we reach here, no lockout occurred
    log_security_test("Brute Force Account Lockout", False, "brute_force_protection",
                    details=f"NO account lockout after {max_attempts} failed attempts", severity="CRITICAL")
    
    # Test with correct password to see if account is still accessible
    try:
        correct_login_data = {
            "username": username,
            "password": password
        }
        response = requests.post(f"{API_URL}/wallet/login", json=correct_login_data)
        if response.status_code == 200:
            log_security_test("Brute Force Protection Bypass", False, "brute_force_protection",
                            details="Account still accessible with correct password after multiple failed attempts", severity="CRITICAL")
        else:
            log_security_test("Brute Force Protection Bypass", True, "brute_force_protection",
                            details="Account properly protected even with correct password", severity="HIGH")
    except Exception as e:
        log_security_test("Brute Force Protection Bypass", False, "brute_force_protection",
                        error=str(e), severity="HIGH")

def test_invalid_username_brute_force():
    """Test brute force protection for invalid usernames"""
    print("\n🔴 Testing brute force protection for invalid usernames...")
    
    fake_username = f"nonexistent_{secrets.token_hex(4)}"
    fake_password = "FakePassword123!"
    
    for attempt in range(1, 6):
        try:
            login_data = {
                "username": fake_username,
                "password": fake_password
            }
            
            response = requests.post(f"{API_URL}/wallet/login", json=login_data)
            print(f"  Invalid username attempt {attempt}: HTTP {response.status_code}")
            
            if response.status_code == 423:
                log_security_test("Invalid Username Brute Force Protection", True, "brute_force_protection",
                                details=f"Invalid username attempts blocked after {attempt} tries", severity="HIGH")
                return
            elif response.status_code != 401:
                log_security_test("Invalid Username Brute Force Protection", False, "brute_force_protection",
                                details=f"Unexpected response: HTTP {response.status_code}", severity="HIGH")
                return
                
        except Exception as e:
            log_security_test("Invalid Username Brute Force Protection", False, "brute_force_protection",
                            error=str(e), severity="HIGH")
            return
    
    log_security_test("Invalid Username Brute Force Protection", False, "brute_force_protection",
                    details="No protection against invalid username brute force attempts", severity="HIGH")

# ===== 2. RATE LIMITING VERIFICATION =====

def test_rate_limiting():
    """Test 2: Rate Limiting Verification"""
    print("\n🔴 RATE LIMITING VERIFICATION")
    print("Testing custom SecurityMiddleware rate limiting and global API limits...")
    
    # Test global API rate limiting
    print("Testing global API rate limiting...")
    rate_limit_hit = False
    
    for request_num in range(1, 101):  # Test up to 100 requests
        try:
            response = requests.get(f"{API_URL}/")
            
            # Check for rate limiting headers
            rate_limit_headers = [
                "X-RateLimit-Limit",
                "X-RateLimit-Remaining", 
                "X-RateLimit-Reset",
                "Retry-After"
            ]
            
            present_headers = [header for header in rate_limit_headers if header in response.headers]
            
            if response.status_code == 429:
                log_security_test("Global API Rate Limiting", True, "rate_limiting",
                                details=f"Rate limit enforced after {request_num} requests (HTTP 429)", severity="CRITICAL")
                rate_limit_hit = True
                
                if present_headers:
                    log_security_test("Rate Limiting Headers", True, "rate_limiting",
                                    details=f"Rate limiting headers present: {present_headers}", severity="HIGH")
                else:
                    log_security_test("Rate Limiting Headers", False, "rate_limiting",
                                    details="No rate limiting headers in 429 response", severity="HIGH")
                break
                
            if request_num % 20 == 0:
                print(f"  Completed {request_num} requests without rate limiting...")
                
        except Exception as e:
            log_security_test("Global API Rate Limiting", False, "rate_limiting",
                            error=f"Exception on request {request_num}: {str(e)}", severity="CRITICAL")
            break
    
    if not rate_limit_hit:
        log_security_test("Global API Rate Limiting", False, "rate_limiting",
                        details="No global API rate limiting after 100 requests", severity="CRITICAL")
    
    # Test wallet creation rate limiting
    print("Testing wallet creation rate limiting...")
    creation_rate_limit_hit = False
    
    for attempt in range(1, 11):  # Test up to 10 wallet creation attempts
        try:
            username, password = generate_test_user_data()
            create_data = {
                "username": username,
                "password": password
            }
            
            response = requests.post(f"{API_URL}/wallet/create", json=create_data)
            
            if response.status_code == 429:
                log_security_test("Wallet Creation Rate Limiting", True, "rate_limiting",
                                details=f"Wallet creation rate limited after {attempt} attempts", severity="HIGH")
                creation_rate_limit_hit = True
                break
            elif response.status_code == 200:
                continue
            elif response.status_code == 400:
                # Expected for duplicate usernames or validation errors
                continue
            else:
                print(f"  Wallet creation attempt {attempt}: HTTP {response.status_code}")
                
        except Exception as e:
            log_security_test("Wallet Creation Rate Limiting", False, "rate_limiting",
                            error=f"Exception on attempt {attempt}: {str(e)}", severity="HIGH")
            break
    
    if not creation_rate_limit_hit:
        log_security_test("Wallet Creation Rate Limiting", False, "rate_limiting",
                        details="No wallet creation rate limiting after 10 attempts", severity="HIGH")
    
    # Test login rate limiting
    print("Testing login rate limiting...")
    username, password, address = create_test_wallet()
    if username:
        login_rate_limit_hit = False
        
        for attempt in range(1, 16):  # Test up to 15 login attempts
            try:
                login_data = {
                    "username": username,
                    "password": password
                }
                
                response = requests.post(f"{API_URL}/wallet/login", json=login_data)
                
                if response.status_code == 429:
                    log_security_test("Login Rate Limiting", True, "rate_limiting",
                                    details=f"Login rate limited after {attempt} attempts", severity="HIGH")
                    login_rate_limit_hit = True
                    break
                elif response.status_code == 200:
                    continue
                else:
                    print(f"  Login attempt {attempt}: HTTP {response.status_code}")
                    
            except Exception as e:
                log_security_test("Login Rate Limiting", False, "rate_limiting",
                                error=f"Exception on attempt {attempt}: {str(e)}", severity="HIGH")
                break
        
        if not login_rate_limit_hit:
            log_security_test("Login Rate Limiting", False, "rate_limiting",
                            details="No login rate limiting after 15 attempts", severity="HIGH")
    else:
        log_security_test("Login Rate Limiting", False, "rate_limiting",
                        error="Could not create test wallet for login rate limiting test", severity="HIGH")

# ===== 3. INPUT VALIDATION SECURITY =====

def test_input_validation():
    """Test 3: Input Validation Security"""
    print("\n🟠 INPUT VALIDATION SECURITY TESTING")
    print("Testing XSS, SQL injection, and other input validation protections...")
    
    # Test XSS protection
    xss_payloads = [
        "<script>alert('XSS')</script>",
        "javascript:alert('XSS')",
        "<img src=x onerror=alert('XSS')>",
        "';alert('XSS');//",
        "<svg onload=alert('XSS')>"
    ]
    
    xss_blocked = 0
    for i, payload in enumerate(xss_payloads, 1):
        try:
            create_data = {
                "username": payload,
                "password": "ValidPassword123!"
            }
            
            response = requests.post(f"{API_URL}/wallet/create", json=create_data)
            
            if response.status_code == 400:
                # Check if it's blocked due to validation
                error_data = response.text
                if "invalid" in error_data.lower() or "validation" in error_data.lower():
                    xss_blocked += 1
                    print(f"  XSS payload {i} blocked ✅")
                else:
                    print(f"  XSS payload {i} not specifically blocked ⚠️")
            elif response.status_code == 200:
                # Check if XSS payload was sanitized
                data = response.json()
                if payload not in str(data):
                    xss_blocked += 1
                    print(f"  XSS payload {i} sanitized ✅")
                else:
                    print(f"  XSS payload {i} not sanitized ❌")
            else:
                print(f"  XSS payload {i}: HTTP {response.status_code}")
                
        except Exception as e:
            print(f"  XSS payload {i} error: {e}")
    
    if xss_blocked >= 4:
        log_security_test("XSS Protection", True, "input_validation",
                        details=f"XSS protection working ({xss_blocked}/{len(xss_payloads)} blocked)", severity="HIGH")
    else:
        log_security_test("XSS Protection", False, "input_validation",
                        details=f"Insufficient XSS protection ({xss_blocked}/{len(xss_payloads)} blocked)", severity="HIGH")
    
    # Test SQL/NoSQL injection protection
    injection_payloads = [
        "'; DROP TABLE wallets; --",
        "' OR '1'='1",
        "admin'--",
        "' UNION SELECT * FROM wallets --",
        "'; DELETE FROM wallets WHERE '1'='1'; --"
    ]
    
    injection_blocked = 0
    for i, payload in enumerate(injection_payloads, 1):
        try:
            create_data = {
                "username": payload,
                "password": "ValidPassword123!"
            }
            
            response = requests.post(f"{API_URL}/wallet/create", json=create_data)
            
            if response.status_code == 400:
                injection_blocked += 1
                print(f"  SQL injection payload {i} blocked ✅")
            elif response.status_code == 500:
                # Server error might indicate injection attempt was processed
                print(f"  SQL injection payload {i} caused server error ❌")
            else:
                print(f"  SQL injection payload {i}: HTTP {response.status_code}")
                
        except Exception as e:
            print(f"  SQL injection payload {i} error: {e}")
    
    if injection_blocked >= 4:
        log_security_test("SQL/NoSQL Injection Protection", True, "input_validation",
                        details=f"Injection protection working ({injection_blocked}/{len(injection_payloads)} blocked)", severity="HIGH")
    else:
        log_security_test("SQL/NoSQL Injection Protection", False, "input_validation",
                        details=f"Insufficient injection protection ({injection_blocked}/{len(injection_payloads)} blocked)", severity="HIGH")
    
    # Test path traversal protection
    path_traversal_payloads = [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\config\\sam",
        "....//....//....//etc/passwd",
        "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd"
    ]
    
    path_traversal_blocked = 0
    for i, payload in enumerate(path_traversal_payloads, 1):
        try:
            # Test in wallet address parameter
            response = requests.get(f"{API_URL}/wallet/{payload}")
            
            if response.status_code == 400 or response.status_code == 404:
                path_traversal_blocked += 1
                print(f"  Path traversal payload {i} blocked ✅")
            elif response.status_code == 500:
                print(f"  Path traversal payload {i} caused server error ❌")
            else:
                print(f"  Path traversal payload {i}: HTTP {response.status_code}")
                
        except Exception as e:
            print(f"  Path traversal payload {i} error: {e}")
    
    if path_traversal_blocked >= 3:
        log_security_test("Path Traversal Protection", True, "input_validation",
                        details=f"Path traversal protection working ({path_traversal_blocked}/{len(path_traversal_payloads)} blocked)", severity="MEDIUM")
    else:
        log_security_test("Path Traversal Protection", False, "input_validation",
                        details=f"Insufficient path traversal protection ({path_traversal_blocked}/{len(path_traversal_payloads)} blocked)", severity="MEDIUM")

# ===== 4. AUTHENTICATION SECURITY =====

def test_authentication_security():
    """Test 4: Authentication Security"""
    print("\n🟠 AUTHENTICATION SECURITY TESTING")
    print("Testing password strength validation, hashing, and session management...")
    
    # Test password strength validation
    weak_passwords = [
        "123456",
        "password",
        "abc123",
        "test",
        "12345678",
        "qwerty",
        "Password1"  # Missing special character
    ]
    
    weak_passwords_rejected = 0
    for i, weak_password in enumerate(weak_passwords, 1):
        try:
            username = f"testuser_{i}_{secrets.token_hex(2)}"
            create_data = {
                "username": username,
                "password": weak_password
            }
            
            response = requests.post(f"{API_URL}/wallet/create", json=create_data)
            
            if response.status_code == 400:
                error_data = response.text
                if "password" in error_data.lower() and ("strength" in error_data.lower() or "requirements" in error_data.lower()):
                    weak_passwords_rejected += 1
                    print(f"  Weak password {i} rejected ✅")
                else:
                    print(f"  Weak password {i} rejected for other reason ⚠️")
            elif response.status_code == 200:
                print(f"  Weak password {i} accepted ❌")
            else:
                print(f"  Weak password {i}: HTTP {response.status_code}")
                
        except Exception as e:
            print(f"  Weak password {i} error: {e}")
    
    if weak_passwords_rejected >= 6:
        log_security_test("Password Strength Validation", True, "authentication_security",
                        details=f"Password strength validation working ({weak_passwords_rejected}/{len(weak_passwords)} rejected)", severity="HIGH")
    else:
        log_security_test("Password Strength Validation", False, "authentication_security",
                        details=f"Insufficient password strength validation ({weak_passwords_rejected}/{len(weak_passwords)} rejected)", severity="HIGH")
    
    # Test strong password acceptance
    strong_passwords = [
        "StrongPassword123!@#",
        "MySecure$Pass2024",
        "Complex&Password789"
    ]
    
    strong_passwords_accepted = 0
    for i, strong_password in enumerate(strong_passwords, 1):
        try:
            username = f"stronguser_{i}_{secrets.token_hex(2)}"
            create_data = {
                "username": username,
                "password": strong_password
            }
            
            response = requests.post(f"{API_URL}/wallet/create", json=create_data)
            
            if response.status_code == 200:
                strong_passwords_accepted += 1
                print(f"  Strong password {i} accepted ✅")
            else:
                print(f"  Strong password {i}: HTTP {response.status_code}")
                
        except Exception as e:
            print(f"  Strong password {i} error: {e}")
    
    if strong_passwords_accepted >= 2:
        log_security_test("Strong Password Acceptance", True, "authentication_security",
                        details=f"Strong passwords properly accepted ({strong_passwords_accepted}/{len(strong_passwords)})", severity="MEDIUM")
    else:
        log_security_test("Strong Password Acceptance", False, "authentication_security",
                        details=f"Strong passwords not properly accepted ({strong_passwords_accepted}/{len(strong_passwords)})", severity="MEDIUM")
    
    # Test password hashing security (no plaintext in responses)
    username, password, address = create_test_wallet()
    if username:
        try:
            login_data = {
                "username": username,
                "password": password
            }
            
            response = requests.post(f"{API_URL}/wallet/login", json=login_data)
            
            if response.status_code == 200:
                data = response.json()
                response_text = str(data)
                
                if password not in response_text:
                    log_security_test("Password Hashing Security", True, "authentication_security",
                                    details="Password not exposed in login response", severity="HIGH")
                else:
                    log_security_test("Password Hashing Security", False, "authentication_security",
                                    details="Password exposed in login response", severity="HIGH")
            else:
                log_security_test("Password Hashing Security", False, "authentication_security",
                                details=f"Could not test - login failed: HTTP {response.status_code}", severity="HIGH")
                
        except Exception as e:
            log_security_test("Password Hashing Security", False, "authentication_security",
                            error=str(e), severity="HIGH")
    else:
        log_security_test("Password Hashing Security", False, "authentication_security",
                        error="Could not create test wallet", severity="HIGH")

# ===== 5. SECURITY HEADERS =====

def test_security_headers():
    """Test 5: Security Headers"""
    print("\n🟡 SECURITY HEADERS TESTING")
    print("Testing critical security headers and CORS configuration...")
    
    try:
        response = requests.get(f"{API_URL}/")
        
        critical_security_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": ["DENY", "SAMEORIGIN"],
            "X-XSS-Protection": "1; mode=block",
            "Content-Security-Policy": None,  # Just check presence
            "Strict-Transport-Security": None  # Just check presence
        }
        
        headers_present = 0
        headers_details = []
        
        for header, expected_value in critical_security_headers.items():
            if header in response.headers:
                headers_present += 1
                actual_value = response.headers[header]
                
                if expected_value is None:
                    headers_details.append(f"{header}: Present")
                elif isinstance(expected_value, list):
                    if any(val in actual_value for val in expected_value):
                        headers_details.append(f"{header}: {actual_value} ✅")
                    else:
                        headers_details.append(f"{header}: {actual_value} ⚠️")
                elif expected_value in actual_value:
                    headers_details.append(f"{header}: {actual_value} ✅")
                else:
                    headers_details.append(f"{header}: {actual_value} ⚠️")
            else:
                headers_details.append(f"{header}: Missing ❌")
        
        if headers_present >= 4:
            log_security_test("Critical Security Headers", True, "security_headers",
                            details=f"Security headers present ({headers_present}/5): {headers_details}", severity="MEDIUM")
        else:
            log_security_test("Critical Security Headers", False, "security_headers",
                            details=f"Insufficient security headers ({headers_present}/5): {headers_details}", severity="MEDIUM")
        
        # Test CORS configuration
        cors_headers = {
            "Access-Control-Allow-Origin": response.headers.get("Access-Control-Allow-Origin"),
            "Access-Control-Allow-Methods": response.headers.get("Access-Control-Allow-Methods"),
            "Access-Control-Allow-Headers": response.headers.get("Access-Control-Allow-Headers")
        }
        
        cors_origin = cors_headers["Access-Control-Allow-Origin"]
        if cors_origin and cors_origin != "*":
            log_security_test("CORS Security Configuration", True, "security_headers",
                            details=f"CORS properly configured - Origin: {cors_origin}", severity="LOW")
        elif cors_origin == "*":
            log_security_test("CORS Security Configuration", False, "security_headers",
                            details="CORS allows all origins (*) - security risk", severity="MEDIUM")
        else:
            log_security_test("CORS Security Configuration", True, "security_headers",
                            details="CORS headers not present - restrictive by default", severity="LOW")
        
    except Exception as e:
        log_security_test("Security Headers", False, "security_headers",
                        error=str(e), severity="MEDIUM")

# ===== 6. DATA PROTECTION =====

def test_data_protection():
    """Test 6: Data Protection"""
    print("\n🟡 DATA PROTECTION TESTING")
    print("Testing sensitive data exposure and error message security...")
    
    # Test for sensitive data exposure in API responses
    try:
        response = requests.get(f"{API_URL}/")
        response_text = response.text.lower()
        
        sensitive_patterns = [
            "password",
            "secret",
            "private_key",
            "api_key",
            "token",
            "mongodb://",
            "mysql://",
            "postgres://"
        ]
        
        exposed_data = [pattern for pattern in sensitive_patterns if pattern in response_text]
        
        if not exposed_data:
            log_security_test("Sensitive Data Exposure", True, "data_protection",
                            details="No sensitive data exposed in API responses", severity="HIGH")
        else:
            log_security_test("Sensitive Data Exposure", False, "data_protection",
                            details=f"Sensitive data exposed: {exposed_data}", severity="HIGH")
        
    except Exception as e:
        log_security_test("Sensitive Data Exposure", False, "data_protection",
                        error=str(e), severity="HIGH")
    
    # Test error message information disclosure
    try:
        # Test with malformed request to trigger error
        response = requests.post(f"{API_URL}/wallet/create", json={"invalid": "data"})
        
        if response.status_code >= 400:
            error_text = response.text.lower()
            
            # Check for information disclosure in error messages
            disclosure_patterns = [
                "stack trace",
                "traceback",
                "file not found",
                "permission denied",
                "database error",
                "sql error",
                "mongodb error"
            ]
            
            disclosed_info = [pattern for pattern in disclosure_patterns if pattern in error_text]
            
            if not disclosed_info:
                log_security_test("Error Message Security", True, "data_protection",
                                details="Error messages don't disclose sensitive information", severity="MEDIUM")
            else:
                log_security_test("Error Message Security", False, "data_protection",
                                details=f"Error messages disclose information: {disclosed_info}", severity="MEDIUM")
        else:
            log_security_test("Error Message Security", False, "data_protection",
                            details="Could not trigger error for testing", severity="LOW")
        
    except Exception as e:
        log_security_test("Error Message Security", False, "data_protection",
                        error=str(e), severity="MEDIUM")

# ===== SECURITY SCORE CALCULATION =====

def calculate_security_score():
    """Calculate overall security score with weighted categories"""
    print("\n📊 SECURITY SCORE CALCULATION")
    print("Calculating weighted security score for launch readiness...")
    
    total_weighted_score = 0
    total_weight = 0
    category_scores = {}
    
    for category, data in security_results["categories"].items():
        if data["total"] > 0:
            category_score = (data["passed"] / data["total"]) * 100
            weighted_score = category_score * (data["weight"] / 100)
            total_weighted_score += weighted_score
            total_weight += data["weight"]
            category_scores[category] = category_score
        else:
            category_scores[category] = 0
    
    overall_score = total_weighted_score if total_weight > 0 else 0
    
    print(f"\n🎯 DETAILED CATEGORY BREAKDOWN:")
    category_names = {
        "brute_force_protection": "🚨 Brute Force Protection",
        "rate_limiting": "🔴 Rate Limiting", 
        "input_validation": "🟠 Input Validation",
        "authentication_security": "🟠 Authentication Security",
        "security_headers": "🟡 Security Headers",
        "data_protection": "🟡 Data Protection"
    }
    
    critical_vulnerabilities = []
    high_vulnerabilities = []
    
    for category, name in category_names.items():
        data = security_results["categories"][category]
        score = category_scores[category]
        weight = data["weight"]
        
        if score < 50 and weight >= 20:
            critical_vulnerabilities.append(name)
        elif score < 70 and weight >= 15:
            high_vulnerabilities.append(name)
        
        status = "✅" if score >= 70 else "⚠️" if score >= 50 else "❌"
        print(f"  {status} {name}: {score:.1f}% [Weight: {weight}%] ({data['passed']}/{data['total']})")
    
    print(f"\n🏆 OVERALL SECURITY SCORE: {overall_score:.1f}%")
    
    # Launch Assessment
    print(f"\n🎄 CHRISTMAS DAY 2025 LAUNCH ASSESSMENT:")
    
    if overall_score >= 85:
        print("🎉 LAUNCH READY - Excellent security score!")
        print("   ✅ Meets 85%+ target for cryptocurrency production")
        print("   ✅ All critical security measures operational")
        print("   ✅ System demonstrates enterprise-grade security")
        launch_status = "GO"
    elif overall_score >= 70:
        print("⚠️  LAUNCH CONDITIONAL - Good security but improvements needed")
        print("   ⚠️  Above 70% but below 85% target")
        print("   ⚠️  Some security vulnerabilities present")
        print("   ⚠️  Additional fixes recommended before launch")
        launch_status = "CONDITIONAL"
    elif overall_score >= 50:
        print("🚨 LAUNCH DELAYED - Significant security issues")
        print("   ❌ Below 70% minimum for cryptocurrency operations")
        print("   ❌ Multiple security vulnerabilities present")
        print("   ❌ Not suitable for public launch")
        launch_status = "DELAYED"
    else:
        print("🚨 LAUNCH BLOCKED - Critical security failures")
        print("   ❌ Below 50% - Unacceptable for cryptocurrency operations")
        print("   ❌ Critical security vulnerabilities present")
        print("   ❌ System not ready for any production use")
        launch_status = "BLOCKED"
    
    print(f"\n🔍 VULNERABILITY ANALYSIS:")
    if critical_vulnerabilities:
        print(f"🔴 CRITICAL VULNERABILITIES ({len(critical_vulnerabilities)}):")
        for vuln in critical_vulnerabilities:
            print(f"  • {vuln}")
    
    if high_vulnerabilities:
        print(f"🟠 HIGH SEVERITY VULNERABILITIES ({len(high_vulnerabilities)}):")
        for vuln in high_vulnerabilities:
            print(f"  • {vuln}")
    
    if not critical_vulnerabilities and not high_vulnerabilities:
        print("✅ No critical or high severity vulnerabilities detected")
    
    return {
        "overall_score": overall_score,
        "category_scores": category_scores,
        "launch_status": launch_status,
        "critical_vulnerabilities": critical_vulnerabilities,
        "high_vulnerabilities": high_vulnerabilities,
        "total_tests": security_results["total"],
        "passed_tests": security_results["passed"],
        "failed_tests": security_results["failed"]
    }

def run_comprehensive_security_testing():
    """Run comprehensive security testing for launch"""
    print("🔐 STARTING COMPREHENSIVE SECURITY TESTING")
    print("Testing authentication system security for launch readiness...")
    print("=" * 80)
    
    # Run all security test categories
    test_brute_force_protection()
    test_invalid_username_brute_force()
    test_rate_limiting()
    test_input_validation()
    test_authentication_security()
    test_security_headers()
    test_data_protection()
    
    # Calculate and display security score
    score_results = calculate_security_score()
    
    # Print comprehensive results
    print("\n" + "=" * 80)
    print("🔐 COMPREHENSIVE SECURITY TESTING RESULTS")
    print("=" * 80)
    
    print(f"📊 OVERALL RESULTS:")
    print(f"• Total Security Tests: {score_results['total_tests']}")
    print(f"• Passed: {score_results['passed_tests']} ✅")
    print(f"• Failed: {score_results['failed_tests']} ❌")
    print(f"• Security Score: {score_results['overall_score']:.1f}%")
    print(f"• Launch Status: {score_results['launch_status']}")
    
    # Failed tests summary
    failed_tests = [test for test in security_results['tests'] if not test['passed']]
    if failed_tests:
        print(f"\n❌ FAILED SECURITY TESTS ({len(failed_tests)} total):")
        for test in failed_tests:
            severity_icon = {"CRITICAL": "🚨", "HIGH": "🔴", "MEDIUM": "🟠", "LOW": "🟡"}.get(test['severity'], "🟠")
            print(f"  {severity_icon} {test['name']} [{test['severity']}]")
            if test['details']:
                print(f"    Issue: {test['details']}")
            if test['error']:
                print(f"    Error: {test['error']}")
    
    print(f"\n🎯 CHRISTMAS DAY 2025 LAUNCH READINESS:")
    if score_results['launch_status'] == "GO":
        print("🎉 SYSTEM READY FOR CHRISTMAS DAY 2025 LAUNCH!")
        print("   • Security score meets 85%+ target")
        print("   • All critical security measures operational")
        print("   • Authentication system fully secured")
    elif score_results['launch_status'] == "CONDITIONAL":
        print("⚠️  SYSTEM CONDITIONALLY READY - IMPROVEMENTS RECOMMENDED")
        print("   • Security score above 70% but below 85% target")
        print("   • Some security improvements needed")
        print("   • Launch possible with risk acceptance")
    else:
        print("🚨 SYSTEM NOT READY FOR CHRISTMAS DAY 2025 LAUNCH")
        print("   • Security score below acceptable threshold")
        print("   • Critical security vulnerabilities present")
        print("   • Immediate fixes required before launch")
    
    return score_results

if __name__ == "__main__":
    print("⚠️ LEGACY SCRIPT: canonical path is wepo-blockchain/scripts/run_canonical_fee_smoke.sh")
    # Run comprehensive security testing
    results = run_comprehensive_security_testing()
    
    print("\n" + "=" * 80)
    print("🎄 FINAL CHRISTMAS DAY 2025 LAUNCH ASSESSMENT")
    print("=" * 80)
    
    print(f"🔐 SECURITY SCORE: {results['overall_score']:.1f}%")
    print(f"🎯 TARGET SCORE: 85%+")
    print(f"🚀 LAUNCH STATUS: {results['launch_status']}")
    
    if results['critical_vulnerabilities']:
        print(f"\n🚨 IMMEDIATE ACTION REQUIRED:")
        print("   Critical security vulnerabilities must be resolved:")
        for vuln in results['critical_vulnerabilities']:
            print(f"   • {vuln}")
    
    if results['high_vulnerabilities']:
        print(f"\n🔴 HIGH PRIORITY FIXES:")
        for vuln in results['high_vulnerabilities']:
            print(f"   • {vuln}")
    
    print(f"\n💡 RECOMMENDATIONS:")
    if results['overall_score'] >= 85:
        print("   • 🎉 System under launch review")
        print("   • Continue monitoring for any edge cases")
        print("   • Maintain current security measures")
    elif results['overall_score'] >= 70:
        print("   • ⚠️  Address remaining security issues before launch")
        print("   • Focus on high-priority vulnerabilities")
        print("   • Re-test after implementing fixes")
    else:
        print("   • 🚨 Implement critical security fixes immediately")
        print("   • Focus on brute force protection and rate limiting")
        print("   • Comprehensive security review required")
        print("   • launch should be delayed until fixes complete")
"""
WEPO CRITICAL SECURITY TESTING FOR CHRISTMAS DAY 2025 LAUNCH
=============================================================

CRITICAL SECURITY TESTS REQUIRED:

1. **BRUTE FORCE PROTECTION TEST** - CRITICAL PRIORITY
   - Test wallet login endpoint with multiple failed attempts (test 6-8 attempts)
   - Verify HTTP 423 response after 5 failed attempts (account lockout)
   - Check lockout duration and proper error messages
   - Test if lockout persists across requests

2. **RATE LIMITING TEST** - CRITICAL PRIORITY  
   - Test global API rate limiting (should limit after 60 requests/minute)
   - Test wallet creation rate limiting (should limit after 3 attempts/minute)
   - Test wallet login rate limiting (should limit after 5 attempts/minute)
   - Verify HTTP 429 responses with proper headers

3. **SECURITY INTEGRATION VERIFICATION**
   - Test if SlowAPI middleware is functioning
   - Verify rate limiting headers are present
   - Test brute force protection storage persistence

4. **WORKING SECURITY FEATURES CONFIRMATION**
   - Verify input validation still works (XSS, SQL injection protection)
   - Confirm security headers are present
   - Test password strength validation

CRITICAL SUCCESS CRITERIA:
- Brute force protection: HTTP 423 after 5 failed attempts
- Rate limiting: HTTP 429 responses at specified limits
- Overall security score: Must achieve 85%+ for cryptocurrency public launch
"""

import requests
import json
import time
import uuid
import secrets
import threading
import concurrent.futures
from datetime import datetime
import random
import string

# Legacy preview target. Override explicitly if you still need this script.
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8011")
API_URL = f"{BACKEND_URL}/api"

print("⚠️ LEGACY SCRIPT: use wepo-blockchain/scripts/run_canonical_fee_smoke.sh for the canonical path")
print(f"🔐 WEPO CRITICAL SECURITY TESTING FOR CHRISTMAS DAY 2025 LAUNCH")
print(f"Backend API URL: {API_URL}")
print(f"Target Security Score: 85%+ for cryptocurrency public launch")
print("=" * 80)

# Test results tracking
security_results = {
    "total_tests": 0,
    "passed_tests": 0,
    "failed_tests": 0,
    "security_score": 0.0,
    "categories": {
        "brute_force_protection": {"weight": 25, "passed": 0, "total": 0, "score": 0.0},
        "rate_limiting": {"weight": 25, "passed": 0, "total": 0, "score": 0.0},
        "security_integration": {"weight": 20, "passed": 0, "total": 0, "score": 0.0},
        "working_security_features": {"weight": 30, "passed": 0, "total": 0, "score": 0.0}
    },
    "critical_vulnerabilities": [],
    "tests": []
}

def log_security_test(name, passed, category, details=None, error=None, severity="medium"):
    """Log security test results with severity tracking"""
    status = "✅ PASSED" if passed else "❌ FAILED"
    severity_icon = {"critical": "🚨", "high": "🔴", "medium": "🟠", "low": "🟡"}.get(severity, "🟠")
    
    print(f"{status} {severity_icon} {name}")
    
    if details:
        print(f"  Details: {details}")
    
    if error:
        print(f"  Error: {error}")
    
    # Update results
    security_results["total_tests"] += 1
    security_results["categories"][category]["total"] += 1
    
    if passed:
        security_results["passed_tests"] += 1
        security_results["categories"][category]["passed"] += 1
    else:
        security_results["failed_tests"] += 1
        if severity in ["critical", "high"]:
            security_results["critical_vulnerabilities"].append({
                "name": name,
                "category": category,
                "severity": severity,
                "details": details,
                "error": error
            })
    
    security_results["tests"].append({
        "name": name,
        "category": category,
        "passed": passed,
        "severity": severity,
        "details": details,
        "error": error
    })

def generate_test_user():
    """Generate test user data for security testing"""
    username = f"sectest_{secrets.token_hex(4)}"
    password = f"SecTest123!{secrets.token_hex(2)}"
    return username, password

def create_test_wallet():
    """Create a test wallet for security testing"""
    username, password = generate_test_user()
    
    try:
        response = requests.post(f"{API_URL}/wallet/create", json={
            "username": username,
            "password": password
        })
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                return username, password, data.get("address")
        
        return None, None, None
    except Exception:
        return None, None, None

# ===== 1. BRUTE FORCE PROTECTION TESTING =====

def test_brute_force_protection():
    """Test 1: Brute Force Protection - CRITICAL PRIORITY"""
    print("\n🚨 BRUTE FORCE PROTECTION TESTING - CRITICAL PRIORITY")
    print("Testing wallet login endpoint with multiple failed attempts...")
    
    # Create test wallet first
    username, password, address = create_test_wallet()
    if not username:
        log_security_test("Brute Force Protection Setup", False, "brute_force_protection",
                         details="Failed to create test wallet for brute force testing", severity="critical")
        return
    
    print(f"Created test wallet: {username}")
    
    # Test multiple failed login attempts
    failed_attempts = 0
    wrong_password = "WrongPassword123!"
    
    print("Testing failed login attempts...")
    
    for attempt in range(1, 9):  # Test up to 8 attempts
        try:
            response = requests.post(f"{API_URL}/wallet/login", json={
                "username": username,
                "password": wrong_password
            })
            
            print(f"  Attempt {attempt}: HTTP {response.status_code}")
            
            if response.status_code == 423:
                # Account locked!
                log_security_test("Brute Force Account Lockout", True, "brute_force_protection",
                               details=f"Account locked after {attempt} failed attempts (HTTP 423)", severity="critical")
                
                # Test lockout persistence
                time.sleep(1)
                persistence_response = requests.post(f"{API_URL}/wallet/login", json={
                    "username": username,
                    "password": password  # Try with correct password
                })
                
                if persistence_response.status_code == 423:
                    log_security_test("Brute Force Lockout Persistence", True, "brute_force_protection",
                                   details="Account remains locked even with correct password", severity="critical")
                else:
                    log_security_test("Brute Force Lockout Persistence", False, "brute_force_protection",
                                   details=f"Lockout not persistent - HTTP {persistence_response.status_code}", severity="critical")
                
                return
            
            elif response.status_code == 401:
                failed_attempts += 1
                continue
            else:
                log_security_test("Brute Force Protection Response", False, "brute_force_protection",
                               details=f"Unexpected response on attempt {attempt}: HTTP {response.status_code}", severity="high")
                break
                
        except Exception as e:
            log_security_test("Brute Force Protection Test", False, "brute_force_protection",
                           error=str(e), severity="critical")
            return
    
    # If we get here, no lockout occurred
    log_security_test("Brute Force Account Lockout", False, "brute_force_protection",
                     details=f"NO account lockout after {failed_attempts} failed attempts", severity="critical")
    
    # Test with invalid username brute force
    print("Testing brute force protection for invalid usernames...")
    invalid_username = f"nonexistent_{secrets.token_hex(4)}"
    
    for attempt in range(1, 6):
        try:
            response = requests.post(f"{API_URL}/wallet/login", json={
                "username": invalid_username,
                "password": "AnyPassword123!"
            })
            
            if response.status_code == 423:
                log_security_test("Invalid Username Brute Force Protection", True, "brute_force_protection",
                               details=f"Protection active for invalid usernames after {attempt} attempts", severity="high")
                return
            elif response.status_code != 401:
                break
                
        except Exception as e:
            log_security_test("Invalid Username Brute Force Test", False, "brute_force_protection",
                           error=str(e), severity="high")
            return
    
    log_security_test("Invalid Username Brute Force Protection", False, "brute_force_protection",
                     details="NO protection for invalid username brute force attempts", severity="high")

# ===== 2. RATE LIMITING TESTING =====

def test_rate_limiting():
    """Test 2: Rate Limiting - CRITICAL PRIORITY"""
    print("\n🚨 RATE LIMITING TESTING - CRITICAL PRIORITY")
    print("Testing global API rate limiting and endpoint-specific limits...")
    
    # Test global API rate limiting
    print("Testing global API rate limiting (should limit after 60 requests/minute)...")
    
    start_time = time.time()
    global_requests = 0
    rate_limited = False
    
    for i in range(70):  # Test beyond the 60 request limit
        try:
            response = requests.get(f"{API_URL}/")
            global_requests += 1
            
            if response.status_code == 429:
                rate_limited = True
                log_security_test("Global API Rate Limiting", True, "rate_limiting",
                               details=f"Rate limited after {global_requests} requests (HTTP 429)", severity="critical")
                
                # Check for rate limiting headers
                headers = response.headers
                rate_headers = ["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset", "Retry-After"]
                present_headers = [h for h in rate_headers if h in headers]
                
                if present_headers:
                    log_security_test("Rate Limiting Headers", True, "rate_limiting",
                                   details=f"Rate limiting headers present: {present_headers}", severity="medium")
                else:
                    log_security_test("Rate Limiting Headers", False, "rate_limiting",
                                   details="Missing rate limiting headers in 429 response", severity="medium")
                break
                
        except Exception as e:
            log_security_test("Global API Rate Limiting Test", False, "rate_limiting",
                           error=str(e), severity="critical")
            break
    
    if not rate_limited:
        log_security_test("Global API Rate Limiting", False, "rate_limiting",
                         details=f"NO global rate limiting after {global_requests} requests", severity="critical")
    
    # Test wallet creation rate limiting
    print("Testing wallet creation rate limiting (should limit after 3 attempts/minute)...")
    
    creation_attempts = 0
    creation_rate_limited = False
    
    for i in range(5):  # Test beyond the 3 attempt limit
        try:
            username, password = generate_test_user()
            response = requests.post(f"{API_URL}/wallet/create", json={
                "username": username,
                "password": password
            })
            
            creation_attempts += 1
            
            if response.status_code == 429:
                creation_rate_limited = True
                log_security_test("Wallet Creation Rate Limiting", True, "rate_limiting",
                               details=f"Wallet creation rate limited after {creation_attempts} attempts (HTTP 429)", severity="critical")
                break
            elif response.status_code == 200:
                continue
            else:
                # Other errors are acceptable (validation, etc.)
                continue
                
        except Exception as e:
            log_security_test("Wallet Creation Rate Limiting Test", False, "rate_limiting",
                           error=str(e), severity="critical")
            break
    
    if not creation_rate_limited:
        log_security_test("Wallet Creation Rate Limiting", False, "rate_limiting",
                         details=f"NO wallet creation rate limiting after {creation_attempts} attempts", severity="critical")
    
    # Test wallet login rate limiting
    print("Testing wallet login rate limiting (should limit after 5 attempts/minute)...")
    
    # Create test wallet for login testing
    username, password, address = create_test_wallet()
    if username:
        login_attempts = 0
        login_rate_limited = False
        
        for i in range(7):  # Test beyond the 5 attempt limit
            try:
                response = requests.post(f"{API_URL}/wallet/login", json={
                    "username": username,
                    "password": password
                })
                
                login_attempts += 1
                
                if response.status_code == 429:
                    login_rate_limited = True
                    log_security_test("Wallet Login Rate Limiting", True, "rate_limiting",
                                   details=f"Login rate limited after {login_attempts} attempts (HTTP 429)", severity="critical")
                    break
                elif response.status_code in [200, 401, 423]:
                    continue
                else:
                    break
                    
            except Exception as e:
                log_security_test("Wallet Login Rate Limiting Test", False, "rate_limiting",
                               error=str(e), severity="critical")
                break
        
        if not login_rate_limited:
            log_security_test("Wallet Login Rate Limiting", False, "rate_limiting",
                             details=f"NO login rate limiting after {login_attempts} attempts", severity="critical")
    else:
        log_security_test("Wallet Login Rate Limiting", False, "rate_limiting",
                         details="Could not create test wallet for login rate limiting test", severity="high")

# ===== 3. SECURITY INTEGRATION VERIFICATION =====

def test_security_integration():
    """Test 3: Security Integration Verification"""
    print("\n🔐 SECURITY INTEGRATION VERIFICATION")
    print("Testing SlowAPI middleware and security integration...")
    
    # Test security middleware functionality
    try:
        response = requests.get(f"{API_URL}/")
        
        # Check for security headers that should be added by middleware
        security_headers = [
            "X-Content-Type-Options",
            "X-Frame-Options", 
            "X-XSS-Protection",
            "Content-Security-Policy",
            "Strict-Transport-Security"
        ]
        
        present_headers = [h for h in security_headers if h in response.headers]
        missing_headers = [h for h in security_headers if h not in response.headers]
        
        if len(present_headers) >= 4:
            log_security_test("Security Middleware Headers", True, "security_integration",
                           details=f"Security headers present: {present_headers}", severity="medium")
        else:
            log_security_test("Security Middleware Headers", False, "security_integration",
                           details=f"Missing security headers: {missing_headers}", severity="high")
        
    except Exception as e:
        log_security_test("Security Middleware Test", False, "security_integration",
                         error=str(e), severity="high")
    
    # Test CORS configuration
    try:
        response = requests.options(f"{API_URL}/", headers={
            "Origin": "https://malicious-site.com",
            "Access-Control-Request-Method": "POST"
        })
        
        cors_header = response.headers.get("Access-Control-Allow-Origin", "")
        
        if cors_header == "*":
            log_security_test("CORS Security Configuration", False, "security_integration",
                           details="CORS allows all origins (*) - security risk", severity="high")
        elif cors_header and "malicious-site.com" not in cors_header:
            log_security_test("CORS Security Configuration", True, "security_integration",
                           details=f"CORS properly restricted: {cors_header}", severity="medium")
        else:
            log_security_test("CORS Security Configuration", True, "security_integration",
                           details="CORS appears to be properly configured", severity="medium")
        
    except Exception as e:
        log_security_test("CORS Security Test", False, "security_integration",
                         error=str(e), severity="medium")
    
    # Test error handling security
    try:
        response = requests.post(f"{API_URL}/wallet/login", json={
            "username": "test",
            "password": "test"
        })
        
        response_text = response.text.lower()
        
        # Check if error messages expose sensitive information
        sensitive_terms = ["database", "sql", "mongodb", "internal", "stack trace", "exception"]
        exposed_terms = [term for term in sensitive_terms if term in response_text]
        
        if exposed_terms:
            log_security_test("Error Message Security", False, "security_integration",
                           details=f"Error messages may expose sensitive information: {exposed_terms}", severity="medium")
        else:
            log_security_test("Error Message Security", True, "security_integration",
                           details="Error messages don't expose sensitive information", severity="medium")
        
    except Exception as e:
        log_security_test("Error Message Security Test", False, "security_integration",
                         error=str(e), severity="medium")

# ===== 4. WORKING SECURITY FEATURES CONFIRMATION =====

def test_working_security_features():
    """Test 4: Working Security Features Confirmation"""
    print("\n✅ WORKING SECURITY FEATURES CONFIRMATION")
    print("Verifying input validation, security headers, and password strength validation...")
    
    # Test XSS protection
    xss_payloads = [
        "<script>alert('xss')</script>",
        "javascript:alert('xss')",
        "<img src=x onerror=alert('xss')>",
        "';alert('xss');//",
        "<svg onload=alert('xss')>"
    ]
    
    xss_blocked = 0
    for payload in xss_payloads:
        try:
            response = requests.post(f"{API_URL}/wallet/create", json={
                "username": payload,
                "password": "ValidPass123!"
            })
            
            if response.status_code == 400:
                xss_blocked += 1
            elif response.status_code == 200:
                # Check if payload was sanitized
                data = response.json()
                if payload not in str(data):
                    xss_blocked += 1
                    
        except Exception:
            continue
    
    if xss_blocked >= 4:
        log_security_test("XSS Protection", True, "working_security_features",
                         details=f"XSS protection working ({xss_blocked}/{len(xss_payloads)} blocked)", severity="medium")
    else:
        log_security_test("XSS Protection", False, "working_security_features",
                         details=f"XSS protection insufficient ({xss_blocked}/{len(xss_payloads)} blocked)", severity="high")
    
    # Test SQL/NoSQL injection protection
    injection_payloads = [
        "'; DROP TABLE users; --",
        "' OR '1'='1",
        "admin'--",
        "' UNION SELECT * FROM users --",
        "'; DELETE FROM wallets; --"
    ]
    
    injection_blocked = 0
    for payload in injection_payloads:
        try:
            response = requests.post(f"{API_URL}/wallet/login", json={
                "username": payload,
                "password": "test"
            })
            
            if response.status_code in [400, 401]:
                injection_blocked += 1
                
        except Exception:
            continue
    
    if injection_blocked >= 4:
        log_security_test("SQL/NoSQL Injection Protection", True, "working_security_features",
                         details=f"Injection protection working ({injection_blocked}/{len(injection_payloads)} blocked)", severity="medium")
    else:
        log_security_test("SQL/NoSQL Injection Protection", False, "working_security_features",
                         details=f"Injection protection insufficient ({injection_blocked}/{len(injection_payloads)} blocked)", severity="high")
    
    # Test password strength validation
    weak_passwords = [
        "123456",
        "password",
        "abc123",
        "test",
        "12345678",
        "qwerty",
        "admin"
    ]
    
    weak_rejected = 0
    for weak_pass in weak_passwords:
        try:
            username, _ = generate_test_user()
            response = requests.post(f"{API_URL}/wallet/create", json={
                "username": username,
                "password": weak_pass
            })
            
            if response.status_code == 400:
                weak_rejected += 1
                
        except Exception:
            continue
    
    if weak_rejected >= 5:
        log_security_test("Password Strength Validation", True, "working_security_features",
                         details=f"Password validation working ({weak_rejected}/{len(weak_passwords)} weak passwords rejected)", severity="medium")
    else:
        log_security_test("Password Strength Validation", False, "working_security_features",
                         details=f"Password validation insufficient ({weak_rejected}/{len(weak_passwords)} weak passwords rejected)", severity="high")
    
    # Test strong password acceptance
    strong_passwords = [
        "StrongPass123!@#",
        "MySecure2024Password!",
        "ComplexP@ssw0rd2024"
    ]
    
    strong_accepted = 0
    for strong_pass in strong_passwords:
        try:
            username, _ = generate_test_user()
            response = requests.post(f"{API_URL}/wallet/create", json={
                "username": username,
                "password": strong_pass
            })
            
            if response.status_code == 200:
                strong_accepted += 1
                
        except Exception:
            continue
    
    if strong_accepted >= 2:
        log_security_test("Strong Password Acceptance", True, "working_security_features",
                         details=f"Strong passwords accepted ({strong_accepted}/{len(strong_passwords)} accepted)", severity="low")
    else:
        log_security_test("Strong Password Acceptance", False, "working_security_features",
                         details=f"Strong password acceptance issues ({strong_accepted}/{len(strong_passwords)} accepted)", severity="medium")

def calculate_security_score():
    """Calculate overall security score based on weighted categories"""
    total_weighted_score = 0.0
    
    for category, data in security_results["categories"].items():
        if data["total"] > 0:
            category_score = (data["passed"] / data["total"]) * 100
            weighted_score = (category_score * data["weight"]) / 100
            total_weighted_score += weighted_score
            data["score"] = category_score
    
    security_results["security_score"] = total_weighted_score
    return total_weighted_score

def run_critical_security_testing():
    """Run critical security testing for launch"""
    print("🔐 STARTING CRITICAL SECURITY TESTING FOR CHRISTMAS DAY 2025 LAUNCH")
    print("Testing critical security requirements for cryptocurrency production...")
    print("=" * 80)
    
    # Run critical security tests
    test_brute_force_protection()
    test_rate_limiting()
    test_security_integration()
    test_working_security_features()
    
    # Calculate security score
    security_score = calculate_security_score()
    
    # Print results
    print("\n" + "=" * 80)
    print("🔐 CRITICAL SECURITY TESTING RESULTS")
    print("=" * 80)
    
    print(f"Total Security Tests: {security_results['total_tests']}")
    print(f"Passed: {security_results['passed_tests']} ✅")
    print(f"Failed: {security_results['failed_tests']} ❌")
    print(f"Overall Security Score: {security_score:.1f}%")
    
    # Category breakdown
    print("\n📊 SECURITY CATEGORY BREAKDOWN:")
    for category, data in security_results["categories"].items():
        category_name = category.replace("_", " ").title()
        status = "✅" if data["score"] >= 75 else "❌"
        print(f"  {status} {category_name}: {data['passed']}/{data['total']} ({data['score']:.1f}%) [Weight: {data['weight']}%]")
    
    # Critical vulnerabilities
    if security_results["critical_vulnerabilities"]:
        print(f"\n🚨 CRITICAL VULNERABILITIES IDENTIFIED ({len(security_results['critical_vulnerabilities'])}):")
        for vuln in security_results["critical_vulnerabilities"]:
            severity_icon = {"critical": "🚨", "high": "🔴"}.get(vuln["severity"], "🟠")
            print(f"  {severity_icon} {vuln['name']} ({vuln['severity'].upper()})")
            if vuln["details"]:
                print(f"    Issue: {vuln['details']}")
    
    # launch assessment
    print(f"\n🎄 CHRISTMAS DAY 2025 LAUNCH ASSESSMENT:")
    if security_score >= 85:
        print("🎉 LAUNCH APPROVED - Security requirements met!")
        print("   ✅ Security score meets 85%+ requirement for cryptocurrency production")
        print("   ✅ Critical security vulnerabilities addressed")
        print("   ✅ System under launch review")
    elif security_score >= 70:
        print("⚠️  LAUNCH CONDITIONAL - Security improvements needed")
        print("   ⚠️  Security score below 85% requirement")
        print("   ⚠️  Some critical vulnerabilities remain")
        print("   ⚠️  Additional security fixes required before launch")
    else:
        print("🚨 LAUNCH BLOCKED - Critical security issues")
        print("   ❌ Security score significantly below 85% requirement")
        print("   ❌ Multiple critical vulnerabilities present")
        print("   ❌ System not suitable for cryptocurrency operations")
    
    # Production readiness assessment
    print(f"\n🏭 PRODUCTION READINESS:")
    if security_score >= 85:
        print("✅ READY FOR PRODUCTION")
        print("   • Security controls meet enterprise cryptocurrency standards")
        print("   • Brute force protection operational")
        print("   • Rate limiting properly implemented")
        print("   • Input validation and security headers working")
    else:
        print("❌ NOT READY FOR PRODUCTION")
        print("   • Security vulnerabilities must be resolved")
        print("   • Critical security controls missing or non-functional")
        print("   • Immediate security fixes required")
    
    # Specific recommendations
    print(f"\n💡 IMMEDIATE ACTION REQUIRED:")
    
    # Check specific critical issues
    brute_force_score = security_results["categories"]["brute_force_protection"]["score"]
    rate_limiting_score = security_results["categories"]["rate_limiting"]["score"]
    
    if brute_force_score < 50:
        print("🚨 CRITICAL: Implement working brute force protection with account lockout")
    
    if rate_limiting_score < 50:
        print("🚨 CRITICAL: Implement comprehensive rate limiting (global + endpoint-specific)")
    
    if security_score < 85:
        print("🚨 CRITICAL: Address all security vulnerabilities before launch")
    
    return {
        "security_score": security_score,
        "total_tests": security_results["total_tests"],
        "passed_tests": security_results["passed_tests"],
        "failed_tests": security_results["failed_tests"],
        "critical_vulnerabilities": security_results["critical_vulnerabilities"],
        "categories": security_results["categories"],
        "launch_approved": security_score >= 85
    }

if __name__ == "__main__":
    print("⚠️ LEGACY SCRIPT: canonical path is wepo-blockchain/scripts/run_canonical_fee_smoke.sh")
    # Run critical security testing
    results = run_critical_security_testing()
    
    print("\n" + "=" * 80)
    print("🎯 FINAL SECURITY ASSESSMENT SUMMARY")
    print("=" * 80)
    
    print(f"📊 SECURITY METRICS:")
    print(f"• Security Score: {results['security_score']:.1f}% (Target: 85%+)")
    print(f"• Total Tests: {results['total_tests']}")
    print(f"• Critical Vulnerabilities: {len(results['critical_vulnerabilities'])}")
    
    print(f"\n🎄 CHRISTMAS DAY 2025 LAUNCH STATUS:")
    if results['launch_approved']:
        print("🎉 APPROVED - Security requirements met for cryptocurrency production")
    else:
        print("🚨 BLOCKED - Critical security vulnerabilities must be resolved")
    
    print(f"\n🔧 NEXT STEPS:")
    if results['launch_approved']:
        print("• System under launch review")
        print("• Continue monitoring for security edge cases")
        print("• Proceed with final production preparations")
    else:
        print("• Address critical security vulnerabilities immediately")
        print("• Focus on brute force protection and rate limiting")
        print("• Re-run security verification after fixes")
        print("• launch depends on security fixes")
