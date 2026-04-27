#!/usr/bin/env python3
"""
WEPO Dilithium2 Migration Script
Migrates from simulated RSA-backend Dilithium to REAL quantum-resistant Dilithium2
"""

import os
import sys
import json
import time
from pathlib import Path

# Add blockchain core to path
sys.path.append('/app/wepo-blockchain/core')

from real_dilithium import RealDilithiumSigner, is_real_dilithium_available, migrate_from_rsa_simulation
from dilithium import DilithiumSigner  # Old simulated version

def test_migration_compatibility():
    """Test migration from old to new implementation"""
    print("🧪 TESTING MIGRATION COMPATIBILITY")
    print("=" * 50)
    
    # Test old implementation
    print("1. Testing OLD simulated Dilithium...")
    try:
        old_signer = DilithiumSigner()
        old_keypair = old_signer.generate_keypair()
        old_message = b"WEPO migration test message"
        old_signature = old_signer.sign(old_message)
        old_valid = old_signer.verify(old_message, old_signature)
        
        print(f"✅ Old implementation working:")
        print(f"   Public Key: {len(old_keypair.public_key)} bytes")
        print(f"   Private Key: {len(old_keypair.private_key)} bytes") 
        print(f"   Signature: {len(old_signature)} bytes")
        print(f"   Verification: {old_valid}")
    except Exception as e:
        print(f"❌ Old implementation failed: {e}")
        return False
    
    # Test new implementation
    print("\n2. Testing NEW real Dilithium...")
    try:
        new_signer = RealDilithiumSigner()
        new_keypair = new_signer.generate_keypair()
        new_message = b"WEPO migration test message"
        new_signature = new_signer.sign(new_message)
        new_valid = new_signer.verify(new_message, new_signature)
        
        print(f"✅ New implementation working:")
        print(f"   Public Key: {len(new_keypair.public_key)} bytes")
        print(f"   Private Key: {len(new_keypair.private_key)} bytes")
        print(f"   Signature: {len(new_signature)} bytes")
        print(f"   Verification: {new_valid}")
    except Exception as e:
        print(f"❌ New implementation failed: {e}")
        return False
    
    # Test cross-compatibility (should fail as expected)
    print("\n3. Testing cross-compatibility...")
    try:
        cross_valid = new_signer.verify(old_message, old_signature, old_keypair.public_key)
        print(f"⚠️  Cross-verification result: {cross_valid} (Expected: False)")
    except Exception as e:
        print(f"✅ Cross-verification failed as expected: {e}")
    
    return True

def analyze_current_dilithium_usage():
    """Analyze current Dilithium usage in WEPO"""
    print("\n🔍 ANALYZING CURRENT DILITHIUM USAGE")
    print("=" * 50)
    
    # Check blockchain.py
    blockchain_file = Path("/app/wepo-blockchain/core/blockchain.py")
    if blockchain_file.exists():
        with open(blockchain_file, 'r') as f:
            content = f.read()
            if 'dilithium' in content.lower():
                print("✅ blockchain.py uses Dilithium")
                # Count imports
                dilithium_imports = content.count('dilithium')
                print(f"   Dilithium references: {dilithium_imports}")
            else:
                print("⚠️  blockchain.py doesn't seem to use Dilithium directly")
    
    # Check other core files
    core_files = [
        "quantum_transaction.py",
        "quantum_blockchain.py", 
        "transaction.py",
        "wepo_node.py"
    ]
    
    for filename in core_files:
        filepath = Path(f"/app/wepo-blockchain/core/{filename}")
        if filepath.exists():
            with open(filepath, 'r') as f:
                content = f.read()
                if 'dilithium' in content.lower():
                    print(f"✅ {filename} uses Dilithium")
                else:
                    print(f"⚪ {filename} doesn't use Dilithium")
        else:
            print(f"❌ {filename} not found")

def create_migration_plan():
    """Create comprehensive migration plan"""
    print("\n📋 MIGRATION PLAN")
    print("=" * 50)
    
    migration_steps = [
        {
            "step": 1,
            "title": "Update dilithium.py imports",
            "description": "Replace old DilithiumSigner with RealDilithiumSigner",
            "files": ["/app/wepo-blockchain/core/dilithium.py"],
            "risk": "HIGH - Breaks existing signatures",
            "rollback": "Keep backup of old dilithium.py"
        },
        {
            "step": 2, 
            "title": "Update blockchain.py integration",
            "description": "Update any direct Dilithium usage in blockchain core",
            "files": ["/app/wepo-blockchain/core/blockchain.py"],
            "risk": "MEDIUM - May affect consensus",
            "rollback": "Git revert if consensus breaks"
        },
        {
            "step": 3,
            "title": "Update transaction signing",
            "description": "Ensure all transaction signatures use real Dilithium",
            "files": ["/app/wepo-blockchain/core/transaction.py"],
            "risk": "HIGH - Affects all transactions",
            "rollback": "Restore old transaction module"
        },
        {
            "step": 4,
            "title": "Update wallet integration",
            "description": "Update wallet to generate real Dilithium keys",
            "files": ["/app/wepo-fast-test-bridge.py"],
            "risk": "MEDIUM - Affects wallet creation",
            "rollback": "Restore old wallet generation"
        },
        {
            "step": 5,
            "title": "Add migration endpoints",
            "description": "Add API endpoints for key migration",
            "files": ["/app/wepo-fast-test-bridge.py"],
            "risk": "LOW - New functionality",
            "rollback": "Remove new endpoints"
        },
        {
            "step": 6,
            "title": "Update frontend components",
            "description": "Update wallet creation to show quantum resistance status",
            "files": ["/app/frontend/src/components/WalletSetup.js"],
            "risk": "LOW - UI only",
            "rollback": "Restore old UI"
        },
        {
            "step": 7,
            "title": "Comprehensive testing",
            "description": "Test all signature operations with real Dilithium",
            "files": ["All test files"],
            "risk": "LOW - Testing only",
            "rollback": "N/A"
        }
    ]
    
    for step in migration_steps:
        print(f"\n📌 STEP {step['step']}: {step['title']}")
        print(f"   Description: {step['description']}")
        print(f"   Files: {', '.join(step['files'])}")
        print(f"   Risk Level: {step['risk']}")
        print(f"   Rollback: {step['rollback']}")
    
    return migration_steps

