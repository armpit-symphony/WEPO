#!/usr/bin/env python3
"""
Test brute force protection locally
"""

import requests
import json
import time
import secrets

# Test locally
API_URL = "http://localhost:8003/api"

def test_local():
    """Test locally to see debug logs"""
    print("🔍 TESTING LOCALLY")
    
    # Create test wallet
    username = f"localtest_{secrets.token_hex(4)}"
    password = f"TestPass123!{secrets.token_hex(2)}"
    
    create_data = {
        "username": username,
        "password": password
    }
    
    print(f"Creating test wallet: {username}")
    response = requests.post(f"{API_URL}/wallet/create", json=create_data)
    if response.status_code != 200:
        print(f"Failed to create wallet: {response.status_code} - {response.text}")
        return
    
    print("✅ Wallet created successfully")
    
    # Test 6 failed login attempts
    wrong_password = "WrongPassword123!"
    
    for attempt in range(1, 7):  # Test up to 6 attempts
        print(f"\n--- Attempt {attempt} ---")
        
        login_data = {
            "username": username,
            "password": wrong_password
        }
        
        response = requests.post(f"{API_URL}/wallet/login", json=login_data)
        print(f"Status Code: {response.status_code}")
        
        try:
            response_data = response.json()
            print(f"Response: {json.dumps(response_data, indent=2)}")
        except:
            print(f"Response (text): {response.text}")
        
        if response.status_code == 423:
            print("🔒 Account locked!")
            break
        elif response.status_code == 401:
            print("❌ Failed login")
        else:
            print(f"⚠️ Unexpected status code: {response.status_code}")
        
        time.sleep(0.5)

if __name__ == "__main__":
    test_local()