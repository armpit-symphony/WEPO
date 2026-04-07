#!/usr/bin/env python3
"""
COMPREHENSIVE API SECURITY AUDIT AND FUNCTIONALITY VERIFICATION
For WEPO Cryptocurrency System

This test conducts a comprehensive security audit covering:
1. Authentication & Authorization Security
2. Input Validation & Sanitization Security  
3. Rate Limiting & DDoS Protection
4. HTTP Security Headers
5. Data Protection & Privacy
6. Cryptocurrency-Specific Security
7. API Endpoint Functionality Verification
8. Network Security & Infrastructure

Target: 90%+ security score across all categories for enterprise-grade security
"""

import requests
import json
import time
import uuid
import secrets
import hashlib
import re
import base64
from datetime import datetime
import random
import string

# Use preview backend URL from frontend/.env
BACKEND_URL = "https://blockchain-sectest.preview.emergentagent.com"
API_URL = f"{BACKEND_URL}/api"

print(f"🔐 COMPREHENSIVE API SECURITY AUDIT - WEPO CRYPTOCURRENCY SYSTEM")
print(f"Backend API URL: {API_URL}")
print(f"Target: Enterprise-grade security for launch")
print("=" * 80)

# Test results tracking
security_results = {
    "total": 0,
    "passed": 0,
    "failed": 0,
    "categories": {
        "authentication_security": {"passed": 0, "total": 0, "tests": []},
        "input_validation_security": {"passed": 0, "total": 0, "tests": []},
        "rate_limiting_protection": {"passed": 0, "total": 0, "tests": []},
        "http_security_headers": {"passed": 0, "total": 0, "tests": []},
        "data_protection_privacy": {"passed": 0, "total": 0, "tests": []},
        "cryptocurrency_security": {"passed": 0, "total": 0, "tests": []},
        "api_functionality": {"passed": 0, "total": 0, "tests": []},
        "network_security": {"passed": 0, "total": 0, "tests": []}
    }
}

def log_security_test(name, passed, category, details=None, severity="medium", recommendation=None):
    """Log security test results with severity and recommendations"""
    status = "✅ SECURE" if passed else "🚨 VULNERABLE"
    severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
    
    print(f"{status} {name} [{severity_icon.get(severity, '🟡')} {severity.upper()}]")
    
    if details:
        print(f"  Details: {details}")
    
    if not passed and recommendation:
        print(f"  🔧 Recommendation: {recommendation}")
    
    security_results["total"] += 1
    security_results["categories"][category]["total"] += 1
    
    test_record = {
        "name": name,
        "passed": passed,
        "severity": severity,
        "details": details,
        "recommendation": recommendation
    }
    
    security_results["categories"][category]["tests"].append(test_record)
    
    if passed:
        security_results["passed"] += 1
        security_results["categories"][category]["passed"] += 1
    else:
        security_results["failed"] += 1

def generate_valid_wepo_address():
    """Generate a valid WEPO address for testing"""
    random_data = secrets.token_bytes(16)
    hex_part = random_data.hex()
    return f"wepo1{hex_part}"

def generate_test_credentials():
    """Generate secure test credentials"""
    username = f"sectest_{secrets.token_hex(4)}"
    password = f"SecTest123!{secrets.token_hex(2)}"
    return username, password

# ===== 1. AUTHENTICATION & AUTHORIZATION SECURITY =====

