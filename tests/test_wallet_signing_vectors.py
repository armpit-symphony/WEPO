"""Cross-runtime acceptance for the committed wallet signing vector."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("WEPO_NETWORK_PROFILE", "test")
CORE = Path(__file__).resolve().parents[1] / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from address_utils import generate_wepo_address  # noqa: E402
from blockchain import (  # noqa: E402
    BlockHeader,
    COIN,
    Transaction,
    WepoBlockchain,
)

VECTOR_PATH = Path(__file__).parent / "vectors" / "wallet_signing_v3.json"


def _load_vector() -> dict:
    return json.loads(VECTOR_PATH.read_text(encoding="utf-8"))


def _signed_transaction(vector: dict) -> Transaction:
    raw = copy.deepcopy(vector["unsigned_tx"])
    for tx_input in raw["inputs"]:
        tx_input.update(
            {
                "signature_type": "dilithium",
                "quantum_public_key": vector["expected"]["owner_public_key"],
                "quantum_signature": vector["expected"][
                    "deterministic_signature"
                ],
                "script_sig": "",
            }
        )
    return Transaction.from_dict(raw)


def test_published_wallet_vector_matches_python_consensus():
    vector = _load_vector()
    assert vector["schema"] == "wepo-wallet-signing-vector-v3"
    assert vector["test_only"] is True

    public_key = bytes.fromhex(vector["expected"]["owner_public_key"])
    assert (
        generate_wepo_address(public_key, address_type="quantum")
        == vector["expected"]["owner_address"]
    )

    tx = _signed_transaction(vector)
    assert (
        tx.get_canonical_sighash(vector["network"]).hex()
        == vector["expected"]["canonical_sighash"]
    )

    unsigned_tx = Transaction.from_dict(vector["unsigned_tx"])
    unsigned = {
        "version": unsigned_tx.version,
        "lock_time": unsigned_tx.lock_time,
        "timestamp": unsigned_tx.timestamp,
        "fee": unsigned_tx.fee,
        "tx_type": unsigned_tx.tx_type,
        "inputs": [
            {
                "prev_txid": tx_input.prev_txid,
                "prev_vout": tx_input.prev_vout,
                "sequence": tx_input.sequence,
            }
            for tx_input in unsigned_tx.inputs
        ],
        "outputs": [
            {
                "value": output.value,
                "address": output.address,
                "script_pubkey": bytes(output.script_pubkey or b"").hex(),
            }
            for output in unsigned_tx.outputs
        ],
        "shielded_bundle": None,
        "extra_data": unsigned_tx.extra_data or {},
    }
    sighash_payload = json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    sighash_preimage = (
        b"WEPO_SIGHASH_V3\x00"
        + struct.pack("<I", len(vector["network"].encode("ascii")))
        + vector["network"].encode("ascii")
        + struct.pack("<I", len(sighash_payload))
        + sighash_payload
    )
    assert sighash_payload.hex() == vector["expected"]["sighash_payload_utf8_hex"]
    assert sighash_preimage.hex() == vector["expected"]["sighash_preimage_hex"]
    assert hashlib.sha256(sighash_preimage).hexdigest() == vector["expected"][
        "canonical_sighash"
    ]

    signed_payload = json.dumps(
        tx.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    txid_preimage = (
        b"WEPO_TXID_V2\x00"
        + struct.pack("<I", len(signed_payload))
        + signed_payload
    )
    assert (
        signed_payload.hex()
        == vector["expected"]["signed_transaction_payload_utf8_hex"]
    )
    assert txid_preimage.hex() == vector["expected"]["txid_preimage_hex"]
    assert tx.calculate_txid() == vector["expected"]["txid"]
    assert hashlib.sha256(txid_preimage).hexdigest() == vector["expected"]["txid"]
    assert tx.verify_quantum_signature(
        0, expected_address=vector["expected"]["owner_address"],
        network=vector["network"],
    )

    with tempfile.TemporaryDirectory(prefix="wepo-wallet-vector-") as data_dir:
        chain = WepoBlockchain(data_dir=data_dir, network_profile="test")
        try:
            chain.conn.execute(
                "INSERT INTO utxos "
                "(txid, vout, address, amount, script_pubkey, spent) "
                "VALUES (?, ?, ?, ?, ?, FALSE)",
                (
                    "a" * 64,
                    0,
                    vector["expected"]["owner_address"],
                    10 * COIN,
                    b"output_script",
                ),
            )
            chain.conn.commit()
            assert chain.validate_transaction(tx)
        finally:
            chain.conn.close()


def _block_header_from_vector(entry: dict) -> BlockHeader:
    fields = copy.deepcopy(entry["fields"])
    for name in ("validator_public_key", "validator_signature"):
        value = fields[name]
        fields[name] = bytes.fromhex(value) if value is not None else None
    return BlockHeader(**fields)


def test_published_block_header_vectors_match_python_consensus():
    vector = _load_vector()
    headers = vector["block_headers"]
    assert set(headers) == {"pow", "pos_serialization"}
    assert headers["pos_serialization"]["serialization_only"] is True

    for entry in headers.values():
        header = _block_header_from_vector(entry)
        expected = entry["expected"]
        canonical = header.canonical_bytes()

        assert canonical.hex() == expected["canonical_bytes_hex"]
        assert (
            header.canonical_bytes(include_validator_signature=False).hex()
            == expected["signing_bytes_hex"]
        )
        assert header.calculate_hash() == expected["block_hash"]
        assert hashlib.sha256(canonical).hexdigest() == expected["block_hash"]

    pos_header = _block_header_from_vector(headers["pos_serialization"])
    original_signing_bytes = pos_header.canonical_bytes(
        include_validator_signature=False
    )
    original_block_hash = pos_header.calculate_hash()
    pos_header.validator_signature = b"tampered"

    assert (
        pos_header.canonical_bytes(include_validator_signature=False)
        == original_signing_bytes
    )
    assert pos_header.calculate_hash() != original_block_hash
