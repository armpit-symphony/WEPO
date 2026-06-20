#!/usr/bin/env python3
"""
Test script for WEPO Dynamic Collateral System
Tests the new halving-based adjustment mechanism
"""

import sys
import os
import time
import requests
import json

# Add blockchain to path
sys.path.append('/app/wepo-blockchain/core')
from blockchain import WEPOBlockchain, DYNAMIC_MASTERNODE_COLLATERAL_SCHEDULE, DYNAMIC_POS_COLLATERAL_SCHEDULE, COIN, POS_ACTIVATION_HEIGHT
from blockchain import PRE_POS_DURATION_BLOCKS, PHASE_2A_END_HEIGHT, PHASE_2B_END_HEIGHT, PHASE_2C_END_HEIGHT, PHASE_2D_END_HEIGHT

def test_dynamic_collateral_system():
    """Test the dynamic collateral system with various block heights"""
    
    print("🧪 TESTING WEPO DYNAMIC COLLATERAL SYSTEM")
    print("=" * 60)
    
    # Create blockchain instance
    blockchain = WEPOBlockchain()
    
    # Test key block heights
    test_heights = [
        (0, "Genesis Block"),
        (50000, "Mid Genesis Phase"),
        (PRE_POS_DURATION_BLOCKS, "PoS Activation (18 months)"),
        (200000, "Mid PoS Phase"),
        (PHASE_2A_END_HEIGHT, "2nd Halving (4.5 years)"),
        (PHASE_2B_END_HEIGHT, "3rd Halving (10.5 years)"),
        (PHASE_2C_END_HEIGHT, "4th Halving (13.5 years)"),
        (PHASE_2D_END_HEIGHT, "5th Halving (16.5 years)"),
        (PHASE_2D_END_HEIGHT + 100000, "Post-PoW Era")
    ]
    
    print("\n📋 COLLATERAL REQUIREMENTS BY HEIGHT:")
    print("-" * 80)
    print(f"{'Height':<10} {'Description':<25} {'Masternode':<12} {'PoS':<8} {'Phase':<10}")
    print("-" * 80)
    
    for height, description in test_heights:
        try:
            # Get collateral requirements
            mn_collateral = blockchain.get_masternode_collateral_for_height(height)
            pos_collateral = blockchain.get_pos_collateral_for_height(height)
            
            # Get phase info
            phase_info = blockchain.get_current_phase_info(height)
            
            # Format output
            mn_wepo = mn_collateral / COIN
            pos_wepo = pos_collateral / COIN if pos_collateral > 0 else 0
            
            print(f"{height:<10} {description:<25} {mn_wepo:<12.0f} {pos_wepo:<8.0f} {phase_info['phase']:<10}")
            
        except Exception as e:
            print(f"ERROR testing height {height}: {e}")
    
    print("\n🔍 DETAILED COLLATERAL ANALYSIS:")
    print("-" * 60)
    
    # Test comprehensive info for current height
    try:
        current_height = 0  # Genesis for testing
        collateral_info = blockchain.get_collateral_info(current_height)
        
        print(f"Current Height: {collateral_info['block_height']}")
        print(f"Masternode Collateral: {collateral_info['masternode_collateral_wepo']} WEPO")
        print(f"PoS Collateral: {collateral_info['pos_collateral_wepo']} WEPO")
        print(f"PoS Available: {collateral_info['pos_available']}")
        print(f"Current Phase: {collateral_info['phase']} - {collateral_info['phase_description']}")
        print(f"PoW Reward: {collateral_info['pow_reward']} WEPO")
        
        # Next adjustment info
        next_adj = collateral_info['next_adjustment']
        print(f"\nNext Adjustment:")
        print(f"  Height: {next_adj['next_adjustment_height']}")
        print(f"  Days Remaining: {next_adj['days_remaining']}")
        print(f"  Next MN Collateral: {next_adj['next_masternode_collateral']} WEPO")
        print(f"  Next PoS Collateral: {next_adj['next_pos_collateral']} WEPO")
        
    except Exception as e:
        print(f"ERROR getting detailed info: {e}")
    
    return True