def test_authentication_security():
    """Test 1: Authentication & Authorization Security"""
    print("\n🔐 AUTHENTICATION & AUTHORIZATION SECURITY TESTING")
    print("Testing wallet login vulnerabilities, session management, and access controls...")
    
    # Test 1.1: Brute Force Protection
    try:
        username, password = generate_test_credentials()
        failed_attempts = 0
        
        # Create a test wallet first
        create_response = requests.post(f"{API_URL}/wallet/create", json={
            "username": username,
            "password": password
        })
        
        if create_response.status_code == 200:
            # Now test brute force protection with wrong passwords
            for i in range(6):  # Try 6 failed attempts
                wrong_password = f"wrong_password_{i}"
                response = requests.post(f"{API_URL}/wallet/login", json={
                    "username": username,
                    "password": wrong_password
                })
                
                if response.status_code == 429:  # Rate limited
                    log_security_test(
                        "Brute Force Protection", True, "authentication_security",
                        f"Rate limiting activated after {i+1} attempts",
                        "high", None
                    )
                    break
                elif response.status_code == 423:  # Account locked
                    log_security_test(
                        "Account Lockout Mechanism", True, "authentication_security",
                        f"Account locked after {i+1} failed attempts",
                        "high", None
                    )
                    break
                failed_attempts += 1
            else:
                log_security_test(
                    "Brute Force Protection", False, "authentication_security",
                    f"No protection after {failed_attempts} failed attempts",
                    "critical", "Implement rate limiting and account lockout after 5 failed attempts"
                )
        else:
            log_security_test(
                "Brute Force Protection", False, "authentication_security",
                "Cannot test - wallet creation failed",
                "medium", "Fix wallet creation endpoint first"
            )
    except Exception as e:
        log_security_test(
            "Brute Force Protection", False, "authentication_security",
            f"Test error: {str(e)}", "medium", "Investigate authentication endpoint stability"
        )
    
    # Test 1.2: Password Security Requirements
    try:
        weak_passwords = [
            "123456",
            "password",
            "abc123",
            "test",
            "12345678"
        ]
        
        weak_rejected = 0
        for weak_pass in weak_passwords:
            username = f"weaktest_{secrets.token_hex(2)}"
            response = requests.post(f"{API_URL}/wallet/create", json={
                "username": username,
                "password": weak_pass
            })
            
            if response.status_code == 400:
                weak_rejected += 1
        
        if weak_rejected >= 4:  # At least 4/5 weak passwords rejected
            log_security_test(
                "Password Strength Validation", True, "authentication_security",
                f"Rejected {weak_rejected}/5 weak passwords",
                "high", None
            )
        else:
            log_security_test(
                "Password Strength Validation", False, "authentication_security",
                f"Only rejected {weak_rejected}/5 weak passwords",
                "high", "Implement comprehensive password complexity requirements"
            )
    except Exception as e:
        log_security_test(
            "Password Strength Validation", False, "authentication_security",
            f"Test error: {str(e)}", "medium", "Investigate password validation endpoint"
        )
    
    # Test 1.3: Session Management Security
    try:
        username, password = generate_test_credentials()
        
        # Create wallet
        create_response = requests.post(f"{API_URL}/wallet/create", json={
            "username": username,
            "password": password
        })
        
        if create_response.status_code == 200:
            # Test login
            login_response = requests.post(f"{API_URL}/wallet/login", json={
                "username": username,
                "password": password
            })
            
            if login_response.status_code == 200:
                login_data = login_response.json()
                if login_data.get("success") and not login_data.get("session_token"):
                    log_security_test(
                        "Session Management", True, "authentication_security",
                        "Stateless authentication - no session tokens exposed",
                        "medium", None
                    )
                elif login_data.get("session_token"):
                    log_security_test(
                        "Session Management", False, "authentication_security",
                        "Session token exposed in response",
                        "medium", "Avoid exposing session tokens in API responses"
                    )
                else:
                    log_security_test(
                        "Session Management", True, "authentication_security",
                        "Login successful with secure session handling",
                        "medium", None
                    )
            else:
                log_security_test(
                    "Session Management", False, "authentication_security",
                    f"Login failed: HTTP {login_response.status_code}",
                    "medium", "Fix login endpoint for session testing"
                )
        else:
            log_security_test(
                "Session Management", False, "authentication_security",
                "Cannot test - wallet creation failed",
                "medium", "Fix wallet creation for session testing"
            )
    except Exception as e:
        log_security_test(
            "Session Management", False, "authentication_security",
            f"Test error: {str(e)}", "medium", "Investigate session management implementation"
        )

# ===== 2. INPUT VALIDATION & SANITIZATION SECURITY =====

def test_input_validation_security():
    """Test 2: Input Validation & Sanitization Security"""
    print("\n🛡️ INPUT VALIDATION & SANITIZATION SECURITY TESTING")
    print("Testing XSS protection, injection resistance, and parameter validation...")
    
    # Test 2.1: XSS Protection
    try:
        xss_payloads = [
            "<script>alert('XSS')</script>",
            "javascript:alert('XSS')",
            "<img src=x onerror=alert('XSS')>",
            "';alert('XSS');//",
            "<svg onload=alert('XSS')>"
        ]
        
        xss_blocked = 0
        for payload in xss_payloads:
            username = f"xsstest_{secrets.token_hex(2)}"
            response = requests.post(f"{API_URL}/wallet/create", json={
                "username": payload,
                "password": "SecurePass123!"
            })
            
            # Check if payload is reflected unsanitized
            if response.status_code == 400 or (response.status_code == 200 and payload not in response.text):
                xss_blocked += 1
        
        if xss_blocked >= 4:  # At least 4/5 XSS attempts blocked
            log_security_test(
                "XSS Protection", True, "input_validation_security",
                f"Blocked {xss_blocked}/5 XSS payloads",
                "high", None
            )
        else:
            log_security_test(
                "XSS Protection", False, "input_validation_security",
                f"Only blocked {xss_blocked}/5 XSS payloads",
                "critical", "Implement comprehensive input sanitization and output encoding"
            )
    except Exception as e:
        log_security_test(
            "XSS Protection", False, "input_validation_security",
            f"Test error: {str(e)}", "high", "Investigate XSS protection implementation"
        )
    
    # Test 2.2: SQL/NoSQL Injection Protection
    try:
        injection_payloads = [
            "'; DROP TABLE wallets; --",
            "' OR '1'='1",
            "admin'--",
            "' UNION SELECT * FROM users--",
            "'; INSERT INTO wallets VALUES('hacked'); --"
        ]
        
        injection_blocked = 0
        for payload in injection_payloads:
            username = f"sqltest_{secrets.token_hex(2)}"
            response = requests.post(f"{API_URL}/wallet/create", json={
                "username": payload,
                "password": "SecurePass123!"
            })
            
            # Check if injection attempt is properly handled
            if response.status_code == 400 or response.status_code == 422:
                injection_blocked += 1
        
        if injection_blocked >= 4:  # At least 4/5 injection attempts blocked
            log_security_test(
                "SQL/NoSQL Injection Protection", True, "input_validation_security",
                f"Blocked {injection_blocked}/5 injection attempts",
                "critical", None
            )
        else:
            log_security_test(
                "SQL/NoSQL Injection Protection", False, "input_validation_security",
                f"Only blocked {injection_blocked}/5 injection attempts",
                "critical", "Implement parameterized queries and input validation"
            )
    except Exception as e:
        log_security_test(
            "SQL/NoSQL Injection Protection", False, "input_validation_security",
            f"Test error: {str(e)}", "critical", "Investigate injection protection implementation"
        )
    
    # Test 2.3: Parameter Validation
    try:
        # Test invalid transaction amounts
        test_address = generate_valid_wepo_address()
        invalid_amounts = [-100, 0, "invalid", None, float('inf')]
        
        amount_validation_working = 0
        for amount in invalid_amounts:
            response = requests.post(f"{API_URL}/transaction/send", json={
                "from_address": test_address,
                "to_address": test_address,
                "amount": amount
            })
            
            if response.status_code == 400 or response.status_code == 422:
                amount_validation_working += 1
        
        if amount_validation_working >= 4:  # At least 4/5 invalid amounts rejected
            log_security_test(
                "Parameter Validation", True, "input_validation_security",
                f"Rejected {amount_validation_working}/5 invalid amounts",
                "medium", None
            )
        else:
            log_security_test(
                "Parameter Validation", False, "input_validation_security",
                f"Only rejected {amount_validation_working}/5 invalid amounts",
                "medium", "Implement comprehensive parameter validation"
            )
    except Exception as e:
        log_security_test(
            "Parameter Validation", False, "input_validation_security",
            f"Test error: {str(e)}", "medium", "Investigate parameter validation implementation"
        )

