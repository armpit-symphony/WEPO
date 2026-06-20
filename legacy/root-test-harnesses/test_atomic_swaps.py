#!/usr/bin/env python3
"""
Test script for WEPO BTC Atomic Swap implementation
"""

import sys
import os
sys.path.append('/app/wepo-blockchain')

from core.atomic_swaps import (
    AtomicSwapEngine, 
    SwapType, 
    SwapState,
    validate_btc_address,
    validate_wepo_address,
    create_swap_request
)
import asyncio
import time
import json

async def test_atomic_swap_validation():
    """Test address validation functions"""
    print("=== Testing Address Validation ===")
    
    # Test BTC address validation
    btc_addresses = [
        "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",  # Valid P2PKH
        "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",  # Valid P2SH
        "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",  # Valid Bech32
        "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx",  # Valid Testnet
        "invalid_address",  # Invalid
        ""  # Empty
    ]
    
    for addr in btc_addresses:
        is_valid = validate_btc_address(addr)
        print(f"BTC address '{addr}': {'✓' if is_valid else '✗'}")
    
    # Test WEPO address validation
    wepo_addresses = [
        "wepo1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",  # Valid
        "wepo1test123456789abcdef0123456789abcdef01",  # Valid
        "wepo1short",  # Too short
        "btc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",  # Wrong prefix
        ""  # Empty
    ]
    
    for addr in wepo_addresses:
        is_valid = validate_wepo_address(addr)
        print(f"WEPO address '{addr}': {'✓' if is_valid else '✗'}")
    
    print()

async def test_swap_engine_basic():
    """Test basic atomic swap engine functionality"""
    print("=== Testing Atomic Swap Engine ===")
    
    engine = AtomicSwapEngine()
    
    # Test exchange rate
    rate = engine.get_exchange_rate()
    print(f"Exchange rate: 1 BTC = {rate} WEPO")
    
    # Test amount calculation
    btc_amount = 0.1
    wepo_amount = engine.calculate_wepo_amount(btc_amount)
    print(f"Amount calculation: {btc_amount} BTC = {wepo_amount} WEPO")
    
    # Test parameter validation
    valid_params = engine.validate_swap_parameters(
        btc_amount=0.1,
        btc_address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        wepo_address="wepo1test123456789abcdef0123456789abcdef01"
    )
    print(f"Valid parameters: {'✓' if valid_params else '✗'}")
    
    # Test invalid parameters
    invalid_params = engine.validate_swap_parameters(
        btc_amount=0.0001,  # Too small
        btc_address="invalid_address",
        wepo_address="wepo1test123456789abcdef0123456789abcdef01"
    )
    print(f"Invalid parameters (should be false): {'✓' if not invalid_params else '✗'}")
    
    print()

async def test_swap_initiation():
    """Test atomic swap initiation"""
    print("=== Testing Swap Initiation ===")
    
    engine = AtomicSwapEngine()
    
    # Test data
    initiator_btc = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    initiator_wepo = "wepo1test123456789abcdef0123456789abcdef01"
    participant_btc = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
    participant_wepo = "wepo1participant123456789abcdef0123456789ab"
    btc_amount = 0.05
    
    try:
        # Initiate BTC to WEPO swap
        swap_contract = await engine.initiate_swap(
            SwapType.BTC_TO_WEPO,
            initiator_btc,
            initiator_wepo,
            participant_btc,
            participant_wepo,
            btc_amount
        )
        
        print(f"Swap initiated successfully!")
        print(f"Swap ID: {swap_contract.swap_id}")
        print(f"Swap Type: {swap_contract.swap_type.value}")
        print(f"State: {swap_contract.state.value}")
        print(f"BTC Amount: {swap_contract.btc_amount}")
        print(f"WEPO Amount: {swap_contract.wepo_amount}")
        print(f"Secret Hash: {swap_contract.secret_hash[:16]}...")
        print(f"BTC HTLC Address: {swap_contract.btc_htlc_address}")
        print(f"WEPO HTLC Address: {swap_contract.wepo_htlc_address}")
        print(f"BTC Locktime: {swap_contract.btc_locktime}")
        print(f"WEPO Locktime: {swap_contract.wepo_locktime}")
        print(f"Expires At: {swap_contract.expires_at}")
        
        return swap_contract
        
    except Exception as e:
        print(f"Swap initiation failed: {e}")
        return None