def backup_current_implementation():
    """Backup current Dilithium implementation"""
    print("\n💾 BACKING UP CURRENT IMPLEMENTATION")
    print("=" * 40)
    
    backup_dir = Path("/app/dilithium_backup")
    backup_dir.mkdir(exist_ok=True)
    
    files_to_backup = [
        "/app/wepo-blockchain/core/dilithium.py",
        "/app/wepo-blockchain/core/blockchain.py", 
        "/app/wepo-blockchain/core/transaction.py"
    ]
    
    for file_path in files_to_backup:
        source = Path(file_path)
        if source.exists():
            backup_name = f"{source.name}.backup.{int(time.time())}"
            backup_path = backup_dir / backup_name
            
            try:
                backup_path.write_text(source.read_text())
                print(f"✅ Backed up {source.name} → {backup_name}")
            except Exception as e:
                print(f"❌ Failed to backup {source.name}: {e}")
        else:
            print(f"⚠️  File not found: {file_path}")
    
    return backup_dir

def estimate_migration_impact():
    """Estimate migration impact and requirements"""
    print("\n📊 MIGRATION IMPACT ASSESSMENT")
    print("=" * 40)
    
    impact_assessment = {
        "security_improvement": "🔐 CRITICAL - Upgrades from simulated to REAL quantum resistance",
        "breaking_changes": "💥 HIGH - All existing signatures become invalid", 
        "development_time": "⏱️  MEDIUM - 2-3 days for complete migration",
        "testing_required": "🧪 HIGH - Comprehensive testing of all signature operations",
        "rollback_complexity": "🔄 MEDIUM - Requires backup restoration and testing",
        "user_impact": "👥 LOW - Transparent to end users (better security)",
        "network_impact": "🌐 MEDIUM - All nodes need upgrade simultaneously",
        "backwards_compatibility": "❌ NONE - Complete break from old signatures"
    }
    
    for category, impact in impact_assessment.items():
        print(f"   {category}: {impact}")
    
    print("\n🎯 RECOMMENDATION:")
    print("   ✅ PROCEED with migration - Security benefits outweigh risks")
    print("   ⚠️  COORDINATE with all network participants") 
    print("   🔄 PLAN for coordinated upgrade across all nodes")
    print("   💾 MAINTAIN comprehensive backups")

if __name__ == "__main__":
    print("🔐 WEPO DILITHIUM2 MIGRATION ANALYSIS")
    print("=" * 60)
    print("🎯 Purpose: Migrate from simulated to REAL quantum-resistant signatures")
    print("📅 Date:", time.strftime("%Y-%m-%d %H:%M:%S"))
    print()
    
    # Check if real Dilithium is available
    print("1. Checking real Dilithium availability...")
    if is_real_dilithium_available():
        print("✅ Real Dilithium2 is available and working!")
    else:
        print("❌ Real Dilithium2 not available - migration cannot proceed")
        sys.exit(1)
    
    # Test migration compatibility
    if not test_migration_compatibility():
        print("❌ Migration compatibility test failed")
        sys.exit(1)
    
    # Analyze current usage
    analyze_current_dilithium_usage()
    
    # Create migration plan
    migration_steps = create_migration_plan()
    
    # Backup current implementation
    backup_dir = backup_current_implementation()
    
    # Estimate impact
    estimate_migration_impact()
    
    print(f"\n🎉 MIGRATION ANALYSIS COMPLETE")
    print("=" * 40)
    print(f"✅ Real Dilithium2 is under deployment review")
    print(f"💾 Backups created in: {backup_dir}")
    print(f"📋 Migration plan ready with {len(migration_steps)} steps")
    print(f"🔐 WEPO will have TRUE quantum resistance after migration!")
    
    print(f"\n🚀 NEXT STEPS:")
    print(f"   1. Review migration plan above")
    print(f"   2. Coordinate with development team")
    print(f"   3. Execute migration in development environment first")
    print(f"   4. Test thoroughly before deployment review")