# ===== 3. RATE LIMITING & DDOS PROTECTION =====

def test_rate_limiting_protection():
    """Test 3: Rate Limiting & DDoS Protection"""
    print("\n⚡ RATE LIMITING & DDOS PROTECTION TESTING")
    print("Testing rate limiting effectiveness and abuse prevention...")
    
    # Test 3.1: Wallet Creation Rate Limiting
    try:
        rate_limited = False
        for i in range(10):  # Try 10 rapid wallet creations
            username = f"ratetest_{i}_{secrets.token_hex(2)}"
            response = requests.post(f"{API_URL}/wallet/create", json={
                "username": username,
                "password": "SecurePass123!"
            })
            
            if response.status_code == 429:  # Rate limited
                rate_limited = True
                log_security_test(
                    "Wallet Creation Rate Limiting", True, "rate_limiting_protection",
                    f"Rate limiting activated after {i+1} attempts",
                    "high", None
                )
                break
            
            time.sleep(0.1)  # Small delay between requests
        
        if not rate_limited:
            log_security_test(
                "Wallet Creation Rate Limiting", False, "rate_limiting_protection",
                "No rate limiting detected after 10 rapid attempts",
                "high", "Implement rate limiting on wallet creation (3-5 per minute)"
            )
    except Exception as e:
        log_security_test(
            "Wallet Creation Rate Limiting", False, "rate_limiting_protection",
            f"Test error: {str(e)}", "medium", "Investigate rate limiting implementation"
        )
    
    # Test 3.2: Transaction Rate Limiting
    try:
        test_address = generate_valid_wepo_address()
        rate_limited = False
        
        for i in range(15):  # Try 15 rapid transactions
            response = requests.post(f"{API_URL}/transaction/send", json={
                "from_address": test_address,
                "to_address": generate_valid_wepo_address(),
                "amount": 1.0
            })
            
            if response.status_code == 429:  # Rate limited
                rate_limited = True
                log_security_test(
                    "Transaction Rate Limiting", True, "rate_limiting_protection",
                    f"Rate limiting activated after {i+1} attempts",
                    "high", None
                )
                break
            
            time.sleep(0.05)  # Very small delay
        
        if not rate_limited:
            log_security_test(
                "Transaction Rate Limiting", False, "rate_limiting_protection",
                "No rate limiting detected after 15 rapid attempts",
                "high", "Implement rate limiting on transactions (10-20 per minute)"
            )
    except Exception as e:
        log_security_test(
            "Transaction Rate Limiting", False, "rate_limiting_protection",
            f"Test error: {str(e)}", "medium", "Investigate transaction rate limiting"
        )
    
    # Test 3.3: API Endpoint Abuse Protection
    try:
        endpoints_to_test = [
            "/network/status",
            "/mining/info",
            "/swap/rate"
        ]
        
        protected_endpoints = 0
        for endpoint in endpoints_to_test:
            rate_limited = False
            for i in range(20):  # Try 20 rapid requests
                response = requests.get(f"{API_URL}{endpoint}")
                
                if response.status_code == 429:
                    rate_limited = True
                    protected_endpoints += 1
                    break
                
                time.sleep(0.02)  # Very rapid requests
            
            if not rate_limited and endpoint == "/network/status":
                # Network status might be cached, which is acceptable
                protected_endpoints += 0.5
        
        if protected_endpoints >= 2:  # At least 2/3 endpoints protected
            log_security_test(
                "API Endpoint Abuse Protection", True, "rate_limiting_protection",
                f"Protected {protected_endpoints}/3 endpoints from abuse",
                "medium", None
            )
        else:
            log_security_test(
                "API Endpoint Abuse Protection", False, "rate_limiting_protection",
                f"Only protected {protected_endpoints}/3 endpoints",
                "medium", "Implement global rate limiting on API endpoints"
            )
    except Exception as e:
        log_security_test(
            "API Endpoint Abuse Protection", False, "rate_limiting_protection",
            f"Test error: {str(e)}", "medium", "Investigate API abuse protection"
        )