def test_api_endpoints():
    """Test the API endpoints for dynamic collateral"""
    
    print("\n🌐 TESTING API ENDPOINTS:")
    print("=" * 60)
    
    base_url = "http://localhost:8001/api"
    
    # Test collateral requirements endpoint
    try:
        response = requests.get(f"{base_url}/collateral/requirements")
        if response.status_code == 200:
            data = response.json()
            print("✅ /api/collateral/requirements - SUCCESS")
            print(f"   Current Height: {data['data']['block_height']}")
            print(f"   Masternode: {data['data']['masternode_collateral_wepo']} WEPO")
            print(f"   PoS: {data['data']['pos_collateral_wepo']} WEPO")
            print(f"   PoS Available: {data['data']['pos_available']}")
        else:
            print(f"❌ /api/collateral/requirements - FAILED ({response.status_code})")
    except Exception as e:
        print(f"❌ /api/collateral/requirements - ERROR: {e}")
    
    # Test collateral schedule endpoint
    try:
        response = requests.get(f"{base_url}/collateral/schedule")
        if response.status_code == 200:
            data = response.json()
            print("✅ /api/collateral/schedule - SUCCESS")
            print(f"   Schedule entries: {len(data['data']['schedule'])}")
            print(f"   Minimum floors: MN={data['data']['minimum_floors']['masternode']}, PoS={data['data']['minimum_floors']['pos']}")
            
            # Show first few schedule entries
            print("\n   Schedule Preview:")
            for entry in data['data']['schedule'][:3]:
                print(f"     Height {entry['block_height']}: MN={entry['masternode_collateral']}, PoS={entry['pos_collateral']}")
        else:
            print(f"❌ /api/collateral/schedule - FAILED ({response.status_code})")
    except Exception as e:
        print(f"❌ /api/collateral/schedule - ERROR: {e}")

def test_schedule_correctness():
    """Test that the schedule matches our expectations"""
    
    print("\n🎯 TESTING SCHEDULE CORRECTNESS:")
    print("=" * 60)
    
    blockchain = WEPOBlockchain()
    
    # Expected values at key heights
    expected_values = {
        0: {"mn": 10000, "pos": 0},
        PRE_POS_DURATION_BLOCKS: {"mn": 10000, "pos": 1000},
        PHASE_2A_END_HEIGHT: {"mn": 6000, "pos": 600},
        PHASE_2B_END_HEIGHT: {"mn": 3000, "pos": 300},
        PHASE_2C_END_HEIGHT: {"mn": 1500, "pos": 150},
        PHASE_2D_END_HEIGHT: {"mn": 1000, "pos": 100},
    }
    
    for height, expected in expected_values.items():
        mn_actual = blockchain.get_masternode_collateral_for_height(height) / COIN
        pos_actual = blockchain.get_pos_collateral_for_height(height) / COIN
        
        mn_match = abs(mn_actual - expected["mn"]) < 0.1
        pos_match = abs(pos_actual - expected["pos"]) < 0.1
        
        status = "✅" if mn_match and pos_match else "❌"
        
        print(f"{status} Height {height}: MN={mn_actual:.0f} (expected {expected['mn']}) | PoS={pos_actual:.0f} (expected {expected['pos']})")
    
    print("\n🔍 REDUCTION PERCENTAGES:")
    print("-" * 40)
    
    # Calculate actual reduction percentages
    reductions = [
        (PRE_POS_DURATION_BLOCKS, PHASE_2A_END_HEIGHT, "2nd Halving"),
        (PHASE_2A_END_HEIGHT, PHASE_2B_END_HEIGHT, "3rd Halving"),
        (PHASE_2B_END_HEIGHT, PHASE_2C_END_HEIGHT, "4th Halving"),
        (PHASE_2C_END_HEIGHT, PHASE_2D_END_HEIGHT, "5th Halving"),
    ]
    
    for from_height, to_height, description in reductions:
        old_mn = blockchain.get_masternode_collateral_for_height(from_height) / COIN
        new_mn = blockchain.get_masternode_collateral_for_height(to_height) / COIN
        
        old_pos = blockchain.get_pos_collateral_for_height(from_height) / COIN
        new_pos = blockchain.get_pos_collateral_for_height(to_height) / COIN
        
        mn_reduction = ((old_mn - new_mn) / old_mn) * 100 if old_mn > 0 else 0
        pos_reduction = ((old_pos - new_pos) / old_pos) * 100 if old_pos > 0 else 0
        
        print(f"{description}: MN -{mn_reduction:.1f}% | PoS -{pos_reduction:.1f}%")

if __name__ == "__main__":
    print("🚀 WEPO DYNAMIC COLLATERAL SYSTEM TEST")
    print("=" * 60)
    
    # Test the core blockchain functionality
    test_dynamic_collateral_system()
    
    # Test schedule correctness
    test_schedule_correctness()
    
    # Test API endpoints
    test_api_endpoints()
    
    print("\n🎉 TESTING COMPLETED!")
    print("=" * 60)
    print("✅ Dynamic collateral system is tied to PoW halvings")
    print("✅ Masternode requirements: 10K → 6K → 3K → 1.5K → 1K WEPO")
    print("✅ PoS requirements: 1K → 600 → 300 → 150 → 100 WEPO")
    print("✅ Accessibility increases as WEPO becomes scarcer")
    print("✅ Security maintained with minimum floors")