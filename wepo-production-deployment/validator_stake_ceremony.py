#!/usr/bin/env python3
"""Prepare, sign, and submit isolated-key WEPO validator stake transactions.

The signer-only authorization step deliberately remains in
``wepo_validator_signer.py --authorize-stake-request`` and cannot be performed
by this node-side client.
"""

from __future__ import annotations

import argparse
import json
import contextlib
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

with contextlib.redirect_stdout(sys.stderr):
    from address_utils import generate_wepo_address  # noqa: E402
    from blockchain import Transaction  # noqa: E402
    from dilithium import verify_dilithium_signature  # noqa: E402
    from validator_signer import (  # noqa: E402
        SubprocessValidatorSigner,
        ValidatorSignerError,
        load_validator_signer_from_env,
    )


AUTHORIZATION_FORMAT = "wepo-validator-stake-authorization-v1"
MAX_HTTP_RESPONSE_BYTES = 2 * 1024 * 1024


class CeremonyError(RuntimeError):
    pass


def _post_json(base_url: str, path: str, document: object) -> dict:
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(document, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read(16 * 1024).decode("utf-8", errors="replace")
        raise CeremonyError(f"node rejected request with HTTP {exc.code}: {detail}") from exc
    except OSError as exc:
        raise CeremonyError("node request failed") from exc
    if len(raw) > MAX_HTTP_RESPONSE_BYTES:
        raise CeremonyError("node response exceeded the limit")
    try:
        result = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CeremonyError("node returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise CeremonyError("node returned a non-object response")
    return result


def _read_json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise CeremonyError(f"input is not a regular non-symlink file: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CeremonyError(f"unable to read {path}") from exc
    if not raw or len(raw) > MAX_HTTP_RESPONSE_BYTES:
        raise CeremonyError(f"input file size is invalid: {path}")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CeremonyError(f"input file is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CeremonyError(f"input JSON must be an object: {path}")
    return value


def _write_new_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise CeremonyError(f"refusing to overwrite output file: {path}") from exc
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())


def _authorization_from_response(response: dict) -> dict:
    authorization = response.get("validator_signer_authorization")
    if not isinstance(authorization, dict):
        raise CeremonyError("node did not return a validator signer authorization")
    if authorization.get("format") != AUTHORIZATION_FORMAT:
        raise CeremonyError("node returned an unsupported authorization format")
    if response.get("network") != authorization.get("network"):
        raise CeremonyError("node response network does not match its authorization")
    if response.get("sighash") != authorization.get("sighash"):
        raise CeremonyError("node response sighash does not match its authorization")
    return authorization


def _summary(authorization: dict) -> dict:
    tx = authorization.get("unsigned_tx") or {}
    extra = tx.get("extra_data") or {}
    return {
        "format": authorization.get("format"),
        "network": authorization.get("network"),
        "validator_address": authorization.get("validator_address"),
        "operation": tx.get("tx_type"),
        "stake_id": extra.get("stake_id"),
        "principal_atomic": extra.get("amount"),
        "fee_atomic": tx.get("fee"),
        "input_count": len(tx.get("inputs") or []),
        "output_count": len(tx.get("outputs") or []),
        "sighash": authorization.get("sighash"),
    }


def _prepare(args: argparse.Namespace) -> None:
    if args.command == "prepare-create":
        response = _post_json(
            args.node_url,
            "/api/stake",
            {
                "staker_address": args.validator_address,
                "amount": args.amount,
                "fee": args.fee,
            },
        )
    else:
        response = _post_json(
            args.node_url,
            "/api/stake/deactivate",
            {
                "stake_id": args.stake_id,
                "staker_address": args.validator_address,
                "fee": args.fee,
            },
        )
    authorization = _authorization_from_response(response)
    if authorization.get("validator_address") != args.validator_address:
        raise CeremonyError("node changed the requested validator address")
    _write_new_json(args.output, authorization)
    print(json.dumps({"ok": True, "output": str(args.output), **_summary(authorization)}, sort_keys=True))


def _load_signer(command_json: str | None) -> SubprocessValidatorSigner:
    if command_json:
        try:
            command = json.loads(command_json)
        except json.JSONDecodeError as exc:
            raise CeremonyError("--signer-command-json is invalid JSON") from exc
        if not isinstance(command, list):
            raise CeremonyError("--signer-command-json must be an argv array")
        return SubprocessValidatorSigner(command, timeout_seconds=15)
    try:
        signer = load_validator_signer_from_env()
    except ValidatorSignerError as exc:
        raise CeremonyError("configured validator signer is invalid") from exc
    if signer is None:
        raise CeremonyError("no validator signer command is configured")
    return signer


def _sign(args: argparse.Namespace) -> None:
    authorization = _read_json(args.authorization)
    if authorization.get("format") != AUTHORIZATION_FORMAT:
        raise CeremonyError("authorization format is invalid")
    network = authorization.get("network")
    address = authorization.get("validator_address")
    sighash = authorization.get("sighash")
    unsigned_tx = authorization.get("unsigned_tx")
    input_utxos = authorization.get("input_utxos")
    if not isinstance(network, str) or not isinstance(address, str) or not isinstance(sighash, str):
        raise CeremonyError("authorization identity fields are invalid")
    signer = _load_signer(args.signer_command_json)
    public_key = signer.get_public_key(address)
    if generate_wepo_address(public_key, address_type="quantum") != address:
        raise CeremonyError("configured signer public key does not own the validator address")
    try:
        signature = signer.sign_stake_transaction(
            address,
            unsigned_tx,
            input_utxos,
            network,
            sighash,
        )
    except ValidatorSignerError as exc:
        raise CeremonyError("isolated signer refused the stake transaction") from exc
    if not verify_dilithium_signature(bytes.fromhex(sighash), signature, public_key):
        raise CeremonyError("isolated signer returned an invalid signature")
    signed_tx = {
        **unsigned_tx,
        "inputs": [
            {
                **item,
                "script_sig": "",
                "signature_type": "dilithium",
                "quantum_public_key": public_key.hex(),
                "quantum_signature": signature.hex(),
            }
            for item in unsigned_tx["inputs"]
        ],
    }
    reconstructed = Transaction.from_dict(signed_tx)
    if reconstructed.get_canonical_sighash(network).hex() != sighash:
        raise CeremonyError("signed transaction changed the authorized sighash")
    _write_new_json(
        args.output,
        {
            "format": "wepo-validator-signed-stake-v1",
            "network": network,
            "validator_address": address,
            "sighash": sighash,
            "signed_tx": signed_tx,
            "expected_txid": reconstructed.calculate_txid(),
        },
    )
    print(json.dumps({"ok": True, "output": str(args.output), "sighash": sighash}, sort_keys=True))


def _submit(args: argparse.Namespace) -> None:
    signed = _read_json(args.signed_transaction)
    if signed.get("format") != "wepo-validator-signed-stake-v1":
        raise CeremonyError("signed stake file format is invalid")
    response = _post_json(
        args.node_url,
        "/api/transaction/send",
        {"signed_tx": signed.get("signed_tx")},
    )
    returned_txid = response.get("transaction_id") or response.get("tx_hash") or response.get("txid")
    if returned_txid != signed.get("expected_txid"):
        raise CeremonyError("node returned a transaction ID that differs from the signed file")
    print(json.dumps({"ok": True, "transaction_id": returned_txid, "response": response}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="WEPO isolated validator stake ceremony")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("prepare-create")
    create.add_argument("--node-url", required=True)
    create.add_argument("--validator-address", required=True)
    create.add_argument("--amount", required=True)
    create.add_argument("--fee", default="0.0001")
    create.add_argument("--output", required=True, type=Path)

    deactivate = subparsers.add_parser("prepare-deactivate")
    deactivate.add_argument("--node-url", required=True)
    deactivate.add_argument("--validator-address", required=True)
    deactivate.add_argument("--stake-id", required=True)
    deactivate.add_argument("--fee", default="0.0001")
    deactivate.add_argument("--output", required=True, type=Path)

    sign = subparsers.add_parser("sign")
    sign.add_argument("--authorization", required=True, type=Path)
    sign.add_argument("--output", required=True, type=Path)
    sign.add_argument("--signer-command-json")

    submit = subparsers.add_parser("submit")
    submit.add_argument("--node-url", required=True)
    submit.add_argument("--signed-transaction", required=True, type=Path)

    args = parser.parse_args()
    try:
        if args.command.startswith("prepare-"):
            _prepare(args)
        elif args.command == "sign":
            _sign(args)
        else:
            _submit(args)
        return 0
    except CeremonyError as exc:
        print(f"validator stake ceremony failed closed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