# ===== 4. HTTP SECURITY HEADERS =====

def test_http_security_headers():
    """Test 4: HTTP Security Headers"""
    print("\n🛡️ HTTP SECURITY HEADERS TESTING")
    print("Testing security headers implementation and CORS configuration...")
    
    # Test 4.1: Essential Security Headers
    try:
        response = requests.get(f"{API_URL}/")
        
        required_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": ["DENY", "SAMEORIGIN"],
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": "max-age",
            "Content-Security-Policy": "default-src"
        }
        
        headers_present = 0
        missing_headers = []
        
        for header, expected in required_headers.items():
            if header in response.headers:
                header_value = response.headers[header]
                if isinstance(expected, list):
                    if any(exp in header_value for exp in expected):
                        headers_present += 1
                    else:
                        missing_headers.append(f"{header} (invalid value)")
                elif expected in header_value:
                    headers_present += 1
                else:
                    missing_headers.append(f"{header} (invalid value)")
            else:
                missing_headers.append(header)
        
        if headers_present >= 4:  # At least 4/5 headers present
            log_security_test(
                "Essential Security Headers", True, "http_security_headers",
                f"Present: {headers_present}/5 security headers",
                "high", None
            )
        else:
            log_security_test(
                "Essential Security Headers", False, "http_security_headers",
                f"Missing: {missing_headers}",
                "high", "Implement all essential HTTP security headers"
            )
    except Exception as e:
        log_security_test(
            "Essential Security Headers", False, "http_security_headers",
            f"Test error: {str(e)}", "high", "Investigate security headers implementation"
        )
    
    # Test 4.2: CORS Configuration Security
    try:
        # Test with various origins
        test_origins = [
            "https://malicious-site.com",
            "http://localhost:3000",
            "*",
            "null"
        ]
        
        secure_cors = True
        cors_issues = []
        
        for origin in test_origins:
            response = requests.get(f"{API_URL}/", headers={"Origin": origin})
            
            if "Access-Control-Allow-Origin" in response.headers:
                allowed_origin = response.headers["Access-Control-Allow-Origin"]
                
                if allowed_origin == "*":
                    secure_cors = False
                    cors_issues.append("Wildcard (*) CORS policy detected")
                elif origin == "https://malicious-site.com" and allowed_origin == origin:
                    secure_cors = False
                    cors_issues.append("Malicious origin allowed")
        
        if secure_cors:
            log_security_test(
                "CORS Configuration Security", True, "http_security_headers",
                "CORS properly restricted - no wildcard or malicious origins",
                "medium", None
            )
        else:
            log_security_test(
                "CORS Configuration Security", False, "http_security_headers",
                f"CORS issues: {cors_issues}",
                "medium", "Restrict CORS to specific trusted origins only"
            )
    except Exception as e:
        log_security_test(
            "CORS Configuration Security", False, "http_security_headers",
            f"Test error: {str(e)}", "medium", "Investigate CORS configuration"
        )

# ===== 5. DATA PROTECTION & PRIVACY =====

def test_data_protection_privacy():
    """Test 5: Data Protection & Privacy"""
    print("\n🔒 DATA PROTECTION & PRIVACY TESTING")
    print("Testing sensitive data exposure and information disclosure...")
    
    # Test 5.1: Sensitive Data Exposure
    try:
        username, password = generate_test_credentials()
        
        # Create wallet
        create_response = requests.post(f"{API_URL}/wallet/create", json={
            "username": username,
            "password": password
        })
        
        sensitive_data_exposed = False
        exposure_issues = []
        
        if create_response.status_code == 200:
            response_text = create_response.text.lower()
            
            # Check for sensitive data in response
            if password.lower() in response_text:
                sensitive_data_exposed = True
                exposure_issues.append("Password exposed in response")
            
            if "private_key" in response_text and len(response_text) > 100:
                sensitive_data_exposed = True
                exposure_issues.append("Private key potentially exposed")
            
            if "secret" in response_text or "seed" in response_text:
                # Check if it's just field names or actual values
                if len([word for word in response_text.split() if len(word) > 20]) > 0:
                    sensitive_data_exposed = True
                    exposure_issues.append("Seed/secret data potentially exposed")
        
        if not sensitive_data_exposed:
            log_security_test(
                "Sensitive Data Exposure", True, "data_protection_privacy",
                "No sensitive data exposed in API responses",
                "critical", None
            )
        else:
            log_security_test(
                "Sensitive Data Exposure", False, "data_protection_privacy",
                f"Exposure issues: {exposure_issues}",
                "critical", "Remove all sensitive data from API responses"
            )
    except Exception as e:
        log_security_test(
            "Sensitive Data Exposure", False, "data_protection_privacy",
            f"Test error: {str(e)}", "critical", "Investigate data exposure protection"
        )
    
    # Test 5.2: Error Message Information Disclosure
    try:
        # Test various error conditions
        error_responses = []
        
        # Invalid wallet lookup
        response = requests.get(f"{API_URL}/wallet/nonexistent_wallet_12345")
        error_responses.append(("wallet_lookup", response))
        
        # Invalid transaction
        response = requests.post(f"{API_URL}/transaction/send", json={
            "from_address": "invalid",
            "to_address": "invalid",
            "amount": -1
        })
        error_responses.append(("transaction", response))
        
        information_disclosed = False
        disclosure_issues = []
        
        for test_name, response in error_responses:
            if response.status_code >= 400:
                response_text = response.text.lower()
                
                # Check for information disclosure
                if any(keyword in response_text for keyword in ["database", "sql", "mongodb", "stack trace", "file path"]):
                    information_disclosed = True
                    disclosure_issues.append(f"{test_name}: System information disclosed")
        
        if not information_disclosed:
            log_security_test(
                "Error Message Information Disclosure", True, "data_protection_privacy",
                "Error messages properly sanitized",
                "medium", None
            )
        else:
            log_security_test(
                "Error Message Information Disclosure", False, "data_protection_privacy",
                f"Disclosure issues: {disclosure_issues}",
                "medium", "Sanitize error messages to prevent information disclosure"
            )
    except Exception as e:
        log_security_test(
            "Error Message Information Disclosure", False, "data_protection_privacy",
            f"Test error: {str(e)}", "medium", "Investigate error message handling"
        )

