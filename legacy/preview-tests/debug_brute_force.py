#!/usr/bin/env python3
"""
Debug brute force protection issue
"""

import requests
import json
import time
import secrets

# Use preview backend URL from frontend/.env
BACKEND_URL = "https://blockchain-sectest.preview.emergentagent.com"
API_URL = f"{BACKEND_URL}/api"

def debug_brute_force():
    """Debug the brute force protection step by step"""
    print("🔍 DEBUGGING BRUTE FORCE PROTECTION")
    
    # Create test wallet
    username = f"debugtest_{secrets.token_hex(4)}"
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
    
    # Test failed login attempts one by one
    wrong_password = "WrongPassword123!"
    
    for attempt in range(1, 8):  # Test up to 7 attempts
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
            print("❌ Failed login (expected for first 5)")
        else:
            print(f"⚠️ Unexpected status code: {response.status_code}")
        
        time.sleep(0.5)  # Small delay between attempts

if __name__ == "__main__":
    debug_brute_force()