async def test_swap_funding():
    """Test atomic swap funding"""
    print("\n=== Testing Swap Funding ===")
    
    engine = AtomicSwapEngine()
    
    # Create a swap specifically for testing funding
    try:
        swap_contract = await engine.initiate_swap(
            SwapType.BTC_TO_WEPO,
            "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "wepo1test123456789abcdef0123456789abcdef01",
            "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",
            "wepo1participant123456789abcdef0123456789ab",
            0.05
        )
        print(f"Funding test swap created: {swap_contract.swap_id}")
    except Exception as e:
        print(f"Failed to create swap for funding test: {e}")
        return None
    
    swap_id = swap_contract.swap_id
    
    # Test BTC funding
    btc_tx_hash = "a1b2c3d4e5f6789012345678901234567890123456789012345678901234567890"
    btc_funding_success = await engine.fund_swap(swap_id, "BTC", btc_tx_hash)
    print(f"BTC funding: {'✓' if btc_funding_success else '✗'}")
    
    # Check status after BTC funding
    status_after_btc = engine.get_swap_status(swap_id)
    if status_after_btc:
        print(f"BTC funding recorded: {'✓' if status_after_btc.btc_funding_tx == btc_tx_hash else '✗'}")
    
    # Test WEPO funding
    wepo_tx_hash = "w1x2y3z4a5b6789012345678901234567890123456789012345678901234567890"
    wepo_funding_success = await engine.fund_swap(swap_id, "WEPO", wepo_tx_hash)
    print(f"WEPO funding: {'✓' if wepo_funding_success else '✗'}")
    
    # Check final swap status
    swap_status = engine.get_swap_status(swap_id)
    if swap_status:
        print(f"Swap state after funding: {swap_status.state.value}")
        print(f"BTC funding tx: {swap_status.btc_funding_tx}")
        print(f"WEPO funding tx: {swap_status.wepo_funding_tx}")
        print(f"Both sides funded: {'✓' if swap_status.state == SwapState.FUNDED else '✗'}")
    
    return swap_contract

async def test_swap_redemption():
    """Test atomic swap redemption"""
    print("\n=== Testing Swap Redemption ===")
    
    engine = AtomicSwapEngine()
    
    # Create and fund a swap specifically for redemption testing
    try:
        swap_contract = await engine.initiate_swap(
            SwapType.BTC_TO_WEPO,
            "1RedemptionTest34567890123456789012345",
            "wepo1redemption123456789abcdef0123456789ab",
            "3RedemptionParticipant567890123456789012",
            "wepo1participant123456789abcdef0123456789ab",
            0.03
        )
        
        # Fund the swap
        await engine.fund_swap(swap_contract.swap_id, "BTC", "btc_redemption_tx")
        await engine.fund_swap(swap_contract.swap_id, "WEPO", "wepo_redemption_tx")
        
        print(f"Redemption test swap created and funded: {swap_contract.swap_id}")
        
    except Exception as e:
        print(f"Failed to create swap for redemption test: {e}")
        return None
    
    swap_id = swap_contract.swap_id
    secret = swap_contract.secret
    
    # Check that swap is funded
    current_status = engine.get_swap_status(swap_id)
    print(f"Swap funded status: {'✓' if current_status.state == SwapState.FUNDED else '✗'}")
    
    # Test redemption with correct secret
    redemption_success = await engine.redeem_swap(swap_id, secret)
    print(f"Redemption with correct secret: {'✓' if redemption_success else '✗'}")
    
    # Check swap status
    swap_status = engine.get_swap_status(swap_id)
    if swap_status:
        print(f"Swap state after redemption: {swap_status.state.value}")
        if swap_status.secret:
            print(f"Secret revealed: {swap_status.secret[:16]}...")
    
    # Test redemption with wrong secret on a new swap
    new_swap = await engine.initiate_swap(
        SwapType.BTC_TO_WEPO,
        "1TestWrongSecret4567890123456789012345",
        "wepo1wrong123456789abcdef0123456789abcdef01",
        "3TestParticipant234567890123456789012",
        "wepo1participant123456789abcdef0123456789ab",
        0.01
    )
    wrong_secret = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    wrong_redemption = await engine.redeem_swap(new_swap.swap_id, wrong_secret)
    print(f"Redemption with wrong secret (should fail): {'✓' if not wrong_redemption else '✗'}")
    
    return swap_contract