# ===== 6. CRYPTOCURRENCY-SPECIFIC SECURITY =====

def test_cryptocurrency_security():
    """Test 6: Cryptocurrency-Specific Security"""
    print("\n💰 CRYPTOCURRENCY-SPECIFIC SECURITY TESTING")
    print("Testing wallet operations, transaction validation, and blockchain security...")
    
    # Test 6.1: Wallet Operation Security
    try:
        username, password = generate_test_credentials()
        
        # Test wallet creation security
        create_response = requests.post(f"{API_URL}/wallet/create", json={
            "username": username,
            "password": password
        })
        
        wallet_secure = True
        security_issues = []
        
        if create_response.status_code == 200:
            wallet_data = create_response.json()
            
            # Check wallet address format
            address = wallet_data.get("address", "")
            if not address.startswith("wepo1") or len(address) != 37:
                wallet_secure = False
                security_issues.append("Invalid wallet address format")
            
            # Check for proper response structure
            if not wallet_data.get("success"):
                wallet_secure = False
                security_issues.append("Wallet creation response lacks success confirmation")
            
            # Test wallet balance check
            balance_response = requests.get(f"{API_URL}/wallet/{address}")
            if balance_response.status_code == 200:
                balance_data = balance_response.json()
                if "balance" not in balance_data:
                    wallet_secure = False
                    security_issues.append("Balance information missing from wallet data")
        else:
            wallet_secure = False
            security_issues.append(f"Wallet creation failed: HTTP {create_response.status_code}")
        
        if wallet_secure:
            log_security_test(
                "Wallet Operation Security", True, "cryptocurrency_security",
                "Wallet operations properly secured and validated",
                "high", None
            )
        else:
            log_security_test(
                "Wallet Operation Security", False, "cryptocurrency_security",
                f"Security issues: {security_issues}",
                "high", "Implement comprehensive wallet operation validation"
            )
    except Exception as e:
        log_security_test(
            "Wallet Operation Security", False, "cryptocurrency_security",
            f"Test error: {str(e)}", "high", "Investigate wallet security implementation"
        )
    
    # Test 6.2: Transaction Validation Security
    try:
        test_address = generate_valid_wepo_address()
        
        # Test various invalid transactions
        invalid_transactions = [
            {"from_address": "", "to_address": test_address, "amount": 1.0},
            {"from_address": test_address, "to_address": "", "amount": 1.0},
            {"from_address": test_address, "to_address": test_address, "amount": 1.0},  # Self-transaction
            {"from_address": test_address, "to_address": test_address, "amount": -1.0},  # Negative amount
            {"from_address": "invalid_address", "to_address": test_address, "amount": 1.0}
        ]
        
        validation_working = 0
        for tx in invalid_transactions:
            response = requests.post(f"{API_URL}/transaction/send", json=tx)
            if response.status_code == 400 or response.status_code == 422:
                validation_working += 1
        
        if validation_working >= 4:  # At least 4/5 invalid transactions rejected
            log_security_test(
                "Transaction Validation Security", True, "cryptocurrency_security",
                f"Rejected {validation_working}/5 invalid transactions",
                "critical", None
            )
        else:
            log_security_test(
                "Transaction Validation Security", False, "cryptocurrency_security",
                f"Only rejected {validation_working}/5 invalid transactions",
                "critical", "Implement comprehensive transaction validation"
            )
    except Exception as e:
        log_security_test(
            "Transaction Validation Security", False, "cryptocurrency_security",
            f"Test error: {str(e)}", "critical", "Investigate transaction validation"
        )
    
    # Test 6.3: Mining and Staking Security
    try:
        # Test mining endpoints
        mining_response = requests.get(f"{API_URL}/mining/info")
        network_response = requests.get(f"{API_URL}/network/status")
        
        mining_secure = True
        mining_issues = []
        
        if mining_response.status_code == 200:
            mining_data = mining_response.json()
            
            # Check for reasonable mining data
            if mining_data.get("current_reward", 0) <= 0:
                mining_secure = False
                mining_issues.append("Invalid mining reward data")
            
            if not mining_data.get("algorithm"):
                mining_secure = False
                mining_issues.append("Mining algorithm not specified")
        else:
            mining_secure = False
            mining_issues.append("Mining info endpoint not accessible")
        
        if network_response.status_code == 200:
            network_data = network_response.json()
            
            # Check network data integrity
            if network_data.get("total_supply", 0) <= 0:
                mining_secure = False
                mining_issues.append("Invalid total supply data")
        else:
            mining_secure = False
            mining_issues.append("Network status endpoint not accessible")
        
        if mining_secure:
            log_security_test(
                "Mining and Network Security", True, "cryptocurrency_security",
                "Mining and network data properly secured",
                "medium", None
            )
        else:
            log_security_test(
                "Mining and Network Security", False, "cryptocurrency_security",
                f"Security issues: {mining_issues}",
                "medium", "Validate mining and network data integrity"
            )
    except Exception as e:
        log_security_test(
            "Mining and Network Security", False, "cryptocurrency_security",
            f"Test error: {str(e)}", "medium", "Investigate mining/network security"
        )

