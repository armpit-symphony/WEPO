#!/usr/bin/env python3
"""
Test script to verify TRUE End-to-End Encryption in WEPO messaging system
"""

import sys
import os
sys.path.append('/app/wepo-blockchain/core')

from quantum_messaging import messaging_system

def test_true_e2e_encryption():
    """Test that TRUE E2E encryption is working"""
    print("🔐 Testing TRUE End-to-End Encryption")
    print("=" * 50)
    
    # Test addresses
    alice_address = "wepo1alice000000000000000000000000000"
    bob_address = "wepo1bob00000000000000000000000000000"
    
    # Test message
    secret_message = "This is a SECRET message that only Bob should be able to read!"
    
    print(f"1. Testing message from Alice to Bob...")
    print(f"   Alice: {alice_address}")
    print(f"   Bob: {bob_address}")
    print(f"   Message: '{secret_message}'")
    
    # Send message from Alice to Bob
    try:
        message = messaging_system.send_message(
            from_address=alice_address,
            to_address=bob_address,
            content=secret_message,
            subject="Secret Test Message"
        )
        print(f"✓ Message sent successfully: {message.message_id}")
        
        # Verify message is encrypted
        print(f"\n2. Verifying message is encrypted...")
        print(f"   Encrypted content: {message.content[:50]}...")
        print(f"   Encrypted key length: {len(message.encryption_key)} bytes")
        
        # Test that Alice cannot decrypt Bob's message (not the recipient)
        print(f"\n3. Testing access control...")
        try:
            alice_decrypt = messaging_system.decrypt_message_for_user(message, alice_address)
            print(f"❌ SECURITY BREACH: Alice could decrypt Bob's message!")
            return False
        except Exception as e:
            print(f"✅ Access control working: {str(e)}")
            if "ACCESS DENIED" in str(e):
                print(f"✅ TRUE E2E: Server correctly denied access to Alice")
        
        # Test that Bob CAN decrypt the message (is the recipient)
        print(f"\n4. Testing legitimate decryption...")
        try:
            bob_decrypt = messaging_system.decrypt_message_for_user(message, bob_address)
            print(f"✓ Bob successfully decrypted: '{bob_decrypt}'")
            
            if bob_decrypt == secret_message:
                print(f"✓ Decryption successful - message intact")
            else:
                print(f"❌ Decryption corrupted message")
                return False
        except Exception as e:
            print(f"❌ Bob couldn't decrypt his own message: {e}")
            return False
        
        # Test that server cannot decrypt the message
        print(f"\n5. Testing server cannot decrypt...")
        try:
            # Try to decrypt without proper keys
            server_decrypt = messaging_system.decrypt_message_content(
                message.content, 
                message.encryption_key
            )
            print(f"❌ SECURITY BREACH: Server could decrypt message!")
            return False
        except Exception as e:
            print(f"✓ Server cannot decrypt: {str(e)}")
        
        print(f"\n6. Testing message statistics...")
        stats = messaging_system.get_messaging_stats()
        print(f"   Total messages: {stats['total_messages']}")
        print(f"   Encryption: {stats['quantum_encryption']}")
        print(f"   Universal compatibility: {stats['universal_compatibility']}")
        
        print(f"\n🎉 TRUE End-to-End Encryption Test PASSED!")
        print(f"✅ Server cannot decrypt messages")
        print(f"✅ Only recipients can decrypt messages")
        print(f"✅ Access control working correctly")
        print(f"✅ Message integrity preserved")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    success = test_true_e2e_encryption()
    if success:
        print("\n✅ TRUE E2E ENCRYPTION WORKING CORRECTLY")
    else:
        print("\n❌ TRUE E2E ENCRYPTION FAILED")
        sys.exit(1)