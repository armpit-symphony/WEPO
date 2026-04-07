#!/usr/bin/env python3
"""
Comprehensive Step 2 Testing with Rate Limiting Awareness
"""

import requests
import time
import json
from pathlib import Path

OUTPUT_PATH = Path(__file__).resolve().parent / "legacy" / "step2-results" / "comprehensive_step2_results.json"

def load_backend_url():
    frontend_env = Path("/app/frontend/.env")
    with frontend_env.open("r") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"\'')
    return None

def test_with_delay(api_base, test_name, username, password, expected_blocked=True):
    """Test a single payload with proper delay and error handling"""
    print(f"\n🧪 Testing {test_name}")
    print(f"   Username: {username}")
    
    try:
        response = requests.post(
            f"{api_base}/wallet/create",
            json={"username": username, "password": password},
            timeout=15
        )
        
        print(f"   Status: HTTP {response.status_code}")
        
        if response.status_code == 400:
            try:
                resp_json = response.json()
                detail = resp_json.get('detail', 'No detail')
                print(f"   Detail: {detail}")
                
                # Check if it's a proper validation error vs generic error
                if 'Username' in detail and 'password' in detail:
                    print(f"   ⚠️ Generic error - payload may have been sanitized")
                    return "sanitized"
                else:
                    print(f"   ✅ Properly blocked with validation error")
                    return "blocked"
            except:
                print(f"   ✅ Blocked (non-JSON response)")
                return "blocked"
                
        elif response.status_code == 429:
            print(f"   ⚠️ Rate limited - cannot determine blocking")
            return "rate_limited"
        elif response.status_code == 200:
            print(f"   ❌ Payload NOT blocked - wallet created!")
            return "not_blocked"
        else:
            print(f"   ❓ Unexpected status: {response.status_code}")
            return "unknown"
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return "error"

def main():
    backend_url = load_backend_url()
    if not backend_url:
        print("❌ Could not load backend URL")
        return
    
    api_base = f"{backend_url}/api"
    print(f"🎯 Comprehensive Step 2 Post-Fix Testing")
    print(f"Backend: {api_base}")
    print("=" * 80)
    
    results = {
        "timestamp": int(time.time()),
        "backend_url": api_base,
        "tests": []
    }
    
    # Test cases with longer delays between each
    test_cases = [
        # Weak passwords (should be blocked)
        {"name": "Weak Password - 123456", "username": f"user_{int(time.time())}", "password": "123456", "type": "weak_password"},
        {"name": "Weak Password - password", "username": f"user_{int(time.time())}", "password": "password", "type": "weak_password"},
        
        # XSS payloads (should be blocked or sanitized)
        {"name": "XSS - Script Tag", "username": "<script>alert('xss')</script>", "password": "ValidPass123!", "type": "xss"},
        {"name": "XSS - JavaScript URL", "username": "javascript:alert('xss')", "password": "ValidPass123!", "type": "xss"},
        
        # SQL Injection (should be blocked or sanitized)
        {"name": "SQL Injection - DROP TABLE", "username": "'; DROP TABLE users; --", "password": "ValidPass123!", "type": "sql_injection"},
        {"name": "NoSQL Injection - OR condition", "username": "' OR '1'='1", "password": "ValidPass123!", "type": "nosql_injection"},
        
        # Path Traversal (should be blocked or sanitized)
        {"name": "Path Traversal - Unix", "username": "../../../etc/passwd", "password": "ValidPass123!", "type": "path_traversal"},
    ]
    
    for i, test_case in enumerate(test_cases):
        print(f"\n--- Test {i+1}/{len(test_cases)} ---")
        
        result = test_with_delay(
            api_base, 
            test_case["name"], 
            test_case["username"], 
            test_case["password"]
        )
        
        test_case["result"] = result
        results["tests"].append(test_case)
        
        # Wait between tests to avoid rate limiting
        if i < len(test_cases) - 1:  # Don't wait after last test
            print(f"   ⏳ Waiting 45 seconds to avoid rate limiting...")
            time.sleep(45)
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 COMPREHENSIVE STEP 2 TEST RESULTS")
    
    categories = {
        "weak_password": [],
        "xss": [],
        "sql_injection": [],
        "nosql_injection": [],
        "path_traversal": []
    }
    
    for test in results["tests"]:
        categories[test["type"]].append(test)
    
    for category, tests in categories.items():
        if tests:
            blocked_count = sum(1 for t in tests if t["result"] in ["blocked", "sanitized"])
            total_count = len([t for t in tests if t["result"] != "rate_limited"])
            print(f"\n{category.replace('_', ' ').title()}: {blocked_count}/{total_count} properly handled")
            
            for test in tests:
                status_icon = {
                    "blocked": "✅",
                    "sanitized": "⚠️",
                    "not_blocked": "❌",
                    "rate_limited": "⏸️",
                    "error": "❌",
                    "unknown": "❓"
                }.get(test["result"], "❓")
                print(f"  {status_icon} {test['name']}: {test['result']}")
    
    # Overall assessment
    print(f"\n🎯 STEP 2 POST-FIX OVERALL ASSESSMENT:")
    
    total_security_tests = len([t for t in results["tests"] if t["type"] != "weak_password"])
    blocked_security_tests = len([t for t in results["tests"] if t["type"] != "weak_password" and t["result"] in ["blocked", "sanitized"]])
    
    weak_pwd_tests = len([t for t in results["tests"] if t["type"] == "weak_password"])
    blocked_weak_pwd = len([t for t in results["tests"] if t["type"] == "weak_password" and t["result"] == "blocked"])
    
    print(f"Password Strength Validation: {blocked_weak_pwd}/{weak_pwd_tests} weak passwords rejected")
    print(f"Input Validation Security: {blocked_security_tests}/{total_security_tests} malicious payloads handled")
    
    if blocked_weak_pwd >= weak_pwd_tests and blocked_security_tests >= total_security_tests * 0.8:
        print("✅ EXCELLENT - Strong input validation across all categories")
    elif blocked_weak_pwd >= weak_pwd_tests * 0.8 and blocked_security_tests >= total_security_tests * 0.6:
        print("⚠️ GOOD - Most input validation working properly")
    elif blocked_security_tests >= total_security_tests * 0.4:
        print("⚠️ PARTIAL - Some input validation working")
    else:
        print("❌ POOR - Input validation needs significant improvement")
    
    # Save results
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w") as f:
        json.dump(results, f, indent=2)
    print(f"\n📝 Detailed results saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