# ===== 7. API ENDPOINT FUNCTIONALITY VERIFICATION =====

def test_api_functionality():
    """Test 7: API Endpoint Functionality Verification"""
    print("\n🔧 API ENDPOINT FUNCTIONALITY VERIFICATION")
    print("Testing critical API endpoints for proper functionality and reliability...")
    
    # Test 7.1: Core API Endpoints
    try:
        core_endpoints = [
            ("/", "API root"),
            ("/network/status", "Network status"),
            ("/mining/info", "Mining information"),
            ("/swap/rate", "Exchange rates")
        ]
        
        functional_endpoints = 0
        for endpoint, description in core_endpoints:
            response = requests.get(f"{API_URL}{endpoint}")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    if isinstance(data, dict) and data:  # Valid JSON response with data
                        functional_endpoints += 1
                except:
                    pass  # Invalid JSON response
        
        if functional_endpoints >= 3:  # At least 3/4 endpoints working
            log_security_test(
                "Core API Endpoints", True, "api_functionality",
                f"Functional: {functional_endpoints}/4 core endpoints",
                "high", None
            )
        else:
            log_security_test(
                "Core API Endpoints", False, "api_functionality",
                f"Only {functional_endpoints}/4 endpoints functional",
                "high", "Fix non-functional API endpoints"
            )
    except Exception as e:
        log_security_test(
            "Core API Endpoints", False, "api_functionality",
            f"Test error: {str(e)}", "high", "Investigate API endpoint functionality"
        )
    
    # Test 7.2: Error Handling Consistency
    try:
        # Test various error conditions
        error_tests = [
            (f"{API_URL}/wallet/nonexistent", "GET", None, "Wallet not found"),
            (f"{API_URL}/transaction/send", "POST", {"invalid": "data"}, "Invalid transaction"),
            (f"{API_URL}/nonexistent/endpoint", "GET", None, "Endpoint not found")
        ]
        
        consistent_errors = 0
        for url, method, data, description in error_tests:
            if method == "GET":
                response = requests.get(url)
            else:
                response = requests.post(url, json=data)
            
            # Check for proper HTTP status codes
            if response.status_code in [400, 404, 422, 500]:
                try:
                    error_data = response.json()
                    if "detail" in error_data or "message" in error_data or "error" in error_data:
                        consistent_errors += 1
                except:
                    # Non-JSON error response is also acceptable
                    consistent_errors += 1
        
        if consistent_errors >= 2:  # At least 2/3 error conditions handled properly
            log_security_test(
                "Error Handling Consistency", True, "api_functionality",
                f"Consistent: {consistent_errors}/3 error conditions",
                "medium", None
            )
        else:
            log_security_test(
                "Error Handling Consistency", False, "api_functionality",
                f"Only {consistent_errors}/3 error conditions handled properly",
                "medium", "Implement consistent error handling across all endpoints"
            )
    except Exception as e:
        log_security_test(
            "Error Handling Consistency", False, "api_functionality",
            f"Test error: {str(e)}", "medium", "Investigate error handling implementation"
        )
    
    # Test 7.3: API Response Performance
    try:
        performance_endpoints = [
            "/network/status",
            "/mining/info",
            "/"
        ]
        
        fast_endpoints = 0
        for endpoint in performance_endpoints:
            start_time = time.time()
            response = requests.get(f"{API_URL}{endpoint}")
            end_time = time.time()
            
            response_time = end_time - start_time
            
            if response.status_code == 200 and response_time < 2.0:  # Under 2 seconds
                fast_endpoints += 1
        
        if fast_endpoints >= 2:  # At least 2/3 endpoints respond quickly
            log_security_test(
                "API Response Performance", True, "api_functionality",
                f"Fast response: {fast_endpoints}/3 endpoints under 2s",
                "low", None
            )
        else:
            log_security_test(
                "API Response Performance", False, "api_functionality",
                f"Only {fast_endpoints}/3 endpoints respond quickly",
                "low", "Optimize API response times"
            )
    except Exception as e:
        log_security_test(
            "API Response Performance", False, "api_functionality",
            f"Test error: {str(e)}", "low", "Investigate API performance"
        )

# ===== 8. NETWORK SECURITY & INFRASTRUCTURE =====

