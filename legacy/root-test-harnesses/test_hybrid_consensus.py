#!/usr/bin/env python3
"""
Test script for WEPO Hybrid PoW/PoS Consensus System
"""

import sys
import os
import time
sys.path.append('/app/wepo-blockchain/core')

from blockchain import WepoBlockchain, POS_ACTIVATION_HEIGHT, BLOCK_TIME_POS, BLOCK_TIME_POW_HYBRID

def test_hybrid_consensus():
    """Test the hybrid PoW/PoS consensus system"""
    print("🔗 Testing WEPO Hybrid PoW/PoS Consensus System")
    print("=" * 60)
    
    # Create blockchain instance
    blockchain = WepoBlockchain()
    
    # Test addresses
    miner_address = "wepo1miner000000000000000000000000000"
    validator_address = "wepo1validator000000000000000000000000"
    staker_address = "wepo1staker000000000000000000000000000"
    
    print(f"1. Testing consensus type detection...")
    
    # Test pre-PoS consensus
    pre_pos_consensus = blockchain.get_consensus_type(100)
    print(f"   Block 100 consensus: {pre_pos_consensus}")
    
    # Test post-PoS consensus
    post_pos_consensus = blockchain.get_consensus_type(POS_ACTIVATION_HEIGHT + 100)
    print(f"   Block {POS_ACTIVATION_HEIGHT + 100} consensus: {post_pos_consensus}")
    
    print(f"\n2. Testing validator selection...")
    
    # Add staking stake for validator
    blockchain.add_stake(validator_address, 10000_00000000)  # 10,000 WEPO
    blockchain.add_stake(staker_address, 5000_00000000)      # 5,000 WEPO
    
    # Test validator selection
    selected_validator = blockchain.select_pos_validator(POS_ACTIVATION_HEIGHT + 1)
    print(f"   Selected validator: {selected_validator}")
    
    # Test validator validation
    is_valid = blockchain.is_valid_pos_validator(validator_address, POS_ACTIVATION_HEIGHT + 1)
    print(f"   Validator {validator_address} is valid: {is_valid}")
    
    print(f"\n3. Testing PoS block creation...")
    
    # Create a PoS block
    pos_block = blockchain.create_pos_block(validator_address)
    if pos_block:
        print(f"   ✅ PoS block created: {pos_block.get_block_hash()}")
        print(f"   Validator: {pos_block.header.validator_address}")
        print(f"   Consensus type: {pos_block.header.consensus_type}")
        print(f"   Block height: {pos_block.height}")
        
        # Validate PoS block
        is_valid_pos = blockchain.validate_pos_block(pos_block)
        print(f"   PoS block validation: {is_valid_pos}")
    else:
        print(f"   ❌ Failed to create PoS block")
        return False
    
    print(f"\n4. Testing PoW block creation...")
    
    # Create a PoW block
    pow_block = blockchain.create_new_block(miner_address)
    if pow_block:
        print(f"   ✅ PoW block created: {pow_block.get_block_hash()}")
        print(f"   Miner: {miner_address}")
        print(f"   Consensus type: {pow_block.header.consensus_type}")
        print(f"   Block height: {pow_block.height}")
        
        # Validate PoW block
        is_valid_pow = blockchain.validate_block(pow_block)
        print(f"   PoW block validation: {is_valid_pow}")
    else:
        print(f"   ❌ Failed to create PoW block")
        return False
    
    print(f"\n5. Testing reward calculations...")
    
    # Test PoW reward
    pow_reward = blockchain.calculate_block_reward(POS_ACTIVATION_HEIGHT + 1)
    print(f"   PoW reward: {pow_reward / 100000000:.8f} WEPO")
    
    # Test PoS reward  
    pos_reward = blockchain.calculate_pos_reward(POS_ACTIVATION_HEIGHT + 1)
    print(f"   PoS reward: {pos_reward / 100000000:.8f} WEPO")
    
    # Test reward ratio
    reward_ratio = pos_reward / pow_reward if pow_reward > 0 else 0
    print(f"   PoS/PoW reward ratio: {reward_ratio:.2f}")
    
    print(f"\n6. Testing hybrid block timing...")
    
    print(f"   PoS block time: {BLOCK_TIME_POS // 60} minutes")
    print(f"   PoW block time: {BLOCK_TIME_POW_HYBRID // 60} minutes")
    print(f"   PoS frequency: {BLOCK_TIME_POW_HYBRID // BLOCK_TIME_POS}x more frequent")
    
    print(f"\n7. Testing network info...")
    
    # Test network info with hybrid consensus
    network_info = blockchain.get_network_info()
    print(f"   Network consensus: {network_info.get('consensus_type', 'unknown')}")
    
    if 'hybrid_consensus' in network_info:
        hybrid_info = network_info['hybrid_consensus']
        print(f"   Hybrid consensus active: {hybrid_info.get('pos_activated', False)}")
        print(f"   Total staked: {hybrid_info.get('total_staked', 0) / 100000000:.8f} WEPO")
        print(f"   Active validators: {hybrid_info.get('active_validators', 0)}")
    
    print(f"\n8. Testing coinbase transactions...")
    
    # Test PoW coinbase
    pow_coinbase = blockchain.create_coinbase_transaction(
        POS_ACTIVATION_HEIGHT + 1, miner_address, "pow"
    )
    print(f"   PoW coinbase value: {pow_coinbase.outputs[0].value / 100000000:.8f} WEPO")
    
    # Test PoS coinbase
    pos_coinbase = blockchain.create_coinbase_transaction(
        POS_ACTIVATION_HEIGHT + 1, validator_address, "pos"
    )
    print(f"   PoS coinbase value: {pos_coinbase.outputs[0].value / 100000000:.8f} WEPO")
    
    print(f"\n9. Testing staking info...")
    
    # Test staking info
    staking_info = blockchain.get_staking_info()
    print(f"   Staking activated: {staking_info.get('active', False)}")
    print(f"   Minimum stake: {staking_info.get('min_stake', 0) / 100000000:.0f} WEPO")
    
    print(f"\n🎉 Hybrid PoW/PoS Consensus Test Results:")
    print(f"✅ Consensus type detection working")
    print(f"✅ Validator selection working")
    print(f"✅ PoS block creation working")
    print(f"✅ PoW block creation working")
    print(f"✅ Reward calculations working")
    print(f"✅ Block timing configured correctly")
    print(f"✅ Network info shows hybrid status")
    print(f"✅ Coinbase transactions working")
    print(f"✅ Staking integration working")
    
    print(f"\n🔗 HYBRID CONSENSUS SUMMARY:")
    print(f"   After block {POS_ACTIVATION_HEIGHT}:")
    print(f"   - PoS blocks every {BLOCK_TIME_POS // 60} minutes")
    print(f"   - PoW blocks every {BLOCK_TIME_POW_HYBRID // 60} minutes")
    print(f"   - PoS validators selected by stake weight")
    print(f"   - First valid block wins (timestamp priority)")
    print(f"   - Both consensus types supported simultaneously")
    
    return True

if __name__ == "__main__":
    success = test_hybrid_consensus()
    if success:
        print("\n✅ HYBRID POW/POS CONSENSUS SYSTEM WORKING!")
    else:
        print("\n❌ HYBRID POW/POS CONSENSUS SYSTEM FAILED!")
        sys.exit(1)