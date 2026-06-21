"""
WEPO private-messaging blind relay — verification core (see MESSAGING_DESIGN.md).

The relay only ever stores opaque, end-to-end-encrypted envelopes; it cannot read
message content. The security-critical server-side checks are:

  1. Key registry binding — a published messaging key bundle must be signed by the
     account's SPEND key, and the WEPO address must equal H(spend pubkey). This
     binds the (ML-KEM, ML-DSA) messaging public keys to the address trustlessly,
     so the relay cannot substitute keys for a man-in-the-middle.
  2. Inbox fetch authorization — only the address owner (proven by a fresh
     spend-key signature) may fetch envelopes addressed to it.

These are pure functions so they can be unit-tested without Mongo/HTTP. The
signatures are ML-DSA-44, interoperable with the JS wallet (@noble), verified by
the same primitive used for spend authorization.
"""
import hashlib
import os
import sys
import time
from typing import Optional

CORE_DIR = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
if os.path.abspath(CORE_DIR) not in sys.path:
    sys.path.append(os.path.abspath(CORE_DIR))

from dilithium import verify_dilithium_signature  # noqa: E402
from address_utils import generate_wepo_address  # noqa: E402

MAX_ENVELOPE_BYTES = 64 * 1024   # reject oversized stored envelopes
FETCH_AUTH_MAX_SKEW = 120        # seconds a signed fetch/ack request stays valid


def _digest(text: str) -> bytes:
    return hashlib.sha256(text.encode()).digest()


def key_registry_digest(address: str, kem_pub_hex: str, sig_pub_hex: str) -> bytes:
    """Canonical bytes a user signs (with their spend key) to publish messaging keys."""
    return _digest(f"WEPO-MSGKEY-v1|{address}|{kem_pub_hex}|{sig_pub_hex}")


def fetch_auth_digest(address: str, ts) -> bytes:
    """Canonical bytes a user signs to authenticate an inbox fetch/ack."""
    return _digest(f"WEPO-MSGFETCH-v1|{address}|{ts}")


def _address_matches_spend_key(address: str, spend_pub_hex: str) -> bool:
    try:
        spend_pub = bytes.fromhex(spend_pub_hex)
    except (ValueError, TypeError):
        return False
    try:
        return generate_wepo_address(spend_pub, address_type="quantum") == address
    except Exception:
        return False


def verify_key_binding(address: str, kem_pub_hex: str, sig_pub_hex: str,
                       spend_pub_hex: str, sig_hex: str) -> bool:
    """True iff the bundle is signed by the spend key AND address == H(spend pubkey)."""
    if not all([address, kem_pub_hex, sig_pub_hex, spend_pub_hex, sig_hex]):
        return False
    if not _address_matches_spend_key(address, spend_pub_hex):
        return False
    try:
        return bool(verify_dilithium_signature(
            key_registry_digest(address, kem_pub_hex, sig_pub_hex),
            bytes.fromhex(sig_hex),
            bytes.fromhex(spend_pub_hex),
        ))
    except Exception:
        return False


def verify_fetch_auth(address: str, spend_pub_hex: str, sig_hex: str, ts,
                      now: Optional[int] = None) -> bool:
    """True iff a fresh, spend-key-signed request proves ownership of `address`."""
    now = int(time.time()) if now is None else int(now)
    try:
        if abs(now - int(ts)) > FETCH_AUTH_MAX_SKEW:
            return False
    except (ValueError, TypeError):
        return False
    if not _address_matches_spend_key(address, spend_pub_hex):
        return False
    try:
        return bool(verify_dilithium_signature(
            fetch_auth_digest(address, ts),
            bytes.fromhex(sig_hex),
            bytes.fromhex(spend_pub_hex),
        ))
    except Exception:
        return False