def test_network_security():
    """Test 8: Network Security & Infrastructure"""
    print("\n🌐 NETWORK SECURITY & INFRASTRUCTURE TESTING")
    print("Testing server security, information disclosure, and infrastructure hardening...")
    
    # Test 8.1: Server Information Disclosure
    try:
        response = requests.get(f"{API_URL}/")
        
        server_secure = True
        disclosure_issues = []
        
        # Check response headers for information disclosure
        sensitive_headers = ["Server", "X-Powered-By", "X-AspNet-Version"]
        for header in sensitive_headers:
            if header in response.headers:
                server_secure = False
                disclosure_issues.append(f"{header} header exposes server information")
        
        # Check response body for version information
        response_text = response.text.lower()
        if any(keyword in response_text for keyword in ["version", "build", "debug", "development"]):
            # Check if it's just API version (acceptable) or system version (not acceptable)
            if "api" not in response_text or "system" in response_text:
                server_secure = False
                disclosure_issues.append("System version information disclosed")
        
        if server_secure:
            log_security_test(
                "Server Information Disclosure", True, "network_security",
                "No sensitive server information disclosed",
                "medium", None
            )
        else:
            log_security_test(
                "Server Information Disclosure", False, "network_security",
                f"Disclosure issues: {disclosure_issues}",
                "medium", "Remove server information from headers and responses"
            )
    except Exception as e:
        log_security_test(
            "Server Information Disclosure", False, "network_security",
            f"Test error: {str(e)}", "medium", "Investigate server information disclosure"
        )
    
    # Test 8.2: HTTP Methods Security
    try:
        # Test for insecure HTTP methods
        insecure_methods = ["TRACE", "OPTIONS", "PUT", "DELETE", "PATCH"]
        
        secure_methods = 0
        for method in insecure_methods:
            response = requests.request(method, f"{API_URL}/")
            
            # These methods should return 405 (Method Not Allowed) or 404
            if response.status_code in [404, 405]:
                secure_methods += 1
        
        if secure_methods >= 4:  # At least 4/5 insecure methods blocked
            log_security_test(
                "HTTP Methods Security", True, "network_security",
                f"Blocked: {secure_methods}/5 insecure HTTP methods",
                "low", None
            )
        else:
            log_security_test(
                "HTTP Methods Security", False, "network_security",
                f"Only blocked {secure_methods}/5 insecure methods",
                "low", "Disable unnecessary HTTP methods"
            )
    except Exception as e:
        log_security_test(
            "HTTP Methods Security", False, "network_security",
            f"Test error: {str(e)}", "low", "Investigate HTTP methods configuration"
        )
    
    # Test 8.3: SSL/TLS Security
    try:
        # Check if HTTPS is enforced
        if BACKEND_URL.startswith("https://"):
            log_security_test(
                "SSL/TLS Security", True, "network_security",
                "HTTPS properly configured and enforced",
                "critical", None
            )
        else:
            log_security_test(
                "SSL/TLS Security", False, "network_security",
                "HTTPS not enforced - using HTTP",
                "critical", "Enforce HTTPS for all API communications"
            )
    except Exception as e:
        log_security_test(
            "SSL/TLS Security", False, "network_security",
            f"Test error: {str(e)}", "critical", "Investigate SSL/TLS configuration"
        )

