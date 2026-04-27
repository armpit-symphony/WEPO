#!/usr/bin/env python3
"""
WEPO Address Standardization System - Backend
Unified address generation, validation, and formatting for Python backend
"""

import hashlib
import re
from typing import Dict, Optional, Union

# Address format definitions
ADDRESS_FORMATS = {
    "WEPO_REGULAR": {
        "prefix": "wepo1",
        "payload_length": 32,
        "total_length": 37,
        "type": "regular"
    },
    "WEPO_QUANTUM": {
        "prefix": "wepo1q",
        "payload_length": 39,
        "total_length": 45,
        "type": "quantum"
    },
    "BTC": {
        "prefix": "1",
        "payload_length": 25,
        "total_length": 34,
        "type": "bitcoin"
    }
}

def generate_wepo_address(seed: Union[str, bytes], address_type: str = "regular") -> str:
    """
    Generate standardized WEPO address from seed
    
    Args:
        seed: Wallet seed (string or bytes)
        address_type: 'regular' or 'quantum'
        
    Returns:
        Standardized WEPO address
    """
    if isinstance(seed, bytes):
        seed_str = seed.hex()
    else:
        seed_str = str(seed)
    
    # Generate hash from seed
    hash_obj = hashlib.sha256(seed_str.encode()).hexdigest()
    
    if address_type == "quantum":
        format_info = ADDRESS_FORMATS["WEPO_QUANTUM"]
        payload = hash_obj[:format_info["payload_length"]]
        return f"{format_info['prefix']}{payload}"
    else:
        format_info = ADDRESS_FORMATS["WEPO_REGULAR"]
        payload = hash_obj[:format_info["payload_length"]]
        return f"{format_info['prefix']}{payload}"

def validate_wepo_address(address: str) -> Dict[str, Union[bool, str, None]]:
    """
    Validate WEPO address format
    
    Args:
        address: Address string to validate
        
    Returns:
        Dict with validation result, type, and error message if invalid
    """
    if not address or not isinstance(address, str):
        return {
            "valid": False,
            "type": None,
            "error": "Address must be a string"
        }
    
    # Check for regular WEPO address
    regular_format = ADDRESS_FORMATS["WEPO_REGULAR"]
    if address.startswith(regular_format["prefix"]) and not address.startswith(ADDRESS_FORMATS["WEPO_QUANTUM"]["prefix"]):
        if len(address) == regular_format["total_length"]:
            return {
                "valid": True,
                "type": "regular",
                "format": regular_format
            }
        else:
            return {
                "valid": False,
                "type": "regular",
                "error": f"Regular WEPO address must be {regular_format['total_length']} characters"
            }
    
    # Check for quantum WEPO address
    quantum_format = ADDRESS_FORMATS["WEPO_QUANTUM"]
    if address.startswith(quantum_format["prefix"]):
        if len(address) == quantum_format["total_length"]:
            return {
                "valid": True,
                "type": "quantum",
                "format": quantum_format
            }
        else:
            return {
                "valid": False,
                "type": "quantum",
                "error": f"Quantum WEPO address must be {quantum_format['total_length']} characters"
            }
    
    return {
        "valid": False,
        "type": None,
        "error": "Address must start with wepo1 (regular) or wepo1q (quantum)"
    }

def get_address_type(address: str) -> Optional[str]:
    """
    Detect address type from address string
    
    Args:
        address: Address to analyze
        
    Returns:
        Address type ('regular', 'quantum') or None if invalid
    """
    validation = validate_wepo_address(address)
    return validation["type"] if validation["valid"] else None

def is_quantum_address(address: str) -> bool:
    """
    Check if address is quantum-resistant
    
    Args:
        address: Address to check
        
    Returns:
        True if quantum-resistant
    """
    return get_address_type(address) == "quantum"

def is_regular_address(address: str) -> bool:
    """
    Check if address is regular WEPO address
    
    Args:
        address: Address to check
        
    Returns:
        True if regular WEPO address
    """
    return get_address_type(address) == "regular"

