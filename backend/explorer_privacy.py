"""
Block-explorer privacy projection — pure, unit-testable core.

The explorer surfaces only data already public on-chain and must NEVER weaken
privacy. Transparent transactions render in full (the base UTXO layer is
auditable by design); shielded "Ghost" transactions expose only that a valid
transaction occurred — amounts and parties stay cryptographically hidden. RWA
creation and messaging-key anchors publish safe commitments by design.

Kept separate from server.py (HTTP/Mongo) so the redaction policy can be tested
in isolation. See WEPO_WHITEPAPER.md sections 2, 9 and 11.
"""
from typing import Optional

SHIELDED_NOTE = (
    "Shielded (Ghost) transaction — amounts and parties are cryptographically "
    "hidden; validity is proven on-chain."
)


def tx_is_coinbase(tx: dict) -> bool:
    """A coinbase has a single input whose prev_txid is all zeros."""
    inputs = tx.get("inputs") or []
    if len(inputs) != 1:
        return False
    prev = str(inputs[0].get("prev_txid") or "")
    return bool(prev) and set(prev) <= {"0"}


def sanitize_tx(tx: Optional[dict]) -> dict:
    """Privacy-aware projection of a node transaction summary.

    Transparent transfers pass through (already public); shielded transactions
    have amounts/addresses stripped, keeping only what the chain reveals. A
    transaction counts as shielded when it carries a privacy proof or a ring
    signature — the two consensus-level markers of the shielded path.
    """
    if not isinstance(tx, dict):
        return {}
    shielded = bool(tx.get("privacy_proof") or tx.get("ring_signature"))
    tx_type = tx.get("tx_type", "transfer")
    view = {
        "txid": tx.get("txid"),
        "tx_type": tx_type,
        "fee": tx.get("fee"),
        "timestamp": tx.get("timestamp"),
        "block_height": tx.get("block_height"),
        "confirmations": tx.get("confirmations", 0),
        "coinbase": tx_is_coinbase(tx),
        "shielded": shielded,
    }
    if shielded:
        # Reveal only the shape (counts), never amounts or addresses.
        view["inputs"] = [{"shielded": True} for _ in (tx.get("inputs") or [])]
        view["outputs"] = [{"shielded": True} for _ in (tx.get("outputs") or [])]
        view["note"] = SHIELDED_NOTE
        return view

    view["inputs"] = tx.get("inputs") or []
    view["outputs"] = tx.get("outputs") or []
    extra = tx.get("extra_data") or {}
    if tx_type == "rwa_create":
        view["asset"] = {
            "asset_id": extra.get("asset_id"),
            "name": extra.get("name"),
            "asset_type": extra.get("asset_type") or extra.get("type"),
            "asset_hash": extra.get("asset_hash"),
        }
    elif tx_type == "key_register":
        view["messaging_key_anchor"] = {
            "owner_address": extra.get("owner_address"),
            "note": "On-chain messaging-key anchor (public keys only).",
        }
    return view
