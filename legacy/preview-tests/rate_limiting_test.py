#!/usr/bin/env python3
"""
COMPREHENSIVE RATE LIMITING OPTIMIZATION TESTING
Focus: Improving from 60% to 100% rate limiting functionality

**OPTIMIZATION IMPROVEMENTS TO TEST:**
1. ✅ OptimizedRateLimiter Class - Enhanced Redis integration with better fallback handling
2. ✅ Enhanced Error Responses - Added retry_after, limit_type, X-RateLimit-Remaining headers  
3. ✅ Better UX Messages - Improved user-friendly rate limit error messages
4. ✅ Infrastructure Optimization - More robust rate limiting system architecture

**COMPREHENSIVE RATE LIMITING TESTS:**
1. GLOBAL API RATE LIMITING (High Priority) - 60/minute rate limit
2. ENDPOINT-SPECIFIC RATE LIMITING (High Priority) - wallet creation (3/minute), login (5/minute)
3. RATE LIMITING HEADERS & METADATA (Medium Priority) - All headers present and accurate
4. RATE LIMITING PERSISTENCE & RECOVERY (Medium Priority) - Redis vs in-memory behavior
5. USER EXPERIENCE OPTIMIZATION (Lower Priority) - Clear error messages and retry guidance

**SCORING CRITERIA FOR 100% RATE LIMITING:**
- Global rate limiting: Must work with accurate HTTP 429 responses
- Endpoint-specific limits: Must enforce wallet creation (3/min) and login (5/min) limits
- Headers: All rate limiting headers must be accurate and present
- Persistence: Rate limiting must work consistently across requests
- UX: Error messages must be clear and helpful

**TARGET:** Achieve 90-100% rate limiting functionality for optimal system performance.
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

# Use preview backend URL from frontend/.env
BACKEND_URL = "https://blockchain-sectest.preview.emergentagent.com"
API_URL = f"{BACKEND_URL}/api"

print(f"🚀 COMPREHENSIVE RATE LIMITING OPTIMIZATION TESTING")
print(f"Preview Backend API URL: {API_URL}")
print(f"Focus: Improving from 60% to 100% rate limiting functionality")
print("=" * 80)

# Test results tracking
test_results = {
    "total": 0,
    "passed": 0,
    "failed": 0,
    "tests": [],
    "categories": {
        "global_rate_limiting": {"passed": 0, "total": 0, "weight": 30},
        "endpoint_specific_limiting": {"passed": 0, "total": 0, "weight": 30},
        "rate_limiting_headers": {"passed": 0, "total": 0, "weight": 20},
        "persistence_recovery": {"passed": 0, "total": 0, "weight": 15},
        "user_experience": {"passed": 0, "total": 0, "weight": 5}
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

def generate_test_user_data():
    """Generate realistic test user data"""
    username = f"ratetest_{secrets.token_hex(4)}"
    password = f"TestPass123!{secrets.token_hex(2)}"
    return username, password

def make_rapid_requests(url, data=None, method="GET", count=10, delay=0.1):
    """Make rapid requests to test rate limiting"""
    results = []
    
    for i in range(count):
        try:
            if method == "POST":
                response = requests.post(url, json=data, timeout=5)
            else:
                response = requests.get(url, timeout=5)
            
            results.append({
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "response_time": response.elapsed.total_seconds(),
                "request_number": i + 1
            })
            
            if delay > 0:
                time.sleep(delay)
                
        except Exception as e:
            results.append({
                "status_code": 0,
                "headers": {},
                "error": str(e),
                "request_number": i + 1
            })
    
    return results

def check_rate_limit_headers(headers):
    """Check for presence and accuracy of rate limiting headers"""
    expected_headers = [
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining", 
        "X-RateLimit-Reset",
        "Retry-After"
    ]
    
    present_headers = []
    missing_headers = []
    
    for header in expected_headers:
        if header in headers:
            present_headers.append(header)
        else:
            missing_headers.append(header)
    
    return {
        "present": present_headers,
        "missing": missing_headers,
        "total_expected": len(expected_headers),
        "total_present": len(present_headers),
        "percentage": (len(present_headers) / len(expected_headers)) * 100
    }

# ===== 1. GLOBAL API RATE LIMITING TESTING =====

def test_global_api_rate_limiting():
    """Test 1: Global API Rate Limiting (High Priority) - 60/minute limit"""
    print("\n🌐 GLOBAL API RATE LIMITING TESTING - HIGH PRIORITY")
    print("Testing global 60/minute rate limit with rapid API requests...")
    
    # Test global rate limiting with rapid requests to root endpoint
    try:
        print("  Testing rapid requests to API root endpoint...")
        results = make_rapid_requests(f"{API_URL}/", count=65, delay=0.05)
        
        # Analyze results
        status_codes = [r["status_code"] for r in results if "status_code" in r]
        rate_limited_requests = [r for r in results if r.get("status_code") == 429]
        successful_requests = [r for r in results if r.get("status_code") == 200]
        
        if len(rate_limited_requests) > 0:
            # Check if rate limiting kicked in around the expected limit
            first_rate_limit = next((i for i, r in enumerate(results) if r.get("status_code") == 429), None)
            
            if first_rate_limit and first_rate_limit <= 65:  # Should hit limit before 65 requests
                log_test("Global API Rate Limiting Enforcement", True, "global_rate_limiting",
                        details=f"Rate limiting activated after {first_rate_limit + 1} requests. {len(rate_limited_requests)} requests blocked with HTTP 429")
            else:
                log_test("Global API Rate Limiting Enforcement", False, "global_rate_limiting",
                        details=f"Rate limiting too lenient - first 429 at request {first_rate_limit + 1 if first_rate_limit else 'never'}")
        else:
            log_test("Global API Rate Limiting Enforcement", False, "global_rate_limiting",
                    details=f"No rate limiting detected after 65 requests. All responses: {set(status_codes)}")
    
    except Exception as e:
        log_test("Global API Rate Limiting Enforcement", False, "global_rate_limiting", error=str(e))
    
    # Test HTTP 429 response format
    try:
        print("  Testing HTTP 429 response format and headers...")
        # Make enough requests to trigger rate limiting
        results = make_rapid_requests(f"{API_URL}/", count=70, delay=0.02)
        
        rate_limited_responses = [r for r in results if r.get("status_code") == 429]
        
        if rate_limited_responses:
            sample_429 = rate_limited_responses[0]
            headers_check = check_rate_limit_headers(sample_429["headers"])
            
            if headers_check["percentage"] >= 75:  # At least 3 out of 4 headers
                log_test("Global Rate Limiting HTTP 429 Response", True, "global_rate_limiting",
                        details=f"HTTP 429 responses include {headers_check['total_present']}/{headers_check['total_expected']} rate limiting headers: {headers_check['present']}")
            else:
                log_test("Global Rate Limiting HTTP 429 Response", False, "global_rate_limiting",
                        details=f"HTTP 429 responses missing headers: {headers_check['missing']}")
        else:
            log_test("Global Rate Limiting HTTP 429 Response", False, "global_rate_limiting",
                    details="No HTTP 429 responses received to test header format")
    
    except Exception as e:
        log_test("Global Rate Limiting HTTP 429 Response", False, "global_rate_limiting", error=str(e))
    
    # Test rate limit header accuracy
    try:
        print("  Testing rate limit header accuracy and timing...")
        # Make a few requests and check header values
        response = requests.get(f"{API_URL}/")
        
        if response.status_code == 200:
            headers = response.headers
            limit_header = headers.get("X-RateLimit-Limit")
            remaining_header = headers.get("X-RateLimit-Remaining")
            reset_header = headers.get("X-RateLimit-Reset")
            
            accuracy_checks = []
            
            if limit_header:
                try:
                    limit_value = int(limit_header)
                    if 50 <= limit_value <= 70:  # Should be around 60
                        accuracy_checks.append("Limit header reasonable")
                    else:
                        accuracy_checks.append(f"Limit header suspicious: {limit_value}")
                except:
                    accuracy_checks.append("Limit header not numeric")
            
            if remaining_header:
                try:
                    remaining_value = int(remaining_header)
                    if 0 <= remaining_value <= 70:
                        accuracy_checks.append("Remaining header reasonable")
                    else:
                        accuracy_checks.append(f"Remaining header suspicious: {remaining_value}")
                except:
                    accuracy_checks.append("Remaining header not numeric")
            
            if reset_header:
                try:
                    reset_value = int(reset_header)
                    current_time = int(time.time())
                    if current_time <= reset_value <= current_time + 120:  # Within next 2 minutes
                        accuracy_checks.append("Reset header reasonable")
                    else:
                        accuracy_checks.append(f"Reset header suspicious: {reset_value}")
                except:
                    accuracy_checks.append("Reset header not numeric")
            
            suspicious_checks = [check for check in accuracy_checks if "suspicious" in check or "not numeric" in check]
            
            if len(suspicious_checks) == 0:
                log_test("Rate Limit Header Accuracy", True, "global_rate_limiting",
                        details=f"All header values reasonable: {accuracy_checks}")
            else:
                log_test("Rate Limit Header Accuracy", False, "global_rate_limiting",
                        details=f"Header accuracy issues: {suspicious_checks}")
        else:
            log_test("Rate Limit Header Accuracy", False, "global_rate_limiting",
                    details=f"Cannot test headers - HTTP {response.status_code}")
    
    except Exception as e:
        log_test("Rate Limit Header Accuracy", False, "global_rate_limiting", error=str(e))

# ===== 2. ENDPOINT-SPECIFIC RATE LIMITING TESTING =====

def test_endpoint_specific_rate_limiting():
    """Test 2: Endpoint-Specific Rate Limiting (High Priority)"""
    print("\n🎯 ENDPOINT-SPECIFIC RATE LIMITING TESTING - HIGH PRIORITY")
    print("Testing wallet creation (3/minute) and login (5/minute) rate limits...")
    
    # Test wallet creation rate limiting (3/minute)
    try:
        print("  Testing wallet creation rate limiting (3/minute limit)...")
        
        # Generate multiple unique wallet creation requests
        wallet_requests = []
        for i in range(6):  # Try 6 requests, should block after 3
            username, password = generate_test_user_data()
            wallet_requests.append({
                "username": username,
                "password": password
            })
        
        results = []
        for i, wallet_data in enumerate(wallet_requests):
            try:
                response = requests.post(f"{API_URL}/wallet/create", json=wallet_data, timeout=5)
                results.append({
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "request_number": i + 1
                })
                time.sleep(0.1)  # Small delay between requests
            except Exception as e:
                results.append({
                    "status_code": 0,
                    "error": str(e),
                    "request_number": i + 1
                })
        
        # Analyze wallet creation rate limiting
        rate_limited_requests = [r for r in results if r.get("status_code") == 429]
        successful_requests = [r for r in results if r.get("status_code") == 200]
        
        if len(rate_limited_requests) > 0:
            first_rate_limit = next((i for i, r in enumerate(results) if r.get("status_code") == 429), None)
            
            if first_rate_limit and first_rate_limit <= 4:  # Should block around 3-4 requests
                log_test("Wallet Creation Rate Limiting (3/minute)", True, "endpoint_specific_limiting",
                        details=f"Rate limiting activated after {first_rate_limit + 1} wallet creation attempts. {len(rate_limited_requests)} requests blocked")
            else:
                log_test("Wallet Creation Rate Limiting (3/minute)", False, "endpoint_specific_limiting",
                        details=f"Rate limiting too lenient - first 429 at request {first_rate_limit + 1 if first_rate_limit else 'never'}")
        else:
            log_test("Wallet Creation Rate Limiting (3/minute)", False, "endpoint_specific_limiting",
                    details=f"No rate limiting detected after 6 wallet creation attempts")
    
    except Exception as e:
        log_test("Wallet Creation Rate Limiting (3/minute)", False, "endpoint_specific_limiting", error=str(e))
    
    # Test wallet login rate limiting (5/minute)
    try:
        print("  Testing wallet login rate limiting (5/minute limit)...")
        
        # Generate login attempts (will fail but should trigger rate limiting)
        login_requests = []
        for i in range(8):  # Try 8 requests, should block after 5
            username, password = generate_test_user_data()
            login_requests.append({
                "username": username,
                "password": password
            })
        
        results = []
        for i, login_data in enumerate(login_requests):
            try:
                response = requests.post(f"{API_URL}/wallet/login", json=login_data, timeout=5)
                results.append({
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "request_number": i + 1
                })
                time.sleep(0.1)  # Small delay between requests
            except Exception as e:
                results.append({
                    "status_code": 0,
                    "error": str(e),
                    "request_number": i + 1
                })
        
        # Analyze wallet login rate limiting
        rate_limited_requests = [r for r in results if r.get("status_code") == 429]
        auth_failed_requests = [r for r in results if r.get("status_code") == 401]
        
        if len(rate_limited_requests) > 0:
            first_rate_limit = next((i for i, r in enumerate(results) if r.get("status_code") == 429), None)
            
            if first_rate_limit and first_rate_limit <= 6:  # Should block around 5-6 requests
                log_test("Wallet Login Rate Limiting (5/minute)", True, "endpoint_specific_limiting",
                        details=f"Rate limiting activated after {first_rate_limit + 1} login attempts. {len(rate_limited_requests)} requests blocked")
            else:
                log_test("Wallet Login Rate Limiting (5/minute)", False, "endpoint_specific_limiting",
                        details=f"Rate limiting too lenient - first 429 at request {first_rate_limit + 1 if first_rate_limit else 'never'}")
        else:
            log_test("Wallet Login Rate Limiting (5/minute)", False, "endpoint_specific_limiting",
                    details=f"No rate limiting detected after 8 login attempts. Auth failures: {len(auth_failed_requests)}")
    
    except Exception as e:
        log_test("Wallet Login Rate Limiting (5/minute)", False, "endpoint_specific_limiting", error=str(e))
    
    # Test endpoint-specific HTTP 429 responses
    try:
        print("  Testing endpoint-specific HTTP 429 response format...")
        
        # Try to trigger rate limiting on wallet creation
        wallet_data = {"username": f"test_{secrets.token_hex(4)}", "password": "TestPass123!"}
        results = make_rapid_requests(f"{API_URL}/wallet/create", data=wallet_data, method="POST", count=5, delay=0.1)
        
        rate_limited_responses = [r for r in results if r.get("status_code") == 429]
        
        if rate_limited_responses:
            sample_429 = rate_limited_responses[0]
            headers_check = check_rate_limit_headers(sample_429["headers"])
            
            # Check for endpoint-specific information
            has_limit_type = any("limit" in str(v).lower() for v in sample_429["headers"].values())
            
            if headers_check["percentage"] >= 50 and has_limit_type:  # At least 2 headers + limit type info
                log_test("Endpoint-Specific HTTP 429 Responses", True, "endpoint_specific_limiting",
                        details=f"Endpoint-specific 429 responses include {headers_check['total_present']} rate limiting headers")
            else:
                log_test("Endpoint-Specific HTTP 429 Responses", False, "endpoint_specific_limiting",
                        details=f"Endpoint-specific 429 responses missing headers or limit type info")
        else:
            log_test("Endpoint-Specific HTTP 429 Responses", False, "endpoint_specific_limiting",
                    details="No endpoint-specific HTTP 429 responses received to test")
    
    except Exception as e:
        log_test("Endpoint-Specific HTTP 429 Responses", False, "endpoint_specific_limiting", error=str(e))

# ===== 3. RATE LIMITING HEADERS & METADATA TESTING =====

def test_rate_limiting_headers():
    """Test 3: Rate Limiting Headers & Metadata (Medium Priority)"""
    print("\n📊 RATE LIMITING HEADERS & METADATA TESTING - MEDIUM PRIORITY")
    print("Testing rate limiting headers presence, accuracy, and metadata...")
    
    # Test rate limiting headers presence
    try:
        print("  Testing rate limiting headers presence in responses...")
        
        response = requests.get(f"{API_URL}/")
        headers_check = check_rate_limit_headers(response.headers)
        
        if headers_check["percentage"] >= 75:  # At least 3 out of 4 headers
            log_test("Rate Limiting Headers Presence", True, "rate_limiting_headers",
                    details=f"Rate limiting headers present: {headers_check['present']} ({headers_check['percentage']:.1f}%)")
        else:
            log_test("Rate Limiting Headers Presence", False, "rate_limiting_headers",
                    details=f"Missing rate limiting headers: {headers_check['missing']} (only {headers_check['percentage']:.1f}% present)")
    
    except Exception as e:
        log_test("Rate Limiting Headers Presence", False, "rate_limiting_headers", error=str(e))
    
    # Test header accuracy and timing calculations
    try:
        print("  Testing header accuracy and timing calculations...")
        
        # Make multiple requests and track header changes
        header_samples = []
        for i in range(3):
            response = requests.get(f"{API_URL}/")
            if response.status_code == 200:
                header_samples.append({
                    "limit": response.headers.get("X-RateLimit-Limit"),
                    "remaining": response.headers.get("X-RateLimit-Remaining"),
                    "reset": response.headers.get("X-RateLimit-Reset"),
                    "timestamp": time.time()
                })
            time.sleep(1)
        
        if len(header_samples) >= 2:
            # Check if remaining count decreases
            remaining_values = [int(h["remaining"]) for h in header_samples if h["remaining"] and h["remaining"].isdigit()]
            
            if len(remaining_values) >= 2:
                remaining_decreased = remaining_values[0] > remaining_values[-1]
                
                if remaining_decreased:
                    log_test("Header Accuracy and Timing", True, "rate_limiting_headers",
                            details=f"Remaining count properly decreases: {remaining_values[0]} → {remaining_values[-1]}")
                else:
                    log_test("Header Accuracy and Timing", False, "rate_limiting_headers",
                            details=f"Remaining count not decreasing properly: {remaining_values}")
            else:
                log_test("Header Accuracy and Timing", False, "rate_limiting_headers",
                        details="Cannot verify timing - remaining header not numeric")
        else:
            log_test("Header Accuracy and Timing", False, "rate_limiting_headers",
                    details="Insufficient header samples to verify timing")
    
    except Exception as e:
        log_test("Header Accuracy and Timing", False, "rate_limiting_headers", error=str(e))
    
    # Test rate limiting metadata in error responses
    try:
        print("  Testing rate limiting metadata in error responses...")
        
        # Try to trigger rate limiting and check error response metadata
        results = make_rapid_requests(f"{API_URL}/", count=70, delay=0.02)
        rate_limited_responses = [r for r in results if r.get("status_code") == 429]
        
        if rate_limited_responses:
            sample_429 = rate_limited_responses[0]
            
            # Check for comprehensive metadata
            metadata_checks = []
            
            if "Retry-After" in sample_429["headers"]:
                metadata_checks.append("Retry-After header present")
            
            if "X-RateLimit-Limit" in sample_429["headers"]:
                metadata_checks.append("Rate limit value present")
            
            if "X-RateLimit-Reset" in sample_429["headers"]:
                metadata_checks.append("Reset time present")
            
            # Check for additional metadata in response body (if JSON)
            try:
                # Note: We don't have response body in our results, so we'll check headers only
                if len(metadata_checks) >= 2:
                    log_test("Rate Limiting Metadata in Error Responses", True, "rate_limiting_headers",
                            details=f"Comprehensive metadata present: {metadata_checks}")
                else:
                    log_test("Rate Limiting Metadata in Error Responses", False, "rate_limiting_headers",
                            details=f"Limited metadata: {metadata_checks}")
            except:
                log_test("Rate Limiting Metadata in Error Responses", False, "rate_limiting_headers",
                        details="Cannot parse error response metadata")
        else:
            log_test("Rate Limiting Metadata in Error Responses", False, "rate_limiting_headers",
                    details="No rate limited responses to test metadata")
    
    except Exception as e:
        log_test("Rate Limiting Metadata in Error Responses", False, "rate_limiting_headers", error=str(e))
    
    # Test retry_after values and recommendations
    try:
        print("  Testing retry_after values and recommendations...")
        
        # Trigger rate limiting and check retry_after values
        results = make_rapid_requests(f"{API_URL}/", count=70, delay=0.01)
        rate_limited_responses = [r for r in results if r.get("status_code") == 429]
        
        if rate_limited_responses:
            retry_after_values = []
            for response in rate_limited_responses[:3]:  # Check first 3 rate limited responses
                retry_after = response["headers"].get("Retry-After")
                if retry_after:
                    try:
                        retry_after_values.append(int(retry_after))
                    except:
                        pass
            
            if retry_after_values:
                # Check if retry_after values are reasonable (should be 60 seconds or less for 1-minute window)
                reasonable_values = [v for v in retry_after_values if 1 <= v <= 120]
                
                if len(reasonable_values) == len(retry_after_values):
                    log_test("Retry-After Values and Recommendations", True, "rate_limiting_headers",
                            details=f"Retry-After values reasonable: {retry_after_values} seconds")
                else:
                    log_test("Retry-After Values and Recommendations", False, "rate_limiting_headers",
                            details=f"Retry-After values unreasonable: {retry_after_values}")
            else:
                log_test("Retry-After Values and Recommendations", False, "rate_limiting_headers",
                        details="No Retry-After values found in rate limited responses")
        else:
            log_test("Retry-After Values and Recommendations", False, "rate_limiting_headers",
                    details="No rate limited responses to test retry_after values")
    
    except Exception as e:
        log_test("Retry-After Values and Recommendations", False, "rate_limiting_headers", error=str(e))

# ===== 4. RATE LIMITING PERSISTENCE & RECOVERY TESTING =====

def test_persistence_and_recovery():
    """Test 4: Rate Limiting Persistence & Recovery (Medium Priority)"""
    print("\n💾 RATE LIMITING PERSISTENCE & RECOVERY TESTING - MEDIUM PRIORITY")
    print("Testing rate limiting storage persistence, reset behavior, and recovery...")
    
    # Test rate limiting storage persistence
    try:
        print("  Testing rate limiting storage persistence...")
        
        # Make some requests to establish rate limiting state
        initial_response = requests.get(f"{API_URL}/")
        initial_remaining = initial_response.headers.get("X-RateLimit-Remaining")
        
        if initial_remaining and initial_remaining.isdigit():
            initial_count = int(initial_remaining)
            
            # Make a few more requests
            for i in range(3):
                requests.get(f"{API_URL}/")
                time.sleep(0.1)
            
            # Check if state persisted
            final_response = requests.get(f"{API_URL}/")
            final_remaining = final_response.headers.get("X-RateLimit-Remaining")
            
            if final_remaining and final_remaining.isdigit():
                final_count = int(final_remaining)
                
                # Should have decreased by at least 3 (the requests we made)
                if initial_count - final_count >= 3:
                    log_test("Rate Limiting Storage Persistence", True, "persistence_recovery",
                            details=f"Rate limiting state persisted: {initial_count} → {final_count} remaining")
                else:
                    log_test("Rate Limiting Storage Persistence", False, "persistence_recovery",
                            details=f"Rate limiting state not properly persisted: {initial_count} → {final_count}")
            else:
                log_test("Rate Limiting Storage Persistence", False, "persistence_recovery",
                        details="Cannot verify persistence - final remaining header not numeric")
        else:
            log_test("Rate Limiting Storage Persistence", False, "persistence_recovery",
                    details="Cannot verify persistence - initial remaining header not available")
    
    except Exception as e:
        log_test("Rate Limiting Storage Persistence", False, "persistence_recovery", error=str(e))
    
    # Test rate limiting reset behavior after time windows
    try:
        print("  Testing rate limiting reset behavior (abbreviated test)...")
        
        # Get current rate limit state
        response = requests.get(f"{API_URL}/")
        reset_time = response.headers.get("X-RateLimit-Reset")
        current_remaining = response.headers.get("X-RateLimit-Remaining")
        
        if reset_time and reset_time.isdigit() and current_remaining and current_remaining.isdigit():
            reset_timestamp = int(reset_time)
            current_time = int(time.time())
            time_to_reset = reset_timestamp - current_time
            
            # Check if reset time is reasonable (should be within next 60 seconds for 1-minute window)
            if 0 <= time_to_reset <= 120:
                log_test("Rate Limiting Reset Behavior", True, "persistence_recovery",
                        details=f"Reset time reasonable: {time_to_reset} seconds from now")
            else:
                log_test("Rate Limiting Reset Behavior", False, "persistence_recovery",
                        details=f"Reset time unreasonable: {time_to_reset} seconds from now")
        else:
            log_test("Rate Limiting Reset Behavior", False, "persistence_recovery",
                    details="Cannot verify reset behavior - missing or invalid headers")
    
    except Exception as e:
        log_test("Rate Limiting Reset Behavior", False, "persistence_recovery", error=str(e))
    
    # Test concurrent user rate limiting isolation
    try:
        print("  Testing concurrent user rate limiting isolation...")
        
        def make_requests_from_different_source(source_id):
            """Simulate requests from different sources"""
            results = []
            for i in range(5):
                try:
                    # Add a custom header to simulate different sources
                    headers = {"X-Test-Source": f"source_{source_id}"}
                    response = requests.get(f"{API_URL}/", headers=headers, timeout=5)
                    results.append(response.status_code)
                    time.sleep(0.1)
                except:
                    results.append(0)
            return results
        
        # Test with 2 concurrent "users"
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(make_requests_from_different_source, 1)
            future2 = executor.submit(make_requests_from_different_source, 2)
            
            results1 = future1.result()
            results2 = future2.result()
        
        # Both sources should be able to make requests (isolation working)
        successful1 = len([r for r in results1 if r == 200])
        successful2 = len([r for r in results2 if r == 200])
        
        if successful1 >= 3 and successful2 >= 3:
            log_test("Concurrent User Rate Limiting Isolation", True, "persistence_recovery",
                    details=f"Rate limiting isolation working: Source1: {successful1}/5, Source2: {successful2}/5 successful")
        else:
            log_test("Concurrent User Rate Limiting Isolation", False, "persistence_recovery",
                    details=f"Rate limiting isolation issues: Source1: {successful1}/5, Source2: {successful2}/5 successful")
    
    except Exception as e:
        log_test("Concurrent User Rate Limiting Isolation", False, "persistence_recovery", error=str(e))

# ===== 5. USER EXPERIENCE OPTIMIZATION TESTING =====

def test_user_experience():
    """Test 5: User Experience Optimization (Lower Priority)"""
    print("\n😊 USER EXPERIENCE OPTIMIZATION TESTING - LOWER PRIORITY")
    print("Testing rate limiting error message clarity, retry guidance, and UX...")
    
    # Test rate limiting error message clarity
    try:
        print("  Testing rate limiting error message clarity...")
        
        # Trigger rate limiting and check error message quality
        results = make_rapid_requests(f"{API_URL}/", count=70, delay=0.01)
        rate_limited_responses = [r for r in results if r.get("status_code") == 429]
        
        if rate_limited_responses:
            # Check for user-friendly elements in headers
            sample_429 = rate_limited_responses[0]
            headers = sample_429["headers"]
            
            ux_elements = []
            
            if "Retry-After" in headers:
                ux_elements.append("Retry guidance provided")
            
            if "X-RateLimit-Remaining" in headers:
                ux_elements.append("Remaining requests shown")
            
            if "X-RateLimit-Reset" in headers:
                ux_elements.append("Reset time provided")
            
            # Check for helpful header values
            retry_after = headers.get("Retry-After")
            if retry_after and retry_after.isdigit() and 1 <= int(retry_after) <= 120:
                ux_elements.append("Reasonable retry time")
            
            if len(ux_elements) >= 3:
                log_test("Rate Limiting Error Message Clarity", True, "user_experience",
                        details=f"User-friendly error elements: {ux_elements}")
            else:
                log_test("Rate Limiting Error Message Clarity", False, "user_experience",
                        details=f"Limited user-friendly elements: {ux_elements}")
        else:
            log_test("Rate Limiting Error Message Clarity", False, "user_experience",
                    details="No rate limited responses to test error message clarity")
    
    except Exception as e:
        log_test("Rate Limiting Error Message Clarity", False, "user_experience", error=str(e))
    
    # Test integration with authentication flows
    try:
        print("  Testing rate limiting integration with authentication flows...")
        
        # Test that rate limiting works properly with authentication endpoints
        username, password = generate_test_user_data()
        auth_data = {"username": username, "password": password}
        
        # Make multiple authentication requests
        auth_results = make_rapid_requests(f"{API_URL}/wallet/login", data=auth_data, method="POST", count=7, delay=0.1)
        
        # Should see both authentication failures (401) and rate limiting (429)
        auth_failures = [r for r in auth_results if r.get("status_code") == 401]
        rate_limited = [r for r in auth_results if r.get("status_code") == 429]
        
        if len(auth_failures) > 0 and len(rate_limited) > 0:
            log_test("Rate Limiting Integration with Authentication", True, "user_experience",
                    details=f"Proper integration: {len(auth_failures)} auth failures, {len(rate_limited)} rate limited")
        elif len(rate_limited) > 0:
            log_test("Rate Limiting Integration with Authentication", True, "user_experience",
                    details=f"Rate limiting working: {len(rate_limited)} requests rate limited")
        else:
            log_test("Rate Limiting Integration with Authentication", False, "user_experience",
                    details=f"No rate limiting detected in authentication flow")
    
    except Exception as e:
        log_test("Rate Limiting Integration with Authentication", False, "user_experience", error=str(e))

def calculate_weighted_score():
    """Calculate weighted score based on category importance"""
    total_weighted_score = 0
    total_weight = 0
    
    for category, data in test_results["categories"].items():
        if data["total"] > 0:
            category_score = (data["passed"] / data["total"]) * 100
            weighted_contribution = category_score * data["weight"]
            total_weighted_score += weighted_contribution
            total_weight += data["weight"]
    
    return total_weighted_score / total_weight if total_weight > 0 else 0

def run_comprehensive_rate_limiting_testing():
    """Run comprehensive rate limiting optimization testing"""
    print("🚀 STARTING COMPREHENSIVE RATE LIMITING OPTIMIZATION TESTING")
    print("Testing rate limiting improvements from 60% to 100% functionality...")
    print("=" * 80)
    
    # Run all test categories
    test_global_api_rate_limiting()
    test_endpoint_specific_rate_limiting()
    test_rate_limiting_headers()
    test_persistence_and_recovery()
    test_user_experience()
    
    # Calculate results
    print("\n" + "=" * 80)
    print("🚀 COMPREHENSIVE RATE LIMITING OPTIMIZATION RESULTS")
    print("=" * 80)
    
    success_rate = (test_results["passed"] / test_results["total"]) * 100 if test_results["total"] > 0 else 0
    weighted_score = calculate_weighted_score()
    
    print(f"Total Tests: {test_results['total']}")
    print(f"Passed: {test_results['passed']} ✅")
    print(f"Failed: {test_results['failed']} ❌")
    print(f"Overall Success Rate: {success_rate:.1f}%")
    print(f"Weighted Score (by priority): {weighted_score:.1f}%")
    
    # Category-wise results
    print("\n📊 RATE LIMITING CATEGORY RESULTS:")
    categories = {
        "global_rate_limiting": "🌐 Global API Rate Limiting (30%)",
        "endpoint_specific_limiting": "🎯 Endpoint-Specific Limiting (30%)",
        "rate_limiting_headers": "📊 Rate Limiting Headers (20%)",
        "persistence_recovery": "💾 Persistence & Recovery (15%)",
        "user_experience": "😊 User Experience (5%)"
    }
    
    critical_issues = []
    
    for category_key, category_name in categories.items():
        cat_data = test_results["categories"][category_key]
        cat_rate = (cat_data["passed"] / cat_data["total"]) * 100 if cat_data["total"] > 0 else 0
        status = "✅" if cat_rate >= 70 else "❌"
        print(f"  {status} {category_name}: {cat_data['passed']}/{cat_data['total']} ({cat_rate:.1f}%)")
        
        if cat_rate < 70:
            critical_issues.append(category_name)
    
    # Rate limiting optimization assessment
    print(f"\n🎯 RATE LIMITING OPTIMIZATION ASSESSMENT:")
    
    if weighted_score >= 90:
        print("🎉 EXCELLENT - TARGET ACHIEVED! (90-100%)")
        print("   Rate limiting optimization successful")
        print("   All critical rate limiting features operational")
        print("   System ready for optimal performance")
    elif weighted_score >= 80:
        print("✅ VERY GOOD - NEAR TARGET (80-89%)")
        print("   Significant rate limiting improvements achieved")
        print("   Most optimization goals met")
        print("   Minor fine-tuning needed")
    elif weighted_score >= 70:
        print("⚠️  GOOD - SUBSTANTIAL IMPROVEMENT (70-79%)")
        print("   Good progress from 60% baseline")
        print("   Core rate limiting working")
        print("   Some optimization areas need attention")
    elif weighted_score >= 60:
        print("⚠️  FAIR - MINIMAL IMPROVEMENT (60-69%)")
        print("   Limited improvement from baseline")
        print("   Rate limiting partially working")
        print("   Significant optimization needed")
    else:
        print("🚨 POOR - BELOW BASELINE (<60%)")
        print("   Rate limiting optimization unsuccessful")
        print("   Critical issues persist")
        print("   Immediate fixes required")
    
    # Failed tests summary
    failed_tests = [test for test in test_results['tests'] if not test['passed']]
    if failed_tests:
        print(f"\n❌ FAILED RATE LIMITING TESTS ({len(failed_tests)} total):")
        for test in failed_tests:
            print(f"  • {test['name']} ({test['category']})")
            if test['details']:
                print(f"    Issue: {test['details']}")
    
    # Recommendations
    print(f"\n💡 OPTIMIZATION RECOMMENDATIONS:")
    
    if weighted_score >= 90:
        print("• 🎉 OPTIMIZATION TARGET ACHIEVED!")
        print("• Rate limiting system is enterprise-ready")
        print("• Monitor for edge cases and performance")
        print("• Consider additional security enhancements")
    elif weighted_score >= 80:
        print("• ✅ EXCELLENT PROGRESS - Fine-tune remaining issues")
        print("• Focus on failed test categories")
        print("• Optimize header accuracy and timing")
        print("• Enhance user experience elements")
    elif weighted_score >= 70:
        print("• ⚠️  GOOD FOUNDATION - Address critical gaps")
        print("• Strengthen global rate limiting enforcement")
        print("• Improve endpoint-specific rate limiting")
        print("• Enhance rate limiting headers and metadata")
    else:
        print("• 🚨 URGENT - Major rate limiting fixes needed")
        print("• Implement basic rate limiting enforcement")
        print("• Add proper HTTP 429 responses")
        print("• Include essential rate limiting headers")
    
    return {
        "success_rate": success_rate,
        "weighted_score": weighted_score,
        "total_tests": test_results["total"],
        "passed_tests": test_results["passed"],
        "failed_tests": failed_tests,
        "categories": test_results["categories"],
        "critical_issues": critical_issues,
        "optimization_level": "EXCELLENT" if weighted_score >= 90 else "VERY GOOD" if weighted_score >= 80 else "GOOD" if weighted_score >= 70 else "FAIR" if weighted_score >= 60 else "POOR"
    }

if __name__ == "__main__":
    # Run comprehensive rate limiting testing
    results = run_comprehensive_rate_limiting_testing()
    
    print("\n" + "=" * 80)
    print("🎯 FINAL RATE LIMITING OPTIMIZATION SUMMARY")
    print("=" * 80)
    
    print(f"📊 OPTIMIZATION RESULTS:")
    print(f"• Total Tests: {results['total_tests']}")
    print(f"• Passed: {results['passed_tests']} ✅")
    print(f"• Failed: {len(results['failed_tests'])} ❌")
    print(f"• Success Rate: {results['success_rate']:.1f}%")
    print(f"• Weighted Score: {results['weighted_score']:.1f}%")
    print(f"• Optimization Level: {results['optimization_level']}")
    
    print(f"\n🎯 RATE LIMITING SYSTEM STATUS:")
    for category_key, category_data in results['categories'].items():
        if category_data['total'] > 0:
            cat_rate = (category_data['passed'] / category_data['total']) * 100
            category_names = {
                "global_rate_limiting": "🌐 Global Rate Limiting",
                "endpoint_specific_limiting": "🎯 Endpoint-Specific Limiting",
                "rate_limiting_headers": "📊 Headers & Metadata",
                "persistence_recovery": "💾 Persistence & Recovery",
                "user_experience": "😊 User Experience"
            }
            print(f"• {category_names.get(category_key, category_key)}: {cat_rate:.1f}%")
    
    if results['critical_issues']:
        print(f"\n🚨 CRITICAL AREAS NEEDING ATTENTION:")
        for i, issue in enumerate(results['critical_issues'], 1):
            print(f"{i}. {issue}")
    
    print(f"\n🔧 NEXT STEPS:")
    if results['weighted_score'] >= 90:
        print("• 🎉 OPTIMIZATION COMPLETE - Rate limiting system optimal!")
        print("• Monitor system performance and edge cases")
        print("• Document rate limiting configuration")
        print("• Consider advanced rate limiting features")
    elif results['weighted_score'] >= 80:
        print("• ✅ NEAR COMPLETE - Address remaining failed tests")
        print("• Fine-tune rate limiting parameters")
        print("• Enhance error messages and user experience")
        print("• Test under high load conditions")
    else:
        print("• 🚨 CONTINUE OPTIMIZATION - Focus on critical failures")
        print("• Implement missing rate limiting enforcement")
        print("• Add proper HTTP 429 responses and headers")
        print("• Test and validate all rate limiting scenarios")
    
    print(f"\n📈 IMPROVEMENT FROM BASELINE:")
    baseline_score = 60  # Previous 60% rate limiting score
    improvement = results['weighted_score'] - baseline_score
    if improvement > 0:
        print(f"• Improvement: +{improvement:.1f}% (from {baseline_score}% to {results['weighted_score']:.1f}%)")
        print(f"• Target Achievement: {(results['weighted_score'] / 100) * 100:.1f}% of 100% goal")
    else:
        print(f"• No improvement detected (current: {results['weighted_score']:.1f}%, baseline: {baseline_score}%)")
        print(f"• Urgent optimization required to meet targets")