def format_address_for_display(address: str, start_chars: int = 8, end_chars: int = 6) -> str:
    """
    Format address for display (truncate middle)
    
    Args:
        address: Full address
        start_chars: Characters to show at start
        end_chars: Characters to show at end
        
    Returns:
        Formatted address
    """
    if not address or len(address) <= start_chars + end_chars:
        return address
    
    return f"{address[:start_chars]}...{address[-end_chars:]}"

def standardize_address(legacy_address: str) -> str:
    """
    Convert legacy address to standardized format
    
    Args:
        legacy_address: Old format address
        
    Returns:
        Standardized address
    """
    if not legacy_address or not legacy_address.startswith("wepo1"):
        return legacy_address
    
    # Handle legacy 45-char addresses (convert to quantum format)
    if len(legacy_address) == 45 and not legacy_address.startswith("wepo1q"):
        # Convert to new quantum format
        payload = legacy_address[5:44]  # Remove 'wepo1', take 39 chars
        return f"wepo1q{payload}"
    
    # Handle legacy 37-char addresses (already standard regular format)
    if len(legacy_address) == 37:
        return legacy_address  # Already in correct format
    
    # Return as-is if doesn't match expected patterns
    return legacy_address

def get_address_patterns() -> Dict[str, re.Pattern]:
    """
    Generate address validation regex patterns
    
    Returns:
        Dict of regex patterns for different address types
    """
    regular_format = ADDRESS_FORMATS["WEPO_REGULAR"]
    quantum_format = ADDRESS_FORMATS["WEPO_QUANTUM"]
    
    return {
        "regular": re.compile(f"^{re.escape(regular_format['prefix'])}[a-f0-9]{{{regular_format['payload_length']}}}$"),
        "quantum": re.compile(f"^{re.escape(quantum_format['prefix'])}[a-f0-9]{{{quantum_format['payload_length']}}}$"),
        "any": re.compile(r"^wepo1q?[a-f0-9]{32,39}$")
    }

def addresses_equal(address1: str, address2: str) -> bool:
    """
    Check if two addresses are equivalent (handles legacy formats)
    
    Args:
        address1: First address
        address2: Second address
        
    Returns:
        True if addresses are equivalent
    """
    if not address1 or not address2:
        return False
    
    std1 = standardize_address(address1)
    std2 = standardize_address(address2)
    
    return std1 == std2

def validate_address_batch(addresses: list) -> list:
    """
    Batch validate multiple addresses
    
    Args:
        addresses: List of addresses to validate
        
    Returns:
        List of validation results
    """
    results = []
    for address in addresses:
        validation = validate_wepo_address(address)
        results.append({
            "address": address,
            **validation
        })
    return results

def is_valid_wepo_address(address: str) -> bool:
    """
    Simple boolean check for address validity
    
    Args:
        address: Address to validate
        
    Returns:
        True if valid WEPO address
    """
    validation = validate_wepo_address(address)
    return validation["valid"]

# Legacy compatibility functions
def validate_btc_address(address: str) -> bool:
    """
    Legacy BTC address validation (placeholder for future BTC integration)
    
    Args:
        address: BTC address to validate
        
    Returns:
        True if valid BTC address format
    """
    # Simple validation for now - will be enhanced with proper BTC integration
    if not address or not isinstance(address, str):
        return False
    
    # Basic BTC address patterns
    if address.startswith('1') and 26 <= len(address) <= 35:
        return True
    if address.startswith('3') and 26 <= len(address) <= 35:
        return True
    if address.startswith('bc1') and 14 <= len(address) <= 74:
        return True
    
    return False

# Export main functions for backward compatibility
__all__ = [
    'ADDRESS_FORMATS',
    'generate_wepo_address',
    'validate_wepo_address',
    'get_address_type',
    'is_quantum_address',
    'is_regular_address',
    'format_address_for_display',
    'standardize_address',
    'get_address_patterns',
    'addresses_equal',
    'validate_address_batch',
    'is_valid_wepo_address',
    'validate_btc_address'
]