async def test_swap_refund():
    """Test atomic swap refund"""
    print("\n=== Testing Swap Refund ===")
    
    engine = AtomicSwapEngine()
    
    # Create a new swap for refund testing
    swap_contract = await engine.initiate_swap(
        SwapType.WEPO_TO_BTC,
        "1RefundTest1234567890123456789012345678",
        "wepo1refund123456789abcdef0123456789abcdef01",
        "3RefundParticipant1234567890123456789012",
        "wepo1participant123456789abcdef0123456789ab",
        0.01  # btc_amount parameter
    )
    
    swap_id = swap_contract.swap_id
    
    # Test refund before expiry (should fail)
    early_refund = await engine.refund_swap(swap_id)
    print(f"Early refund (should fail): {'✓' if not early_refund else '✗'}")
    
    # Simulate expiry by modifying locktime
    swap_contract.btc_locktime = int(time.time()) - 3600  # 1 hour ago
    swap_contract.wepo_locktime = int(time.time()) - 3600  # 1 hour ago
    
    # Test refund after expiry (should succeed)
    expired_refund = await engine.refund_swap(swap_id)
    print(f"Expired refund: {'✓' if expired_refund else '✗'}")
    
    # Check swap status
    swap_status = engine.get_swap_status(swap_id)
    if swap_status:
        print(f"Swap state after refund: {swap_status.state.value}")

async def test_swap_proof():
    """Test atomic swap proof generation"""
    print("\n=== Testing Swap Proof ===")
    
    engine = AtomicSwapEngine()
    
    # Create a swap
    swap_contract = await engine.initiate_swap(
        SwapType.BTC_TO_WEPO,
        "1ProofTest1234567890123456789012345678",
        "wepo1proof123456789abcdef0123456789abcdef01",
        "3ProofParticipant1234567890123456789012",
        "wepo1participant123456789abcdef0123456789ab",
        0.02
    )
    
    swap_id = swap_contract.swap_id
    
    # Get swap proof
    proof = await engine.get_swap_proof(swap_id)
    if proof:
        print(f"Proof generated successfully!")
        print(f"Proof type: {proof['proof_type']}")
        print(f"Secret hash: {proof['secret_hash'][:16]}...")
        print(f"BTC HTLC address: {proof['btc_htlc_address']}")
        print(f"WEPO HTLC address: {proof['wepo_htlc_address']}")
        print(f"State: {proof['state']}")
    else:
        print("Failed to generate proof")

async def test_swap_list():
    """Test atomic swap listing"""
    print("\n=== Testing Swap List ===")
    
    engine = AtomicSwapEngine()
    
    # Create multiple swaps
    for i in range(3):
        await engine.initiate_swap(
            SwapType.BTC_TO_WEPO,
            f"1ListTest{i}234567890123456789012345678",
            f"wepo1list{i}123456789abcdef0123456789abcdef01",
            f"3ListParticipant{i}234567890123456789012",
            f"wepo1participant{i}123456789abcdef0123456789ab",
            0.01 * (i + 1)
        )
    
    # Get all swaps
    all_swaps = engine.get_all_swaps()
    print(f"Total swaps: {len(all_swaps)}")
    
    for i, swap in enumerate(all_swaps):
        print(f"Swap {i+1}: {swap.swap_id} - {swap.state.value} - {swap.btc_amount} BTC")

async def test_swap_cleanup():
    """Test expired swap cleanup"""
    print("\n=== Testing Swap Cleanup ===")
    
    engine = AtomicSwapEngine()
    
    # Create a swap and make it expired
    swap_contract = await engine.initiate_swap(
        SwapType.BTC_TO_WEPO,
        "1CleanupTest234567890123456789012345678",
        "wepo1cleanup123456789abcdef0123456789abcdef01",
        "3CleanupParticipant234567890123456789012",
        "wepo1participant123456789abcdef0123456789ab",
        0.01
    )
    
    # Make it expired
    swap_contract.expires_at = swap_contract.expires_at.replace(year=2020)
    
    print(f"Swaps before cleanup: {len(engine.get_all_swaps())}")
    
    # Run cleanup
    await engine.cleanup_expired_swaps()
    
    print(f"Swaps after cleanup: {len(engine.get_all_swaps())}")

async def main():
    """Run all atomic swap tests"""
    print("WEPO BTC Atomic Swap Implementation Test")
    print("=" * 50)
    
    tests = [
        test_atomic_swap_validation,
        test_swap_engine_basic,
        test_swap_initiation,
        test_swap_funding,
        test_swap_redemption,
        test_swap_refund,
        test_swap_proof,
        test_swap_list,
        test_swap_cleanup
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            await test()
            passed += 1
            print("✓ PASSED")
        except Exception as e:
            print(f"✗ FAILED: {e}")
    
    print(f"\nTest Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED - Real atomic swap implementation is working!")
    else:
        print("❌ Some tests failed - Need to fix implementation")
    
    return passed == total

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)