"""
WEPO private-messaging blind relay — verification core (see MESSAGING_DESIGN.md).

The relay only ever stores opaque, end-to-end-encrypted envelopes; it cannot read
message content. Messaging uses a DEVICE-LOCAL messaging key (ML-KEM + ML-DSA),
independent of the wallet's spend/funds key, so messaging is click-and-use (no
password, works for any wallet). The security-critical server-side checks are:

  1. Key registration — a published messaging key bundle must be self-signed by the
     messaging ML-DSA key it registers (proves the registrant holds that key).
     Stored FIRST-WRITE-WINS per address: the first self-signed bundle is accepted
     (trust-on-first-use); re-publishing the SAME key is idempotent; replacing it
     with a DIFFERENT key requires a rotation signature by the CURRENTLY registered
     key (verify_key_rotation) — so an attacker cannot silently overwrite an in-use
     address's registration (no last-write-wins takeover/squat of an active inbox).
  2. Inbox fetch authorization — only the holder of the messaging key currently
     registered for an address (proven by a fresh signature) may fetch its inbox.

NOTE: this convenience path is claim-based — the relay does NOT prove the messaging
keys belong to the address's spend-key owner. First-write-wins narrows the exposure
to squatting an address that has NEVER registered (low impact: content stays E2E,
and the real owner overrides via the on-chain anchor). The TRUSTLESS path is the
on-chain key anchor (spend-key-bound consensus tx), which clients resolve first.
Content stays end-to-end encrypted either way. Messaging is gated pre-mainnet;
revisit before enabling. See MESSAGING_DESIGN.md.

These are pure functions so they can be unit-tested without Mongo/HTTP. The
signatures are ML-DSA-44, interoperable with the JS wallet (@noble).
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

MAX_ENVELOPE_BYTES = 64 * 1024   # reject oversized stored envelopes
FETCH_AUTH_MAX_SKEW = 120        # seconds a signed fetch/ack request stays valid


def _digest(text: str) -> bytes:
    return hashlib.sha256(text.encode()).digest()


def key_registry_digest(address: str, kem_pub_hex: str, sig_pub_hex: str) -> bytes:
    """Canonical bytes a user signs (with their messaging key) to publish keys."""
    return _digest(f"WEPO-MSGKEY-v1|{address}|{kem_pub_hex}|{sig_pub_hex}")


def fetch_auth_digest(address: str, ts) -> bytes:
    """Canonical bytes a user signs to authenticate an inbox fetch/ack."""
    return _digest(f"WEPO-MSGFETCH-v1|{address}|{ts}")


def key_rotation_digest(address: str, old_sig_pub_hex: str, kem_pub_hex: str,
                        new_sig_pub_hex: str) -> bytes:
    """Canonical bytes the CURRENTLY registered messaging key signs to authorize
    replacing its registration with a new (kem_pub, sig_pub) bundle."""
    return _digest(
        f"WEPO-MSGKEY-ROTATE-v1|{address}|{old_sig_pub_hex}|{kem_pub_hex}|{new_sig_pub_hex}"
    )


def verify_key_registration(address: str, kem_pub_hex: str, sig_pub_hex: str,
                            sig_hex: str) -> bool:
    """True iff the bundle is self-signed by the messaging key (sig_pub) it registers.

    Claim-based: proves the registrant holds the messaging secret for sig_pub, not
    that they own `address`'s spend key (see module note).
    """
    if not all([address, kem_pub_hex, sig_pub_hex, sig_hex]):
        return False
    try:
        return bool(verify_dilithium_signature(
            key_registry_digest(address, kem_pub_hex, sig_pub_hex),
            bytes.fromhex(sig_hex),
            bytes.fromhex(sig_pub_hex),
        ))
    except Exception:
        return False


def verify_key_rotation(address: str, old_sig_pub_hex: str, kem_pub_hex: str,
                        new_sig_pub_hex: str, rotation_sig_hex: str) -> bool:
    """True iff `rotation_sig_hex` authorizes rotating `address`'s registration to a
    new bundle, signed by the CURRENTLY registered messaging key (old_sig_pub_hex).

    Only the incumbent key-holder can authorize a key change, so an attacker who
    merely holds some other valid messaging key cannot overwrite an in-use address.
    """
    if not all([address, old_sig_pub_hex, kem_pub_hex, new_sig_pub_hex, rotation_sig_hex]):
        return False
    try:
        return bool(verify_dilithium_signature(
            key_rotation_digest(address, old_sig_pub_hex, kem_pub_hex, new_sig_pub_hex),
            bytes.fromhex(rotation_sig_hex),
            bytes.fromhex(old_sig_pub_hex),
        ))
    except Exception:
        return False


def registration_action(existing_kem_hex: Optional[str], existing_sig_hex: Optional[str],
                        address: str, kem_pub_hex: str, sig_pub_hex: str,
                        rotation_sig_hex: str = "") -> tuple:
    """Decide whether a key publish is allowed under first-write-wins + authorized
    rotation. PURE (no DB/HTTP) so the policy is unit-testable.

    The caller must have already verified the NEW bundle's self-signature
    (verify_key_registration). Returns (allowed: bool, reason: str) where reason is
    one of: "tofu" (first registration), "idempotent" (same key re-published),
    "rotation" (incumbent-authorized key change), or "conflict" (a different key
    tried to overwrite an in-use registration without a valid rotation signature).
    """
    if not existing_sig_hex:
        return True, "tofu"
    if existing_kem_hex == kem_pub_hex and existing_sig_hex == sig_pub_hex:
        return True, "idempotent"
    if verify_key_rotation(address, existing_sig_hex, kem_pub_hex, sig_pub_hex, rotation_sig_hex):
        return True, "rotation"
    return False, "conflict"


def verify_fetch_auth(address: str, registered_sig_pub_hex: str, sig_hex: str, ts,
                      now: Optional[int] = None) -> bool:
    """True iff a fresh request is signed by the messaging key currently registered
    for `address` (so only that inbox's key-holder can read it)."""
    now = int(time.time()) if now is None else int(now)
    try:
        if abs(now - int(ts)) > FETCH_AUTH_MAX_SKEW:
            return False
    except (ValueError, TypeError):
        return False
    if not registered_sig_pub_hex:
        return False
    try:
        return bool(verify_dilithium_signature(
            fetch_auth_digest(address, ts),
            bytes.fromhex(sig_hex),
            bytes.fromhex(registered_sig_pub_hex),
        ))
    except Exception:
        return False
