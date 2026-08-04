#!/usr/bin/env python3
"""Strict, network-bound value-flow policy for isolated validator stake keys."""

from __future__ import annotations

import hashlib
import json
import re
import struct
from dataclasses import dataclass
from typing import Mapping


AUTHORIZATION_FORMAT = "wepo-validator-stake-authorization-v1"
SIGHASH_DOMAIN = b"WEPO_SIGHASH_V3\x00"
MAX_STAKE_FEE_ATOMIC = 10_000
MAX_STAKE_INPUTS = 64
MAX_ATOMIC_VALUE = 0x7FFFFFFFFFFFFFFF
UNSIGNED_PLACEHOLDER = "7369676e61747572655f706c616365686f6c646572"
MIN_STAKE_BY_NETWORK = {
    "mainnet": 1_000 * 100_000_000,
    "test": 100 * 100_000_000,
}


class StakePolicyRefusal(RuntimeError):
    """The requested transaction is outside the validator-key policy."""


@dataclass(frozen=True)
class StakeAuthorization:
    network: str
    validator_address: str
    operation: str
    stake_id: str
    unsigned_tx: dict[str, object]
    input_utxos: list[dict[str, object]]
    sighash: bytes
    outpoints: tuple[tuple[str, int], ...]

    @property
    def canonical_transaction_json(self) -> str:
        return _canonical_json(self.unsigned_tx)

    @property
    def canonical_utxos_json(self) -> str:
        return _canonical_json(self.input_utxos)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _plain_dict(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise StakePolicyRefusal(f"{name} must be an object")
    return dict(value)


def _require_exact_keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise StakePolicyRefusal(f"{name} schema is invalid")


def _require_hex(value: object, name: str, *, exact_bytes: int | None = None, max_bytes: int | None = None) -> str:
    if not isinstance(value, str) or len(value) % 2 or value.lower() != value:
        raise StakePolicyRefusal(f"{name} must be lowercase hexadecimal")
    if value and re.fullmatch(r"[0-9a-f]+", value) is None:
        raise StakePolicyRefusal(f"{name} must be lowercase hexadecimal")
    size = len(value) // 2
    if exact_bytes is not None and size != exact_bytes:
        raise StakePolicyRefusal(f"{name} has the wrong size")
    if max_bytes is not None and size > max_bytes:
        raise StakePolicyRefusal(f"{name} is oversized")
    return value


def _require_atomic(value: object, name: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0) or value > MAX_ATOMIC_VALUE:
        raise StakePolicyRefusal(f"{name} is invalid")
    return value


def _canonical_sighash(unsigned_tx: Mapping[str, object], network: str) -> bytes:
    inputs = unsigned_tx["inputs"]
    outputs = unsigned_tx["outputs"]
    assert isinstance(inputs, list) and isinstance(outputs, list)
    payload_document = {
        "version": unsigned_tx["version"],
        "lock_time": unsigned_tx["lock_time"],
        "timestamp": unsigned_tx["timestamp"],
        "fee": unsigned_tx["fee"],
        "tx_type": unsigned_tx["tx_type"],
        "inputs": [
            {
                "prev_txid": item["prev_txid"],
                "prev_vout": item["prev_vout"],
                "sequence": item["sequence"],
            }
            for item in inputs
        ],
        "outputs": [
            {
                "value": item["value"],
                "address": item["address"],
                "script_pubkey": item["script_pubkey"],
            }
            for item in outputs
        ],
        "shielded_bundle": None,
        "extra_data": unsigned_tx["extra_data"],
    }
    payload = _canonical_json(payload_document).encode("utf-8")
    network_bytes = network.encode("ascii", errors="strict")
    preimage = (
        SIGHASH_DOMAIN
        + struct.pack("<I", len(network_bytes))
        + network_bytes
        + struct.pack("<I", len(payload))
        + payload
    )
    return hashlib.sha256(preimage).digest()


def _validate_unsigned_inputs(raw_inputs: object) -> tuple[list[dict[str, object]], tuple[tuple[str, int], ...]]:
    if not isinstance(raw_inputs, list) or not 1 <= len(raw_inputs) <= MAX_STAKE_INPUTS:
        raise StakePolicyRefusal("stake transaction input count is invalid")
    normalized: list[dict[str, object]] = []
    outpoints: list[tuple[str, int]] = []
    expected_keys = {
        "prev_txid", "prev_vout", "script_sig", "sequence",
        "quantum_signature", "quantum_public_key", "signature_type",
    }
    for raw in raw_inputs:
        item = _plain_dict(raw, "stake transaction input")
        _require_exact_keys(item, expected_keys, "stake transaction input")
        txid = _require_hex(item["prev_txid"], "input transaction id", exact_bytes=32)
        vout = item["prev_vout"]
        if type(vout) is not int or not 0 <= vout <= 0xFFFFFFFF:
            raise StakePolicyRefusal("input output index is invalid")
        if item["sequence"] != 0xFFFFFFFF:
            raise StakePolicyRefusal("stake transaction input sequence is non-canonical")
        if item["script_sig"] != UNSIGNED_PLACEHOLDER:
            raise StakePolicyRefusal("stake transaction is not unsigned")
        if (
            item["signature_type"] != "ecdsa"
            or item["quantum_signature"] is not None
            or item["quantum_public_key"] is not None
        ):
            raise StakePolicyRefusal("stake transaction already contains authorization data")
        outpoint = (txid, vout)
        if outpoint in outpoints:
            raise StakePolicyRefusal("stake transaction repeats an input outpoint")
        outpoints.append(outpoint)
        normalized.append(item)
    return normalized, tuple(outpoints)


def _validate_outputs(raw_outputs: object, validator_address: str) -> list[dict[str, object]]:
    if not isinstance(raw_outputs, list) or not 1 <= len(raw_outputs) <= 2:
        raise StakePolicyRefusal("stake transaction output count is invalid")
    normalized: list[dict[str, object]] = []
    for raw in raw_outputs:
        item = _plain_dict(raw, "stake transaction output")
        _require_exact_keys(item, {"value", "address", "script_pubkey"}, "stake transaction output")
        _require_atomic(item["value"], "stake transaction output value", positive=True)
        if item["address"] != validator_address:
            raise StakePolicyRefusal("stake transaction sends value outside the validator address")
        _require_hex(item["script_pubkey"], "stake transaction output script", max_bytes=1024)
        normalized.append(item)
    return normalized


def _validate_input_utxos(
    raw_utxos: object,
    inputs: list[dict[str, object]],
    validator_address: str,
) -> list[dict[str, object]]:
    if not isinstance(raw_utxos, list) or len(raw_utxos) != len(inputs):
        raise StakePolicyRefusal("input UTXO context does not match the transaction")
    normalized: list[dict[str, object]] = []
    expected_keys = {"prev_txid", "prev_vout", "amount", "address", "script_pubkey"}
    for raw, tx_input in zip(raw_utxos, inputs):
        item = _plain_dict(raw, "input UTXO context")
        _require_exact_keys(item, expected_keys, "input UTXO context")
        txid = _require_hex(item["prev_txid"], "UTXO transaction id", exact_bytes=32)
        vout = item["prev_vout"]
        if txid != tx_input["prev_txid"] or vout != tx_input["prev_vout"]:
            raise StakePolicyRefusal("input UTXO context is out of order or mismatched")
        if type(vout) is not int or not 0 <= vout <= 0xFFFFFFFF:
            raise StakePolicyRefusal("UTXO output index is invalid")
        _require_atomic(item["amount"], "input UTXO amount", positive=True)
        if item["address"] != validator_address:
            raise StakePolicyRefusal("input UTXO is not owned by the validator address")
        _require_hex(item["script_pubkey"], "input UTXO script", max_bytes=1024)
        normalized.append(item)
    return normalized


def _is_spendable_funding_script(script_hex: str) -> bool:
    marker = bytes.fromhex(script_hex)
    return (
        marker in {
            b"genesis_output", b"coinbase_output", b"output_script",
            b"change_script", b"stake_unlock", b"masternode_unlock",
        }
        or marker.startswith(b"staker_fee_output:")
        or marker.startswith(b"masternode_fee_output:")
    )


def validate_stake_authorization(document: object, *, expected_network: str, validator_address: str) -> StakeAuthorization:
    authorization = _plain_dict(document, "stake authorization")
    _require_exact_keys(
        authorization,
        {"format", "network", "validator_address", "unsigned_tx", "input_utxos", "sighash"},
        "stake authorization",
    )
    if authorization["format"] != AUTHORIZATION_FORMAT:
        raise StakePolicyRefusal("stake authorization format is invalid")
    if authorization["network"] != expected_network or authorization["validator_address"] != validator_address:
        raise StakePolicyRefusal("stake authorization targets the wrong key or network")
    if expected_network not in MIN_STAKE_BY_NETWORK:
        raise StakePolicyRefusal("stake authorization network has no frozen policy")

    tx = _plain_dict(authorization["unsigned_tx"], "unsigned stake transaction")
    _require_exact_keys(
        tx,
        {
            "version", "lock_time", "fee", "tx_type", "timestamp", "extra_data",
            "privacy_proof", "ring_signature", "shielded_bundle", "inputs", "outputs",
        },
        "unsigned stake transaction",
    )
    if tx["version"] != 1 or tx["lock_time"] != 0:
        raise StakePolicyRefusal("stake transaction version or lock time is invalid")
    if type(tx["timestamp"]) is not int or not 0 < tx["timestamp"] <= MAX_ATOMIC_VALUE:
        raise StakePolicyRefusal("stake transaction timestamp is invalid")
    fee = _require_atomic(tx["fee"], "stake transaction fee")
    if fee > MAX_STAKE_FEE_ATOMIC:
        raise StakePolicyRefusal("stake transaction fee exceeds the signer ceiling")
    if tx["privacy_proof"] is not None or tx["ring_signature"] is not None or tx["shielded_bundle"] is not None:
        raise StakePolicyRefusal("stake transaction contains unsupported privacy data")

    inputs, outpoints = _validate_unsigned_inputs(tx["inputs"])
    outputs = _validate_outputs(tx["outputs"], validator_address)
    input_utxos = _validate_input_utxos(authorization["input_utxos"], inputs, validator_address)
    total_input = sum(int(item["amount"]) for item in input_utxos)
    total_output = sum(int(item["value"]) for item in outputs)
    if total_input - total_output != fee:
        raise StakePolicyRefusal("stake transaction UTXO context violates value conservation")

    extra = _plain_dict(tx["extra_data"], "stake transaction metadata")
    _require_exact_keys(extra, {"stake_id", "staker_address", "amount"}, "stake transaction metadata")
    stake_id = extra["stake_id"]
    if (
        not isinstance(stake_id, str)
        or len(stake_id) > 512
        or re.fullmatch(rf"stake_{re.escape(validator_address)}_[0-9]+", stake_id) is None
        or extra["staker_address"] != validator_address
    ):
        raise StakePolicyRefusal("stake transaction identity is invalid")
    principal = _require_atomic(extra["amount"], "stake principal", positive=True)

    operation = tx["tx_type"]
    lock_script = f"stake_lock:{stake_id}".encode("ascii").hex()
    if operation == "stake_create":
        if principal < MIN_STAKE_BY_NETWORK[expected_network]:
            raise StakePolicyRefusal("stake principal is below the signer minimum")
        if any(not _is_spendable_funding_script(str(item["script_pubkey"])) for item in input_utxos):
            raise StakePolicyRefusal("stake creation attempts to consume a protocol-locked or unknown UTXO")
        lock_outputs = [item for item in outputs if item["script_pubkey"] == lock_script]
        if len(lock_outputs) != 1 or lock_outputs[0]["value"] != principal:
            raise StakePolicyRefusal("stake creation lock output is invalid")
        change = [item for item in outputs if item is not lock_outputs[0]]
        if len(change) > 1 or (change and change[0]["script_pubkey"] != b"change_script".hex()):
            raise StakePolicyRefusal("stake creation change output is invalid")
    elif operation == "stake_deactivate":
        if len(inputs) != 1 or len(outputs) != 1:
            raise StakePolicyRefusal("stake withdrawal must have one input and one output")
        if input_utxos[0]["script_pubkey"] != lock_script:
            raise StakePolicyRefusal("stake withdrawal does not spend its named stake lock")
        if outputs[0]["script_pubkey"] != b"stake_unlock".hex():
            raise StakePolicyRefusal("stake withdrawal output is non-canonical")
        if principal != input_utxos[0]["amount"] or outputs[0]["value"] + fee != principal:
            raise StakePolicyRefusal("stake withdrawal does not return principal minus fee")
    else:
        raise StakePolicyRefusal("validator key may sign only stake create or deactivate transactions")

    sighash = _canonical_sighash(tx, expected_network)
    supplied_sighash = _require_hex(authorization["sighash"], "stake authorization sighash", exact_bytes=32)
    if bytes.fromhex(supplied_sighash) != sighash:
        raise StakePolicyRefusal("stake authorization sighash does not match its transaction")
    return StakeAuthorization(
        network=expected_network,
        validator_address=validator_address,
        operation=operation,
        stake_id=stake_id,
        unsigned_tx=tx,
        input_utxos=input_utxos,
        sighash=sighash,
        outpoints=outpoints,
    )
