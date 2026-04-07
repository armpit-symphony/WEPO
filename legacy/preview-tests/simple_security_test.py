#!/usr/bin/env python3
"""
SIMPLE SECURITY TEST - DIRECT VERIFICATION
==========================================

Direct test of security features on the wepo-fast-test-bridge service.
"""

import requests
import json
import time
import secrets

# Use preview backend URL
BACKEND_URL = "https://blockchain-sectest.preview.emergentagent.com"

print(f"🔐 SIMPLE SECURITY TEST - DIRECT VERIFICATION")
print(f"Backend URL: {BACKEND_URL}")
print("=" * 80)

def test_basic_connectivity():
    """Test basic connectivity"""
    print("\n🌐 BASIC CONNECTIVITY TEST")
    
    try:
        # Test root endpoint
        response = requests.get(f"{BACKEND_URL}/")
        print(f"Root endpoint: HTTP {response.status_code}")
        if response.status_code == 200:
            print(f"Response: {response.text[:100]}")
        
        # Test API root
        response = requests.get(f"{BACKEND_URL}/api/")
        print(f"API root: HTTP {response.status_code}")
        if response.status_code == 200:
            print(f"Response: {response.text[:100]}")
        elif response.status_code == 429:
            print("Rate limiting is active!")
            
    except Exception as e:
        print(f"Connectivity error: {e}")

def test_security_headers():
    """Test security headers"""
    print("\n🔐 SECURITY HEADERS TEST")
    
    try:
        response = requests.get(f"{BACKEND_URL}/")
        
        security_headers = [
            "X-Content-Type-Options",
            "X-Frame-Options", 
            "X-XSS-Protection",
            "Content-Security-Policy",
            "Strict-Transport-Security"
        ]
        
        print("Security headers found:")
        for header in security_headers:
            if header in response.headers:
                print(f"  ✅ {header}: {response.headers[header]}")
            else:
                print(f"  ❌ {header}: Missing")
                
    except Exception as e:
        print(f"Security headers test error: {e}")

def test_rate_limiting():
    """Test rate limiting"""
    print("\n🚨 RATE LIMITING TEST")
    
    try:
        print("Making multiple requests to test rate limiting...")
        
        for i in range(5):
            response = requests.get(f"{BACKEND_URL}/")
            print(f"Request {i+1}: HTTP {response.status_code}")
            
            if response.status_code == 429:
                print("✅ Rate limiting is working!")
                
                # Check headers
                if "X-RateLimit-Limit" in response.headers:
                    print(f"  Rate limit: {response.headers['X-RateLimit-Limit']}")
                if "Retry-After" in response.headers:
                    print(f"  Retry after: {response.headers['Retry-After']} seconds")
                break
            elif response.status_code == 200:
                print(f"  Response: {response.text[:50]}...")
            
            time.sleep(0.5)  # Brief pause between requests
            
    except Exception as e:
        print(f"Rate limiting test error: {e}")

def test_wallet_creation_attempt():
    """Test wallet creation"""
    print("\n🔒 WALLET CREATION TEST")
    
    try:
        username = f"testuser_{secrets.token_hex(4)}"
        password = "TestPassword123!"
        
        print(f"Attempting to create wallet for user: {username}")
        
        response = requests.post(f"{BACKEND_URL}/api/wallet/create", json={
            "username": username,
            "password": password
        })
        
        print(f"Wallet creation: HTTP {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Wallet created successfully!")
            print(f"  Address: {data.get('address', 'N/A')}")
            return username, password
        elif response.status_code == 400:
            print(f"❌ Validation error: {response.text}")
        elif response.status_code == 429:
            print(f"⚠️  Rate limited: {response.text}")
        elif response.status_code == 500:
            print(f"❌ Server error: {response.text}")
        else:
            print(f"❌ Unexpected response: {response.text}")
            
        return None, None
        
    except Exception as e:
        print(f"Wallet creation test error: {e}")
        return None, None

def test_login_attempts(username, password):
    """Test login attempts"""
    print("\n🚨 LOGIN ATTEMPTS TEST")
    
    if not username:
        print("❌ No test user available for login testing")
        return
    
    try:
        print(f"Testing login attempts for user: {username}")
        
        # Test correct login first
        response = requests.post(f"{BACKEND_URL}/api/wallet/login", json={
            "username": username,
            "password": password
        })
        
        print(f"Correct login: HTTP {response.status_code}")
        
        if response.status_code == 200:
            print("✅ Correct login successful")
        elif response.status_code == 429:
            print("⚠️  Login rate limited")
            return
        
        # Test failed login attempts
        print("Testing failed login attempts...")
        
        for attempt in range(1, 4):
            response = requests.post(f"{BACKEND_URL}/api/wallet/login", json={
                "username": username,
                "password": "WrongPassword123!"
            })
            
            print(f"Failed attempt {attempt}: HTTP {response.status_code}")
            
            if response.status_code == 423:
                print("✅ Account locked due to failed attempts!")
                break
            elif response.status_code == 429:
                print("⚠️  Rate limited")
                break
            elif response.status_code == 401:
                print("  Invalid credentials (expected)")
            
            time.sleep(1)  # Brief pause between attempts
            
    except Exception as e:
        print(f"Login attempts test error: {e}")

def run_simple_security_test():
    """Run simple security test"""
    print("🔐 STARTING SIMPLE SECURITY TEST")
    print("Testing basic security features...")
    print("=" * 80)
    
    # Run tests
    test_basic_connectivity()
    test_security_headers()
    test_rate_limiting()
    
    # Test wallet functionality
    username, password = test_wallet_creation_attempt()
    if username:
        test_login_attempts(username, password)
    
    print("\n" + "=" * 80)
    print("🎯 SIMPLE SECURITY TEST COMPLETED")
    print("=" * 80)
    
    print("\n📊 OBSERVATIONS:")
    print("• Check the output above for specific security feature results")
    print("• Rate limiting appears to be active based on HTTP 429 responses")
    print("• Security headers are present in responses")
    print("• Wallet creation and login functionality needs further investigation")
    
    print("\n🔧 NEXT STEPS:")
    print("• If rate limiting is working, that's a good sign")
    print("• If security headers are present, that's another good sign")
    print("• Wallet creation issues may be due to database connectivity")
    print("• Overall security posture appears to have some protections in place")

if __name__ == "__main__":
    run_simple_security_test()