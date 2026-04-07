#!/usr/bin/env python3
"""
Focused Step 2 Post-Fix Testing
- Weak password rejection at /api/wallet/create
- XSS/injection/path traversal blocking
- Rate limiting interference monitoring
"""

import requests
import time
import json
from pathlib import Path

OUTPUT_PATH = Path(__file__).resolve().parent / "legacy" / "step2-results" / "step2_test_results.json"

# Load backend URL
def load_backend_url():
    frontend_env = Path("/app/frontend/.env")
    with frontend_env.open("r") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"\'')
    return None

def test_weak_password_rejection(api_base):
    """Test if weak passwords are properly rejected at /api/wallet/create"""
    print("\n🔐 Testing Weak Password Rejection at /api/wallet/create")
    
    weak_passwords = [
        "123456",
        "password", 
        "abc123",
        "qwerty",
        "12345678"
    ]
    
    results = []
    for i, weak_pwd in enumerate(weak_passwords):
        try:
            username = f"testuser_{i}_{int(time.time())}"
            response = requests.post(
                f"{api_base}/wallet/create",
                json={"username": username, "password": weak_pwd},
                timeout=10
            )
            
            if response.status_code == 400:
                print(f"✅ Weak password '{weak_pwd}' properly rejected (HTTP 400)")
                results.append({"password": weak_pwd, "rejected": True, "status": 400})
            elif response.status_code == 429:
                print(f"⚠️ Rate limited while testing '{weak_pwd}' (HTTP 429)")
                results.append({"password": weak_pwd, "rejected": "rate_limited", "status": 429})
                time.sleep(2)  # Wait before next attempt
            else:
                print(f"❌ Weak password '{weak_pwd}' NOT rejected (HTTP {response.status_code})")
                results.append({"password": weak_pwd, "rejected": False, "status": response.status_code})
                
        except Exception as e:
            print(f"❌ Error testing password '{weak_pwd}': {e}")
            results.append({"password": weak_pwd, "rejected": "error", "error": str(e)})
            
        time.sleep(1)  # Avoid rate limiting
    
    return results

def test_xss_injection_protection(api_base):
    """Test XSS and injection protection"""
    print("\n🛡️ Testing XSS/Injection/Path Traversal Protection")
    
    test_payloads = [
        # XSS payloads
        {"type": "XSS", "payload": "<script>alert('xss')</script>"},
        {"type": "XSS", "payload": "javascript:alert('xss')"},
        {"type": "XSS", "payload": "<img src=x onerror=alert('xss')>"},
        
        # SQL/NoSQL Injection
        {"type": "SQL_Injection", "payload": "'; DROP TABLE users; --"},
        {"type": "NoSQL_Injection", "payload": "' OR '1'='1"},
        {"type": "NoSQL_Injection", "payload": "{$ne: null}"},
        
        # Path Traversal
        {"type": "Path_Traversal", "payload": "../../../etc/passwd"},
        {"type": "Path_Traversal", "payload": "..\\..\\..\\windows\\system32\\config\\sam"}
    ]
    
    results = []
    for i, test in enumerate(test_payloads):
        try:
            username = test["payload"]
            password = "ValidPassword123!"
            
            response = requests.post(
                f"{api_base}/wallet/create",
                json={"username": username, "password": password},
                timeout=10
            )
            
            if response.status_code == 400:
                print(f"✅ {test['type']} payload blocked (HTTP 400)")
                results.append({**test, "blocked": True, "status": 400})
            elif response.status_code == 429:
                print(f"⚠️ Rate limited while testing {test['type']} (HTTP 429)")
                results.append({**test, "blocked": "rate_limited", "status": 429})
                time.sleep(3)  # Longer wait for rate limiting
            else:
                print(f"❌ {test['type']} payload NOT blocked (HTTP {response.status_code})")
                results.append({**test, "blocked": False, "status": response.status_code})
                
        except Exception as e:
            print(f"❌ Error testing {test['type']}: {e}")
            results.append({**test, "blocked": "error", "error": str(e)})
            
        time.sleep(2)  # Avoid rate limiting
    
    return results

