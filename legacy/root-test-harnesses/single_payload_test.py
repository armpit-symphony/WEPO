#!/usr/bin/env python3
"""
Single payload test to avoid rate limiting interference
"""

import requests
import time
from pathlib import Path

def load_backend_url():
    frontend_env = Path("/app/frontend/.env")
    with frontend_env.open("r") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"\'')
    return None

def test_single_xss_payload(api_base):
    """Test a single XSS payload"""
    print("🛡️ Testing Single XSS Payload")
    
    try:
        username = "<script>alert('xss')</script>"
        password = "ValidPassword123!"
        
        response = requests.post(
            f"{api_base}/wallet/create",
            json={"username": username, "password": password},
            timeout=10
        )
        
        print(f"Response Status: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        if response.status_code == 400:
            print("✅ XSS payload properly blocked (HTTP 400)")
            try:
                resp_json = response.json()
                print(f"Response body: {resp_json}")
            except:
                print(f"Response text: {response.text}")
        elif response.status_code == 429:
            print("⚠️ Rate limited (HTTP 429)")
        else:
            print(f"❌ XSS payload NOT blocked (HTTP {response.status_code})")
            try:
                resp_json = response.json()
                print(f"Response body: {resp_json}")
            except:
                print(f"Response text: {response.text}")
                
    except Exception as e:
        print(f"❌ Error: {e}")

def main():
    backend_url = load_backend_url()
    if not backend_url:
        print("❌ Could not load backend URL")
        return
    
    api_base = f"{backend_url}/api"
    print(f"Testing single payload against: {api_base}")
    
    test_single_xss_payload(api_base)

if __name__ == "__main__":
    main()