"""
WEPO private-messaging blind relay — verification core (see MESSAGING_DESIGN.md).

The relay only ever stores opaque, end-to-end-encrypted envelopes; it cannot read
message content. Messaging uses a DEVICE-LOCAL messaging key (ML-KEM + ML-DSA),
independent of the wallet's spend/funds key, so messaging is click-and-use (no
password, works for any wallet). The security-critical server-side checks are:

  1. Key registration — a published bundle must be BOTH (a) self-signed by the
     messaging ML-DSA key it registers (verify_key_registration — proves the
     registrant holds that inbox key) AND (b) owner-bound: signed by the address's
     SPEND key, whose public key hashes to the address (verify_owner_binding —
     proves the registrant OWNS the address). Because only the true owner can
     produce (b), nobody can front-run/squat or overwrite an address's messaging
     registration; the spend key is the authority and may set or rotate it freely
     (seamless across devices). (The legacy first-write-wins/rotation-signature
     helpers remain for reference/interop but are superseded by owner binding.)
  2. Inbox fetch authorization — only the holder of the messaging key currently
     registered for an address (proven by a fresh signature) may fetch its inbox.

OWNERSHIP BINDING (mandatory): every relay registration must additionally carry an
owner binding — a signature by the address's SPEND key (ML-DSA-44) over the bundle,
where the signing spend public key hashes to the address using the SAME derivation
consensus enforces for spends (generate_wepo_address / addresses_equal). This proves
the registrant owns the address, so a stranger cannot front-run / squat an address's
messaging keys (they cannot produce the owner's spend-key signature). The spend key
is the authority for the address: it may set or replace the registration freely, so
discovery is trustless on BOTH the relay path (owner-binding verified) and the
on-chain anchor path. Producing the owner binding needs the spend key, which the
wallet already unlocks at login — so publishing stays a silent, zero-fee, no-extra-
step background action; daily send/read still use only the device-local messaging
key. Content stays end-to-end encrypted regardless. See MESSAGING_DESIGN.md.

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
from address_utils import generate_wepo_address, addresses_equal  # noqa: E402

MAX_ENVELOPE_BYTES = 64 * 1024   # reject oversized stored envelopes
FETCH_AUTH_MAX_SKEW = 120        # seconds a signed fetch/ack request stays valid
ML_DSA44_PUB_HEX_LEN = 1312 * 2  # 2624 hex chars — NIST ML-DSA-44 public key


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


def key_owner_binding_digest(address: str, kem_pub_hex: str, sig_pub_hex: str) -> bytes:
    """Canonical bytes the address's SPEND key signs to authorize (own) this bundle.

    Signing this with the spend key, together with revealing the spend public key
    that hashes to `address`, proves the registrant owns the address — so nobody can
    register messaging keys for an address they do not control."""
    return _digest(f"WEPO-MSGKEY-OWNER-v1|{address}|{kem_pub_hex}|{sig_pub_hex}")


def verify_owner_binding(address: str, kem_pub_hex: str, sig_pub_hex: str,
                         owner_sig_pub_hex: str, owner_sig_hex: str) -> bool:
    """True iff the bundle is signed by the SPEND key that owns `address`.

    Two independent checks, both required:
      1. Address binding — `owner_sig_pub_hex` (an ML-DSA-44 spend public key) must
         hash to `address` under the exact derivation consensus uses for spends
         (generate_wepo_address(..., "quantum") + addresses_equal). This is what
         ties the signature to THIS address specifically.
      2. Signature — that spend key validly signs key_owner_binding_digest over the
         (kem_pub, sig_pub) being registered.
    An attacker who does not hold the address's spend key cannot satisfy both, so
    front-running/squatting an address's messaging registration is impossible.
    """
    if not all([address, kem_pub_hex, sig_pub_hex, owner_sig_pub_hex, owner_sig_hex]):
        return False
    try:
        if len(owner_sig_pub_hex) != ML_DSA44_PUB_HEX_LEN:
            return False
        derived_address = generate_wepo_address(owner_sig_pub_hex, address_type="quantum")
        if not addresses_equal(derived_address, address):
            return False
        return bool(verify_dilithium_signature(
            key_owner_binding_digest(address, kem_pub_hex, sig_pub_hex),
            bytes.fromhex(owner_sig_hex),
            bytes.fromhex(owner_sig_pub_hex),
        ))
    except Exception:
        return False


def verify_key_registration(address: str, kem_pub_hex: str, sig_pub_hex: str,
                            sig_hex: str) -> bool:
    """True iff the bundle is self-signed by the messaging key (sig_pub) it registers.

    Proves the registrant holds the messaging secret for sig_pub (so the registered
    inbox key is actually controlled). Address OWNERSHIP is proven separately by
    verify_owner_binding; the server requires BOTH.
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
