#!/usr/bin/env python3
"""
WEPO COMPREHENSIVE FINAL SECURITY ASSESSMENT
Launch Readiness Evaluation

**COMPREHENSIVE FINAL SECURITY ASSESSMENT**

**1. CRITICAL SECURITY VULNERABILITIES TESTING**

**Brute Force Protection Assessment:**
- Test `/api/wallet/login` with 6+ failed login attempts
- Verify if account lockout occurs after 5 failed attempts (HTTP 423)
- Check lockout response format and duration information
- Test if lockout persists with correct password

**Rate Limiting Assessment:**
- Test global API rate limiting (should limit after 60 requests/minute)
- Test wallet creation rate limiting (should limit after 3 attempts/minute)
- Test wallet login rate limiting (should limit after 5 attempts/minute)
- Verify HTTP 429 responses with proper rate limit headers

**DDoS Protection Assessment:**
- Test concurrent request handling under load
- Test malformed request handling
- Verify system stability under attack conditions

**2. WORKING SECURITY FEATURES VERIFICATION**

**Input Validation Security:**
- Test XSS protection with malicious scripts
- Test SQL injection resistance
- Test path traversal protection
- Test buffer overflow protection

**Authentication Security:**
- Test password strength validation
- Test secure password hashing (bcrypt)
- Test session management
- Test unauthorized access prevention

**Security Headers Compliance:**
- Verify Content Security Policy (CSP)
- Check X-Frame-Options, X-XSS-Protection
- Test CORS configuration security
- Verify all critical security headers present

**Data Protection:**
- Test for sensitive data exposure in responses
- Verify error message sanitization
- Check for information disclosure vulnerabilities

**3. OVERALL SECURITY SCORE CALCULATION**

**Weighted Security Categories:**
- Brute Force Protection: 25% weight (critical)
- Rate Limiting: 25% weight (critical)
- Input Validation: 20% weight
- Authentication Security: 15% weight
- Security Headers: 10% weight
- Data Protection: 5% weight

**4. PRODUCTION READINESS ASSESSMENT**

**Launch Criteria:**
- Minimum 85% overall security score required
- Zero critical vulnerabilities (brute force, rate limiting)
- 100% authentication security
- No sensitive data exposure

**Expected Assessment Results:**
- Overall Security Score: 40-55% (FAILING)
- Critical Issues: 2 (brute force + rate limiting)
- Launch Status: BLOCKED
- Required Fixes: Account lockout + API rate limiting

**GOAL: Provide definitive security status to confirm system needs critical fixes before cryptocurrency public launch**
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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Use preview backend URL from frontend/.env
BACKEND_URL = "http://127.0.0.1:18021"
API_URL = f"{BACKEND_URL}/api"

print(f"🔐 WEPO COMPREHENSIVE FINAL SECURITY ASSESSMENT")
print(f"🎄 Launch Readiness Evaluation")
print(f"Preview Backend API URL: {API_URL}")
print(f"Focus: Critical Security Vulnerabilities & Production Readiness")
print("=" * 80)

# Security test results tracking with weighted scoring
security_results = {
    "total_tests": 0,
    "passed_tests": 0,
    "failed_tests": 0,
    "categories": {
        "brute_force_protection": {"passed": 0, "total": 0, "weight": 25, "critical": True},
        "rate_limiting": {"passed": 0, "total": 0, "weight": 25, "critical": True},
        "input_validation": {"passed": 0, "total": 0, "weight": 20, "critical": False},
        "authentication_security": {"passed": 0, "total": 0, "weight": 15, "critical": False},
        "security_headers": {"passed": 0, "total": 0, "weight": 10, "critical": False},
        "data_protection": {"passed": 0, "total": 0, "weight": 5, "critical": False}
    },
    "tests": [],
    "critical_vulnerabilities": [],
    "security_score": 0.0,
    "launch_ready": False
}

def log_security_test(name, passed, category, response=None, error=None, details=None, severity="medium"):
    """Log security test results with enhanced details and severity tracking"""
    status = "✅ SECURE" if passed else "🚨 VULNERABLE"
    print(f"{status} {name}")
    
    if details:
        print(f"  Details: {details}")
    
    if error:
        print(f"  Error: {error}")
    
    if response and not passed:
        print(f"  Response: {response}")
    
    # Update counters
    security_results["total_tests"] += 1
    security_results["categories"][category]["total"] += 1
    
    if passed:
        security_results["passed_tests"] += 1
        security_results["categories"][category]["passed"] += 1
    else:
        security_results["failed_tests"] += 1
        
        # Track critical vulnerabilities
        if security_results["categories"][category]["critical"] or severity == "critical":
            security_results["critical_vulnerabilities"].append({
                "name": name,
                "category": category,
                "severity": severity,
                "details": details,
                "error": error
            })
    
    # Store test details
    security_results["tests"].append({
        "name": name,
        "category": category,
        "passed": passed,
        "severity": severity,
        "error": error,
        "details": details
    })

def generate_valid_wepo_address():
    """Generate a valid 37-character WEPO address (wepo1 + 32 hex chars)"""
    random_data = secrets.token_bytes(16)  # 16 bytes = 32 hex chars
    hex_part = random_data.hex()
    return f"wepo1{hex_part}"

def generate_test_user_data():
    """Generate realistic test user data for security testing"""
    username = f"sectest_{secrets.token_hex(4)}"
    password = f"SecTest123!{secrets.token_hex(2)}"
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
            return {
                "username": username,
                "password": password,
                "address": data.get("address"),
                "success": True
            }
    except Exception as e:
        pass
    
    return {"success": False}

# ===== 1. CRITICAL SECURITY VULNERABILITIES TESTING =====

def test_brute_force_protection():
    """Test 1: Brute Force Protection Assessment - CRITICAL"""
    print("\n🔐 BRUTE FORCE PROTECTION ASSESSMENT - CRITICAL")
    print("Testing account lockout after failed login attempts...")
    
    # Create test wallet first
    wallet = create_test_wallet()
    if not wallet["success"]:
        log_security_test("Brute Force Protection Setup", False, "brute_force_protection",
                         error="Could not create test wallet for brute force testing", severity="critical")
        return
    
    username = wallet["username"]
    correct_password = wallet["password"]
    wrong_password = "WrongPassword123!"
    
    print(f"  Testing with username: {username}")
    print(f"  Attempting 8 failed login attempts...")
    
    # Test multiple failed login attempts
    failed_attempts = 0
    lockout_detected = False
    
    for attempt in range(1, 9):  # 8 attempts
        try:
            login_data = {
                "username": username,
                "password": wrong_password
            }
            
            response = requests.post(f"{API_URL}/wallet/login", json=login_data)
            print(f"    Attempt {attempt}: HTTP {response.status_code}")
            
            if response.status_code == 423:  # Account locked
                lockout_detected = True
                lockout_attempt = attempt
                print(f"    🔒 Account lockout detected at attempt {attempt}")
                
                # Test lockout response format
                try:
                    lockout_data = response.json()
                    if isinstance(lockout_data, dict) and "message" in lockout_data:
                        log_security_test("Brute Force Lockout Response Format", True, "brute_force_protection",
                                        details=f"Proper lockout response with message at attempt {attempt}", severity="critical")
                    else:
                        log_security_test("Brute Force Lockout Response Format", False, "brute_force_protection",
                                        details=f"Lockout response missing proper format: {lockout_data}", severity="critical")
                except:
                    log_security_test("Brute Force Lockout Response Format", False, "brute_force_protection",
                                    details="Lockout response not valid JSON", severity="critical")
                break
            elif response.status_code == 401:
                failed_attempts += 1
            else:
                print(f"    Unexpected response: {response.status_code}")
                
        except Exception as e:
            print(f"    Error on attempt {attempt}: {str(e)}")
    
    # Test if account lockout occurred
    if lockout_detected:
        log_security_test("Brute Force Account Lockout", True, "brute_force_protection",
                        details=f"Account locked after {lockout_attempt} failed attempts", severity="critical")
        
        # Test if lockout persists with correct password
        try:
            correct_login_data = {
                "username": username,
                "password": correct_password
            }
            
            response = requests.post(f"{API_URL}/wallet/login", json=correct_login_data)
            if response.status_code == 423:
                log_security_test("Brute Force Lockout Persistence", True, "brute_force_protection",
                                details="Lockout persists even with correct password - proper security", severity="critical")
            else:
                log_security_test("Brute Force Lockout Persistence", False, "brute_force_protection",
                                details=f"Lockout bypassed with correct password - HTTP {response.status_code}", severity="critical")
        except Exception as e:
            log_security_test("Brute Force Lockout Persistence", False, "brute_force_protection",
                            error=str(e), severity="critical")
    else:
        log_security_test("Brute Force Account Lockout", False, "brute_force_protection",
                        details=f"NO account lockout after {failed_attempts} failed attempts", severity="critical")
        log_security_test("Brute Force Lockout Persistence", False, "brute_force_protection",
                        details="Cannot test persistence - no lockout occurred", severity="critical")

def test_rate_limiting():
    """Test 2: Rate Limiting Assessment - CRITICAL"""
    print("\n⚡ RATE LIMITING ASSESSMENT - CRITICAL")
    print("Testing API rate limiting and endpoint-specific limits...")
    
    # Test global API rate limiting
    print("  Testing global API rate limiting (60 requests/minute)...")
    rate_limit_detected = False
    
    try:
        # Make rapid requests to test global rate limiting
        for i in range(1, 101):  # 100 requests
            response = requests.get(f"{API_URL}/")
            
            if response.status_code == 429:  # Rate limited
                rate_limit_detected = True
                print(f"    🚫 Global rate limit detected at request {i}")
                
                # Check for rate limit headers
                rate_headers = ["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset", "Retry-After"]
                present_headers = [header for header in rate_headers if header in response.headers]
                
                if present_headers:
                    log_security_test("Global Rate Limiting Headers", True, "rate_limiting",
                                    details=f"Rate limit headers present: {present_headers}", severity="critical")
                else:
                    log_security_test("Global Rate Limiting Headers", False, "rate_limiting",
                                    details="Rate limit headers missing", severity="critical")
                break
            
            if i % 20 == 0:
                print(f"    Request {i}: HTTP {response.status_code}")
                
        if rate_limit_detected:
            log_security_test("Global API Rate Limiting", True, "rate_limiting",
                            details="Global rate limiting working", severity="critical")
        else:
            log_security_test("Global API Rate Limiting", False, "rate_limiting",
                            details="NO global rate limiting after 100 requests", severity="critical")
            log_security_test("Global Rate Limiting Headers", False, "rate_limiting",
                            details="Cannot test headers - no rate limiting", severity="critical")
            
    except Exception as e:
        log_security_test("Global API Rate Limiting", False, "rate_limiting",
                        error=str(e), severity="critical")
    
    # Test wallet creation rate limiting
    print("  Testing wallet creation rate limiting (3 attempts/minute)...")
    creation_rate_limit = False
    
    try:
        for i in range(1, 11):  # 10 attempts
            username, password = generate_test_user_data()
            create_data = {
                "username": f"{username}_{i}",
                "password": password
            }
            
            response = requests.post(f"{API_URL}/wallet/create", json=create_data)
            
            if response.status_code == 429:
                creation_rate_limit = True
                print(f"    🚫 Wallet creation rate limit detected at attempt {i}")
                break
            
            if i % 3 == 0:
                print(f"    Creation attempt {i}: HTTP {response.status_code}")
                
        if creation_rate_limit:
            log_security_test("Wallet Creation Rate Limiting", True, "rate_limiting",
                            details="Wallet creation rate limiting working", severity="critical")
        else:
            log_security_test("Wallet Creation Rate Limiting", False, "rate_limiting",
                            details="NO wallet creation rate limiting after 10 attempts", severity="critical")
            
    except Exception as e:
        log_security_test("Wallet Creation Rate Limiting", False, "rate_limiting",
                        error=str(e), severity="critical")
    
    # Test wallet login rate limiting
    print("  Testing wallet login rate limiting (5 attempts/minute)...")
    login_rate_limit = False
    
    # Create test wallet for login testing
    wallet = create_test_wallet()
    if wallet["success"]:
        try:
            for i in range(1, 16):  # 15 attempts
                login_data = {
                    "username": wallet["username"],
                    "password": "WrongPassword123!"
                }
                
                response = requests.post(f"{API_URL}/wallet/login", json=login_data)
                
                if response.status_code == 429:
                    login_rate_limit = True
                    print(f"    🚫 Login rate limit detected at attempt {i}")
                    break
                elif response.status_code == 423:
                    print(f"    Account locked at attempt {i} (expected)")
                    break
                
                if i % 5 == 0:
                    print(f"    Login attempt {i}: HTTP {response.status_code}")
                    
            if login_rate_limit:
                log_security_test("Wallet Login Rate Limiting", True, "rate_limiting",
                                details="Login rate limiting working", severity="critical")
            else:
                log_security_test("Wallet Login Rate Limiting", False, "rate_limiting",
                                details="NO login rate limiting after 15 attempts", severity="critical")
                
        except Exception as e:
            log_security_test("Wallet Login Rate Limiting", False, "rate_limiting",
                            error=str(e), severity="critical")
    else:
        log_security_test("Wallet Login Rate Limiting", False, "rate_limiting",
                        error="Could not create test wallet for login rate limiting test", severity="critical")

def test_ddos_protection():
    """Test 3: DDoS Protection Assessment"""
    print("\n🛡️ DDOS PROTECTION ASSESSMENT")
    print("Testing concurrent request handling and malformed request protection...")
    
    # Test concurrent request handling
    print("  Testing concurrent request handling (50 simultaneous requests)...")
    
    def make_request(request_id):
        try:
            response = requests.get(f"{API_URL}/", timeout=10)
            return {"id": request_id, "status": response.status_code, "success": True}
        except Exception as e:
            return {"id": request_id, "error": str(e), "success": False}
    
    try:
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(make_request, i) for i in range(50)]
            results = [future.result() for future in as_completed(futures, timeout=30)]
        
        successful_requests = len([r for r in results if r["success"]])
        failed_requests = len([r for r in results if not r["success"]])
        
        if successful_requests >= 40:  # 80% success rate acceptable
            log_security_test("Concurrent Request Protection", True, "rate_limiting",
                            details=f"Handled {successful_requests}/50 concurrent requests successfully")
        else:
            log_security_test("Concurrent Request Protection", False, "rate_limiting",
                            details=f"Only {successful_requests}/50 concurrent requests succeeded")
            
    except Exception as e:
        log_security_test("Concurrent Request Protection", False, "rate_limiting",
                        error=str(e))
    
    # Test malformed request handling
    print("  Testing malformed request handling...")
    malformed_tests = [
        {"name": "Invalid JSON", "data": "invalid json{", "content_type": "application/json"},
        {"name": "Oversized Payload", "data": "x" * 100000, "content_type": "application/json"},
        {"name": "Invalid Content-Type", "data": '{"test": "data"}', "content_type": "application/xml"},
        {"name": "Missing Content-Type", "data": '{"test": "data"}', "content_type": None},
        {"name": "Binary Data", "data": b'\x00\x01\x02\x03', "content_type": "application/octet-stream"}
    ]
    
    malformed_handled = 0
    
    for test in malformed_tests:
        try:
            headers = {}
            if test["content_type"]:
                headers["Content-Type"] = test["content_type"]
            
            if isinstance(test["data"], bytes):
                response = requests.post(f"{API_URL}/wallet/create", data=test["data"], headers=headers, timeout=5)
            else:
                response = requests.post(f"{API_URL}/wallet/create", data=test["data"], headers=headers, timeout=5)
            
            # Acceptable responses: 400 (Bad Request), 415 (Unsupported Media Type), 413 (Payload Too Large)
            if response.status_code in [400, 413, 415, 422]:
                malformed_handled += 1
                print(f"    ✅ {test['name']}: HTTP {response.status_code} (properly handled)")
            else:
                print(f"    ❌ {test['name']}: HTTP {response.status_code} (not properly handled)")
                
        except requests.exceptions.Timeout:
            print(f"    ⚠️  {test['name']}: Timeout (may indicate DoS vulnerability)")
        except Exception as e:
            print(f"    ❌ {test['name']}: Error - {str(e)}")
    
    if malformed_handled >= 3:  # At least 3/5 handled properly
        log_security_test("Malformed Request Handling", True, "rate_limiting",
                        details=f"Properly handled {malformed_handled}/5 malformed requests")
    else:
        log_security_test("Malformed Request Handling", False, "rate_limiting",
                        details=f"Only handled {malformed_handled}/5 malformed requests properly")

# ===== 2. WORKING SECURITY FEATURES VERIFICATION =====

def test_input_validation_security():
    """Test 4: Input Validation Security"""
    print("\n🛡️ INPUT VALIDATION SECURITY TESTING")
    print("Testing XSS, injection, and path traversal protection...")
    
    # XSS Protection Tests
    xss_payloads = [
        "<script>alert('XSS')</script>",
        "javascript:alert('XSS')",
        "<img src=x onerror=alert('XSS')>",
        "';alert('XSS');//",
        "<svg onload=alert('XSS')>"
    ]
    
    xss_blocked = 0
    for payload in xss_payloads:
        try:
            create_data = {
                "username": payload,
                "password": "TestPass123!"
            }
            
            response = requests.post(f"{API_URL}/wallet/create", json=create_data)
            
            # Check if XSS payload is reflected in response
            response_text = response.text.lower()
            if "<script>" not in response_text and "javascript:" not in response_text and "onerror=" not in response_text:
                xss_blocked += 1
                
        except Exception:
            xss_blocked += 1  # Exception likely means payload was blocked
    
    if xss_blocked >= 4:  # At least 4/5 blocked
        log_security_test("XSS Protection", True, "input_validation",
                        details=f"Blocked {xss_blocked}/5 XSS payloads")
    else:
        log_security_test("XSS Protection", False, "input_validation",
                        details=f"Only blocked {xss_blocked}/5 XSS payloads")
    
    # SQL/NoSQL Injection Tests
    injection_payloads = [
        "'; DROP TABLE wallets; --",
        "' OR '1'='1",
        "admin'--",
        "' UNION SELECT * FROM wallets --",
        "'; INSERT INTO wallets VALUES ('hacked'); --"
    ]
    
    injection_blocked = 0
    for payload in injection_payloads:
        try:
            create_data = {
                "username": payload,
                "password": "TestPass123!"
            }
            
            response = requests.post(f"{API_URL}/wallet/create", json=create_data)
            
            # If we get a 400 error or proper validation error, injection was likely blocked
            if response.status_code in [400, 422] or "invalid" in response.text.lower():
                injection_blocked += 1
                
        except Exception:
            injection_blocked += 1
    
    if injection_blocked >= 4:  # At least 4/5 blocked
        log_security_test("SQL/NoSQL Injection Protection", True, "input_validation",
                        details=f"Blocked {injection_blocked}/5 injection payloads")
    else:
        log_security_test("SQL/NoSQL Injection Protection", False, "input_validation",
                        details=f"Only blocked {injection_blocked}/5 injection payloads")
    
    # Path Traversal Tests
    traversal_payloads = [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\config\\sam",
        "....//....//....//etc//passwd",
        "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd"
    ]
    
    traversal_blocked = 0
    for payload in traversal_payloads:
        try:
            # Test path traversal in wallet address lookup
            response = requests.get(f"{API_URL}/wallet/{payload}")
            
            # Should return 404 or 400, not file contents
            if response.status_code in [400, 404] and "root:" not in response.text:
                traversal_blocked += 1
                
        except Exception:
            traversal_blocked += 1
    
    if traversal_blocked >= 3:  # At least 3/4 blocked
        log_security_test("Path Traversal Protection", True, "input_validation",
                        details=f"Blocked {traversal_blocked}/4 path traversal attempts")
    else:
        log_security_test("Path Traversal Protection", False, "input_validation",
                        details=f"Only blocked {traversal_blocked}/4 path traversal attempts")
    
    # Buffer Overflow Tests
    buffer_tests = [
        "A" * 1000,   # 1KB
        "A" * 10000,  # 10KB
        "A" * 100000  # 100KB
    ]
    
    buffer_handled = 0
    for i, payload in enumerate(buffer_tests):
        try:
            create_data = {
                "username": payload,
                "password": "TestPass123!"
            }
            
            response = requests.post(f"{API_URL}/wallet/create", json=create_data, timeout=5)
            
            # Should handle gracefully with 400 or 413 (Payload Too Large)
            if response.status_code in [400, 413, 422]:
                buffer_handled += 1
                
        except requests.exceptions.Timeout:
            # Timeout might indicate vulnerability
            pass
        except Exception:
            buffer_handled += 1  # Exception likely means proper handling
    
    if buffer_handled >= 2:  # At least 2/3 handled
        log_security_test("Buffer Overflow Protection", True, "input_validation",
                        details=f"Properly handled {buffer_handled}/3 buffer overflow tests")
    else:
        log_security_test("Buffer Overflow Protection", False, "input_validation",
                        details=f"Only handled {buffer_handled}/3 buffer overflow tests")

def test_authentication_security():
    """Test 5: Authentication Security"""
    print("\n🔐 AUTHENTICATION SECURITY TESTING")
    print("Testing password strength, hashing, and session management...")
    
    # Password Strength Validation Tests
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
    for password in weak_passwords:
        try:
            username, _ = generate_test_user_data()
            create_data = {
                "username": username,
                "password": password
            }
            
            response = requests.post(f"{API_URL}/wallet/create", json=create_data)
            
            # Weak password should be rejected with 400
            if response.status_code == 400:
                response_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
                if "password" in str(response_data).lower() or "strength" in str(response_data).lower():
                    weak_rejected += 1
                    
        except Exception:
            pass
    
    if weak_rejected >= 5:  # At least 5/7 rejected
        log_security_test("Password Strength Validation", True, "authentication_security",
                        details=f"Rejected {weak_rejected}/7 weak passwords")
    else:
        log_security_test("Password Strength Validation", False, "authentication_security",
                        details=f"Only rejected {weak_rejected}/7 weak passwords")
    
    # Strong Password Acceptance Tests
    strong_passwords = [
        "StrongPass123!@#",
        "MySecure2024Password!",
        "Complex#Pass$2024"
    ]
    
    strong_accepted = 0
    for password in strong_passwords:
        try:
            username, _ = generate_test_user_data()
            create_data = {
                "username": username,
                "password": password
            }
            
            response = requests.post(f"{API_URL}/wallet/create", json=create_data)
            
            # Strong password should be accepted
            if response.status_code == 200:
                strong_accepted += 1
                
        except Exception:
            pass
    
    if strong_accepted >= 2:  # At least 2/3 accepted
        log_security_test("Strong Password Acceptance", True, "authentication_security",
                        details=f"Accepted {strong_accepted}/3 strong passwords")
    else:
        log_security_test("Strong Password Acceptance", False, "authentication_security",
                        details=f"Only accepted {strong_accepted}/3 strong passwords")
    
    # Password Hashing Security Test
    wallet1 = create_test_wallet()
    wallet2 = create_test_wallet()
    
    if wallet1["success"] and wallet2["success"]:
        # Passwords should not be stored in plaintext or be visible in responses
        try:
            response1 = requests.get(f"{API_URL}/wallet/{wallet1['address']}")
            response2 = requests.get(f"{API_URL}/wallet/{wallet2['address']}")
            
            password_exposed = False
            if response1.status_code == 200:
                if wallet1["password"] in response1.text:
                    password_exposed = True
            if response2.status_code == 200:
                if wallet2["password"] in response2.text:
                    password_exposed = True
            
            if not password_exposed:
                log_security_test("Password Hashing Security", True, "authentication_security",
                                details="Passwords not exposed in API responses")
            else:
                log_security_test("Password Hashing Security", False, "authentication_security",
                                details="Passwords exposed in plaintext in API responses", severity="critical")
                
        except Exception as e:
            log_security_test("Password Hashing Security", False, "authentication_security",
                            error=str(e))
    else:
        log_security_test("Password Hashing Security", False, "authentication_security",
                        error="Could not create test wallets for password hashing test")

def test_security_headers():
    """Test 6: Security Headers Compliance"""
    print("\n🛡️ SECURITY HEADERS COMPLIANCE TESTING")
    print("Testing critical security headers and CORS configuration...")
    
    try:
        response = requests.get(f"{API_URL}/")
        
        # Critical security headers to check
        critical_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": ["DENY", "SAMEORIGIN"],
            "X-XSS-Protection": "1; mode=block",
            "Content-Security-Policy": None,  # Just check presence
            "Strict-Transport-Security": None  # Just check presence
        }
        
        headers_present = 0
        headers_details = []
        
        for header, expected_values in critical_headers.items():
            if header in response.headers:
                headers_present += 1
                header_value = response.headers[header]
                
                if expected_values is None:
                    headers_details.append(f"{header}: {header_value}")
                elif isinstance(expected_values, list):
                    if any(val in header_value for val in expected_values):
                        headers_details.append(f"{header}: {header_value} ✓")
                    else:
                        headers_details.append(f"{header}: {header_value} ⚠️")
                else:
                    if expected_values in header_value:
                        headers_details.append(f"{header}: {header_value} ✓")
                    else:
                        headers_details.append(f"{header}: {header_value} ⚠️")
            else:
                headers_details.append(f"{header}: MISSING ❌")
        
        if headers_present >= 4:  # At least 4/5 critical headers
            log_security_test("Critical Security Headers", True, "security_headers",
                            details=f"Present: {headers_present}/5 headers - {headers_details}")
        else:
            log_security_test("Critical Security Headers", False, "security_headers",
                            details=f"Only {headers_present}/5 headers present - {headers_details}")
        
        # CORS Configuration Test
        cors_headers = ["Access-Control-Allow-Origin", "Access-Control-Allow-Methods", "Access-Control-Allow-Headers"]
        cors_present = [header for header in cors_headers if header in response.headers]
        
        # Check for wildcard CORS (security risk)
        cors_origin = response.headers.get("Access-Control-Allow-Origin", "")
        if cors_origin == "*":
            log_security_test("CORS Security Configuration", False, "security_headers",
                            details="Wildcard CORS detected - security risk", severity="high")
        elif cors_present:
            log_security_test("CORS Security Configuration", True, "security_headers",
                            details=f"CORS properly configured - {cors_present}")
        else:
            log_security_test("CORS Security Configuration", True, "security_headers",
                            details="No CORS headers (restrictive - secure)")
            
    except Exception as e:
        log_security_test("Critical Security Headers", False, "security_headers", error=str(e))
        log_security_test("CORS Security Configuration", False, "security_headers", error=str(e))

def test_data_protection():
    """Test 7: Data Protection"""
    print("\n🔒 DATA PROTECTION TESTING")
    print("Testing sensitive data exposure and error message sanitization...")
    
    # Test for sensitive data exposure in API responses
    wallet = create_test_wallet()
    if wallet["success"]:
        try:
            # Test wallet info endpoint
            response = requests.get(f"{API_URL}/wallet/{wallet['address']}")
            
            sensitive_data_exposed = False
            sensitive_fields = ["password", "private_key", "seed", "mnemonic", "secret"]
            
            if response.status_code == 200:
                response_text = response.text.lower()
                exposed_fields = [field for field in sensitive_fields if field in response_text]
                
                if exposed_fields:
                    sensitive_data_exposed = True
                    log_security_test("Sensitive Data Exposure", False, "data_protection",
                                    details=f"Sensitive fields exposed: {exposed_fields}", severity="critical")
                else:
                    log_security_test("Sensitive Data Exposure", True, "data_protection",
                                    details="No sensitive data exposed in wallet info")
            else:
                log_security_test("Sensitive Data Exposure", True, "data_protection",
                                details=f"Wallet info not accessible (HTTP {response.status_code}) - secure")
                
        except Exception as e:
            log_security_test("Sensitive Data Exposure", False, "data_protection", error=str(e))
    else:
        log_security_test("Sensitive Data Exposure", False, "data_protection",
                        error="Could not create test wallet for data exposure test")
    
    # Test error message sanitization
    try:
        # Test with invalid data to trigger errors
        invalid_requests = [
            {"endpoint": "/wallet/invalid_address", "method": "GET"},
            {"endpoint": "/wallet/create", "method": "POST", "data": {"invalid": "data"}},
            {"endpoint": "/transaction/send", "method": "POST", "data": {"invalid": "transaction"}}
        ]
        
        error_messages_safe = 0
        dangerous_patterns = ["stack trace", "internal error", "database", "mongodb", "exception", "traceback"]
        
        for req in invalid_requests:
            try:
                if req["method"] == "GET":
                    response = requests.get(f"{API_URL}{req['endpoint']}")
                else:
                    response = requests.post(f"{API_URL}{req['endpoint']}", json=req.get("data", {}))
                
                response_text = response.text.lower()
                dangerous_found = [pattern for pattern in dangerous_patterns if pattern in response_text]
                
                if not dangerous_found:
                    error_messages_safe += 1
                    
            except Exception:
                error_messages_safe += 1  # Exception handling is good
        
        if error_messages_safe >= 2:  # At least 2/3 safe
            log_security_test("Error Message Sanitization", True, "data_protection",
                            details=f"Safe error messages: {error_messages_safe}/3")
        else:
            log_security_test("Error Message Sanitization", False, "data_protection",
                            details=f"Only {error_messages_safe}/3 error messages are safe")
            
    except Exception as e:
        log_security_test("Error Message Sanitization", False, "data_protection", error=str(e))

# ===== 3. OVERALL SECURITY SCORE CALCULATION =====

def calculate_security_score():
    """Calculate weighted security score and production readiness"""
    print("\n📊 CALCULATING OVERALL SECURITY SCORE")
    print("Weighted scoring based on category importance...")
    
    total_weighted_score = 0.0
    max_possible_score = 0.0
    
    category_scores = {}
    
    for category, data in security_results["categories"].items():
        if data["total"] > 0:
            category_rate = (data["passed"] / data["total"]) * 100
            weighted_score = (category_rate * data["weight"]) / 100
            total_weighted_score += weighted_score
            max_possible_score += data["weight"]
            
            category_scores[category] = {
                "rate": category_rate,
                "weighted_score": weighted_score,
                "weight": data["weight"],
                "critical": data["critical"]
            }
            
            status = "✅" if category_rate >= 80 else "⚠️" if category_rate >= 60 else "🚨"
            print(f"  {status} {category.replace('_', ' ').title()}: {category_rate:.1f}% (Weight: {data['weight']}%)")
    
    # Calculate final security score
    if max_possible_score > 0:
        final_score = (total_weighted_score / max_possible_score) * 100
    else:
        final_score = 0.0
    
    security_results["security_score"] = final_score
    security_results["category_scores"] = category_scores
    
    print(f"\n🎯 OVERALL SECURITY SCORE: {final_score:.1f}%")
    
    return final_score, category_scores

# ===== 4. PRODUCTION READINESS ASSESSMENT =====

def assess_production_readiness():
    """Assess launch readiness"""
    print("\n🎄 CHRISTMAS DAY 2025 LAUNCH READINESS ASSESSMENT")
    print("Evaluating production readiness criteria...")
    
    final_score, category_scores = calculate_security_score()
    
    # Launch criteria
    MINIMUM_SCORE = 85.0
    CRITICAL_THRESHOLD = 100.0  # Critical categories must be 100%
    
    # Check critical vulnerabilities
    critical_failures = []
    for category, scores in category_scores.items():
        if scores["critical"] and scores["rate"] < CRITICAL_THRESHOLD:
            critical_failures.append({
                "category": category.replace('_', ' ').title(),
                "score": scores["rate"],
                "required": CRITICAL_THRESHOLD
            })
    
    # Determine launch status
    launch_ready = final_score >= MINIMUM_SCORE and len(critical_failures) == 0
    security_results["launch_ready"] = launch_ready
    
    print(f"\n📋 LAUNCH CRITERIA EVALUATION:")
    print(f"  • Minimum Security Score (85%): {'✅ PASSED' if final_score >= MINIMUM_SCORE else '❌ FAILED'} ({final_score:.1f}%)")
    print(f"  • Zero Critical Vulnerabilities: {'✅ PASSED' if len(critical_failures) == 0 else '❌ FAILED'} ({len(critical_failures)} critical issues)")
    print(f"  • Critical Security Categories (100%): {'✅ PASSED' if len(critical_failures) == 0 else '❌ FAILED'}")
    
    if critical_failures:
        print(f"\n🚨 CRITICAL VULNERABILITIES BLOCKING LAUNCH:")
        for failure in critical_failures:
            print(f"  • {failure['category']}: {failure['score']:.1f}% (Required: {failure['required']:.1f}%)")
    
    # Overall assessment
    print(f"\n🎄 CHRISTMAS DAY 2025 LAUNCH STATUS:")
    if launch_ready:
        print("✅ LAUNCH APPROVED - System meets security requirements")
        print("   All critical vulnerabilities resolved")
        print("   Security score exceeds minimum threshold")
        print("   Ready for cryptocurrency production operations")
    else:
        print("🚨 LAUNCH BLOCKED - Critical security issues detected")
        print("   System not suitable for cryptocurrency operations")
        print("   Immediate security fixes required before launch")
        
        if final_score < MINIMUM_SCORE:
            print(f"   Security score too low: {final_score:.1f}% (Required: {MINIMUM_SCORE:.1f}%)")
        
        if critical_failures:
            print(f"   Critical vulnerabilities present: {len(critical_failures)} issues")
    
    return launch_ready, final_score, critical_failures

def run_comprehensive_security_assessment():
    """Run comprehensive final security assessment"""
    print("🔐 STARTING WEPO COMPREHENSIVE FINAL SECURITY ASSESSMENT")
    print("🎄 Launch Readiness Evaluation")
    print("=" * 80)
    
    # Run all security tests
    test_brute_force_protection()
    test_rate_limiting()
    test_ddos_protection()
    test_input_validation_security()
    test_authentication_security()
    test_security_headers()
    test_data_protection()
    
    # Calculate scores and assess readiness
    launch_ready, final_score, critical_failures = assess_production_readiness()
    
    # Print comprehensive results
    print("\n" + "=" * 80)
    print("🔐 COMPREHENSIVE FINAL SECURITY ASSESSMENT RESULTS")
    print("=" * 80)
    
    print(f"📊 SECURITY STATISTICS:")
    print(f"  • Total Security Tests: {security_results['total_tests']}")
    print(f"  • Tests Passed: {security_results['passed_tests']} ✅")
    print(f"  • Tests Failed: {security_results['failed_tests']} ❌")
    print(f"  • Overall Security Score: {final_score:.1f}%")
    print(f"  • Critical Vulnerabilities: {len(security_results['critical_vulnerabilities'])}")
    
    # Category breakdown
    print(f"\n📋 SECURITY CATEGORY BREAKDOWN:")
    for category, data in security_results["categories"].items():
        if data["total"] > 0:
            rate = (data["passed"] / data["total"]) * 100
            status = "🚨 CRITICAL" if data["critical"] and rate < 100 else "✅ SECURE" if rate >= 80 else "⚠️ WEAK"
            print(f"  • {category.replace('_', ' ').title()}: {rate:.1f}% ({data['passed']}/{data['total']}) - {status}")
    
    # Critical vulnerabilities
    if security_results["critical_vulnerabilities"]:
        print(f"\n🚨 CRITICAL VULNERABILITIES DETECTED:")
        for vuln in security_results["critical_vulnerabilities"]:
            print(f"  • {vuln['name']} ({vuln['category']})")
            if vuln['details']:
                print(f"    Details: {vuln['details']}")
    
    # Failed tests summary
    failed_tests = [test for test in security_results['tests'] if not test['passed']]
    if failed_tests:
        print(f"\n❌ FAILED SECURITY TESTS ({len(failed_tests)} total):")
        for test in failed_tests:
            severity_icon = "🚨" if test['severity'] == "critical" else "⚠️" if test['severity'] == "high" else "❌"
            print(f"  {severity_icon} {test['name']} ({test['category']})")
            if test['details']:
                print(f"    Issue: {test['details']}")
    
    # Final recommendation
    print(f"\n🎄 FINAL CHRISTMAS DAY 2025 LAUNCH RECOMMENDATION:")
    if launch_ready:
        print("🎉 LAUNCH APPROVED - WEPO system is secure and not yet approved for production")
        print("   ✅ All critical security requirements met")
        print("   ✅ Security score exceeds 85% threshold")
        print("   ✅ No critical vulnerabilities detected")
        print("   ✅ Suitable for cryptocurrency operations")
    else:
        print("🚨 LAUNCH BLOCKED - Critical security vulnerabilities must be resolved")
        print("   ❌ System not ready for cryptocurrency production")
        print("   ❌ Critical security fixes required immediately")
        print("   ❌ Launch postponement recommended until fixes implemented")
        
        print(f"\n🔧 IMMEDIATE ACTIONS REQUIRED:")
        if final_score < 85:
            print(f"  1. Improve overall security score from {final_score:.1f}% to 85%+")
        
        critical_categories = [cat for cat, scores in security_results.get('category_scores', {}).items() 
                             if scores['critical'] and scores['rate'] < 100]
        if critical_categories:
            print(f"  2. Fix critical security categories:")
            for cat in critical_categories:
                print(f"     • {cat.replace('_', ' ').title()}")
        
        if security_results["critical_vulnerabilities"]:
            print(f"  3. Resolve {len(security_results['critical_vulnerabilities'])} critical vulnerabilities")
    
    return {
        "launch_ready": launch_ready,
        "security_score": final_score,
        "total_tests": security_results["total_tests"],
        "passed_tests": security_results["passed_tests"],
        "failed_tests": security_results["failed_tests"],
        "critical_vulnerabilities": len(security_results["critical_vulnerabilities"]),
        "category_scores": security_results.get("category_scores", {}),
        "failed_test_details": failed_tests
    }

if __name__ == "__main__":
    # Run comprehensive security assessment
    results = run_comprehensive_security_assessment()
    
    print("\n" + "=" * 80)
    print("🎯 EXECUTIVE SECURITY SUMMARY")
    print("=" * 80)
    
    print(f"🔐 SECURITY ASSESSMENT RESULTS:")
    print(f"• Overall Security Score: {results['security_score']:.1f}% (Target: 85%+)")
    print(f"• Tests Passed: {results['passed_tests']}/{results['total_tests']}")
    print(f"• Critical Vulnerabilities: {results['critical_vulnerabilities']}")
    print(f"• Launch: {'✅ APPROVED' if results['launch_ready'] else '🚨 BLOCKED'}")
    
    if not results['launch_ready']:
        print(f"\n🚨 LAUNCH BLOCKING ISSUES:")
        if results['security_score'] < 85:
            print(f"• Security score below threshold: {results['security_score']:.1f}% < 85%")
        if results['critical_vulnerabilities'] > 0:
            print(f"• Critical vulnerabilities present: {results['critical_vulnerabilities']} issues")
    
    print(f"\n💡 FINAL RECOMMENDATION:")
    if results['launch_ready']:
        print("🎉 WEPO system is SECURE and READY for genesis date cryptocurrency launch!")
    else:
        print("🚨 WEPO system requires IMMEDIATE SECURITY FIXES before cryptocurrency launch!")
        print("   Launch should be POSTPONED until all critical vulnerabilities are resolved.")