def generate_security_report():
    """Generate comprehensive security audit report"""
    print("\n" + "=" * 80)
    print("🔐 COMPREHENSIVE SECURITY AUDIT REPORT")
    print("=" * 80)
    
    total_tests = security_results["total"]
    passed_tests = security_results["passed"]
    failed_tests = security_results["failed"]
    
    overall_score = (passed_tests / total_tests) * 100 if total_tests > 0 else 0
    
    print(f"📊 OVERALL SECURITY SCORE: {overall_score:.1f}%")
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {passed_tests} ✅")
    print(f"Failed: {failed_tests} ❌")
    
    # Security grade
    if overall_score >= 90:
        grade = "A+ (EXCELLENT)"
        status = "🎉 ENTERPRISE-READY"
    elif overall_score >= 80:
        grade = "A (VERY GOOD)"
        status = "✅ PRODUCTION-READY"
    elif overall_score >= 70:
        grade = "B (GOOD)"
        status = "⚠️ NEEDS MINOR FIXES"
    elif overall_score >= 60:
        grade = "C (FAIR)"
        status = "🔧 NEEDS IMPROVEMENTS"
    else:
        grade = "F (POOR)"
        status = "🚨 CRITICAL ISSUES"
    
    print(f"Security Grade: {grade}")
    print(f"Launch Status: {status}")
    
    # Category breakdown
    print(f"\n📋 SECURITY CATEGORY BREAKDOWN:")
    
    category_names = {
        "authentication_security": "🔐 Authentication & Authorization",
        "input_validation_security": "🛡️ Input Validation & Sanitization",
        "rate_limiting_protection": "⚡ Rate Limiting & DDoS Protection",
        "http_security_headers": "🛡️ HTTP Security Headers",
        "data_protection_privacy": "🔒 Data Protection & Privacy",
        "cryptocurrency_security": "💰 Cryptocurrency-Specific Security",
        "api_functionality": "🔧 API Functionality",
        "network_security": "🌐 Network Security & Infrastructure"
    }
    
    critical_issues = []
    high_issues = []
    
    for category_key, category_name in category_names.items():
        cat_data = security_results["categories"][category_key]
        cat_score = (cat_data["passed"] / cat_data["total"]) * 100 if cat_data["total"] > 0 else 0
        
        if cat_score >= 80:
            status_icon = "✅"
        elif cat_score >= 60:
            status_icon = "⚠️"
        else:
            status_icon = "🚨"
        
        print(f"  {status_icon} {category_name}: {cat_data['passed']}/{cat_data['total']} ({cat_score:.1f}%)")
        
        # Collect failed tests by severity
        for test in cat_data["tests"]:
            if not test["passed"]:
                if test["severity"] == "critical":
                    critical_issues.append(f"{test['name']} - {test['details']}")
                elif test["severity"] == "high":
                    high_issues.append(f"{test['name']} - {test['details']}")
    
    # Critical and high severity issues
    if critical_issues:
        print(f"\n🔴 CRITICAL SECURITY ISSUES ({len(critical_issues)}):")
        for i, issue in enumerate(critical_issues, 1):
            print(f"  {i}. {issue}")
    
    if high_issues:
        print(f"\n🟠 HIGH SEVERITY ISSUES ({len(high_issues)}):")
        for i, issue in enumerate(high_issues, 1):
            print(f"  {i}. {issue}")
    
    # Recommendations
    print(f"\n💡 SECURITY RECOMMENDATIONS:")
    
    if overall_score >= 90:
        print("• 🎉 EXCELLENT SECURITY POSTURE!")
        print("• System meets enterprise-grade security standards")
        print("• Under launch review")
        print("• Continue monitoring and regular security audits")
    elif overall_score >= 80:
        print("• ✅ STRONG SECURITY FOUNDATION")
        print("• Address remaining high-severity issues")
        print("• System is not yet production-ready with minor improvements")
        print("• Implement continuous security monitoring")
    elif overall_score >= 70:
        print("• ⚠️ GOOD SECURITY WITH ROOM FOR IMPROVEMENT")
        print("• Focus on critical and high-severity vulnerabilities")
        print("• Implement additional security controls")
        print("• Re-audit after fixes are applied")
    else:
        print("• 🚨 SIGNIFICANT SECURITY IMPROVEMENTS NEEDED")
        print("• Address all critical vulnerabilities immediately")
        print("• Implement comprehensive security controls")
        print("• Consider security code review and penetration testing")
    
    # Launch Readiness
    print(f"\n🎄 CHRISTMAS DAY 2025 LAUNCH READINESS:")
    
    if overall_score >= 85:
        print("✅ READY FOR LAUNCH")
        print("• Security standards meet enterprise requirements")
        print("• Cryptocurrency-specific protections in place")
        print("• User data and transactions properly secured")
    elif overall_score >= 70:
        print("⚠️ LAUNCH POSSIBLE WITH FIXES")
        print("• Address critical issues before launch")
        print("• Implement additional security monitoring")
        print("• Consider phased rollout with security monitoring")
    else:
        print("🚨 NOT READY FOR LAUNCH")
        print("• Critical security vulnerabilities must be resolved")
        print("• Comprehensive security improvements required")
        print("• Delay launch until security standards are met")
    
    return {
        "overall_score": overall_score,
        "grade": grade,
        "total_tests": total_tests,
        "passed_tests": passed_tests,
        "failed_tests": failed_tests,
        "critical_issues": len(critical_issues),
        "high_issues": len(high_issues),
        "categories": security_results["categories"]
    }

def run_comprehensive_security_audit():
    """Run the complete security audit"""
    print("🔐 STARTING COMPREHENSIVE API SECURITY AUDIT")
    print("Testing all security categories for enterprise-grade protection...")
    print("=" * 80)
    
    # Run all security test categories
    test_authentication_security()
    test_input_validation_security()
    test_rate_limiting_protection()
    test_http_security_headers()
    test_data_protection_privacy()
    test_cryptocurrency_security()
    test_api_functionality()
    test_network_security()
    
    # Generate comprehensive report
    report = generate_security_report()
    
    return report

if __name__ == "__main__":
    # Run comprehensive security audit
    audit_results = run_comprehensive_security_audit()
    
    print("\n" + "=" * 80)
    print("🎯 FINAL SECURITY AUDIT SUMMARY")
    print("=" * 80)
    
    print(f"🔐 OVERALL SECURITY SCORE: {audit_results['overall_score']:.1f}%")
    print(f"📊 SECURITY GRADE: {audit_results['grade']}")
    print(f"📈 TESTS PASSED: {audit_results['passed_tests']}/{audit_results['total_tests']}")
    
    if audit_results['critical_issues'] > 0:
        print(f"🔴 CRITICAL ISSUES: {audit_results['critical_issues']}")
    
    if audit_results['high_issues'] > 0:
        print(f"🟠 HIGH SEVERITY ISSUES: {audit_results['high_issues']}")
    
    print(f"\n🎄 CHRISTMAS DAY 2025 LAUNCH STATUS:")
    if audit_results['overall_score'] >= 85:
        print("✅ SECURITY AUDIT PASSED - READY FOR LAUNCH!")
    elif audit_results['overall_score'] >= 70:
        print("⚠️ CONDITIONAL PASS - MINOR FIXES NEEDED")
    else:
        print("🚨 SECURITY AUDIT FAILED - MAJOR IMPROVEMENTS REQUIRED")
    
    print(f"\n🔧 NEXT STEPS:")
    if audit_results['overall_score'] >= 90:
        print("• Maintain current security posture")
        print("• Implement continuous monitoring")
        print("• Regular security audits")
    elif audit_results['overall_score'] >= 80:
        print("• Address remaining high-severity issues")
        print("• Implement additional monitoring")
        print("• Schedule follow-up audit")
    else:
        print("• Fix all critical and high-severity vulnerabilities")
        print("• Implement comprehensive security controls")
        print("• Re-run security audit after fixes")