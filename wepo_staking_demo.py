#!/usr/bin/env python3
"""
WEPO Staking Activation Demo Tool
Fast-track activation for demonstration and testing
"""

import sys
import os
import time
import requests
import json
from datetime import datetime

class StakingDemo:
    """WEPO Staking Demonstration Tool"""
    
    def __init__(self, backend_url: str = "http://localhost:8001"):
        self.backend_url = backend_url
        self.api_url = f"{backend_url}/api"
    
    def mine_blocks_to_activation(self, target_height: int = 78840) -> bool:
        """Mine blocks to reach activation height"""
        try:
            # Get current height
            response = requests.get(f"{self.api_url}/mining/info", timeout=5)
            if response.status_code == 200:
                data = response.json()
                current_height = data.get('current_block_height', 0)
                
                print(f"Current height: {current_height}")
                print(f"Target height: {target_height}")
                print(f"Blocks to mine: {target_height - current_height}")
                
                if current_height >= target_height:
                    print("✅ Already at activation height!")
                    return True
                
                # Mine blocks using test endpoint
                miner_address = "wepo1staking000000000000000000000000000"
                blocks_needed = target_height - current_height
                
                print(f"Mining {blocks_needed} blocks to reach activation...")
                
                # Mine in batches to avoid timeouts
                batch_size = 100
                batches = (blocks_needed + batch_size - 1) // batch_size
                
                for batch in range(batches):
                    blocks_this_batch = min(batch_size, blocks_needed - (batch * batch_size))
                    
                    for i in range(blocks_this_batch):
                        response = requests.post(
                            f"{self.api_url}/test/mine-block",
                            json={"miner_address": miner_address},
                            timeout=10
                        )
                        
                        if response.status_code == 200:
                            if (i + 1) % 10 == 0:
                                print(f"  Mined {i + 1}/{blocks_this_batch} blocks in batch {batch + 1}")
                        else:
                            print(f"❌ Failed to mine block: {response.status_code}")
                            return False
                    
                    print(f"✅ Completed batch {batch + 1}/{batches}")
                
                print("🎉 Finished mining blocks!")
                return True
            else:
                print(f"❌ Cannot get mining info: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Mining failed: {str(e)}")
            return False
    
    def verify_activation(self) -> bool:
        """Verify PoS activation"""
        try:
            response = requests.get(f"{self.api_url}/staking/info", timeout=5)
            if response.status_code == 200:
                data = response.json()
                
                print(f"PoS Activated: {data.get('pos_activated')}")
                print(f"Current Height: {data.get('current_height')}")
                print(f"Activation Height: {data.get('activation_height')}")
                print(f"Blocks Until Activation: {data.get('blocks_until_activation')}")
                
                return data.get('pos_activated', False)
            else:
                print(f"❌ Cannot verify activation: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Verification failed: {str(e)}")
            return False
    
    def test_staking_after_activation(self) -> bool:
        """Test staking functionality after activation"""
        try:
            # Create a test wallet and fund it
            test_address = "wepo1staking000000000000000000000000000"
            
            print("Creating and funding test wallet...")
            
            # Fund the wallet
            response = requests.post(
                f"{self.api_url}/test/fund-wallet",
                json={"address": test_address, "amount": 5000.0},
                timeout=10
            )
            
            if response.status_code == 200:
                print("✅ Test wallet funded")
            else:
                print(f"⚠️ Wallet funding failed: {response.status_code}")
            
            # Try to create a stake
            print("Testing stake creation...")
            
            response = requests.post(
                f"{self.api_url}/stake",
                json={
                    "staker_address": test_address,
                    "amount": 1000.0
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Stake created successfully: {data.get('stake_id')}")
                print(f"   Staker: {data.get('staker_address')}")
                print(f"   Amount: {data.get('amount')} WEPO")
                return True
            else:
                print(f"❌ Stake creation failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ Staking test failed: {str(e)}")
            return False
    
    def test_masternode_after_activation(self) -> bool:
        """Test masternode functionality after activation"""
        try:
            # Create a test wallet and fund it with collateral
            test_address = "wepo1masternode0000000000000000000000000"
            
            print("Creating and funding masternode wallet...")
            
            # Fund the wallet with collateral amount
            response = requests.post(
                f"{self.api_url}/test/fund-wallet",
                json={"address": test_address, "amount": 15000.0},
                timeout=10
            )
            
            if response.status_code == 200:
                print("✅ Masternode wallet funded")
            else:
                print(f"⚠️ Masternode wallet funding failed: {response.status_code}")
            
            # Try to create a masternode
            print("Testing masternode creation...")
            
            response = requests.post(
                f"{self.api_url}/masternode",
                json={
                    "operator_address": test_address,
                    "collateral_txid": "test_collateral_txid",
                    "collateral_vout": 0,
                    "ip_address": "127.0.0.1",
                    "port": 22567
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Masternode created successfully: {data.get('masternode_id')}")
                print(f"   Operator: {data.get('operator_address')}")
                print(f"   IP: {data.get('ip_address')}:{data.get('port')}")
                return True
            else:
                print(f"❌ Masternode creation failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ Masternode test failed: {str(e)}")
            return False
    
    def run_activation_demo(self) -> bool:
        """Run complete staking activation demo"""
        print("🚀 WEPO STAKING ACTIVATION DEMO")
        print("=" * 60)
        print("Fast-tracking staking activation for demonstration...")
        print("=" * 60)
        
        # Step 1: Mine blocks to activation
        print("\n🔍 STEP 1: Mining blocks to activation height")
        print("-" * 40)
        
        if not self.mine_blocks_to_activation():
            print("❌ Failed to mine blocks to activation")
            return False
        
        # Step 2: Verify activation
        print("\n🔍 STEP 2: Verifying PoS activation")
        print("-" * 40)
        
        if not self.verify_activation():
            print("❌ PoS activation verification failed")
            return False
        
        print("✅ PoS IS NOW ACTIVATED!")
        
        # Step 3: Test staking
        print("\n🔍 STEP 3: Testing staking functionality")
        print("-" * 40)
        
        if not self.test_staking_after_activation():
            print("❌ Staking test failed")
            return False
        
        # Step 4: Test masternode
        print("\n🔍 STEP 4: Testing masternode functionality")
        print("-" * 40)
        
        if not self.test_masternode_after_activation():
            print("❌ Masternode test failed")
            return False
        
        # Final verification
        print("\n🔍 STEP 5: Final verification")
        print("-" * 40)
        
        self.show_final_status()
        
        return True
    
    def show_final_status(self):
        """Show final activation status"""
        try:
            response = requests.get(f"{self.api_url}/staking/info", timeout=5)
            if response.status_code == 200:
                data = response.json()
                
                print("📊 FINAL STAKING STATUS:")
                print(f"   PoS Activated: {'✅ YES' if data.get('pos_activated') else '❌ NO'}")
                print(f"   Current Height: {data.get('current_height')}")
                print(f"   Active Stakes: {data.get('active_stakes_count')}")
                print(f"   Total Staked: {data.get('total_staked_amount')} WEPO")
                print(f"   Active Masternodes: {data.get('active_masternodes_count')}")
                print(f"   Min Stake: {data.get('min_stake_amount')} WEPO")
                print(f"   Masternode Collateral: {data.get('masternode_collateral')} WEPO")
                print(f"   Staking Rewards: {data.get('staking_reward_percentage')}%")
                print(f"   Masternode Rewards: {data.get('masternode_reward_percentage')}%")
        except Exception as e:
            print(f"❌ Could not get final status: {str(e)}")

def main():
    """Main demo function"""
    print("⚠️  WEPO STAKING ACTIVATION DEMO")
    print("This will mine blocks to reach the activation height.")
    print("This is for demonstration purposes only.")
    print()
    
    # Confirm with user
    try:
        confirm = input("Do you want to proceed with the activation demo? (y/N): ").lower()
        if confirm != 'y':
            print("Demo cancelled.")
            return 0
    except KeyboardInterrupt:
        print("\nDemo cancelled.")
        return 0
    
    # Initialize demo
    demo = StakingDemo()
    
    # Run demo
    try:
        success = demo.run_activation_demo()
        
        if success:
            print("\n🎉 STAKING ACTIVATION DEMO COMPLETED!")
            print("=" * 60)
            print("✅ PoS is now activated and functional")
            print("✅ Staking mechanism working")
            print("✅ Masternode system operational")
            print("✅ WEPO staking is not yet production-ready!")
            print("=" * 60)
            return 0
        else:
            print("\n❌ STAKING ACTIVATION DEMO FAILED!")
            return 1
    
    except KeyboardInterrupt:
        print("\n🛑 Demo interrupted by user")
        return 1
    except Exception as e:
        print(f"\n💥 Demo error: {str(e)}")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)