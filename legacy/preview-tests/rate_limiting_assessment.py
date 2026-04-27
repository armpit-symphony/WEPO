#!/usr/bin/env python3
"""
WEPO RATE LIMITING OPTIMIZATION STATUS CHECK - DETERMINE CURRENT BASELINE

**REVIEW REQUEST FOCUS:**
Determine the current rate limiting optimization status after implementation issues.
Conduct focused rate limiting assessment to understand current baseline performance.

**CURRENT STATUS UNCERTAINTY:**
- Implemented TrueOptimizedRateLimiter class with advanced features
- Encountered integration challenges with middleware
- Basic functionality may have been affected during optimization attempts
- Need to establish current working baseline before further optimization

**FOCUSED RATE LIMITING ASSESSMENT:**

**1. BASIC FUNCTIONALITY VERIFICATION (Priority 1)**
- Test if basic API endpoints are working (GET /api/)
- Test if wallet creation/login endpoints are functional
- Identify any blocking issues preventing normal operation

**2. CURRENT RATE LIMITING STATUS (Priority 2)**
- Test current global API rate limiting functionality
- Test current endpoint-specific rate limiting (if any)
- Verify current rate limiting headers presence and accuracy
- Assess current enforcement level

**3. OPTIMIZATION IMPACT ASSESSMENT (Priority 3)**  
- Compare current performance vs baseline 60% score
- Identify specific areas where optimization was successful
- Identify areas still needing improvement
- Measure improvement percentage

**4. SPECIFIC RATE LIMITING METRICS**
- Global rate limiting: Test 60/minute enforcement
- Wallet creation: Test 3/minute endpoint limit
- Wallet login: Test 5/minute endpoint limit
- Headers: X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset presence

**TARGET ASSESSMENT:**
- Determine if we achieved any improvement from 60% baseline
- Identify remaining gaps to reach 90-100% optimization
- Provide specific recommendations for completion
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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Use preview backend URL from frontend/.env
BACKEND_URL = "http://127.0.0.1:18021"
API_URL = f"{BACKEND_URL}/api"

print(f"🎯 WEPO RATE LIMITING OPTIMIZATION STATUS CHECK")
print(f"Preview Backend API URL: {API_URL}")
print(f"Focus: Determine Current Baseline Performance")
print("=" * 80)

# Test results tracking
assessment_results = {
    "basic_functionality": {"passed": 0, "total": 0, "score": 0.0},
    "rate_limiting_status": {"passed": 0, "total": 0, "score": 0.0},
    "optimization_impact": {"passed": 0, "total": 0, "score": 0.0},
    "specific_metrics": {"passed": 0, "total": 0, "score": 0.0},
    "overall_score": 0.0,
    "baseline_comparison": "unknown",
    "tests": []
}

def log_assessment(name, passed, category, details=None, error=None, score_impact=0.0):
    """Log assessment results with scoring"""
    status = "✅ PASSED" if passed else "❌ FAILED"
    print(f"{status} {name}")
    
    if details:
        print(f"  Details: {details}")
    
    if error:
        print(f"  Error: {error}")
    
    assessment_results[category]["total"] += 1
    if passed:
        assessment_results[category]["passed"] += 1
        assessment_results[category]["score"] += score_impact
    
    assessment_results["tests"].append({
        "name": name,
        "category": category,
        "passed": passed,
        "error": error,
        "details": details,
        "score_impact": score_impact
    })

def generate_test_user_data():
    """Generate realistic test user data"""
    username = f"testuser_{secrets.token_hex(4)}"
    password = f"TestPass123!{secrets.token_hex(2)}"
    return username, password

def make_concurrent_requests(url, count, data=None, method="GET"):
    """Make concurrent requests to test rate limiting"""
    results = []
    
    def make_request():
        try:
            if method == "POST":
                response = requests.post(url, json=data, timeout=10)
            else:
                response = requests.get(url, timeout=10)
            return {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "response_time": response.elapsed.total_seconds(),
                "content": response.text[:200] if response.status_code != 200 else "OK"
            }
        except Exception as e:
            return {
                "status_code": 0,
                "headers": {},
                "response_time": 0,
                "error": str(e)
            }
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(make_request) for _ in range(count)]
        for future in as_completed(futures):
            results.append(future.result())
    
    return results

# ===== 1. BASIC FUNCTIONALITY VERIFICATION (Priority 1) =====

def test_basic_functionality():
    """Priority 1: Basic Functionality Verification"""
    print("\n🔧 BASIC FUNCTIONALITY VERIFICATION (Priority 1)")
    print("Testing if basic API endpoints are working...")
    
    # Test 1.1: Basic API Root Endpoint
    try:
        response = requests.get(f"{API_URL}/", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("message") and "WEPO" in data.get("message", ""):
                log_assessment("Basic API Root Endpoint", True, "basic_functionality",
                             details=f"API accessible - {data.get('message', 'No message')}", score_impact=25.0)
            else:
                log_assessment("Basic API Root Endpoint", False, "basic_functionality",
                             details="API response missing expected WEPO message")
        else:
            log_assessment("Basic API Root Endpoint", False, "basic_functionality",
                         details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_assessment("Basic API Root Endpoint", False, "basic_functionality", error=str(e))
    
    # Test 1.2: Wallet Creation Endpoint Functionality
    try:
        username, password = generate_test_user_data()
        create_data = {
            "username": username,
            "password": password
        }
        
        response = requests.post(f"{API_URL}/wallet/create", json=create_data, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success") and data.get("address"):
                log_assessment("Wallet Creation Endpoint Functionality", True, "basic_functionality",
                             details="Wallet creation working - Basic functionality operational", score_impact=25.0)
            else:
                log_assessment("Wallet Creation Endpoint Functionality", False, "basic_functionality",
                             details="Wallet creation response invalid")
        elif response.status_code in [400, 429]:
            log_assessment("Wallet Creation Endpoint Functionality", True, "basic_functionality",
                         details="Wallet endpoint responding with validation/rate limiting", score_impact=25.0)
        else:
            log_assessment("Wallet Creation Endpoint Functionality", False, "basic_functionality",
                         details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_assessment("Wallet Creation Endpoint Functionality", False, "basic_functionality", error=str(e))
    
    # Test 1.3: Wallet Login Endpoint Functionality
    try:
        login_data = {
            "username": "testuser",
            "password": "testpass"
        }
        
        response = requests.post(f"{API_URL}/wallet/login", json=login_data, timeout=10)
        
        if response.status_code in [200, 401, 400, 429]:
            log_assessment("Wallet Login Endpoint Functionality", True, "basic_functionality",
                         details=f"Login endpoint responding properly - HTTP {response.status_code}", score_impact=25.0)
        elif response.status_code == 500:
            log_assessment("Wallet Login Endpoint Functionality", False, "basic_functionality",
                         details="Internal server error - Basic functionality compromised")
        else:
            log_assessment("Wallet Login Endpoint Functionality", False, "basic_functionality",
                         details=f"Unexpected response: HTTP {response.status_code}")
    except Exception as e:
        log_assessment("Wallet Login Endpoint Functionality", False, "basic_functionality", error=str(e))
    
    # Test 1.4: Network Status Endpoint
    try:
        response = requests.get(f"{API_URL}/network/status", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict) and "block_height" in data:
                log_assessment("Network Status Endpoint Functionality", True, "basic_functionality",
                             details=f"Network status accessible - Block height: {data.get('block_height', 0)}", score_impact=25.0)
            else:
                log_assessment("Network Status Endpoint Functionality", False, "basic_functionality",
                             details=f"Unexpected data format: {type(data)}")
        else:
            log_assessment("Network Status Endpoint Functionality", False, "basic_functionality",
                         details=f"HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        log_assessment("Network Status Endpoint Functionality", False, "basic_functionality", error=str(e))

# ===== 2. CURRENT RATE LIMITING STATUS (Priority 2) =====

def test_current_rate_limiting_status():
    """Priority 2: Current Rate Limiting Status"""
    print("\n⏱️ CURRENT RATE LIMITING STATUS (Priority 2)")
    print("Testing current rate limiting functionality and enforcement...")
    
    # Test 2.1: Global API Rate Limiting (60/minute)
    try:
        print("  Testing global API rate limiting (60/minute)...")
        results = make_concurrent_requests(f"{API_URL}/", 65)  # Test beyond 60/minute
        
        success_count = len([r for r in results if r["status_code"] == 200])
        rate_limited_count = len([r for r in results if r["status_code"] == 429])
        
        if rate_limited_count > 0:
            log_assessment("Global API Rate Limiting Enforcement", True, "rate_limiting_status",
                         details=f"Rate limiting active - {success_count} success, {rate_limited_count} rate limited", score_impact=30.0)
        else:
            log_assessment("Global API Rate Limiting Enforcement", False, "rate_limiting_status",
                         details=f"No rate limiting detected - {success_count} requests succeeded")
        
        # Check for rate limiting headers in successful responses
        headers_present = []
        for result in results[:5]:  # Check first 5 responses
            if result["status_code"] == 200:
                headers = result["headers"]
                if "X-RateLimit-Limit" in headers:
                    headers_present.append("X-RateLimit-Limit")
                if "X-RateLimit-Remaining" in headers:
                    headers_present.append("X-RateLimit-Remaining")
                if "X-RateLimit-Reset" in headers:
                    headers_present.append("X-RateLimit-Reset")
                break
        
        if headers_present:
            log_assessment("Global Rate Limiting Headers", True, "rate_limiting_status",
                         details=f"Headers present: {headers_present}", score_impact=20.0)
        else:
            log_assessment("Global Rate Limiting Headers", False, "rate_limiting_status",
                         details="No rate limiting headers detected in responses")
            
    except Exception as e:
        log_assessment("Global API Rate Limiting Test", False, "rate_limiting_status", error=str(e))
    
    # Test 2.2: Wallet Creation Rate Limiting (3/minute)
    try:
        print("  Testing wallet creation rate limiting (3/minute)...")
        
        # Make 5 wallet creation requests quickly
        wallet_requests = []
        for i in range(5):
            username, password = generate_test_user_data()
            create_data = {
                "username": f"{username}_{i}",
                "password": password
            }
            wallet_requests.append(create_data)
        
        results = make_concurrent_requests(f"{API_URL}/wallet/create", 5, wallet_requests[0], "POST")
        
        success_count = len([r for r in results if r["status_code"] == 200])
        rate_limited_count = len([r for r in results if r["status_code"] == 429])
        
        if rate_limited_count > 0:
            log_assessment("Wallet Creation Rate Limiting", True, "rate_limiting_status",
                         details=f"Endpoint-specific rate limiting active - {rate_limited_count} blocked", score_impact=25.0)
        else:
            log_assessment("Wallet Creation Rate Limiting", False, "rate_limiting_status",
                         details=f"No endpoint-specific rate limiting - {success_count} requests succeeded")
            
    except Exception as e:
        log_assessment("Wallet Creation Rate Limiting", False, "rate_limiting_status", error=str(e))
    
    # Test 2.3: Wallet Login Rate Limiting (5/minute)
    try:
        print("  Testing wallet login rate limiting (5/minute)...")
        
        login_data = {
            "username": "testuser",
            "password": "wrongpassword"
        }
        
        results = make_concurrent_requests(f"{API_URL}/wallet/login", 7, login_data, "POST")
        
        success_count = len([r for r in results if r["status_code"] in [200, 401]])
        rate_limited_count = len([r for r in results if r["status_code"] == 429])
        
        if rate_limited_count > 0:
            log_assessment("Wallet Login Rate Limiting", True, "rate_limiting_status",
                         details=f"Login rate limiting active - {rate_limited_count} blocked", score_impact=25.0)
        else:
            log_assessment("Wallet Login Rate Limiting", False, "rate_limiting_status",
                         details=f"No login rate limiting - {success_count} requests processed")
            
    except Exception as e:
        log_assessment("Wallet Login Rate Limiting", False, "rate_limiting_status", error=str(e))

# ===== 3. OPTIMIZATION IMPACT ASSESSMENT (Priority 3) =====

def test_optimization_impact():
    """Priority 3: Optimization Impact Assessment"""
    print("\n📊 OPTIMIZATION IMPACT ASSESSMENT (Priority 3)")
    print("Comparing current performance vs baseline 60% score...")
    
    # Test 3.1: Rate Limiting Headers Quality
    try:
        response = requests.get(f"{API_URL}/", timeout=10)
        headers = response.headers
        
        expected_headers = ["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset", "Retry-After"]
        present_headers = [h for h in expected_headers if h in headers]
        
        header_score = (len(present_headers) / len(expected_headers)) * 100
        
        if header_score >= 75:
            log_assessment("Rate Limiting Headers Quality", True, "optimization_impact",
                         details=f"Excellent header implementation - {len(present_headers)}/4 headers", score_impact=25.0)
        elif header_score >= 50:
            log_assessment("Rate Limiting Headers Quality", True, "optimization_impact",
                         details=f"Good header implementation - {len(present_headers)}/4 headers", score_impact=15.0)
        else:
            log_assessment("Rate Limiting Headers Quality", False, "optimization_impact",
                         details=f"Poor header implementation - {len(present_headers)}/4 headers")
            
    except Exception as e:
        log_assessment("Rate Limiting Headers Quality", False, "optimization_impact", error=str(e))
    
    # Test 3.2: Error Response Quality
    try:
        # Try to trigger a rate limit response
        results = make_concurrent_requests(f"{API_URL}/", 70)
        
        rate_limited_responses = [r for r in results if r["status_code"] == 429]
        
        if rate_limited_responses:
            # Check quality of rate limit error response
            sample_response = rate_limited_responses[0]
            headers = sample_response["headers"]
            
            quality_indicators = []
            if "Retry-After" in headers:
                quality_indicators.append("Retry-After header")
            if "X-RateLimit-Reset" in headers:
                quality_indicators.append("Reset time")
            if "rate limit" in sample_response.get("content", "").lower():
                quality_indicators.append("Clear error message")
            
            if len(quality_indicators) >= 2:
                log_assessment("Rate Limit Error Response Quality", True, "optimization_impact",
                             details=f"High-quality error responses - {quality_indicators}", score_impact=25.0)
            else:
                log_assessment("Rate Limit Error Response Quality", False, "optimization_impact",
                             details=f"Basic error responses - {quality_indicators}")
        else:
            log_assessment("Rate Limit Error Response Quality", False, "optimization_impact",
                         details="Cannot assess - No rate limit responses triggered")
            
    except Exception as e:
        log_assessment("Rate Limit Error Response Quality", False, "optimization_impact", error=str(e))
    
    # Test 3.3: Performance Under Load
    try:
        print("  Testing performance under load...")
        start_time = time.time()
        results = make_concurrent_requests(f"{API_URL}/", 50)
        end_time = time.time()
        
        total_time = end_time - start_time
        avg_response_time = sum([r.get("response_time", 0) for r in results]) / len(results)
        success_rate = len([r for r in results if r["status_code"] == 200]) / len(results) * 100
        
        if avg_response_time < 1.0 and success_rate >= 80:
            log_assessment("Performance Under Load", True, "optimization_impact",
                         details=f"Good performance - Avg: {avg_response_time:.2f}s, Success: {success_rate:.1f}%", score_impact=25.0)
        elif avg_response_time < 2.0 and success_rate >= 60:
            log_assessment("Performance Under Load", True, "optimization_impact",
                         details=f"Acceptable performance - Avg: {avg_response_time:.2f}s, Success: {success_rate:.1f}%", score_impact=15.0)
        else:
            log_assessment("Performance Under Load", False, "optimization_impact",
                         details=f"Poor performance - Avg: {avg_response_time:.2f}s, Success: {success_rate:.1f}%")
            
    except Exception as e:
        log_assessment("Performance Under Load", False, "optimization_impact", error=str(e))
    
    # Test 3.4: Advanced Rate Limiting Features
    try:
        # Test for advanced features like different limits per endpoint
        wallet_response = requests.post(f"{API_URL}/wallet/create", json={"username": "test", "password": "test"}, timeout=10)
        api_response = requests.get(f"{API_URL}/", timeout=10)
        
        wallet_headers = wallet_response.headers
        api_headers = api_response.headers
        
        advanced_features = []
        
        # Check for different rate limits
        wallet_limit = wallet_headers.get("X-RateLimit-Limit")
        api_limit = api_headers.get("X-RateLimit-Limit")
        
        if wallet_limit and api_limit and wallet_limit != api_limit:
            advanced_features.append("Endpoint-specific limits")
        
        # Check for rate limit type indicators
        if "X-RateLimit-Type" in wallet_headers or "X-RateLimit-Type" in api_headers:
            advanced_features.append("Rate limit type indicators")
        
        if len(advanced_features) > 0:
            log_assessment("Advanced Rate Limiting Features", True, "optimization_impact",
                         details=f"Advanced features detected: {advanced_features}", score_impact=25.0)
        else:
            log_assessment("Advanced Rate Limiting Features", False, "optimization_impact",
                         details="No advanced rate limiting features detected")
            
    except Exception as e:
        log_assessment("Advanced Rate Limiting Features", False, "optimization_impact", error=str(e))

# ===== 4. SPECIFIC RATE LIMITING METRICS =====

def test_specific_metrics():
    """Test specific rate limiting metrics"""
    print("\n📏 SPECIFIC RATE LIMITING METRICS")
    print("Testing specific rate limiting requirements...")
    
    # Test 4.1: Header Accuracy
    try:
        response = requests.get(f"{API_URL}/", timeout=10)
        headers = response.headers
        
        accuracy_checks = []
        
        # Check X-RateLimit-Limit
        if "X-RateLimit-Limit" in headers:
            limit_value = headers["X-RateLimit-Limit"]
            if limit_value.isdigit() and int(limit_value) > 0:
                accuracy_checks.append("Limit header valid")
            else:
                accuracy_checks.append("Limit header invalid")
        
        # Check X-RateLimit-Remaining
        if "X-RateLimit-Remaining" in headers:
            remaining_value = headers["X-RateLimit-Remaining"]
            if remaining_value.isdigit() and int(remaining_value) >= 0:
                accuracy_checks.append("Remaining header valid")
            else:
                accuracy_checks.append("Remaining header invalid")
        
        # Check X-RateLimit-Reset
        if "X-RateLimit-Reset" in headers:
            reset_value = headers["X-RateLimit-Reset"]
            if reset_value.isdigit() and int(reset_value) > int(time.time()):
                accuracy_checks.append("Reset header valid")
            else:
                accuracy_checks.append("Reset header invalid")
        
        valid_checks = [c for c in accuracy_checks if "valid" in c]
        
        if len(valid_checks) >= 2:
            log_assessment("Rate Limiting Header Accuracy", True, "specific_metrics",
                         details=f"Headers accurate - {valid_checks}", score_impact=25.0)
        else:
            log_assessment("Rate Limiting Header Accuracy", False, "specific_metrics",
                         details=f"Header accuracy issues - {accuracy_checks}")
            
    except Exception as e:
        log_assessment("Rate Limiting Header Accuracy", False, "specific_metrics", error=str(e))
    
    # Test 4.2: Enforcement Consistency
    try:
        print("  Testing enforcement consistency...")
        
        # Test multiple times to check consistency
        consistency_results = []
        
        for i in range(3):
            time.sleep(1)  # Brief pause between tests
            results = make_concurrent_requests(f"{API_URL}/", 65)
            rate_limited_count = len([r for r in results if r["status_code"] == 429])
            consistency_results.append(rate_limited_count > 0)
        
        consistent_enforcement = all(consistency_results) or not any(consistency_results)
        
        if consistent_enforcement:
            log_assessment("Rate Limiting Enforcement Consistency", True, "specific_metrics",
                         details=f"Consistent enforcement across tests", score_impact=25.0)
        else:
            log_assessment("Rate Limiting Enforcement Consistency", False, "specific_metrics",
                         details=f"Inconsistent enforcement - {consistency_results}")
            
    except Exception as e:
        log_assessment("Rate Limiting Enforcement Consistency", False, "specific_metrics", error=str(e))
    
    # Test 4.3: Reset Behavior
    try:
        print("  Testing rate limit reset behavior...")
        
        # Trigger rate limit
        results = make_concurrent_requests(f"{API_URL}/", 70)
        rate_limited_responses = [r for r in results if r["status_code"] == 429]
        
        if rate_limited_responses:
            # Check reset time
            reset_header = rate_limited_responses[0]["headers"].get("X-RateLimit-Reset")
            if reset_header:
                reset_time = int(reset_header)
                current_time = int(time.time())
                time_to_reset = reset_time - current_time
                
                if 0 < time_to_reset <= 60:  # Should reset within a minute
                    log_assessment("Rate Limit Reset Behavior", True, "specific_metrics",
                                 details=f"Proper reset time - {time_to_reset}s", score_impact=25.0)
                else:
                    log_assessment("Rate Limit Reset Behavior", False, "specific_metrics",
                                 details=f"Invalid reset time - {time_to_reset}s")
            else:
                log_assessment("Rate Limit Reset Behavior", False, "specific_metrics",
                             details="No reset header in rate limited response")
        else:
            log_assessment("Rate Limit Reset Behavior", False, "specific_metrics",
                         details="Cannot test reset - No rate limiting triggered")
            
    except Exception as e:
        log_assessment("Rate Limit Reset Behavior", False, "specific_metrics", error=str(e))
    
    # Test 4.4: User Experience Quality
    try:
        # Test for user-friendly error messages
        results = make_concurrent_requests(f"{API_URL}/", 70)
        rate_limited_responses = [r for r in results if r["status_code"] == 429]
        
        if rate_limited_responses:
            error_content = rate_limited_responses[0].get("content", "")
            
            ux_indicators = []
            if "rate limit" in error_content.lower():
                ux_indicators.append("Clear rate limit message")
            if "try again" in error_content.lower():
                ux_indicators.append("Retry guidance")
            if "minute" in error_content.lower() or "second" in error_content.lower():
                ux_indicators.append("Time guidance")
            
            if len(ux_indicators) >= 2:
                log_assessment("Rate Limiting User Experience", True, "specific_metrics",
                             details=f"Good UX - {ux_indicators}", score_impact=25.0)
            else:
                log_assessment("Rate Limiting User Experience", False, "specific_metrics",
                             details=f"Basic UX - {ux_indicators}")
        else:
            log_assessment("Rate Limiting User Experience", False, "specific_metrics",
                         details="Cannot assess UX - No rate limiting triggered")
            
    except Exception as e:
        log_assessment("Rate Limiting User Experience", False, "specific_metrics", error=str(e))

def calculate_overall_assessment():
    """Calculate overall assessment score and comparison"""
    
    # Calculate category scores
    for category in ["basic_functionality", "rate_limiting_status", "optimization_impact", "specific_metrics"]:
        if assessment_results[category]["total"] > 0:
            assessment_results[category]["score"] = (assessment_results[category]["score"] / 100.0) * 100
    
    # Calculate overall score (weighted)
    weights = {
        "basic_functionality": 0.25,  # 25% - Must work first
        "rate_limiting_status": 0.35,  # 35% - Core rate limiting
        "optimization_impact": 0.25,   # 25% - Optimization quality
        "specific_metrics": 0.15       # 15% - Specific requirements
    }
    
    overall_score = 0.0
    for category, weight in weights.items():
        category_score = assessment_results[category]["score"]
        overall_score += category_score * weight
    
    assessment_results["overall_score"] = overall_score
    
    # Determine baseline comparison
    baseline_score = 60.0  # Previous baseline was 60%
    
    if overall_score >= 90:
        assessment_results["baseline_comparison"] = "excellent_improvement"
    elif overall_score >= 75:
        assessment_results["baseline_comparison"] = "good_improvement"
    elif overall_score >= baseline_score:
        assessment_results["baseline_comparison"] = "some_improvement"
    else:
        assessment_results["baseline_comparison"] = "no_improvement"

def run_rate_limiting_assessment():
    """Run comprehensive rate limiting assessment"""
    print("🔍 STARTING WEPO RATE LIMITING OPTIMIZATION STATUS CHECK")
    print("Determining current baseline performance...")
    print("=" * 80)
    
    # Run assessment phases
    test_basic_functionality()
    test_current_rate_limiting_status()
    test_optimization_impact()
    test_specific_metrics()
    
    # Calculate overall assessment
    calculate_overall_assessment()
    
    # Print results
    print("\n" + "=" * 80)
    print("🎯 RATE LIMITING OPTIMIZATION STATUS ASSESSMENT")
    print("=" * 80)
    
    overall_score = assessment_results["overall_score"]
    baseline_comparison = assessment_results["baseline_comparison"]
    
    print(f"📊 OVERALL ASSESSMENT SCORE: {overall_score:.1f}%")
    
    # Category breakdown
    print(f"\n📋 CATEGORY BREAKDOWN:")
    categories = {
        "basic_functionality": "🔧 Basic Functionality",
        "rate_limiting_status": "⏱️ Rate Limiting Status", 
        "optimization_impact": "📊 Optimization Impact",
        "specific_metrics": "📏 Specific Metrics"
    }
    
    for category_key, category_name in categories.items():
        cat_data = assessment_results[category_key]
        cat_score = cat_data["score"]
        status = "✅" if cat_score >= 60 else "❌"
        print(f"  {status} {category_name}: {cat_data['passed']}/{cat_data['total']} ({cat_score:.1f}%)")
    
    # Baseline comparison
    print(f"\n📈 BASELINE COMPARISON (vs 60% baseline):")
    if baseline_comparison == "excellent_improvement":
        print("🎉 EXCELLENT IMPROVEMENT - Target 90-100% achieved!")
        print("   Rate limiting optimization highly successful")
    elif baseline_comparison == "good_improvement":
        print("✅ GOOD IMPROVEMENT - Significant progress made")
        print("   Rate limiting optimization substantially successful")
    elif baseline_comparison == "some_improvement":
        print("⚠️ SOME IMPROVEMENT - Progress made but more work needed")
        print("   Rate limiting optimization partially successful")
    else:
        print("🚨 NO IMPROVEMENT - Score below 60% baseline")
        print("   Rate limiting optimization unsuccessful")
    
    # Specific findings
    print(f"\n🔍 KEY FINDINGS:")
    
    # Basic functionality status
    basic_score = assessment_results["basic_functionality"]["score"]
    if basic_score >= 75:
        print("✅ Basic functionality is working well")
    elif basic_score >= 50:
        print("⚠️ Basic functionality has some issues")
    else:
        print("🚨 Basic functionality is compromised")
    
    # Rate limiting status
    rl_score = assessment_results["rate_limiting_status"]["score"]
    if rl_score >= 75:
        print("✅ Rate limiting is actively enforced")
    elif rl_score >= 50:
        print("⚠️ Rate limiting is partially working")
    else:
        print("🚨 Rate limiting is not working properly")
    
    # Optimization impact
    opt_score = assessment_results["optimization_impact"]["score"]
    if opt_score >= 75:
        print("✅ Optimization features are working well")
    elif opt_score >= 50:
        print("⚠️ Some optimization features are working")
    else:
        print("🚨 Optimization features need work")
    
    # Failed tests
    failed_tests = [test for test in assessment_results['tests'] if not test['passed']]
    if failed_tests:
        print(f"\n❌ AREAS NEEDING ATTENTION ({len(failed_tests)} issues):")
        for test in failed_tests[:5]:  # Show top 5 issues
            print(f"  • {test['name']}")
            if test['details']:
                print(f"    Issue: {test['details']}")
    
    # Recommendations
    print(f"\n💡 RECOMMENDATIONS:")
    if overall_score >= 90:
        print("• 🎉 EXCELLENT - Rate limiting optimization successful!")
        print("• System not approved for production use")
        print("• Monitor performance and fine-tune as needed")
    elif overall_score >= 75:
        print("• ✅ GOOD - Substantial progress made")
        print("• Address remaining failed tests")
        print("• System approaching production readiness")
    elif overall_score >= 60:
        print("• ⚠️ FAIR - Some improvement achieved")
        print("• Focus on critical failing areas")
        print("• Additional optimization work needed")
    else:
        print("• 🚨 POOR - Optimization unsuccessful")
        print("• Basic functionality may be compromised")
        print("• Immediate attention required")
    
    return {
        "overall_score": overall_score,
        "baseline_comparison": baseline_comparison,
        "category_scores": {k: v["score"] for k, v in assessment_results.items() if k not in ["overall_score", "baseline_comparison", "tests"]},
        "failed_tests": failed_tests,
        "total_tests": len(assessment_results["tests"]),
        "passed_tests": len([t for t in assessment_results["tests"] if t["passed"]])
    }

if __name__ == "__main__":
    # Run rate limiting assessment
    results = run_rate_limiting_assessment()
    
    print("\n" + "=" * 80)
    print("🎯 FINAL RATE LIMITING OPTIMIZATION STATUS")
    print("=" * 80)
    
    print(f"📊 CURRENT BASELINE: {results['overall_score']:.1f}%")
    print(f"📈 IMPROVEMENT STATUS: {results['baseline_comparison'].replace('_', ' ').title()}")
    print(f"🧪 TESTS: {results['passed_tests']}/{results['total_tests']} passed")
    
    print(f"\n🎯 NEXT STEPS:")
    if results['overall_score'] >= 90:
        print("• System has achieved excellent rate limiting optimization")
        print("• Ready for deployment review")
        print("• Continue monitoring and maintenance")
    elif results['overall_score'] >= 75:
        print("• System has good rate limiting optimization")
        print("• Address remaining issues for production readiness")
        print("• Focus on failed test areas")
    elif results['overall_score'] >= 60:
        print("• System shows some rate limiting improvement")
        print("• Significant additional work needed")
        print("• Focus on core rate limiting functionality")
    else:
        print("• System needs major rate limiting work")
        print("• Basic functionality may be compromised")
        print("• Consider reverting to stable baseline")
    
    print(f"\n🔧 PRIORITY ACTIONS:")
    if len(results['failed_tests']) > 0:
        print("• Address failed test areas:")
        for test in results['failed_tests'][:3]:
            print(f"  - {test['name']}")
    else:
        print("• All tests passing - system is optimized")
    
    print(f"\n📋 ASSESSMENT COMPLETE")
    print(f"Current rate limiting optimization level: {results['overall_score']:.1f}%")