def test_rate_limiting_behavior(api_base):
    """Monitor rate limiting behavior"""
    print("\n⚡ Testing Rate Limiting Behavior")
    
    print("Testing global rate limiting...")
    rate_limit_hit = False
    requests_made = 0
    
    for i in range(20):  # Reduced from 65 to avoid excessive load
        try:
            response = requests.get(f"{api_base}/", timeout=5)
            requests_made += 1
            
            if response.status_code == 429:
                print(f"✅ Rate limiting active - HTTP 429 after {requests_made} requests")
                print(f"   Headers: {dict(response.headers)}")
                rate_limit_hit = True
                break
            elif i % 5 == 0:
                print(f"   Request {requests_made}: HTTP {response.status_code}")
                
            time.sleep(0.1)  # Small delay between requests
            
        except Exception as e:
            print(f"❌ Error during rate limit test: {e}")
            break
    
    if not rate_limit_hit:
        print(f"⚠️ No rate limiting observed after {requests_made} requests")
    
    return {"rate_limit_hit": rate_limit_hit, "requests_made": requests_made}

def main():
    backend_url = load_backend_url()
    if not backend_url:
        print("❌ Could not load backend URL from frontend/.env")
        return
    
    api_base = f"{backend_url}/api"
    print(f"🎯 Focused Step 2 Post-Fix Testing")
    print(f"Backend: {api_base}")
    print("=" * 80)
    
    # Test results storage
    test_results = {
        "timestamp": int(time.time()),
        "backend_url": api_base,
        "weak_password_results": [],
        "xss_injection_results": [],
        "rate_limiting_results": {}
    }
    
    # Run tests with delays to avoid rate limiting
    try:
        test_results["weak_password_results"] = test_weak_password_rejection(api_base)
        time.sleep(5)  # Wait between test categories
        
        test_results["xss_injection_results"] = test_xss_injection_protection(api_base)
        time.sleep(5)  # Wait between test categories
        
        test_results["rate_limiting_results"] = test_rate_limiting_behavior(api_base)
        
    except Exception as e:
        print(f"❌ Test execution error: {e}")
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 STEP 2 POST-FIX TEST SUMMARY")
    
    # Weak password summary
    weak_pwd_rejected = sum(1 for r in test_results["weak_password_results"] if r.get("rejected") == True)
    weak_pwd_total = len([r for r in test_results["weak_password_results"] if r.get("rejected") != "rate_limited"])
    print(f"🔐 Weak Password Rejection: {weak_pwd_rejected}/{weak_pwd_total} properly rejected")
    
    # XSS/Injection summary
    blocked_count = sum(1 for r in test_results["xss_injection_results"] if r.get("blocked") == True)
    total_payloads = len([r for r in test_results["xss_injection_results"] if r.get("blocked") != "rate_limited"])
    print(f"🛡️ XSS/Injection/Path Traversal: {blocked_count}/{total_payloads} payloads blocked")
    
    # Rate limiting summary
    rate_limit_active = test_results["rate_limiting_results"].get("rate_limit_hit", False)
    print(f"⚡ Rate Limiting: {'Active' if rate_limit_active else 'Not observed'}")
    
    # Overall assessment
    print(f"\n🎯 STEP 2 POST-FIX ASSESSMENT:")
    if weak_pwd_rejected >= 3 and blocked_count >= 4:
        print("✅ GOOD - Input validation working well")
    elif weak_pwd_rejected >= 2 or blocked_count >= 2:
        print("⚠️ PARTIAL - Some input validation working")
    else:
        print("❌ POOR - Input validation needs improvement")
    
    # Save detailed results
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w") as f:
        json.dump(test_results, f, indent=2)
    print(f"\n📝 Detailed results saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
